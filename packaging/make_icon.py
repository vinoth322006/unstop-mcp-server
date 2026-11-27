"""Generate packaging/icon.png (512x512) and packaging/icon.ico with no third-party dependencies.

A blue rounded square with a white "U". Run:  python packaging/make_icon.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 512
S = SIZE / 256  # design coordinates are on a 256 grid
BLUE = (28, 78, 216)
WHITE = (255, 255, 255)


def _inside_rounded(x: float, y: float, size: int, r: float) -> float:
    """Coverage (0..1) of a rounded square, with 1px anti-aliasing."""
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    d = math.hypot(x - cx, y - cy)
    return max(0.0, min(1.0, r - d + 0.5))


def _in_u(x: float, y: float) -> float:
    """Coverage of a thick 'U': two stems joined by a half-ring."""
    left, right, top, bottom, thick = 74 * S, 182 * S, 62 * S, 186 * S, 30 * S
    cx, cy = (left + right) / 2, bottom - (right - left) / 2
    outer, inner = (right - left) / 2, (right - left) / 2 - thick
    if top <= y <= cy:
        if left <= x <= left + thick or right - thick <= x <= right:
            return 1.0
    if y > cy:
        d = math.hypot(x - cx, y - cy)
        return max(0.0, min(1.0, outer - d + 0.5)) * max(0.0, min(1.0, d - inner + 0.5))
    return 0.0


def render() -> bytes:
    rows = []
    for j in range(SIZE):
        row = bytearray([0])  # PNG filter: none
        for i in range(SIZE):
            x, y = i + 0.5, j + 0.5
            a = _inside_rounded(x, y, SIZE, 56 * S)
            u = _in_u(x, y)
            r, g, b = (round(BLUE[k] * (1 - u) + WHITE[k] * u) for k in range(3))
            row += bytes((r, g, b, round(255 * a)))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def to_ico(png: bytes) -> bytes:
    # ICO files may embed a PNG directly (Vista+); width/height 0 means 256.
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    return header + entry + png


if __name__ == "__main__":
    here = Path(__file__).parent
    png = render()
    (here / "icon.png").write_bytes(png)
    SIZE, S = 256, 1.0  # Windows .ico entries top out at 256 px
    (here / "icon.ico").write_bytes(to_ico(render()))
    print(f"wrote {here / 'icon.png'} ({len(png)} bytes) and icon.ico")
