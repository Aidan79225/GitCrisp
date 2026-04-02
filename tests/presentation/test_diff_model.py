from git_gui.domain.entities import FileStatus
from git_gui.presentation.models.diff_model import DiffModel
from PySide6.QtCore import Qt


def _make_file(path, status="staged", delta="modified"):
    return FileStatus(path=path, status=status, delta=delta)


def test_row_count(qtbot):
    model = DiffModel([_make_file("a.py"), _make_file("b.py")])
    assert model.rowCount() == 2


def test_display_role_returns_path(qtbot):
    model = DiffModel([_make_file("src/main.py")])
    assert model.data(model.index(0), Qt.DisplayRole) == "src/main.py"


def test_user_role_returns_file_status(qtbot):
    f = _make_file("src/main.py")
    model = DiffModel([f])
    result = model.data(model.index(0), Qt.UserRole)
    assert result.path == "src/main.py"
    assert result.status == "staged"


def test_empty_model(qtbot):
    model = DiffModel([])
    assert model.rowCount() == 0


def test_invalid_index_returns_none(qtbot):
    model = DiffModel([])
    assert model.data(model.index(99), Qt.DisplayRole) is None
