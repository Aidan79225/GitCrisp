# /// script
# requires-python = ">=3.13"
# dependencies = ["cairosvg>=2.7", "pillow>=11"]
# ///
"""Render arts/gitcrisp.svg into the packaged icon containers.

PyInstaller needs a .ico to embed in the Windows exe and a .icns for the macOS
bundle; neither can be a vector. Both are generated here and committed, rather
than built in release.yml, so the release job stays free of a rasteriser on
three different runners. Re-run after editing the SVG:

    uv run scripts/build_icons.py

The .icns container is written by hand instead of shelling out to `iconutil`,
which only exists on macOS — this way the icons can be regenerated from any
machine that can run the script at all.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "arts" / "gitcrisp.svg"

# Windows reads whichever of these matches the display density it needs.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# OSType -> pixel size. These are the PNG-carrying types; the legacy raw-bitmap
# ones (is32/il32 and their masks) are not written, and macOS has not needed
# them since 10.7. 16pt and 32pt are covered by their @2x entries (ic11/ic12),
# which macOS downscales for a 1x display.
ICNS_TYPES = {
    b"ic11": 32,  # 16pt @2x
    b"ic12": 64,  # 32pt @2x
    b"ic07": 128,  # 128pt @1x
    b"ic13": 256,  # 128pt @2x
    b"ic08": 256,  # 256pt @1x
    b"ic14": 512,  # 256pt @2x
    b"ic09": 512,  # 512pt @1x
    b"ic10": 1024,  # 512pt @2x
}


def render(size: int) -> Image.Image:
    png = cairosvg.svg2png(url=str(SVG), output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def write_ico(path: Path) -> None:
    largest = render(max(ICO_SIZES))
    largest.save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])


def write_icns(path: Path) -> None:
    entries = bytearray()
    for ostype, size in ICNS_TYPES.items():
        buf = io.BytesIO()
        render(size).save(buf, format="PNG")
        payload = buf.getvalue()
        entries += ostype + struct.pack(">I", 8 + len(payload)) + payload
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(entries)) + bytes(entries))


def main() -> None:
    ico, icns = SVG.with_suffix(".ico"), SVG.with_suffix(".icns")
    write_ico(ico)
    write_icns(icns)
    for out in (ico, icns):
        with Image.open(out) as im:
            sizes = sorted({s[0] for s in getattr(im, "info", {}).get("sizes", [im.size])})
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size:,} bytes, sizes {sizes}")


if __name__ == "__main__":
    main()
