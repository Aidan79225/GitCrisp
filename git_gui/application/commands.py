from __future__ import annotations
from git_gui.domain.entities import Branch, Commit
from git_gui.domain.ports import IRepositoryWriter


class StageFiles:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, paths: list[str]) -> None:
        self._writer.stage(paths)


class UnstageFiles:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, paths: list[str]) -> None:
        self._writer.unstage(paths)


class CreateCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, message: str) -> Commit:
        return self._writer.commit(message)


class Checkout:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, branch: str) -> None:
        self._writer.checkout(branch)


class CheckoutCommit:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, oid: str) -> None:
        self._writer.checkout_commit(oid)


class CheckoutRemoteBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote_branch: str) -> None:
        self._writer.checkout_remote_branch(remote_branch)


class CreateBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, from_oid: str) -> Branch:
        return self._writer.create_branch(name, from_oid)


class DeleteBranch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str) -> None:
        self._writer.delete_branch(name)


class CreateTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, oid: str, message: str | None = None) -> None:
        self._writer.create_tag(name, oid, message)


class DeleteTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str) -> None:
        self._writer.delete_tag(name)


class PushTag:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, name: str) -> None:
        self._writer.push_tag(remote, name)


class Merge:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, branch: str) -> None:
        self._writer.merge(branch)


class Rebase:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, branch: str) -> None:
        self._writer.rebase(branch)


class Push:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, branch: str) -> None:
        self._writer.push(remote, branch)


class Pull:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str, branch: str) -> None:
        self._writer.pull(remote, branch)


class Fetch:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, remote: str) -> None:
        self._writer.fetch(remote)


class FetchAllPrune:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self) -> None:
        self._writer.fetch_all_prune()


class Stash:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, message: str) -> None:
        self._writer.stash(message)


class PopStash:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, index: int) -> None:
        self._writer.pop_stash(index)


class ApplyStash:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, index: int) -> None:
        self._writer.apply_stash(index)


class DropStash:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, index: int) -> None:
        self._writer.drop_stash(index)


class StageHunk:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, hunk_header: str) -> None:
        self._writer.stage_hunk(path, hunk_header)


class UnstageHunk:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, hunk_header: str) -> None:
        self._writer.unstage_hunk(path, hunk_header)


class DiscardFile:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str) -> None:
        self._writer.discard_file(path)


class DiscardHunk:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, hunk_header: str) -> None:
        self._writer.discard_hunk(path, hunk_header)


class AddRemote:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, url: str) -> None:
        self._writer.add_remote(name, url)


class RemoveRemote:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str) -> None:
        self._writer.remove_remote(name)


class RenameRemote:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, old_name: str, new_name: str) -> None:
        self._writer.rename_remote(old_name, new_name)


class SetRemoteUrl:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, name: str, url: str) -> None:
        self._writer.set_remote_url(name, url)


class AddSubmodule:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, url: str) -> None:
        self._writer.add_submodule(path, url)


class RemoveSubmodule:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str) -> None:
        self._writer.remove_submodule(path)


class SetSubmoduleUrl:
    def __init__(self, writer: IRepositoryWriter) -> None:
        self._writer = writer

    def execute(self, path: str, url: str) -> None:
        self._writer.set_submodule_url(path, url)
