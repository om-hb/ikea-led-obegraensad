#!/usr/bin/env python3
"""
Network discovery for LED matrix displays (DDP and ArtNet)

Methods:
    1. mDNS/Bonjour discovery (requires zeroconf)
    2. UDP broadcast scan on DDP/ArtNet ports
    3. Sequential IP scan (fallback)

Usage:
    python discover.py              # Auto-discover displays
    python discover.py --timeout 5  # Longer timeout
    python discover.py --subnet 192.168.1.0/24  # Scan specific subnet
    python discover.py --protocol ddp    # Only DDP displays
    python discover.py --protocol artnet # Only ArtNet displays
"""

import argparse
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

# Try to import zeroconf for mDNS discovery
try:
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

DDP_PORT = 4048
ARTNET_PORT = 6454

DDP_QUERY_PACKET = bytes([
    0x42,  # Version 1 + Query flag
    0x00,  # Sequence
    0x00,  # Data type
    0x00,  # Data type (cont)
    0x00, 0x00, 0x00, 0x00,  # Offset (4 bytes)
    0x00, 0x00,  # Length (0 for query)
])


@dataclass
class Display:
    ip: str
    port: int = DDP_PORT
    name: str = ""
    method: str = ""  # How it was discovered
    protocol: str = "ddp"  # ddp or artnet

    def __str__(self) -> str:
        if self.name:
            return f"{self.name} ({self.ip}:{self.port}) [{self.protocol}]"
        return f"{self.ip}:{self.port} [{self.protocol}]"


class MDNSListener(ServiceListener):
    """Listener for mDNS service discovery"""

    def __init__(self):
        self.displays: list[Display] = []

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info:
            for addr in info.parsed_addresses():
                # Extract display name from service name (remove service type suffix)
                display_name = name
                for suffix in ["._ddp._udp.local.", "._artnet._udp.local.", "._ledmatrix._tcp.local.", "._http._tcp.local."]:
                    display_name = display_name.replace(suffix, "")

                # Determine protocol and port from service type
                if "_artnet._udp" in type_:
                    protocol = "artnet"
                    port = ARTNET_PORT
                else:
                    protocol = "ddp"
                    port = DDP_PORT

                # Avoid duplicates by IP+protocol
                key = f"{addr}:{protocol}"
                if key not in [f"{d.ip}:{d.protocol}" for d in self.displays]:
                    display = Display(
                        ip=addr,
                        port=port,
                        name=display_name,
                        method=f"mDNS ({type_.replace('.local.', '')})",
                        protocol=protocol
                    )
                    self.displays.append(display)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass


def discover_mdns(timeout: float = 3.0) -> list[Display]:
    """Discover displays using mDNS/Bonjour"""
    if not ZEROCONF_AVAILABLE:
        return []

    print("  Scanning mDNS...")
    displays = []

    try:
        zeroconf = Zeroconf()
        listener = MDNSListener()

        # Look for specific LED matrix services (preferred)
        # The firmware advertises these service types:
        #   _ddp._udp - DDP protocol on port 4048
        #   _artnet._udp - ArtNet protocol on port 6454
        #   _ledmatrix._tcp - specific LED matrix service
        browsers = [
            ServiceBrowser(zeroconf, "_ddp._udp.local.", listener),
            ServiceBrowser(zeroconf, "_artnet._udp.local.", listener),
            ServiceBrowser(zeroconf, "_ledmatrix._tcp.local.", listener),
        ]

        time.sleep(timeout)
        displays = listener.displays

        zeroconf.close()
    except Exception as e:
        print(f"  mDNS error: {e}")

    return displays


def discover_udp_broadcast(timeout: float = 2.0) -> list[Display]:
    """Discover displays using UDP broadcast"""
    print("  Scanning UDP broadcast...")
    displays = []

    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)

        # Bind to receive responses
        sock.bind(("", 0))

        # Send broadcast query
        sock.sendto(DDP_QUERY_PACKET, ("<broadcast>", DDP_PORT))

        # Also try common broadcast addresses
        try:
            sock.sendto(DDP_QUERY_PACKET, ("255.255.255.255", DDP_PORT))
        except:
            pass

        # Listen for responses
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                data, addr = sock.recvfrom(1024)
                if len(data) >= 10:  # Valid DDP packet
                    display = Display(ip=addr[0], port=DDP_PORT, method="UDP broadcast")
                    if display.ip not in [d.ip for d in displays]:
                        displays.append(display)
            except socket.timeout:
                continue

        sock.close()
    except Exception as e:
        print(f"  UDP broadcast error: {e}")

    return displays


