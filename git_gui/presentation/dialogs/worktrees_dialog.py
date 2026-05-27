from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from git_gui.domain.entities import Worktree


class WorktreesDialog(QDialog):
    open_requested = Signal(str)          # absolute path
    remove_requested = Signal(str)
    lock_requested = Signal(str, str)     # path, reason (may be empty)
    unlock_requested = Signal(str)
    add_requested = Signal()

    def __init__(self, worktrees: list[Worktree] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Worktrees")
        self.resize(720, 420)
        self._worktrees: list[Worktree] = list(worktrees or [])

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Branch", "Path", "Locked", "Status"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._open_btn = QPushButton("Open")
        self._lock_btn = QPushButton("Lock…")
        self._unlock_btn = QPushButton("Unlock")
        self._remove_btn = QPushButton("Remove…")
        self._add_btn = QPushButton("Add Worktree…")
        self._close_btn = QPushButton("Close")

        self._open_btn.clicked.connect(self._on_open)
        self._lock_btn.clicked.connect(lambda: self._on_lock())
        self._unlock_btn.clicked.connect(self._on_unlock)
        self._remove_btn.clicked.connect(self._on_remove)
        self._add_btn.clicked.connect(lambda: self.add_requested.emit())
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._lock_btn)
        btn_row.addWidget(self._unlock_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._populate()

    # ── Public test/inspection API ───────────────────────────────────────

    def row_count(self) -> int:
        return self._table.rowCount()

    def row_branch(self, row: int) -> str:
        return self._table.item(row, 0).text()

    def row_path(self, row: int) -> str:
        return self._table.item(row, 1).text()

    def row_locked_text(self, row: int) -> str:
        return self._table.item(row, 2).text()

    def select_row(self, row: int) -> None:
        self._table.selectRow(row)

    def click_open(self) -> None:
        self._on_open()

    def click_remove(self) -> None:
        self._on_remove()

    def click_lock(self, reason_for_test: str | None = None) -> None:
        # Test seam: bypass QInputDialog by passing reason directly.
        self._on_lock(reason_override=reason_for_test)

    def click_unlock(self) -> None:
        self._on_unlock()

    def click_add(self) -> None:
        self.add_requested.emit()

    # ── Internals ────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._table.setRowCount(0)
        for wt in self._worktrees:
            row = self._table.rowCount()
            self._table.insertRow(row)
            branch = wt.branch or "(detached)"
            self._table.setItem(row, 0, QTableWidgetItem(branch))
            self._table.setItem(row, 1, QTableWidgetItem(str(wt.path)))
            locked_text = ""
            if wt.is_locked:
                locked_text = wt.lock_reason or "Locked"
            self._table.setItem(row, 2, QTableWidgetItem(locked_text))
            self._table.setItem(row, 3, QTableWidgetItem("main" if wt.is_main else ""))

    def _selected_path(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 1).text()

    def _on_open(self) -> None:
        path = self._selected_path()
        if path:
            self.open_requested.emit(path)

    def _on_remove(self) -> None:
        path = self._selected_path()
        if path:
            self.remove_requested.emit(path)

    def _on_lock(self, reason_override: str | None = None) -> None:
        path = self._selected_path()
        if not path:
            return
        if reason_override is None:
            text, ok = QInputDialog.getText(self, "Lock Worktree", "Reason (optional):")
            if not ok:
                return
            reason = text.strip()
        else:
            reason = reason_override
        self.lock_requested.emit(path, reason)

    def _on_unlock(self) -> None:
        path = self._selected_path()
        if path:
            self.unlock_requested.emit(path)
