# MD3 Theming Batch 3 Implementation Plan — Theme Dialog

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `View → Appearance → System/Light/Dark` submenu with a single menu item that opens a Theme Dialog. The dialog has 4 mode radios (System / Light / Dark / Custom). When Custom is selected, an inline editor with a `QToolBox` accordion exposes all colour tokens (grouped) plus a global typography scale slider, prefilled from Dark.

**Architecture:** (1) Add `"custom"` mode to `ThemeManager` that loads from `<AppData>/GitStack/custom_theme.json` (full Theme JSON, strict-loader format). (2) Build `ThemeDialog(QDialog)` in a new `dialogs/` package: mode radios + custom panel containing typography slider + 7-page `QToolBox` of colour swatches + Apply/Cancel/Reset. Apply semantics — no live preview. (3) Rewrite `install_appearance_menu` to expose one action that opens the dialog.

**Tech Stack:** Python 3.13, PySide6 (Qt 6 — `QDialog`, `QToolBox`, `QColorDialog`, `QButtonGroup`, `QSlider`), `uv run`, pytest, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-07-md3-theming-batch3-theme-dialog-design.md`

---

## File Structure

**New:**
- `git_gui/presentation/dialogs/__init__.py`
- `git_gui/presentation/dialogs/theme_dialog.py`
- `tests/presentation/dialogs/__init__.py`
- `tests/presentation/dialogs/test_theme_dialog.py`

**Modified:**
- `git_gui/presentation/theme/manager.py` — add `"custom"` mode, `_load_custom_or_fallback`.
- `git_gui/presentation/theme/settings.py` — expose `custom_theme_path()` returning the file path.
- `git_gui/presentation/menus/appearance.py` — replace 3-action submenu with one action that opens `ThemeDialog`.
- `tests/presentation/menus/test_appearance.py` — rewrite for the single-action menu.
- `tests/presentation/theme/test_manager.py` — add `set_mode("custom")` tests.

---

## Conventions

- All Python execution via `uv run` (per `CLAUDE.md`).
- Tests: `uv run pytest tests/ -q`.
- One commit per task unless noted.
- Don't change unrelated files.

---

## Task 1: ThemeManager `"custom"` mode

**Files:**
- Modify: `git_gui/presentation/theme/settings.py`
- Modify: `git_gui/presentation/theme/manager.py`
- Modify: `tests/presentation/theme/test_manager.py`

- [ ] **Step 1: Add `custom_theme_path()` to settings.py**

Open `git_gui/presentation/theme/settings.py`. Read it. After the existing `settings_path()` function add:

```python
def custom_theme_path() -> Path:
    """Path to the user's saved custom theme JSON.

    Lives next to settings.json so the entire user theme state stays in
    one directory under <AppData>/GitStack/.
    """
    return settings_path().parent / "custom_theme.json"
```

- [ ] **Step 2: Write a failing test for set_mode("custom") with a present file**

Append to `tests/presentation/theme/test_manager.py`:

```python
def test_set_mode_custom_loads_from_file(app, isolated_settings, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    from git_gui.presentation.theme.loader import load_builtin

    custom_path = tmp_path / "custom_theme.json"
    monkeypatch.setattr(s, "custom_theme_path", lambda: custom_path)

    # Use light as the custom file's content so we can detect it loaded.
    base = load_builtin("light")
    import json
    from dataclasses import asdict
    payload = {
        "name": "Custom Test",
        "is_dark": False,
        "colors": {k: v for k, v in asdict(base.colors).items()},
        "typography": {k: asdict(v) for k, v in asdict(base.typography).items()},
        "shape": asdict(base.shape),
        "spacing": asdict(base.spacing),
    }
    custom_path.write_text(json.dumps(payload))

    mgr = ThemeManager(app)
    mgr.set_mode("custom")
    assert mgr.mode == "custom"
    assert mgr.current.name == "Custom Test"


def test_set_mode_custom_missing_file_falls_back_to_dark(app, isolated_settings, tmp_path, monkeypatch, caplog):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "missing.json")

    mgr = ThemeManager(app)
    with caplog.at_level("WARNING"):
        mgr.set_mode("custom")
    assert mgr.mode == "custom"
    assert mgr.current.is_dark is True  # fell back to dark
    assert any("custom" in r.message.lower() for r in caplog.records)
