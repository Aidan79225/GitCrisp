"""Signal-contract tests for AddWorktreeDialog."""
from __future__ import annotations

from git_gui.presentation.dialogs.add_worktree_dialog import AddWorktreeDialog


def _open_dialog(qtbot, *, repo_path="/tmp/repo", branches=None,
                 in_use=None, preselect=None, default_create=False):
    dlg = AddWorktreeDialog(
        repo_path=repo_path,
        branches=branches or ["master", "feat/a", "feat/b"],
        branches_in_use={} if in_use is None else in_use,
        preselect_branch=preselect,
        default_create_new=default_create,
    )
    qtbot.addWidget(dlg)
    return dlg


def test_default_path_template_updates_with_branch_selection(qtbot):
    dlg = _open_dialog(qtbot, repo_path="/tmp/myrepo",
                      branches=["master", "feat/a"], preselect="feat/a")
    assert dlg.location() == "/tmp/myrepo-feat-a"


def test_manual_path_edit_pins_value(qtbot):
    dlg = _open_dialog(qtbot, repo_path="/tmp/myrepo", branches=["master", "x"])
    dlg.set_location("/custom/path")
    dlg.select_branch("x")
    assert dlg.location() == "/custom/path"


def test_create_new_toggle_flips_to_name_field(qtbot):
    dlg = _open_dialog(qtbot)
    dlg.set_create_new(True)
    assert dlg.is_create_new() is True
    dlg.set_new_branch_name("feat/z")
    dlg.set_base_ref("master")
    assert dlg.new_branch_name() == "feat/z"
    assert dlg.base_ref() == "master"


def test_branches_in_use_are_disabled_with_tooltip(qtbot):
    dlg = _open_dialog(
        qtbot,
        branches=["master", "feat/a", "feat/b"],
        in_use={"feat/a": "/tmp/wt-feat-a"},
    )
    assert dlg.branch_disabled("feat/a") is True
    tooltip = dlg.branch_tooltip("feat/a") or ""
    assert "/tmp/wt-feat-a" in tooltip


def test_submit_emits_add_requested_with_values(qtbot):
    dlg = _open_dialog(qtbot, branches=["master"], preselect="master")
    dlg.set_location("/tmp/x")
    received: list = []
    dlg.add_requested.connect(lambda v: received.append(v))
    with qtbot.waitSignal(dlg.add_requested, timeout=1000):
        dlg.submit()
    assert received and received[0] == {
        "branch": "master",
        "create_new": False,
        "base_ref": None,
        "location": "/tmp/x",
        "switch_after": True,
    }


def test_submit_with_create_new_emits_correct_payload(qtbot):
    dlg = _open_dialog(qtbot, branches=["master"])
    dlg.set_create_new(True)
    dlg.set_new_branch_name("feat/new")
    dlg.set_base_ref("master")
    dlg.set_location("/tmp/wt-feat-new")
    received: list = []
    dlg.add_requested.connect(lambda v: received.append(v))
    dlg.submit()
    assert received[0]["branch"] == "feat/new"
    assert received[0]["create_new"] is True
    assert received[0]["base_ref"] == "master"
    assert received[0]["location"] == "/tmp/wt-feat-new"


def test_add_button_disabled_until_valid(qtbot):
    dlg = _open_dialog(qtbot, branches=["master"])
    dlg.set_location("")
    assert dlg.add_button_enabled() is False
    dlg.set_location("/tmp/x")
    assert dlg.add_button_enabled() is True
