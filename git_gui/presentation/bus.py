# git_gui/presentation/bus.py
from __future__ import annotations
from dataclasses import dataclass
from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty,
)
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CheckoutCommit, CheckoutRemoteBranch, CreateBranch, DeleteBranch,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash, ApplyStash, DropStash,
    StageHunk, UnstageHunk, FetchAllPrune,
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
    get_commit_detail: GetCommitDetail
    is_dirty: IsDirty

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
            get_commit_detail=GetCommitDetail(reader),
            is_dirty=IsDirty(reader),
        )


@dataclass
class CommandBus:
    stage_files: StageFiles
    unstage_files: UnstageFiles
    create_commit: CreateCommit
    checkout: Checkout
    checkout_commit: CheckoutCommit
    checkout_remote_branch: CheckoutRemoteBranch
    create_branch: CreateBranch
    delete_branch: DeleteBranch
    merge: Merge
    rebase: Rebase
    push: Push
    pull: Pull
    fetch: Fetch
    stash: Stash
    pop_stash: PopStash
    apply_stash: ApplyStash
    drop_stash: DropStash
    stage_hunk: StageHunk
    unstage_hunk: UnstageHunk
    fetch_all_prune: FetchAllPrune

    @classmethod
    def from_writer(cls, writer: IRepositoryWriter) -> "CommandBus":
        return cls(
            stage_files=StageFiles(writer),
            unstage_files=UnstageFiles(writer),
            create_commit=CreateCommit(writer),
            checkout=Checkout(writer),
            checkout_commit=CheckoutCommit(writer),
            checkout_remote_branch=CheckoutRemoteBranch(writer),
            create_branch=CreateBranch(writer),
            delete_branch=DeleteBranch(writer),
            merge=Merge(writer),
            rebase=Rebase(writer),
            push=Push(writer),
            pull=Pull(writer),
            fetch=Fetch(writer),
            stash=Stash(writer),
            pop_stash=PopStash(writer),
            apply_stash=ApplyStash(writer),
            drop_stash=DropStash(writer),
            stage_hunk=StageHunk(writer),
            unstage_hunk=UnstageHunk(writer),
            fetch_all_prune=FetchAllPrune(writer),
        )
