# Follow-up: What review round 3 left open

**Date:** 2026-10-27
**Status:** Not planned as standalone tasks. Pick opportunistically, or turn a group into a spec.

## Context

Round 3 of the code-review loop reviewed the 163 round-2 fix commits that shipped in v1.3.0 without a review of their own. Two independent verifiers checked every finding, and nothing below was fixed in this round.

The round fixed everything that was confirmed in scope and estimated at 30 minutes or less:

- 62 correctness defects, each with a regression test. The review ran three passes, and each pass also checked the previous pass's fixes.
- 60 quality changes.
- One test fixture that crashed the interpreter. It fed mock data through typed Qt signals.

What is left falls into five groups:

- Decisions only the maintainer can make.
- Defects reviewers found in code the round did not touch.
- Refactors estimated at over 30 minutes.
- Smaller follow-ups the fixers noticed in passing.
- Findings the two verifiers disagreed on.

## Needs a decision

1. **Conflicted hunks** still show a stage checkbox and a discard button that do nothing. Hide them, or route them to whole-file staging?
2. **Push remote in fork setups.** Pull follows the branch's upstream; push still targets `origin`. Supporting `pushRemote` / `pushDefault` needs a new port.
3. **Cancelling an interactive rebase** midway: leave the repo REBASING, or abort? Today the rebase runs in the remote-op slot, which shows Cancel, but nothing can stop it.
4. **Localised git messages.** Run worktree commands under `LC_ALL=C` so the dirty and locked messages still parse?
5. **Graph toolbar overflow.** It is not clipped at the default width, but nothing handles a narrower one.

## Defects found outside the round's scope

Each was reported by a reviewer, in code the round-2 commits did not change. None is verified to the round's standard.

- **Tests share one settings file.** The autouse `_isolated_settings` fixtures in `test_app_settings.py`, `test_preferences_dialog.py` and `test_create_tag_dialog.py` call `QSettings.setPath(tmp_path)` and never restore it. Every later test reads and writes the last such test's ini file.
- **A later click loses to an earlier one.** Selecting an already-loaded commit in the graph does not clear an earlier click's `_pending_scroll_oid`, so the earlier click's load lands later and overrides the newer selection.
- **Paging can skip commits.** The graph's `_load_more` worker reads `self._extra_tips` when it runs rather than capturing it, so a branch click in between pages the walk with different tips than the list being extended.
- **A bad text scale stops the launch.** A hand-edited `settings.json` with a non-numeric `typography_scale` raises in `ThemeManager.__init__` (also `theme_dialog.py`).
- **Add Worktree blocks on a dead share.** The dialog stats the typed location on the UI thread on every keystroke, twice; a UNC path to an unreachable server blocks each keystroke for the SMB timeout.
- **Clone can write outside its location.** The Clone dialog joins the folder name to the location unchecked, so `..\x` or `D:\x` clones outside the chosen location.
- **Clone dialogs are never freed.** Each one is parented to the right panel and never deleted, so every dialog and its signals live as long as the window.
- **A failed diff map leaves skeletons forever.** When the diff-map query raises, every file block in the commit view and the working-tree view stays a loading skeleton, with only a log line.
- **A worker can destroy its signals object on the wrong thread.** The diff panes replace their load-signals object while its worker still runs. The worker's exit can then drop the last reference on its own thread. This is a possible crash and was not reproduced.
- **A theme change during a long render mixes old text in.** A re-render while a hunk of more than 100 lines is still rendering in chunks lets the old slices keep inserting into the cleared editor.
- **Delete tag asks before checking the remote slot.** "Local + remote" checks whether a remote operation is running only after the user confirms, against the rule that a flow which asks first checks first.
- **Ctrl+W on a linked worktree lands on the wrong repo.** It goes to the first open repo, not the worktree's owner.
- **A worktree row can list itself.** A linked worktree opened as its own OPEN row is listed as a child of itself.
- **Cancel cannot stop the tag refresh.** After a fetch or a tag push, `git ls-remote` runs outside the cancellable runner, so Cancel logs "cancelling..." and stops nothing.
- **Rebase blocks the window.** Rebase onto a branch runs `git rebase` synchronously on the GUI thread.
- **Setting an upstream can pick a local branch.** When the repo holds a local branch named like the remote-tracking one, for example a local `origin/master` beside `refs/remotes/origin/master`, `set_branch_upstream('master', 'origin/master')` records the local branch as the upstream. The round-3 Pull fixer found this while writing a test. It is not verified.
- **Removing the worktree on screen may fail on Windows.** The window's change detector watches the worktree's gitdir, and the app does not stop it before running `git worktree remove`. A test that removed a watched worktree failed once under load with exit status 255 and "access denied" from the watcher. The test now stops the watch first; the app path is not verified.
- **A late blame failure wipes the current blame.** The blame pane's `_on_failed` has no staleness check, unlike `_on_loaded`, so a slow failure for a revision the user has left clears the newer blame.