```

Note: the test file's existing fixtures (`app`, `isolated_settings`) work as-is. The `asdict` chain above is verbose because some sub-dataclasses (e.g. `Typography`) need the inner `TextStyle`s also dumped.

If `asdict` recursion already produces a usable nested dict, the test can simplify to:

```python
import dataclasses
payload = dataclasses.asdict(base) | {"name": "Custom Test"}
custom_path.write_text(json.dumps(payload))
```

Try the simpler form first. If it errors (e.g. `Theme` has `name` already and the override needs to be inside the dict), keep the explicit form.

- [ ] **Step 3: Run to verify failure**

`uv run pytest tests/presentation/theme/test_manager.py -v`
Expected: the two new tests fail because `"custom"` is not in `_VALID_MODES`.

- [ ] **Step 4: Edit `manager.py`**

Open `git_gui/presentation/theme/manager.py`. Read it. Make these changes:

1. Add to imports near the existing `from .loader import load_builtin`:
   ```python
   from .loader import load_builtin, load_theme, ThemeValidationError
   from .settings import load_settings, save_settings, custom_theme_path
   ```

2. Update `_VALID_MODES`:
   ```python
   _VALID_MODES = ("system", "light", "dark", "custom")
   ```

3. Extend `_resolve_theme`:
   ```python
   def _resolve_theme(self) -> Theme:
       if self._mode == "light":
           return load_builtin("light")
       if self._mode == "dark":
           return load_builtin("dark")
       if self._mode == "custom":
           return self._load_custom_or_fallback()
       return self._system_theme()
   ```

4. Add the helper method on `ThemeManager`:
   ```python
   def _load_custom_or_fallback(self) -> Theme:
       path = custom_theme_path()
       if not path.exists():
           _log.warning("Custom theme file not found at %s; falling back to dark", path)
           return load_builtin("dark")
       try:
           return load_theme(path)
       except (OSError, ThemeValidationError) as e:
           _log.warning("Could not load custom theme at %s: %s; falling back to dark", path, e)
           return load_builtin("dark")
   ```

5. Add the logger import at the top of the file if it isn't already imported:
   ```python
   import logging
   _log = logging.getLogger(__name__)
   ```
   (Check first — `settings.py` already has this pattern.)

- [ ] **Step 5: Run the new tests**

`uv run pytest tests/presentation/theme/test_manager.py -v`
Expected: all manager tests pass (existing + 2 new).

- [ ] **Step 6: Run full suite**

`uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/theme/settings.py git_gui/presentation/theme/manager.py tests/presentation/theme/test_manager.py
git commit -m "feat(theme): add custom mode loading from custom_theme.json"
```

---

## Task 2: ThemeDialog scaffold (mode radios + Apply/Cancel)

**Files:**
- Create: `git_gui/presentation/dialogs/__init__.py`
- Create: `git_gui/presentation/dialogs/theme_dialog.py`
- Create: `tests/presentation/dialogs/__init__.py`
- Create: `tests/presentation/dialogs/test_theme_dialog.py`

This task ships the dialog skeleton with the 4 mode radios working. The custom panel exists but is empty (a placeholder QGroupBox). Task 3 fills it.

- [ ] **Step 1: Create package skeletons**

```python
# git_gui/presentation/dialogs/__init__.py
"""GitStack dialog widgets."""
```

```python
# tests/presentation/dialogs/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/presentation/dialogs/test_theme_dialog.py`:

```python
"""Tests for the ThemeDialog."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QRadioButton

from git_gui.presentation.dialogs.theme_dialog import ThemeDialog
from git_gui.presentation.theme import get_theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reset_theme():
    yield
    get_theme_manager().set_mode("dark")


def _radios(dialog: ThemeDialog) -> dict[str, QRadioButton]:
    """Return {mode_name: radio} for the dialog's mode buttons."""
    return {
        radio.property("mode"): radio
        for radio in dialog.findChildren(QRadioButton)
        if radio.property("mode") in ("system", "light", "dark", "custom")
    }


def test_dialog_constructs(app, reset_theme):
    dlg = ThemeDialog()
    assert isinstance(dlg, QDialog)
    radios = _radios(dlg)
    assert set(radios.keys()) == {"system", "light", "dark", "custom"}


def test_initial_radio_matches_current_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()
    assert _radios(dlg)["dark"].isChecked()


def test_apply_with_light_radio_sets_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()
    _radios(dlg)["light"].setChecked(True)
    dlg._on_apply()
    assert mgr.mode == "light"


def test_cancel_does_not_change_mode(app, reset_theme):
    mgr = get_theme_manager()
    mgr.set_mode("dark")
    dlg = ThemeDialog()
    _radios(dlg)["light"].setChecked(True)
    dlg._on_cancel()
    assert mgr.mode == "dark"
```

