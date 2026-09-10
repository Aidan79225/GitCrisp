# `MainWindow` Split — Design

**Date:** 2026-04-18
**Status:** Proposed

## Goal

Break `git_gui/presentation/main_window.py` (969 LOC, 69 methods, 51 `_on_*` handlers) into ten focused mixin modules so no single file exceeds ~150 lines of concern-specific code. External behavior is unchanged — `MainWindow` still imports from the same package path and exposes the same constructor and handler semantics.

## Scope

- Create `git_gui/presentation/main_window/` subpackage containing the composite `MainWindow` class + ten mixin modules.
- Delete the old flat `git_gui/presentation/main_window.py`.
- Update `main.py` to import `MainWindow` from the new subpackage path.
- Add two structural tests (package import + MRO + composite-discipline guard) matching the pattern established by the pygit2 split.

## UX Decisions

| Concern | Decision |
|---|---|
| Split style | Mixins, consistent with `git_gui/infrastructure/pygit2/`. `MainWindow(QMainWindow, <mixins>)` via Python MRO. |
| Where signal wiring lives | Each mixin owns `_wire_<concern>_signals()`. `MainWindow.__init__` calls them in a fixed order after widget construction. |
| Shared instance state | Stays on `MainWindow` — `_queries`, `_commands`, `_repo_path`, `_remote_running`, `_selected_oid`, widget refs, `_repo_ready_signals`. Mixins access via `self.`. |
| External API | Unchanged. `from git_gui.presentation.main_window import MainWindow` continues to work because the subpackage's `__init__.py` re-exports. |
| Alternatives considered | Presenter / delegate classes rejected — would require injecting a bus swap on every repo switch and fragment signal wiring. |
| Scope of change | One PR. Sequence of mechanical per-mixin extractions with the 502-test suite as the safety net. |
| Widget construction | Stays on `MainWindow` in `_build_chrome / _build_widgets / _build_layout / _build_shortcuts`. Not fragmented across mixins. |

## Approach

Each concern group becomes a mixin class in its own file under `git_gui/presentation/main_window/`. `MainWindow` inherits from `QMainWindow` and all ten mixins. Its own body contains only:

