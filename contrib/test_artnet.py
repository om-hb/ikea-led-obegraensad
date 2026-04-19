#!/usr/bin/env python3
"""
ArtNet test and animation script for ESP32 LED Matrix

Usage:
    python test_artnet.py --discover           # Auto-discover
    python test_artnet.py [IP] [--no-switch]

Tests:
    1. Basic connectivity test
    2. Grayscale levels test
    3. Universe switching test
    4. Sequence test
    5. Animation test
"""

import argparse
import math
import os
import socket
import sys
import time

# Add parent directory to path for artnet import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artnet import (
    ARTNET_PORT,
    ArtNetClient,
    create_packet,
    create_packet_from_buffer,
    switch_to_artnet_plugin,
)
from discover import discover_displays

DEFAULT_IP = "192.168.40.204"  # Fallback if discovery fails
DISPLAY_SIZE = 16
DISPLAY_PIXELS = 256
MAX_BRIGHTNESS = 255


class FrameTimer:
    """Precise frame timing"""

    def __init__(self, fps: float):
        self.interval = 1.0 / fps
        self.next_frame = time.perf_counter()
        self.frame_count = 0
        self.start_time = self.next_frame

    def wait(self) -> None:
        self.next_frame += self.interval
        now = time.perf_counter()
        if self.next_frame > now:
            sleep_time = self.next_frame - now - 0.001
            if sleep_time > 0:
                time.sleep(sleep_time)
            while time.perf_counter() < self.next_frame:
                pass
        else:
            self.next_frame = time.perf_counter()
        self.frame_count += 1

    def get_actual_fps(self) -> float:
        elapsed = time.perf_counter() - self.start_time
        return self.frame_count / elapsed if elapsed > 0 else 0.0


def create_buffer() -> bytearray:
    return bytearray(DISPLAY_PIXELS)


def set_pixel(buf: bytearray, x: int, y: int, brightness: int) -> None:
    if 0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE:
        buf[y * DISPLAY_SIZE + x] = min(255, max(0, brightness))


def fill_buffer(buf: bytearray, brightness: int) -> None:
    val = min(255, max(0, brightness))
    for i in range(DISPLAY_PIXELS):
        buf[i] = val


def test_connectivity(ip: str) -> bool:
    """Test 1: Basic ArtNet connectivity"""
    print("\n[TEST 1] Basic Connectivity")
    print("=" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)

    try:
        # Send a few test packets
        for i in range(5):
            brightness = 255 if i % 2 == 0 else 0
            buf = create_buffer()
            fill_buffer(buf, brightness)
            packet = create_packet_from_buffer(buf, sequence=i)
            sock.sendto(packet, (ip, ARTNET_PORT))
            print(f"  Sent packet {i+1}/5 (brightness={brightness})")
            time.sleep(0.2)

        # Clear
        buf = create_buffer()
        packet = create_packet_from_buffer(buf)
        sock.sendto(packet, (ip, ARTNET_PORT))
        print("  Cleared display")

        print("  Result: PASS (no socket errors)")
        return True

    except Exception as e:
        print(f"  Result: FAIL ({e})")
        return False
    finally:
        sock.close()


