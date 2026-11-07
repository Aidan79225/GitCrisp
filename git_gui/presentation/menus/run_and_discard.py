"""Run a modal dialog a menu action opened, and delete it afterwards."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog


def run_and_discard(dialog: QDialog) -> None:
    """Run `dialog` modally, then delete it.

    A dialog parented to the window is not freed once the caller lets go of it
    if a closure connected to one of its own widgets captures it: it stays a
    child of the window until the window closes, holding whatever it was given.
    """
    dialog.exec()
    dialog.deleteLater()
