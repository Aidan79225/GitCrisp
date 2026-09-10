"""Tests for IdentityDialog (inline prompt for missing git identity)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QWidget

from git_gui.presentation.dialogs.identity_dialog import IdentityDialog, ensure_identity


def _app():
    return QApplication.instance() or QApplication([])


def test_initial_empty_disables_ok(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    assert not ok_btn.isEnabled()


def test_filling_both_fields_enables_ok(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    dlg._name_edit.setText("Alice")
    dlg._email_edit.setText("alice@example.com")
    assert ok_btn.isEnabled()


def test_partial_initial_prefills_existing_field(qtbot):
    _app()
    dlg = IdentityDialog("Alice", None)
    qtbot.addWidget(dlg)
    assert dlg._name_edit.text() == "Alice"
    assert dlg._email_edit.text() == ""


def test_values_returns_trimmed_text_and_global_flag(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    dlg._name_edit.setText("  Alice  ")
    dlg._email_edit.setText("  alice@example.com  ")
    dlg._global_check.setChecked(True)
    name, email, global_ = dlg.values()
    assert name == "Alice"
    assert email == "alice@example.com"
    assert global_ is True


def test_global_checkbox_defaults_off(qtbot):
    _app()
    dlg = IdentityDialog(None, None)
    qtbot.addWidget(dlg)
    assert dlg._global_check.isChecked() is False


def _make_buses(identity: tuple[str | None, str | None]):
    queries = MagicMock()
    queries.get_identity.execute.return_value = identity
    commands = MagicMock()
    return queries, commands


def test_ensure_identity_returns_true_when_already_set(qtbot):
    _app()
    parent = QWidget()
    qtbot.addWidget(parent)
    queries, commands = _make_buses(("Alice", "alice@example.com"))
    with patch.object(IdentityDialog, "exec") as exec_:
        assert ensure_identity(parent, queries, commands) is True
    exec_.assert_not_called()
    commands.set_identity.execute.assert_not_called()


def test_ensure_identity_saves_when_user_confirms(qtbot):
    _app()
    parent = QWidget()
    qtbot.addWidget(parent)
    queries, commands = _make_buses((None, None))
    mock_dlg = MagicMock()
    mock_dlg.exec.return_value = QDialog.Accepted
    mock_dlg.values.return_value = ("Bob", "bob@example.com", True)
    with patch(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        return_value=mock_dlg,
    ):
        assert ensure_identity(parent, queries, commands) is True
    commands.set_identity.execute.assert_called_once_with("Bob", "bob@example.com", True)


def test_ensure_identity_returns_false_when_user_cancels(qtbot):
    _app()
    parent = QWidget()
    qtbot.addWidget(parent)
    queries, commands = _make_buses((None, None))
    mock_dlg = MagicMock()
    mock_dlg.exec.return_value = QDialog.Rejected
    with patch(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        return_value=mock_dlg,
    ):
        assert ensure_identity(parent, queries, commands) is False
    commands.set_identity.execute.assert_not_called()


def test_ensure_identity_returns_false_when_save_fails(qtbot):
    _app()
    parent = QWidget()
    qtbot.addWidget(parent)
    queries, commands = _make_buses((None, None))
    commands.set_identity.execute.side_effect = RuntimeError("disk full")
    mock_dlg = MagicMock()
    mock_dlg.exec.return_value = QDialog.Accepted
    mock_dlg.values.return_value = ("Bob", "bob@example.com", False)
    with patch(
        "git_gui.presentation.dialogs.identity_dialog.IdentityDialog",
        return_value=mock_dlg,
    ):
        assert ensure_identity(parent, queries, commands) is False
