from __future__ import annotations

import os
import re
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from git_gui.infrastructure.git_clone import CloneCancelled, CloneProgress, clone_repo
from git_gui.presentation.theme import connect_widget, get_theme_manager

_REPO_NAME_RE = re.compile(r"[/:\\]([^/:\\]+?)(?:\.git)?[/\\]?$")


def _parse_repo_name(url: str) -> str:
    """Extract repo name from a git URL."""
    m = _REPO_NAME_RE.search(url.strip())
    return m.group(1) if m else ""


def _stays_inside(folder: str, name: str) -> bool:
    """Whether a clone named ``name`` under ``folder`` is written inside ``folder``.

    Joined the way git sees it, so ``..``, another drive, a rooted name and an
    absolute path all count. Text only: no disk access on the GUI thread.
    """
    # abspath, not normpath: Path.is_relative_to takes "../x" for inside ".".
    root = Path(os.path.abspath(folder))
    return Path(os.path.abspath(root / name)).is_relative_to(root)


def _input_problem(url: str, folder: str, name: str) -> str | None:
    """Why a clone of ``url`` into ``folder``/``name`` cannot start, or None when it can.

    Text only: no disk access on the GUI thread.
    """
    if not url:
        return "URL is required."
    if not folder:
        return "Location is required."
    if not name:
        return "Folder name is required."
    if not _stays_inside(folder, name):
        return "Folder name must stay inside the location."
    return None


class _CloneSignals(QObject):
    progress = Signal(str, int)  # phase, percent
    finished = Signal(str)  # dest path
    failed = Signal(str)  # error message
    cleanup_failed = Signal(str, str)  # dest path, reason
    ended = Signal()  # the worker is done, whichever way the clone went


class CloneDialog(QDialog):
    clone_completed = Signal(str)  # dest path
    # A cancelled clone left files in dest: the dialog has closed, so whoever
    # opened it has to tell the user.
    cleanup_failed = Signal(str, str)  # dest path, reason

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clone Repository")
        self.setMinimumWidth(500)
        self._cloning = False
        self._cancel_requested = threading.Event()
        self._workers_running = 0
        self._release_requested = False

        # URL
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://github.com/user/repo.git  or  git@github.com:user/repo.git"
        )
        self._url_edit.textChanged.connect(self._on_url_changed)

        # Folder location
        self._folder_edit = QLineEdit(str(Path.home()))
        self._folder_browse = QPushButton("Browse...")
        self._folder_browse.clicked.connect(self._on_browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(self._folder_browse)

        # Folder name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("(auto-detected from URL)")

        # Form
        form = QFormLayout()
        form.addRow("URL:", self._url_edit)
        form.addRow("Location:", folder_row)
        form.addRow("Folder name:", self._name_edit)

        # Progress
        self._progress_label = QLabel("")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(True)
        self._progress_label.setVisible(False)
        self._progress_bar.setVisible(False)

        # Error label
        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)

        # Buttons
        self._clone_btn = QPushButton("Clone")
        self._clone_btn.setDefault(True)
        self._clone_btn.clicked.connect(self._on_clone)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._clone_btn)
        btn_row.addWidget(self._cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._progress_label)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._error_label)
        layout.addLayout(btn_row)

        self._rebuild_styles()
        connect_widget(self, rebuild=self._rebuild_styles)

    def _rebuild_styles(self) -> None:
        c = get_theme_manager().current.colors
        self._error_label.setStyleSheet(f"color: {c.error};")

    def _on_url_changed(self, text: str) -> None:
        name = _parse_repo_name(text)
        if name:
            self._name_edit.setText(name)

    def _on_browse(self) -> None:
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Select Clone Location")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if self._folder_edit.text():
            dialog.setDirectory(self._folder_edit.text())
        if dialog.exec() == QFileDialog.Accepted:
            dirs = dialog.selectedFiles()
            if dirs:
                self._folder_edit.setText(dirs[0])

    def _on_clone(self) -> None:
        url = self._url_edit.text().strip()
        folder = self._folder_edit.text().strip()
        name = self._name_edit.text().strip()

        problem = _input_problem(url, folder, name)
        if problem is not None:
            self._show_error(problem)
            return

        dest = str(Path(folder) / name)

        self._set_cloning(True)
        self._error_label.setVisible(False)
        self._progress_label.setVisible(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting clone...")
        self._start_clone_worker(url, dest)

    def _start_clone_worker(self, url: str, dest: str) -> None:
        # A child of this dialog that deletes itself once its clone has ended, so
        # Qt frees it on the GUI thread. Parentless, it died with its last Python
        # reference, which the worker or a garbage collection on any thread could drop.
        signals = _CloneSignals(self)
        signals.progress.connect(self._on_progress)
        signals.finished.connect(self._on_finished)
        signals.failed.connect(self._on_failed)
        signals.cleanup_failed.connect(self.cleanup_failed)
        signals.ended.connect(self._on_worker_ended)
        signals.ended.connect(signals.deleteLater)
        self._clone_signals = signals  # the newest clone's, for tests to listen to
        self._workers_running += 1

        cancelled = self._cancel_requested

        def _worker():
            with suppress(RuntimeError):  # the dialog was destroyed, signals and all
                try:

                    def _report(p: CloneProgress):
                        signals.progress.emit(p.phase, p.percent)

                    clone_repo(url, dest, on_progress=_report, cancelled=cancelled)
                    signals.finished.emit(dest)
                except CloneCancelled as e:
                    # The dialog closed when the user cancelled; only leftover files need telling.
                    if e.cleanup_error is not None:
                        signals.cleanup_failed.emit(dest, str(e.cleanup_error))
                except Exception as e:
                    signals.failed.emit(str(e))
                finally:
                    signals.ended.emit()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, phase: str, percent: int) -> None:
        self._progress_label.setText(f"{phase}: {percent}%")
        self._progress_bar.setValue(percent)

    def _on_finished(self, dest: str) -> None:
        if self._cancel_requested.is_set():
            return
        self.clone_completed.emit(dest)
        self.accept()

    def _on_failed(self, error: str) -> None:
        self._set_cloning(False)
        self._progress_label.setVisible(False)
        self._progress_bar.setVisible(False)
        self._show_error(error)

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _set_cloning(self, cloning: bool) -> None:
        self._cloning = cloning
        # Cancel is the one control left enabled, so the focus leaving the
        # disabled ones would land on it, and a second Enter or a Space would
        # throw the clone away. It stays a click or Esc away.
        self._cancel_btn.setFocusPolicy(
            Qt.FocusPolicy.NoFocus if cloning else Qt.FocusPolicy.StrongFocus
        )
        for widget in (
            self._url_edit,
            self._folder_edit,
            self._folder_browse,
            self._name_edit,
            self._clone_btn,
        ):
            widget.setEnabled(not cloning)

    def reject(self) -> None:
        # The clone stops git and removes what it wrote in the background; the
        # dialog closes without waiting, so a git slow to die cannot hold the
        # app behind it, and a clone that finished meanwhile is still not opened.
        if self._cloning:
            self._cancel_requested.set()
        super().reject()

    def release(self) -> None:
        """Delete the dialog, once it has closed and no clone is still ending.

        A cancelled clone's worker outlives the closed dialog: it reports what it
        could not remove through the dialog, so deleting the dialog sooner would
        drop that report.
        """
        self._release_requested = True
        self._delete_if_idle()

    def _on_worker_ended(self) -> None:
        self._workers_running -= 1
        self._delete_if_idle()

    def _delete_if_idle(self) -> None:
        if self._release_requested and self._workers_running == 0:
            self.deleteLater()