- [ ] **Step 3: Run to verify failure**

`uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement the dialog skeleton**

Create `git_gui/presentation/dialogs/theme_dialog.py`:

```python
"""ThemeDialog — pick System/Light/Dark/Custom theme.

Custom mode (Task 3) opens a colour token editor. This file currently
contains the mode radios + Apply/Cancel/Reset wiring; the custom panel
is a placeholder.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.theme import get_theme_manager


_MODES: list[tuple[str, str]] = [
    ("system", "System"),
    ("dark",   "Dark"),
    ("light",  "Light"),
    ("custom", "Custom"),
]


class ThemeDialog(QDialog):
    """Modal dialog for choosing the active theme."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Theme")
        self.setModal(True)
        self.setMinimumSize(520, 400)

        self._mgr = get_theme_manager()
        layout = QVBoxLayout(self)

        # --- Mode radios ---
        mode_group = QGroupBox("Mode")
        mode_layout = QHBoxLayout(mode_group)
        self._mode_buttons = QButtonGroup(self)
        self._mode_buttons.setExclusive(True)
        for mode, label in _MODES:
            radio = QRadioButton(label)
            radio.setProperty("mode", mode)
            radio.setChecked(self._mgr.mode == mode)
            self._mode_buttons.addButton(radio)
            mode_layout.addWidget(radio)
            radio.toggled.connect(self._on_mode_radio_toggled)
        layout.addWidget(mode_group)

        # --- Custom panel (placeholder; populated by Task 3) ---
        self._custom_panel = QGroupBox("Custom")
        custom_layout = QVBoxLayout(self._custom_panel)
        custom_layout.addWidget(QLabel("Custom editor — populated in Task 3."))
        self._custom_panel.setEnabled(self._selected_mode() == "custom")
        layout.addWidget(self._custom_panel)

        layout.addStretch()

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel | QDialogButtonBox.Reset
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        buttons.button(QDialogButtonBox.Cancel).clicked.connect(self._on_cancel)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._on_reset)
        layout.addWidget(buttons)

    def _selected_mode(self) -> str:
        for radio in self._mode_buttons.buttons():
            if radio.isChecked():
                return radio.property("mode")
        return self._mgr.mode

    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        self._custom_panel.setEnabled(self._selected_mode() == "custom")

    def _on_apply(self) -> None:
        mode = self._selected_mode()
        # Custom mode write (Task 3) happens before set_mode so the file
        # exists when ThemeManager loads it.
        self._mgr.set_mode(mode)
        self.accept()

    def _on_cancel(self) -> None:
        self.reject()

    def _on_reset(self) -> None:
        # Task 3 reloads dark defaults into the editor here.
        pass
```

- [ ] **Step 5: Run the new tests**

`uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Run the full suite**

`uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/dialogs/__init__.py git_gui/presentation/dialogs/theme_dialog.py tests/presentation/dialogs/__init__.py tests/presentation/dialogs/test_theme_dialog.py
git commit -m "feat(dialogs): add ThemeDialog skeleton with mode radios"
```

---

## Task 3: Custom panel — typography scale + colour accordion

**Files:**
- Modify: `git_gui/presentation/dialogs/theme_dialog.py`
- Modify: `tests/presentation/dialogs/test_theme_dialog.py`

This is the main implementation task. Builds the custom panel: typography slider + 7-page `QToolBox` of colour swatches + Apply persistence + Reset.

- [ ] **Step 1: Define the group constants**

At the top of `theme_dialog.py` (after `_MODES`), add:

