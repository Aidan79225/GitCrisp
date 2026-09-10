# README & Website Feature Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every feature claim in `README.md` and `docs/_layouts/default.html` against the current codebase, fix in place, and produce a structured audit report. Fold in the three known additions from theme PR #55 (softer Light, Custom panel inspection mode, global typography scale).

**Architecture:** Three sequential commits on `docs/feature-audit-2026-05-06`. Task 1 produces the audit report (read-only investigation, no doc edits). Task 2 applies the README fixes derived from the report. Task 3 applies the website fixes. Splitting README and website lets each diff be reviewed independently.

**Tech Stack:** Markdown for the audit report and README; HTML for the website layout (Jekyll-rendered). No code or tests.

**Spec:** `docs/superpowers/specs/2026-05-06-readme-website-audit-design.md`

---

## File Structure

- **Create:** `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md` — the audit report.
- **Modify:** `README.md` — apply audit fixes.
- **Modify:** `docs/_layouts/default.html` — apply audit fixes.
- **Don't touch:** screenshots in `docs/screenshot/`, specs/plans under `docs/superpowers/{specs,plans}/`, any code under `git_gui/` or `tests/`.

---

## Task 1: Audit pass — produce the report

Read every claim in both docs. Verify each against the codebase. Record findings in the audit report.

**Files:**
- Create: `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md`
- Read-only inputs: `README.md`, `docs/_layouts/default.html`, all of `git_gui/`

- [ ] **Step 1: Read both docs end-to-end**

Read `README.md` and `docs/_layouts/default.html` start-to-finish before opening the codebase. The goal is to internalize every claim so you know what to verify.

- [ ] **Step 2: Grep the codebase against the README's claims**

Work through the README sections in order. For each, run targeted greps to confirm the feature exists and behaves as described. Suggested grep targets:

| README section | What to grep for | Where to look |
|---|---|---|
| Commit Graph & History — "Inline search (Ctrl+F)" | `Ctrl+F` / `QShortcut.*F` / `searchInLog` | `git_gui/presentation/widgets/log_panel.py`, `presentation/main_window/` |
| Commit Graph & History — "Auto-refresh" | `RepoChangeDetector`, `applicationStateChanged` | `git_gui/presentation/services/` |
| Working Tree & Staging — "Per-hunk staging" | `stage_hunk`, `unstage_hunk` | `infrastructure/pygit2/stage_ops.py`, `application/commands.py` |
| Working Tree & Staging — "Syntax highlighting via Pygments" | `pygments`, `Lexer` | `git_gui/presentation/widgets/diff_block.py`, theme `make_syntax_formats` |
| Working Tree & Staging — "Word-level intra-line diff" | `word_overlay`, `word_diff` | `git_gui/presentation/widgets/diff_block.py` |
| Working Tree & Staging — "Lazy diff loading" | `ViewportBlockLoader` | `git_gui/presentation/widgets/` |
| Branch Management — "Interactive rebase" | `InteractiveRebaseDialog`, `interactive_rebase` | `dialogs/`, `application/commands.py` |
| Branch Management — "Merge options dialog" | `MergeOptionsDialog`, `merge_analysis` | `dialogs/` |
| Branch Management — "Branches dialog" | `BranchesDialog` | `dialogs/` |
| Branch Management — "Checkout-conflict prompt" | `checkout_conflict`, `hard-reset` | `dialogs/`, `main_window/` |
| Commit Operations — "Cherry-pick / Revert / Reset" | `cherry_pick`, `revert_commit`, `reset_to` | `infrastructure/pygit2/commit_ops.py`, graph context menu |
| Conflict Resolution — "Banner with Abort/Continue" | `state_banner`, `conflict_banner` | `presentation/widgets/diff.py`, `working_tree.py` |
| Tags | `create_tag`, `delete_tag`, `push_tag` | `infrastructure/pygit2/tag_ops.py` |
| Stash | `stash_list`, `stash_pop`, toolbar stash button | `infrastructure/pygit2/stash_ops.py` |
| Remote Operations — "Force push dialog" | `ForcePushDialog`, `force-with-lease` | `dialogs/` |
| Remote Operations — "Delete a remote branch" | `delete_remote_branch`, `--delete` | sidebar context menu |
| Submodule Support — "Click-to-open in diffs" | `submodule_open_requested`, file_path role in diff blocks | `presentation/widgets/diff.py`, `diff_block.py` |
| Multi-Repository — "Two-line repo entries" | `RepoListWidget`, two-line layout | `presentation/widgets/repo_list.py` |
| Multi-Repository — "Persistent state in `~/.gitcrisp/repos.json`" | `repos.json`, `RepoStore` | `infrastructure/repo_store.py` |
| Theming | `ThemeManager`, `View → Appearance`, `theme_dialog.py` | `presentation/theme/`, `dialogs/theme_dialog.py` |
| Insights | `InsightDialog`, per-author stats | `dialogs/insight_dialog.py` |
| Keyboard Shortcuts — F5 / Ctrl+W / Ctrl+1..9 | `QKeySequence`, `Qt.Key_F5`, `Qt.CTRL` | `presentation/main_window/`, menubars |
| Diagnostics — "rotating logger at `~/.gitcrisp/logs/gitcrisp.log`" | `RotatingFileHandler`, `gitcrisp.log` | `git_gui/__main__.py` or `main.py` |
| Architecture tree | actual `git_gui/` directory layout | `ls git_gui/`, `ls git_gui/infrastructure/pygit2/` |
| Requirements — Python 3.13, PySide6 6.11, pygit2 1.19 | `pyproject.toml` or `requirements.txt` | repo root |

