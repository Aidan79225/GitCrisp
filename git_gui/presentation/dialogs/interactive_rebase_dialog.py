"""Interactive rebase commit list editor dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from git_gui.domain.entities import Commit

_ACTIONS = ["pick", "squash", "fixup", "drop"]


class InteractiveRebaseDialog(QDialog):
    """Commit list editor for interactive rebase.

    Shows one row per commit (oldest-first). Each row has an action
    dropdown (pick/squash/fixup/drop), short oid, and first-line message.
    Rows are drag-and-drop reorderable.

    The "Execute" button is disabled when squash or fixup is on the
    first row (nothing to combine with).
    """

    def __init__(
        self,
        commits: list[Commit],
        target_label: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Interactive Rebase onto {target_label}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._commits = list(commits)

        layout = QVBoxLayout(self)

        # Table
        self._table = QTableWidget(len(commits), 3)
        self._table.setHorizontalHeaderLabels(["Action", "OID", "Message"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 80)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)

        # Enable row drag-and-drop reorder
        self._table.setDragDropMode(QAbstractItemView.InternalMove)
        self._table.setDragDropOverwriteMode(False)

        for row, commit in enumerate(commits):
            # Action combo
            combo = QComboBox()
            combo.addItems(_ACTIONS)
            combo.setCurrentText("pick")
            combo.currentTextChanged.connect(self._validate)
            self._table.setCellWidget(row, 0, combo)

            # OID
            oid_item = QTableWidgetItem(commit.oid[:7])
            oid_item.setFlags(oid_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 1, oid_item)

            # Message (first line)
            msg_line = commit.message.split("\n", 1)[0]
            msg_item = QTableWidgetItem(msg_line)
            msg_item.setFlags(msg_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 2, msg_item)

        layout.addWidget(self._table)

        # Buttons
        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Execute")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._validate()

    def _validate(self) -> None:
        """Disable Execute when squash/fixup is on the first row."""
        execute_btn = self._buttons.button(QDialogButtonBox.Ok)
        if self._table.rowCount() == 0:
            execute_btn.setEnabled(False)
            return
        first_combo = self._table.cellWidget(0, 0)
        if first_combo and first_combo.currentText() in ("squash", "fixup"):
            execute_btn.setEnabled(False)
            execute_btn.setToolTip(
                "Cannot squash/fixup the first commit — no preceding commit to combine with."
            )
        else:
            execute_btn.setEnabled(True)
            execute_btn.setToolTip("")

    def result_entries(self) -> list[tuple[str, str]]:
        """Return (action, full_oid) tuples in current row order."""
        entries: list[tuple[str, str]] = []
        for row in range(self._table.rowCount()):
            combo = self._table.cellWidget(row, 0)
            action = combo.currentText() if combo else "pick"
            # Find the original commit by matching the short oid
            short_oid = self._table.item(row, 1).text()
            full_oid = short_oid  # fallback
            for c in self._commits:
                if c.oid[:7] == short_oid:
                    full_oid = c.oid
                    break
            entries.append((action, full_oid))
        return entries
