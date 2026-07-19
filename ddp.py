#!/usr/bin/env python3

import json
import logging
import socket
import argparse
import time

try:
    import websocket as ws_client
except ImportError:
    ws_client = None

logger: logging.Logger = logging.getLogger(__name__)

# DDP Protocol constants
DDP_PORT = 4048
DDP_HEADER_SIZE = 10
DDP_FLAG_PUSH = 0x01  # Render frame immediately
DDP_FLAG_QUERY = 0x02
DDP_FLAG_REPLY = 0x04
DDP_FLAG_STORAGE = 0x08
DDP_FLAG_TIME = 0x10
DDP_VER1 = 0x40  # Version 1 base flag

# Display constants
DISPLAY_WIDTH = 16
DISPLAY_HEIGHT = 16
DISPLAY_PIXELS = DISPLAY_WIDTH * DISPLAY_HEIGHT
GRAYSCALE_LEVELS = 16  # Display supports 4-bit grayscale (0-15), but we send 0-255

# Data type constants
DDP_TYPE_RGB = 0x01  # 3 bytes per pixel (legacy)
DDP_TYPE_GRAYSCALE = 0x02  # 1 byte per pixel (0-255, quantized by firmware)

# Pre-allocated buffers for performance
_HEADER_PUSH = bytearray([DDP_VER1 | DDP_FLAG_PUSH, 0, 0, DDP_TYPE_GRAYSCALE, 0, 0, 0, 0, 1, 0])
_HEADER_NO_PUSH = bytearray([DDP_VER1, 0, 0, DDP_TYPE_GRAYSCALE, 0, 0, 0, 0, 1, 0])
_SYNC_PACKET = bytearray([DDP_VER1 | DDP_FLAG_PUSH, 0, 0, DDP_TYPE_GRAYSCALE, 0, 0, 0, 0, 0, 0])


def create_packet(
    pixels: list[tuple[int, int, int]] | None = None, push: bool = True
) -> bytearray:
    """Create a DDP packet with specified pixels or all off

    Args:
        pixels: List of (x, y, brightness) tuples (brightness 0-255)
        push: If True, display renders immediately. If False, data is buffered.
    """
    # Use pre-allocated header
    packet = bytearray(_HEADER_PUSH if push else _HEADER_NO_PUSH)

    # Initialize all pixels to 0 (1 byte per pixel for grayscale)
    data = bytearray(DISPLAY_PIXELS)

    # Set specified pixels
    if pixels:
        for x, y, brightness in pixels:
            if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
                index = y * DISPLAY_WIDTH + x
                data[index] = min(255, max(0, brightness))

    packet.extend(data)
    return packet


def create_packet_from_buffer(buffer: bytearray, push: bool = True) -> bytearray:
    """Create a DDP packet from a pre-filled 256-byte grayscale buffer

    Args:
        buffer: 256 bytes, one per pixel (values 0-255)
        push: If True, display renders immediately
    """
    packet = bytearray(_HEADER_PUSH if push else _HEADER_NO_PUSH)
    packet.extend(buffer)
    return packet


def create_sync_packet() -> bytearray:
    """Create a sync packet (push flag only, no data) to trigger rendering"""
    return bytearray(_SYNC_PACKET)


