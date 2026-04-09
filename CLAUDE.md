# CLAUDE.md — project conventions for Claude Code

## Python execution

Always use `uv run` to execute all Python operations (scripts, pytest, etc.).

Examples:
- Tests: `uv run pytest tests/ -v`
- Scripts: `uv run python main.py`
- One-liners: `uv run python -c "..."`
