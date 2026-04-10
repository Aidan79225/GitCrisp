from __future__ import annotations
from dataclasses import dataclass
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
    QRadioButton, QVBoxLayout,
)
from git_gui.domain.entities import MergeStrategy


@dataclass
class MergeRequest:
    strategy: MergeStrategy
    message: str | None


class MergeDialog(QDialog):
    """Dialog for choosing merge strategy and editing commit message."""

    def __init__(
        self,
        source_label: str,
        target_label: str,
        can_ff: bool,
        default_message: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Merge {source_label} into {target_label}")
        self.setMinimumWidth(480)
        self._can_ff = can_ff

        layout = QVBoxLayout(self)

        # Analysis label
        if can_ff:
            hint = "This merge can be fast-forwarded"
        else:
            hint = "This merge requires a merge commit"
        self._analysis_label = QLabel(hint)
        self._analysis_label.setStyleSheet("font-style: italic; padding: 4px;")
        layout.addWidget(self._analysis_label)

        # Strategy radios
        self._radio_no_ff = QRadioButton("No fast-forward (--no-ff)")
        self._radio_ff_only = QRadioButton("Fast-forward only (--ff-only)")
        self._radio_allow_ff = QRadioButton("Allow fast-forward")

        self._radio_no_ff.setChecked(True)

        if not can_ff:
            self._radio_ff_only.setEnabled(False)
            self._radio_ff_only.setToolTip("Cannot fast-forward this merge")

        self._radio_no_ff.toggled.connect(self._on_strategy_changed)
        self._radio_ff_only.toggled.connect(self._on_strategy_changed)
        self._radio_allow_ff.toggled.connect(self._on_strategy_changed)

        layout.addWidget(self._radio_no_ff)
        layout.addWidget(self._radio_ff_only)
        layout.addWidget(self._radio_allow_ff)

        # Commit message editor
        self._message_label = QLabel("Commit message:")
        layout.addWidget(self._message_label)

        self._message_edit = QPlainTextEdit()
        self._message_edit.setPlainText(default_message)
        self._message_edit.setMinimumHeight(80)
        layout.addWidget(self._message_edit)

        # Buttons
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Merge")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        # Apply initial state
        self._on_strategy_changed()

    def _will_create_merge_commit(self) -> bool:
        if self._radio_no_ff.isChecked():
            return True
        if self._radio_ff_only.isChecked():
            return False  # ff only → no merge commit
        # allow-ff
        return not self._can_ff

    def _on_strategy_changed(self) -> None:
        will_commit = self._will_create_merge_commit()
        self._message_edit.setEnabled(will_commit)
        self._message_label.setEnabled(will_commit)

        # Safety net: disable Merge button if ff-only but can't ff
        merge_btn = self._buttons.button(QDialogButtonBox.Ok)
        if self._radio_ff_only.isChecked() and not self._can_ff:
            merge_btn.setEnabled(False)
        else:
            merge_btn.setEnabled(True)

    def result_value(self) -> MergeRequest:
        if self._radio_no_ff.isChecked():
            strategy = MergeStrategy.NO_FF
        elif self._radio_ff_only.isChecked():
            strategy = MergeStrategy.FF_ONLY
        else:
            strategy = MergeStrategy.ALLOW_FF

        if self._will_create_merge_commit():
            message = self._message_edit.toPlainText()
        else:
            message = None

        return MergeRequest(strategy=strategy, message=message)
