"""get_commits must always include `extra_tips` in its result, even when the
tip's commit sorts beyond `limit` in the topological/time-ordered walk.

Regression: clicking an older branch (whose tip predates many newer mainline
commits) failed to locate/scroll to it because pushing the tip as a walker tip
does not guarantee inclusion once `limit` truncates the newest N commits.
"""

import pygit2

from git_gui.infrastructure.pygit2 import Pygit2Repository


def _commit(repo, parents, message, t, branch_ref=None):
    """Create a commit at time `t` (seconds). Returns its hex oid."""
    sig = pygit2.Signature("Test User", "test@example.com", int(t), 0)
    tree = repo.index.write_tree()
    ref = branch_ref if branch_ref is not None else "refs/heads/master"
    oid = repo.create_commit(ref, sig, sig, message, tree, list(parents))
    return str(oid)


def test_get_commits_includes_old_extra_tip_beyond_limit(repo_path):
    repo = pygit2.Repository(str(repo_path))
    initial = str(repo.head.target)  # from the fixture, time defaults to "now"

    # A diverged branch whose tip is OLDER than the newer mainline commits.
    old_tip = _commit(repo, [initial], "old branch tip", t=1000, branch_ref="refs/heads/ancient")

    # Several newer commits on master (each newer than old_tip), so the old tip
    # sorts beyond a small limit in time-descending order.
    c = initial
    for i in range(4):
        c = _commit(repo, [c], f"newer {i}", t=2000 + i)
    repo.set_head("refs/heads/master")

    impl = Pygit2Repository(str(repo_path))

    # Sanity: with a small limit and no extra tip, the old tip is NOT loaded.
    base = impl.get_commits(limit=4)
    assert old_tip not in {x.oid for x in base}

    # With the tip as an extra walker tip, it MUST be present regardless of limit.
    result = impl.get_commits(limit=4, extra_tips=[old_tip])
    assert old_tip in {x.oid for x in result}


def test_get_commits_no_duplicate_when_extra_tip_already_loaded(repo_path):
    repo = pygit2.Repository(str(repo_path))
    initial = str(repo.head.target)
    c2 = _commit(repo, [initial], "c2", t=2000)
    repo.set_head("refs/heads/master")

    impl = Pygit2Repository(str(repo_path))
    result = impl.get_commits(limit=10, extra_tips=[c2])
    oids = [x.oid for x in result]
    assert oids.count(c2) == 1