```python
_GROUPS: list[tuple[str, list[str]]] = [
    ("Brand", [
        "primary", "on_primary", "primary_container", "on_primary_container",
        "secondary", "on_secondary", "error", "on_error",
    ]),
    ("Surface", [
        "background", "on_background", "surface", "on_surface",
        "surface_variant", "on_surface_variant",
        "surface_container", "surface_container_high",
        "outline", "outline_variant",
    ]),
    ("Status badges", [
        "status_modified", "status_added", "status_deleted",
        "status_renamed", "status_unknown", "on_badge",
    ]),
    ("Branches & refs", [
        "branch_head_bg",
        "ref_badge_branch_bg", "ref_badge_tag_bg", "ref_badge_remote_bg",
    ]),
    ("Diff", [
        "diff_added_bg", "diff_added_fg",
        "diff_removed_bg", "diff_removed_fg",
        "diff_added_overlay", "diff_removed_overlay",
        "diff_file_header_fg", "diff_hunk_header_fg",
    ]),
    ("Misc", ["hover_overlay"]),
]

_GRAPH_LANE_PAGE_TITLE = "Graph lanes"  # special-cased: list[str], not single hex


_TYPOGRAPHY_SCALE_DEFAULT = 100
_TYPOGRAPHY_SCALE_MIN = 50
_TYPOGRAPHY_SCALE_MAX = 200
_TYPOGRAPHY_SCALE_STEP = 10
```

- [ ] **Step 2: Helpers — hex/QColor conversion**

Below the constants, add:

```python
from PySide6.QtGui import QColor


def _hex_for_token(token: str, qcolor: QColor) -> str:
    """Return the hex string for a token, hex8 (#AARRGGBB) for overlays."""
    if token.endswith("_overlay") or token == "hover_overlay":
        return "#{:02x}{:02x}{:02x}{:02x}".format(
            qcolor.alpha(), qcolor.red(), qcolor.green(), qcolor.blue()
        )
    return "#{:02x}{:02x}{:02x}".format(qcolor.red(), qcolor.green(), qcolor.blue())


def _qcolor_for_hex(hex_str: str) -> QColor:
    """QColor() handles both #RRGGBB and #AARRGGBB."""
    return QColor(hex_str)
```

- [ ] **Step 3: Build the custom panel inside `ThemeDialog.__init__`**

Replace the placeholder block (`self._custom_panel = QGroupBox("Custom") ... layout.addWidget(self._custom_panel)`) with this version:

```python
        # --- Custom panel ---
        self._custom_panel = self._build_custom_panel()
        self._custom_panel.setEnabled(self._selected_mode() == "custom")
        layout.addWidget(self._custom_panel)
```

And add these methods to the class (after `__init__`):

