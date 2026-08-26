# CLAUDE.md — project conventions for Claude Code

## Communication

When the user writes a message, rewrite it into correct English (with proper grammar and word choice) before responding to the request — regardless of whether the original is in English or another language. Show the corrected/translated version as a blockquote at the start of your response.

## Architecture

Follow **Clean Architecture** principles:
- **Domain** (`domain/entities.py`, `domain/ports.py`): pure data classes and protocol interfaces — no framework dependencies
- **Application** (`application/commands.py`, `application/queries.py`): thin use-case wrappers that delegate to ports
- **Infrastructure** (`infrastructure/pygit2/`): concrete implementations of ports (pygit2, subprocess) — `Pygit2Repository` is a composite of ten focused mixin modules (`branch_ops`, `commit_ops`, `diff_ops`, etc.)
- **Presentation** (`presentation/`): PySide6 widgets, bus wiring, main window

Dependencies point inward: presentation → application → domain ← infrastructure. Never import presentation or infrastructure from domain/application.

## UI / Theming

Follow **Material Design 3** (MD3) conventions:
- Use the existing theme token system (`presentation/theme/tokens.py`) for all colors
- Refer to MD3 color roles (primary, on_surface, surface, outline, etc.)
- New UI components should use MD3 spacing, typography scale, and elevation patterns
- All colors must come from theme tokens — no hard-coded hex values in widget code (QSS templates in `qss_template.py` are the exception)

## Python execution

Always use `uv run` to execute all Python operations (scripts, pytest, etc.). Never use bare `python` or `pytest`.

Examples:
- Tests: `uv run pytest tests/ -v`
- Scripts: `uv run python main.py`
- One-liners: `uv run python -c "..."`

## Pull requests

**Estimate the diff before writing code.** If a feature will exceed ~400 changed
lines, say so while discussing the approach and propose a split — don't hand over
a 700-line PR and leave the reader to find the seams.

**Split a feature along the architecture layer boundary**, into sequential PRs
merged in order:

1. **Data** — `domain/ports.py`, `application/`, `infrastructure/`, and their tests.
   No UI change. Lands a capability nothing calls yet; that is expected and fine.
2. **Display** — `presentation/models/` and `presentation/widgets/`. This is where
   the real review effort belongs, so it gets a PR to itself.
3. **Wiring** — entry points, context menus, `main_window/` signal connections, README.

**Every merge must leave `master` releasable.** The Release workflow could run on
any commit and has to produce a working app, so a PR is not done when CI is green:
CI runs tests, ruff, and mypy over `domain` + `application` only — none of which
notice that the app fails to launch, that `presentation` has a type error, or that
a new button opens nothing. Launch it and exercise the area you touched before
opening the PR.

A split feature may sit on `master` half-built, but only where the user cannot
reach it. That is what fixes the layer order above: data lands invisible, display
lands unreachable, wiring is what makes the feature reachable — so wiring lands
last and in one piece. Never ship an entry point ahead of what it opens, and never
split the wiring layer in a way that leaves a dead menu item or a button that
raises.

Each PR must stand on its own: green tests, lint clean, and a body that explains
why, not just what. A layer that turns out to be trivial can fold into its
neighbour — three PRs is the shape, not a quota.

Within a PR, keep one logical change per commit and split commits along the same
boundary. Two unrelated changes never share a PR, however small one of them is.

Development happens on a single designated branch that is reset from the default
branch after each merge, so a split is serialized: the next PR starts once the
previous one lands.

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (60-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk go test             # Go test failures only (90%)
rtk jest                # Jest failures only (99.5%)
rtk vitest              # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk pytest              # Python test failures only (90%)
rtk rake test           # Ruby test failures only (90%)
rtk rspec               # RSpec test failures only (60%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%)
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->