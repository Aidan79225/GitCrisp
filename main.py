import sys
from PySide6.QtWidgets import QApplication, QFileDialog
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("git gui")

    # Accept path as CLI argument, otherwise show dialog
    if len(sys.argv) > 1:
        repo_path = sys.argv[1]
    else:
        repo_path = QFileDialog.getExistingDirectory(None, "Open Repository", "")
    if not repo_path:
        sys.exit(0)

    repo = Pygit2Repository(repo_path)
    queries = QueryBus.from_reader(repo)
    commands = CommandBus.from_writer(repo)

    window = MainWindow(queries, commands, repo_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
