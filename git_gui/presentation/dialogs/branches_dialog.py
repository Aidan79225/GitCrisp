from __future__ import annotations
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)


class _CreateDialog(QDialog):
    def __init__(self, parent=None, default_start: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Branch")
        self._name = QLineEdit()
        self._start = QLineEdit(default_start)
        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("Start point:", self._start)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._start.text().strip()


class _RenameDialog(QDialog):
    def __init__(self, parent=None, current: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Rename Branch")
        self._name = QLineEdit(current)
        form = QFormLayout()
        form.addRow("New name:", self._name)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self._name.text().strip()


class _UpstreamDialog(QDialog):
    def __init__(self, parent=None, remote_branches: list[str] | None = None,
                 current: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Upstream")
        self._combo = QComboBox()
        self._combo.addItem("(none)")
        for rb in (remote_branches or []):
            self._combo.addItem(rb)
        if current:
            idx = self._combo.findText(current)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        form = QFormLayout()
        form.addRow("Upstream:", self._combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def value(self) -> str | None:
        text = self._combo.currentText()
        return None if text == "(none)" else text


class BranchesDialog(QDialog):
    def __init__(self, queries, commands, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Branches")
        self.resize(720, 420)
        self._queries = queries
        self._commands = commands

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Upstream", "Last commit"])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._checkout_btn = QPushButton("Checkout")
        self._create_btn = QPushButton("Create...")
        self._rename_btn = QPushButton("Rename...")
        self._upstream_btn = QPushButton("Set Upstream...")
        self._delete_btn = QPushButton("Delete")
        self._close_btn = QPushButton("Close")

        self._checkout_btn.clicked.connect(self._on_checkout)
        self._create_btn.clicked.connect(self._on_create)
        self._rename_btn.clicked.connect(self._on_rename)
        self._upstream_btn.clicked.connect(self._on_set_upstream)
        self._delete_btn.clicked.connect(self._on_delete)
        self._close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._checkout_btn)
        btn_row.addWidget(self._create_btn)
        btn_row.addWidget(self._rename_btn)
        btn_row.addWidget(self._upstream_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        try:
            infos = self._queries.list_local_branches_with_upstream.execute()
        except Exception as e:
            QMessageBox.warning(self, "Load branches failed", str(e))
            infos = []
        self._table.setRowCount(0)
        for info in infos:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(info.name))
            self._table.setItem(
                row, 1,
                QTableWidgetItem(info.upstream if info.upstream else "(none)"),
            )
            commit_text = f"{info.last_commit_sha}  {info.last_commit_message}"
            self._table.setItem(row, 2, QTableWidgetItem(commit_text))

    def _selected_name(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _selected_upstream(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        text = self._table.item(rows[0].row(), 1).text()
        return None if text == "(none)" else text

    def _remote_branch_names(self) -> list[str]:
        try:
            return [b.name for b in self._queries.get_branches.execute() if b.is_remote]
        except Exception:
            return []

    def _on_checkout(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            self._commands.checkout.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Checkout failed", str(e))
            return
        self.accept()

    def _on_create(self) -> None:
        default_start = self._selected_name() or ""
        d = _CreateDialog(self, default_start=default_start)
        if d.exec() != QDialog.Accepted:
            return
        name, start = d.values()
        if not name or not start:
            QMessageBox.warning(self, "Invalid input", "Name and start point are required.")
            return
        try:
            self._commands.create_branch.execute(name, start)
            self._commands.checkout.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Create branch failed", str(e))
        self._refresh()

    def _on_rename(self) -> None:
        old = self._selected_name()
        if not old:
            return
        d = _RenameDialog(self, current=old)
        if d.exec() != QDialog.Accepted:
            return
        new = d.value()
        if not new or new == old:
            return
        try:
            self._commands.rename_branch.execute(old, new)
        except Exception as e:
            QMessageBox.warning(self, "Rename branch failed", str(e))
        self._refresh()

    def _on_set_upstream(self) -> None:
        name = self._selected_name()
        if not name:
            return
        d = _UpstreamDialog(
            self,
            remote_branches=self._remote_branch_names(),
            current=self._selected_upstream(),
        )
        if d.exec() != QDialog.Accepted:
            return
        new_upstream = d.value()
        try:
            if new_upstream is None:
                self._commands.unset_branch_upstream.execute(name)
            else:
                self._commands.set_branch_upstream.execute(name, new_upstream)
        except Exception as e:
            QMessageBox.warning(self, "Set upstream failed", str(e))
        self._refresh()

    def _on_delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(self, "Delete branch", f"Delete branch '{name}'?") != QMessageBox.Yes:
            return
        try:
            self._commands.delete_branch.execute(name)
        except Exception as e:
            QMessageBox.warning(self, "Delete branch failed", str(e))
        self._refresh()