```python
    def _build_custom_panel(self) -> QGroupBox:
        from PySide6.QtWidgets import (
            QGridLayout, QPushButton, QSlider, QToolBox,
        )
        from git_gui.presentation.theme.loader import load_builtin

        panel = QGroupBox("Custom")
        outer = QVBoxLayout(panel)

        # --- Typography scale ---
        typo_row = QHBoxLayout()
        typo_row.addWidget(QLabel("Typography scale:"))
        self._typo_slider = QSlider(Qt.Horizontal)
        self._typo_slider.setRange(_TYPOGRAPHY_SCALE_MIN, _TYPOGRAPHY_SCALE_MAX)
        self._typo_slider.setSingleStep(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setPageStep(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
        self._typo_label = QLabel(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")
        self._typo_slider.valueChanged.connect(
            lambda v: self._typo_label.setText(f"{v}%")
        )
        typo_row.addWidget(self._typo_slider, 1)
        typo_row.addWidget(self._typo_label)
        outer.addLayout(typo_row)

        # --- Working colour state, prefilled from dark ---
        self._dark_defaults = load_builtin("dark")
        self._working_colors: dict[str, str] = {}
        self._working_lane_colors: list[str] = []
        self._swatch_buttons: dict[str, QPushButton] = {}
        self._lane_buttons: list[QPushButton] = []
        self._reset_to_dark_defaults_state()

        # --- Accordion (QToolBox) ---
        self._toolbox = QToolBox()
        for title, tokens in _GROUPS:
            page = QWidget()
            grid = QGridLayout(page)
            for row, token in enumerate(tokens):
                grid.addWidget(QLabel(token), row, 0)
                btn = QPushButton()
                btn.setFixedSize(40, 22)
                btn.setFlat(True)
                btn.clicked.connect(
                    lambda _checked=False, t=token: self._open_picker(t)
                )
                self._swatch_buttons[token] = btn
                self._apply_swatch_color(token, self._working_colors[token])
                grid.addWidget(btn, row, 1)
            grid.setColumnStretch(2, 1)
            self._toolbox.addItem(page, title)

        # Graph lanes page (special-case list[str])
        lanes_page = QWidget()
        lanes_layout = QVBoxLayout(lanes_page)
        lanes_layout.addWidget(QLabel("Graph lane colours (top = lane 0)"))
        lanes_row = QHBoxLayout()
        for i, hex_value in enumerate(self._working_lane_colors):
            btn = QPushButton()
            btn.setFixedSize(40, 22)
            btn.setFlat(True)
            btn.clicked.connect(
                lambda _checked=False, idx=i: self._open_lane_picker(idx)
            )
            self._lane_buttons.append(btn)
            self._apply_lane_swatch_color(i, hex_value)
            lanes_row.addWidget(btn)
        lanes_row.addStretch()
        lanes_layout.addLayout(lanes_row)
        lanes_layout.addStretch()
        self._toolbox.addItem(lanes_page, _GRAPH_LANE_PAGE_TITLE)

        outer.addWidget(self._toolbox, 1)
        return panel

    def _reset_to_dark_defaults_state(self) -> None:
        c = self._dark_defaults.colors
        self._working_colors = {}
        for _, tokens in _GROUPS:
            for token in tokens:
                self._working_colors[token] = getattr(c, token)
        self._working_lane_colors = list(c.graph_lane_colors)
        self._typo_slider_value_default()

    def _typo_slider_value_default(self) -> None:
        # Called from reset; the slider may not exist yet during initial build.
        if hasattr(self, "_typo_slider"):
            self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
            self._typo_label.setText(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")

    def _apply_swatch_color(self, token: str, hex_value: str) -> None:
        btn = self._swatch_buttons[token]
        # Use stylesheet so the swatch shows the colour, including alpha
        # blended over a checkered or solid background. For simplicity:
        # opaque colour rendered behind a label of the hex value.
        btn.setText(hex_value)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_value}; "
            f"border: 1px solid #888; padding: 0px; }}"
        )

    def _apply_lane_swatch_color(self, idx: int, hex_value: str) -> None:
        btn = self._lane_buttons[idx]
        btn.setText("")
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_value}; "
            f"border: 1px solid #888; padding: 0px; }}"
        )

    def _open_picker(self, token: str) -> None:
        from PySide6.QtWidgets import QColorDialog
        current = self._working_colors[token]
        initial = _qcolor_for_hex(current)
        is_overlay = token.endswith("_overlay") or token == "hover_overlay"
        options = (
            QColorDialog.ColorDialogOption.ShowAlphaChannel
            if is_overlay
            else QColorDialog.ColorDialogOptions()
        )
        chosen = QColorDialog.getColor(initial, self, f"Choose {token}", options=options)
        if chosen.isValid():
            new_hex = _hex_for_token(token, chosen)
            self._working_colors[token] = new_hex
            self._apply_swatch_color(token, new_hex)

    def _open_lane_picker(self, idx: int) -> None:
        from PySide6.QtWidgets import QColorDialog
        current = self._working_lane_colors[idx]
        initial = _qcolor_for_hex(current)
        chosen = QColorDialog.getColor(initial, self, f"Lane {idx}")
        if chosen.isValid():
            new_hex = "#{:02x}{:02x}{:02x}".format(
                chosen.red(), chosen.green(), chosen.blue()
            )
            self._working_lane_colors[idx] = new_hex
            self._apply_lane_swatch_color(idx, new_hex)
```

- [ ] **Step 4: Replace `_on_reset`**

Replace the placeholder `_on_reset` with:

```python
    def _on_reset(self) -> None:
        if self._selected_mode() != "custom":
            return
        self._reset_to_dark_defaults_state()
        for token, hex_value in self._working_colors.items():
            self._apply_swatch_color(token, hex_value)
        for i, hex_value in enumerate(self._working_lane_colors):
            self._apply_lane_swatch_color(i, hex_value)
```

