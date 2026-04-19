#!/usr/bin/env python3
"""
ArtNet protocol implementation for ESP32 LED Matrix

ArtNet is a protocol for transmitting DMX512 data over UDP.
Standard port: 6454

Usage:
    python artnet.py --discover fill 128        # Auto-discover displays
    python artnet.py --ip 192.168.1.100 fill 128
    python artnet.py --ip 192.168.1.100 clear
    python artnet.py --ip 192.168.1.100 pixels -p 8 8 255
"""

import argparse
import json
import logging
import socket
import time

try:
    import websocket as ws_client
except ImportError:
    ws_client = None

try:
    from discover import discover_displays
except ImportError:
    discover_displays = None

logger: logging.Logger = logging.getLogger(__name__)

# ArtNet Protocol constants
ARTNET_PORT = 6454
ARTNET_MAGIC = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000
ARTNET_PROTOCOL_VERSION = 14

# Display constants
DISPLAY_WIDTH = 16
DISPLAY_HEIGHT = 16
DISPLAY_PIXELS = DISPLAY_WIDTH * DISPLAY_HEIGHT


def create_artdmx_packet(
    data: bytes | bytearray,
    universe: int = 0,
    sequence: int = 0,
    physical: int = 0,
) -> bytearray:
    """Create an Art-DMX packet

    Args:
        data: DMX channel data (up to 512 bytes)
        universe: DMX universe (0-32767)
        sequence: Sequence number (0-255, 0 disables sequencing)
        physical: Physical input port (0-3)

    Returns:
        Complete Art-DMX packet ready to send
    """
    packet = bytearray()

    # Art-Net magic (8 bytes)
    packet.extend(ARTNET_MAGIC)

    # Opcode (2 bytes, little-endian)
    packet.append(ARTNET_OPCODE_DMX & 0xFF)
    packet.append((ARTNET_OPCODE_DMX >> 8) & 0xFF)

    # Protocol version (2 bytes, big-endian)
    packet.append((ARTNET_PROTOCOL_VERSION >> 8) & 0xFF)
    packet.append(ARTNET_PROTOCOL_VERSION & 0xFF)

    # Sequence (1 byte)
    packet.append(sequence & 0xFF)

    # Physical (1 byte)
    packet.append(physical & 0x03)

    # Universe (2 bytes, little-endian)
    packet.append(universe & 0xFF)
    packet.append((universe >> 8) & 0xFF)

    # Length (2 bytes, big-endian) - must be even, 2-512
    length = len(data)
    if length % 2 == 1:
        length += 1
    length = max(2, min(512, length))
    packet.append((length >> 8) & 0xFF)
    packet.append(length & 0xFF)

    # Data
    packet.extend(data)
    # Pad to even length if needed
    if len(data) % 2 == 1:
        packet.append(0)

    return packet


def create_packet(
    pixels: list[tuple[int, int, int]] | None = None,
    universe: int = 0,
    sequence: int = 0,
) -> bytearray:
    """Create an Art-DMX packet for the LED matrix

    Args:
        pixels: List of (x, y, brightness) tuples (brightness 0-255)
        universe: DMX universe
        sequence: Packet sequence number

    Returns:
        Complete Art-DMX packet
    """
    # Initialize all pixels to 0
    data = bytearray(DISPLAY_PIXELS)

    # Set specified pixels
    if pixels:
        for x, y, brightness in pixels:
            if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
                index = y * DISPLAY_WIDTH + x
                data[index] = min(255, max(0, brightness))

    return create_artdmx_packet(data, universe=universe, sequence=sequence)


def create_packet_from_buffer(
    buffer: bytearray,
    universe: int = 0,
    sequence: int = 0,
) -> bytearray:
    """Create an Art-DMX packet from a pre-filled buffer

    Args:
        buffer: 256 bytes, one per pixel (values 0-255)
        universe: DMX universe
        sequence: Packet sequence number

    Returns:
        Complete Art-DMX packet
    """
    return create_artdmx_packet(buffer, universe=universe, sequence=sequence)


