from __future__ import annotations
from git_gui.domain.entities import Branch, Commit, FileStatus, Hunk, Stash, Tag
from git_gui.domain.ports import IRepositoryReader


class GetCommitGraph:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, limit: int = 200, skip: int = 0, extra_tips: list[str] | None = None) -> list[Commit]:
        return self._reader.get_commits(limit, skip, extra_tips=extra_tips)


class GetBranches:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Branch]:
        return self._reader.get_branches()


class GetStashes:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Stash]:
        return self._reader.get_stashes()


class GetTags:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Tag]:
        return self._reader.get_tags()


class GetRemoteTags:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, remote: str) -> list[str]:
        return self._reader.get_remote_tags(remote)


class GetCommitFiles:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str) -> list[FileStatus]:
        return self._reader.get_commit_files(oid)


class GetFileDiff:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str, path: str) -> list[Hunk]:
        return self._reader.get_file_diff(oid, path)


class GetStagedDiff:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, path: str) -> list[Hunk]:
        return self._reader.get_staged_diff(path)


class GetWorkingTree:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[FileStatus]:
        return self._reader.get_working_tree()


class IsDirty:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> bool:
        return self._reader.is_dirty()


class GetHeadOid:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> str | None:
        return self._reader.get_head_oid()


class GetCommitDetail:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str) -> Commit:
        return self._reader.get_commit(oid)