class DDPClient:
    """DDP client with support for synchronized multi-display rendering"""

    def __init__(self, displays: list[str], port: int = DDP_PORT):
        """
        Args:
            displays: List of IP addresses
            port: UDP port (default 4048)
        """
        self.displays = displays
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Use blocking socket for reliable delivery
        self.sock.setblocking(True)
        # Increase send buffer size
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        # Pre-resolve addresses
        self._addrs = [(ip, port) for ip in displays]
        # Cache sync packet
        self._sync_packet = create_sync_packet()

    def close(self) -> None:
        """Close the socket"""
        self.sock.close()

    def send_frame(self, packets: list[bytearray]) -> None:
        """Send frames to displays with immediate render

        Args:
            packets: List of packets, one per display
        """
        for addr, packet in zip(self._addrs, packets):
            self.sock.sendto(packet, addr)

    def send_frame_sync(self, packets: list[bytearray]) -> None:
        """Send frames to multiple displays with synchronized rendering

        Args:
            packets: List of packets (without push flag), one per display
        """
        # 1. Send pixel data to all displays (buffered)
        for addr, packet in zip(self._addrs, packets):
            self.sock.sendto(packet, addr)

        # 2. Send sync packet to trigger simultaneous render
        for addr in self._addrs:
            self.sock.sendto(self._sync_packet, addr)

    def send_buffer_sync(self, buffers: list[bytearray]) -> None:
        """Send pre-filled buffers to displays with sync

        Args:
            buffers: List of 256-byte grayscale buffers, one per display
        """
        for addr, buf in zip(self._addrs, buffers):
            packet = bytearray(_HEADER_NO_PUSH)
            packet.extend(buf)
            self.sock.sendto(packet, addr)

        for addr in self._addrs:
            self.sock.sendto(self._sync_packet, addr)

    def __enter__(self) -> "DDPClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def send_ddp_packet(ip: str, port: int, packet: bytearray) -> None:
    """Send a DDP packet to the specified IP and port"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (ip, port))
        logger.info(f"Sent DDP packet to {ip}:{port}")
        logger.info(f"Packet size: {len(packet)} bytes")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        sock.close()


def switch_to_ddp_plugin(ip: str, timeout: float = 5.0, verbose: bool = True) -> bool:
    """Switch display to DDP plugin via WebSocket

    Args:
        ip: Display IP address
        timeout: WebSocket connection timeout
        verbose: Print status messages

    Returns:
        True if successful, False otherwise
    """
    if ws_client is None:
        if verbose:
            print("Warning: websocket-client not installed, cannot auto-switch plugin")
            print("Install with: pip install websocket-client")
        return False

    try:
        ws = ws_client.create_connection(f"ws://{ip}/ws", timeout=timeout)

        while True:
            result = ws.recv()
            data = json.loads(result)

            if data.get("event") == "info":
                plugins = data.get("plugins", [])
                current_plugin = data.get("plugin", -1)

                ddp_plugin = None
                for p in plugins:
                    if p.get("name") == "DDP":
                        ddp_plugin = p
                        break

                if ddp_plugin is None:
                    if verbose:
                        print(f"Warning: DDP plugin not found on {ip}")
                    ws.close()
                    return False

                ddp_id = ddp_plugin["id"]

                if current_plugin == ddp_id:
                    if verbose:
                        print(f"  {ip}: Already on DDP (ID: {ddp_id})")
                    ws.close()
                    return True

                if verbose:
                    print(f"  {ip}: Switching to DDP (ID: {ddp_id})...")
                ws.send(json.dumps({"event": "plugin", "plugin": ddp_id}))
                time.sleep(1.0)  # Wait for plugin switch animation
                ws.close()
                return True

    except Exception as e:
        if verbose:
            print(f"Warning: Could not switch {ip}: {e}")
        return False


def discover_displays_legacy(timeout: float = 2.0, subnet: str = None) -> list[str]:
    """Discover DDP displays on the network (legacy subnet scan method)

    Args:
        timeout: Discovery timeout in seconds
        subnet: Subnet to scan (e.g., "192.168.1.0/24"), auto-detected if None

    Returns:
        List of discovered display IP addresses
    """
    import threading
    import urllib.request

    displays = []
    found_lock = threading.Lock()

    # Determine subnet to scan
    if subnet is None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            parts = local_ip.split(".")
            subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        except:
            subnet = "192.168.1.0/24"

    # Parse subnet
    if "/" in subnet:
        base_ip, prefix = subnet.split("/")
        prefix = int(prefix)
    else:
        base_ip = subnet
        prefix = 24

    base_parts = [int(p) for p in base_ip.split(".")]
    base_int = (base_parts[0] << 24) | (base_parts[1] << 16) | (base_parts[2] << 8) | base_parts[3]
    num_hosts = min(2 ** (32 - prefix) - 2, 254)
    start_ip = (base_int & (0xFFFFFFFF << (32 - prefix))) + 1

    def check_host(ip_int: int):
        ip = f"{(ip_int >> 24) & 0xFF}.{(ip_int >> 16) & 0xFF}.{(ip_int >> 8) & 0xFF}.{ip_int & 0xFF}"
        try:
            # Check HTTP API to verify it's our display
            url = f"http://{ip}/api/info"
            req = urllib.request.Request(url, headers={"User-Agent": "DDP-Discovery"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read().decode()
                if "freeHeap" in data or "plugin" in data:
                    with found_lock:
                        displays.append(ip)
        except:
            pass

    # Scan in parallel
    threads = []
    for i in range(num_hosts):
        ip_int = start_ip + i
        t = threading.Thread(target=check_host, args=(ip_int,))
        t.daemon = True
        t.start()
        threads.append(t)

        if len(threads) >= 50:
            for t in threads:
                t.join(timeout=timeout + 0.5)
            threads = []

    for t in threads:
        t.join(timeout=timeout + 0.5)

    return sorted(displays)


# Re-export discover_displays from discover module if available
try:
    from discover import discover_displays
except ImportError:
    # Fall back to legacy method
    discover_displays = discover_displays_legacy


def create_arg_parser() -> argparse.ArgumentParser:
    # Use parent parser for common arguments
    parent_parser = argparse.ArgumentParser(
        description="The parent parser", add_help=False
    )

    parent_parser.add_argument(
        "--ip", type=str, default=None, help="IP address of the display"
    )
    parent_parser.add_argument(
        "--discover", action="store_true", help="Auto-discover displays on network"
    )
    parent_parser.add_argument("--port", type=int, default=4048, help="UDP port")
    parent_parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug logging"
    )
    parent_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    # Main parser with subcommands
    parser = argparse.ArgumentParser(
        description="Send DDP packets to control LED matrix", parents=[parent_parser]
    )

    subparsers = parser.add_subparsers(help="help for subcommand", dest="subcommand")

    subparsers.add_parser("clear", help="Clear all pixels", parents=[parent_parser])

    fill_parser: argparse.ArgumentParser = subparsers.add_parser(
        "fill",
        help="Fill all pixels with specified brightness",
        parents=[parent_parser],
    )
    fill_parser.add_argument(
        "brightness",
        type=int,
        metavar="BRIGHTNESS",
        choices=range(0, 256),
        help="Brightness level (0-255)",
    )

    pixels_parser: argparse.ArgumentParser = subparsers.add_parser(
        "pixels", help="Set individual pixel brightness", parents=[parent_parser]
    )
    pixels_parser.add_argument(
        "-p",
        "--pixel",
        nargs=3,
        type=int,
        action="append",
        metavar=("X", "Y", "BRIGHTNESS"),
        help="Set pixel at X,Y to brightness (can be used multiple times)",
    )

    # Deprecated arguments for backward compatibility
    parser.add_argument(
        "--clear", action="store_true", help="Clear all pixels", deprecated=True
    )
    parser.add_argument(
        "--fill",
        type=int,
        metavar="BRIGHTNESS",
        help="Fill all pixels with specified brightness (0-255)",
        deprecated=True,
    )
    parser.add_argument(
        "-p",
        "--pixel",
        nargs=3,
        type=int,
        action="append",
        metavar=("X", "Y", "BRIGHTNESS"),
        help="Set pixel at X,Y to brightness (can be used multiple times)",
        deprecated=True,
    )

    return parser


def main() -> None:
    parser: argparse.ArgumentParser = create_arg_parser()
    args: argparse.Namespace = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG
        if args.debug
        else logging.INFO
        if args.verbose
        else logging.WARNING
    )

    # Get display IP
    if args.discover:
        print("Discovering displays...")
        discovered = discover_displays(protocol="ddp") if callable(discover_displays) else discover_displays_legacy()
        if discovered:
            display_ip = discovered[0] if isinstance(discovered[0], str) else discovered[0]
            print(f"  Found: {display_ip}")
        else:
            print("  No displays found, using default")
            display_ip = "192.168.178.50"
    elif args.ip:
        display_ip = args.ip
    else:
        display_ip = "192.168.178.50"

    pixels: list[tuple[int, int, int]] = []

    # Validate fill brightness
    if args.subcommand == "fill" or args.fill is not None:
        if args.subcommand == "fill":
            fill_brightness: int = args.brightness
        else:
            fill_brightness: int = args.fill

        if not 0 <= fill_brightness <= 255:
            parser.error("Fill brightness must be between 0 and 255")

        logger.info(f"Filling all pixels with brightness {fill_brightness}")
        pixels = [(x, y, fill_brightness) for x in range(16) for y in range(16)]

    # Validate pixel coordinates and brightness
    if args.subcommand == "pixels" or args.pixel is not None:
        for x, y, brightness in args.pixel:
            if not (0 <= x < 16 and 0 <= y < 16):
                parser.error(f"Invalid coordinates: {x},{y} (must be 0-15)")

            if not (0 <= brightness <= 255):
                parser.error(f"Invalid brightness: {brightness} (must be 0-255)")

            logger.info(f"Setting pixel ({x},{y}) to brightness {brightness}")
            pixels.append((x, y, brightness))

    if args.subcommand == "clear" or args.clear:
        logger.info("Clearing all pixels")

    packet: bytearray = create_packet(pixels)
    send_ddp_packet(display_ip, args.port, packet)

    return


if __name__ == "__main__":
    main()
