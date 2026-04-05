import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QFileDialog
from git_gui.infrastructure.pygit2_repo import Pygit2Repository
from git_gui.infrastructure.repo_store import JsonRepoStore
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.presentation.bus import CommandBus, QueryBus
from git_gui.presentation.main_window import MainWindow


def _pick_repo() -> str:
    dialog = QFileDialog()
    dialog.setWindowTitle("Open Repository")
    dialog.setFileMode(QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    if dialog.exec() == QFileDialog.Accepted:
        dirs = dialog.selectedFiles()
        return dirs[0] if dirs else ""
    return ""


def _find_valid_repo(repo_store: JsonRepoStore) -> str | None:
    """Return the first valid repo path from active or open list, pruning invalid ones."""
    active = repo_store.get_active()
    if active and Path(active).is_dir():
        return active

    for path in list(repo_store.get_open_repos()):
        if Path(path).is_dir():
            repo_store.set_active(path)
            return path
        repo_store.close_repo(path)

    repo_store.save()
    return None


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("GitCrisp")

    repo_store = JsonRepoStore()
    repo_store.load()
    remote_tag_cache = JsonRemoteTagCache()

    repo_path = _find_valid_repo(repo_store)

    if not repo_path:
        repo_path = _pick_repo()
        if not repo_path:
            sys.exit(0)
        repo_store.add_open(repo_path)
        repo_store.save()

    if repo_path not in repo_store.get_open_repos():
        repo_store.add_open(repo_path)
        repo_store.save()

    repo = Pygit2Repository(repo_path)
    queries = QueryBus.from_reader(repo)
    commands = CommandBus.from_writer(repo)

    window = MainWindow(queries, commands, repo_store, remote_tag_cache, repo_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