class ArtNetClient:
    """ArtNet client for sending DMX data to displays"""

    def __init__(self, displays: list[str], port: int = ARTNET_PORT):
        """
        Args:
            displays: List of IP addresses
            port: UDP port (default 6454)
        """
        self.displays = displays
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(True)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        self._addrs = [(ip, port) for ip in displays]
        self._sequence = 0

    def close(self) -> None:
        """Close the socket"""
        self.sock.close()

    def send_frame(self, buffers: list[bytearray], universe: int = 0) -> None:
        """Send frames to displays

        Args:
            buffers: List of 256-byte grayscale buffers, one per display
            universe: DMX universe
        """
        for addr, buf in zip(self._addrs, buffers):
            packet = create_packet_from_buffer(buf, universe=universe, sequence=self._sequence)
            self.sock.sendto(packet, addr)
        self._sequence = (self._sequence + 1) & 0xFF

    def __enter__(self) -> "ArtNetClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def send_artnet_packet(ip: str, port: int, packet: bytearray) -> None:
    """Send an ArtNet packet to the specified IP and port"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (ip, port))
        logger.info(f"Sent ArtNet packet to {ip}:{port}")
        logger.info(f"Packet size: {len(packet)} bytes")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        sock.close()


def switch_to_artnet_plugin(ip: str, timeout: float = 5.0, verbose: bool = True) -> bool:
    """Switch display to ArtNet plugin via WebSocket

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

                artnet_plugin = None
                for p in plugins:
                    if p.get("name") == "ArtNet":
                        artnet_plugin = p
                        break

                if artnet_plugin is None:
                    if verbose:
                        print(f"Warning: ArtNet plugin not found on {ip}")
                    ws.close()
                    return False

                artnet_id = artnet_plugin["id"]

                if current_plugin == artnet_id:
                    if verbose:
                        print(f"  {ip}: Already on ArtNet (ID: {artnet_id})")
                    ws.close()
                    return True

                if verbose:
                    print(f"  {ip}: Switching to ArtNet (ID: {artnet_id})...")
                ws.send(json.dumps({"event": "plugin", "plugin": artnet_id}))
                time.sleep(1.0)  # Wait for plugin switch animation
                ws.close()
                return True

    except Exception as e:
        if verbose:
            print(f"Warning: Could not switch {ip}: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Send ArtNet packets to control LED matrix")
    parser.add_argument("--ip", type=str, default=None, help="IP address of the display")
    parser.add_argument("--discover", action="store_true", help="Auto-discover displays on network")
    parser.add_argument("--port", type=int, default=ARTNET_PORT, help="UDP port")
    parser.add_argument("--universe", type=int, default=0, help="DMX universe")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("clear", help="Clear all pixels")

    fill_parser = subparsers.add_parser("fill", help="Fill all pixels with specified brightness")
    fill_parser.add_argument("brightness", type=int, help="Brightness level (0-255)")

    pixels_parser = subparsers.add_parser("pixels", help="Set individual pixel brightness")
    pixels_parser.add_argument(
        "-p", "--pixel",
        nargs=3, type=int, action="append",
        metavar=("X", "Y", "BRIGHTNESS"),
        help="Set pixel at X,Y to brightness",
    )

    test_parser = subparsers.add_parser("test", help="Run test animation")
    test_parser.add_argument("--fps", type=int, default=30, help="Frames per second")
    test_parser.add_argument("--duration", type=float, default=10, help="Duration in seconds")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO if args.verbose else logging.WARNING
    )

    # Get display IP
    if args.discover:
        if discover_displays is None:
            print("Error: discover module not available")
            return
        print("Discovering displays...")
        discovered = discover_displays(protocol="artnet")
        if not discovered:
            # Fall back to DDP discovery (same displays support both)
            discovered = discover_displays(protocol="ddp")
        if discovered:
            display_ip = discovered[0]
            print(f"  Found: {display_ip}")
        else:
            print("  No displays found")
            return
    elif args.ip:
        display_ip = args.ip
    else:
        display_ip = "192.168.178.50"  # Default fallback

    pixels: list[tuple[int, int, int]] = []

    if args.command == "fill":
        brightness = max(0, min(255, args.brightness))
        pixels = [(x, y, brightness) for x in range(16) for y in range(16)]

    elif args.command == "pixels" and args.pixel:
        for x, y, brightness in args.pixel:
            if 0 <= x < 16 and 0 <= y < 16:
                pixels.append((x, y, max(0, min(255, brightness))))

    elif args.command == "test":
        # Switch to ArtNet plugin first
        print(f"Switching to ArtNet plugin on {display_ip}...")
        switch_to_artnet_plugin(display_ip)

        print(f"Running test animation at {args.fps} FPS for {args.duration}s...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        frame_time = 1.0 / args.fps
        frames = 0
        start = time.time()
        sequence = 0

        try:
            while time.time() - start < args.duration:
                frame_start = time.time()

                # Create a simple moving bar animation
                buffer = bytearray(256)
                bar_pos = frames % 16
                for y in range(16):
                    for x in range(16):
                        if x == bar_pos:
                            buffer[y * 16 + x] = 255

                packet = create_packet_from_buffer(buffer, universe=args.universe, sequence=sequence)
                sock.sendto(packet, (display_ip, args.port))

                frames += 1
                sequence = (sequence + 1) & 0xFF

                # Frame timing
                elapsed = time.time() - frame_start
                if elapsed < frame_time:
                    time.sleep(frame_time - elapsed)

        except KeyboardInterrupt:
            pass
        finally:
            sock.close()

        actual_fps = frames / (time.time() - start)
        print(f"Sent {frames} frames at {actual_fps:.1f} FPS")
        return

    elif args.command == "clear":
        pass  # pixels stays empty

    else:
        parser.print_help()
        return

    packet = create_packet(pixels, universe=args.universe)
    send_artnet_packet(display_ip, args.port, packet)


if __name__ == "__main__":
    main()
