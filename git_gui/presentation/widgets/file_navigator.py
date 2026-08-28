"""FileNavigatorWidget — vertical list / horizontal pill strip for files in a commit.

Wraps a FileListView and (in pill mode, see Task 3) a horizontal strip of pill
buttons. Both share the same selection model so click-to-filter works
identically regardless of which mode is active.

Mode-switch and active-file highlight are driven externally — by
DiffWidget's _StickyPinController in the case of pin/unpin, and by scroll-
based auto-highlight logic.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListView,
    QMenu,
    QScrollArea,
    QStackedLayout,
    QToolButton,
    QWidget,
)

from git_gui.presentation.models.diff_model import DiffModel
from git_gui.presentation.theme import connect_widget, get_theme_manager
from git_gui.presentation.widgets.file_list_view import FileDeltaDelegate, FileListView


class _HorizontalWheelScrollArea(QScrollArea):
    """QScrollArea that scrolls horizontally on wheel events instead of vertically.

    Used for the pill strip — the strip itself never scrolls vertically (it's
    one row of pills), but the user expects the wheel to move it left/right
    when there are more pills than fit. Without this, wheel events are
    swallowed (because vertical scroll is disabled) and the user can't
    reach offscreen pills without dragging the horizontal scrollbar.
    """

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - delta)
        event.accept()


class NavMode(Enum):
    LIST = 0
    PILL = 1


def _delta_dot_icon(delta: str, diameter: int = 8) -> QIcon:
    """Generate a circle-icon pixmap colored by the file's delta status."""
    pix = QPixmap(diameter, diameter)
    pix.fill(QColor(0, 0, 0, 0))  # transparent
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    color = get_theme_manager().current.colors.status_color(delta)
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, diameter, diameter)
    painter.end()
    return QIcon(pix)


