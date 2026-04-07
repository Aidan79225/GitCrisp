# git_gui/presentation/widgets/clone_dialog.py
from __future__ import annotations
import re
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QVBoxLayout,
)
from git_gui.infrastructure.git_clone import CloneProgress, clone_repo
from git_gui.presentation.theme import get_theme_manager, connect_widget


_REPO_NAME_RE = re.compile(r"[/:]([^/:]+?)(?:\.git)?/?$")


def _parse_repo_name(url: str) -> str:
    """Extract repo name from a git URL."""
    m = _REPO_NAME_RE.search(url.strip())
    return m.group(1) if m else ""


class _CloneSignals(QObject):
    progress = Signal(str, int)    # phase, percent
    finished = Signal(str)         # dest path
    failed = Signal(str)           # error message


class CloneDialog(QDialog):
    clone_completed = Signal(str)  # dest path

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clone Repository")
        self.setMinimumWidth(500)
        self._proc_thread: threading.Thread | None = None

        # URL
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://github.com/user/repo.git  or  git@github.com:user/repo.git")
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

        if not url:
            self._show_error("URL is required")
            return
        if not folder:
            self._show_error("Location is required")
            return
        if not name:
            self._show_error("Folder name is required")
            return

        dest = str(Path(folder) / name)

        # Disable inputs
        self._set_inputs_enabled(False)
        self._error_label.setVisible(False)
        self._progress_label.setVisible(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting clone...")

        signals = _CloneSignals()
        signals.progress.connect(self._on_progress)
        signals.finished.connect(self._on_finished)
        signals.failed.connect(self._on_failed)
        self._clone_signals = signals  # prevent GC

        def _worker():
            try:
                def _report(p: CloneProgress):
                    signals.progress.emit(p.phase, p.percent)
                clone_repo(url, dest, on_progress=_report)
                signals.finished.emit(dest)
            except Exception as e:
                signals.failed.emit(str(e))

        self._proc_thread = threading.Thread(target=_worker, daemon=True)
        self._proc_thread.start()

    def _on_progress(self, phase: str, percent: int) -> None:
        self._progress_label.setText(f"{phase}: {percent}%")
        self._progress_bar.setValue(percent)

    def _on_finished(self, dest: str) -> None:
        self.clone_completed.emit(dest)
        self.accept()

    def _on_failed(self, error: str) -> None:
        self._set_inputs_enabled(True)
        self._progress_label.setVisible(False)
        self._progress_bar.setVisible(False)
        self._show_error(error)

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.setVisible(True)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        self._url_edit.setEnabled(enabled)
        self._folder_edit.setEnabled(enabled)
        self._folder_browse.setEnabled(enabled)
        self._name_edit.setEnabled(enabled)
        self._clone_btn.setEnabled(enabled)