For each claim, mark a verdict:
- ✅ accurate — leave alone.
- ⚠️ partially right — note what's off.
- ❌ wrong, missing, or outdated.

- [ ] **Step 3: Grep the codebase against the website's claims**

Work through `docs/_layouts/default.html` similarly:

| Website element | What to verify |
|---|---|
| Hero subtitle (line 16) | each phrase: "visual commit graph", "per-hunk staging", "interactive rebase", "conflict resolution", "branches/remotes/submodules/tags" |
| Feature card "Visual Commit Graph" | inline search, lazy pagination, branch nav |
| Feature card "Per-Hunk Staging" | per-hunk + lazy diff loading |
| Feature card "Branch & Rebase" | merge options dialog, interactive rebase, checkout-conflict reset |
| Feature card "Conflict Resolution" | banner, conflict file indicators, dual-parent graph |
| Feature card "Tags & Stash" | create/delete/push tags, stash via context menu |
| Feature card "Remote Operations" | force push dialog, remotes CRUD |
| Feature card "Submodule Support" | submodule dialog, click-to-open in diffs, HEAD divergence |
| Feature card "Multi-Repository" | two-line entries, drag-drop, Ctrl+W, Ctrl+1..9 |
| Feature card "Theming & Insights" | light/dark + typography scale + per-author commit stats |
| Architecture layer diagram | Domain / Application / Infrastructure / Presentation labels |
| Footer | GitHub link, MIT license, releases link |

- [ ] **Step 4: Verify the architecture tree in `README.md:107-151`**

The current tree lists ten `_ops` mixin modules under `infrastructure/pygit2/`. Confirm by listing the directory:

Run: `rtk ls git_gui/infrastructure/pygit2/`

Cross-reference each listed file with the README's tree comment. Mark ❌ for any that differ.

- [ ] **Step 5: Verify the keyboard shortcuts table**

For each row in the README's shortcuts table (F5 / Ctrl+F / Ctrl+W / Ctrl+1..9), grep for the binding in the codebase:

```
rtk grep -n "Key_F5\|Ctrl+F\|Ctrl+W\|Key_1\|Key_2\|Key_3" git_gui/presentation/
```

Confirm each shortcut is wired to its claimed action.

- [ ] **Step 6: Identify stale screenshots**

Compare `docs/screenshot/basic-view.png`, `theme-dialog.png`, `branches-dialog.png`, `insight-dialog.png` mentally against current UI. The Light theme softening in PR #55 is the primary trigger for staleness; the Custom panel layout has also shifted.

For each screenshot, write a short "Re-capture needed: …" entry in the audit report's Re-capture section, with the recommended app state for the new shot. Don't re-capture them.

- [ ] **Step 7: Write the audit report**

Create `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md`. Use this structure:

