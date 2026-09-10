"""Structural tests for the git_gui.presentation.main_window subpackage.

Locks in the mixin-composite layout so future drift is caught:
- MainWindow is importable from the package root.
- Its MRO includes every declared mixin.
- MainWindow itself defines only __init__ + _build_* helpers + any Qt overrides.
- No _on_* or _wire_* method is defined directly on the composite — they
  must all come from mixins.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow


def test_main_window_is_importable_from_package_root():
    from git_gui.presentation.main_window import MainWindow

    assert MainWindow is not None


def test_main_window_mro_includes_all_mixins():
    from git_gui.presentation.main_window import MainWindow
    from git_gui.presentation.main_window.branch_flows import BranchFlowsMixin
    from git_gui.presentation.main_window.cherry_pick_revert_flows import CherryPickRevertFlowsMixin
    from git_gui.presentation.main_window.merge_rebase_flows import MergeRebaseFlowsMixin
    from git_gui.presentation.main_window.reload_coordinator import ReloadCoordinatorMixin
    from git_gui.presentation.main_window.remote_op_queue import RemoteOpQueueMixin
    from git_gui.presentation.main_window.repo_lifecycle import RepoLifecycleMixin
    from git_gui.presentation.main_window.reset_flow import ResetFlowMixin
    from git_gui.presentation.main_window.right_panel import RightPanelMixin
    from git_gui.presentation.main_window.stash_flows import StashFlowsMixin
    from git_gui.presentation.main_window.tag_flows import TagFlowsMixin

    expected = {
        BranchFlowsMixin,
        CherryPickRevertFlowsMixin,
        MergeRebaseFlowsMixin,
        ReloadCoordinatorMixin,
        RemoteOpQueueMixin,
        RepoLifecycleMixin,
        ResetFlowMixin,
        RightPanelMixin,
        StashFlowsMixin,
        TagFlowsMixin,
    }
    missing = expected - set(MainWindow.__mro__)
    assert not missing, f"MainWindow MRO missing mixins: {missing}"
    assert QMainWindow in MainWindow.__mro__, "MainWindow must still inherit from QMainWindow"


def test_main_window_composite_defines_no_handlers_directly():
    """The composite must not define any _on_* or _wire_* method directly.
    All handlers and wiring come from mixins."""
    from git_gui.presentation.main_window import MainWindow

    own_names = list(vars(MainWindow).keys())
    offending = [n for n in own_names if n.startswith("_on_") or n.startswith("_wire_")]
    assert offending == [], (
        f"MainWindow must not define _on_* or _wire_* methods directly; "
        f"move them to the appropriate mixin. Found: {offending}"
    )


def test_main_window_composite_body_matches_allowlist():
    """The composite may only define __init__, _build_* helpers, and Qt
    overrides (methods resolvable on QMainWindow). This prevents flow
    helpers from creeping back onto the composite."""
    from git_gui.presentation.main_window import MainWindow

    own_names = [n for n in vars(MainWindow) if not n.startswith("__")]
    allowed_prefixes = ("_build_",)
    for name in own_names:
        is_build = name.startswith(allowed_prefixes)
        is_qt_override = hasattr(QMainWindow, name)
        assert is_build or is_qt_override, (
            f"MainWindow defines '{name}' directly; "
            f"it must be either a _build_* helper or a Qt override."
        )
