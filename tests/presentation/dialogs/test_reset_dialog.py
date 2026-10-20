from __future__ import annotations

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel

from git_gui.domain.entities import FileStatus, ResetMode
from git_gui.presentation.dialogs.reset_dialog import ResetDialog


def _status(path: str, status: str = "unstaged", delta: str = "modified") -> FileStatus:
    return FileStatus(path=path, status=status, delta=delta)


def test_default_mode_is_mixed(qtbot):
    dlg = ResetDialog(
        "master", "abc1234", "Initial commit", default_mode=ResetMode.MIXED, dirty_files=[]
    )
    qtbot.addWidget(dlg)
    assert dlg._radio_mixed.isChecked()


def test_pre_selected_hard_mode(qtbot):
    dlg = ResetDialog(
        "master", "abc1234", "Initial commit", default_mode=ResetMode.HARD, dirty_files=[]
    )
    qtbot.addWidget(dlg)
    assert dlg._radio_hard.isChecked()


def test_dirty_file_list_hidden_for_soft(qtbot):
    files = [_status("src/foo.py")]
    dlg = ResetDialog("master", "abc1234", "msg", default_mode=ResetMode.SOFT, dirty_files=files)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._dirty_list.isVisible() is False


def test_dirty_file_list_hidden_for_mixed(qtbot):
    files = [_status("src/foo.py")]
    dlg = ResetDialog("master", "abc1234", "msg", default_mode=ResetMode.MIXED, dirty_files=files)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._dirty_list.isVisible() is False


def test_dirty_file_list_visible_for_hard(qtbot):
    files = [_status("src/foo.py"), _status("src/new.py", status="untracked", delta="added")]
    dlg = ResetDialog("master", "abc1234", "msg", default_mode=ResetMode.HARD, dirty_files=files)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._dirty_list.isVisible() is True
    text = dlg._dirty_list.toPlainText()
    assert "src/foo.py" in text
    assert "src/new.py" in text


def test_hard_with_clean_tree_shows_clean_message(qtbot):
    dlg = ResetDialog("master", "abc1234", "msg", default_mode=ResetMode.HARD, dirty_files=[])
    qtbot.addWidget(dlg)
    dlg.show()
    assert "clean" in dlg._dirty_list.toPlainText().lower()


def test_switching_to_hard_reveals_dirty_list(qtbot):
    files = [_status("src/foo.py")]
    dlg = ResetDialog("master", "abc1234", "msg", default_mode=ResetMode.MIXED, dirty_files=files)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg._dirty_list.isVisible() is False
    dlg._radio_hard.setChecked(True)
    assert dlg._dirty_list.isVisible() is True


def test_result_mode_returns_selected(qtbot):
    dlg = ResetDialog("master", "abc1234", "msg", default_mode=ResetMode.MIXED, dirty_files=[])
    qtbot.addWidget(dlg)
    dlg._radio_soft.setChecked(True)
    assert dlg.result_mode() == ResetMode.SOFT
    dlg._radio_hard.setChecked(True)
    assert dlg.result_mode() == ResetMode.HARD


def _rendered_header(dlg: ResetDialog) -> str:
    header = next(lbl for lbl in dlg.findChildren(QLabel) if lbl.text().startswith("Reset"))
    doc = QTextDocument()
    doc.setHtml(header.text())
    return doc.toPlainText()


def test_header_shows_angle_brackets_in_branch_and_subject_as_text(qtbot):
    dlg = ResetDialog(
        "feat/<wip>",
        "abc1234",
        "Add Option<T> support & a<b",
        default_mode=ResetMode.MIXED,
        dirty_files=[],
    )
    qtbot.addWidget(dlg)
    assert _rendered_header(dlg) == 'Reset feat/<wip> to abc1234 "Add Option<T> support & a<b"'
