"""ThemeDialog — pick System/Light/Dark/Custom theme."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

_GRAPH_LANE_PAGE_TITLE = "Graph lanes"

_TYPOGRAPHY_SCALE_DEFAULT = 100
_TYPOGRAPHY_SCALE_MIN = 50
_TYPOGRAPHY_SCALE_MAX = 200
_TYPOGRAPHY_SCALE_STEP = 10


def _hex_for_token(token: str, qcolor: QColor) -> str:
    """Return hex string for a token; hex8 (#AARRGGBB) for overlay tokens."""
    if token.endswith("_overlay") or token == "hover_overlay":
        return "#{:02x}{:02x}{:02x}{:02x}".format(
            qcolor.alpha(), qcolor.red(), qcolor.green(), qcolor.blue()
        )
    return "#{:02x}{:02x}{:02x}".format(qcolor.red(), qcolor.green(), qcolor.blue())


def _qcolor_for_hex(hex_str: str) -> QColor:
    return QColor(hex_str)


def _readable_fg_for(hex_value: str) -> str:
    """Return #000 or #fff depending on which contrasts better with hex_value.
    For overlay (#AARRGGBB) tokens, ignore alpha and judge by RGB."""
    s = hex_value.lstrip("#")
    if len(s) == 8:
        s = s[2:]
    try:
        r = int(s[0:2], 16); g = int(s[2:4], 16); b = int(s[4:6], 16)
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

        # --- Custom panel ---
        self._custom_panel = self._build_custom_panel()
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

        self._maybe_load_existing_custom_theme()

    def _selected_mode(self) -> str:
        for radio in self._mode_buttons.buttons():
            if radio.isChecked():
                return radio.property("mode")
        return self._mgr.mode

    def _on_mode_radio_toggled(self, _checked: bool) -> None:
        self._custom_panel.setEnabled(self._selected_mode() == "custom")

    def _build_custom_panel(self) -> QGroupBox:
        from PySide6.QtWidgets import QGridLayout, QPushButton, QSlider, QToolBox
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
        self._typo_slider.setTickInterval(_TYPOGRAPHY_SCALE_STEP)
        self._typo_slider.setTickPosition(QSlider.TicksBelow)
        self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
        self._typo_label = QLabel(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")

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
                btn.setFixedSize(80, 22)
                btn.setFlat(True)
                btn.clicked.connect(
                    lambda _checked=False, t=token: self._open_picker(t)
                )
                self._swatch_buttons[token] = btn
                self._apply_swatch_color(token, self._working_colors[token])
                grid.addWidget(btn, row, 1)
            grid.setColumnStretch(2, 1)
            self._toolbox.addItem(page, title)

        # Graph lanes page (special-case: list[str])
        lanes_page = QWidget()
        lanes_layout = QVBoxLayout(lanes_page)
        lanes_layout.addWidget(QLabel("Graph lane colours (left = lane 0)"))
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
        if hasattr(self, "_typo_slider"):
            self._typo_slider.setValue(_TYPOGRAPHY_SCALE_DEFAULT)
            self._typo_label.setText(f"{_TYPOGRAPHY_SCALE_DEFAULT}%")

    def _apply_swatch_color(self, token: str, hex_value: str) -> None:
        btn = self._swatch_buttons[token]
        btn.setText(hex_value)
        fg = _readable_fg_for(hex_value)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {hex_value}; color: {fg}; "
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

    def _on_apply(self) -> None:
        mode = self._selected_mode()
        if mode == "custom":
            self._write_custom_theme()
        self._mgr.set_mode(mode, force=(mode == "custom"))
        self.accept()

    def _on_cancel(self) -> None:
        self.reject()

    def _on_reset(self) -> None:
        if self._selected_mode() != "custom":
            return
        self._reset_to_dark_defaults_state()
        for token, hex_value in self._working_colors.items():
            self._apply_swatch_color(token, hex_value)
        for i, hex_value in enumerate(self._working_lane_colors):
            self._apply_lane_swatch_color(i, hex_value)

    def _write_custom_theme(self) -> None:
        import json
        import dataclasses
        from git_gui.presentation.theme import settings as _settings
        from git_gui.presentation.theme.tokens import (
            Colors, Theme, Typography, TextStyle,
        )

        scale = self._typo_slider.value() / 100.0
        dark = self._dark_defaults

        scaled_styles = {}
        for field in dataclasses.fields(Typography):
            base: TextStyle = getattr(dark.typography, field.name)
            scaled_styles[field.name] = TextStyle(
                family=base.family,
                size=max(1, round(base.size * scale)),
                weight=base.weight,
                letter_spacing=base.letter_spacing,
            )

        colors_kwargs = dict(dataclasses.asdict(dark.colors))
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

        path = _settings.custom_theme_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_theme_to_json(custom_theme), indent=2))

    def _maybe_load_existing_custom_theme(self) -> None:
        from git_gui.presentation.theme import settings as _settings
        from git_gui.presentation.theme.loader import load_theme, ThemeValidationError
        path = _settings.custom_theme_path()
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

        dark_size = self._dark_defaults.typography.body_medium.size
        if dark_size > 0:
            ratio = theme.typography.body_medium.size / dark_size
            slider_value = round(ratio * 100 / _TYPOGRAPHY_SCALE_STEP) * _TYPOGRAPHY_SCALE_STEP
            slider_value = max(_TYPOGRAPHY_SCALE_MIN, min(_TYPOGRAPHY_SCALE_MAX, slider_value))
            self._typo_slider.setValue(slider_value)
            self._typo_label.setText(f"{slider_value}%")


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
