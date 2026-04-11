# CLAUDE.md — project conventions for Claude Code

## Communication

When the user writes a message, rewrite it into correct English (with proper grammar and word choice) before responding to the request — regardless of whether the original is in English or another language. Show the corrected/translated version as a blockquote at the start of your response.

## Architecture

Follow **Clean Architecture** principles:
- **Domain** (`domain/entities.py`, `domain/ports.py`): pure data classes and protocol interfaces — no framework dependencies
- **Application** (`application/commands.py`, `application/queries.py`): thin use-case wrappers that delegate to ports
- **Infrastructure** (`infrastructure/pygit2_repo.py`): concrete implementations of ports (pygit2, subprocess)
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
