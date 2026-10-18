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


# ── Ref badges and the sha ───────────────────────────────────────────────────


SHA = "bc8a15f6"
LONG_BRANCH = "claude/code-review-loop-refactor"
LONG_REMOTE = "origin/claude/code-review-loop-refactor"


def _drawn(painted: RecordingPainter, text: str) -> DrawnText:
    return next(t for t in painted.texts if t.text == text)


def _badge_labels(painted: RecordingPainter) -> list[DrawnText]:
    badge_rects = [rect for rect, _ in painted.badges]
    return [t for t in painted.texts if t.rect in badge_rects]


def test_a_badge_wider_than_the_room_left_of_the_sha_stays_clear_of_it(qtbot):
    info = _info(branch_names=[LONG_BRANCH], head_branch=LONG_BRANCH, short_oid=SHA)
    width = _text_width(SHA) + _text_width(LONG_BRANCH) // 2

    painted = _paint(info, width)

    sha = _drawn(painted, SHA).bounds
    assert painted.badges
    assert not any(rect.intersects(sha) for rect, _ in painted.badges)


def test_a_badge_wider_than_the_row_is_elided_not_cut_mid_glyph(qtbot):
    info = _info(branch_names=[LONG_BRANCH, LONG_REMOTE], short_oid=SHA)
    width = _text_width(LONG_REMOTE) // 2

    painted = _paint(info, width)

    assert len(painted.badges) == 2
    assert all(rect.left() >= 0 and rect.right() < width for rect, _ in painted.badges)
    labels = _badge_labels(painted)
    assert all(label.fits() for label in labels)
    assert all(label.text.endswith(ELLIPSIS) for label in labels)


def test_badges_that_fit_are_drawn_whole(qtbot):
    info = _info(branch_names=["main", "origin/main"], short_oid=SHA)

    painted = _paint(info, 4 * _text_width(f"main origin/main {SHA}"))

    assert [label.text for label in _badge_labels(painted)] == ["main", "origin/main"]


# ── Author and date ──────────────────────────────────────────────────────────


AUTHOR = "Aidan Wang"
DATE = "2026-10-16"


def _drawn_author(painted: RecordingPainter) -> DrawnText:
    return next(
        t for t in painted.texts if t.text and AUTHOR.startswith(t.text.removesuffix(ELLIPSIS))
    )


def test_the_author_is_elided_before_it_reaches_the_date(qtbot):
    """A deep lane indent leaves the header too narrow for both in full."""
    info = _info(author=f"{AUTHOR} <a@example.com>", timestamp=DATE)

    painted = _paint(info, _text_width(AUTHOR + DATE) * 3 // 4)

    author = _drawn_author(painted)
    assert not author.bounds.intersects(_drawn(painted, DATE).bounds)
    assert author.text.endswith(ELLIPSIS)


def test_an_author_that_fits_beside_the_date_is_drawn_whole(qtbot):
    info = _info(author=f"{AUTHOR} <a@example.com>", timestamp=DATE)

    painted = _paint(info, 2 * _text_width(AUTHOR + DATE))

    assert _drawn_author(painted).text == AUTHOR


# ── Badge colours ────────────────────────────────────────────────────────────


def test_a_local_branch_with_a_slash_is_not_painted_as_a_remote(qtbot):
    from git_gui.presentation.theme import ColorRole, get_theme_manager

    colors = get_theme_manager().current.colors
    info = _info(
        branch_names=["feature/login", "origin/main"],
        remote_branches=frozenset({"origin/main"}),
    )

    painted = _paint(info, 4 * _text_width(f"feature/login origin/main {SHA}"))

    assert [colour for _, colour in painted.badges] == [
        colors.as_qcolor(ColorRole.REF_BADGE_BRANCH_BG),
        colors.as_qcolor(ColorRole.REF_BADGE_REMOTE_BG),
    ]


# ── Row height ───────────────────────────────────────────────────────────────


def _row_height(info: CommitInfo, width: int) -> int:
    """The height the delegate asks the view to give this row."""
    model = QStandardItemModel(1, 1)
    item = QStandardItem()
    item.setData(info, INFO_ROLE)
    model.setItem(0, 0, item)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, width, 0)
    option.fontMetrics = QFontMetrics(QFont(), QImage(1, 1, QImage.Format_ARGB32))
    return CommitRowDelegate().sizeHint(option, model.index(0, 0)).height()


def test_a_row_whose_badges_wrap_still_has_room_for_its_last_message_line(qtbot):
    """sizeHint and paint each work out the layout; they must agree on its height."""
    info = _info(branch_names=[LONG_BRANCH, LONG_REMOTE], short_oid=SHA, message=CJK_SUBJECT)
    width = _text_width(LONG_REMOTE) + _text_width(SHA)

    painted = _paint(info, width)

    assert len({rect.top() for rect, _ in painted.badges}) == 2
    last_line = _message_lines(painted, CJK_SUBJECT)[-1]
    assert last_line.rect.bottom() < _row_height(info, width)
