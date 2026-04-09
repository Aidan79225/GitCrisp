# README and Jekyll Site Refresh

**Date:** 2026-04-09
**Status:** Approved

## Overview

Update `README.md` and the Jekyll site (`docs/_layouts/default.html` + supporting assets) to reflect every feature added since the last docs pass. The current docs are missing: theming, tags, insights, log panel, the entire `Git` menu (Branches/Remotes/Submodules dialogs), submodule support and click-to-open, recursive clone, and the checkout-conflict prompt. They also incorrectly state that merge and rebase are "deliberately omitted" — both are now wired up via the sidebar.

This is a content + structure overhaul, not a redesign. Visual style and the existing 4-layer architecture diagram stay.

## Scope

- Full content refresh of `README.md` and `docs/_layouts/default.html`.
- Restructured feature lists grouped by area.
- Remove the "Deliberately Omitted" / "Design Philosophy" sections from both files entirely.
- Add 2-3 new screenshots provided by the user (Branches dialog, Theme dialog, Insight dialog) to `docs/screenshot/`.
- Reflow the Jekyll feature grid CSS if needed to accommodate 9 cards.

## README Structure

1. Title + tagline (one line).
2. Hero screenshot — `docs/screenshot/basic-view.png`.
3. Features — grouped sections, each with a one-line description and 2-5 bullets:
   - Commit Graph & History
   - Working Tree & Staging
   - Branch Management (sidebar tree, graph context menu, `Git → Branches...` dialog, checkout-conflict reset prompt)
   - Tags
   - Stash
   - Remotes (`Git → Remotes...` CRUD)
   - Submodules (`Git → Submodules...` CRUD, recursive clone, click submodule diff to open)
   - Multi-Repository
   - Theming (`View → Appearance...`, light/dark, typography scale)
   - Insights (commit stats over time)
4. Keyboard Shortcuts table.
5. Architecture — keep the existing tree diagram, lightly updated.
6. Requirements — `Python >= 3.13`, `PySide6 >= 6.11.0`, `pygit2 >= 1.19.2`.
7. Getting Started — clone, `uv sync`, `uv run python main.py`.
8. Running Tests — `uv run pytest -v`.
9. License — MIT.

The "Deliberately Omitted Features" section is removed.

## Jekyll Site Structure

`docs/_layouts/default.html`:

1. **Hero** — unchanged (title, tagline, subtitle, Download/GitHub buttons).
2. **Hero screenshot** — add `basic-view.png` directly under the hero buttons. The site currently has no screenshot at all.
3. **Feature grid** — expand from 5 to 9 cards:
   - 📊 Visual Commit Graph
   - 🧩 Per-Hunk Staging
   - 🌿 Branch Management *(new)*
   - 🏷️ Tag Management *(new)*
   - 📦 Stash Management
   - 🌐 Remote Operations *(updated)*
   - 🔗 Submodule Support *(new)*
   - 📂 Multi-Repository
   - 🎨 Theming & Insights *(new)*
4. **Optional screenshot strip** — single horizontal row showing supplementary screenshots provided by the user, with captions. If a screenshot doesn't exist, that card is omitted (no broken images).
5. **Architecture** — keep the existing 4-layer pill diagram unchanged.
6. **Philosophy section** — REMOVED.
7. **Footer** — unchanged.

CSS impact: check `docs/assets/css/style.css` and tweak the feature grid (e.g. `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))`) so 9 cards reflow cleanly. No other CSS changes.

## Screenshots

User will provide:

- `docs/screenshot/branches-dialog.png` — `Git → Branches...` showing local branches with upstream tracking.
- `docs/screenshot/theme-dialog.png` — `View → Appearance...` showing theme + typography controls.
- `docs/screenshot/insight-dialog.png` — Insight dialog showing commit stats.

Any missing screenshot is silently omitted from the screenshot strip. `basic-view.png` is unchanged.

## Process

1. Read `pyproject.toml` for version pins (already confirmed: Python 3.13, PySide6 6.11.0, pygit2 1.19.2).
2. Read `docs/assets/css/style.css` to confirm whether the feature grid needs reflow tweaks for 9 cards.
3. Rewrite `README.md` and `docs/_layouts/default.html` (and `style.css` if needed) in one pass.
4. Single commit: `docs: refresh README and Jekyll site for current feature set`.
5. No tests run — docs only.

## Out of Scope (YAGNI)

- New site pages, blog posts, changelog, or `_posts/`.
- Translating to other languages.
- Touching `_site/` (Jekyll build output — regenerated automatically).
- Updating or replacing `basic-view.png`.
- Restyling the hero, architecture diagram, or footer.
- Touching the GitHub Actions workflow or any CI.
