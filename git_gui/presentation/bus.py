# git_gui/presentation/bus.py
from __future__ import annotations
from dataclasses import dataclass
from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.application.queries import (
    GetCommitGraph, GetBranches, GetStashes, GetTags, GetRemoteTags, GetCommitStats,
    GetCommitFiles, GetFileDiff, GetStagedDiff, GetWorkingTree,
    GetCommitDetail, IsDirty, GetHeadOid,
    ListRemotes, ListSubmodules, ListLocalBranchesWithUpstream,
)
from git_gui.application.commands import (
    StageFiles, UnstageFiles, CreateCommit,
    Checkout, CheckoutCommit, CheckoutRemoteBranch, CreateBranch, DeleteBranch,
    CreateTag, DeleteTag, PushTag, DeleteRemoteTag,
    Merge, Rebase, Push, Pull, Fetch,
    Stash, PopStash, ApplyStash, DropStash,
    StageHunk, UnstageHunk, FetchAllPrune,
    DiscardFile, DiscardHunk,
    AddRemote, RemoveRemote, RenameRemote, SetRemoteUrl,
    AddSubmodule, RemoveSubmodule, SetSubmoduleUrl,
    SetBranchUpstream, UnsetBranchUpstream, RenameBranch, ResetBranchToRef,
)


@dataclass
class QueryBus:
    get_commit_graph: GetCommitGraph
    get_branches: GetBranches
    get_stashes: GetStashes
    get_tags: GetTags
    get_remote_tags: GetRemoteTags
    get_commit_stats: GetCommitStats
    get_commit_files: GetCommitFiles
    get_file_diff: GetFileDiff
    get_staged_diff: GetStagedDiff
    get_working_tree: GetWorkingTree
    get_commit_detail: GetCommitDetail
    is_dirty: IsDirty
    get_head_oid: GetHeadOid
    list_remotes: ListRemotes
    list_submodules: ListSubmodules
    list_local_branches_with_upstream: ListLocalBranchesWithUpstream

    @classmethod
    def from_reader(cls, reader: IRepositoryReader) -> "QueryBus":
        return cls(
            get_commit_graph=GetCommitGraph(reader),
            get_branches=GetBranches(reader),
            get_stashes=GetStashes(reader),
            get_tags=GetTags(reader),
            get_remote_tags=GetRemoteTags(reader),
            get_commit_stats=GetCommitStats(reader),
            get_commit_files=GetCommitFiles(reader),
            get_file_diff=GetFileDiff(reader),
            get_staged_diff=GetStagedDiff(reader),
            get_working_tree=GetWorkingTree(reader),
            get_commit_detail=GetCommitDetail(reader),
            is_dirty=IsDirty(reader),
            get_head_oid=GetHeadOid(reader),
            list_remotes=ListRemotes(reader),
            list_submodules=ListSubmodules(reader),
            list_local_branches_with_upstream=ListLocalBranchesWithUpstream(reader),
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
    create_tag: CreateTag
    delete_tag: DeleteTag
    push_tag: PushTag
    delete_remote_tag: DeleteRemoteTag
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
    discard_file: DiscardFile
    discard_hunk: DiscardHunk
    fetch_all_prune: FetchAllPrune
    add_remote: AddRemote
    remove_remote: RemoveRemote
    rename_remote: RenameRemote
    set_remote_url: SetRemoteUrl
    add_submodule: AddSubmodule
    remove_submodule: RemoveSubmodule
    set_submodule_url: SetSubmoduleUrl
    set_branch_upstream: SetBranchUpstream
    unset_branch_upstream: UnsetBranchUpstream
    rename_branch: RenameBranch
    reset_branch_to_ref: ResetBranchToRef

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
            create_tag=CreateTag(writer),
            delete_tag=DeleteTag(writer),
            push_tag=PushTag(writer),
            delete_remote_tag=DeleteRemoteTag(writer),
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
            discard_file=DiscardFile(writer),
            discard_hunk=DiscardHunk(writer),
            fetch_all_prune=FetchAllPrune(writer),
            add_remote=AddRemote(writer),
            remove_remote=RemoveRemote(writer),
            rename_remote=RenameRemote(writer),
            set_remote_url=SetRemoteUrl(writer),
            add_submodule=AddSubmodule(writer),
            remove_submodule=RemoveSubmodule(writer),
            set_submodule_url=SetSubmoduleUrl(writer),
            set_branch_upstream=SetBranchUpstream(writer),
            unset_branch_upstream=UnsetBranchUpstream(writer),
            rename_branch=RenameBranch(writer),
            reset_branch_to_ref=ResetBranchToRef(writer),
        )
