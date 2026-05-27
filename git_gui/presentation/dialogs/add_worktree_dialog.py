from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


def _sanitize_branch(branch: str) -> str:
    """Replace path-unfriendly chars in a branch name for the default path."""
    return branch.replace("/", "-")


def _default_location(repo_path: str, branch: str) -> str:
    """Compute `{repo_parent}/{repo_name}-{sanitized_branch}`."""
    p = Path(repo_path)
    parent = p.parent
    name = p.name or "worktree"
    return str(parent / f"{name}-{_sanitize_branch(branch or 'new')}")


class AddWorktreeDialog(QDialog):
    add_requested = Signal(dict)  # {branch, create_new, base_ref, location, switch_after}
    switch_to_existing_requested = Signal(str)  # path of the owning worktree

    def __init__(
        self,
        repo_path: str,
        branches: list[str],
        branches_in_use: dict[str, str] | None = None,
        preselect_branch: str | None = None,
        default_create_new: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Worktree")
        self._repo_path = repo_path
        self._branches_in_use = dict(branches_in_use or {})
        self._location_dirty = False  # True once user manually edits the path

        # Branch combo (existing-branch mode).
        self._branch_combo = QComboBox()
        for b in branches:
            self._branch_combo.addItem(b)
            if b in self._branches_in_use:
                idx = self._branch_combo.count() - 1
                item = self._branch_combo.model().item(idx)
                item.setEnabled(False)
                item.setToolTip(f"Already checked out at {self._branches_in_use[b]}")

        # Create-new mode widgets.
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("feature/my-branch")
        self._base_ref = QComboBox()
        for b in branches:
            self._base_ref.addItem(b)
        new_branch_widget = QWidget()
        new_form = QFormLayout(new_branch_widget)
        new_form.setContentsMargins(0, 0, 0, 0)
        new_form.addRow("New name:", self._new_name)
        new_form.addRow("Base ref:", self._base_ref)

        # Switch between existing-combo and new-name field.
        self._mode_stack = QStackedWidget()
        existing_widget = QWidget()
        existing_layout = QHBoxLayout(existing_widget)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        existing_layout.addWidget(self._branch_combo)
        self._mode_stack.addWidget(existing_widget)
        self._mode_stack.addWidget(new_branch_widget)

        # "Create new branch" checkbox above the stack.
        self._create_new_cb = QCheckBox("Create new branch")
        self._create_new_cb.toggled.connect(self._on_create_new_toggled)

        # Location row.
        self._location_edit = QLineEdit()
        self._location_edit.textEdited.connect(self._on_location_edited)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.clicked.connect(self._on_browse)
        loc_row = QHBoxLayout()
        loc_row.addWidget(self._location_edit, 1)
        loc_row.addWidget(self._browse_btn)

        # Switch-after checkbox.
        self._switch_after_cb = QCheckBox("Switch to new worktree after creating")
        self._switch_after_cb.setChecked(True)

        # Form layout.
        form = QFormLayout()
        form.addRow("Branch:", self._create_new_cb)
        form.addRow("", self._mode_stack)
        form.addRow("Location:", loc_row)
        form.addRow("", self._switch_after_cb)

        # Buttons.
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Add")
        self._buttons.accepted.connect(self.submit)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        # Live-update the location template.
        self._branch_combo.currentTextChanged.connect(self._on_branch_changed)
        self._new_name.textChanged.connect(self._on_new_name_changed)

        # Initial preselect + state.
        self._create_new_cb.setChecked(default_create_new)
        if preselect_branch and preselect_branch in branches and not default_create_new:
            idx = self._branch_combo.findText(preselect_branch)
            if idx >= 0:
                self._branch_combo.setCurrentIndex(idx)
        self._refresh_default_location()
        self._refresh_add_button()

    # ── Public state accessors ──────────────────────────────────────────

    def is_create_new(self) -> bool:
        return self._create_new_cb.isChecked()

    def set_create_new(self, value: bool) -> None:
        self._create_new_cb.setChecked(value)

    def select_branch(self, name: str) -> None:
        idx = self._branch_combo.findText(name)
        if idx >= 0:
            self._branch_combo.setCurrentIndex(idx)

    def new_branch_name(self) -> str:
        return self._new_name.text().strip()

    def set_new_branch_name(self, name: str) -> None:
        self._new_name.setText(name)

    def base_ref(self) -> str:
        return self._base_ref.currentText().strip()

    def set_base_ref(self, name: str) -> None:
        idx = self._base_ref.findText(name)
        if idx >= 0:
            self._base_ref.setCurrentIndex(idx)

    def location(self) -> str:
        return self._location_edit.text().strip()

    def set_location(self, value: str) -> None:
        # Programmatic set marks the dirty bit when value is non-empty
        # so the template doesn't overwrite it.
        self._location_edit.setText(value)
        self._location_dirty = True if value else self._location_dirty
        self._refresh_add_button()

    def add_button_enabled(self) -> bool:
        return self._buttons.button(QDialogButtonBox.Ok).isEnabled()

    def branch_disabled(self, name: str) -> bool:
        idx = self._branch_combo.findText(name)
        if idx < 0:
            return False
        return not self._branch_combo.model().item(idx).isEnabled()

    def branch_tooltip(self, name: str) -> str | None:
        idx = self._branch_combo.findText(name)
        if idx < 0:
            return None
        return self._branch_combo.model().item(idx).toolTip() or None

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_create_new_toggled(self, on: bool) -> None:
        self._mode_stack.setCurrentIndex(1 if on else 0)
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_branch_changed(self, _text: str) -> None:
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_new_name_changed(self, _text: str) -> None:
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_location_edited(self, text: str) -> None:
        self._location_dirty = True
        self._refresh_add_button()

    def _on_browse(self) -> None:
        d = QFileDialog(self, "Choose worktree location")
        d.setFileMode(QFileDialog.Directory)
        d.setOption(QFileDialog.ShowDirsOnly, True)
        if d.exec() == QFileDialog.Accepted:
            files = d.selectedFiles()
            if files:
                self._location_edit.setText(files[0])
                self._location_dirty = True
                self._refresh_add_button()

    def _current_branch(self) -> str:
        if self.is_create_new():
            return self.new_branch_name()
        return self._branch_combo.currentText().strip()

    def _refresh_default_location(self) -> None:
        if self._location_dirty:
            return
        branch = self._current_branch()
        self._location_edit.setText(_default_location(self._repo_path, branch))

    def _refresh_add_button(self) -> None:
        branch = self._current_branch()
        loc = self.location()
        valid = bool(branch) and bool(loc)
        if not self.is_create_new() and self.branch_disabled(branch):
            valid = False
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(valid)

    def submit(self) -> None:
        payload = {
            "branch": self._current_branch(),
            "create_new": self.is_create_new(),
            "base_ref": self.base_ref() if self.is_create_new() else None,
            "location": self.location(),
            "switch_after": self._switch_after_cb.isChecked(),
        }
        self.add_requested.emit(payload)
        self.accept()
