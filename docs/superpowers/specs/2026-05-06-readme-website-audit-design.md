# README & website feature audit

## Context

`README.md` and `docs/_layouts/default.html` are the public face of
GitCrisp. They've grown by accretion as features landed, with the
last broad update at commit `fb59dab docs: update README and website
with new features`. Several things have shifted since:

- The theme PR (#55) added a softer primary-tinted Light theme,
  Custom-panel inspection mode (always-expandable sections, active-
  theme pre-fill, live radio refresh), and a global typography scale
  setting. None of this is reflected in either doc.
- The architecture tree in `README.md:107-151` lists module names
  and a `Pygit2Repository` "ten mixin" composite that may or may not
  match the current `infrastructure/pygit2/` directory.
- The keyboard shortcuts table claims F5 / Ctrl+F / Ctrl+W / Ctrl+1..9.
  These need to be verified against actual bindings.
- `docs/screenshot/basic-view.png` and `theme-dialog.png` were
  captured before Light surfaces shifted to `#eff5fd`. Visually
  stale.

The fix is a structured audit: read every claim in both docs, verify
it against the codebase, and apply fixes in place. The work product
is a single PR plus an audit report that summarizes what shifted, so
the diff is reviewable and the report serves as a future reference.

## Scope

- **Modify in place:** `README.md`, `docs/_layouts/default.html`.
- **Create:** `docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md`
  — the audit report.
- **Don't touch:** screenshots (will be flagged for re-capture, not
  re-captured), specs/plans under `docs/superpowers/{specs,plans}/`,
  or any code.

## Audit method

For each claim in `README.md` and `docs/_layouts/default.html`:

1. **Locate.** Grep the codebase for the class, method, menu string,
   keyboard shortcut, or directory path the claim references.
2. **Verify.** Read the relevant code and confirm the behavior
   matches the doc.
3. **Verdict.** One of:
   - ✅ accurate — leave the claim alone.
   - ⚠️ partially right — note the discrepancy, fix it.
   - ❌ wrong / missing / out-of-date — fix in place.
4. **Record.** Add a row to the audit report.

The audit covers:

- Every section header and bullet in `README.md` (features by
  category, keyboard shortcuts table, architecture tree,
  requirements, Getting Started, Running Tests).
- Every section in `docs/_layouts/default.html` (hero blurb, all
  nine feature cards, screenshot captions, architecture layer
  diagram, footer links).

The audit does **not**:

- Exhaustively scan the codebase for undocumented features. README
  is a curated inventory, not a complete manual. Substantial
  undocumented features (full menus, dialogs) that surface during
  the audit get flagged; minor utilities don't.
- Touch any code. Findings about code-level issues (e.g., a
  promised behavior that's actually broken) are recorded in the
  audit report's "Possible follow-ups" section, not fixed.

## Known additions to fold in

These changes from PR #55 must appear in both docs after the audit:

1. **Light theme is primary-tinted.** Surfaces are no longer pure
   white. The README's Theming section currently says "Light and
   dark themes selectable from `View → Appearance...`" — this stays
   accurate but should mention the soft-blue character of the Light
   theme. The website's Theming card needs a similar tweak.
2. **Custom panel inspection mode.** A new bullet point under
   Theming in the README, and a sentence on the website's Theming
   card, explaining that Light/Dark/System mode users can open the
   Theme dialog → Custom radio to expand sections and read each
   token's hex code without entering edit mode. Clicking individual
   swatches outside Custom is a no-op; toggling the radio Live-
   refreshes the swatches.
3. **Typography scale is global.** README currently says "Custom
   typography scale (snaps to 10% steps) for the entire UI" — this
   is correct in spirit but pre-dates global persistence. Update to
   mention that the slider's effect persists across restarts in
   any mode (System/Light/Dark/Custom), driven by the
   `typography_scale` setting.

## Deliverable

### Audit report (`docs/superpowers/follow-ups/2026-05-06-readme-website-audit.md`)

Structure:

```markdown
# README & website audit — 2026-05-06

## README.md

| Section | Claim | Verdict | Action |
|---|---|---|---|
| Commit Graph | "Lane-based visual graph..." | ✅ | none |
| Working Tree | "Per-hunk staging..." | ✅ | none |
| Architecture | "Pygit2Repository — composite of N mixin modules" | (verify N matches actual count in `infrastructure/pygit2/`) | … |
| ... | ... | ... | ... |

## docs/_layouts/default.html

| Section | Claim | Verdict | Action |
|---|---|---|---|
| ... | ... | ... | ... |

## Re-capture needed (screenshots)

- `docs/screenshot/basic-view.png` — Light theme surface color shifted
  in PR #55. Re-capture: open a repo with several commits, switch to
  Light via View → Appearance, capture the main window.
- `docs/screenshot/theme-dialog.png` — Custom panel layout changed
  (always-expandable, hex codes pre-filled). Re-capture with Light
  active and the Theme dialog open on the Custom radio.

## Possible follow-ups (out of scope for this PR)

- (anything found that's a code-level bug or missing feature, with a
  one-line description)
```

### In-place README edits

Apply each ❌/⚠️ fix from the audit report to `README.md`. Add the
three theme-PR additions described in "Known additions to fold in"
above:

- Theming section gets two new bullets (Light primary-tinted character;
  Custom panel inspection mode).
- The "Custom typography scale" bullet is rewritten to clarify
  global persistence.

### In-place website edits

Apply each ❌/⚠️ fix to `docs/_layouts/default.html`:

- The "Theming & Insights" feature card is updated to mention the
  Custom panel inspection mode and global typography scale.
- The hero subtitle (`docs/_layouts/default.html:16`) is checked for
  feature-claim accuracy (currently mentions interactive rebase,
  conflict resolution, branches/remotes/submodules/tags — verify each
  against the codebase as part of the audit).

## Branch & PR strategy

- **Branch:** `docs/feature-audit-2026-05-06` from `master`.
- **Commits:**
  1. `docs(audit): inventory pass — generate audit report` —
     creates the audit report only. Lets the audit be reviewable
     before any README/website edits go in.
  2. `docs(readme): apply audit fixes` — in-place edits to
     `README.md`.
  3. `docs(website): apply audit fixes` — in-place edits to
     `docs/_layouts/default.html`.
- **PR:** single PR with all three commits, body summarizing the
  count of ✅/⚠️/❌ findings and a link to the report.

## Verification

**Automated:**

- `uv run pytest tests/ -q` — should still pass; no code changes.
  Run as a sanity check that nothing was edited outside the docs
  surface.

**Manual (post-merge, optional):**

- Re-capture the two flagged screenshots per the report's
  instructions, in a follow-up PR.
- Open the website (`docs/index.md` rendered via Jekyll or GitHub
  Pages) and confirm the feature grid renders correctly after the
  HTML edits.

## What stays untouched

- All code under `git_gui/` and `tests/`.
- The `docs/superpowers/specs/` and `docs/superpowers/plans/`
  histories.
- Existing screenshots — flagged for re-capture but not modified.
- `docs/_config.yml` (no need to change Jekyll config).
- The `docs/index.md` shim (just frontmatter pointing at the layout).
