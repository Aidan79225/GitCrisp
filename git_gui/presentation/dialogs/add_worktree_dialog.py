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
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from git_gui.presentation.theme import get_theme_manager


def _sanitize_branch(branch: str) -> str:
    """Replace path-unfriendly chars in a branch name for the default path."""
    return branch.replace("/", "-")


def _default_location(repo_path: str, branch: str) -> str:
    """Compute `{repo_parent}/{repo_name}-{sanitized_branch}`."""
    p = Path(repo_path)
    parent = p.parent
    name = p.name or "worktree"
    return str(parent / f"{name}-{_sanitize_branch(branch or 'new')}")


def _location_problem(location: str) -> str | None:
    """Why a worktree cannot be created at `location`, or None when it can."""
    if not location:
        return None
    path = Path(location)
    if not path.is_absolute():
        # git would resolve it against the app's working directory.
        return "Location must be an absolute path."
    try:
        if path.exists() and not _is_empty_folder(path):
            # git worktree add accepts an empty folder, the only kind Browse… returns.
            return "This location already exists and is not an empty folder."
    except OSError:
        # exists() re-raises EACCES, e.g. under a folder the user cannot search.
        return "This location cannot be accessed."
    return None


def _is_empty_folder(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())


def _same_location(a: str, b: str) -> bool:
    return Path(a).resolve() == Path(b).resolve()


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
        self._location_chosen_by_user = False

        self._branch_combo = self._build_branch_combo(branches)
        self._create_new_cb = QCheckBox("Create new branch")
        self._mode_stack = self._build_mode_stack(branches)
        self._in_use_notice = self._build_in_use_notice()
        location_row = self._build_location_row()
        self._switch_after_cb = QCheckBox("Switch to new worktree after creating")
        self._switch_after_cb.setChecked(True)
        self._buttons = self._build_buttons()
        self._lay_out(location_row)
        self._connect_signals()
        self._preselect(preselect_branch, default_create_new)

    def _build_branch_combo(self, branches: list[str]) -> QComboBox:
        combo = QComboBox()
        for b in branches:
            combo.addItem(b)
            if b in self._branches_in_use:
                item = combo.model().item(combo.count() - 1)
                item.setEnabled(False)
                item.setToolTip(f"Already checked out at {self._branches_in_use[b]}")
        return combo

    def _build_mode_stack(self, branches: list[str]) -> QStackedWidget:
        """Existing-branch combo on page 0, the new-branch form on page 1."""
        existing = QWidget()
        existing_layout = QHBoxLayout(existing)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        existing_layout.addWidget(self._branch_combo)
        stack = QStackedWidget()
        stack.addWidget(existing)
        stack.addWidget(self._build_new_branch_form(branches))
        return stack

    def _build_new_branch_form(self, branches: list[str]) -> QWidget:
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("feature/my-branch")
        self._base_ref = QComboBox()
        self._base_ref.addItems(branches)
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("New name:", self._new_name)
        form.addRow("Base ref:", self._base_ref)
        return widget

    def _build_in_use_notice(self) -> QWidget:
        # git allows a branch in one worktree only, so Add cannot proceed
        # for an in-use branch; offer to switch to that worktree instead.
        self._in_use_label = QLabel()
        self._in_use_label.setWordWrap(True)
        self._switch_btn = QPushButton("Switch to That Worktree")
        notice = QWidget()
        row = QHBoxLayout(notice)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._in_use_label, 1)
        row.addWidget(self._switch_btn)
        return notice

    def _build_location_row(self) -> QHBoxLayout:
        self._location_edit = QLineEdit()
        self._browse_btn = QPushButton("Browse…")
        row = QHBoxLayout()
        row.addWidget(self._location_edit, 1)
        row.addWidget(self._browse_btn)
        self._location_error = QLabel()
        self._location_error.setWordWrap(True)
        self._location_error.setStyleSheet(f"color: {get_theme_manager().current.colors.error};")
        self._location_error.setVisible(False)
        return row

    def _build_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        return buttons

    def _lay_out(self, location_row: QHBoxLayout) -> None:
        form = QFormLayout()
        form.addRow("Branch:", self._create_new_cb)
        form.addRow("", self._mode_stack)
        form.addRow("", self._in_use_notice)
        form.addRow("Location:", location_row)
        form.addRow("", self._location_error)
        form.addRow("", self._switch_after_cb)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

    def _connect_signals(self) -> None:
        self._create_new_cb.toggled.connect(self._on_create_new_toggled)
        self._branch_combo.currentTextChanged.connect(self._on_branch_changed)
        self._new_name.textChanged.connect(self._on_branch_changed)
        self._switch_btn.clicked.connect(self._on_switch_to_existing)
        self._location_edit.textEdited.connect(self._on_location_edited)
        self._location_edit.textChanged.connect(self._refresh_location_error)
        self._location_edit.textChanged.connect(self._refresh_add_button)
        self._browse_btn.clicked.connect(self._on_browse)
        self._buttons.accepted.connect(self.submit)
        self._buttons.rejected.connect(self.reject)

    def _preselect(self, branch: str | None, create_new: bool) -> None:
        self._create_new_cb.setChecked(create_new)
        if branch and not create_new:
            self.select_branch(branch)
        self._sync_to_branch()

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
        self._location_edit.setText(value)
        if value:
            self._location_chosen_by_user = True

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
        self._sync_to_branch()

    def _on_branch_changed(self, _text: str) -> None:
        self._sync_to_branch()

    def _sync_to_branch(self) -> None:
        self._refresh_in_use_notice()
        self._refresh_default_location()
        self._refresh_add_button()

    def _on_switch_to_existing(self) -> None:
        path = self._branches_in_use[self._current_branch()]
        self.accept()
        self.switch_to_existing_requested.emit(path)

    def _on_location_edited(self, _text: str) -> None:
        self._location_chosen_by_user = True

    def _on_browse(self) -> None:
        d = QFileDialog(self, "Choose worktree location")
        d.setFileMode(QFileDialog.Directory)
        d.setOption(QFileDialog.ShowDirsOnly, True)
        if d.exec() == QFileDialog.Accepted:
            files = d.selectedFiles()
            if files:
                self.set_location(files[0])

    def _current_branch(self) -> str:
        if self.is_create_new():
            return self.new_branch_name()
        return self._branch_combo.currentText().strip()

    def _in_use_path(self) -> str | None:
        """Where the chosen existing branch is already checked out, if anywhere."""
        if self.is_create_new():
            return None
        return self._branches_in_use.get(self._current_branch())

    def _refresh_in_use_notice(self) -> None:
        path = self._in_use_path()
        in_this_worktree = path is not None and _same_location(path, self._repo_path)
        self._in_use_notice.setVisible(path is not None)
        self._switch_btn.setVisible(not in_this_worktree)
        if in_this_worktree:
            self._in_use_label.setText("Already checked out in this worktree")
        else:
            self._in_use_label.setText(f"Already checked out at {path}" if path else "")

    def _refresh_location_error(self) -> None:
        problem = _location_problem(self.location())
        self._location_error.setText(problem or "")
        self._location_error.setVisible(problem is not None)

    def _refresh_default_location(self) -> None:
        if self._location_chosen_by_user:
            return
        branch = self._current_branch()
        self._location_edit.setText(_default_location(self._repo_path, branch))

    def _refresh_add_button(self) -> None:
        branch = self._current_branch()
        loc = self.location()
        valid = bool(branch) and bool(loc) and _location_problem(loc) is None
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
