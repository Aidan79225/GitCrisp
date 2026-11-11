"""Operations that run in the remote-op slot say so when it is busy.

The slot runs one op at a time and drops a request made while one runs.
Interactive rebase and remote-branch delete both ask the user first, so
they check the slot before asking rather than lose what was confirmed.
Deleting a tag asks first too, but only its remote half needs the slot:
while it is busy the prompt withholds that choice and keeps the local one.
"""

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QMessageBox

from tests.presentation.window_helpers import wired_window

_REBASE_DLG = "git_gui.presentation.main_window.merge_rebase_flows.InteractiveRebaseDialog"


def _busy_window(qtbot):
    win = wired_window(qtbot)
    win._log_panel = MagicMock()
    win._remote_running = True
    return win


def _tag_on_origin(win) -> None:
    """Make the tag cache list v1 on origin, as an earlier fetch or tag push does."""
    win._repo_path = "/repo"
    win._remote_tag_cache = MagicMock()
    win._remote_tag_cache.load.return_value = {"origin": ["v1"]}


def _button(box: QMessageBox, text: str):
    return next(b for b in box.buttons() if b.text() == text)


def _cancel(box: QMessageBox):
    return box.button(QMessageBox.Cancel)


def _delete_tag_v1(win, choose) -> dict:
    """Delete tag v1, clicking the prompt button *choose*(box) picks.

    Returns what the prompt showed.
    """
    shown: dict = {}

    def _exec(box: QMessageBox) -> int:
        shown["enabled"] = {b.text(): b.isEnabled() for b in box.buttons()}
        shown["informative"] = box.informativeText()
        shown["cancel_is_default"] = box.defaultButton() is _cancel(box)
        choose(box).click()
        return 0

    with patch.object(QMessageBox, "exec", _exec), patch.object(win, "_reload"):
        win._on_delete_tag("v1")
    return shown


def test_interactive_rebase_is_not_offered_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    with patch(_REBASE_DLG) as dialog_cls:
        win._on_interactive_rebase_commit("a" * 40)
    dialog_cls.assert_not_called()
    win._commands.interactive_rebase.execute.assert_not_called()
    assert "skipped" in win._log_panel.log_error.call_args.args[0]


def test_remote_branch_delete_is_not_confirmed_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question:
        win._on_delete_remote_branch("origin", "topic")
    question.assert_not_called()
    win._commands.delete_remote_branch.execute.assert_not_called()
    assert "skipped" in win._log_panel.log_error.call_args.args[0]


def test_a_free_slot_lets_the_op_through_without_a_message(qtbot):
    win = _busy_window(qtbot)
    win._remote_running = False
    assert win._remote_slot_busy("Fetch origin") is False
    win._log_panel.log_error.assert_not_called()


def test_a_skipped_interactive_rebase_names_the_op_that_holds_the_slot(qtbot):
    win = _busy_window(qtbot)
    win._remote_op_name = "Fetch origin"
    with patch(_REBASE_DLG):
        win._on_interactive_rebase_commit("a" * 40)
    assert "Fetch origin" in win._log_panel.log_error.call_args.args[0]


def test_a_skipped_remote_branch_delete_names_the_op_that_holds_the_slot(qtbot):
    win = _busy_window(qtbot)
    win._remote_op_name = "Fetch origin"
    win._on_delete_remote_branch("origin", "topic")
    assert "Fetch origin" in win._log_panel.log_error.call_args.args[0]


def test_delete_tag_does_not_offer_the_remote_delete_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    _tag_on_origin(win)

    shown = _delete_tag_v1(win, _cancel)

    assert shown["enabled"]["Local + remote"] is False
    assert shown["enabled"]["Local only"] is True
    win._commands.delete_tag.execute.assert_not_called()
    win._log_panel.log_error.assert_not_called()  # nothing was confirmed, so nothing is skipped


def test_the_tag_prompt_names_the_op_that_holds_the_slot(qtbot):
    win = _busy_window(qtbot)
    win._remote_op_name = "Fetch origin"
    _tag_on_origin(win)

    shown = _delete_tag_v1(win, _cancel)

    assert "Fetch origin" in shown["informative"]


def test_the_tag_prompt_defaults_to_cancel_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    _tag_on_origin(win)

    assert _delete_tag_v1(win, _cancel)["cancel_is_default"] is True


def test_the_running_op_is_named_the_same_way_in_every_message_about_a_busy_slot(qtbot):
    win = _busy_window(qtbot)
    assert win._running_remote_op_name() == "another remote operation"
    win._remote_op_name = "Fetch origin"
    assert win._running_remote_op_name() == "Fetch origin"


def test_a_local_only_tag_delete_still_runs_while_a_remote_op_runs(qtbot):
    win = _busy_window(qtbot)
    _tag_on_origin(win)

    _delete_tag_v1(win, lambda box: _button(box, "Local only"))

    win._commands.delete_tag.execute.assert_called_once_with("v1")
    win._commands.delete_remote_tag.execute.assert_not_called()


def test_a_free_slot_offers_both_tag_deletes(qtbot):
    win = _busy_window(qtbot)
    win._remote_running = False
    _tag_on_origin(win)

    shown = _delete_tag_v1(win, _cancel)

    assert shown["enabled"]["Local + remote"] is True
    assert shown["enabled"]["Local only"] is True


def test_a_remote_op_that_starts_while_the_tag_prompt_is_open_still_stops_the_remote_delete(qtbot):
    win = _busy_window(qtbot)
    win._remote_running = False
    _tag_on_origin(win)

    def _fetch_starts_then_remote_delete_is_chosen(box: QMessageBox):
        win._remote_running = True
        win._remote_op_name = "Fetch origin"
        return _button(box, "Local + remote")

    _delete_tag_v1(win, _fetch_starts_then_remote_delete_is_chosen)

    win._commands.delete_tag.execute.assert_not_called()
    assert "Fetch origin" in win._log_panel.log_error.call_args.args[0]