- [ ] **Step 5: Replace `_on_apply` to handle custom**

Replace `_on_apply` with:

```python
    def _on_apply(self) -> None:
        mode = self._selected_mode()
        if mode == "custom":
            self._write_custom_theme()
        self._mgr.set_mode(mode)
        self.accept()
```

And add the writer:

```python
    def _write_custom_theme(self) -> None:
        import json
        import dataclasses
        from git_gui.presentation.theme.settings import custom_theme_path
        from git_gui.presentation.theme.tokens import (
            Colors, Theme, Typography, TextStyle,
        )

        scale = self._typo_slider.value() / 100.0
        dark = self._dark_defaults

        # Build typography with scaled sizes.
        scaled_styles = {}
        for field in dataclasses.fields(Typography):
            base: TextStyle = getattr(dark.typography, field.name)
            scaled_styles[field.name] = TextStyle(
                family=base.family,
                size=max(1, round(base.size * scale)),
                weight=base.weight,
                letter_spacing=base.letter_spacing,
            )

        colors_kwargs = dict(dataclasses.asdict(dark.colors))  # all defaults
        # Overwrite with edited tokens
        for token, hex_value in self._working_colors.items():
            colors_kwargs[token] = hex_value
        colors_kwargs["graph_lane_colors"] = list(self._working_lane_colors)

        custom_theme = Theme(
            name="Custom",
            is_dark=dark.is_dark,
            colors=Colors(**colors_kwargs),
            typography=Typography(**scaled_styles),
            shape=dark.shape,
            spacing=dark.spacing,
        )

        path = custom_theme_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_theme_to_json(custom_theme), indent=2))


def _theme_to_json(theme) -> dict:
    """Serialize Theme to a dict matching the loader's strict schema."""
    import dataclasses
    return {
        "name": theme.name,
        "is_dark": theme.is_dark,
        "colors": dataclasses.asdict(theme.colors),
        "typography": {
            field.name: dataclasses.asdict(getattr(theme.typography, field.name))
            for field in dataclasses.fields(type(theme.typography))
        },
        "shape": dataclasses.asdict(theme.shape),
        "spacing": dataclasses.asdict(theme.spacing),
    }
```

- [ ] **Step 6: Add a constructor flag to prefill from existing custom file**

If the user re-opens the dialog after a previous Apply, the custom panel should reflect the saved state, not dark defaults. Add this near the end of `__init__` (after `layout.addWidget(buttons)`):

```python
        self._maybe_load_existing_custom_theme()
```

And implement:

```python
    def _maybe_load_existing_custom_theme(self) -> None:
        from git_gui.presentation.theme.settings import custom_theme_path
        from git_gui.presentation.theme.loader import load_theme, ThemeValidationError
        path = custom_theme_path()
        if not path.exists():
            return
        try:
            theme = load_theme(path)
        except (OSError, ThemeValidationError):
            return

        c = theme.colors
        for token in list(self._working_colors.keys()):
            if hasattr(c, token):
                self._working_colors[token] = getattr(c, token)
                if token in self._swatch_buttons:
                    self._apply_swatch_color(token, getattr(c, token))
        self._working_lane_colors = list(c.graph_lane_colors)
        for i, hex_value in enumerate(self._working_lane_colors):
            if i < len(self._lane_buttons):
                self._apply_lane_swatch_color(i, hex_value)

        # Reverse-compute the typography scale from body_medium.size
        dark_size = self._dark_defaults.typography.body_medium.size
        if dark_size > 0:
            ratio = theme.typography.body_medium.size / dark_size
            slider_value = round(ratio * 100 / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
            slider_value = max(_TYPOGRAPHY_SCALE_MIN, min(_TYPOGRAPHY_SCALE_MAX, slider_value))
            self._typo_slider.setValue(slider_value)
            self._typo_label.setText(f"{slider_value}%")
```

- [ ] **Step 7: Add tests for the custom panel**

Append to `tests/presentation/dialogs/test_theme_dialog.py`:

