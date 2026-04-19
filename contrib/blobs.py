#!/usr/bin/env python3
"""
Metaball animation for DDP displays (single or multi-display)

Requirements:
    pip install numpy websocket-client

Usage:
    # Auto-discover displays
    python blobs.py --discover

    # Single display
    python blobs.py

    # Dual display (32x16)
    python blobs.py --dual --discover

    # Custom displays
    python blobs.py --displays 192.168.40.204 192.168.40.233

    # More balls, higher FPS
    python blobs.py --balls 6 --fps 60
"""
import argparse
import os
import sys
import time

# Add project root to path for ddp import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from ddp import DDPClient, create_packet_from_buffer, switch_to_ddp_plugin
from discover import discover_displays

# ==============================
# Config
# ==============================
DISPLAYS = ["192.168.40.204", "192.168.40.233"]  # Fallback if discovery fails
DISPLAY_SIZE = 16
SIM_SCALE = 8                # Simulation resolution multiplier

DEFAULT_NUM_BALLS = 4
DEFAULT_FPS = 40
RADIUS_FACTOR = 3.0          # Radius as multiplier of SIM_SCALE
SPEED_FACTOR = 0.6           # Speed as multiplier of SIM_SCALE
GAMMA = 1.7
CAP_VALUE = 3.0              # Max field value before tone-mapping


class MetaballSimulation:
    """Metaball simulation that can span multiple displays"""

    def __init__(self, width: int, height: int, num_balls: int = DEFAULT_NUM_BALLS, sim_scale: int = SIM_SCALE):
        self.width = width
        self.height = height
        self.sim_scale = sim_scale
        self.sim_w = width * sim_scale
        self.sim_h = height * sim_scale
        self.num_balls = num_balls

        # Radius and speed scaled to simulation resolution
        self.radius = RADIUS_FACTOR * sim_scale
        self.speed = SPEED_FACTOR * sim_scale

        # Initialize balls with random positions and velocities
        self.balls = np.random.uniform(0, [self.sim_w, self.sim_h], size=(num_balls, 2))
        self.velocities = np.random.uniform(-self.speed, self.speed, size=(num_balls, 2))

        # Pre-compute coordinate grids for vectorized rendering
        y_coords, x_coords = np.mgrid[0:self.sim_h, 0:self.sim_w]
        self.coords = np.stack([x_coords, y_coords], axis=-1).astype(float)

    def attenuation_fn(self, d_squared: np.ndarray) -> np.ndarray:
        """Vectorized attenuation using squared distance"""
        r_squared = self.radius * self.radius
        mask = d_squared <= r_squared
        ratio = d_squared / r_squared
        return np.where(mask, (1 - ratio) ** 2, 0.0)

    def tone_map(self, grid: np.ndarray) -> np.ndarray:
        """Vectorized tone mapping"""
        capped = np.minimum(grid, CAP_VALUE)
        normalized = capped / CAP_VALUE
        return (normalized ** (1 / GAMMA) * 255).astype(np.uint8)

    def update(self) -> None:
        """Update ball positions with wall bouncing"""
        self.balls += self.velocities

        # Bounce off walls
        out_x = (self.balls[:, 0] < 0) | (self.balls[:, 0] >= self.sim_w)
        out_y = (self.balls[:, 1] < 0) | (self.balls[:, 1] >= self.sim_h)
        self.velocities[out_x, 0] *= -1
        self.velocities[out_y, 1] *= -1

        # Clamp positions
        self.balls[:, 0] = np.clip(self.balls[:, 0], 0, self.sim_w - 1)
        self.balls[:, 1] = np.clip(self.balls[:, 1], 0, self.sim_h - 1)

    def render(self) -> np.ndarray:
        """Render metaballs to high-resolution grid"""
        grid = np.zeros((self.sim_h, self.sim_w), dtype=float)

        for ball_pos in self.balls:
            diff = self.coords - ball_pos
            d_squared = np.sum(diff * diff, axis=-1)
            grid += self.attenuation_fn(d_squared)

        return grid

    def render_downsampled(self) -> np.ndarray:
        """Render and downsample to display resolution"""
        grid = self.render()
        tone_mapped = self.tone_map(grid)

        # Downsample using reshape and mean
        reshaped = tone_mapped.reshape(self.height, self.sim_scale, self.width, self.sim_scale)
        return reshaped.mean(axis=(1, 3)).astype(np.uint8)

    def get_display_buffers(self, num_displays: int) -> list[bytearray]:
        """Get buffers for each display (splits horizontally)"""
        frame = self.render_downsampled()
        buffers = []

        pixels_per_display = self.width // num_displays

        for i in range(num_displays):
            start_x = i * pixels_per_display
            end_x = start_x + pixels_per_display
            display_frame = frame[:, start_x:end_x]
            buffers.append(bytearray(display_frame.flatten().tobytes()))

        return buffers


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

    def get_fps(self) -> float:
        elapsed = time.perf_counter() - self.start_time
        return self.frame_count / elapsed if elapsed > 0 else 0.0


