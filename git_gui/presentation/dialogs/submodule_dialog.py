from __future__ import annotations
import os
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class _SubmoduleAddDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Submodule")
        self._path = QLineEdit()
        self._url = QLineEdit()
        form = QFormLayout()
        form.addRow("Path:", self._path)
        form.addRow("URL:", self._url)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._path.text().strip(), self._url.text().strip()


class _SubmoduleUrlDialog(QDialog):
    def __init__(self, parent=None, url: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Submodule URL")
        self._url = QLineEdit(url)
        form = QFormLayout()
        form.addRow("URL:", self._url)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self._url.text().strip()


class SubmoduleDialog(QDialog):
    submoduleOpenRequested = Signal(str)

    def __init__(self, queries, commands, repo_workdir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Submodules")
        self.resize(640, 380)
        self._queries = queries
        self._commands = commands
        self._workdir = repo_workdir

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Path", "URL", "HEAD"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._add_btn = QPushButton("Add...")
        self._edit_btn = QPushButton("Edit URL...")
        self._remove_btn = QPushButton("Remove")
        self._open_btn = QPushButton("Open")
        self._close_btn = QPushButton("Close")

        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn.clicked.connect(self._on_edit)
        self._remove_btn.clicked.connect(self._on_remove)
        self._open_btn.clicked.connect(self._on_open)
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        try:
            subs = self._queries.list_submodules.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load submodules failed", str(e))
            subs = []
        self._table.setRowCount(0)
        for s in subs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(s.path))
            self._table.setItem(row, 1, QTableWidgetItem(s.url))
            self._table.setItem(row, 2, QTableWidgetItem((s.head_sha or "")[:10]))

    def _selected_path(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _selected_url(self) -> str:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return ""
        return self._table.item(rows[0].row(), 1).text()

    def _on_add(self) -> None:
        d = _SubmoduleAddDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        path, url = d.values()
        if not path or not url:
            QMessageBox.warning(self, "Invalid input", "Path and URL are required.")
            return
        try:
            self._commands.add_submodule.execute(path, url)
        except Exception as e:
            QMessageBox.warning(self, "Add submodule failed", str(e))
        self._refresh()

    def _on_edit(self) -> None:
        path = self._selected_path()
        if not path:
            return
        d = _SubmoduleUrlDialog(self, url=self._selected_url())
        if d.exec() != QDialog.Accepted:
            return
        url = d.value()
        if not url:
            QMessageBox.warning(self, "Invalid input", "URL is required.")
            return
        try:
            self._commands.set_submodule_url.execute(path, url)
        except Exception as e:
            QMessageBox.warning(self, "Edit submodule failed", str(e))
        self._refresh()

    def _on_remove(self) -> None:
        path = self._selected_path()
        if not path:
            return
        if QMessageBox.question(self, "Remove submodule", f"Remove submodule '{path}'?") != QMessageBox.Yes:
            return
        try:
            self._commands.remove_submodule.execute(path)
        except Exception as e:
            QMessageBox.warning(self, "Remove submodule failed", str(e))
        self._refresh()

    def _on_open(self) -> None:
        path = self._selected_path()
        if not path:
            return
        abs_path = os.path.abspath(os.path.join(self._workdir, path))
        self.submoduleOpenRequested.emit(abs_path)
        self.accept()