```markdown
# README & website audit — 2026-05-06

Generated by walking each claim in `README.md` and
`docs/_layouts/default.html` against the current codebase.

## README.md

| Section | Claim | Verdict | Action |
|---|---|---|---|
| Commit Graph | "Lane-based visual graph with topological + time sort" | ✅ | none |
| Commit Graph | "Inline search (Ctrl+F) — search commit messages, authors, hashes, and dates" | (your verdict) | (your action) |
| ... | ... | ... | ... |

## docs/_layouts/default.html

| Section | Claim | Verdict | Action |
|---|---|---|---|
| Hero | "Visual commit graph, per-hunk staging, interactive rebase, conflict resolution..." | (verdict) | (action) |
| Feature card: Visual Commit Graph | "Lane-based graph with lazy pagination, inline search (Ctrl+F)..." | (verdict) | (action) |
| ... | ... | ... | ... |

## Re-capture needed (screenshots)

- `docs/screenshot/basic-view.png` — Light theme surface color shifted
  in PR #55. Re-capture: open a repo with several commits, switch to
  Light via View → Appearance, capture the main window.
- `docs/screenshot/theme-dialog.png` — Custom panel layout changed
  (always-expandable, hex codes pre-filled). Re-capture with Light
  active and the Theme dialog open on the Custom radio.
- (any others you flag during the audit)

## Known additions to fold in (from theme PR #55)

- **Light theme is primary-tinted.** Surfaces are no longer pure white.
- **Custom panel inspection.** Light/Dark/System users can open the
  Theme dialog → Custom radio to expand sections and read each token's
  hex code without entering edit mode.
- **Typography scale is global.** The slider's effect persists across
  restarts in any mode (System/Light/Dark/Custom), driven by the
  `typography_scale` setting.

## Possible follow-ups (out of scope for this PR)

- (any code-level issues found during the audit, with one-line description)
```