def main():
    parser = argparse.ArgumentParser(description="Metaball animation for DDP displays")
    parser.add_argument("--no-switch", action="store_true", help="Don't auto-switch to DDP plugin")
    parser.add_argument("--displays", nargs="+", default=None, help="Display IP addresses")
    parser.add_argument("--discover", action="store_true", help="Auto-discover displays on network")
    parser.add_argument("--dual", "-d", action="store_true", help="Use dual display mode (32x16)")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"Target FPS (default: {DEFAULT_FPS})")
    parser.add_argument("--balls", type=int, default=DEFAULT_NUM_BALLS, help=f"Number of metaballs (default: {DEFAULT_NUM_BALLS})")
    args = parser.parse_args()

    # Get display list
    if args.discover:
        print("Discovering displays...")
        discovered = discover_displays(protocol="ddp")
        if discovered:
            display_ips = discovered
            print(f"  Found {len(display_ips)} display(s): {', '.join(display_ips)}")
        else:
            print("  No displays found, using defaults")
            display_ips = DISPLAYS
        print()
    elif args.displays:
        display_ips = args.displays
    else:
        display_ips = DISPLAYS

    # Determine display configuration
    if args.dual:
        displays = display_ips[:2]
        num_displays = 2
        width = DISPLAY_SIZE * 2
    else:
        displays = [display_ips[0]]
        num_displays = 1
        width = DISPLAY_SIZE

    height = DISPLAY_SIZE

    print("=" * 50)
    print("Metaball Animation")
    print("=" * 50)
    print(f"Displays: {num_displays}")
    for i, ip in enumerate(displays):
        print(f"  [{i + 1}] {ip}")
    print(f"Resolution: {width}x{height}")
    print(f"Metaballs: {args.balls}")
    print(f"Target FPS: {args.fps}")
    print()

    # Auto-switch to DDP plugin
    if not args.no_switch:
        print("Switching displays to DDP plugin...")
        for ip in displays:
            switch_to_ddp_plugin(ip)
        print()

    # Create simulation
    sim = MetaballSimulation(width, height, num_balls=args.balls)
    timer = FrameTimer(args.fps)

    print("Running... (Ctrl+C to stop)")

    with DDPClient(displays) as client:
        try:
            while True:
                sim.update()
                buffers = sim.get_display_buffers(num_displays)

                # Create packets and send
                packets = [create_packet_from_buffer(buf, push=(num_displays == 1)) for buf in buffers]

                if num_displays > 1:
                    client.send_frame_sync(packets)
                else:
                    client.send_frame(packets)

                timer.wait()

                # Show FPS every second
                if timer.frame_count % args.fps == 0:
                    print(f"\r  FPS: {timer.get_fps():.1f}", end="", flush=True)

        except KeyboardInterrupt:
            print(f"\n\nStopped. Actual FPS: {timer.get_fps():.1f}")


if __name__ == "__main__":
    main()
