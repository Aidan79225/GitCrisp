# GitStack Website Design

## Goal

Create a single-page dark-themed landing page for GitStack, built with Jekyll and hosted on GitHub Pages from the `docs/` folder of the main repo.

## Tech Stack

- Jekyll (GitHub Pages built-in, no custom CI needed)
- Source: `docs/` folder on `master` branch
- URL: `https://aidan79225.github.io/GitStack/`

## Page Sections

### 1. Hero
- GitStack name + tagline: "A clean, focused Git GUI"
- Download button linking to GitHub Releases (`/GitStack/releases/latest`)
- Screenshot placeholder (to be added later)

### 2. Features
4-6 feature cards with icon/emoji and short description:
- **Visual Commit Graph** — Lane-based graph with branching and merging history
- **Per-Hunk Staging** — Stage or unstage individual diff hunks within a file
- **Stash Management** — One-click stash, view stash contents, pop/apply/drop
- **Remote Operations** — Push, pull, fetch with background execution and status logging
- **Multi-Repository** — Switch between repos with persistent open/recent lists

### 3. Architecture
Brief description of Clean Architecture layers (domain, application, infrastructure, presentation) with a text or simple diagram.

### 4. Philosophy
Explain deliberately omitted features:
- **Merge** — Use pull requests for safer, traceable branch integration
- **Rebase & Cherry-Pick** — CLI with your preferred editor handles conflicts better than any GUI

### 5. Footer
- GitHub repo link
- MIT license
- Download link

## Visual Theme

- Background: `#0d1117` (GitHub Dark)
- Card/surface: `#161b22`
- Border: `#30363d`
- Accent: `#58a6ff` (blue)
- Text: `#f0f6fc` (primary), `#8b949e` (muted)

## File Structure

```
docs/
├── _config.yml          # Jekyll config (title, baseurl, theme settings)
├── _layouts/
│   └── default.html     # Main HTML layout with all sections
├── assets/
│   └── css/
│       └── style.css    # Dark theme styles
├── index.md             # Front matter only, content in layout
└── screenshot.png       # App screenshot (placeholder for now)
```

## Deployment

GitHub repo Settings → Pages → Source: Deploy from branch, `master`, `/docs` folder. GitHub automatically builds with Jekyll — no custom workflow needed.
