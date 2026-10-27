"""ThemeDialog — pick System/Light/Dark/Custom theme."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.theme import ThemeMode, get_theme_manager
from git_gui.presentation.theme import settings as _settings
from git_gui.presentation.theme.loader import load_builtin
from git_gui.presentation.theme.tokens import Theme
from git_gui.presentation.widgets.avatar_loader import get_avatar_loader

_log = logging.getLogger(__name__)

_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Brand",
        [
            "primary",
            "on_primary",
            "primary_container",
            "on_primary_container",
            "secondary",
            "on_secondary",
            "error",
            "on_error",
        ],
    ),
    (
        "Surface",
        [
            "background",
            "on_background",
            "surface",
            "on_surface",
            "surface_variant",
            "on_surface_variant",
            "surface_container",
            "surface_container_high",
            "outline",
            "outline_variant",
        ],
    ),
    (
        "Status badges",
        [
            "status_modified",
            "status_added",
            "status_deleted",
            "status_renamed",
            "status_unknown",
            "on_badge",
        ],
    ),
    (
        "Branches & refs",
        [
            "branch_head_bg",
            "ref_badge_branch_bg",
            "ref_badge_tag_bg",
            "ref_badge_remote_bg",
        ],
    ),
    (
        "Diff",
        [
            "diff_added_bg",
            "diff_added_fg",
            "diff_removed_bg",
            "diff_removed_fg",
            "diff_added_overlay",
            "diff_removed_overlay",
            "diff_file_header_fg",
            "diff_hunk_header_fg",
        ],
    ),
    ("Misc", ["hover_overlay"]),
]

_GRAPH_LANE_PAGE_TITLE = "Graph lanes"

_TYPOGRAPHY_SCALE_DEFAULT = 100
_TYPOGRAPHY_SCALE_MIN = 50
_TYPOGRAPHY_SCALE_MAX = 200
_TYPOGRAPHY_SCALE_STEP = 10


def _hex_for_token(token: str, qcolor: QColor) -> str:
    """Return hex string for a token; hex8 (#AARRGGBB) for overlay tokens."""
    if token.endswith("_overlay") or token == "hover_overlay":
        return f"#{qcolor.alpha():02x}{qcolor.red():02x}{qcolor.green():02x}{qcolor.blue():02x}"
    return f"#{qcolor.red():02x}{qcolor.green():02x}{qcolor.blue():02x}"


def _qcolor_for_hex(hex_str: str) -> QColor:
    return QColor(hex_str)


def _readable_fg_for(hex_value: str) -> str:
    """Return #000 or #fff depending on which contrasts better with hex_value.
    For overlay (#AARRGGBB) tokens, ignore alpha and judge by RGB."""
    s = hex_value.lstrip("#")
    if len(s) == 8:
        s = s[2:]
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        return "#000"
    # Perceived luminance
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000" if lum > 140 else "#fff"


class ThemeDialog(QDialog):
    """Modal dialog for choosing the active theme."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Theme")
        self.setModal(True)
        self.setMinimumSize(520, 400)

        self._mgr = get_theme_manager()
        layout = QVBoxLayout(self)

        # --- Avatars ---
        avatar_group = QGroupBox("Avatars")
        avatar_layout = QVBoxLayout(avatar_group)
        self._gravatar_checkbox = QCheckBox(
            "Fetch avatars from Gravatar (sends a hash of the author email to gravatar.com)"
        )
        self._gravatar_checkbox.setChecked(
            bool(_settings.load_settings().get("avatar_gravatar_enabled", True))
        )
        avatar_layout.addWidget(self._gravatar_checkbox)
        layout.addWidget(avatar_group)

        # --- Mode radios ---
        mode_group = QGroupBox("Mode")
        mode_layout = QHBoxLayout(mode_group)
        self._mode_buttons = QButtonGroup(self)
        self._mode_buttons.setExclusive(True)
        for mode in ThemeMode:
            radio = QRadioButton(mode.value.title())
            radio.setProperty("mode", mode)
            radio.setChecked(self._mgr.mode is mode)
            self._mode_buttons.addButton(radio)
            mode_layout.addWidget(radio)
            radio.toggled.connect(self._on_mode_radio_toggled)
        layout.addWidget(mode_group)

        # _base_theme drives the Custom panel's swatch pre-fill and is
        # re-seeded whenever the user toggles the mode radio.
        # _base_theme_mode remembers the mode that produced the current
        # pre-fill so the toggle handler can short-circuit no-op refreshes.
        self._base_theme_mode = self._mgr.mode
        self._base_theme = self._mgr.theme_for_mode(self._base_theme_mode)
        # A saved Custom theme carries Dark's unscaled typography, not the
        # prefill theme's: typography_scale is applied at runtime in every
        # mode, and a file saved before that setting existed has it baked in.
        self._custom_typography = load_builtin("dark").typography

        # --- Custom panel ---
        self._custom_panel = self._build_custom_panel()
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

        self._maybe_load_existing_custom_theme()

    def _selected_mode(self) -> ThemeMode:
        for radio in self._mode_buttons.buttons():
            if radio.isChecked():
                return ThemeMode(radio.property("mode"))
        return self._mgr.mode

    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        mode = self._selected_mode()
        if mode is self._base_theme_mode or mode is ThemeMode.CUSTOM:
            return
        self._base_theme_mode = mode
        self._base_theme = self._mgr.theme_for_mode(mode)
        self._reset_to_base_state()
        self._show_working_colors()

    def _build_custom_panel(self) -> QGroupBox:
        from PySide6.QtWidgets import QGridLayout, QSlider, QToolBox

        panel = QGroupBox("Custom")
        outer = QVBoxLayout(panel)

        # --- Typography scale ---
        typo_row = QHBoxLayout()
        typo_row.addWidget(QLabel("Typography scale:"))
        self._typo_slider = QSlider(Qt.Horizontal)
        self._typo_slider.setRange(_TYPOGRAPHY_SCALE_MIN, _TYPOGRAPHY_SCALE_MAX)
        self._typo_slider.setSingleStep(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setPageStep(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setTickInterval(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setTickPosition(QSlider.TicksBelow)
        saved_scale = float(_settings.load_settings().get("typography_scale", 1.0))
        initial_value = round(saved_scale * 100 / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
        initial_value = max(_TYPOGRAPHY_SCALE_MIN, min(_TYPOGRAPHY_SCALE_MAX, initial_value))
        self._typo_slider.setValue(initial_value)
        self._typo_label = QLabel(f"{initial_value}%")

        def _snap_typo(v: int) -> None:
            snapped = round(v / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
            if snapped != v:
                self._typo_slider.blockSignals(True)
                self._typo_slider.setValue(snapped)
                self._typo_slider.blockSignals(False)
            self._typo_label.setText(f"{snapped}%")

        self._typo_slider.valueChanged.connect(_snap_typo)
        typo_row.addWidget(self._typo_slider, 1)
        typo_row.addWidget(self._typo_label)
        outer.addLayout(typo_row)

        # --- Working colour state, prefilled from the currently-active theme ---
        self._working_colors: dict[str, str] = {}
        self._working_lane_colors: list[str] = []
        self._swatch_buttons: dict[str, QPushButton] = {}
        self._lane_buttons: list[QPushButton] = []
        self._reset_to_base_state()

        # --- Accordion (QToolBox) ---
        self._toolbox = QToolBox()
        for title, tokens in _GROUPS:
            page = QWidget()
            grid = QGridLayout(page)
            for row, token in enumerate(tokens):
                grid.addWidget(QLabel(token), row, 0)
                btn = QPushButton()
                btn.setFixedSize(80, 22)
                btn.setFlat(True)
                btn.clicked.connect(lambda _checked=False, t=token: self._open_picker(t))
                self._swatch_buttons[token] = btn
                self._apply_swatch_color(token, self._working_colors[token])
                grid.addWidget(btn, row, 1)
            grid.setColumnStretch(2, 1)
            self._toolbox.addItem(page, title)

        # Graph lanes page (special-case: list[str])
        lanes_page = QWidget()
        lanes_layout = QVBoxLayout(lanes_page)
        lanes_layout.addWidget(QLabel("Graph lane colours (left = lane 0)"))
        self._lanes_row = QHBoxLayout()
        self._lanes_row.addStretch()
        self._show_lane_colors()
        lanes_layout.addLayout(self._lanes_row)
        lanes_layout.addStretch()
        self._toolbox.addItem(lanes_page, _GRAPH_LANE_PAGE_TITLE)

        outer.addWidget(self._toolbox, 1)
        return panel

    def _reset_to_base_state(self) -> None:
        self._fill_working_state(self._base_theme)

    def _fill_working_state(self, theme: Theme) -> None:
        c = theme.colors
        self._working_colors = {
            token: getattr(c, token) for _, tokens in _GROUPS for token in tokens
        }
        self._working_lane_colors = list(c.graph_lane_colors)
        self._prefill_theme = theme

    def _show_working_colors(self) -> None:
        for token, hex_value in self._working_colors.items():
            self._apply_swatch_color(token, hex_value)
        self._show_lane_colors()

    def _show_lane_colors(self) -> None:
        # One button per working lane: a saved theme may list more or fewer
        # lanes than the builtins, and Apply saves every lane it lists.
        while len(self._lane_buttons) < len(self._working_lane_colors):
            self._add_lane_button()
        while len(self._lane_buttons) > len(self._working_lane_colors):
            stale = self._lane_buttons.pop()
            stale.setParent(None)  # leaves the row and the screen at once
            stale.deleteLater()
        for i, hex_value in enumerate(self._working_lane_colors):
            self._apply_lane_swatch_color(i, hex_value)

    def _add_lane_button(self) -> None:
        idx = len(self._lane_buttons)
        btn = QPushButton()
        btn.setFixedSize(40, 22)
        btn.setFlat(True)
        btn.clicked.connect(lambda _checked=False: self._open_lane_picker(idx))
        self._lane_buttons.append(btn)
        self._lanes_row.insertWidget(idx, btn)  # ahead of the trailing stretch

    def _apply_swatch_color(self, token: str, hex_value: str) -> None:
        btn = self._swatch_buttons[token]
        btn.setText(hex_value)
        # The label beside it names the token for sighted users only.
        btn.setAccessibleName(f"{token} colour {hex_value}")
        btn.setStyleSheet(self._swatch_style(hex_value, _readable_fg_for(hex_value)))

    def _apply_lane_swatch_color(self, idx: int, hex_value: str) -> None:
        btn = self._lane_buttons[idx]
        btn.setText("")
        btn.setAccessibleName(f"Graph lane {idx} colour {hex_value}")
        btn.setStyleSheet(self._swatch_style(hex_value))

    def _swatch_style(self, background: str, text: str | None = None) -> str:
        text_rule = f"color: {text}; " if text else ""
        border = self._mgr.current.colors.outline
        return (
            f"QPushButton {{ background-color: {background}; {text_rule}"
            f"border: 1px solid {border}; padding: 0px; }}"
        )

    def _open_picker(self, token: str) -> None:
        if self._selected_mode() is not ThemeMode.CUSTOM:
            return
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
        if self._selected_mode() is not ThemeMode.CUSTOM:
            return
        from PySide6.QtWidgets import QColorDialog

        current = self._working_lane_colors[idx]
        initial = _qcolor_for_hex(current)
        chosen = QColorDialog.getColor(initial, self, f"Lane {idx}")
        if chosen.isValid():
            new_hex = f"#{chosen.red():02x}{chosen.green():02x}{chosen.blue():02x}"
            self._working_lane_colors[idx] = new_hex
            self._apply_lane_swatch_color(idx, new_hex)

    def _on_apply(self) -> None:
        try:
            self._save_and_apply()
        except OSError as e:
            QMessageBox.warning(self, "Save appearance failed", str(e))
            return
        self.accept()

    def _save_and_apply(self) -> None:
        mode = self._selected_mode()
        scale = self._typo_slider.value() / 100.0
        if mode is ThemeMode.CUSTOM:
            # The custom file goes first, so a failure there leaves the saved
            # scale and mode as they were, matching what is still on screen;
            # a failure saving those puts the previous custom file back.
            with _restored_on_failure(_settings.custom_theme_path()):
                self._write_custom_theme()
                self._mgr.set_appearance(mode, scale)
        else:
            self._mgr.set_appearance(mode, scale)
        self._save_avatar_setting()

    def _save_avatar_setting(self) -> None:
        enabled = self._gravatar_checkbox.isChecked()
        data = _settings.load_settings()
        if data.get("avatar_gravatar_enabled") == enabled:
            return
        data["avatar_gravatar_enabled"] = enabled
        _settings.save_settings(data)
        get_avatar_loader().set_enabled(enabled)

    def _on_cancel(self) -> None:
        self.reject()

    def _on_reset(self) -> None:
        if self._selected_mode() is not ThemeMode.CUSTOM:
            return
        self._reset_to_base_state()
        self._show_working_colors()

    def _write_custom_theme(self) -> None:
        import dataclasses
        import json

        from git_gui.presentation.theme import settings as _settings
        from git_gui.presentation.theme.tokens import Colors

        # Tokens without a swatch come from the theme the swatches were
        # filled from, so a saved theme never pairs one theme's surfaces
        # with another's syntax colours.
        base = self._prefill_theme

        colors_kwargs = dict(dataclasses.asdict(base.colors))
        for token, hex_value in self._working_colors.items():
            colors_kwargs[token] = hex_value
        colors_kwargs["graph_lane_colors"] = list(self._working_lane_colors)

        custom_theme = Theme(
            name="Custom",
            is_dark=base.is_dark,
            colors=Colors(**colors_kwargs),
            typography=self._custom_typography,
            shape=base.shape,
            spacing=base.spacing,
        )

        path = _settings.custom_theme_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_theme_to_json(custom_theme), indent=2))

    def _maybe_load_existing_custom_theme(self) -> None:
        from git_gui.presentation.theme import settings as _settings
        from git_gui.presentation.theme.loader import ThemeValidationError, load_theme

        path = _settings.custom_theme_path()
        if not path.exists():
            return
        try:
            theme = load_theme(path)
        except (OSError, ThemeValidationError):
            return
        self._fill_working_state(theme)
        self._show_working_colors()


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


@contextmanager
def _restored_on_failure(path: Path) -> Iterator[None]:
    """Put the file at *path* back as it was if the block raises OSError."""
    previous = path.read_bytes() if path.exists() else None
    try:
        yield
    except OSError:
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)
        except OSError as e:  # the error the user is shown is the first one
            _log.warning("Could not restore %s: %s", path, e)
        raise