Fill in the verdict and action columns for every README section and website element. Aim for one row per atomic claim (don't combine multiple claims into one row — granularity makes the diff review easier later).

- [ ] **Step 8: Commit the audit report**

```bash
rtk git add docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md
rtk git commit -m "$(cat <<'EOF'
docs(audit): inventory pass — generate audit report

Read every claim in README.md and docs/_layouts/default.html, verify
each against the current codebase, and record findings in
docs/superpowers/follow-ups/. Identifies which README sections and
website elements need fixing in subsequent commits, plus stale
screenshots that need re-capture in a follow-up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Apply README fixes

Now apply every ❌ and ⚠️ entry from the audit report to `README.md`. Also fold in the three theme-PR additions documented in the report's "Known additions to fold in" section.

**Files:**
- Modify: `README.md`
- Read-only input: `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md`

- [ ] **Step 1: Open the audit report and the README side-by-side**

Walk through the audit report's `## README.md` table top-to-bottom. For each row with verdict ⚠️ or ❌, locate the corresponding line in `README.md` and apply the action specified in the table.

- [ ] **Step 2: Fold in theme-PR additions**

In the **Theming** section of the README (around line 83-86), apply these edits:

Find:
```markdown
### Theming
- Light and dark themes selectable from **`View → Appearance...`**
- Custom typography scale (snaps to 10% steps) for the entire UI
- Live preview, no restart needed
```

Replace with:
```markdown
### Theming
- Light and dark themes selectable from **`View → Appearance...`** — Light uses a softer primary-tinted surface palette; Dark stays on the deeper Material 3 baseline.
- **Inspection mode** — open the Theme dialog and click the Custom radio in any mode to expand each section (Brand, Surface, Diff, etc.) and read every token's hex code. Individual swatch clicks are no-ops outside Custom; toggling the radio between Light / Dark / System refreshes the swatches live.
- **Custom typography scale** (snaps to 10% steps) — drag the slider in any mode, click Apply, and the new scale persists across restarts via `settings.typography_scale`. Works in System / Light / Dark / Custom.
- Live preview, no restart needed
```

- [ ] **Step 3: Apply remaining audit fixes**

Walk through every other ⚠️/❌ row in the audit report's README table. Apply each fix in place. If a row says "actual count is N mixins, fix" and the README says "ten mixin modules", change "ten" to "N" (or whatever the verified count is).

- [ ] **Step 4: Spot-check the rendered Markdown**

Open `README.md` in a Markdown preview (or `cat` it) and confirm:
- Section headings render as expected.
- Tables (like the keyboard shortcuts table) are still well-formed.
- Code blocks (Architecture tree, Getting Started) have matching backticks.
- Internal links (if any) still resolve.

If any structural issue surfaces, fix it now.

- [ ] **Step 5: Commit**

```bash
rtk git add README.md
rtk git commit -m "$(cat <<'EOF'
docs(readme): apply audit fixes

Apply every ⚠️/❌ finding from the 2026-05-06 audit report. Fold in
the theme PR #55 additions: Light theme is primary-tinted; Custom
panel works as an inspection mode for hex-code lookup in any
non-Custom mode; typography scale persists globally via
settings.typography_scale.

See docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md
for the full list of changes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Apply website fixes

Apply the audit's website findings to `docs/_layouts/default.html`. Fold in the same theme-PR additions on the website side.

**Files:**
- Modify: `docs/_layouts/default.html`
- Read-only input: `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md`

- [ ] **Step 1: Walk the audit report's website table**

Open the audit report's `## docs/_layouts/default.html` section. For each ⚠️/❌ row, locate the relevant element in the HTML and apply the action.

- [ ] **Step 2: Update the "Theming & Insights" feature card**

The card currently reads:

```html
<div class="feature-card">
  <div class="feature-icon">&#x1F3A8;</div>
  <h3>Theming &amp; Insights</h3>
  <p>Light and dark themes with a custom typography scale, plus per-author commit stats over a configurable date range.</p>
</div>
```

Replace the `<p>…</p>` with:

```html
  <p>Softer primary-tinted Light theme and a Material 3 Dark, plus a global typography scale that persists across restarts. Custom panel doubles as an inspection tool — open it in any mode to read every token's hex code. Per-author commit stats round out the theming pair.</p>
```

The card title stays "Theming & Insights" — it's still a fair grouping.

- [ ] **Step 3: Update the hero subtitle if any verified phrase changed**

The hero subtitle (line 16) reads:

```html
<p class="subtitle">Visual commit graph, per-hunk staging, interactive rebase, conflict resolution, and full management dialogs for branches, remotes, submodules, and tags &mdash; built with Python and Qt.</p>
```

If the audit verdict on this line is ✅ for every clause, leave it alone. If a verdict was ⚠️/❌, edit accordingly.

- [ ] **Step 4: Apply remaining audit fixes**

Walk every other ⚠️/❌ row in the website table. Apply each in place.

- [ ] **Step 5: Spot-check the HTML**

Visually scan the file end-to-end. Confirm:
- All `<section>` blocks open and close.
- HTML entities (`&mdash;`, `&middot;`, `&#x1F4CA;`) are preserved.
- Jekyll Liquid tags (`{{ '...' | relative_url }}`) are intact.
- Indentation and quote style match the rest of the file.

If you have a way to render it (Jekyll serve or just open the file in a browser), do a quick visual check on the feature card text wrapping.

- [ ] **Step 6: Commit**

```bash
rtk git add docs/_layouts/default.html
rtk git commit -m "$(cat <<'EOF'
docs(website): apply audit fixes

Apply every ⚠️/❌ finding from the 2026-05-06 audit report to the
Jekyll layout. Theming & Insights feature card now mentions the
softer Light surface palette, the Custom panel inspection tool, and
the global typography scale.

See docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Final sanity check

Quick automated + manual sweep before pushing.

**Files:** none modified.

- [ ] **Step 1: Run the test suite**

Run: `rtk uv run pytest tests/ -q`

Expected: all PASSED. No code was changed in this PR; this is a sanity check that nothing leaked outside the docs surface.

- [ ] **Step 2: Diff the branch against master**

Run: `rtk git diff master..HEAD --stat`

Expected: only three files appear:
- `docs/superpowers/specs/2026-05-06-readme-website-audit-design.md` (added)
- `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md` (added)
- `README.md` (modified)
- `docs/_layouts/default.html` (modified)

If anything else appears, investigate.

- [ ] **Step 3: Read the README and website edits one more time**

Open both files and read them top-to-bottom. The goal is to catch any rough edges from the table-driven editing — sentences that flow oddly, lists that lost a parallel structure, etc.

Apply small touch-ups inline if needed; commit them as a single fixup at the end:

```bash
rtk git add README.md docs/_layouts/default.html
rtk git commit -m "$(cat <<'EOF'
docs(readme,website): tighten language after audit pass

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Skip this commit if no touch-ups are needed.)

---

## Self-Review

**Spec coverage:**
- Audit method (locate, verify, verdict, record) → Task 1 Steps 2–6. ✅
- Audit covers every README section and website element → Task 1 Steps 2 + 3 explicitly enumerate them. ✅
- Audit does NOT touch code → Task 1 is read-only on the codebase. ✅
- Audit report structure → Task 1 Step 7 includes the template. ✅
- Three theme-PR additions folded in → Task 2 Step 2 (README) and Task 3 Step 2 (website). ✅
- README fixes in place → Task 2. ✅
- Website fixes in place → Task 3. ✅
- Branch + commit strategy (3 commits, single PR) → matches Tasks 1, 2, 3. Task 4 is an optional fixup. ✅
- Stale screenshots flagged but not re-captured → Task 1 Step 6. ✅
- Verification (pytest sanity, manual diff check) → Task 4. ✅

**Placeholder scan:** none — every step has the actual command or content. The audit report's table rows are intentionally placeholder-shaped (`(your verdict)`) because the auditor fills them in; that's a content-driven gap, not a planning gap.

**Type/method consistency:** N/A — this is documentation work, no types or methods.
