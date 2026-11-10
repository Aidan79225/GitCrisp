"""Run a modal dialog a menu action opened, and delete it afterwards."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog


def run_and_discard(dialog: QDialog) -> None:
    """Run `dialog` modally, then delete it.

    PySide's `QDialog.exec()` hands a window-parented dialog back to Python, so
    a dialog nothing else references is freed when the caller lets go of it. A
    closure that captures the dialog and is connected to one of its own widgets
    defeats that, as the Theme dialog's slots do: the dialog then stays a child
    of the window until the window closes, holding whatever it was given.

    Run every dialog a menu opens through here, so that a closure added to one
    later cannot keep it, and whatever it was given, alive under the window.
    The exception is a dialog that sets WA_DeleteOnClose: `exec()` deletes it on
    return, and `deleteLater()` on the deleted dialog raises RuntimeError.
    """
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
