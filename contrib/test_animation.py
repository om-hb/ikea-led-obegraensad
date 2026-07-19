#!/usr/bin/env python3
"""Optimized test animation for DDP displays - dynamic multi-display support

Usage:
    python test_animation.py [--no-switch]
"""

import argparse
import math
import os
import sys
import time

# Add parent directory to path for ddp import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddp import DDPClient, create_packet_from_buffer, DISPLAY_PIXELS, switch_to_ddp_plugin

# Display configuration - add/remove IPs as needed
DISPLAYS = ["192.168.40.204", "192.168.40.233"]

# Virtual display dimensions (displays arranged side-by-side)
DISPLAY_SIZE = 16


def switch_all_displays():
    """Switch all displays to DDP plugin"""
    print("Switching all displays to DDP plugin...")
    for ip in DISPLAYS:
        switch_to_ddp_plugin(ip)
NUM_DISPLAYS = len(DISPLAYS)
VIRTUAL_WIDTH = DISPLAY_SIZE * NUM_DISPLAYS
VIRTUAL_HEIGHT = DISPLAY_SIZE

# Brightness range 0-255 (firmware quantizes to 16 levels)
MAX_BRIGHTNESS = 255


class FrameTimer:
    """Precise frame timing using perf_counter to maintain consistent FPS"""

    def __init__(self, fps: float):
        self.interval = 1.0 / fps
        self.next_frame = time.perf_counter()
        self.frame_count = 0
        self.start_time = self.next_frame

    def wait(self) -> None:
        """Wait until next frame time, compensating for processing delays"""
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
        """Get actual achieved FPS"""
        elapsed = time.perf_counter() - self.start_time
        return self.frame_count / elapsed if elapsed > 0 else 0.0


def create_buffer() -> bytearray:
    """Create an empty frame buffer (256 bytes)"""
    return bytearray(DISPLAY_PIXELS)


def create_buffers() -> list[bytearray]:
    """Create empty buffers for all displays"""
    return [create_buffer() for _ in range(NUM_DISPLAYS)]


def set_pixel(buf: bytearray, x: int, y: int, brightness: int) -> None:
    """Set a pixel in a single display buffer (brightness 0-255)"""
    if 0 <= x < DISPLAY_SIZE and 0 <= y < DISPLAY_SIZE:
        buf[y * DISPLAY_SIZE + x] = min(255, max(0, brightness))


def set_virtual_pixel(buffers: list[bytearray], x: int, y: int, brightness: int) -> None:
    """Set a pixel on the virtual display (spans all displays side-by-side)"""
    if 0 <= x < VIRTUAL_WIDTH and 0 <= y < VIRTUAL_HEIGHT:
        display_idx = x // DISPLAY_SIZE
        local_x = x % DISPLAY_SIZE
        if display_idx < len(buffers):
            set_pixel(buffers[display_idx], local_x, y, brightness)


def fill_buffer(buf: bytearray, brightness: int) -> None:
    """Fill entire buffer with brightness (0-255)"""
    val = min(255, max(0, brightness))
    for i in range(DISPLAY_PIXELS):
        buf[i] = val


def buffers_to_packets(buffers: list[bytearray], push: bool = False) -> list[bytearray]:
    """Convert list of buffers to list of packets"""
    return [create_packet_from_buffer(buf, push=push) for buf in buffers]


# =============================================================================
# COMPARISON PATTERNS: Show difference between SYNC and UNSYNC
# =============================================================================


def compare_blink_unsync():
    """WITHOUT SYNC: Fast blinking"""
    print("  [UNSYNC] Fast blinking without synchronization...")

    buf_on = create_buffer()
    fill_buffer(buf_on, MAX_BRIGHTNESS)
    buf_off = create_buffer()

    packet_on = create_packet_from_buffer(buf_on, push=True)
    packet_off = create_packet_from_buffer(buf_off, push=True)

    timer = FrameTimer(12.5)
    with DDPClient(DISPLAYS) as client:
        for _ in range(30):
            for addr in client._addrs:
                client.sock.sendto(packet_on, addr)
            timer.wait()

            for addr in client._addrs:
                client.sock.sendto(packet_off, addr)
            timer.wait()


