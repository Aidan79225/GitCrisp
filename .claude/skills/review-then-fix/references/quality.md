# Quality review

The code works; the question now is whether the next person can change it
safely. Judge each finding by what it costs a reader, and say that cost in the
finding. A rule applied where it costs nothing is a nit.

## Clean Architecture, as this repository draws it

```
presentation  →  application  →  domain  ←  infrastructure
```

- **Domain** (`domain/entities.py`, `domain/ports.py`) holds data classes and
  `Protocol` interfaces only. No Qt, no pygit2, no subprocess, no logging of
  presentation concerns. An entity that knows how it is displayed, or a port
  that leaks a pygit2 type, is a must-fix.
- **Application** (`application/commands.py`, `application/queries.py`) is thin
  use-case wrappers that delegate to ports. Business decisions that have crept
  in here belong in the domain; Qt types here are a must-fix.
- **Infrastructure** (`infrastructure/pygit2/`) implements the ports.
  `Pygit2Repository` is a composite of focused mixins; a new capability goes in
  the mixin it belongs to, or a new one, not into whichever file was open.
- **Presentation** (`presentation/`) may import application and domain. A widget
  that reaches into `infrastructure` directly, or runs git itself, is a must-fix.
  Widgets talk to the buses (`CommandBus`, `QueryBus`), not to repositories.

A new concept should enter at the layer where it is a concept: a new git
operation is a port and a mixin before it is a button.

## Dependency injection, everywhere

A class receives its collaborators; it does not build them or go and find
them. This is what keeps the layers above testable without patching and lets
`main.py` and `MainWindow` be the only places that know how the app is wired.

- **Constructors take ports and buses.** A widget takes `QueryBus` and
  `CommandBus` (or the one it needs); a use case takes the port it calls; an
  infrastructure class takes the repository path or handle. One that
  constructs a `Pygit2Repository`, a bus, a store, or a subprocess runner
  inside its own body is a should-fix, and a must-fix if it does so in
  `domain/` or `application/`.
- **The composition root wires, nothing else does.** `main.py` builds the
  stores, the session and the window and hands them down; `MainWindow` passes
  what each panel needs and nothing more. A panel that imports a sibling
  panel's dependency to build it itself has moved wiring out of the root.
- **Depend on the Protocol, not the implementation.** Type a parameter as the
  port from `domain/ports.py` so a test can pass a fake. A parameter typed as
  the concrete pygit2 class forces every test through real git.
- **No new module-level singletons.** `get_theme_manager()` and
  `get_avatar_loader()` exist because the theme and the avatar cache are
  process-wide; they are the exceptions, not the pattern. Reaching for a new
  global, a class attribute shared across instances, or a settings read in the
  middle of logic instead of a value passed in is a should-fix.
- **Tests inject, they do not patch.** A test that reaches `patch()` to replace
  a collaborator is telling you the collaborator should have been a parameter.
  Flag the production code, not the test.

## Domain-Driven Design

- **Ubiquitous language.** Names in code match the words a git user says:
  stage, unstage, worktree, stash, amend, cherry-pick. A new name for an old
  idea, or a git word used for something else, is a should-fix.
- **Entities carry meaning, not transport.** A domain type with fields that
  exist only because one widget wanted them, or stringly-typed state where an
  enum exists (`StagingState`, `FileDelta`), is a should-fix.
- **Use cases are verbs.** A command or query named after a screen rather than
  an intent, or one that does three things because one screen needed three, is
  a should-fix.
- **Invariants live with the data.** If the same check is repeated at several
  call sites, the entity or a domain function should own it.

## Clean Code

**Functions are short and do one thing.** Around twenty lines is the ceiling to
aim for; a function that needs a blank line and a comment to separate its
phases is two functions. A `paint()` or `__init__` that lays out a whole widget
is the usual offender: pull each region into a method named for what it builds.

**Names say how; comments say why.** The reader should learn what a function
does from its name and what a variable holds from its name, not from a comment
above it. A comment that restates the code (`# increment counter`) is a
should-fix: delete it. A comment that explains a decision the code cannot show
(why a lock is held here, why this platform needs a special case, which bug
forced this) is the only kind to keep, and it must be true. A stale "why" is
worse than none.

Prefer renaming over commenting. If a block needs a comment to say what it
does, it needs a name, so extract it.

**A value from a closed set is an enum, not a literal.** A string such as
`"staged"` or `"modified"`, a bare integer standing for a mode, or a boolean
pair that really encodes three states, is a should-fix when an enum already
exists for it (`StagingState`, `FileDelta`, `ColorRole`, `ResetMode`) and a
should-fix to introduce one when the same literal appears at more than one
site or is compared against. The enum names the set, lets the type checker
catch a misspelling, and gives the next reader one place to see every member.
Compare against the enum member, never the literal behind it. A literal that
is a measurement or a one-off (a pixel inset, a timeout) is a named constant,
not an enum.

**No dead weight.** Unused imports, parameters nobody passes, a flag that is
always the same value, a branch no caller can reach, a docstring that repeats
the signature. Each is a should-fix because each one is a thing the next reader
has to rule out.

**Duplication.** Two copies of the same six lines will drift. Extract when the
copies are the same idea; leave them when they merely look alike today.

**Errors are not control flow.** Catching `Exception` to pick a default hides
the bug that produced it. Catch what you expect, where you can do something
about it.

**Tests read like the rule they protect.** A test named for the behaviour
(`test_a_failed_reload_does_not_block_the_next_one`) beats one named for the
method. One assertion idea per test. Setup that is longer than the assertion
wants a fixture or a helper.

## Theming and UI

- Colours come from theme tokens (`presentation/theme/tokens.py`) and MD3 roles.
  A hex literal in widget code is a must-fix (QSS templates are the exception).
- Spacing, type scale and elevation follow MD3; a magic pixel value needs a
  named constant that says what it is.
- Any new control gets an accessible name a screen reader can speak.

## What not to flag

- Style that `ruff format` already enforces.
- Line length, import order, quote style.
- A long function that is a flat table of data or a declarative layout with no
  logic, where splitting would scatter one picture across many methods.
- Working code in the diff that merely differs from how you would write it.
  Preference is a nit at most.