## Refactors deferred (over 30 minutes)

Each was confirmed by both verifiers as worth doing, but it was too large for the round or needed changes across several owners.

- **Clone behind a port.** Move `CloneProgress` and `CloneCancelled` to the domain and clone behind an application port. The Clone dialog is the last presentation module that imports infrastructure. About 75 minutes.
- **One cancellable remote branch delete.** Deleting a branch on a remote is implemented twice, in `remote_ops.py` and `branch_ops.py`, and only one of them is cancellable. About 45 minutes.
- **Worktree removal refusals as domain outcomes.** Name them in the domain and keep one override rule. Today presentation dispatches on infrastructure exception class names in two places, with three different force prompts. About 60 minutes.
- **Add Worktree's location rules behind the port.** What `git worktree add` accepts as a location is encoded and probed on disk in the dialog. About 45 minutes.
- **The squash rule in the domain.** Move interactive rebase's "nothing to squash into" rule next to `RebaseAction`. About 20 minutes, deferred with the dialog work above.
- **One owner for theme saves.** Saving appearance and the custom theme as one unit is split between `ThemeManager` and the theme dialog. About 40 minutes.
- **`LogPanel.report_error`.** Replace the expand-then-`log_error` pair repeated at about 47 sites and four wrappers. About 50 minutes.
- **Worktree ownership as window state.** Which repo owns the worktree on screen is kept in the repo-list widget, and the lifecycle rules read it back. About 45 minutes.
- **One background-worker helper.** Move `widgets/background.py` to services and migrate the remaining ~13 widgets that start `threading.Thread` by hand. About 90 minutes.
- **File-history membership as a query.** Which commits a file's history can hold is decided in the graph widget. About 75 minutes.
- **A typed ref badge.** Use a value type for a ref badge's kind instead of the `tag:` prefix and the `HEAD` sentinel. About 90 minutes.
- **One numbering helper for hunk lines.** Hunk line numbering is implemented once per renderer, so the marker fix had to land in both. About 20 minutes.
- **One save path for the repo list.** The list persists the store itself, alongside the window's save-and-report path. About 30 minutes.
- **Shared test builders.** A private `_git()` helper is copied into about 30 test modules, and real-repo, real-window and held-session builders are pasted into several new test files. About 45 minutes each.

## Smaller follow-ups the fixers noted

- **One tolerant remote listing.** The graph, Pull and the Remote Branches dialog each fall back on their own when `list_remotes` fails, and each reports it differently.
- **One identity check.** `WorkingTreeWidget._ensure_identity` is a second copy of `identity_dialog.ensure_identity`.
- **Pull without naming the remote.** When the branch has an upstream, Pull could run `git pull --rebase` with no arguments. This needs a port variant.
- **A stale Branches dialog.** An open Branches dialog keeps listing the previous repo's branches after a switch. Its Checkout is guarded, so it cannot act on the wrong repo.
- **A clearer remote delete prompt.** The prompt names `remote/branch` joined. Naming the two parts would read better when a remote's name contains '/'.

## Findings the verifiers disagreed on

These were left unchanged.

- **Repo-list maintenance in `main.py`.** The startup choice and the pruning of gone repos live in `main.py` against the concrete store. One verifier wanted an application use case; the other pointed out that `application/` holds only thin wrappers by design.
- **The log panel's row writers.** The two routines are near-identical. One verifier wanted them merged; the other found their essential step differs, insertHtml against formatted text that the recolouring reads.
- **The theme dialog's fill and repaint.** The pair appears at three sites and has a one-line alias.
- **The repo list's `show_open_repo_from` setter.** One verifier objected to its name and default; the other found the setter is always called before the first reload.
- **The Insight range math.** It lives in a dialog method, so its tests build a dialog. One verifier wanted a pure function; the other said the ranges are UI captions, not a domain concept.
