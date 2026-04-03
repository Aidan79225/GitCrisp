from unittest.mock import MagicMock
from PySide6.QtCore import Qt
from git_gui.domain.entities import FileStatus
from git_gui.presentation.widgets.working_tree_model import WorkingTreeModel


def _make_files():
    return [
        FileStatus(path="src/foo.py", status="staged", delta="modified"),
        FileStatus(path="src/bar.py", status="unstaged", delta="added"),
        FileStatus(path="README.md", status="staged", delta="deleted"),
    ]


def test_row_count(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    assert model.rowCount() == 3


def test_display_role(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    text = model.data(model.index(0), Qt.DisplayRole)
    assert text == "src/foo.py"


def test_check_state_staged(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    assert model.data(model.index(0), Qt.CheckStateRole) == Qt.CheckState.Checked


def test_check_state_unstaged(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    assert model.data(model.index(1), Qt.CheckStateRole) == Qt.CheckState.Unchecked


def test_user_role_returns_file_status(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    fs = model.data(model.index(0), Qt.UserRole)
    assert isinstance(fs, FileStatus)
    assert fs.path == "src/foo.py"


def test_toggle_checkbox_calls_stage(qtbot):
    commands = MagicMock()
    model = WorkingTreeModel(commands)
    model.reload(_make_files())
    model.setData(model.index(1), Qt.CheckState.Checked, Qt.CheckStateRole)
    commands.stage_files.execute.assert_called_once_with(["src/bar.py"])


def test_toggle_checkbox_calls_unstage(qtbot):
    commands = MagicMock()
    model = WorkingTreeModel(commands)
    model.reload(_make_files())
    model.setData(model.index(0), Qt.CheckState.Unchecked, Qt.CheckStateRole)
    commands.unstage_files.execute.assert_called_once_with(["src/foo.py"])


def test_flags_include_checkable(qtbot):
    model = WorkingTreeModel(MagicMock())
    model.reload(_make_files())
    flags = model.flags(model.index(0))
    assert flags & Qt.ItemIsUserCheckable
    assert flags & Qt.ItemIsSelectable
    assert flags & Qt.ItemIsEnabled
