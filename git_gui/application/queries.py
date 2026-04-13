from __future__ import annotations
from datetime import datetime
from git_gui.domain.entities import Branch, Commit, CommitStat, FileStatus, Hunk, LocalBranchInfo, Remote, RepoStateInfo, Stash, Submodule, Tag, MergeAnalysisResult
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


class GetCommitStats:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, since: datetime | None = None, until: datetime | None = None) -> list[CommitStat]:
        return self._reader.get_commit_stats(since, until)


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


class ListRemotes:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Remote]:
        return self._reader.list_remotes()


class ListSubmodules:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[Submodule]:
        return self._reader.list_submodules()


class ListLocalBranchesWithUpstream:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> list[LocalBranchInfo]:
        return self._reader.list_local_branches_with_upstream()


class GetRepoState:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> RepoStateInfo:
        return self._reader.repo_state()


class IsAncestor:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, ancestor_oid: str, descendant_oid: str) -> bool:
        return self._reader.is_ancestor(ancestor_oid, descendant_oid)


class GetMergeAnalysis:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader
    def execute(self, oid: str) -> MergeAnalysisResult:
        return self._reader.merge_analysis(oid)


class GetMergeHead:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader
    def execute(self) -> str | None:
        return self._reader.get_merge_head()


class GetMergeMsg:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader
    def execute(self) -> str | None:
        return self._reader.get_merge_msg()


class HasUnresolvedConflicts:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader
    def execute(self) -> bool:
        return self._reader.has_unresolved_conflicts()


class GetCommitDiffMap:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, oid: str) -> dict[str, list[Hunk]]:
        return self._reader.get_commit_diff_map(oid)


class GetWorkingTreeDiffMap:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self) -> dict[str, dict[str, list[Hunk]]]:
        return self._reader.get_working_tree_diff_map()


class GetCommitRange:
    def __init__(self, reader: IRepositoryReader) -> None:
        self._reader = reader

    def execute(self, head_oid: str, base_oid: str) -> list[Commit]:
        return self._reader.get_commit_range(head_oid, base_oid)
