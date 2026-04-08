from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class _RemoteEditDialog(QDialog):
    def __init__(self, parent=None, name: str = "", url: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Remote" if name else "Add Remote")
        self._name = QLineEdit(name)
        self._url = QLineEdit(url)
        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("URL:", self._url)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._url.text().strip()


class RemoteDialog(QDialog):
    def __init__(self, queries, commands, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remotes")
        self.resize(560, 360)
        self._queries = queries
        self._commands = commands

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Fetch URL", "Push URL"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._add_btn = QPushButton("Add...")
        self._edit_btn = QPushButton("Edit...")
        self._remove_btn = QPushButton("Remove")
        self._close_btn = QPushButton("Close")

        self._add_btn.clicked.connect(self._on_add)
        self._edit_btn.clicked.connect(self._on_edit)
        self._remove_btn.clicked.connect(self._on_remove)
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        try:
            remotes = self._queries.list_remotes.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load remotes failed", str(e))
            remotes = []
        self._table.setRowCount(0)
        for r in remotes:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(r.name))
            self._table.setItem(row, 1, QTableWidgetItem(r.fetch_url))
            self._table.setItem(row, 2, QTableWidgetItem(r.push_url))

    def _selected_name(self) -> str | None:
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
        d = _RemoteEditDialog(self)
        if d.exec() != QDialog.Accepted:
            return
        name, url = d.values()
        if not name or not url:
            QMessageBox.warning(self, "Invalid input", "Name and URL are required.")
            return
        try:
            self._commands.add_remote.execute(name, url)
        except Exception as e:
            QMessageBox.warning(self, "Add remote failed", str(e))
        self._refresh()

    def _on_edit(self) -> None:
        name = self._selected_name()
        if not name:
            return
        url = self._selected_url()
        d = _RemoteEditDialog(self, name=name, url=url)
        if d.exec() != QDialog.Accepted:
            return
        new_name, new_url = d.values()
        if not new_name or not new_url:
            QMessageBox.warning(self, "Invalid input", "Name and URL are required.")
            return
        try:
            if new_name != name:
                self._commands.rename_remote.execute(name, new_name)
            if new_url != url:
                self._commands.set_remote_url.execute(new_name, new_url)
        except Exception as e:
            QMessageBox.warning(self, "Edit remote failed", str(e))
        self._refresh()

    def _on_remove(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(self, "Remove remote", f"Remove remote '{name}'?") != QMessageBox.Yes:
            return
        try:
            self._commands.remove_remote.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Remove remote failed", str(e))
        self._refresh()
