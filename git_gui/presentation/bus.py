# git_gui/presentation/bus.py
from __future__ import annotations
from dataclasses import dataclass
from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
)
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CreateBranch, DeleteBranch,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash,
)


@dataclass
class QueryBus:
    get_commit_graph: GetCommitGraph
    get_branches: GetBranches
    get_stashes: GetStashes
    get_commit_files: GetCommitFiles
    get_file_diff: GetFileDiff
    get_staged_diff: GetStagedDiff
    get_working_tree: GetWorkingTree

    @classmethod
    def from_reader(cls, reader: IRepositoryReader) -> "QueryBus":
        return cls(
            get_commit_graph=GetCommitGraph(reader),
            get_branches=GetBranches(reader),
            get_stashes=GetStashes(reader),
            get_commit_files=GetCommitFiles(reader),
            get_file_diff=GetFileDiff(reader),
            get_staged_diff=GetStagedDiff(reader),
            get_working_tree=GetWorkingTree(reader),
        )


@dataclass
class CommandBus:
    stage_files: StageFiles
    unstage_files: UnstageFiles
    create_commit: CreateCommit
    checkout: Checkout
    create_branch: CreateBranch
    delete_branch: DeleteBranch
    merge: Merge
    rebase: Rebase
    push: Push
    pull: Pull
    fetch: Fetch
    stash: Stash
    pop_stash: PopStash

    @classmethod
    def from_writer(cls, writer: IRepositoryWriter) -> "CommandBus":
        return cls(
            stage_files=StageFiles(writer),
            unstage_files=UnstageFiles(writer),
            create_commit=CreateCommit(writer),
            checkout=Checkout(writer),
            create_branch=CreateBranch(writer),
            delete_branch=DeleteBranch(writer),
            merge=Merge(writer),
            rebase=Rebase(writer),
            push=Push(writer),
            pull=Pull(writer),
            fetch=Fetch(writer),
            stash=Stash(writer),
            pop_stash=PopStash(writer),
        )
