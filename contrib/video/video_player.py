#!/usr/bin/env python3
"""
Video player for DDP displays
Plays video files on one or two 16x16 LED matrix displays

Requirements:
    pip install opencv-python numpy websocket-client

Usage:
    # Auto-discover displays
    python video_player.py video.mp4 --discover

    # Single display (scaled to 16x16)
    python video_player.py video.mp4

    # Two displays side by side (scaled to 32x16, split in half)
    python video_player.py video.mp4 --dual --discover

    # Adjust FPS
    python video_player.py video.mp4 --fps 30

    # Loop video
    python video_player.py video.mp4 --loop

    # Don't auto-switch to DDP plugin
    python video_player.py video.mp4 --no-switch
"""

import argparse
import os
import sys
import time

# Add project root to path for ddp import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import cv2
    import numpy as np
except ImportError:
    print("Error: OpenCV and NumPy required")
    print("Install with: pip install opencv-python numpy")
    sys.exit(1)

from ddp import DDPClient, create_packet_from_buffer, DISPLAY_PIXELS, switch_to_ddp_plugin
from discover import discover_displays

# Display configuration
DISPLAYS = ["192.168.40.204", "192.168.40.233"]  # Fallback if discovery fails
DISPLAY_SIZE = 16


class FrameTimer:
    """Precise frame timing"""

    def __init__(self, fps: float):
        self.interval = 1.0 / fps
        self.next_frame = time.perf_counter()
        self.frame_count = 0
        self.start_time = self.next_frame
        self.dropped_frames = 0

    def wait(self) -> bool:
        """Wait for next frame. Returns True if frame was dropped."""
        self.next_frame += self.interval
        now = time.perf_counter()

        if self.next_frame > now:
            sleep_time = self.next_frame - now - 0.001
            if sleep_time > 0:
                time.sleep(sleep_time)
            while time.perf_counter() < self.next_frame:
                pass
            self.frame_count += 1
            return False
        else:
            # Behind schedule
            self.dropped_frames += 1
            self.next_frame = time.perf_counter()
            self.frame_count += 1
            return True

    def get_stats(self) -> tuple[float, int]:
        """Returns (actual_fps, dropped_frames)"""
        elapsed = time.perf_counter() - self.start_time
        fps = self.frame_count / elapsed if elapsed > 0 else 0
        return fps, self.dropped_frames


def frame_to_buffer(frame: np.ndarray) -> bytearray:
    """Convert a 16x16 grayscale frame to DDP buffer"""
    # Ensure correct size
    if frame.shape != (DISPLAY_SIZE, DISPLAY_SIZE):
        frame = cv2.resize(frame, (DISPLAY_SIZE, DISPLAY_SIZE))

    # Flatten to 1D buffer
    return bytearray(frame.flatten().astype(np.uint8))


def process_frame_single(frame: np.ndarray) -> bytearray:
    """Process frame for single display (scale to 16x16)"""
    # Convert to grayscale if needed
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    # Resize to 16x16
    small = cv2.resize(gray, (DISPLAY_SIZE, DISPLAY_SIZE), interpolation=cv2.INTER_AREA)

    return frame_to_buffer(small)


def process_frame_dual(frame: np.ndarray) -> tuple[bytearray, bytearray]:
    """Process frame for dual displays (scale to 32x16, split)"""
    # Convert to grayscale if needed
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    # Resize to 32x16 (two displays side by side)
    wide = cv2.resize(gray, (DISPLAY_SIZE * 2, DISPLAY_SIZE), interpolation=cv2.INTER_AREA)

    # Split into left and right halves
    left = wide[:, :DISPLAY_SIZE]
    right = wide[:, DISPLAY_SIZE:]

    return frame_to_buffer(left), frame_to_buffer(right)


