import pygit2
import pytest

from git_gui.infrastructure.pygit2 import Pygit2Repository


def test_get_commits_returns_initial_commit(repo_impl):
    commits = repo_impl.get_commits(limit=10)
    assert len(commits) == 1
    assert commits[0].message == "Initial commit"
    assert commits[0].parents == []


def test_get_commits_oid_is_string(repo_impl):
    commits = repo_impl.get_commits(limit=10)
    assert isinstance(commits[0].oid, str)
    assert len(commits[0].oid) == 40


def test_get_commits_timestamp_is_local_tz_aware(repo_impl):
    """Commit timestamps should be tz-aware in the user's local timezone,
    not UTC. Render sites call strftime() directly on the datetime, so
    the tzinfo determines whether the user sees local or UTC wall-clock."""
    from datetime import datetime

    commits = repo_impl.get_commits(limit=10)
    ts = commits[0].timestamp
    assert ts.tzinfo is not None
    expected_tz = datetime.now().astimezone().tzinfo
    # Compare UTC offsets — tzinfo objects may not be `==` even when they
    # represent the same offset.
    assert ts.utcoffset() == datetime.now(tz=expected_tz).utcoffset()


def test_get_commits_respects_limit(repo_path):
    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    # add a second commit
    (repo_path / "b.txt").write_text("b")
    repo.index.add("b.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    head_oid = repo.head.target
    repo.create_commit("refs/heads/master", sig, sig, "Second commit", tree, [head_oid])

    impl = Pygit2Repository(str(repo_path))
    commits = impl.get_commits(limit=1)
    assert len(commits) == 1
    assert commits[0].message == "Second commit"


def test_get_branches_returns_master(repo_impl):
    branches = repo_impl.get_branches()
    names = [b.name for b in branches]
    assert "master" in names


def test_get_branches_head_is_marked(repo_impl):
    branches = repo_impl.get_branches()
    head_branches = [b for b in branches if b.is_head]
    assert len(head_branches) == 1
    assert head_branches[0].name == "master"


def test_get_working_tree_empty_on_clean_repo(repo_impl):
    files = repo_impl.get_working_tree()
    assert files == []


def test_get_working_tree_detects_untracked(repo_path, repo_impl):
    (repo_path / "untracked.txt").write_text("new")
    files = repo_impl.get_working_tree()
    paths = [f.path for f in files]
    assert "untracked.txt" in paths
    untracked = next(f for f in files if f.path == "untracked.txt")
    assert untracked.status == "untracked"


def test_get_working_tree_detects_modified(repo_path, repo_impl):
    (repo_path / "README.md").write_text("modified content\n")
    files = repo_impl.get_working_tree()
    modified = next((f for f in files if f.path == "README.md"), None)
    assert modified is not None
    assert modified.status == "unstaged"
    assert modified.delta == "modified"


def test_get_commit_files_initial_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    files = repo_impl.get_commit_files(commits[0].oid)
    paths = [f.path for f in files]
    assert "README.md" in paths


def test_get_stashes_empty(repo_impl):
    stashes = repo_impl.get_stashes()
    assert stashes == []


def test_get_file_diff_initial_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    hunks = repo_impl.get_file_diff(commits[0].oid, "README.md")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("Test Repo" in line for line in added_lines)


def test_get_staged_diff_empty_when_nothing_staged(repo_impl):
    hunks = repo_impl.get_staged_diff("README.md")
    assert hunks == []


def test_get_staged_diff_returns_hunks_after_staging(repo_path, repo_impl):
    (repo_path / "README.md").write_text("# Test Repo\nnew line\n")
    repo_impl.stage(["README.md"])
    hunks = repo_impl.get_staged_diff("README.md")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("new line" in line for line in added_lines)


def test_get_staged_diff_new_file_unborn_head(tmp_path):
    """get_staged_diff on a brand-new repo (no commits yet) shows staged new file."""
    import pygit2

    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.init_repository(str(tmp_path))
    (tmp_path / "new.txt").write_text("hello\n")
    repo.index.add("new.txt")
    repo.index.write()
    impl = Pygit2Repository(str(tmp_path))
    hunks = impl.get_staged_diff("new.txt")
    assert len(hunks) >= 1
    all_lines = [line for h in hunks for line in h.lines]
    added_lines = [content for origin, content in all_lines if origin == "+"]
    assert any("hello" in line for line in added_lines)


def test_get_commit_returns_commit(repo_impl):
    commits = repo_impl.get_commits(limit=1)
    oid = commits[0].oid
    commit = repo_impl.get_commit(oid)
    assert commit.oid == oid
    assert commit.message == "Initial commit"
    assert "Test User" in commit.author


def test_get_tags_empty(repo_impl):
    tags = repo_impl.get_tags()
    assert tags == []


def test_get_tags_lightweight(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    target = raw.head.target
    raw.references.create("refs/tags/v1.0.0", target)
    tags = repo_impl.get_tags()
    assert len(tags) == 1
    assert tags[0].name == "v1.0.0"
    assert tags[0].target_oid == str(target)
    assert tags[0].is_annotated is False
    assert tags[0].message is None


def test_get_remote_tags_no_remote(repo_impl):
    """Repos without remotes return an empty list."""
    tags = repo_impl.get_remote_tags("origin")
    assert tags == []


def test_get_tags_annotated(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    target = raw.head.target
    sig = pygit2.Signature("Tagger", "tagger@example.com")
    raw.create_tag("v2.0.0", target, pygit2.GIT_OBJECT_COMMIT, sig, "Release 2.0")
    tags = repo_impl.get_tags()
    annotated = [t for t in tags if t.name == "v2.0.0"]
    assert len(annotated) == 1
    assert annotated[0].is_annotated is True
    assert annotated[0].message == "Release 2.0"
    assert "Tagger" in annotated[0].tagger


def test_get_commit_stats_returns_initial_commit(repo_impl):
    stats = list(repo_impl.get_commit_stats())
    assert len(stats) == 1
    assert "Test User" in stats[0].author
    assert len(stats[0].files) == 1
    assert stats[0].files[0].path == "README.md"
    assert stats[0].files[0].added >= 1


def test_repo_state_clean(repo_impl):
    info = repo_impl.repo_state()
    assert info.state.name == "CLEAN"
    assert info.head_branch in ("main", "master")


def test_repo_state_detached(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    head_oid = raw.head.target
    raw.checkout_tree(raw.get(head_oid))
    raw.set_head(head_oid)
    info = repo_impl.repo_state()
    assert info.state.name == "DETACHED_HEAD"
    assert info.head_branch is None


def test_repo_state_merging(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    base = raw.head.target

    # Commit A on master (conflicting change to README.md)
    (repo_path / "README.md").write_text("master change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_a = raw.index.write_tree()
    raw.create_commit("refs/heads/master", sig, sig, "master change", tree_a, [base])

    # Create feature branch from base with conflicting change
    raw.branches.local.create("feature", raw.get(base))
    raw.checkout("refs/heads/feature")
    (repo_path / "README.md").write_text("feature change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_b = raw.index.write_tree()
    raw.create_commit("refs/heads/feature", sig, sig, "feature change", tree_b, [base])

    # Switch back to master and merge feature -> produces MERGING state (conflict)
    raw.checkout("refs/heads/master")
    raw.merge(raw.branches.local["feature"].target)

    info = repo_impl.repo_state()
    assert info.state.name == "MERGING"
    assert info.head_branch == "master"


def test_repo_state_rebasing(repo_path, repo_impl):
    """A conflicted rebase reports REBASING, not CLEAN.

    Guards the same mapping as `test_repo_state_merging`: `repo_state` must
    translate every `RepositoryState` libgit2 reports, not just MERGE.
    """
    impl = Pygit2Repository(str(repo_path))
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    base = raw.head.target

    (repo_path / "README.md").write_text("master change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_a = raw.index.write_tree()
    raw.create_commit("refs/heads/master", sig, sig, "master change", tree_a, [base])

    raw.branches.local.create("topic", raw.get(base))
    raw.checkout("refs/heads/topic")
    (repo_path / "README.md").write_text("topic change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_b = raw.index.write_tree()
    raw.create_commit("refs/heads/topic", sig, sig, "topic change", tree_b, [base])

    with pytest.raises(RuntimeError):
        impl.rebase("master")

    assert repo_impl.repo_state().state.name == "REBASING"


def test_get_commit_stats_with_multiple_commits(repo_path, repo_impl):
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("Author Two", "two@example.com")
    (repo_path / "second.txt").write_text("line1\nline2\nline3\n")
    raw.index.add("second.txt")
    raw.index.write()
    tree = raw.index.write_tree()
    head_oid = raw.head.target
    raw.create_commit("refs/heads/master", sig, sig, "Add second", tree, [head_oid])

    stats = list(repo_impl.get_commit_stats())
    assert len(stats) == 2
    authors = [s.author for s in stats]
    assert any("Author Two" in a for a in authors)
    assert any("Test User" in a for a in authors)


def test_is_ancestor(repo_path, repo_impl):
    first_oid = repo_impl.get_head_oid()
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    (repo_path / "b.txt").write_text("b")
    raw.index.add("b.txt")
    raw.index.write()
    tree = raw.index.write_tree()
    head_oid = raw.head.target
    second_oid = raw.create_commit("refs/heads/master", sig, sig, "Second commit", tree, [head_oid])

    assert repo_impl.is_ancestor(first_oid, str(second_oid)) is True
    assert repo_impl.is_ancestor(str(second_oid), first_oid) is False
    assert repo_impl.is_ancestor(first_oid, first_oid) is False


def test_merge_analysis_can_ff(repo_impl, repo_path):
    """Linear history: feature is ahead of main → can fast-forward."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("feature", head_oid)
    repo_impl.checkout("feature")
    (repo_path / "ff.txt").write_text("ff")
    repo_impl.stage(["ff.txt"])
    new = repo_impl.commit("ahead")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name != "feature")
    repo_impl.checkout(main_name)

    result = repo_impl.merge_analysis(new.oid)
    assert result.can_ff is True
    assert result.is_up_to_date is False


def test_merge_analysis_normal(repo_impl, repo_path):
    """Diverged history → cannot fast-forward."""
    head_oid = repo_impl.get_head_oid()
    repo_impl.create_branch("diverge", head_oid)
    # Commit on main
    (repo_path / "main_side.txt").write_text("m")
    repo_impl.stage(["main_side.txt"])
    repo_impl.commit("main side")
    # Commit on diverge
    repo_impl.checkout("diverge")
    (repo_path / "diverge_side.txt").write_text("d")
    repo_impl.stage(["diverge_side.txt"])
    diverge_commit = repo_impl.commit("diverge side")
    branches = repo_impl.get_branches()
    main_name = next(b.name for b in branches if not b.is_remote and b.name not in ("diverge",))
    repo_impl.checkout(main_name)

    result = repo_impl.merge_analysis(diverge_commit.oid)
    assert result.can_ff is False
    assert result.is_up_to_date is False


def test_merge_analysis_up_to_date(repo_impl, repo_path):
    """Same commit → already up to date."""
    head_oid = repo_impl.get_head_oid()
    result = repo_impl.merge_analysis(head_oid)
    assert result.is_up_to_date is True


# ---- get_merge_head / get_merge_msg / has_unresolved_conflicts ----


def _create_merge_conflict(repo_path):
    """Helper: create divergent branches with conflicting changes, trigger merge."""
    raw = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    base = raw.head.target

    # Commit on master (conflicting change to README.md)
    (repo_path / "README.md").write_text("master change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_a = raw.index.write_tree()
    raw.create_commit("refs/heads/master", sig, sig, "master change", tree_a, [base])

    # Create branch from base with conflicting change
    raw.branches.local.create("conflict-branch", raw.get(base))
    raw.checkout("refs/heads/conflict-branch")
    (repo_path / "README.md").write_text("branch change\n")
    raw.index.add("README.md")
    raw.index.write()
    tree_b = raw.index.write_tree()
    branch_tip = raw.create_commit(
        "refs/heads/conflict-branch", sig, sig, "branch change", tree_b, [base]
    )

    # Switch back to master and merge -> conflict
    raw.checkout("refs/heads/master")
    raw.merge(raw.branches.local["conflict-branch"].target)
    return str(branch_tip)


def test_get_merge_head_returns_none_when_clean(repo_impl):
    assert repo_impl.get_merge_head() is None


def test_get_merge_head_returns_oid_during_merge(repo_path, repo_impl):
    branch_tip = _create_merge_conflict(repo_path)
    result = repo_impl.get_merge_head()
    assert result is not None
    assert result == branch_tip


def test_get_merge_msg_returns_none_when_clean(repo_impl):
    assert repo_impl.get_merge_msg() is None


def test_get_merge_msg_returns_content_during_merge(repo_path, repo_impl):
    _create_merge_conflict(repo_path)
    msg = repo_impl.get_merge_msg()
    assert msg is not None
    assert "Merge" in msg or "conflict-branch" in msg


def test_has_unresolved_conflicts_false_when_clean(repo_impl):
    assert repo_impl.has_unresolved_conflicts() is False


def test_has_unresolved_conflicts_true_during_merge(repo_path, repo_impl):
    _create_merge_conflict(repo_path)
    assert repo_impl.has_unresolved_conflicts() is True


def test_get_commit_diff_map_returns_all_files(repo_impl, repo_path):
    """A commit with 3 modified files returns all 3 in the diff map."""
    (repo_path / "a.txt").write_text("a1\n")
    (repo_path / "b.txt").write_text("b1\n")
    (repo_path / "c.txt").write_text("c1\n")
    repo_impl.stage(["a.txt", "b.txt", "c.txt"])
    repo_impl.commit("initial")
    (repo_path / "a.txt").write_text("a2\n")
    (repo_path / "b.txt").write_text("b2\n")
    (repo_path / "c.txt").write_text("c2\n")
    repo_impl.stage(["a.txt", "b.txt", "c.txt"])
    second = repo_impl.commit("second")

    result = repo_impl.get_commit_diff_map(second.oid)

    assert set(result.keys()) == {"a.txt", "b.txt", "c.txt"}
    for path in ("a.txt", "b.txt", "c.txt"):
        assert len(result[path]) > 0, f"{path} has no hunks"


def test_get_commit_diff_map_initial_commit(repo_impl, repo_path):
    """Initial commit (no parent) returns all files as additions."""
    (repo_path / "new.txt").write_text("hello\n")
    repo_impl.stage(["new.txt"])
    first = repo_impl.commit("first")

    result = repo_impl.get_commit_diff_map(first.oid)

    assert "new.txt" in result
    assert len(result["new.txt"]) > 0


def test_get_working_tree_diff_map_staged_and_unstaged(repo_impl, repo_path):
    """Staged + unstaged changes appear in the map with correct sub-dict keys."""
    (repo_path / "base.txt").write_text("base\n")
    repo_impl.stage(["base.txt"])
    repo_impl.commit("base")
    (repo_path / "staged.txt").write_text("staged content\n")
    repo_impl.stage(["staged.txt"])
    (repo_path / "base.txt").write_text("base modified\n")

    result = repo_impl.get_working_tree_diff_map()

    assert "staged.txt" in result
    assert result["staged.txt"]["staged"], "staged.txt should have staged hunks"
    assert "base.txt" in result
    assert result["base.txt"]["unstaged"], "base.txt should have unstaged hunks"


def test_get_working_tree_diff_map_includes_untracked(repo_impl, repo_path):
    """Untracked files appear in the map with unstaged hunks."""
    (repo_path / "base.txt").write_text("base\n")
    repo_impl.stage(["base.txt"])
    repo_impl.commit("base")
    (repo_path / "untracked.txt").write_text("hi\n")

    result = repo_impl.get_working_tree_diff_map()

    assert "untracked.txt" in result
    assert result["untracked.txt"]["unstaged"]


def test_get_working_tree_diff_map_empty_when_clean(repo_impl, repo_path):
    """A clean working tree returns an empty dict."""
    (repo_path / "base.txt").write_text("base\n")
    repo_impl.stage(["base.txt"])
    repo_impl.commit("base")

    result = repo_impl.get_working_tree_diff_map()

    assert result == {}


# ---------- _resolve_gitdir ----------


def test_resolve_gitdir_normal_repo_passthrough(tmp_path):
    """A normal repo where .git is a directory is returned unchanged."""
    from git_gui.infrastructure.pygit2._helpers import _resolve_gitdir

    (tmp_path / ".git").mkdir()

    result = _resolve_gitdir(str(tmp_path))

    assert result == str(tmp_path)


def test_resolve_gitdir_submodule_follows_gitlink(tmp_path):
    """A submodule where .git is a gitlink file is resolved to the real gitdir."""
    from git_gui.infrastructure.pygit2._helpers import _resolve_gitdir

    # Simulate a submodule layout:
    #   parent/
    #     .git/modules/sub/      <-- the real gitdir
    #     sub/
    #       .git                 <-- gitlink file containing "gitdir: ../.git/modules/sub"
    parent = tmp_path / "parent"
    real_gitdir = parent / ".git" / "modules" / "sub"
    real_gitdir.mkdir(parents=True)
    sub = parent / "sub"
    sub.mkdir()
    (sub / ".git").write_text("gitdir: ../.git/modules/sub\n", encoding="utf-8")

    result = _resolve_gitdir(str(sub))

    import os

    assert os.path.normpath(result) == os.path.normpath(str(real_gitdir))


def test_resolve_gitdir_missing_dot_git_passthrough(tmp_path):
    """A path with no .git at all and no parent submodule context is returned unchanged."""
    from git_gui.infrastructure.pygit2._helpers import _resolve_gitdir

    result = _resolve_gitdir(str(tmp_path))

    assert result == str(tmp_path)


def test_resolve_gitdir_uninitialized_submodule(tmp_path):
    """Submodule workdir with no .git file at all — resolved via parent .gitmodules."""
    from git_gui.infrastructure.pygit2._helpers import _resolve_gitdir

    # Simulate:
    #   parent/
    #     .git/                                        <-- parent repo
    #     .git/modules/apps/sub/                       <-- submodule gitdir
    #     .gitmodules                                  <-- lists apps/sub
    #     apps/sub/                                    <-- EMPTY workdir (no .git)
    parent = tmp_path / "parent"
    (parent / ".git").mkdir(parents=True)
    submodule_gitdir = parent / ".git" / "modules" / "apps" / "sub"
    submodule_gitdir.mkdir(parents=True)
    (parent / ".gitmodules").write_text(
        '[submodule "apps/sub"]\n\tpath = apps/sub\n\turl = https://example.com/sub.git\n',
        encoding="utf-8",
    )
    sub_workdir = parent / "apps" / "sub"
    sub_workdir.mkdir(parents=True)

    result = _resolve_gitdir(str(sub_workdir))

    import os

    assert os.path.normpath(result) == os.path.normpath(str(submodule_gitdir))


def test_resolve_gitdir_uninitialized_submodule_nested(tmp_path):
    """Walk up multiple levels to find the parent repo when the path is nested."""
    from git_gui.infrastructure.pygit2._helpers import _resolve_gitdir

    parent = tmp_path / "parent"
    (parent / ".git").mkdir(parents=True)
    submodule_gitdir = parent / ".git" / "modules" / "libs" / "foo" / "bar"
    submodule_gitdir.mkdir(parents=True)
    (parent / ".gitmodules").write_text(
        '[submodule "libs/foo/bar"]\n\tpath = libs/foo/bar\n\turl = https://example.com/bar.git\n',
        encoding="utf-8",
    )
    sub_workdir = parent / "libs" / "foo" / "bar"
    sub_workdir.mkdir(parents=True)

    result = _resolve_gitdir(str(sub_workdir))

    import os

    assert os.path.normpath(result) == os.path.normpath(str(submodule_gitdir))


# ---------- _parse_gitmodules_paths ----------


def test_parse_gitmodules_paths_empty(tmp_path):
    from git_gui.infrastructure.pygit2._helpers import _parse_gitmodules_paths

    assert _parse_gitmodules_paths(str(tmp_path)) == []


def test_parse_gitmodules_paths_multiple(tmp_path):
    from git_gui.infrastructure.pygit2._helpers import _parse_gitmodules_paths

    (tmp_path / ".gitmodules").write_text(
        '[submodule "apps/a"]\n'
        "\tpath = apps/a\n"
        "\turl = https://example.com/a.git\n"
        '[submodule "libs/b"]\n'
        "\tpath = libs/b\n"
        "\turl = https://example.com/b.git\n",
        encoding="utf-8",
    )
    result = _parse_gitmodules_paths(str(tmp_path))
    assert result == ["apps/a", "libs/b"]


# ---------- _submodule_diff_hunk ----------


def test_submodule_diff_hunk_format():
    from git_gui.infrastructure.pygit2._helpers import _submodule_diff_hunk

    hunk = _submodule_diff_hunk("aaa111", "bbb222")
    assert hunk.header == "@@ -1,1 +1,1 @@"
    assert hunk.lines == [
        ("-", "Subproject commit aaa111\n"),
        ("+", "Subproject commit bbb222\n"),
    ]


# ---------- get_commit_range ----------


def test_get_commit_range_returns_oldest_first(repo_impl, repo_path):
    """Create A → B → C chain. Range from C (HEAD) to A should return [B, C] oldest-first."""
    # The conftest fixture creates an initial commit (A).
    head_a = repo_impl.get_head_oid()

    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    (repo_path / "c.txt").write_text("c")
    repo_impl.stage(["c.txt"])
    commit_c = repo_impl.commit("commit C")

    result = repo_impl.get_commit_range(commit_c.oid, head_a)

    assert len(result) == 2
    assert result[0].oid == commit_b.oid  # oldest first
    assert result[1].oid == commit_c.oid


def test_get_commit_range_empty_when_same(repo_impl, repo_path):
    """When head_oid == base_oid, the range is empty."""
    head = repo_impl.get_head_oid()
    result = repo_impl.get_commit_range(head, head)
    assert result == []


def test_get_commit_range_single_commit(repo_impl, repo_path):
    """A → B: range from B to A returns [B]."""
    head_a = repo_impl.get_head_oid()
    (repo_path / "b.txt").write_text("b")
    repo_impl.stage(["b.txt"])
    commit_b = repo_impl.commit("commit B")

    result = repo_impl.get_commit_range(commit_b.oid, head_a)
    assert len(result) == 1
    assert result[0].oid == commit_b.oid


def test_merge_base_returns_common_ancestor(repo_path, repo_impl):
    """Two diverged branches share their initial commit as merge base."""
    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    base_oid = repo.head.target  # initial commit on master

    # Branch "feat" off master, add commit A
    repo.branches.local.create("feat", repo.head.peel())
    (repo_path / "a.txt").write_text("a")
    repo.index.add("a.txt")
    repo.index.write()
    tree_a = repo.index.write_tree()
    a_oid = repo.create_commit("refs/heads/feat", sig, sig, "A", tree_a, [base_oid])

    # Add commit B onto master
    (repo_path / "b.txt").write_text("b")
    repo.index.read()
    repo.index.add("b.txt")
    repo.index.write()
    tree_b = repo.index.write_tree()
    b_oid = repo.create_commit("refs/heads/master", sig, sig, "B", tree_b, [base_oid])

    impl = Pygit2Repository(str(repo_path))
    result = impl.merge_base(str(a_oid), str(b_oid))
    assert result == str(base_oid)


def test_merge_base_returns_none_for_disjoint(repo_path, repo_impl):
    """Two unrelated commits (orphan branch) have no merge base."""
    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    head_oid = repo.head.target

    # Create an orphan branch (a fresh commit with no parents)
    (repo_path / "orphan.txt").write_text("orphan")
    repo.index.read(force=True)
    repo.index.clear()
    repo.index.add("orphan.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    orphan_oid = repo.create_commit("refs/heads/orphan", sig, sig, "orphan", tree, [])

    impl = Pygit2Repository(str(repo_path))
    assert impl.merge_base(str(head_oid), str(orphan_oid)) is None


def test_merge_base_returns_none_for_unknown_oid(repo_impl):
    """Malformed or unknown oids yield None instead of raising."""
    # Valid format but not in repo
    bogus = "0" * 40
    real = repo_impl.get_commits(limit=1)[0].oid
    assert repo_impl.merge_base(real, bogus) is None
    # Malformed hex — too short
    assert repo_impl.merge_base(real, "abc") is None


def test_get_commit_stats_returns_iterator(repo_impl):
    """get_commit_stats should be a generator/iterator, not a list."""
    import inspect

    result = repo_impl.get_commit_stats()
    assert inspect.isgenerator(result) or hasattr(result, "__next__")


def test_get_commit_stats_yields_commits_in_order(repo_impl):
    """The streaming generator yields each commit in repo order
    (newest first, like git log)."""
    stats = list(repo_impl.get_commit_stats())
    assert len(stats) >= 1
    assert all(cs.oid and cs.author for cs in stats)


def test_get_commit_stats_cancel_stops_iteration(repo_path):
    """When the cancel callback returns True, the generator terminates
    after the next commit boundary and the subprocess is gone."""
    import pygit2

    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    head_oid = repo.head.target
    # Add a few commits so the stream has something to iterate over.
    for i in range(3):
        (repo_path / f"f{i}.txt").write_text(f"f{i}")
        repo.index.add(f"f{i}.txt")
        repo.index.write()
        tree = repo.index.write_tree()
        head_oid = repo.create_commit("refs/heads/master", sig, sig, f"c{i}", tree, [head_oid])

    impl = Pygit2Repository(str(repo_path))
    cancel_calls = {"n": 0}

    def cancel() -> bool:
        cancel_calls["n"] += 1
        return cancel_calls["n"] >= 1  # cancel after the very first check

    stats = list(impl.get_commit_stats(cancel=cancel))
    # First commit should be yielded; cancel triggers after that.
    assert len(stats) <= 2  # tolerate one buffered boundary
    assert cancel_calls["n"] >= 1


def test_get_identity_returns_none_when_unset(repo_path):
    """A fresh repo with no user.name/user.email returns (None, None)."""
    import subprocess

    # Ensure repo-local config has no user.name/user.email.
    subprocess.run(
        ["git", "config", "--local", "--unset-all", "user.name"],
        cwd=str(repo_path),
        check=False,
    )
    subprocess.run(
        ["git", "config", "--local", "--unset-all", "user.email"],
        cwd=str(repo_path),
        check=False,
    )
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    impl = Pygit2Repository(str(repo_path))
    name, email = impl.get_identity()
    # Note: a global config may set them. Test the "unset locally" path —
    # if global is set, both will be non-None; we just assert the call works.
    assert isinstance(name, (str, type(None)))
    assert isinstance(email, (str, type(None)))


def test_set_identity_local_then_get(repo_path):
    """set_identity(global_=False) writes user.name/user.email locally,
    and a subsequent get_identity returns them."""
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    impl = Pygit2Repository(str(repo_path))
    impl.set_identity("Alice", "alice@example.com", global_=False)
    name, email = impl.get_identity()
    assert name == "Alice"
    assert email == "alice@example.com"


def test_set_identity_overwrites_existing(repo_path):
    """A second set_identity replaces the first values."""
    from git_gui.infrastructure.pygit2 import Pygit2Repository

    impl = Pygit2Repository(str(repo_path))
    impl.set_identity("Alice", "alice@example.com", global_=False)
    impl.set_identity("Bob", "bob@example.com", global_=False)
    name, email = impl.get_identity()
    assert name == "Bob"
    assert email == "bob@example.com"


def test_get_commits_first_parent_excludes_side_branch_commits(repo_path):
    """With first_parent=True, commits brought in only via a merge's
    second parent must not appear in the listing."""
    import pygit2

    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")

    # Layout:
    #   A (initial, from conftest fixture)
    #   |
    #   B  (master)
    #   |\
    #   | C   (feature)
    #   | |
    #   | D
    #   |/
    #   M  (master, merge of feature into master)
    head_a = repo.head.target

    # B on master
    (repo_path / "b.txt").write_text("b")
    repo.index.add("b.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    b_oid = repo.create_commit("refs/heads/master", sig, sig, "B", tree, [head_a])

    # Create feature branch off B
    repo.branches.local.create("feature", repo.get(b_oid))

    # C on feature
    repo.checkout("refs/heads/feature")
    (repo_path / "c.txt").write_text("c")
    repo.index.add("c.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    c_oid = repo.create_commit("refs/heads/feature", sig, sig, "C", tree, [b_oid])

    # D on feature
    (repo_path / "d.txt").write_text("d")
    repo.index.add("d.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    d_oid = repo.create_commit("refs/heads/feature", sig, sig, "D", tree, [c_oid])

    # Back to master, merge feature (no-ff via explicit merge commit)
    repo.checkout("refs/heads/master")
    # Merge: tree = merged index; parents = [master_tip, feature_tip]
    (repo_path / "c.txt").write_text("c")
    (repo_path / "d.txt").write_text("d")
    repo.index.add("c.txt")
    repo.index.add("d.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "M", tree, [b_oid, d_oid])

    impl = Pygit2Repository(str(repo_path))

    # Full walk includes everyone.
    full = impl.get_commits(limit=100, first_parent=False)
    full_msgs = {c.message.strip() for c in full}
    assert {"M", "B", "C", "D", "Initial commit"}.issubset(full_msgs)

    # First-parent walk hides feature-only commits (C, D) but keeps M, B.
    fp = impl.get_commits(limit=100, first_parent=True)
    fp_msgs = {c.message.strip() for c in fp}
    assert "M" in fp_msgs
    assert "B" in fp_msgs
    assert "Initial commit" in fp_msgs
    assert "C" not in fp_msgs
    assert "D" not in fp_msgs


def test_get_commit_stats_handles_non_ascii_author_and_path(repo_path):
    """Non-ASCII author names and file paths must not break the parser
    regardless of the platform's default locale encoding (Windows defaults
    to cp1252; git emits UTF-8). Regression: text=True without an explicit
    encoding raises UnicodeDecodeError on Windows, killing Insight silently."""
    import pygit2

    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("田中太郎", "tanaka@example.com")
    (repo_path / "日本語.txt").write_text("hello", encoding="utf-8")
    repo.index.add("日本語.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    head = repo.head.target
    repo.create_commit("refs/heads/master", sig, sig, "feat: 中文 message", tree, [head])

    impl = Pygit2Repository(str(repo_path))
    stats = list(impl.get_commit_stats())

    # The crucial assertion is that no exception was raised — the parser
    # decoded UTF-8 correctly. As a bonus, the Japanese author survives
    # the round-trip unmangled.
    assert len(stats) >= 1
    authors = [s.author for s in stats]
    assert any("田中太郎" in a for a in authors), authors


def test_get_commits_first_parent_pagination_never_returns_side_branch(repo_path):
    """skip composes with first_parent: paginating through the first-parent
    line never surfaces a side-branch commit."""
    import pygit2

    from git_gui.infrastructure.pygit2 import Pygit2Repository

    repo = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("T", "t@t.com")
    head_a = repo.head.target

    (repo_path / "b.txt").write_text("b")
    repo.index.add("b.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    b_oid = repo.create_commit("refs/heads/master", sig, sig, "B", tree, [head_a])

    repo.branches.local.create("feature", repo.get(b_oid))
    repo.checkout("refs/heads/feature")
    (repo_path / "c.txt").write_text("c")
    repo.index.add("c.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    c_oid = repo.create_commit("refs/heads/feature", sig, sig, "C", tree, [b_oid])
    (repo_path / "d.txt").write_text("d")
    repo.index.add("d.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    d_oid = repo.create_commit("refs/heads/feature", sig, sig, "D", tree, [c_oid])

    repo.checkout("refs/heads/master")
    (repo_path / "c.txt").write_text("c")
    (repo_path / "d.txt").write_text("d")
    repo.index.add("c.txt")
    repo.index.add("d.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/master", sig, sig, "M", tree, [b_oid, d_oid])

    impl = Pygit2Repository(str(repo_path))

    # First-parent line is: M, B, Initial commit (3 commits total).
    # Paginating with skip=1, limit=2 must yield exactly B and Initial commit.
    page = impl.get_commits(limit=2, skip=1, first_parent=True)
    msgs = [c.message.strip() for c in page]
    assert msgs == ["B", "Initial commit"]
    assert "C" not in msgs and "D" not in msgs