def compare_blink_sync():
    """WITH SYNC: Fast blinking"""
    print("  [SYNC] Fast blinking with synchronization...")

    buf_on = create_buffer()
    fill_buffer(buf_on, MAX_BRIGHTNESS)
    buf_off = create_buffer()

    packet_on = create_packet_from_buffer(buf_on, push=False)
    packet_off = create_packet_from_buffer(buf_off, push=False)

    timer = FrameTimer(12.5)
    with DDPClient(DISPLAYS) as client:
        for _ in range(30):
            client.send_frame_sync([packet_on] * NUM_DISPLAYS)
            timer.wait()

            client.send_frame_sync([packet_off] * NUM_DISPLAYS)
            timer.wait()


def compare_horizontal_line_unsync():
    """WITHOUT SYNC: Horizontal line moves"""
    print("  [UNSYNC] Horizontal line without synchronization...")

    frames = []
    for y in range(DISPLAY_SIZE):
        buf = create_buffer()
        for x in range(DISPLAY_SIZE):
            set_pixel(buf, x, y, MAX_BRIGHTNESS)
        frames.append(create_packet_from_buffer(buf, push=True))

    timer = FrameTimer(25)
    with DDPClient(DISPLAYS) as client:
        for _ in range(3):
            for packet in frames:
                for addr in client._addrs:
                    client.sock.sendto(packet, addr)
                timer.wait()


def compare_horizontal_line_sync():
    """WITH SYNC: Horizontal line moves"""
    print("  [SYNC] Horizontal line with synchronization...")

    frames = []
    for y in range(DISPLAY_SIZE):
        buf = create_buffer()
        for x in range(DISPLAY_SIZE):
            set_pixel(buf, x, y, MAX_BRIGHTNESS)
        frames.append(create_packet_from_buffer(buf, push=False))

    timer = FrameTimer(25)
    with DDPClient(DISPLAYS) as client:
        for _ in range(3):
            for packet in frames:
                client.send_frame_sync([packet] * NUM_DISPLAYS)
                timer.wait()


def compare_checkerboard_unsync():
    """WITHOUT SYNC: Checkerboard alternates"""
    print("  [UNSYNC] Checkerboard pattern without synchronization...")

    buf_a = create_buffer()
    buf_b = create_buffer()
    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            if (x + y) % 2 == 0:
                set_pixel(buf_a, x, y, MAX_BRIGHTNESS)
            else:
                set_pixel(buf_b, x, y, MAX_BRIGHTNESS)

    packet_a = create_packet_from_buffer(buf_a, push=True)
    packet_b = create_packet_from_buffer(buf_b, push=True)

    timer = FrameTimer(10)
    with DDPClient(DISPLAYS) as client:
        for _ in range(20):
            for addr in client._addrs:
                client.sock.sendto(packet_a, addr)
            timer.wait()

            for addr in client._addrs:
                client.sock.sendto(packet_b, addr)
            timer.wait()


def compare_checkerboard_sync():
    """WITH SYNC: Checkerboard alternates"""
    print("  [SYNC] Checkerboard pattern with synchronization...")

    buf_a = create_buffer()
    buf_b = create_buffer()
    for y in range(DISPLAY_SIZE):
        for x in range(DISPLAY_SIZE):
            if (x + y) % 2 == 0:
                set_pixel(buf_a, x, y, MAX_BRIGHTNESS)
            else:
                set_pixel(buf_b, x, y, MAX_BRIGHTNESS)

    packet_a = create_packet_from_buffer(buf_a, push=False)
    packet_b = create_packet_from_buffer(buf_b, push=False)

    timer = FrameTimer(10)
    with DDPClient(DISPLAYS) as client:
        for _ in range(20):
            client.send_frame_sync([packet_a] * NUM_DISPLAYS)
            timer.wait()

            client.send_frame_sync([packet_b] * NUM_DISPLAYS)
            timer.wait()


