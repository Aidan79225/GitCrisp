"""Interactive rebase commit list editor dialog."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from git_gui.domain.entities import Commit, RebaseAction, RebaseTodoEntry

_ACTION_COLUMN, _OID_COLUMN, _MESSAGE_COLUMN = range(3)
_HEADERS = ["Action", "OID", "Message"]
_ACTION_COLUMN_WIDTH = 100
_OID_COLUMN_WIDTH = 80

# Read-only, and never a drop target, so a drop always lands between rows.
_CELL_FLAGS = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(_CELL_FLAGS)
    return item


class _RowMoveTable(QTableWidget):
    """A table whose drag-and-drop moves the dragged row as a whole.

    QTableWidget's own InternalMove moves single cells onto the cell under
    the cursor, overwriting it, and leaves cell widgets where they were.
    """

    row_dropped = Signal(int, int)  # source row, destination row

    def dropEvent(self, event: QDropEvent) -> None:
        dragged = self.selectionModel().selectedRows()
        if event.source() is self and not event.isAccepted() and dragged:
            source = dragged[0].row()
            gap = self._drop_gap(event.position().toPoint())
            # An accepted drop tells QTableWidget the move is done, so it
            # neither moves cells itself nor removes the source row afterwards.
            event.accept()
            self.row_dropped.emit(source, gap - 1 if gap > source else gap)
        super().dropEvent(event)

    def _drop_gap(self, pos: QPoint) -> int:
        """The boundary between rows the drop lands on, counted from the top."""
        row = self.rowAt(pos.y())
        if row < 0:
            return self.rowCount()
        middle = self.visualRect(self.model().index(row, 0)).center().y()
        return row if pos.y() < middle else row + 1


class InteractiveRebaseDialog(QDialog):
    """Commit list editor for interactive rebase.

    Shows one row per commit (oldest-first). Each row has an action
    dropdown (pick/squash/fixup/drop), short oid, and first-line message.
    Rows are drag-and-drop reorderable.

    The "Execute" button is disabled when squash or fixup is on the
    first row that is not dropped (nothing to combine with).
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

        self._table = self._build_table(len(commits))
        for row, commit in enumerate(commits):
            self._add_commit_row(row, commit)
        self._buttons = self._build_buttons()
        layout = QVBoxLayout(self)
        layout.addWidget(self._table)
        layout.addWidget(self._buttons)
        self._validate()

    def _build_table(self, row_count: int) -> _RowMoveTable:
        table = _RowMoveTable(row_count, len(_HEADERS))
        table.setHorizontalHeaderLabels(_HEADERS)
        header = table.horizontalHeader()
        header.setSectionResizeMode(_ACTION_COLUMN, QHeaderView.Fixed)
        header.setSectionResizeMode(_OID_COLUMN, QHeaderView.Fixed)
        header.setSectionResizeMode(_MESSAGE_COLUMN, QHeaderView.Stretch)
        table.setColumnWidth(_ACTION_COLUMN, _ACTION_COLUMN_WIDTH)
        table.setColumnWidth(_OID_COLUMN, _OID_COLUMN_WIDTH)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setDragDropMode(QAbstractItemView.InternalMove)
        table.setDragDropOverwriteMode(False)
        table.row_dropped.connect(self.move_row)
        return table

    def _add_commit_row(self, row: int, commit: Commit) -> None:
        combo = QComboBox()
        combo.addItems([action.value for action in RebaseAction])
        combo.setCurrentText(RebaseAction.PICK.value)
        combo.currentTextChanged.connect(self._validate)
        self._table.setCellWidget(row, _ACTION_COLUMN, combo)
        self._table.setItem(row, _ACTION_COLUMN, _cell(""))
        oid_cell = _cell(commit.oid[:7])
        oid_cell.setData(Qt.UserRole, commit.oid)
        self._table.setItem(row, _OID_COLUMN, oid_cell)
        self._table.setItem(row, _MESSAGE_COLUMN, _cell(commit.message.split("\n", 1)[0]))

    def _build_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Execute")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        return buttons

    def move_row(self, source: int, destination: int) -> None:
        """Move the commit at ``source`` to ``destination``, its action with it."""
        if source == destination:
            return
        rows = [self._take_row(row) for row in range(self._table.rowCount())]
        rows.insert(destination, rows.pop(source))
        for row, (action, items) in enumerate(rows):
            self._action_combo(row).setCurrentText(action.value)
            for column, item in enumerate(items):
                self._table.setItem(row, column, item)
        self._table.selectRow(destination)
        self._validate()

    def _take_row(self, row: int) -> tuple[RebaseAction, list[QTableWidgetItem]]:
        action = self._action_at(row)
        items = [self._table.takeItem(row, column) for column in range(self._table.columnCount())]
        return action, items

    def _action_combo(self, row: int) -> QComboBox:
        return self._table.cellWidget(row, _ACTION_COLUMN)

    def _action_at(self, row: int) -> RebaseAction:
        return RebaseAction(self._action_combo(row).currentText())

    def _validate(self) -> None:
        """Disable Execute when squash/fixup is the first action that keeps a commit."""
        execute_btn = self._buttons.button(QDialogButtonBox.Ok)
        if self._table.rowCount() == 0:
            execute_btn.setEnabled(False)
            return
        if self._first_kept_action() in (RebaseAction.SQUASH, RebaseAction.FIXUP):
            execute_btn.setEnabled(False)
            execute_btn.setToolTip(
                "Cannot squash/fixup the first kept commit — no preceding commit to combine with."
            )
        else:
            execute_btn.setEnabled(True)
            execute_btn.setToolTip("")

    def _first_kept_action(self) -> RebaseAction | None:
        """git does not count a dropped commit as one to squash or fix up into."""
        for row in range(self._table.rowCount()):
            action = self._action_at(row)
            if action != RebaseAction.DROP:
                return action
        return None

    def result_entries(self) -> list[RebaseTodoEntry]:
        """Return the todo entries in current row order."""
        return [
            RebaseTodoEntry(
                self._action_at(row), self._table.item(row, _OID_COLUMN).data(Qt.UserRole)
            )
            for row in range(self._table.rowCount())
        ]
