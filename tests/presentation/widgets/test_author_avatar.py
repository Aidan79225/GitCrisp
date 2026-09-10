"""Tests for author_avatar: initials extraction, color assignment, paint_avatar."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from git_gui.presentation.widgets.author_avatar import (
    _color_for_author,
    _initials,
    paint_avatar,
)


class TestInitials:
    def test_full_name(self):
        assert _initials("Alice Wang") == "AW"

    def test_full_name_with_email(self):
        assert _initials("Alice Wang <alice@example.com>") == "AW"

    def test_single_name(self):
        assert _initials("Alice") == "A"

    def test_single_name_with_email(self):
        assert _initials("Alice <a@a.com>") == "A"

    def test_three_part_name(self):
        assert _initials("Alice B. Wang") == "AW"

    def test_empty_string(self):
        assert _initials("") == "?"

    def test_only_email(self):
        assert _initials("<alice@example.com>") == "?"

    def test_uppercase(self):
        assert _initials("alice wang") == "AW"


class TestColorForAuthor:
    def test_returns_qcolor(self):
        c = _color_for_author("Alice")
        assert isinstance(c, QColor)
        assert c.isValid()

    def test_deterministic(self):
        c1 = _color_for_author("Alice Wang <alice@x.com>")
        c2 = _color_for_author("Alice Wang <alice@x.com>")
        assert c1 == c2

    def test_different_authors_may_differ(self):
        c1 = _color_for_author("Alice")
        c2 = _color_for_author("Bob")
        # Not guaranteed to differ, but at least both should be valid
        assert c1.isValid()
        assert c2.isValid()


class TestPaintAvatar:
    def test_paint_does_not_crash(self):
        img = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        rect = QRect(0, 0, 64, 64)
        paint_avatar(painter, rect, "Alice Wang <a@a.com>")
        painter.end()

    def test_paint_fills_center_pixel(self):
        img = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        paint_avatar(painter, QRect(0, 0, 64, 64), "Bob")
        painter.end()
        center = img.pixelColor(32, 32)
        assert center.alpha() > 0

    def test_paint_small_rect(self):
        img = QImage(16, 16, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        paint_avatar(painter, QRect(0, 0, 16, 16), "X")
        painter.end()
        center = img.pixelColor(8, 8)
        assert center.alpha() > 0
