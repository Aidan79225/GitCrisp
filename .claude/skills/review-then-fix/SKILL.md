---
name: review-then-fix
description: Two-stage review-and-fix loop for GitCrisp changes. Each round runs a correctness review, fixes what it finds, then a code-quality review against Clean Architecture, Domain-Driven Design and Clean Code (short functions, few comments that say why, names that say how), fixes that too, and repeats until a round finds nothing worth fixing. Use this whenever the user asks to review and fix, polish, clean up, harden, iterate on, or make PR-ready a branch, diff, PR or set of files, or asks for reviews "until convergence" or "until it's clean", even when they do not say "skill" or "review".
---

# Review, fix, repeat

The point of this loop is that a change gets two kinds of scrutiny, separately,
from a reader who did not write it. Correctness and quality are reviewed in
different passes because a reviewer hunting bugs skims naming, and a reviewer
hunting naming stops noticing bugs. Fixing after each pass, rather than at the
end, means the quality pass reads code that already works, and the next round's
correctness pass checks that the quality fixes broke nothing.

Arguments, if any, name the target: a PR number, a branch, or paths. With none,
the target is the current branch against `master`, including uncommitted work.

## A round

1. **Correctness review** of the target. Read `references/correctness.md`.
2. **Fix** every must-fix and should-fix finding. Run the gate.
3. **Quality review** of the target as it now stands. Read `references/quality.md`.
4. **Fix** again. Run the gate.

A round converges when both reviews return no must-fix or should-fix findings.
Then write the report. Otherwise start the next round on the updated target.
Stop after four rounds regardless and report what is still open: a loop that
long means the findings are oscillating or the change needs the user.

## Getting an independent read

Spawn a fresh `general-purpose` subagent for each review. Give it the diff (or
the file list and the base ref so it can compute the diff), the path of the
rubric file to read, and the finding format below. Do not give it your own
conclusions, your hypotheses, or the previous round's findings: a reviewer handed
a theory confirms it. Ask it to verify each finding against the code before
reporting it, and to return only the findings list.

If subagents are not available, do the review yourself, but read the rubric
first and write the complete findings list before touching any code. Fixing as
you read anchors the rest of the review on the first thing you saw.

## Finding format

Every finding, from either stage, has these fields:

```
[must-fix | should-fix | nit] path/to/file.py:LINE
Claim: one sentence stating the defect or the rule it breaks.
Why it matters: the input or situation that goes wrong, or the cost to the next reader.
Fix: the concrete change.
```

- **must-fix**: wrong behaviour, a crash, data loss, a broken layer boundary, or
  a change that leaves `master` unreleasable.
- **should-fix**: a real defect or a clear rule violation with a bounded fix.
- **nit**: taste. Fix it if it is a one-liner on a line already being touched;
  otherwise leave it.

Only must-fix and should-fix count toward convergence.

## Fixing

- Fix the finding, not the neighbourhood. A review is not a licence to widen
  the change; something unrelated you notice goes in the report, not the diff.
- If a finding is wrong, say so in the report with the reason, and do not fix
  it. A reviewer can misread code; the fixer is accountable for the change.
- If the same finding comes back after you have fixed it twice in different
  ways, stop and put it to the user. Two reviewers disagreeing is a design
  question, not a bug.
- Keep one logical change per commit, as the project asks. Several findings
  that are one idea share a commit; unrelated ones do not. Commit messages say
  why, and end with the attribution line this session uses.

## The gate

Run after every fix step, before the next review. All four must pass:

```
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy git_gui/domain git_gui/application
```

CI covers only those, so when the change touches `presentation/`, also launch
the app (`uv run python main.py`) or drive the widget in a script and look at
the area that changed. A type error in a widget or a button that opens nothing
passes CI and fails the user.

## Report

Finish with this structure, and nothing after it:

```
## Review loop: <target>

Rounds: N (converged | stopped at cap)

### Round 1
Correctness: X findings (M must, S should, K nit) — fixed: ..., declined: ... (why)
Quality:     X findings (...) — fixed: ..., declined: ... (why)

### Round 2
...

### Still open
- <finding> — <why it was not fixed, or that it needs the user>

### Gate
pytest: N passed · ruff: clean · format: clean · mypy: clean · app launched: yes/no
```
