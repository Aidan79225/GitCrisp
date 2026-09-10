# Light theme — softer, primary-tinted variant

## Context

The current built-in Light theme uses pure-white surfaces (`#ffffff`) for
both `background` and `surface`, with a small jump to `#f6f8fa` /
`#eaeef2` for elevated containers. In daily use this reads as too
bright — the unrelieved white is fatiguing for long sessions and
exaggerates contrast against the existing primary blue (`#79c0ff`).

The fix is a token-only rebalance: keep the same theme identity
(`Light`), keep the GitHub-palette accents (diff add/remove, status,
syntax), but shift every surface and outline token toward a deliberate
cool-blue undertone. The aim is for the theme to read as "still Light,
but visibly tinted" — a "pronounced" intensity from the primary-tinted
family explored during brainstorming.

## Scope

- **Replace, not add.** The existing `Light` theme entry is rebalanced
  in place. There remain exactly two built-in themes: Light, Dark.
- **JSON-only change.** No Python changes — the token-driven theme
  pipeline regenerates QSS from JSON on theme apply, so swapping
  values is sufficient.
- **Untouched:** primary family, diff add/remove backgrounds, status
  colors, graph_lane_colors, ref_badge_*, syntax_*, typography, shape,
  spacing. These are semantic/cultural anchors that shouldn't drift.

## Token mapping

Eleven tokens change in `git_gui/presentation/theme/builtin/light.json`:

| Token | Old | New |
|---|---|---|
| `surface` | `#ffffff` | `#eff5fd` |
| `background` | `#ffffff` | `#eff5fd` |
| `surface_variant` | `#f6f8fa` | `#dde8f6` |
| `surface_container` | `#f6f8fa` | `#dde8f6` |
| `surface_container_high` | `#eaeef2` | `#c9d6e9` |
| `outline` | `#d1d9e0` | `#bcc7da` |
| `outline_variant` | `#d8dee4` | `#c8d2e2` |
| `on_surface` | `#1f2328` | `#1a2533` |
| `on_background` | `#1f2328` | `#1a2533` |
| `on_surface_variant` | `#59636e` | `#475260` |
| `hover_overlay` | `#1e000000` | `#1e0a2540` |

Rationale per group:

- **Surface family (`surface`, `background`, `*_variant`,
  `*_container`, `*_container_high`)** — pulled from the "pronounced"
  intensity validated during brainstorming. The three-step ladder
  (`#eff5fd` → `#dde8f6` → `#c9d6e9`) preserves the same elevation
  contrast as the old palette, just shifted lower in lightness and
  cooler in hue.
- **Outlines** — cool-shifted to match the surfaces; without this
  they'd read as warm against the new bg.
- **Foreground text** (`on_surface`, `on_background`,
  `on_surface_variant`) — small cool shift so text feels like it
  belongs to the new surface family rather than mismatched.
  `on_surface_variant` is darkened slightly more than a pure tonal
  shift would suggest, to clear the AA threshold against
  `surface_container_high` (see Contrast budget).
- **`hover_overlay`** — switches from pure-black-with-alpha to
  primary-tinted-with-alpha so hover ripples cohere with the surface
  family. Same alpha (`#1e` = 12%), so opacity behavior is unchanged.

### Diff overlays are intentionally left alone

`diff_added_overlay` and `diff_removed_overlay` are 50%-alpha overlays
painted on top of `diff_added_bg` / `diff_removed_bg` — they blend with
the underlying diff color, not the page surface. The surface change
doesn't affect their perceived color.

## Contrast budget (WCAG AA)

Body-text minimum is 4.5:1; UI text minimum is 3:1. Worst-case pairs
are body text on every surface in the elevation ladder, including
`surface_container_high` (the deepest tinted surface, where muted text
is most likely to fail).

| Foreground / Background | Ratio | Status |
|---|---|---|
| `on_surface` `#1a2533` / `surface` `#eff5fd` | 14.12:1 | ✅ AAA |
| `on_surface` `#1a2533` / `surface_container_high` `#c9d6e9` | 10.53:1 | ✅ AAA |
| `on_surface_variant` `#475260` / `surface_variant` `#dde8f6` | 6.41:1 | ✅ AA |
| `on_surface_variant` `#475260` / `surface_container_high` `#c9d6e9` | 5.40:1 | ✅ AA |
| `on_primary` `#0a2540` / `primary` `#79c0ff` (unchanged) | 7.99:1 | ✅ AAA |

The muted-text-on-deepest-surface pair was the binding constraint; an
earlier candidate `#54606e` cleared `surface_variant` (5.17:1) but
failed `surface_container_high` (4.36:1). `#475260` darkens just
enough to clear AA on both.

A new contrast test (see Verification) locks these ratios in.

## Critical files

- `git_gui/presentation/theme/builtin/light.json` — the eleven token
  values change.
- `tests/presentation/theme/test_light_contrast.py` — **new** —
  loads the JSON and asserts the contrast ratios above.

Files **not** changed:
- `git_gui/presentation/theme/builtin/dark.json` — Dark is untouched.
- `git_gui/presentation/theme/qss_template.py` — token references
  unchanged.
- `git_gui/presentation/theme/{loader,manager,live,tokens}.py` —
  mechanics unchanged.

## Verification

**Automated:**
```
uv run pytest tests/presentation/theme/ -v
uv run python -c "import json; json.load(open('git_gui/presentation/theme/builtin/light.json'))"
```
The existing `test_manager.py` tests (theme load/swap/notify) must
still pass. The new `test_light_contrast.py` asserts the three
ratios documented above; cheap insurance against future drift.

**Manual smoke test:**

1. `uv run python main.py`. Switch to Light via the theme dialog.
2. Walk through every major surface in a real repo:
   - Graph panel and commit list.
   - Commit detail panel: header, message, file navigator (LIST and
     PILL modes), diff blocks (added/removed/word overlays).
   - Working tree: staged/unstaged splitter, hunk diff.
   - Branches dialog, remote dialog, theme dialog itself.
3. Confirm:
   - No spot where text contrast feels weak against the new bg.
   - Hover and selection states remain visible against the tinted
     surfaces.
   - Badges, pills, and status indicators stay legible.
4. Toggle Light ↔ Dark a few times — both should still look correct
   after re-applying the JSON.
5. Note any documentation screenshots (under `docs/`) that reference
   the old white Light theme; flag for follow-up re-shoot, but do not
   re-shoot in this change.
