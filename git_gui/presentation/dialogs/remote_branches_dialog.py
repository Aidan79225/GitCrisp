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

from git_gui.domain.entities import RemoteBranchDeleteResult, split_remote_branch
from git_gui.presentation.widgets.check_indicator import CheckIndicatorDelegate

_MAX_LISTED = 15

# The dialog loads the remotes when it opens and again after a delete, which
# needs them: while they are unknown, reopening it is the only way back.
_REMOTES_UNKNOWN = (
    "Deleting is off: the remotes did not load. "
    "Fix the remote configuration (git remote -v), then reopen this dialog."
)


def _capped_listing(lines: list[str]) -> str:
    shown = "\n".join(lines[:_MAX_LISTED])
    if len(lines) > _MAX_LISTED:
        shown += f"\n… (+{len(lines) - _MAX_LISTED} more)"
    return shown


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
        self._remotes: list[str] = []
        self._remotes_known = False
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
        self._table.setItemDelegate(CheckIndicatorDelegate(self._table))
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
        names = self._load_branch_names()
        self._remotes_known = self._load_remotes()
        self._populate(names)
        self._apply_filter(self._filter.text())
        self._update_delete_button()

    def _load_branch_names(self) -> list[str]:
        try:
            branches = self._queries.get_branches.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load remote branches failed", str(e))
            return []
        return [b.name for b in branches if b.is_remote and not b.name.endswith("/HEAD")]

    def _load_remotes(self) -> bool:
        """Load the default branches and remote names a delete relies on.

        Without the defaults a default branch could be ticked, and without the
        remote names a remote named with a '/' would get the wrong push, so
        when either fails to load, Delete stays off.
        """
        try:
            defaults = set(self._queries.remote_default_branches.execute().values())
            remotes = [r.name for r in self._queries.list_remotes.execute()]
        except Exception as e:
            QMessageBox.warning(self, "Load remotes failed", f"{_REMOTES_UNKNOWN}\n\n{e}")
            return False
        self._defaults, self._remotes = defaults, remotes
        return True

    def _populate(self, names: list[str]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for name in sorted(names):
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, self._row_item(name))
        self._table.blockSignals(False)

    def _row_item(self, name: str) -> QTableWidgetItem:
        item = QTableWidgetItem(name)
        item.setData(Qt.UserRole, name)
        if name in self._defaults:
            item.setText(f"{name}  (default)")
            item.setFlags(Qt.ItemIsEnabled)
            item.setToolTip("Default branch — cannot be batch-deleted")
        else:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        return item

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
        self._delete_btn.setEnabled(n > 0 and self._remotes_known and not self._busy)
        self._delete_btn.setToolTip("" if self._remotes_known else _REMOTES_UNKNOWN)

    @staticmethod
    def _grouped_by_remote(names: list[str], remotes: list[str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for name in names:
            remote, branch = split_remote_branch(name, remotes)
            grouped.setdefault(remote, []).append(branch)
        return grouped

    def _perform_deletions(self, grouped: dict[str, list[str]]) -> list[RemoteBranchDeleteResult]:
        results: list[RemoteBranchDeleteResult] = []
        for remote, branches in grouped.items():
            results.extend(self._commands.delete_remote_branches.execute(remote, branches))
        return results

    def _on_delete(self) -> None:
        selected = self._collect_selected()
        if selected and self._confirm_delete(selected):
            self._start_delete(self._grouped_by_remote(selected, self._remotes))

    def _confirm_delete(self, selected: list[str]) -> bool:
        answer = QMessageBox.question(
            self,
            "Delete remote branches",
            f"Delete {len(selected)} remote branch(es)? This cannot be undone.\n\n"
            f"{_capped_listing(selected)}",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _start_delete(self, grouped: dict[str, list[str]]) -> None:
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
        for widget in (
            self._table,
            self._filter,
            self._delete_btn,
            self._select_all_btn,
            self._clear_btn,
            self._close_btn,
        ):
            widget.setEnabled(not busy)

    def _on_delete_finished(self, results: list) -> None:
        self._set_busy(False)
        failed = [r for r in results if not r.ok]
        summary = f"{len(results) - len(failed)} deleted"
        self._refresh()
        if failed:
            self._show_failures(summary, failed)
        else:
            QMessageBox.information(self, "Delete remote branches", summary)

    def _show_failures(self, summary: str, failed: list[RemoteBranchDeleteResult]) -> None:
        # git's stderr runs to several lines per branch, and a QMessageBox does
        # not scroll: list each failure by its first line and keep the rest in
        # the details.
        first_lines = [f"  {r.branch} — {r.message.partition('\n')[0]}" for r in failed]
        box = QMessageBox(
            QMessageBox.Information,
            "Delete remote branches",
            f"{summary}, {len(failed)} failed:\n{_capped_listing(first_lines)}",
            QMessageBox.Ok,
            self,
        )
        box.setDetailedText("\n\n".join(f"{r.branch} — {r.message}" for r in failed))
        box.exec()

    def _on_delete_failed(self, message: str) -> None:
        self._set_busy(False)
        self._refresh()
        QMessageBox.warning(self, "Delete remote branches failed", message)