def run_comparison():
    """Runs all comparisons sequentially"""
    comparisons = [
        ("Blinking", compare_blink_unsync, compare_blink_sync),
        ("Horizontal Line", compare_horizontal_line_unsync, compare_horizontal_line_sync),
        ("Checkerboard", compare_checkerboard_unsync, compare_checkerboard_sync),
    ]

    for name, unsync_func, sync_func in comparisons:
        print(f"\n{'='*50}")
        print(f"TEST: {name}")
        print("=" * 50)

        print("\n>>> WITHOUT Synchronization:")
        unsync_func()
        time.sleep(0.5)

        print("\n>>> WITH Synchronization:")
        sync_func()
        time.sleep(0.5)

        input("\n[Enter] for next test...")


# =============================================================================
# STANDARD ANIMATIONS (with sync, optimized, dynamic display count)
# =============================================================================


def snake_animation():
    """Snake game-like animation with head and trailing body across all displays"""
    FPS = 15
    SNAKE_LENGTH = 8  # Number of body segments

    print(f"Computing snake path for {NUM_DISPLAYS} displays ({VIRTUAL_WIDTH}x{VIRTUAL_HEIGHT})...")

    # Build the snake's path (zigzag across virtual display)
    path = []
    for y in range(VIRTUAL_HEIGHT):
        if y % 2 == 0:
            # Left to right
            for x in range(VIRTUAL_WIDTH):
                path.append((x, y))
        else:
            # Right to left
            for x in range(VIRTUAL_WIDTH - 1, -1, -1):
                path.append((x, y))

    # Pre-compute all frames
    frames = []
    total_positions = len(path)

    for head_idx in range(total_positions + SNAKE_LENGTH):
        buffers = create_buffers()

        # Draw each segment of the snake
        for segment in range(SNAKE_LENGTH):
            pos_idx = head_idx - segment
            if 0 <= pos_idx < total_positions:
                x, y = path[pos_idx]
                # Brightness fades from head to tail
                brightness = MAX_BRIGHTNESS - (segment * (MAX_BRIGHTNESS // SNAKE_LENGTH))
                brightness = max(16, brightness)  # Keep minimum visibility
                set_virtual_pixel(buffers, x, y, brightness)

        packets = buffers_to_packets(buffers, push=False)
        frames.append(packets)

    print(f"Starting snake animation @ {FPS} FPS... ({len(frames)} frames, snake length: {SNAKE_LENGTH})")
    timer = FrameTimer(FPS)
    with DDPClient(DISPLAYS) as client:
        try:
            while True:
                for packets in frames:
                    client.send_frame_sync(packets)
                    timer.wait()
        except KeyboardInterrupt:
            print(f"\nActual FPS: {timer.get_actual_fps():.1f}")
            raise


def wave_animation():
    """Synchronized wave across all displays"""
    FPS = 20

    print(f"Computing frames for {NUM_DISPLAYS} displays...")
    frames = []

    for offset in range(64):  # Longer cycle for wider display
        buffers = create_buffers()
        for x in range(VIRTUAL_WIDTH):
            y = int(8 + 6 * math.sin((x + offset) * 0.3))
            set_virtual_pixel(buffers, x, y, MAX_BRIGHTNESS)
        frames.append(buffers_to_packets(buffers, push=False))

    print(f"Starting animation @ {FPS} FPS... ({len(frames)} frames)")
    timer = FrameTimer(FPS)
    with DDPClient(DISPLAYS) as client:
        try:
            while True:
                for packets in frames:
                    client.send_frame_sync(packets)
                    timer.wait()
        except KeyboardInterrupt:
            print(f"\nActual FPS: {timer.get_actual_fps():.1f}")
            raise


def diagonal_wipe():
    """Diagonal wipe across all displays"""
    FPS = 50

    # Max diagonal distance across all displays
    max_diag = VIRTUAL_WIDTH + VIRTUAL_HEIGHT - 2

    print(f"Computing frames for {NUM_DISPLAYS} displays (diagonal 0-{max_diag})...")
    frames_in = []
    frames_out = []

    for step in range(max_diag + 1):
        buffers_in = create_buffers()
        buffers_out = create_buffers()

        for y in range(VIRTUAL_HEIGHT):
            for x in range(VIRTUAL_WIDTH):
                if x + y <= step:
                    set_virtual_pixel(buffers_in, x, y, MAX_BRIGHTNESS)
                if x + y > step:
                    set_virtual_pixel(buffers_out, x, y, MAX_BRIGHTNESS)

        frames_in.append(buffers_to_packets(buffers_in, push=False))
        frames_out.append(buffers_to_packets(buffers_out, push=False))

    pause_frames = 10  # 200ms at 50 FPS

    print(f"Starting animation @ {FPS} FPS... ({len(frames_in)} frames per wipe)")
    timer = FrameTimer(FPS)
    with DDPClient(DISPLAYS) as client:
        try:
            while True:
                # Wipe in
                for packets in frames_in:
                    client.send_frame_sync(packets)
                    timer.wait()

                # Pause
                for _ in range(pause_frames):
                    timer.wait()

                # Wipe out
                for packets in frames_out:
                    client.send_frame_sync(packets)
                    timer.wait()

                # Pause
                for _ in range(pause_frames):
                    timer.wait()
        except KeyboardInterrupt:
            print(f"\nActual FPS: {timer.get_actual_fps():.1f}")
            raise


def grayscale_test():
    """Test all 16 grayscale levels"""
    print(f"Testing all 16 grayscale levels on {NUM_DISPLAYS} displays...")
    with DDPClient(DISPLAYS) as client:
        for level in range(16):
            brightness = (level * 255) // 15 if level > 0 else 0
            buf = create_buffer()
            fill_buffer(buf, brightness)
            packet = create_packet_from_buffer(buf, push=False)
            client.send_frame_sync([packet] * NUM_DISPLAYS)
            print(f"  Level {level}/15 = Brightness {brightness}/255")
            time.sleep(0.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DDP display test animations")
    parser.add_argument("--no-switch", action="store_true", help="Don't auto-switch to DDP plugin")
    args = parser.parse_args()

    animations = {
        "1": ("Comparison: Sync vs Unsync", run_comparison),
        "2": ("Snake Animation", snake_animation),
        "3": ("Wave Animation", wave_animation),
        "4": ("Diagonal Wipe", diagonal_wipe),
        "5": ("Grayscale Test (0-15)", grayscale_test),
    }

    print("=" * 50)
    print("DDP Display Test (Dynamic Multi-Display)")
    print("=" * 50)
    print(f"Displays: {NUM_DISPLAYS}")
    for i, ip in enumerate(DISPLAYS):
        print(f"  [{i+1}] {ip}")
    print(f"Virtual size: {VIRTUAL_WIDTH}x{VIRTUAL_HEIGHT}")
    print(f"Brightness: 0-255 (16 visible levels)")
    print(f"Packet size: 266 bytes (header + 256 pixels)")
    print()

    # Auto-switch to DDP plugin
    if not args.no_switch:
        switch_all_displays()
        print()

    for key, (name, _) in animations.items():
        print(f"  {key}: {name}")

    choice = input("\nSelect (1-5): ").strip()

    if choice in animations:
        name, func = animations[choice]
        print(f"\nStarting: {name}")
        print("(Ctrl+C to exit)\n")
        try:
            func()
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print("Invalid selection.")
