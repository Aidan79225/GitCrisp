# Light Theme Softening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing pure-white Light theme with a "pronounced" primary-tinted variant that reads as deliberately cool and softer, without disturbing other tokens.

**Architecture:** JSON-only change. Eleven surface/outline/text tokens in `git_gui/presentation/theme/builtin/light.json` shift to a primary-tinted palette. The token-driven theme pipeline regenerates QSS on theme apply, so no Python changes are needed in `loader.py`, `manager.py`, `qss_template.py`, or `tokens.py`. A new contrast regression test guards against future drift below WCAG AA.

**Tech Stack:** PySide6 + JSON-defined themes loaded by `git_gui.presentation.theme.loader.load_builtin`. Tests use `pytest` via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-05-05-light-theme-softer-design.md`

---

## File Structure

- **Modify:** `git_gui/presentation/theme/builtin/light.json` — eleven token values shift.
- **Create:** `tests/presentation/theme/test_light_contrast.py` — five WCAG AA regression assertions.

Files **not** changed:
- `git_gui/presentation/theme/builtin/dark.json`
- `git_gui/presentation/theme/{loader,manager,live,tokens,qss_template}.py`

---

## Task 1: Add WCAG AA contrast regression test

The test is added before the JSON edit so the regression guard exists for any future theme tweak. The current Light palette already passes the assertions (5.24:1 worst case on the old palette), so the test passes on first run; that's expected — its job is to fail on future regressions, not on this change.

**Files:**
- Create: `tests/presentation/theme/test_light_contrast.py`

- [ ] **Step 1: Write the test**

Create `tests/presentation/theme/test_light_contrast.py` with the following content:

```python
"""Regression test: Light theme meets WCAG AA contrast.

Locks in the contrast budget documented in
docs/superpowers/specs/2026-05-05-light-theme-softer-design.md so future
edits to surface or text tokens can't silently regress readability. The
worst-case pair (muted text on the deepest tinted surface) is the
binding constraint at ~5:1 — well above the 4.5:1 AA threshold but
close enough that careless tweaks could break it.
"""
from __future__ import annotations

import pytest

from git_gui.presentation.theme.loader import load_builtin


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


@pytest.fixture(scope="module")
def light_colors():
    return load_builtin("light").colors


@pytest.mark.parametrize(
    "fg_attr, bg_attr, label",
    [
        ("on_surface", "surface", "body text on surface"),
        ("on_surface", "surface_container_high", "body text on container_high"),
        ("on_surface_variant", "surface_variant", "muted text on surface_variant"),
        ("on_surface_variant", "surface_container_high", "muted text on container_high"),
        ("on_primary", "primary", "primary button label"),
    ],
)
def test_light_theme_passes_wcag_aa(light_colors, fg_attr, bg_attr, label):
    fg = getattr(light_colors, fg_attr)
    bg = getattr(light_colors, bg_attr)
    ratio = _ratio(fg, bg)
    assert ratio >= 4.5, (
        f"{label}: {fg_attr} {fg} on {bg_attr} {bg} "
        f"= {ratio:.2f}:1 (need ≥ 4.5)"
    )
```

- [ ] **Step 2: Run the test against the existing palette**

Run: `rtk uv run pytest tests/presentation/theme/test_light_contrast.py -v`

Expected: 5 PASSED (the current Light palette already meets AA on all five pairs; the lowest is `on_surface_variant #59636e` on `surface_container_high #eaeef2` at ~5.24:1).

- [ ] **Step 3: Commit**

```bash
rtk git add tests/presentation/theme/test_light_contrast.py
rtk git commit -m "$(cat <<'EOF'
test(theme): add WCAG AA contrast regression test for Light

Locks in the contrast budget for the five worst-case body-text pairs
in the Light palette: on_surface on surface and container_high,
on_surface_variant on surface_variant and container_high, and
on_primary on primary. Passes on the current palette; guards against
future drift.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Soften Light theme tokens

Apply the eleven token shifts in `light.json`. The contrast test from Task 1 verifies AA continues to hold; existing `test_manager.py` tests verify the JSON still loads cleanly through `load_builtin`.

**Files:**
- Modify: `git_gui/presentation/theme/builtin/light.json`

- [ ] **Step 1: Edit `surface`**

In `git_gui/presentation/theme/builtin/light.json`, change:
```json
    "surface": "#ffffff",
```
to:
```json
    "surface": "#eff5fd",
```

- [ ] **Step 2: Edit `on_surface`**

Change:
```json
    "on_surface": "#1f2328",
```
to:
```json
    "on_surface": "#1a2533",
```

- [ ] **Step 3: Edit `surface_variant`**

Change:
```json
    "surface_variant": "#f6f8fa",
```
to:
```json
    "surface_variant": "#dde8f6",
```

- [ ] **Step 4: Edit `on_surface_variant`**

Change:
```json
    "on_surface_variant": "#59636e",
```
to:
```json
    "on_surface_variant": "#475260",
```

- [ ] **Step 5: Edit `surface_container`**

Change:
```json
    "surface_container": "#f6f8fa",
```
to:
```json
    "surface_container": "#dde8f6",
```

- [ ] **Step 6: Edit `surface_container_high`**

Change:
```json
    "surface_container_high": "#eaeef2",
```
to:
```json
    "surface_container_high": "#c9d6e9",
```

- [ ] **Step 7: Edit `outline`**

Change:
```json
    "outline": "#d1d9e0",
