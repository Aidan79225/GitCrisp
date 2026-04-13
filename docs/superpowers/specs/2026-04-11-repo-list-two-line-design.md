# Repo List Two-Line Entry — Design

**Status:** Draft
**Date:** 2026-04-11

## Background

The repository sidebar (`RepoListWidget`) currently shows only the directory basename for each repo — `Path(path).name` — with the full path available only via a hover tooltip. When two open or recent repositories share a directory name but live in different parent paths (e.g. `~/projects/GitStack` and `~/work/GitStack`), they look identical in the list. Users can only distinguish them by hovering.

## Goals

- Make repositories with the same directory name visually distinguishable at a glance.
- Match the established two-line list pattern from macOS Finder, VS Code "Recent Workspaces", and similar tools.
- Keep the change scoped to `RepoListWidget`; no changes to the data model, store, or queries.

Out of scope: branch name / dirty indicators on repo rows, title-bar changes, dialog changes, repo metadata in the store.

## Layout

Each row becomes a two-line entry:

- **Line 1 (primary):** `Path(path).name` — the repo's directory basename.
  - Default font, default weight.
  - When the repo is the currently active one, bold + drawn over the primary color highlight (current behavior is preserved).
- **Line 2 (secondary):** the full path with `~` substituted for the user's home directory, rendered with forward slashes — e.g. `~/projects/GitStack`.
  - Smaller font (about 85% of line 1).
  - Dimmer color: MD3 `on_surface_variant`.
  - Middle-truncated via `QFontMetrics.elidedText(text, Qt.ElideMiddle, available_width)` when it exceeds the row width.
  - Dimmer treatment applies in both active and inactive states — the secondary line is always secondary.

Row height grows from the current `_ROW_HEIGHT` (28 px) to **40 px** to accommodate both lines plus padding. Section headers (`REPOSITORIES`, `OPEN`, `RECENT`) and their current height are unchanged.

Hover state, selection state, section collapsing, click handling, and context menus are unchanged.

The tooltip still shows the untruncated absolute path — it is the fallback when middle-truncation hides a useful segment.

## Helper function

A pure module-level helper converts a path to its display form:

```python
def _display_path(path: str) -> str:
    p = Path(path)
    try:
        rel = p.relative_to(Path.home())
        if rel == Path("."):
            return "~"
        return "~/" + rel.as_posix()
    except ValueError:
        return p.as_posix()
```

- Uses forward slashes on all platforms (consistent with common path display in modern tools).
- Returns exactly `~` when the path is the user's home directory.
- Returns the full path unchanged (with forward slashes) when the path is not under home.

This function is trivial to unit-test without Qt.

## Rendering

A custom `QStyledItemDelegate` subclass, `_RepoItemDelegate`, replaces the default item rendering for non-header rows. The existing row-background painting in `_RepoTree.drawRow` (active highlight and hover overlay) is preserved; the delegate only owns the text inside the row.

### `sizeHint`

For header rows (identified by `Qt.UserRole + 1 == "header"`), return `QSize(option.rect.width(), _ROW_HEIGHT)` — unchanged.

For repo rows, return `QSize(option.rect.width(), 40)`.

### `paint`

For header rows, defer to `super().paint()` — headers keep their existing look.

For repo rows, the delegate:

1. Does **not** fill the selection/hover background — `_RepoTree.drawRow` already handles that before the delegate paints.
2. Computes the usable text rectangle with left and right padding (about 8 px each side, matching current tree indentation).
3. Splits the rectangle vertically: top ~60% for the name, bottom ~40% for the path.
4. Draws the name in the default font:
   - If the item has `_IS_ACTIVE_ROLE == True`, draw bold in `on_primary` (to contrast with the primary-color active background).
   - Otherwise draw in `on_surface` using the normal weight.
5. Draws the path on line 2 with:
   - A font copy that is one point smaller (or 85% of the name font, whichever is more portable across themes).
   - Color `on_surface_variant` (imported via the existing theme token system — add the token if it is not already defined in `tokens.py` and the built-in JSON themes).
   - Text computed by `QFontMetrics(font).elidedText(_display_path(path), Qt.ElideMiddle, text_rect.width())`.

### Wiring

In `RepoListWidget.__init__`, after `self._tree` is created, install the delegate with `self._tree.setItemDelegate(_RepoItemDelegate(self))`.

Item creation in `_make_repo_item` is unchanged except that `QStandardItem.setSizeHint` can be removed (the delegate's `sizeHint` now drives the row height) — leave the `setSizeHint` call for header rows, or let the delegate handle both.

## Theme tokens

Check whether `on_surface_variant` is already defined in `git_gui/presentation/theme/tokens.py` and the built-in themes (`dark.json`, `light.json`). If missing:

- Add `on_surface_variant: str` to the `ColorTokens` dataclass.
- Add values to both `dark.json` and `light.json` matching the MD3 guidance:
  - Dark theme: `#c4c7c5` (a dimmer variant of `on_surface`).
  - Light theme: `#44474f` (a dimmer variant of `on_surface`).

If the token exists, reuse it as-is.

## Testing

### Unit tests for `_display_path`

New file `tests/presentation/widgets/test_repo_list.py` (or extended equivalent):

- `test_display_path_under_home` — path strictly under `Path.home()` returns `~/…`.
- `test_display_path_outside_home` — path not under home returns the path unchanged, with forward slashes.
- `test_display_path_home_itself` — path equal to `Path.home()` returns exactly `"~"`.
- `test_display_path_uses_forward_slashes` — on any OS, output contains only `/` as the separator (no backslashes).

These tests patch `Path.home()` via `monkeypatch` so they are OS-independent.

### Manual acceptance

1. Open two repos with the same directory name in different parent paths; both are distinguishable in the sidebar at a glance.
2. Hover a row → tooltip still shows the full absolute path.
3. Shrink the window so the sidebar is narrow → the second line middle-elides cleanly (start and end of the path remain visible; the middle becomes `…`).
4. Switch the active repo → the active repo's name is still bold and rendered over the primary-color highlight; the secondary line remains dim in both active and inactive states.
5. Section headers (`OPEN`, `RECENT`) still collapse/expand correctly.
6. Context menu behavior and click behavior are unchanged.

## File change list

New:
- `tests/presentation/widgets/test_repo_list.py` (or extend existing).

Modified:
- `git_gui/presentation/widgets/repo_list.py` — add `_display_path` helper, add `_RepoItemDelegate`, install it on `self._tree`.
- `git_gui/presentation/theme/tokens.py` (only if `on_surface_variant` is not yet defined).
- `git_gui/presentation/theme/builtin/dark.json` and `light.json` (only if the token is not yet defined).
