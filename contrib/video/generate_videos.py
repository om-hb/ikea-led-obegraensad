#!/usr/bin/env python3
"""
Generate sample videos optimized for 16x16 LED displays

Usage:
    python generate_videos.py
"""

import math
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    print("Error: OpenCV and NumPy required")
    print("Install with: pip install opencv-python numpy")
    sys.exit(1)


def create_video(filename: str, frames: list[np.ndarray], fps: int = 30):
    """Save frames as video file"""
    height, width = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height), isColor=False)

    for frame in frames:
        out.write(frame)

    out.release()
    print(f"Created: {filename} ({len(frames)} frames, {len(frames)/fps:.1f}s)")


def plasma(size: int = 64, frames: int = 120) -> list[np.ndarray]:
    """Classic plasma effect"""
    result = []
    for t in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)
        for y in range(size):
            for x in range(size):
                v = math.sin(x / 8.0 + t / 10.0)
                v += math.sin((x + y) / 16.0)
                v += math.sin(math.sqrt(x * x + y * y) / 8.0 - t / 10.0)
                v += math.sin(math.sqrt(x * x + y * y + t) / 8.0)
                frame[y, x] = int((v + 4) / 8 * 255)
        result.append(frame)
    return result


def bouncing_ball(size: int = 64, frames: int = 120) -> list[np.ndarray]:
    """Bouncing ball animation"""
    result = []
    x, y = size // 4, size // 4
    vx, vy = 3, 2
    radius = size // 8

    for _ in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)

        # Update position
        x += vx
        y += vy

        # Bounce off walls
        if x - radius < 0 or x + radius >= size:
            vx = -vx
            x = max(radius, min(size - radius - 1, x))
        if y - radius < 0 or y + radius >= size:
            vy = -vy
            y = max(radius, min(size - radius - 1, y))

        # Draw ball
        cv2.circle(frame, (int(x), int(y)), radius, 255, -1)
        result.append(frame)

    return result


def spinning_line(size: int = 64, frames: int = 120) -> list[np.ndarray]:
    """Rotating line"""
    result = []
    center = size // 2
    length = size // 2 - 2

    for t in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)
        angle = t * 2 * math.pi / 60  # One rotation per 60 frames

        x1 = int(center + length * math.cos(angle))
        y1 = int(center + length * math.sin(angle))
        x2 = int(center - length * math.cos(angle))
        y2 = int(center - length * math.sin(angle))

        cv2.line(frame, (x1, y1), (x2, y2), 255, 2)
        result.append(frame)

    return result


def expanding_circles(size: int = 64, frames: int = 120) -> list[np.ndarray]:
    """Expanding circles from center"""
    result = []
    center = size // 2

    for t in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)

        for i in range(4):
            radius = ((t * 2 + i * 15) % 60)
            if radius > 0:
                brightness = 255 - int(radius * 4)
                if brightness > 0:
                    cv2.circle(frame, (center, center), radius, brightness, 2)

        result.append(frame)

    return result


def matrix_rain(size: int = 64, frames: int = 150) -> list[np.ndarray]:
    """Matrix-style falling characters"""
    result = []
    columns = size // 4
    drops = [0] * columns

    for _ in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)

        for i, drop in enumerate(drops):
            x = i * 4 + 2

            # Draw trail
            for j in range(8):
                y = int(drop) - j * 4
                if 0 <= y < size:
                    brightness = 255 - j * 30
                    if brightness > 0:
                        cv2.rectangle(frame, (x - 1, y - 2), (x + 1, y + 2), brightness, -1)

            # Update drop
            drops[i] += 1.5
            if drops[i] > size + 32:
                drops[i] = -np.random.randint(0, 20)

        result.append(frame)

    return result


def wave_pattern(size: int = 64, frames: int = 120) -> list[np.ndarray]:
    """Horizontal wave pattern"""
    result = []

    for t in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)

        for x in range(size):
            y = int(size / 2 + (size / 4) * math.sin(x / 8.0 + t / 10.0))
            cv2.circle(frame, (x, y), 2, 255, -1)

        result.append(frame)

    return result


def checkerboard_zoom(size: int = 64, frames: int = 120) -> list[np.ndarray]:
    """Zooming checkerboard"""
    result = []

    for t in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)
        scale = 4 + 3 * math.sin(t / 20.0)

        for y in range(size):
            for x in range(size):
                if (int(x / scale) + int(y / scale)) % 2 == 0:
                    frame[y, x] = 255

        result.append(frame)

    return result


def starfield(size: int = 64, frames: int = 180) -> list[np.ndarray]:
    """3D starfield effect"""
    result = []
    num_stars = 50
    stars = [(np.random.uniform(-1, 1), np.random.uniform(-1, 1), np.random.uniform(0.1, 1)) for _ in range(num_stars)]
    center = size // 2

    for _ in range(frames):
        frame = np.zeros((size, size), dtype=np.uint8)

        new_stars = []
        for sx, sy, sz in stars:
            # Move star closer
            sz -= 0.02

            if sz <= 0:
                # Reset star
                sx, sy, sz = np.random.uniform(-1, 1), np.random.uniform(-1, 1), 1.0

            # Project to 2D
            x = int(center + sx / sz * center)
            y = int(center + sy / sz * center)

            if 0 <= x < size and 0 <= y < size:
                brightness = int(255 * (1 - sz))
                radius = max(1, int(3 * (1 - sz)))
                cv2.circle(frame, (x, y), radius, brightness, -1)

            new_stars.append((sx, sy, sz))

        stars = new_stars
        result.append(frame)

    return result


def main():
    print("Generating sample videos for 16x16 LED displays...")
    print()

    generators = [
        ("plasma.mp4", plasma, "Plasma effect"),
        ("bouncing_ball.mp4", bouncing_ball, "Bouncing ball"),
        ("spinning_line.mp4", spinning_line, "Spinning line"),
        ("circles.mp4", expanding_circles, "Expanding circles"),
        ("matrix.mp4", matrix_rain, "Matrix rain"),
        ("wave.mp4", wave_pattern, "Wave pattern"),
        ("checkerboard.mp4", checkerboard_zoom, "Checkerboard zoom"),
        ("starfield.mp4", starfield, "3D Starfield"),
    ]

    for filename, generator, description in generators:
        print(f"Generating {description}...")
        frames = generator(size=64, frames=120)
        create_video(filename, frames, fps=30)

    print()
    print("Done! Play videos with:")
    print("  python video_player.py plasma.mp4 --loop")
    print("  python video_player.py plasma.mp4 --dual --loop")


if __name__ == "__main__":
    main()
