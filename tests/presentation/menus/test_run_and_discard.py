"""run_and_discard deletes the dialog it ran, whether or not exec() came back."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog

from git_gui.presentation.menus.run_and_discard import run_and_discard


class _DialogThatCannotRun(QDialog):
    def exec(self) -> int:
        raise RuntimeError("cannot run")


def test_a_dialog_whose_exec_raises_is_still_deleted(qapp):
    dialog = _DialogThatCannotRun()
    deleted: list[bool] = []
    dialog.destroyed.connect(lambda: deleted.append(True))

    with pytest.raises(RuntimeError, match="cannot run"):
        run_and_discard(dialog)
    # What the event loop does at its next turn.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert deleted == [True]