def play_video(
    video_path: str,
    displays: list[str] | None = None,
    dual: bool = False,
    fps: float | None = None,
    loop: bool = False,
    preview: bool = False,
    auto_switch: bool = True,
) -> None:
    """Play video on displays"""
    if displays is None:
        displays = DISPLAYS

    # Auto-switch to DDP plugin
    if auto_switch:
        print("Switching displays to DDP plugin...")
        for ip in (displays if dual else [displays[0]]):
            switch_to_ddp_plugin(ip)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video: {video_path}")
        sys.exit(1)

    # Get video properties
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Use specified FPS or video's native FPS
    target_fps = fps if fps else video_fps

    print(f"Video: {video_path}")
    print(f"  Resolution: {width}x{height}")
    print(f"  Duration: {total_frames / video_fps:.1f}s ({total_frames} frames)")
    print(f"  Video FPS: {video_fps:.1f}")
    print(f"  Target FPS: {target_fps:.1f}")
    print(f"  Mode: {'Dual (32x16)' if dual else 'Single (16x16)'}")
    print(f"  Loop: {'Yes' if loop else 'No'}")
    print()

    display_list = displays if dual else [displays[0]]
    timer = FrameTimer(target_fps)

    with DDPClient(display_list) as client:
        print("Playing... (Ctrl+C to stop)")

        try:
            while True:
                ret, frame = cap.read()

                if not ret:
                    if loop:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        break

                # Process frame
                if dual:
                    buf1, buf2 = process_frame_dual(frame)
                    packet1 = create_packet_from_buffer(buf1, push=False)
                    packet2 = create_packet_from_buffer(buf2, push=False)
                    client.send_frame_sync([packet1, packet2])
                else:
                    buf = process_frame_single(frame)
                    packet = create_packet_from_buffer(buf, push=True)
                    client.send_frame([packet])

                # Optional preview window
                if preview:
                    if dual:
                        preview_frame = cv2.resize(
                            cv2.hconcat(
                                [
                                    np.array(buf1).reshape(16, 16),
                                    np.array(buf2).reshape(16, 16),
                                ]
                            ),
                            (320, 160),
                            interpolation=cv2.INTER_NEAREST,
                        )
                    else:
                        preview_frame = cv2.resize(
                            np.array(buf).reshape(16, 16),
                            (160, 160),
                            interpolation=cv2.INTER_NEAREST,
                        )
                    cv2.imshow("Preview", preview_frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                # Wait for next frame
                timer.wait()

                # Progress
                current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                progress = current_frame / total_frames * 100
                actual_fps, dropped = timer.get_stats()
                print(
                    f"\r  Frame {current_frame}/{total_frames} ({progress:.0f}%) "
                    f"| FPS: {actual_fps:.1f} | Dropped: {dropped}",
                    end="",
                    flush=True,
                )

        except KeyboardInterrupt:
            pass

        finally:
            cap.release()
            if preview:
                cv2.destroyAllWindows()

            actual_fps, dropped = timer.get_stats()
            print(f"\n\nPlayback finished")
            print(f"  Actual FPS: {actual_fps:.1f}")
            print(f"  Dropped frames: {dropped}")


def main():
    parser = argparse.ArgumentParser(description="Play video on DDP LED displays")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument(
        "--dual", "-d", action="store_true", help="Dual display mode (32x16)"
    )
    parser.add_argument("--fps", "-f", type=float, help="Override video FPS")
    parser.add_argument("--loop", "-l", action="store_true", help="Loop video")
    parser.add_argument(
        "--preview", "-p", action="store_true", help="Show preview window"
    )
    parser.add_argument(
        "--no-switch",
        action="store_true",
        help="Don't auto-switch to DDP plugin",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Auto-discover displays on network",
    )
    parser.add_argument(
        "--displays",
        nargs="+",
        default=None,
        help="Display IP addresses",
    )

    args = parser.parse_args()

    # Get display list
    if args.discover:
        print("Discovering displays...")
        discovered = discover_displays(protocol="ddp")
        if discovered:
            displays = discovered
            print(f"  Found {len(displays)} display(s): {', '.join(displays)}")
        else:
            print("  No displays found, using defaults")
            displays = DISPLAYS
        print()
    elif args.displays:
        displays = args.displays
    else:
        displays = DISPLAYS

    play_video(
        args.video,
        displays=displays,
        dual=args.dual,
        fps=args.fps,
        loop=args.loop,
        preview=args.preview,
        auto_switch=not args.no_switch,
    )


if __name__ == "__main__":
    main()