def discover_subnet_scan(
    subnet: str = None,
    timeout: float = 0.5,
    callback: Callable[[str], None] = None
) -> list[Display]:
    """Scan subnet for DDP displays"""
    displays = []
    found_lock = threading.Lock()

    # Determine subnet to scan
    if subnet is None:
        # Get local IP and derive subnet
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            # Assume /24 subnet
            parts = local_ip.split(".")
            subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        except:
            subnet = "192.168.1.0/24"

    print(f"  Scanning {subnet}...")

    # Parse subnet
    if "/" in subnet:
        base_ip, prefix = subnet.split("/")
        prefix = int(prefix)
    else:
        base_ip = subnet
        prefix = 24

    # Calculate IP range
    base_parts = [int(p) for p in base_ip.split(".")]
    base_int = (base_parts[0] << 24) | (base_parts[1] << 16) | (base_parts[2] << 8) | base_parts[3]

    num_hosts = 2 ** (32 - prefix) - 2  # Exclude network and broadcast
    start_ip = (base_int & (0xFFFFFFFF << (32 - prefix))) + 1

    def check_host(ip_int: int):
        ip = f"{(ip_int >> 24) & 0xFF}.{(ip_int >> 16) & 0xFF}.{(ip_int >> 8) & 0xFF}.{ip_int & 0xFF}"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)

            # Send a minimal DDP packet
            test_packet = bytes([0x41, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00]) + bytes(256)
            sock.sendto(test_packet, (ip, DDP_PORT))

            # Try to get a response (some displays echo back or send status)
            # Even without response, if no error, port might be open
            sock.close()

            # Alternative: Try TCP connection to HTTP port to verify it's our device
            try:
                http_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                http_sock.settimeout(timeout)
                http_sock.connect((ip, 80))
                http_sock.close()

                # HTTP port open, likely our display
                with found_lock:
                    display = Display(ip=ip, port=DDP_PORT, method="subnet scan")
                    displays.append(display)
                    if callback:
                        callback(ip)
            except:
                pass

        except:
            pass

    # Scan in parallel
    threads = []
    for i in range(min(num_hosts, 254)):
        ip_int = start_ip + i
        t = threading.Thread(target=check_host, args=(ip_int,))
        t.start()
        threads.append(t)

        # Limit concurrent threads
        if len(threads) >= 50:
            for t in threads:
                t.join()
            threads = []

    # Wait for remaining threads
    for t in threads:
        t.join()

    return displays


def verify_display(ip: str, timeout: float = 1.0) -> bool:
    """Verify that an IP is actually a DDP display by checking HTTP API"""
    try:
        import urllib.request
        url = f"http://{ip}/api/info"
        req = urllib.request.Request(url, headers={"User-Agent": "DDP-Discovery"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read().decode()
            # Check if it looks like our display
            return "freeHeap" in data or "plugin" in data
    except:
        return False


def discover_all(
    timeout: float = 3.0,
    subnet: str = None,
    verify: bool = True,
    protocol: str = None
) -> list[Display]:
    """Run all discovery methods and combine results

    Args:
        timeout: Discovery timeout in seconds
        subnet: Subnet to scan (e.g., 192.168.1.0/24)
        verify: Verify displays via HTTP API
        protocol: Filter by protocol ('ddp', 'artnet', or None for all)
    """
    all_displays: dict[str, Display] = {}

    # Method 1: mDNS
    if ZEROCONF_AVAILABLE:
        for d in discover_mdns(timeout):
            key = f"{d.ip}:{d.protocol}"
            all_displays[key] = d
    else:
        print("  (mDNS unavailable - install zeroconf: pip install zeroconf)")

    # Method 2: UDP Broadcast (DDP only for now)
    for d in discover_udp_broadcast(timeout):
        key = f"{d.ip}:{d.protocol}"
        if key not in all_displays:
            all_displays[key] = d

    # Method 3: Subnet scan (only if few results so far)
    if len(all_displays) < 2:
        for d in discover_subnet_scan(subnet, timeout=0.3):
            key = f"{d.ip}:{d.protocol}"
            if key not in all_displays:
                all_displays[key] = d

    # Filter by protocol if specified
    if protocol:
        all_displays = {k: v for k, v in all_displays.items() if v.protocol == protocol}

    # Verify displays
    if verify:
        verified = []
        for key, display in all_displays.items():
            if verify_display(display.ip):
                display.method += " (verified)"
                verified.append(display)
            else:
                # Keep it but mark as unverified
                display.method += " (unverified)"
                verified.append(display)
        return verified

    return list(all_displays.values())


def discover_displays(protocol: str = None, timeout: float = 3.0) -> list[str]:
    """Simple function to discover displays and return IPs

    Args:
        protocol: Filter by protocol ('ddp', 'artnet', or None for all)
        timeout: Discovery timeout in seconds

    Returns:
        List of IP addresses
    """
    displays = discover_all(timeout=timeout, verify=True, protocol=protocol)
    return [d.ip for d in displays]


def main():
    parser = argparse.ArgumentParser(description="Discover LED matrix displays on the network")
    parser.add_argument("--timeout", "-t", type=float, default=3.0, help="Discovery timeout in seconds")
    parser.add_argument("--subnet", "-s", help="Subnet to scan (e.g., 192.168.1.0/24)")
    parser.add_argument("--no-verify", action="store_true", help="Skip HTTP verification")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--protocol", "-p", choices=["ddp", "artnet"], help="Filter by protocol")
    args = parser.parse_args()

    print("=" * 50)
    print("LED Matrix Display Discovery")
    print("=" * 50)
    print()

    displays = discover_all(
        timeout=args.timeout,
        subnet=args.subnet,
        verify=not args.no_verify,
        protocol=args.protocol
    )

    print()

    if not displays:
        print("No displays found.")
        print()
        print("Tips:")
        print("  - Make sure displays are powered on and connected to WiFi")
        print("  - Check that you're on the same network")
        print("  - Try specifying subnet: --subnet 192.168.1.0/24")
        if not ZEROCONF_AVAILABLE:
            print("  - Install zeroconf for better discovery: pip install zeroconf")
        sys.exit(1)

    if args.json:
        import json
        result = [{"ip": d.ip, "port": d.port, "name": d.name, "method": d.method, "protocol": d.protocol} for d in displays]
        print(json.dumps(result, indent=2))
    else:
        print(f"Found {len(displays)} display(s):")
        print()
        for i, d in enumerate(displays, 1):
            print(f"  [{i}] {d}")
            print(f"      Method: {d.method}")
        print()
        print("Use these IPs with other scripts:")
        ips = " ".join(d.ip for d in displays)
        print(f"  python contrib/blobs.py --displays {ips}")
        print(f"  python contrib/blobs.py --discover          # Auto-discover")
        print(f"  python contrib/test_artnet.py --displays {ips}")


if __name__ == "__main__":
    main()
