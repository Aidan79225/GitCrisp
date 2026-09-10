from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from git_gui.domain.entities import RemoteBranchDeleteResult

_MAX_LISTED_IN_CONFIRM = 15


class _DeleteSignals(QObject):
    finished = Signal(list)  # list[RemoteBranchDeleteResult]
    failed = Signal(str)


class RemoteBranchesDialog(QDialog):
    def __init__(self, queries, commands, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remote Branches")
        self.resize(560, 480)
        self._queries = queries
        self._commands = commands
        self._defaults: set[str] = set()
        self._signals: _DeleteSignals | None = None
        self._busy: bool = False

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter…")
        self._filter.textChanged.connect(self._apply_filter)

        self._table = QTableWidget(0, 1)
        self._table.setHorizontalHeaderLabels(["Remote branch"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.itemChanged.connect(self._on_item_changed)

        self._select_all_btn = QPushButton("Select All")
        self._clear_btn = QPushButton("Clear")
        self._delete_btn = QPushButton("Delete Selected (0)")
        self._close_btn = QPushButton("Close")
        self._select_all_btn.clicked.connect(self._select_all_visible)
        self._clear_btn.clicked.connect(self._clear_all)
        self._delete_btn.clicked.connect(self._on_delete)
        self._close_btn.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self._filter, 1)
        top.addWidget(self._select_all_btn)
        top.addWidget(self._clear_btn)

        bottom = QHBoxLayout()
        bottom.addWidget(self._delete_btn)
        bottom.addStretch(1)
        bottom.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table)
        layout.addLayout(bottom)

        self._refresh()

    def _refresh(self) -> None:
        try:
            names = [b.name for b in self._queries.get_branches.execute() if b.is_remote]
        except Exception as e:
            QMessageBox.warning(self, "Load remote branches failed", str(e))
            names = []
        names = [n for n in names if not n.endswith("/HEAD")]
        try:
            self._defaults = set(self._queries.remote_default_branches.execute().values())
        except Exception:
            self._defaults = set()

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for name in sorted(names):
            row = self._table.rowCount()
            self._table.insertRow(row)
            item = QTableWidgetItem(name)
            item.setData(Qt.UserRole, name)
            if name in self._defaults:
                item.setText(f"{name}  (default)")
                item.setFlags(Qt.ItemIsEnabled)
                item.setToolTip("Default branch — cannot be batch-deleted")
            else:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
            self._table.setItem(row, 0, item)
        self._table.blockSignals(False)
        self._apply_filter(self._filter.text())
        self._update_delete_button()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).data(Qt.UserRole)
            self._table.setRowHidden(row, needle not in name.lower())

    def _on_item_changed(self, _item) -> None:
        self._update_delete_button()

    def _checkable_items(self, *, visible_only: bool):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if visible_only and self._table.isRowHidden(row):
                continue
            yield item

    def _collect_selected(self) -> list[str]:
        return [
            item.data(Qt.UserRole)
            for item in self._checkable_items(visible_only=False)
            if item.checkState() == Qt.Checked
        ]

    def _select_all_visible(self) -> None:
        self._table.blockSignals(True)
        for item in self._checkable_items(visible_only=True):
            item.setCheckState(Qt.Checked)
        self._table.blockSignals(False)
        self._update_delete_button()

    def _clear_all(self) -> None:
        self._table.blockSignals(True)
        for item in self._checkable_items(visible_only=False):
            item.setCheckState(Qt.Unchecked)
        self._table.blockSignals(False)
        self._update_delete_button()

    def _update_delete_button(self) -> None:
        n = len(self._collect_selected())
        self._delete_btn.setText(f"Delete Selected ({n})")
        self._delete_btn.setEnabled(n > 0)

    @staticmethod
    def _grouped_by_remote(names: list[str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for full in names:
            remote, branch = full.split("/", 1)
            grouped.setdefault(remote, []).append(branch)
        return grouped

    def _perform_deletions(self, grouped: dict[str, list[str]]) -> list[RemoteBranchDeleteResult]:
        results: list[RemoteBranchDeleteResult] = []
        for remote, branches in grouped.items():
            results.extend(self._commands.delete_remote_branches.execute(remote, branches))
        return results

    def _on_delete(self) -> None:
        selected = self._collect_selected()
        if not selected:
            return
        shown = "\n".join(selected[:_MAX_LISTED_IN_CONFIRM])
        if len(selected) > _MAX_LISTED_IN_CONFIRM:
            shown += f"\n… (+{len(selected) - _MAX_LISTED_IN_CONFIRM} more)"
        if (
            QMessageBox.question(
                self,
                "Delete remote branches",
                f"Delete {len(selected)} remote branch(es)? This cannot be undone.\n\n{shown}",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            != QMessageBox.Yes
        ):
            return

        grouped = self._grouped_by_remote(selected)
        self._set_busy(True)
        signals = _DeleteSignals(self)
        signals.finished.connect(self._on_delete_finished)
        signals.failed.connect(self._on_delete_failed)
        self._signals = signals  # prevent GC

        def _worker():
            try:
                results = self._perform_deletions(grouped)
                signals.finished.emit(results)
            except Exception as e:
                signals.failed.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def reject(self) -> None:
        if self._busy:
            return
        super().reject()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for btn in (self._delete_btn, self._select_all_btn, self._clear_btn, self._close_btn):
            btn.setEnabled(not busy)

    def _on_delete_finished(self, results: list) -> None:
        self._set_busy(False)
        ok = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        msg = f"{len(ok)} deleted"
        if failed:
            detail = "\n".join(f"  {r.branch} — {r.message}" for r in failed)
            msg += f", {len(failed)} failed:\n{detail}"
        self._refresh()
        QMessageBox.information(self, "Delete remote branches", msg)

    def _on_delete_failed(self, message: str) -> None:
        self._set_busy(False)
        self._refresh()
        QMessageBox.warning(self, "Delete remote branches failed", message)
