# Display timestamps in the user's local timezone

## Context

Commit, stash, and tag timestamps are constructed in three places in
`infrastructure/pygit2/` with `tz=timezone.utc`. Render sites
(`commit_detail.py`, `graph_model.py`, sidebar) call `strftime()` on
those tz-aware datetimes, which formats in the datetime's tz — so
the user sees UTC, not local time.

The Insight dialog is unaffected because it parses
`git log --format=%aI` which already includes the author's local
timezone offset.

## Fix

Append `.astimezone()` to each construction call. Same instant in
time, local-tz-aware datetime, all downstream `strftime()` calls
render in the user's local timezone with no presentation changes.

```python
# infrastructure/pygit2/_helpers.py:39
ts = datetime.fromtimestamp(c.commit_time, tz=timezone.utc).astimezone()

# infrastructure/pygit2/stash_ops.py:28
ts = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc).astimezone()

# infrastructure/pygit2/tag_ops.py:35
ts = (datetime.fromtimestamp(target.tagger.time, tz=timezone.utc).astimezone()
      if target.tagger else None)
```

## Scope

- **Modify:** `git_gui/infrastructure/pygit2/_helpers.py`,
  `stash_ops.py`, `tag_ops.py` — three single-line additions.
- **Add test:** `tests/infrastructure/pygit2/test_helpers.py` (or the
  appropriate existing test file) asserting the converted datetime's
  `tzinfo` matches the local tz.
- **Don't touch:** any presentation-layer rendering code, the
  Insight dialog flow, `graph.py:424` (`datetime.now()` synthetic
  working-tree row stays naive).

## What stays the same

- Tests that build `Commit` entities with naive `datetime.now()` for
  fixtures — naive datetimes still format with `strftime()`, no
  comparisons are made between tz-aware infrastructure-built
  datetimes and naive test fixtures, so they're unaffected.
- The Commit entity's `timestamp` field stays a `datetime` (no type
  change). The only difference is its `tzinfo` is now the local tz
  instead of UTC.

## Verification

- `uv run pytest tests/infrastructure/pygit2/ -v` — new test plus
  existing infrastructure tests pass.
- `uv run pytest tests/ -q` — full suite green.
- Manual: open a commit, inspect the timestamp on the commit detail
  panel. It should match the user's wall-clock time at commit
  authorship (give or take wall-clock vs author-local nuance, but
  no longer 8 hours off in CST/CET zones).