```python
def test_custom_panel_disabled_when_mode_is_dark(app, reset_theme):
    get_theme_manager().set_mode("dark")
    dlg = ThemeDialog()
    assert not dlg._custom_panel.isEnabled()


def test_custom_panel_enables_when_custom_radio_clicked(app, reset_theme):
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    assert dlg._custom_panel.isEnabled()


def test_apply_custom_writes_file_and_sets_mode(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    # Mutate one swatch to a known value
    dlg._working_colors["primary"] = "#abcdef"
    dlg._on_apply()

    assert (tmp_path / "custom_theme.json").exists()
    assert get_theme_manager().mode == "custom"

    import json
    payload = json.loads((tmp_path / "custom_theme.json").read_text())
    assert payload["colors"]["primary"] == "#abcdef"


def test_reset_restores_dark_defaults(app, reset_theme):
    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._working_colors["primary"] = "#abcdef"
    dlg._apply_swatch_color("primary", "#abcdef")
    dlg._on_reset()
    from git_gui.presentation.theme.loader import load_builtin
    expected = load_builtin("dark").colors.primary
    assert dlg._working_colors["primary"] == expected


def test_typography_scale_applied_on_save(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg = ThemeDialog()
    _radios(dlg)["custom"].setChecked(True)
    dlg._typo_slider.setValue(150)
    dlg._on_apply()

    import json
    payload = json.loads((tmp_path / "custom_theme.json").read_text())
    from git_gui.presentation.theme.loader import load_builtin
    dark_body = load_builtin("dark").typography.body_medium.size
    assert payload["typography"]["body_medium"]["size"] == round(dark_body * 1.5)


def test_reopen_dialog_prefills_from_saved_file(app, reset_theme, tmp_path, monkeypatch):
    from git_gui.presentation.theme import settings as s
    monkeypatch.setattr(s, "custom_theme_path", lambda: tmp_path / "custom_theme.json")

    dlg1 = ThemeDialog()
    _radios(dlg1)["custom"].setChecked(True)
    dlg1._working_colors["primary"] = "#123456"
    dlg1._typo_slider.setValue(120)
    dlg1._on_apply()

    dlg2 = ThemeDialog()
    assert dlg2._working_colors["primary"] == "#123456"
    assert dlg2._typo_slider.value() == 120
```

- [ ] **Step 8: Run the tests**

`uv run pytest tests/presentation/dialogs/test_theme_dialog.py -v`
Expected: ALL PASS (4 from Task 2 + 6 new = 10).

If a test fails because of a method-name typo or a path detail, fix it inline. The QColorDialog itself isn't tested (it's modal and Qt-native).

- [ ] **Step 9: Run the full suite**

`uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 10: Commit**

```bash
git add git_gui/presentation/dialogs/theme_dialog.py tests/presentation/dialogs/test_theme_dialog.py
git commit -m "feat(dialogs): add custom theme editor (typography scale + colour accordion)"
```

---

## Task 4: Rewrite the appearance menu installer

**Files:**
- Modify: `git_gui/presentation/menus/appearance.py`
- Modify: `tests/presentation/menus/test_appearance.py`

- [ ] **Step 1: Read the existing appearance.py to confirm structure**

Read `git_gui/presentation/menus/appearance.py`. The current file installs a 3-action submenu with `QActionGroup`, `theme_changed` listener, etc. We're replacing all of it.

- [ ] **Step 2: Rewrite `appearance.py`**

Replace the entire file content with:

```python
"""Install a `View → Appearance...` menu item that opens the Theme dialog."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow

from git_gui.presentation.dialogs.theme_dialog import ThemeDialog


def install_appearance_menu(window: QMainWindow) -> None:
    """Add a `View → Appearance...` action to `window`'s menu bar.

    Clicking the action opens the Theme dialog.
    """
    bar = window.menuBar()
    view_menu = bar.addMenu("&View")
    action = QAction("&Appearance...", window)
    action.triggered.connect(lambda: ThemeDialog(window).exec())
    view_menu.addAction(action)
    # Hold a reference to keep the action alive.
    window._appearance_action = action  # type: ignore[attr-defined]
```

- [ ] **Step 3: Rewrite the menu test file**

Replace the entire content of `tests/presentation/menus/test_appearance.py` with:

```python
"""Tests for the View → Appearance menu installer."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow

from git_gui.presentation.menus.appearance import install_appearance_menu


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _appearance_action(window: QMainWindow):
    bar = window.menuBar()
    for action in bar.actions():
        if action.text().replace("&", "") == "View":
            view_menu = action.menu()
            for sub in view_menu.actions():
                if sub.text().replace("&", "").rstrip(".") == "Appearance":
                    return sub
    return None


def test_install_creates_appearance_action(app):
    window = QMainWindow()
    install_appearance_menu(window)
    action = _appearance_action(window)
    assert action is not None
    # It's a single action, not a submenu.
    assert action.menu() is None


def test_triggering_action_opens_theme_dialog(app, monkeypatch):
    """The action should construct a ThemeDialog and call exec()."""
    construction_count = {"n": 0}

    real_dialog_cls = None

    def fake_exec(self):
        construction_count["n"] += 1
        return 0

    from git_gui.presentation.dialogs import theme_dialog as td
    monkeypatch.setattr(td.ThemeDialog, "exec", fake_exec)

    window = QMainWindow()
    install_appearance_menu(window)
    _appearance_action(window).trigger()
    assert construction_count["n"] == 1
```

- [ ] **Step 4: Run the rewritten tests**

`uv run pytest tests/presentation/menus/test_appearance.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Run the full suite**

`uv run pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 6: Manual smoke**

`uv run python main.py`

- View → Appearance... opens the Theme dialog.
- Pick "Light", click Apply → app flips to light theme.
- Re-open the dialog, pick "Dark", Apply → flips back.
- Pick "Custom", expand "Brand" in the accordion, click the `primary` swatch — `QColorDialog` opens. Pick a colour, OK. The swatch updates.
- Click Apply → custom_theme.json is written, app picks up the new colour.
- Re-open the dialog, confirm the custom panel is prefilled with what you saved.

If the manual check fails for a specific reason (e.g. the colour picker doesn't show alpha for an overlay token, or the slider doesn't restore correctly), fix it before committing the manual confirmation.

- [ ] **Step 7: Commit**

```bash
git add git_gui/presentation/menus/appearance.py tests/presentation/menus/test_appearance.py
git commit -m "feat(menus): replace Appearance submenu with single Theme dialog action"
```

---

## Task 5: Final audit

- [ ] **Step 1: Run all tests**

`uv run pytest tests/ -v`
Expected: ALL PASS (existing + new dialog tests + new manager tests + rewritten menu tests).

- [ ] **Step 2: Audit for stale imports / dead code**

Run a grep for the now-removed `QActionGroup` usage in the menus package:

```bash
uv run python -c "
import os
for root, _, files in os.walk('git_gui/presentation/menus'):
    for f in files:
        if not f.endswith('.py'): continue
        p = os.path.join(root, f)
        t = open(p, encoding='utf-8').read()
        if 'QActionGroup' in t:
            print('STALE:', p)
"
```
Expected: no stale references.

- [ ] **Step 3: End-to-end manual check**

Repeat the smoke test from Task 4 Step 6, this time also:
- Toggle the typography slider to 150% and Apply with mode = Custom — confirm visible text scaling in the main window.
- Toggle back to 100% and Apply.
- Switch to Dark, then to Custom — confirm the saved customizations come back.

- [ ] **Step 4: No-op commit if everything is clean**

```bash
git status
```
If clean, no commit needed.

---

## Summary of Spec Coverage

| Spec section | Tasks |
|---|---|
| ThemeManager `"custom"` mode + fallback | 1 |
| `custom_theme_path()` helper | 1 |
| ThemeDialog skeleton (4 mode radios + Apply/Cancel/Reset) | 2 |
| Custom panel: typography scale slider | 3 |
| Custom panel: 7-page QToolBox accordion | 3 |
| Graph lanes special-case | 3 |
| Colour swatch + QColorDialog | 3 |
| Hex8 vs hex6 handling | 3 |
| Apply writes complete Theme JSON | 3 |
| Reopening dialog prefills from saved file | 3 |
| Reverse-computed typography slider position | 3 |
| Reset restores dark defaults | 3 |
| Menu rewrite — single action opens dialog | 4 |
| Tests for dialog, manager, menu | 1, 2, 3, 4 |
| Manual end-to-end | 4, 5 |