def test_grayscale(ip: str) -> bool:
    """Test 2: All grayscale levels"""
    print("\n[TEST 2] Grayscale Levels")
    print("=" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Test all 16 grayscale levels
        for level in range(16):
            brightness = (level * 255) // 15 if level > 0 else 0
            buf = create_buffer()
            fill_buffer(buf, brightness)
            packet = create_packet_from_buffer(buf, sequence=level)
            sock.sendto(packet, (ip, ARTNET_PORT))
            print(f"  Level {level:2d}/15 = Brightness {brightness:3d}/255")
            time.sleep(0.3)

        # Clear
        buf = create_buffer()
        packet = create_packet_from_buffer(buf)
        sock.sendto(packet, (ip, ARTNET_PORT))

        print("  Result: PASS")
        return True

    except Exception as e:
        print(f"  Result: FAIL ({e})")
        return False
    finally:
        sock.close()


def test_universe(ip: str) -> bool:
    """Test 3: Universe acceptance"""
    print("\n[TEST 3] Universe Acceptance")
    print("=" * 50)
    print("  Note: Plugin accepts universe 0 and configured universe (default: 1)")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Test universe 0 (always accepted)
        buf = create_buffer()
        for y in range(DISPLAY_SIZE):
            set_pixel(buf, 0, y, MAX_BRIGHTNESS)
        packet = create_packet_from_buffer(buf, universe=0)
        sock.sendto(packet, (ip, ARTNET_PORT))
        print("  Universe 0: Sent (1 line) - should be visible")
        time.sleep(1.5)

        # Test universe 1 (default configured universe)
        buf = create_buffer()
        for y in range(DISPLAY_SIZE):
            set_pixel(buf, 0, y, MAX_BRIGHTNESS)
            set_pixel(buf, 3, y, MAX_BRIGHTNESS)
        packet = create_packet_from_buffer(buf, universe=1)
        sock.sendto(packet, (ip, ARTNET_PORT))
        print("  Universe 1: Sent (2 lines) - should be visible")
        time.sleep(1.5)

        # Test universe 2 (should be ignored)
        buf = create_buffer()
        for y in range(DISPLAY_SIZE):
            set_pixel(buf, 0, y, MAX_BRIGHTNESS)
            set_pixel(buf, 3, y, MAX_BRIGHTNESS)
            set_pixel(buf, 6, y, MAX_BRIGHTNESS)
        packet = create_packet_from_buffer(buf, universe=2)
        sock.sendto(packet, (ip, ARTNET_PORT))
        print("  Universe 2: Sent (3 lines) - should be IGNORED (still shows 2 lines)")
        time.sleep(1.5)

        # Clear with universe 0
        buf = create_buffer()
        packet = create_packet_from_buffer(buf, universe=0)
        sock.sendto(packet, (ip, ARTNET_PORT))

        print("  Result: PASS if universe 2 was ignored")
        return True

    except Exception as e:
        print(f"  Result: FAIL ({e})")
        return False
    finally:
        sock.close()


def test_sequence(ip: str) -> bool:
    """Test 4: Sequence number handling"""
    print("\n[TEST 4] Sequence Numbers")
    print("=" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Send packets with incrementing sequence numbers
        # Visual: A moving vertical bar that wraps around
        print("  Sending 256 packets with incrementing sequence...")
        print("  Visual: Moving bar (position = sequence % 16)")

        for seq in range(256):
            buf = create_buffer()
            # Show sequence as moving bar position
            bar_x = seq % DISPLAY_SIZE
            for y in range(DISPLAY_SIZE):
                set_pixel(buf, bar_x, y, MAX_BRIGHTNESS)

            packet = create_packet_from_buffer(buf, sequence=seq)
            sock.sendto(packet, (ip, ARTNET_PORT))
            time.sleep(0.04)  # 25 FPS for better visibility

        print("  Sent all 256 sequence values (bar moved 16 times across)")

        # Clear
        buf = create_buffer()
        packet = create_packet_from_buffer(buf)
        sock.sendto(packet, (ip, ARTNET_PORT))

        print("  Result: PASS")
        return True

    except Exception as e:
        print(f"  Result: FAIL ({e})")
        return False
    finally:
        sock.close()


def test_animation(ip: str, duration: float = 10.0) -> bool:
    """Test 5: Animation stress test"""
    print(f"\n[TEST 5] Animation Test ({duration}s)")
    print("=" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fps = 30
    timer = FrameTimer(fps)
    sequence = 0
    frames_sent = 0
    start = time.time()

    try:
        print(f"  Running animation at {fps} FPS...")

        while time.time() - start < duration:
            buf = create_buffer()

            # Plasma-like effect
            t = time.time() - start
            for y in range(DISPLAY_SIZE):
                for x in range(DISPLAY_SIZE):
                    # Create moving pattern
                    val = math.sin(x * 0.5 + t * 3) + math.sin(y * 0.5 + t * 2)
                    val += math.sin((x + y) * 0.3 + t * 2.5)
                    brightness = int((val + 3) / 6 * 255)
                    brightness = max(0, min(255, brightness))
                    set_pixel(buf, x, y, brightness)

            packet = create_packet_from_buffer(buf, sequence=sequence)
            sock.sendto(packet, (ip, ARTNET_PORT))
            sequence = (sequence + 1) & 0xFF
            frames_sent += 1
            timer.wait()

        actual_fps = timer.get_actual_fps()
        print(f"  Sent {frames_sent} frames at {actual_fps:.1f} FPS")

        # Clear
        buf = create_buffer()
        packet = create_packet_from_buffer(buf)
        sock.sendto(packet, (ip, ARTNET_PORT))

        success = actual_fps >= fps * 0.9  # Allow 10% tolerance
        print(f"  Result: {'PASS' if success else 'FAIL'}")
        return success

    except Exception as e:
        print(f"  Result: FAIL ({e})")
        return False
    finally:
        sock.close()


def run_all_tests(ip: str) -> None:
    """Run all ArtNet tests"""
    results = []

    results.append(("Connectivity", test_connectivity(ip)))
    time.sleep(0.5)

    results.append(("Grayscale", test_grayscale(ip)))
    time.sleep(0.5)

    results.append(("Universe", test_universe(ip)))
    time.sleep(0.5)

    results.append(("Sequence", test_sequence(ip)))
    time.sleep(0.5)

    results.append(("Animation", test_animation(ip)))

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        all_passed = all_passed and passed
        print(f"  [{status}] {name}")

    print()
    if all_passed:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED")


def wave_animation(ip: str) -> None:
    """Interactive wave animation"""
    print("\nWave Animation (Ctrl+C to stop)")
    print("=" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fps = 30
    timer = FrameTimer(fps)
    sequence = 0

    try:
        while True:
            buf = create_buffer()
            t = time.time()

            for x in range(DISPLAY_SIZE):
                y = int(8 + 6 * math.sin(x * 0.4 + t * 3))
                set_pixel(buf, x, y, MAX_BRIGHTNESS)

                # Add tail
                for dy in range(1, 4):
                    if 0 <= y - dy < DISPLAY_SIZE:
                        brightness = MAX_BRIGHTNESS - dy * 60
                        set_pixel(buf, x, y - dy, max(0, brightness))

            packet = create_packet_from_buffer(buf, sequence=sequence)
            sock.sendto(packet, (ip, ARTNET_PORT))
            sequence = (sequence + 1) & 0xFF
            timer.wait()

    except KeyboardInterrupt:
        print(f"\nActual FPS: {timer.get_actual_fps():.1f}")
    finally:
        # Clear
        buf = create_buffer()
        packet = create_packet_from_buffer(buf)
        sock.sendto(packet, (ip, ARTNET_PORT))
        sock.close()


def main():
    parser = argparse.ArgumentParser(description="ArtNet test for ESP32 LED Matrix")
    parser.add_argument("ip", nargs="?", default=None, help=f"Display IP")
    parser.add_argument("--discover", action="store_true", help="Auto-discover displays on network")
    parser.add_argument("--no-switch", action="store_true", help="Don't auto-switch to ArtNet plugin")
    args = parser.parse_args()

    # Get display IP
    if args.discover:
        print("Discovering displays...")
        discovered = discover_displays(protocol="ddp")  # Same displays support both protocols
        if discovered:
            display_ip = discovered[0]
            print(f"  Found: {display_ip}")
        else:
            print("  No displays found, using default")
            display_ip = DEFAULT_IP
        print()
    elif args.ip:
        display_ip = args.ip
    else:
        display_ip = DEFAULT_IP

    print("=" * 50)
    print("ArtNet Test Suite")
    print("=" * 50)
    print(f"Target: {display_ip}:{ARTNET_PORT}")
    print()

    # Switch to ArtNet plugin
    if not args.no_switch:
        print("Switching to ArtNet plugin...")
        if switch_to_artnet_plugin(display_ip):
            print("  OK")
        else:
            print("  Failed to switch - continuing anyway")
        print()

    menu = {
        "1": ("Run All Tests", lambda: run_all_tests(display_ip)),
        "2": ("Connectivity Test", lambda: test_connectivity(display_ip)),
        "3": ("Grayscale Test", lambda: test_grayscale(display_ip)),
        "4": ("Universe Test", lambda: test_universe(display_ip)),
        "5": ("Sequence Test", lambda: test_sequence(display_ip)),
        "6": ("Animation Test (10s)", lambda: test_animation(display_ip)),
        "7": ("Wave Animation (interactive)", lambda: wave_animation(display_ip)),
    }

    for key, (name, _) in menu.items():
        print(f"  {key}: {name}")

    choice = input("\nSelect (1-7): ").strip()

    if choice in menu:
        name, func = menu[choice]
        print(f"\nRunning: {name}")
        try:
            func()
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print("Invalid selection.")


if __name__ == "__main__":
    main()
