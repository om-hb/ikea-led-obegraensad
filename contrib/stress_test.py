#!/usr/bin/env python3
"""
Stress test for ESP32 LED Matrix displays
Tests stability under various load conditions

Usage:
    python stress_test.py [IP] [--duration MINUTES]

Tests performed:
    1. Rapid DDP packet flooding (max throughput)
    2. Rapid ArtNet packet flooding (max throughput)
    3. WebSocket connection cycling
    4. Plugin switching stress
    5. Combined load test
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

# Add parent directory to path for ddp import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import websocket
    from ddp import switch_to_ddp_plugin
    from artnet import switch_to_artnet_plugin, create_packet_from_buffer as create_artnet_packet
except ImportError:
    print("Error: websocket-client required")
    print("Install with: pip install websocket-client")
    sys.exit(1)

DEFAULT_IP = "192.168.40.204"
DDP_PORT = 4048
ARTNET_PORT = 6454


@dataclass
class TestResult:
    name: str
    duration: float
    packets_sent: int = 0
    errors: int = 0
    success: bool = True
    notes: str = ""


def create_ddp_packet(brightness: int = 128) -> bytes:
    """Create a DDP grayscale packet"""
    header = bytearray([0x41, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00])
    data = bytearray([brightness] * 256)
    return bytes(header + data)


def test_ddp_flood(ip: str, duration: float = 30.0) -> TestResult:
    """Test 1: Flood DDP packets at maximum rate"""
    print(f"\n[TEST 1] DDP Packet Flood ({duration}s)")
    print("=" * 50)

    # Switch to DDP plugin first
    print("  Switching to DDP plugin...")
    switch_to_ddp_plugin(ip)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    packets_sent = 0
    errors = 0
    start = time.time()

    # Alternate brightness for visual confirmation
    packets = [create_ddp_packet(0), create_ddp_packet(255)]

    try:
        while time.time() - start < duration:
            try:
                packet = packets[packets_sent % 2]
                sock.sendto(packet, (ip, DDP_PORT))
                packets_sent += 1
            except BlockingIOError:
                pass
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  Error: {e}")

            # Small yield to not completely block
            if packets_sent % 10000 == 0:
                elapsed = time.time() - start
                rate = packets_sent / elapsed
                print(f"  {elapsed:.1f}s: {packets_sent} packets ({rate:.0f}/s)")

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    elapsed = time.time() - start
    rate = packets_sent / elapsed if elapsed > 0 else 0

    print(f"\n  Result: {packets_sent} packets in {elapsed:.1f}s")
    print(f"  Rate: {rate:.0f} packets/second")
    print(f"  Errors: {errors}")

    return TestResult(
        name="DDP Flood",
        duration=elapsed,
        packets_sent=packets_sent,
        errors=errors,
        success=errors < 10,
        notes=f"{rate:.0f} pkt/s"
    )


def test_artnet_flood(ip: str, duration: float = 30.0) -> TestResult:
    """Test: Flood ArtNet packets at maximum rate"""
    print(f"\n[TEST] ArtNet Packet Flood ({duration}s)")
    print("=" * 50)

    # Switch to ArtNet plugin first
    print("  Switching to ArtNet plugin...")
    switch_to_artnet_plugin(ip)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)

    packets_sent = 0
    errors = 0
    start = time.time()
    sequence = 0

    # Create packets with alternating brightness
    buffer_off = bytearray(256)
    buffer_on = bytearray([255] * 256)

    try:
        while time.time() - start < duration:
            try:
                buffer = buffer_on if packets_sent % 2 else buffer_off
                packet = create_artnet_packet(buffer, universe=0, sequence=sequence)
                sock.sendto(packet, (ip, ARTNET_PORT))
                packets_sent += 1
                sequence = (sequence + 1) & 0xFF
            except BlockingIOError:
                pass
            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  Error: {e}")

            if packets_sent % 10000 == 0:
                elapsed = time.time() - start
                rate = packets_sent / elapsed
                print(f"  {elapsed:.1f}s: {packets_sent} packets ({rate:.0f}/s)")

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    elapsed = time.time() - start
    rate = packets_sent / elapsed if elapsed > 0 else 0

    print(f"\n  Result: {packets_sent} packets in {elapsed:.1f}s")
    print(f"  Rate: {rate:.0f} packets/second")
    print(f"  Errors: {errors}")

    return TestResult(
        name="ArtNet Flood",
        duration=elapsed,
        packets_sent=packets_sent,
        errors=errors,
        success=errors < 10,
        notes=f"{rate:.0f} pkt/s"
    )


def test_websocket_cycling(ip: str, duration: float = 30.0) -> TestResult:
    """Test 2: Rapid WebSocket connect/disconnect cycles"""
    print(f"\n[TEST 2] WebSocket Connection Cycling ({duration}s)")
    print("=" * 50)

    connections = 0
    errors = 0
    start = time.time()

    try:
        while time.time() - start < duration:
            try:
                ws = websocket.create_connection(f"ws://{ip}/ws", timeout=5)
                # Wait for info packet
                ws.recv()
                ws.close()
                connections += 1

                if connections % 10 == 0:
                    elapsed = time.time() - start
                    rate = connections / elapsed
                    print(f"  {elapsed:.1f}s: {connections} connections ({rate:.1f}/s)")

            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  Error: {e}")
                time.sleep(0.5)  # Back off on errors

    except KeyboardInterrupt:
        pass

    elapsed = time.time() - start
    rate = connections / elapsed if elapsed > 0 else 0

    print(f"\n  Result: {connections} connections in {elapsed:.1f}s")
    print(f"  Rate: {rate:.1f} connections/second")
    print(f"  Errors: {errors}")

    return TestResult(
        name="WebSocket Cycling",
        duration=elapsed,
        packets_sent=connections,
        errors=errors,
        success=errors < connections * 0.1,  # <10% error rate
        notes=f"{rate:.1f} conn/s"
    )


def test_plugin_switching(ip: str, duration: float = 30.0) -> TestResult:
    """Test 3: Rapid plugin switching"""
    print(f"\n[TEST 3] Plugin Switching Stress ({duration}s)")
    print("=" * 50)

    switches = 0
    errors = 0
    start = time.time()
    plugins = []

    try:
        # Get plugin list
        ws = websocket.create_connection(f"ws://{ip}/ws", timeout=5)
        result = ws.recv()
        data = json.loads(result)
        plugins = [p["id"] for p in data.get("plugins", [])]
        print(f"  Found {len(plugins)} plugins")

        while time.time() - start < duration:
            try:
                # Switch to random plugin
                plugin_id = plugins[switches % len(plugins)]
                ws.send(json.dumps({"event": "plugin", "plugin": plugin_id}))
                switches += 1

                # Small delay to allow processing
                time.sleep(0.1)

                if switches % 20 == 0:
                    elapsed = time.time() - start
                    rate = switches / elapsed
                    print(f"  {elapsed:.1f}s: {switches} switches ({rate:.1f}/s)")

            except Exception as e:
                errors += 1
                if errors < 5:
                    print(f"  Error: {e}")
                # Reconnect
                try:
                    ws.close()
                except:
                    pass
                time.sleep(0.5)
                ws = websocket.create_connection(f"ws://{ip}/ws", timeout=5)
                ws.recv()

        ws.close()

    except KeyboardInterrupt:
        pass
    except Exception as e:
        errors += 1
        print(f"  Fatal error: {e}")

    elapsed = time.time() - start
    rate = switches / elapsed if elapsed > 0 else 0

    print(f"\n  Result: {switches} plugin switches in {elapsed:.1f}s")
    print(f"  Rate: {rate:.1f} switches/second")
    print(f"  Errors: {errors}")

    return TestResult(
        name="Plugin Switching",
        duration=elapsed,
        packets_sent=switches,
        errors=errors,
        success=errors < switches * 0.1,
        notes=f"{rate:.1f} sw/s"
    )


def test_combined_load(ip: str, duration: float = 60.0) -> TestResult:
    """Test 4: Combined stress (DDP + WebSocket simultaneously)"""
    print(f"\n[TEST 4] Combined Load Test ({duration}s)")
    print("=" * 50)

    # Switch to DDP plugin first
    print("  Switching to DDP plugin...")
    switch_to_ddp_plugin(ip)

    ddp_packets = 0
    ws_messages = 0
    errors = 0
    running = True

    def ddp_thread():
        nonlocal ddp_packets, errors
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packet = create_ddp_packet(128)
        while running:
            try:
                sock.sendto(packet, (ip, DDP_PORT))
                ddp_packets += 1
                time.sleep(0.02)  # ~50 FPS
            except Exception:
                errors += 1
        sock.close()

    def ws_thread():
        nonlocal ws_messages, errors
        while running:
            try:
                ws = websocket.create_connection(f"ws://{ip}/ws", timeout=5)
                while running:
                    ws.send(json.dumps({"event": "info"}))
                    ws.recv()
                    ws_messages += 1
                    time.sleep(0.1)
            except Exception:
                errors += 1
                time.sleep(0.5)

    # Start threads
    t1 = threading.Thread(target=ddp_thread)
    t2 = threading.Thread(target=ws_thread)
    t1.start()
    t2.start()

    start = time.time()
    try:
        while time.time() - start < duration:
            elapsed = time.time() - start
            print(f"  {elapsed:.0f}s: DDP={ddp_packets}, WS={ws_messages}, Errors={errors}")
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    running = False
    t1.join(timeout=2)
    t2.join(timeout=2)

    elapsed = time.time() - start

    print(f"\n  Result: DDP={ddp_packets}, WebSocket={ws_messages}")
    print(f"  Duration: {elapsed:.1f}s")
    print(f"  Errors: {errors}")

    return TestResult(
        name="Combined Load",
        duration=elapsed,
        packets_sent=ddp_packets + ws_messages,
        errors=errors,
        success=errors < 20,
        notes=f"DDP:{ddp_packets} WS:{ws_messages}"
    )


def check_device_alive(ip: str) -> bool:
    """Check if device is still responding"""
    try:
        ws = websocket.create_connection(f"ws://{ip}/ws", timeout=5)
        ws.recv()
        ws.close()
        return True
    except:
        return False


def get_heap_info(ip: str) -> dict | None:
    """Get heap information from device"""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://{ip}/api/info", timeout=5) as response:
            data = json.loads(response.read())
            return {
                "free": data.get("freeHeap", 0),
                "min": data.get("minFreeHeap", 0),
                "maxBlock": data.get("maxAllocHeap", 0),
            }
    except:
        return None


def main():
    parser = argparse.ArgumentParser(description="Stress test ESP32 LED Matrix")
    parser.add_argument("ip", nargs="?", default=DEFAULT_IP, help=f"Display IP (default: {DEFAULT_IP})")
    parser.add_argument("--duration", "-d", type=float, default=30, help="Test duration in seconds (default: 30)")
    parser.add_argument("--test", "-t", type=int, choices=[1, 2, 3, 4, 5], help="Run specific test only (1=DDP, 2=ArtNet, 3=WS, 4=Plugin, 5=Combined)")
    args = parser.parse_args()

    print("=" * 60)
    print("ESP32 LED Matrix Stress Test")
    print("=" * 60)
    print(f"Target: {args.ip}")
    print(f"Duration per test: {args.duration}s")
    print()

    # Check device is alive
    print("Checking device connectivity...", end=" ")
    if not check_device_alive(args.ip):
        print("FAILED")
        print("Could not connect to device. Check IP and network.")
        sys.exit(1)
    print("OK")

    # Get initial heap info
    heap_start = get_heap_info(args.ip)
    if heap_start:
        print(f"Initial heap: Free={heap_start['free']}, Min={heap_start['min']}, MaxBlock={heap_start['maxBlock']}")

    tests: list[Callable] = []
    all_tests = [test_ddp_flood, test_artnet_flood, test_websocket_cycling, test_plugin_switching, test_combined_load]
    if args.test:
        tests = [all_tests[args.test - 1]]
    else:
        tests = all_tests

    results: list[TestResult] = []

    for test_func in tests:
        # Check device before each test
        if not check_device_alive(args.ip):
            print(f"\n*** DEVICE CRASHED before {test_func.__name__} ***")
            print("Waiting 30 seconds for potential recovery...")
            time.sleep(30)
            if not check_device_alive(args.ip):
                print("Device did not recover. Aborting.")
                break

        result = test_func(args.ip, args.duration)
        results.append(result)

        # Check device after test
        print("\nChecking device health...", end=" ")
        time.sleep(2)  # Give device time to recover
        if check_device_alive(args.ip):
            print("OK")
        else:
            print("DEVICE NOT RESPONDING!")
            result.success = False
            result.notes += " [CRASH]"

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for r in results:
        status = "PASS" if r.success else "FAIL"
        all_passed = all_passed and r.success
        print(f"  [{status}] {r.name}: {r.notes} (errors: {r.errors})")

    # Final heap info
    heap_end = get_heap_info(args.ip)
    if heap_end and heap_start:
        print()
        print("Heap Analysis:")
        print(f"  Start:  Free={heap_start['free']}, Min={heap_start['min']}")
        print(f"  End:    Free={heap_end['free']}, Min={heap_end['min']}")
        heap_diff = heap_start['free'] - heap_end['free']
        if heap_diff > 0:
            print(f"  Leaked: {heap_diff} bytes")
        elif heap_diff < 0:
            print(f"  Freed:  {-heap_diff} bytes")
        else:
            print("  No leak detected")

    print()
    if all_passed:
        print("All tests PASSED - Device is stable!")
    else:
        print("Some tests FAILED - Check device stability")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
