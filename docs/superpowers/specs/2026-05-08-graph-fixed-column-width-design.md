# GraphWidget: fixed column 0 width, splitter-controlled total

## Context

`GraphWidget._update_column_widths` runs on every scroll and on
every model reload. It does two things:

1. Resizes column 0 (graph lanes) to fit the maximum lane count of
   currently-visible rows.
2. Calls `self.setMinimumWidth(graph_w + info_w)`, which forces the
   surrounding `QSplitter` to give the GraphWidget at least that
   much space.

The minimum-width call is the disruptive one. Even after the user
has dragged the splitter to set their preferred graph width,
scrolling into a busy section pushes the splitter wider, shrinks
the right panel, and breaks the user's layout.

## Fix

Remove the dynamic resize logic. Column 0 becomes a fixed-width
constant; column 1 keeps its existing stretch mode and fills the
remainder of whatever width the user has dragged the splitter to.
The splitter handle is the sole authority on the GraphWidget's
total width.

Trade-off: commits with more than ~8 parallel lanes will visually
clip in column 0. The user accepts this in exchange for stable
layout. If 8 lanes is the wrong default in practice, the constant
can be tuned later in a one-line change.

## Scope

- **Modify:** `git_gui/presentation/widgets/graph.py` — delete four
  helpers and both call sites, add a module-level constant, change
  one `setColumnWidth` call.
- **Modify:** `tests/presentation/widgets/test_graph_signals.py` —
  drop the now-dead stub.
- **Modify:** `tests/presentation/widgets/test_graph_synthetic.py`
  — drop the now-dead stub and its comment.

## Concrete changes to `graph.py`

**Add** near the top, alongside the existing `LANE_W` import:

```python
_DEFAULT_GRAPH_COL_W = 8 * LANE_W  # 128 px — fits ~8 parallel lanes
```

**Change** line 237:

```python
# was:
self._view.setColumnWidth(0, LANE_W)
# becomes:
self._view.setColumnWidth(0, _DEFAULT_GRAPH_COL_W)
```

**Delete** lines 498-536 entirely (the `_INFO_MIN_W` class constant,
the `_compute_info_width` method, and the `_update_column_widths`
method). Also delete the `_get_visible_rows` method (sole caller is
`_update_column_widths`).

**Delete** the call at line 430 (the `_update_column_widths()` line
right after `self._model.reload(...)`).

**Delete** the call at line 539 (the `_update_column_widths()` line
at the top of `_on_scroll`). Keep the rest of `_on_scroll` —
specifically the scrollbar-maximum check that triggers
`_load_more`.

## What stays the same

- Column 1 (info) keeps `QHeaderView.Stretch` — it always fills the
  remaining widget width.
- `LANE_W = 16` in `graph_lane_delegate.py` — unchanged.
- The graph row delegate's painting logic — unchanged.
- Splitter wiring in `main_window.py` — unchanged.

## Tests

- Two existing test files stub `_update_column_widths = lambda:
  None` to keep tests from touching the view/viewport. After the
  deletion, those stubs assign to an attribute that no longer
  exists as a method. They wouldn't error (Python creates an
  instance attribute), but they're misleading dead code. Remove
  them.
- No new tests added — the only behavior change is "stop calling a
  method that we just deleted," which is verified by the dead-stub
  removal. The full pytest suite catches any unexpected regression.

## Verification

**Automated:**
```
uv run pytest tests/presentation/widgets/ -v
uv run pytest tests/ -q
```

All tests must still pass. The two graph test files no longer need
their `_update_column_widths` stub.

**Manual:**
1. `uv run python main.py`. Open a sizeable repo.
2. Drag the central splitter handle to make the GraphWidget narrow.
3. Scroll the graph through busy and quiet sections. The splitter
   should not move on its own. The graph should stay at the width
   you set.
4. Scroll to a section with many parallel branches. Column 0 stays
   at 128 px. Lane drawing in column 0 clips at the right edge of
   the column for very wide commits — expected.
5. Drag the splitter handle wider. Column 0 stays at 128 px;
   column 1 (commit info) grows to fill.