```
to:
```json
    "outline": "#bcc7da",
```

- [ ] **Step 8: Edit `outline_variant`**

Change:
```json
    "outline_variant": "#d8dee4",
```
to:
```json
    "outline_variant": "#c8d2e2",
```

- [ ] **Step 9: Edit `background`**

Change:
```json
    "background": "#ffffff",
```
to:
```json
    "background": "#eff5fd",
```

- [ ] **Step 10: Edit `on_background`**

Change:
```json
    "on_background": "#1f2328",
```
to:
```json
    "on_background": "#1a2533",
```

- [ ] **Step 11: Edit `hover_overlay`**

Change:
```json
    "hover_overlay": "#1e000000",
```
to:
```json
    "hover_overlay": "#1e0a2540",
```

- [ ] **Step 12: Verify JSON parses and loads as a Theme**

Run: `rtk uv run python -c "from git_gui.presentation.theme.loader import load_builtin; t = load_builtin('light'); print('ok name=', t.name, 'is_dark=', t.is_dark, 'surface=', t.colors.surface)"`

Expected output: `ok name= Light is_dark= False surface= #eff5fd`

- [ ] **Step 13: Run the contrast test**

Run: `rtk uv run pytest tests/presentation/theme/test_light_contrast.py -v`

Expected: 5 PASSED. The new palette's worst case is `on_surface_variant #475260` on `surface_container_high #c9d6e9` at 5.40:1.

- [ ] **Step 14: Run the existing theme tests**

Run: `rtk uv run pytest tests/presentation/theme/ -v`

Expected: all PASSED. These tests check theme load/swap/notify mechanics and don't assert specific colors, so they should be unaffected.

- [ ] **Step 15: Run the full test suite as a final smoke check**

Run: `rtk uv run pytest tests/ -q`

Expected: 638 passed (637 prior + 5 new contrast cases consolidate into 5 parametrized cases — total goes from 637 to 642). One pre-existing warning from `test_repo_change_detector_debounce.py` is unrelated.

- [ ] **Step 16: Commit**

```bash
rtk git add git_gui/presentation/theme/builtin/light.json
rtk git commit -m "$(cat <<'EOF'
feat(theme): soften Light theme with primary-tinted surfaces

Replace pure-white surfaces with a "pronounced" primary-tinted
elevation ladder (#eff5fd → #dde8f6 → #c9d6e9). Outlines and text
tokens shift cool to match. Primary, diff colors, status colors,
graph lanes, syntax tokens, typography, shape, and spacing are
unchanged. Worst-case AA contrast is 5.40:1 (muted text on
surface_container_high) — locked in by the contrast regression test.

See docs/superpowers/specs/2026-05-05-light-theme-softer-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Manual visual smoke test

No code changes — this is the human-eyeball pass that automated tests can't substitute for.

**Files:** none modified.

- [ ] **Step 1: Launch the app**

Run: `rtk uv run python main.py`

- [ ] **Step 2: Switch to Light theme**

Open the theme dialog (typically via the toolbar or a menu) and pick "Light". Confirm the surfaces visibly read as cool/blue-tinted, not pure white.

- [ ] **Step 3: Walk through every major surface**

Open a real repo and visit each of the following. At each stop, confirm text is readable, hover/selection states are visible against the new bg, and badges/pills stay legible:

- Graph panel (commit list) — selected row highlight, lane colors, ref badges.
- Commit detail panel — header, full message, file navigator (LIST mode and PILL mode), diff blocks (added overlay, removed overlay, word-level overlays).
- Working tree — staged/unstaged splitter, file list with status badges, hunk diff, conflict banner if available.
- Branches dialog, remote dialog, theme dialog.

- [ ] **Step 4: Toggle Light ↔ Dark a few times**

Use the theme dialog to swap Light → Dark → Light. Both should render correctly without artifacts. Light should show the new tinted surfaces; Dark should be unchanged.

- [ ] **Step 5: Note documentation impact**

If any screenshots or images under `docs/` reference the old white Light theme, jot them down for a follow-up issue. **Do not** re-shoot screenshots in this change — that's a separate scope.

- [ ] **Step 6: No commit needed**

Manual verification doesn't produce changes. If you found a real visual issue (text unreadable somewhere, hover invisible somewhere), stop and surface it before merging — that's a sign a token still needs adjustment.

---

## Self-Review

**Spec coverage:**
- Token mapping table (11 tokens) → Task 2 steps 1-11. ✅
- Contrast budget (5 pairs) → Task 1 test parametrization. ✅
- Diff overlays "intentionally left alone" → not modified in Task 2 (no step touches them). ✅
- Critical files list → both files appear in Task 1 / Task 2 file headers. ✅
- Verification (automated + manual) → Task 1 step 2, Task 2 steps 12-15, Task 3. ✅

**Placeholder scan:** none — every step has the actual content (full test code, exact JSON before/after, exact commands, exact expected outputs).

**Type/value consistency:**
- New tokens used in Task 1 test (`on_surface_variant`, `surface_container_high`, etc.) match the dataclass field names in `Colors` (`tokens.py:19-21`). ✅
- Hex values in Task 2 steps match the spec's token mapping table exactly. ✅
- Test count claim in Task 2 step 15 (637 → 642) is the only quantitative claim that depends on prior count; if the suite has grown since this plan was written, adjust expectation but don't fail on the exact number.
