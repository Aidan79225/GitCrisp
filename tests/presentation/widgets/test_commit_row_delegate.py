"""Where CommitRowDelegate puts each piece of a commit inside its row.

The delegate is driven through its real paint() onto an image, with a painter
that also records every text and badge it is asked to draw, so the tests can
check what a user would see: nothing cut off mid-glyph, nothing drawn on top
of something else.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import QStyleOptionViewItem

from git_gui.presentation.models.graph_model import INFO_ROLE, CommitInfo
from git_gui.presentation.widgets.commit_row_delegate import CommitRowDelegate

ROW_HEIGHT = 200
ELLIPSIS = "…"


@dataclass(frozen=True)
class DrawnText:
    text: str
    rect: QRect  # the rect drawText was given; Qt clips the glyphs to it
    bounds: QRect  # where the glyphs land when nothing clips them

    def fits(self) -> bool:
        return self.rect.left() <= self.bounds.left() and self.bounds.right() <= self.rect.right()


class RecordingPainter(QPainter):
    """Paints for real, and remembers every text and badge it was asked to draw."""

    def __init__(self, device: QImage) -> None:
        super().__init__(device)
        self.texts: list[DrawnText] = []
        self.badges: list[tuple[QRect, QColor]] = []

    def drawText(self, rect, flags, text):
        self.texts.append(DrawnText(text, QRect(rect), self.boundingRect(rect, flags, text)))
        super().drawText(rect, flags, text)

    def drawRoundedRect(self, rect, *radii):
        self.badges.append((QRect(rect), self.brush().color()))
        super().drawRoundedRect(rect, *radii)


def _info(**overrides) -> CommitInfo:
    fields = {
        "author": "Aidan Wang <a@example.com>",
        "timestamp": "2026-10-16",
        "short_oid": "bc8a15f6",
        "branch_names": [],
        "head_branch": None,
        "message": "Fix typo",
    }
    fields.update(overrides)
    return CommitInfo(**fields)


def _paint(info: CommitInfo, width: int) -> RecordingPainter:
    model = QStandardItemModel(1, 1)
    item = QStandardItem()
    item.setData(info, INFO_ROLE)
    model.setItem(0, 0, item)
    image = QImage(width, ROW_HEIGHT, QImage.Format_ARGB32)
    painter = RecordingPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, width, ROW_HEIGHT)
    CommitRowDelegate().paint(painter, option, model.index(0, 0))
    painter.end()
    return painter


def _text_width(text: str) -> int:
    """The text's width in the font the delegate paints with."""
    return QFontMetrics(QFont(), QImage(1, 1, QImage.Format_ARGB32)).horizontalAdvance(text)


def _message_lines(painted: RecordingPainter, message: str) -> list[DrawnText]:
    return [t for t in painted.texts if t.text and t.text.removesuffix(ELLIPSIS) in message]


# ── Message ──────────────────────────────────────────────────────────────────


CJK_SUBJECT = "修正圖表在視窗縮小時訊息被截斷而且沒有省略號的問題並且更新相關測試案例與文件說明"


def test_a_subject_without_spaces_wraps_instead_of_being_cut_off(qtbot):
    """CJK has no spaces to break at, so the text has to break inside the run."""
    painted = _paint(_info(message=CJK_SUBJECT), _text_width(CJK_SUBJECT) // 4)

    lines = _message_lines(painted, CJK_SUBJECT)

    assert len(lines) == 3
    assert all(line.fits() for line in lines)
    shown = "".join(line.text.removesuffix(ELLIPSIS) for line in lines)
    assert CJK_SUBJECT.startswith(shown)


def test_a_subject_too_long_for_three_lines_ends_in_an_ellipsis(qtbot):
    painted = _paint(_info(message=CJK_SUBJECT), _text_width(CJK_SUBJECT) // 4)

    assert _message_lines(painted, CJK_SUBJECT)[-1].text.endswith(ELLIPSIS)


def test_a_subject_that_fits_is_drawn_exactly_as_written(qtbot):
    """No ellipsis on a subject that fits, and its double space survives."""
    painted = _paint(_info(message="Fix  typo"), 4 * _text_width("Fix  typo"))

    assert [t.text for t in _message_lines(painted, "Fix  typo")] == ["Fix  typo"]


def test_a_wrapped_subject_with_an_emoji_loses_no_characters(qtbot):
    """Qt counts an emoji as two positions and Python as one; a wrap must not drift."""
    subject = "🎉 Release the notes for the next version of the graph"
    painted = _paint(_info(message=subject), _text_width(subject) * 2 // 3)

    lines = _message_lines(painted, subject)

    assert len(lines) > 1
    assert "".join(line.text for line in lines) == subject
