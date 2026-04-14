from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QRadioButton,
    QVBoxLayout, QWidget,
)

from git_gui.domain.entities import FileStatus, ResetMode


class ResetDialog(QDialog):
    """Confirm a `git reset` operation: mode radios + dirty-file preview for HARD."""

    def __init__(
        self,
        branch_name: str,
        short_sha: str,
        commit_subject: str,
        default_mode: ResetMode,
        dirty_files: list[FileStatus],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reset Branch")
        self._dirty_files = dirty_files

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Reset <b>{branch_name}</b> to <code>{short_sha}</code> "
            f"&quot;{commit_subject}&quot;"
        )
        header.setTextFormat(header.textFormat().RichText)
        layout.addWidget(header)

        self._radio_soft = QRadioButton("Soft — keep index and working tree")
        self._radio_mixed = QRadioButton("Mixed — keep working tree, reset index")
        self._radio_hard = QRadioButton("Hard — discard all uncommitted changes")
        layout.addWidget(self._radio_soft)
        layout.addWidget(self._radio_mixed)
        layout.addWidget(self._radio_hard)

        {
            ResetMode.SOFT: self._radio_soft,
            ResetMode.MIXED: self._radio_mixed,
            ResetMode.HARD: self._radio_hard,
        }[default_mode].setChecked(True)

        self._dirty_label = QLabel("⚠ The following uncommitted changes will be lost:")
        self._dirty_list = QPlainTextEdit()
        self._dirty_list.setReadOnly(True)
        self._populate_dirty_list()
        layout.addWidget(self._dirty_label)
        layout.addWidget(self._dirty_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Reset")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for radio in (self._radio_soft, self._radio_mixed, self._radio_hard):
            radio.toggled.connect(self._update_dirty_list_visibility)
        self._update_dirty_list_visibility()

    def _populate_dirty_list(self) -> None:
        if not self._dirty_files:
            self._dirty_list.setPlainText("Working tree is clean.")
            return
        lines = []
        for f in self._dirty_files:
            lines.append(f"{f.status}  {f.path}")
        self._dirty_list.setPlainText("\n".join(lines))

    def _update_dirty_list_visibility(self) -> None:
        show = self._radio_hard.isChecked()
        self._dirty_label.setVisible(show)
        self._dirty_list.setVisible(show)

    def result_mode(self) -> ResetMode:
        if self._radio_soft.isChecked():
            return ResetMode.SOFT
        if self._radio_hard.isChecked():
            return ResetMode.HARD
        return ResetMode.MIXED
