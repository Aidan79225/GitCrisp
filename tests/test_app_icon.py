"""Checks on the app icon and the two raster containers built from it.

The .ico is embedded into the Windows exe and the .icns is what Finder reads
off the macOS bundle, so neither is exercised by a Linux CI run or by any test
that launches the app — a corrupt or stale container would first be noticed by
a user looking at a release. These tests stand in for that.

Both containers are generated from arts/gitcrisp.svg by scripts/build_icons.py
and committed, so the failure mode they guard hardest against is drift: the SVG
gets edited and the script is not re-run.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage

ARTS = Path(__file__).resolve().parent.parent / "arts"
SVG = ARTS / "gitcrisp.svg"
ICO = ARTS / "gitcrisp.ico"
ICNS = ARTS / "gitcrisp.icns"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_TYPES = {
    "ic11": 32,
    "ic12": 64,
    "ic07": 128,
    "ic13": 256,
    "ic08": 256,
    "ic14": 512,
    "ic09": 512,
    "ic10": 1024,
}

# In-sync renders of the same artwork score about 0.4 on the coarse comparison
# below; a different image entirely scores in the tens. 8 sits an order of
# magnitude clear of both.
DRIFT_THRESHOLD = 8.0


def _icns_chunks() -> dict[str, QImage]:
    """Walk the icns container the way macOS does, decoding each PNG payload."""
    data = ICNS.read_bytes()
    assert data[:4] == b"icns", "missing icns magic"
    assert struct.unpack(">I", data[4:8])[0] == len(data), (
        "icns header length disagrees with the file size — the container is "
        "truncated, and macOS reads it by that length"
    )
    chunks: dict[str, QImage] = {}
    offset = 8
    while offset < len(data):
        ostype = data[offset : offset + 4].decode("ascii")
        length = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        image = QImage()
        image.loadFromData(data[offset + 8 : offset + length], "PNG")
        chunks[ostype] = image
        offset += length
    return chunks


def _coarse_diff(a: QImage, b: QImage, n: int = 16) -> float:
    """Mean per-channel difference of two renders reduced to n x n.

    Shrinking first is the point: it washes out the antialiasing that makes two
    rasterisers disagree on a sharp corner, leaving only a difference in the
    artwork itself.
    """
    scaled = [
        img.convertToFormat(QImage.Format_RGB32).scaled(
            n, n, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        for img in (a, b)
    ]
    total = 0
    for y in range(n):
        for x in range(n):
            pa, pb = (img.pixelColor(x, y) for img in scaled)
            total += (
                abs(pa.red() - pb.red()) + abs(pa.green() - pb.green()) + abs(pa.blue() - pb.blue())
            )
    return total / (n * n * 3)


def test_qt_can_rasterise_the_icon_svg(qapp):
    """Qt implements only SVG Tiny 1.2, and main.py hands it this file.

    The mark uses gradients and a filled path, all of which Tiny 1.2 covers —
    but a future edit reaching for a filter or a pattern would render blank
    here while still looking right in a browser.
    """
    icon = QIcon(str(SVG))
    for size in (16, 32, 64, 256):
        pixmap = icon.pixmap(QSize(size, size))
        assert not pixmap.isNull(), f"Qt rendered nothing at {size}px"
        assert pixmap.size() == QSize(size, size)
        image = pixmap.toImage()
        colours = {image.pixel(x, y) for x in range(0, size, 4) for y in range(0, size, 4)}
        assert len(colours) > 1, f"{size}px render is a single flat colour"


def test_ico_carries_every_size_windows_asks_for(qapp):
    reader = QIcon(str(ICO))
    have = {size.width() for size in reader.availableSizes()}
    assert set(ICO_SIZES) <= have, f"missing sizes in the .ico: {set(ICO_SIZES) - have}"


def test_icns_chunks_decode_at_the_size_their_ostype_promises(qapp):
    chunks = _icns_chunks()
    assert set(chunks) == set(ICNS_TYPES), (
        f"icns OSTypes differ from what scripts/build_icons.py writes: {set(chunks)}"
    )
    for ostype, expected in ICNS_TYPES.items():
        image = chunks[ostype]
        assert not image.isNull(), f"{ostype} is not a readable PNG"
        assert image.width() == image.height() == expected, (
            f"{ostype} should be {expected}px, got {image.width()}x{image.height()}"
        )


@pytest.mark.parametrize("container", ["ico", "icns"])
def test_generated_icons_still_match_the_svg(qapp, container):
    """The containers are committed, so nothing forces them to be regenerated.

    Re-run scripts/build_icons.py after editing arts/gitcrisp.svg.
    """
    rendered = QIcon(str(SVG)).pixmap(QSize(64, 64)).toImage()
    if container == "ico":
        packaged = QIcon(str(ICO)).pixmap(QSize(64, 64)).toImage()
    else:
        packaged = _icns_chunks()["ic12"]

    drift = _coarse_diff(rendered, packaged)
    assert drift < DRIFT_THRESHOLD, (
        f"arts/gitcrisp.{container} no longer looks like arts/gitcrisp.svg "
        f"(drift {drift:.1f}). Re-run: uv run scripts/build_icons.py"
    )


def test_main_gives_the_running_app_a_window_icon():
    """Without this a Linux window manager that cannot match the window to its
    .desktop entry shows a generic placeholder while the app is running."""
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    assert "setWindowIcon" in source
    assert 'get_resource_path("arts") / "gitcrisp.svg"' in source, (
        "the window icon must resolve through get_resource_path so it is found "
        "inside a PyInstaller bundle, not just from a source checkout"
    )
