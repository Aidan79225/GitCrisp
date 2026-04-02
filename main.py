import sys
from PySide6.QtWidgets import QApplication, QFileDialog
from git_gui.presentation.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("git gui")

    repo_path = QFileDialog.getExistingDirectory(
        None,
        "Open Repository",
        "",
    )
    if not repo_path:
        sys.exit(0)

    window = MainWindow(repo_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
