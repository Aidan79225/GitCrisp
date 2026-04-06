# Git Insight Design

## Overview

A Spotify Wrapped-style analytics dialog that visualizes repository activity: author commit stats, lines added/deleted, and most frequently modified files. Opened from a toolbar button, with time range filtering.

## Data Layer

### Data Source

Single git command to collect all raw data:

```
git log --numstat --format="%H%n%aN%n%aI" [--since=...] [--until=...]
```

- `%H` — full commit hash
- `%aN` — author name (respects .mailmap)
- `%aI` — ISO 8601 author date
- `--numstat` — per-file lines added/deleted
- `--since/--until` — time range filter (omitted for "all time")

### Domain Entities

```python
@dataclass
class FileStat:
    path: str
    added: int
    deleted: int

@dataclass
class CommitStat:
    oid: str
    author: str
    timestamp: datetime
    files: list[FileStat]
```

### Infrastructure

Add `get_commit_stats(since: datetime | None, until: datetime | None) -> list[CommitStat]` to `Pygit2Repository`. Uses `subprocess` to run the git log command and parses the output.

### Application Layer

Add `GetCommitStats` query accepting `since` and `until` parameters. Analysis logic (ranking, aggregation) lives in the dialog, not the domain/application layer, since it's pure display logic.

### Ports

Add `get_commit_stats` to `IRepositoryReader`. Add `GetCommitStats` to `QueryBus`.

## Dialog UI — Wrapped Style

### Opening

Toolbar button with `arts/ic_insight.svg` icon (already exists). Clicking opens `InsightDialog` as a modal dialog.

### Time Range Selector

Top of dialog, fixed position. A row of toggle buttons: **This Week** / **This Month** / **This Year** / **All** / **Custom**. Selecting "Custom" reveals two `QDateEdit` widgets (start date, end date) below the buttons. Switching time range triggers a re-query and refreshes all panels.

### Layout (top to bottom, vertical scroll)

**1. Summary Cards** — Three cards in a horizontal row, large accent-colored number + small label:
- Total Commits
- Active Authors
- Files Changed

**2. Top Authors Card** — Ranked list (top 10), each row:
- Large rank number (accent color, bold)
- Author name
- Commit count
- Horizontal bar showing lines added (green) / deleted (red) ratio

**3. Most Modified Files Card** — Ranked list (top 10), each row:
- Large rank number (accent color, bold)
- File path
- Times modified count
- Small bar showing relative frequency

### Visual Style

- Dark background (matches GitCrisp theme)
- Cards with rounded corners, subtle border, slightly lighter background
- Large bold numbers as visual focal points
- Accent color for rank numbers and key stats (purple/blue, matching GitCrisp palette)
- Custom painted widgets, not QTableWidget
- Green (#238636) for additions, red (#da3633) for deletions in bars

## Data Query & Performance

### Background Thread

Time range changes trigger a query on a background thread to avoid blocking the UI. On completion, emit a signal back to the main thread to update the display.

### Loading State

While querying, display "Loading..." text. Replace with results when the query completes.

### Ranking Limits

Author and file rankings capped at top 10 each.

## Files Affected

| File | Action | Responsibility |
|------|--------|----------------|
| `git_gui/domain/entities.py` | Modify | Add `FileStat`, `CommitStat` dataclasses |
| `git_gui/domain/ports.py` | Modify | Add `get_commit_stats` to `IRepositoryReader` |
| `git_gui/infrastructure/pygit2_repo.py` | Modify | Implement `get_commit_stats` via git log |
| `git_gui/application/queries.py` | Modify | Add `GetCommitStats` query |
| `git_gui/presentation/bus.py` | Modify | Add `get_commit_stats` to `QueryBus` |
| `git_gui/presentation/widgets/insight_dialog.py` | Create | Main dialog with Wrapped-style UI |
| `git_gui/presentation/widgets/graph.py` | Modify | Add insight toolbar button + signal |
| `git_gui/presentation/main_window.py` | Modify | Wire insight button to open dialog |

## Out of Scope

- **Development summary (LLM)** — deferred to future LangChain integration
- **Charts/graphs** — bars are inline in the ranking rows, no separate chart library
- **Export** — no CSV/PDF export
