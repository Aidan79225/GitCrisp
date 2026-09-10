"""What a page owes a caller when an old branch tip is asked for.

Clicking a branch whose tip predates the page pushes it as a walker tip, but
time ordering still puts it past `limit`. `pin_unreachable` appends it anyway
so the caller can find it — and that is a last resort, not the default,
because a pinned commit arrives without its descendants and because it makes
the page longer than the limit the caller asked for.
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


def _old_tip_repo(repo_path):
    """A diverged branch whose tip is older than the newer mainline commits."""
    repo = pygit2.Repository(str(repo_path))
    initial = str(repo.head.target)  # from the fixture, time defaults to "now"
    old_tip = _commit(repo, [initial], "old branch tip", t=1000, branch_ref="refs/heads/ancient")
    c = initial
    for i in range(4):
        c = _commit(repo, [c], f"newer {i}", t=2000 + i)
    repo.set_head("refs/heads/master")
    return Pygit2Repository(str(repo_path)), old_tip


def test_an_old_tip_sorts_past_a_small_page(repo_path):
    """The premise of the rest: the walk alone does not reach it."""
    impl, old_tip = _old_tip_repo(repo_path)

    assert old_tip not in {c.oid for c in impl.get_commits(limit=4)}


def test_pinning_brings_the_tip_back(repo_path):
    impl, old_tip = _old_tip_repo(repo_path)

    result = impl.get_commits(limit=4, extra_tips=[old_tip], pin_unreachable=True)

    assert old_tip in {c.oid for c in result}


def test_a_tip_is_not_pinned_unless_asked_for(repo_path):
    """The default has to stay a plain page. Pinning by default is what drew a
    merged branch as a lane that never merges, and what made a full page look
    like the end of history."""
    impl, old_tip = _old_tip_repo(repo_path)

    result = impl.get_commits(limit=4, extra_tips=[old_tip])

    assert old_tip not in {c.oid for c in result}


def test_a_plain_page_is_never_longer_than_its_limit(repo_path):
    """`len(page) == limit` is how the caller tells a full page from the end
    of history, and how far to skip for the next one. A pinned row silently
    breaking that is what stopped the graph loading any more commits."""
    impl, old_tip = _old_tip_repo(repo_path)

    assert len(impl.get_commits(limit=4, extra_tips=[old_tip])) == 4


def test_a_deeper_page_reaches_the_tip_without_pinning(repo_path):
    """Which is why loading deeper is the first answer and pinning the last:
    at a big enough limit the tip arrives in its own place, with the commits
    that descend from it."""
    impl, old_tip = _old_tip_repo(repo_path)

    assert old_tip in {c.oid for c in impl.get_commits(limit=50, extra_tips=[old_tip])}


def test_get_commits_no_duplicate_when_extra_tip_already_loaded(repo_path):
    repo = pygit2.Repository(str(repo_path))
    initial = str(repo.head.target)
    c2 = _commit(repo, [initial], "c2", t=2000)
    repo.set_head("refs/heads/master")

    impl = Pygit2Repository(str(repo_path))
    result = impl.get_commits(limit=10, extra_tips=[c2], pin_unreachable=True)
    oids = [x.oid for x in result]
    assert oids.count(c2) == 1