class FileNavigatorWidget(QWidget):
    file_history_requested = Signal(str)  # repo-relative path
    blame_requested = Signal(str)  # repo-relative path

    """Two-shape file navigator backed by a shared QItemSelectionModel."""

    # Re-exposes signals from the shared selection model + list view so callers
    # don't have to know the internal structure.
    currentChanged = Signal(QModelIndex, QModelIndex)
    deselected = Signal()

    def __init__(self, model: DiffModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._model = model

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        # ── List mode ────────────────────────────────────────────────────────
        self._list_view = FileListView(max_visible_rows=8)
        self._list_view.setEditTriggers(QListView.NoEditTriggers)
        self._list_view.setModel(model)
        self._list_view.setItemDelegate(FileDeltaDelegate(self._list_view))
        self._list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_view.customContextMenuRequested.connect(self._on_list_context_menu)
        self._stack.addWidget(self._list_view)

        # ── Pill mode ────────────────────────────────────────────────────────
        self._pill_root = _HorizontalWheelScrollArea()
        self._pill_root.setWidgetResizable(True)
        self._pill_root.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pill_root.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._pill_root.setFrameShape(QScrollArea.NoFrame)
        self._pill_root.setViewportMargins(0, 0, 0, 0)

        self._pill_container = QWidget()
        self._pill_layout = QHBoxLayout(self._pill_container)
        self._pill_layout.setContentsMargins(4, 0, 4, 0)
        self._pill_layout.setSpacing(4)
        self._pill_layout.addStretch(1)  # right-side filler
        self._pill_root.setWidget(self._pill_container)
        self._stack.addWidget(self._pill_root)

        # "All" synthetic pill (always present, at index 0).
        self._all_pill = QToolButton()
        self._all_pill.setText("All")
        self._all_pill.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._all_pill.setCheckable(True)
        self._all_pill.setFixedHeight(20)
        self._all_pill.setChecked(True)
        self._all_pill.clicked.connect(self._on_all_pill_clicked)
        self._pill_layout.insertWidget(0, self._all_pill)

        self._pill_buttons: dict[str, QToolButton] = {}
        self._build_pills()
        model.modelReset.connect(self._build_pills)
        # FileListView's updateGeometry only bubbles up through the
        # QStackedLayout, not up to the navigator's parent layout. Without
        # this, the parent slot keeps the empty-model height (~32px) even
        # after files are loaded.
        model.modelReset.connect(self.updateGeometry)

        # Sync pill check state from selection model changes (so list-view
        # clicks update pill highlight too).
        self._list_view.selectionModel().currentChanged.connect(self._sync_pills_to_selection)
        self._list_view.deselected.connect(self._sync_pills_to_selection_cleared)

        connect_widget(self, rebuild=self._restyle_pills)
        self._restyle_pills()

        # Wire signal forwarding.
        self._list_view.selectionModel().currentChanged.connect(self.currentChanged.emit)
        self._list_view.deselected.connect(self.deselected.emit)

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def selection_model(self) -> QItemSelectionModel:
        return self._list_view.selectionModel()

    def mode(self) -> NavMode:
        return NavMode(self._stack.currentIndex())

    def set_mode(self, mode: NavMode) -> None:
        self._stack.setCurrentIndex(mode.value)
        # QStackedLayout's sizeHint is max(children); we override sizeHint
        # to return only the active child's, but we have to nudge the
        # parent layout to re-read it after the index changes.
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        # Default QStackedLayout.sizeHint returns max of all children, which
        # bleeds the LIST mode's tall row count into the PILL mode's
        # one-row footprint. Return the active child's hint instead.
        current = self._stack.currentWidget()
        if current is None:
            return super().sizeHint()
        return current.sizeHint()

    def minimumSizeHint(self) -> QSize:
        current = self._stack.currentWidget()
        if current is None:
            return super().minimumSizeHint()
        return current.minimumSizeHint()

    # ── Pill management ─────────────────────────────────────────────────────

    def _build_pills(self) -> None:
        """Tear down current per-file pills and rebuild from the model."""
        # Remove existing per-file pills (skip the "All" pill at index 0 and
        # the trailing stretch).
        for btn in list(self._pill_buttons.values()):
            self._pill_layout.removeWidget(btn)
            btn.deleteLater()
        self._pill_buttons.clear()

        for row in range(self._model.rowCount()):
            idx = self._model.index(row)
            fs = self._model.data(idx, Qt.UserRole)
            if fs is None:
                continue
            btn = QToolButton()
            btn.setText(fs.path)
            btn.setIcon(_delta_dot_icon(fs.delta))
            btn.setIconSize(QSize(10, 10))
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setCheckable(True)
            btn.setFixedHeight(20)
            btn.setChecked(False)
            btn.clicked.connect(lambda _checked=False, r=row: self._on_pill_clicked(r))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, fp=fs.path: self._show_file_menu(b.mapToGlobal(pos), fp)
            )
            # Insert before the stretch (which is at the end).
            insert_at = self._pill_layout.count() - 1
            self._pill_layout.insertWidget(insert_at, btn)
            self._pill_buttons[fs.path] = btn

        # Reset highlight to "All".
        self._all_pill.setChecked(not self.selection_model.hasSelection())

        # New pill widgets need their QSS applied; the construction-time
        # _restyle_pills call only saw _all_pill.
        self._restyle_pills()

    def _show_file_menu(self, global_pos, path: str) -> None:
        menu = QMenu(self)
        history_action = menu.addAction("Show file history")
        blame_action = menu.addAction("Blame this file")
        chosen = menu.exec(global_pos)
        if chosen is history_action:
            self.file_history_requested.emit(path)
        elif chosen is blame_action:
            self.blame_requested.emit(path)

    def _on_list_context_menu(self, pos) -> None:
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return
        fs = self._model.data(index, Qt.UserRole)
        if fs is None:
            return
        self._show_file_menu(self._list_view.viewport().mapToGlobal(pos), fs.path)

    def _on_pill_clicked(self, row: int) -> None:
        """Drive the shared selection model. Visual pill state will follow via
        _sync_pills_to_selection. The explicit resync at the end handles the case
        where the user re-clicks the already-active pill: setCurrentIndex is a
        no-op (no currentChanged signal), but click() already toggled the pill's
        visual checked state to False — we reset it from the selection model.
        """
        idx = self._model.index(row)
        self.selection_model.setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self._sync_pills_to_selection(self.selection_model.currentIndex(), QModelIndex())

    def _on_all_pill_clicked(self) -> None:
        self.selection_model.clearSelection()
        self._list_view.setCurrentIndex(QModelIndex())
        self._sync_pills_to_selection_cleared()
        self.deselected.emit()

    def _sync_pills_to_selection(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._sync_pills_to_selection_cleared()
            return
        fs = self._model.data(current, Qt.UserRole)
        active_path = fs.path if fs else None
        for path, btn in self._pill_buttons.items():
            btn.setChecked(path == active_path)
        self._all_pill.setChecked(active_path is None)

    def _sync_pills_to_selection_cleared(self) -> None:
        for btn in self._pill_buttons.values():
            btn.setChecked(False)
        self._all_pill.setChecked(True)

    # ── set_active_file (visual-only highlight; does not change selection) ──

    def set_active_file(self, path: str | None) -> None:
        """Visually highlight a pill (and ensure it is on screen) without
        changing the selection model. Used by auto-highlight on scroll.

        DO NOT call this in response to a pill click; pill clicks must go
        through `_on_pill_clicked` so the selection model becomes the source
        of truth. This method is for read-only visual sync from external
        state (e.g., the diff scroll position).
        """
        # Unknown / stale path or explicit None → highlight "All".
        if path is None or path not in self._pill_buttons:
            self._all_pill.setChecked(True)
            for btn in self._pill_buttons.values():
                btn.setChecked(False)
            return

        self._all_pill.setChecked(False)
        active_btn = self._pill_buttons[path]
        for p, btn in self._pill_buttons.items():
            btn.setChecked(p == path)
        self._pill_root.ensureWidgetVisible(active_btn)

    # ── Theming ─────────────────────────────────────────────────────────────

    def _restyle_pills(self) -> None:
        c = get_theme_manager().current.colors
        bg = c.surface_container_high
        outline = c.outline
        on_surface = c.on_surface
        primary = c.primary
        on_primary = c.on_primary

        # Full state coverage so Qt's native Windows style fully yields to
        # our QSS. Without :hover, :pressed, :focus, and outline:none the
        # native style bleeds through and produces sharp-cornered gray
        # rectangles instead of rounded MD3 pills.
        pill_qss = (
            f"QToolButton {{"
            f"  background: {bg};"
            f"  color: {on_surface};"
            f"  border: 1px solid {outline};"
            f"  border-radius: 10px;"
            f"  padding: 1px 10px;"
            f"  outline: none;"
            f"}}"
            f"QToolButton:hover {{"
            f"  border-color: {primary};"
            f"}}"
            f"QToolButton:pressed {{"
            f"  background: {primary};"
            f"  color: {on_primary};"
            f"  border-color: {primary};"
            f"}}"
            f"QToolButton:checked {{"
            f"  background: {primary};"
            f"  color: {on_primary};"
            f"  border-color: {primary};"
            f"}}"
            f"QToolButton:checked:hover {{"
            f"  background: {primary};"
            f"  border-color: {primary};"
            f"}}"
            f"QToolButton:focus {{"
            f"  outline: none;"
            f"}}"
        )
        self._all_pill.setStyleSheet(pill_qss)
        for btn in self._pill_buttons.values():
            btn.setStyleSheet(pill_qss)