- `__init__` (widget construction + calls each mixin's `_wire_*_signals()` + initial state)
- `_build_chrome`, `_build_widgets`, `_build_layout`, `_build_shortcuts` helpers — **new methods**, created during this refactor by carving the existing `__init__` into four labelled phases. Bodies are copy-paste from the current inline `__init__` with no logic change.
- Any Qt overrides (none today; `closeEvent` etc. may be added later without violating discipline)

All 51 handlers, the `_reload` coordinator, the `_run_remote_op` serializer, repo-switch logic, and flow-specific helpers move to mixins. No logic is rewritten. No signals are added or removed. The `_RepoReadySignals` and `_RemoteSignals` helper `QObject` classes move alongside their consumer mixin.

## Architecture & files touched

**New files (all under `git_gui/presentation/main_window/`):**

```
git_gui/presentation/main_window/
├── __init__.py                           # re-exports MainWindow
├── main_window.py                        # composite class — __init__ + _build_* + Qt overrides
├── reload_coordinator.py                 # ReloadCoordinatorMixin — owns `_reload()`
├── repo_lifecycle.py                     # RepoLifecycleMixin + _RepoReadySignals
├── remote_op_queue.py                    # RemoteOpQueueMixin + _RemoteSignals
├── branch_flows.py                       # BranchFlowsMixin
├── merge_rebase_flows.py                 # MergeRebaseFlowsMixin
├── cherry_pick_revert_flows.py           # CherryPickRevertFlowsMixin
├── reset_flow.py                         # ResetFlowMixin
├── tag_flows.py                          # TagFlowsMixin
├── stash_flows.py                        # StashFlowsMixin
└── right_panel.py                        # RightPanelMixin
```

**Deleted:** `git_gui/presentation/main_window.py`.

**Not modified:** `main.py`. The existing `from git_gui.presentation.main_window import MainWindow` keeps working — the subpackage's `__init__.py` re-exports at the same dotted path.

**New tests:**
```
tests/presentation/test_main_window_package.py
```

**Not touched:** domain, application, infrastructure, all child widgets (`sidebar`, `graph`, `diff`, `working_tree`, `repo_list`, `log_panel`), dialogs, menus, theme, QSS, README.

## Group boundaries (ten mixins)

| Mixin | Est. LOC | Handlers / methods (by name; bodies moved verbatim) | Shared helpers owned |
|---|---|---|---|
| `ReloadCoordinatorMixin` | ~25 | `_reload`, `_wire_reload_signals` (working-tree reload-requested → `_reload`; graph reload-requested → `_reload`) | — |
| `RepoLifecycleMixin` | ~110 | `_switch_repo`, `_on_repo_ready`, `_on_repo_failed`, `_enter_empty_state`, `_on_repo_open`, `_on_repo_close`, `_close_current_repo`, `_switch_to_repo_index`, `_on_repo_remove_recent`, `_wire_repo_lifecycle_signals` | `_RepoReadySignals` class |
| `RemoteOpQueueMixin` | ~95 | `_run_remote_op`, `_on_remote_done`, `_on_remote_error`, `_on_push`, `_on_pull`, `_on_fetch_all_prune`, `_on_fetch_single`, `_on_push_tag`, `_get_current_branch`, `_update_remote_tag_cache`, `_wire_remote_op_signals` | `_RemoteSignals` class |
| `BranchFlowsMixin` | ~70 | `_on_branch_changed`, `_on_delete_branch`, `_on_create_branch`, `_on_checkout_commit`, `_on_checkout_branch`, `_wire_branch_flow_signals` | — |
| `MergeRebaseFlowsMixin` | ~145 | `_on_merge`, `_on_merge_commit`, `_on_merge_abort`, `_on_merge_continue`, `_on_rebase`, `_on_rebase_onto_commit`, `_on_rebase_abort`, `_on_rebase_continue`, `_on_interactive_rebase_branch`, `_on_interactive_rebase_commit`, `_open_interactive_rebase`, `_wire_merge_rebase_flow_signals` | — |
| `CherryPickRevertFlowsMixin` | ~85 | `_on_cherry_pick`, `_on_cherry_pick_abort`, `_on_cherry_pick_continue`, `_on_revert`, `_on_revert_abort`, `_on_revert_continue`, `_wire_cherry_pick_revert_flow_signals` | — |
| `ResetFlowMixin` | ~30 | `_on_reset_to_commit`, `_wire_reset_flow_signals` | — |
| `TagFlowsMixin` | ~90 | `_on_create_tag`, `_on_delete_tag`, `_delete_tag_local_only`, `_delete_tag_local_and_remote`, `_wire_tag_flow_signals` | — |
| `StashFlowsMixin` | ~45 | `_on_stash_pop`, `_on_stash_apply`, `_on_stash_drop`, `_on_stash_requested`, `_on_stash_clicked`, `_wire_stash_flow_signals` | — |
| `RightPanelMixin` | ~35 | `_on_commit_selected`, `_on_working_tree_empty`, `_on_insight_requested`, `_on_clone_requested`, `_on_clone_completed`, `_on_submodule_open_requested`, `_on_submodule_path_clicked`, `_wire_right_panel_signals` | — |

## `MainWindow` — composite shape

```python
# git_gui/presentation/main_window/main_window.py
from __future__ import annotations
from typing import Callable
from PySide6.QtWidgets import QMainWindow
# ... standard presentation imports ...

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


class MainWindow(
    QMainWindow,
    ReloadCoordinatorMixin,
    RepoLifecycleMixin,
    RemoteOpQueueMixin,
    BranchFlowsMixin,
    MergeRebaseFlowsMixin,
    CherryPickRevertFlowsMixin,
    ResetFlowMixin,
    TagFlowsMixin,
    StashFlowsMixin,
    RightPanelMixin,
):
    """Composite main window. Handlers and flow logic live on mixins; this
    class owns widget construction, layout, shortcuts, and the fixed
    sequence of `_wire_*_signals()` calls."""

    def __init__(
        self,
        queries,                 # QueryBus | None
        commands,                # CommandBus | None
        repo_store,              # IRepoStore
        remote_tag_cache=None,
        repo_path=None,
        parent=None,
        *,
        session_factory: Callable[[str], tuple],
    ) -> None:
        super().__init__(parent)
        self._queries = queries
        self._commands = commands
        self._repo_store = repo_store
        self._remote_tag_cache = remote_tag_cache
        self._repo_path = repo_path
        self._session_factory = session_factory
        self._remote_running = False
        self._selected_oid = None

        self._build_chrome()
        self._build_widgets()
        self._build_layout()
        self._build_shortcuts()

        self._wire_reload_signals()
        self._wire_repo_lifecycle_signals()
        self._wire_remote_op_signals()
        self._wire_branch_flow_signals()
        self._wire_merge_rebase_flow_signals()
        self._wire_cherry_pick_revert_flow_signals()
        self._wire_reset_flow_signals()
        self._wire_tag_flow_signals()
        self._wire_stash_flow_signals()
        self._wire_right_panel_signals()

        # Initial state exactly as today (update banners, window title, etc.)
        ...
```

The exact `__init__` body at the "Initial state" point is copied verbatim from today's `main_window.py:__init__` — banners, window title, menu install, shortcut enabling, whatever is there.

## Signal-wiring rule

Each mixin exposes ONE public method for wiring: `_wire_<concern>_signals(self)`. The body is copied from the existing `__init__`'s large connect block, split by concern. For example:

```python
# git_gui/presentation/main_window/merge_rebase_flows.py
class MergeRebaseFlowsMixin:
    def _wire_merge_rebase_flow_signals(self) -> None:
        self._graph.merge_branch_requested.connect(self._on_merge)
        self._graph.merge_commit_requested.connect(self._on_merge_commit)
        self._graph.rebase_onto_branch_requested.connect(self._on_rebase)
        self._graph.rebase_onto_commit_requested.connect(self._on_rebase_onto_commit)
        self._graph.interactive_rebase_branch_requested.connect(self._on_interactive_rebase_branch)
        self._graph.interactive_rebase_commit_requested.connect(self._on_interactive_rebase_commit)
        self._sidebar.branch_merge_requested.connect(self._on_merge)
        self._sidebar.branch_rebase_requested.connect(self._on_rebase)
        self._diff.merge_abort_requested.connect(self._on_merge_abort)
        self._diff.rebase_abort_requested.connect(self._on_rebase_abort)
        self._working_tree.merge_abort_requested.connect(self._on_merge_abort)
        self._working_tree.rebase_abort_requested.connect(self._on_rebase_abort)
        self._working_tree.merge_continue_requested.connect(self._on_merge_continue)
        self._diff.rebase_continue_requested.connect(lambda: self._on_rebase_continue(""))
        self._working_tree.rebase_continue_requested.connect(lambda: self._on_rebase_continue(""))

    def _on_merge(self, branch): ...     # body verbatim from today
    # ... etc.
```

`_wire_*_signals` functions are the only new methods introduced by this refactor. Every other method is a move, not a rewrite.

## Mixin discipline

Each mixin file follows this skeleton:

```python
# git_gui/presentation/main_window/<concern>_flows.py
from __future__ import annotations
# only imports needed by the moved method bodies — not MainWindow itself

class <Concern>FlowsMixin:
    """<One-line concern.>

    Mixin — not instantiable on its own. Relies on MainWindow-provided
    attributes (`self._queries`, `self._commands`, `self._log_panel`,
    widget refs) set up by the composite class.
    """

    # Type hints for composite-provided attrs (static checker hint only)
    _queries: object
    _commands: object
    _log_panel: object

    def _wire_<concern>_flow_signals(self) -> None:
        # Signal → slot connections for this concern.
        ...

    def _on_<action>(self, ...) -> None:
        # Moved verbatim from today's MainWindow.
        ...
```

Plain Python class (no `QObject` base), no `super().__init__()` call, no class-level signals. The sole Qt base in the MRO is `QMainWindow` at the top of the composite's bases.

## Qt multiple-inheritance guardrails

1. **One Qt base.** `MainWindow(QMainWindow, <mixins>)`. Mixins never inherit from `QObject` or any Qt class.
2. **No mixin `__init__`.** Python's MRO calls `QMainWindow.__init__` through `super().__init__(parent)`. Mixins have no init to chain.
3. **No mixin-defined signals.** Qt signals require a `QObject` meta-metaclass. If a new signal is ever needed, keep it on an existing `QObject` subclass (such as `_RepoReadySignals` / `_RemoteSignals`), not on a mixin.
4. **Slot methods are plain methods.** `connect(fn)` works with any callable — no `@Slot` decorator is required (and none is used today).

## Shared state

Lives on `MainWindow`:

| Attribute | Notes |
|---|---|
| `_queries`, `_commands` | Rewritten by `_on_repo_ready` / `_enter_empty_state`. |
| `_repo_path` | Same. |
| `_remote_running` | Mutated by `RemoteOpQueueMixin._run_remote_op` and its completion handlers. |
| `_selected_oid` | Written by `RightPanelMixin._on_commit_selected`. |
| `_repo_ready_signals` | Constructed once in `__init__` (same as today after sub-project A). Used by `RepoLifecycleMixin`. |
| Widget refs (`_sidebar`, `_graph`, `_diff`, `_working_tree`, `_repo_list`, `_log_panel`, `_right_stack`) | Constructed once in `_build_widgets` / `_build_layout`. Mixins access via `self.`. |

No cross-mixin state. Every mixin reads/writes these via the shared composite.

## Background threads — unchanged

- `_switch_repo` spawns a one-shot worker that emits `_RepoReadySignals`. Stays the same.
- `_run_remote_op` spawns per-op workers that emit `_RemoteSignals`. Stays the same.
- `_remote_running` gate prevents concurrent remote ops. Stays on `MainWindow`; `RemoteOpQueueMixin` reads and writes it.

## Testing

**Primary safety net:** existing 502-test suite — specifically `tests/presentation/test_main_window_session_factory.py` (repo-switch flow) and `tests/presentation/test_main_window_checkout_conflict.py` (`_on_checkout_branch` path). Any broken signal-wiring surfaces as a test failure.

**New structural tests** (`tests/presentation/test_main_window_package.py`):

1. **Import-surface test** — `from git_gui.presentation.main_window import MainWindow` succeeds after the subpackage exists.
2. **MRO check** — `MainWindow.__mro__` includes all ten mixin classes by name, plus `QMainWindow`.
3. **Composite-discipline check** — for every name `n` in `vars(MainWindow)` that is callable and not a dunder, assert `n` does not start with `_on_` or `_wire_`. Flow helpers (e.g., `_delete_tag_local_only`, `_open_interactive_rebase`) are similarly excluded from the composite by asserting no `vars(MainWindow)` name appears in the union of all mixins' `vars()` entries. Allowed on the composite: `_build_chrome`, `_build_widgets`, `_build_layout`, `_build_shortcuts`, and any Qt override resolvable on `QMainWindow`.
4. **Handler-coverage check** — every `_on_*` and `_wire_*_signals` method declared on a mixin is resolvable as an attribute on `MainWindow` via `getattr`. Guards against an extraction accidentally dropping a method.

**No per-mixin unit tests.** Mixins can't be instantiated alone — they need the composite's widget construction. Behavioral coverage is already complete via integration tests.

## Out of scope

- Converting mixins into injectable presenter classes.
- Introducing a `PresentationBus` or other new messaging abstraction.
- Refactoring child widgets (sidebar, graph, diff, working_tree, repo_list).
- Changing any handler's logic, dialog flow, or user-visible behavior.
- Rewriting the threading model (`threading.Thread` stays; no migration to `QThread`).
- Adding, removing, or renaming handlers.
- Touching `main.py` beyond what's required to keep the existing import path working.
- README update (refactor is internal; no user-visible change).
