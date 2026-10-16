# Correctness review

You are looking for ways the change behaves wrongly, not for ways it could be
written better. Read the diff, then read enough of the surrounding code to know
what the changed lines are actually called with. Every finding must name the
input or situation that goes wrong; a finding you cannot attach a scenario to
is a guess, and guesses go in as nits or not at all.

## Where this codebase breaks

**Threads.** Widgets load data on `threading.Thread` workers and hand results
back through Qt signals. A worker that touches a widget directly, a signal
object that is garbage-collected before it fires, or a result applied after the
user switched repositories are all real bugs here. Check what happens when the
reload is triggered twice before the first returns.

**Qt roles and flags.** Models answer `data()` by role; a role that returns
`None` where the view expects a value silently draws nothing. A flag that is
missing silently disables a behaviour. Check the check-state, user-role and
flags paths for every new model or delegate.

**Paint paths.** `paint()` runs on every frame. One that raises takes the whole
view down, and one that allocates per row stalls scrolling on long lists.

**Git on disk.** `infrastructure/pygit2/` mixes pygit2 calls with `subprocess`
git. Check: unborn HEAD, detached HEAD, a repository with no remote, paths with
spaces, a worktree whose directory was deleted, a conflicted index, a bare
repository. The e2e tests in `tests/e2e/` run on a real repository; a change to
infrastructure without one is under-tested.

**Error paths.** A `try/except Exception` that swallows and continues hides the
failure from the user and the log. Check that failures reach the operations log
or a dialog, and that the widget returns to a usable state afterwards.

**Settings and state.** Anything written under `Path.home()` or through
`QSettings` runs in the user's real profile. Check that tests redirect it
(`tests/conftest.py` does for the suite) and that a failed write does not take
the app down.

**Platform.** The app ships for macOS, Windows and Linux. A shortcut spelling,
a font name, a path separator, or a style metric that is right on the author's
machine is a bug on another. Fusion on Linux and the Windows style lay rows out
differently from macOS.

## Tests

- A behaviour change without a test that fails on the old code is a should-fix.
- A test that passes for the wrong reason (mocks that return what the code
  under test asserts, a widget never shown so nothing is painted) is a must-fix,
  because it will keep passing when the code breaks.
- Tests must stay out of the developer's real home and settings.

## Releasability

`master` must stay releasable on every commit. A new entry point that opens
something unfinished, a menu item that raises, or a layer that imports
`presentation` from `domain` or `application` is a must-fix, whatever else is
right about the change.
