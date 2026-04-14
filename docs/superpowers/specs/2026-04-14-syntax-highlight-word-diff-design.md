# Syntax Highlighting + Word-Level Diff — Design

**Date:** 2026-04-14
**Status:** Approved

## Goal

Upgrade the existing unified-diff widget in GitStack with two features that bring its reading experience in line with GitHub, GitLab, and Sublime Merge:

1. **Syntax highlighting** on every line in the diff (context, added, and deleted) using Pygments.
2. **Word-level (intra-line) diff** that highlights the specific words that changed between an adjacent `-`/`+` pair.

The unified layout is preserved. Side-by-side rendering is out of scope for this release.

## Scope

- Syntax highlighting on all diff lines; language inferred by filename via Pygments.
- Word-level diff for adjacent `-`/`+` pairs inside a hunk (no cross-hunk pairing, no similarity threshold).
- Two new presentation-layer helper modules plus targeted changes in `diff_block.py`.
- Ten new MD3 theme roles (eight syntax categories + two word-diff backgrounds) with light and dark values.
- No user-facing toggle in v1 — highlighting and word-diff are always on.

## UX Decisions

| Concern | Decision |
|---|---|
| Scope | Syntax highlighting + word-level diff on the existing unified layout. |
| Highlighter library | Pygments (`pygments >= 2.17`). |
| Word-diff pairing | Adjacent `-`/`+` pairs only, no similarity filter. |
| Word-diff granularity | Word-level (tokenize on `\w+` / `\s+` / punctuation boundaries). |
| Visual treatment of changed words | Darker / more saturated background overlay inside the existing line background — GitHub-style. |
| Syntax vs line background | Syntax colors applied on all lines (context, add, delete). Contrast verified during theme implementation. |
| User toggle | Always-on in v1; a `View` menu toggle can be added post-release if demanded. |
| Language detection | `get_lexer_for_filename`; `TextLexer` fallback. |

## Approach

Two pure-function helper modules, each with a single responsibility, consumed by the existing hunk-rendering pipeline in `diff_block.py`.

- `syntax_highlighter.py` — `tokenize(text, filename) -> list[SyntaxToken]`. Pure Python; no Qt.
- `word_diff.py` — `pair_diff(old_line, new_line) -> (old_spans, new_spans)`. Pure Python; no Qt.

`diff_block.py` imports both and layers the results onto its existing `QTextCharFormat` painting. Tokenization runs per line inside the existing lazy hunk-render pipeline (no background threads).

This keeps algorithmic work isolated from Qt, preserves the project's small-focused-file convention, and extends `diff_block.py` without turning it into a dumping ground.

## Architecture & files touched

**New files:**

```
git_gui/
└── presentation/widgets/
    ├── syntax_highlighter.py   # pure function: tokenize(text, filename) -> [SyntaxToken]
    └── word_diff.py            # pure function: pair_diff(old, new) -> ([WordSpan], [WordSpan])

tests/
└── presentation/widgets/
    ├── test_syntax_highlighter.py
    └── test_word_diff.py
```

**Modified files:**

```
git_gui/presentation/widgets/diff_block.py   # integrate both modules; add SyntaxFormats
git_gui/presentation/theme/tokens.py         # +10 role names on Palette dataclass
git_gui/presentation/theme/builtin/light.py  # values for new tokens
git_gui/presentation/theme/builtin/dark.py   # values for new tokens
pyproject.toml                               # add pygments >= 2.17
tests/presentation/widgets/test_diff_block_rendering.py   # new or extended
tests/presentation/theme/test_tokens_syntax.py            # new or extended
```

**No changes to:** domain, application, infrastructure, or any widget other than `diff_block.py`.

## `syntax_highlighter.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pygments import lex
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_for_filename, TextLexer
from pygments.token import Token as PygmentsToken
from pygments.util import ClassNotFound


@dataclass(frozen=True)
class SyntaxToken:
    start: int   # char offset into the input text
    end: int
    kind: str    # one of the MD3 syntax role names


_ROLE_MAP = {
    PygmentsToken.Keyword:            "syntax_keyword",
    PygmentsToken.Name.Builtin:       "syntax_keyword",
    PygmentsToken.Name.Function:      "syntax_function",
    PygmentsToken.Name.Class:         "syntax_class",
    PygmentsToken.String:             "syntax_string",
    PygmentsToken.Number:             "syntax_number",
    PygmentsToken.Comment:            "syntax_comment",
    PygmentsToken.Operator:           "syntax_operator",
    PygmentsToken.Name.Decorator:     "syntax_decorator",
}


@lru_cache(maxsize=128)
def _lexer_for(filename: str) -> Lexer:
    try:
        return get_lexer_for_filename(filename, stripnl=False)
    except ClassNotFound:
        return TextLexer(stripnl=False)


def tokenize(text: str, filename: str) -> list[SyntaxToken]:
    lexer = _lexer_for(filename)
    try:
        pairs = list(lex(text, lexer))
    except Exception:
        return []
    tokens: list[SyntaxToken] = []
    offset = 0
    for tok_type, value in pairs:
        length = len(value)
        role = _resolve_role(tok_type)
        if role is not None:
            tokens.append(SyntaxToken(offset, offset + length, role))
        offset += length
    return tokens


def _resolve_role(tok_type) -> str | None:
    for key, role in _ROLE_MAP.items():
        if tok_type in key:
            return role
    return None
```

**Notes:**
- `stripnl=False` preserves line-ending structure.
- `_lexer_for` is LRU-cached so repeated diffs of the same file reuse the lexer.
- Pygments exceptions are caught and swallowed (returns `[]`). Line renders with no syntax coloring; no crash.
- Only eight distinct role names are produced (`_ROLE_MAP` has nine entries because both `Keyword` and `Name.Builtin` map to `syntax_keyword`); everything else falls through as plain text.

## `word_diff.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal
import re


@dataclass(frozen=True)
class WordSpan:
    start: int
    end: int
    kind: Literal["same", "changed"]


_TOKEN_RE = re.compile(r"(\w+|\s+|[^\w\s])")


def _split(line: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for match in _TOKEN_RE.finditer(line):
        s, e = match.span()
        if s > pos:
            spans.append((pos, s, line[pos:s]))
        spans.append((s, e, match.group()))
        pos = e
    if pos < len(line):
        spans.append((pos, len(line), line[pos:]))
    return spans


def pair_diff(old_line: str, new_line: str) -> tuple[list[WordSpan], list[WordSpan]]:
    old_tokens = _split(old_line)
    new_tokens = _split(new_line)
    matcher = SequenceMatcher(a=[t[2] for t in old_tokens],
                              b=[t[2] for t in new_tokens],
                              autojunk=False)

    old_spans: list[WordSpan] = []
    new_spans: list[WordSpan] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        kind = "same" if tag == "equal" else "changed"
        if i1 != i2:
            old_spans.append(WordSpan(
                start=old_tokens[i1][0], end=old_tokens[i2 - 1][1], kind=kind,
            ))
        if j1 != j2:
            new_spans.append(WordSpan(
                start=new_tokens[j1][0], end=new_tokens[j2 - 1][1], kind=kind,
            ))
    return _merge_adjacent(old_spans), _merge_adjacent(new_spans)


def _merge_adjacent(spans: list[WordSpan]) -> list[WordSpan]:
    out: list[WordSpan] = []
    for s in spans:
        if out and out[-1].kind == s.kind and out[-1].end == s.start:
            out[-1] = WordSpan(out[-1].start, s.end, s.kind)
        else:
            out.append(s)
    return out
```

**Notes:**
- Input is the raw line **without** the leading `-`/`+` marker; the caller strips.
- Whitespace tokens are kept separate so whitespace-only changes are detected.
- `"same"` spans are returned for completeness; the caller may ignore them (no format applied).
- The caller decides whether two lines form a "pair" (adjacent-only per Question 3); this module just diffs the pair it's given.

## `diff_block.py` integration

The existing module renders hunks into a `QPlainTextEdit` via `QTextCursor` and a `DiffFormats` dataclass (`diff_block.py:232`). The integration adds two layered passes over each line.

**1. New formats dataclass.**

```python
@dataclass
class SyntaxFormats:
    keyword: QTextCharFormat
    function: QTextCharFormat
    class_: QTextCharFormat
    string: QTextCharFormat
    number: QTextCharFormat
    comment: QTextCharFormat
    operator: QTextCharFormat
    decorator: QTextCharFormat
    add_word_bg: QTextCharFormat
    delete_word_bg: QTextCharFormat


def make_syntax_formats() -> SyntaxFormats:
    """Build a SyntaxFormats dataclass from the active theme's palette."""
    ...
```

The eight syntax formats set `ForegroundColor` only. The two word-bg formats set `BackgroundColor` only — they layer cleanly on top of line background and syntax foreground.

**2. Per-line render passes.** Inside the existing line-rendering loop, after the existing line-background pass, add:

```python
# Pass 2: syntax tokens (skip the leading marker column).
if len(line_text) <= 2000:
    for tok in tokenize(line_text[1:], filename):
        _apply_format(
            cursor,
            line_start + 1 + tok.start,
            line_start + 1 + tok.end,
            _format_for(syntax_formats, tok.kind),
        )

# Pass 3: word-level (only for paired -/+ lines).
if line_is_paired_minus:
    old_spans, _ = pair_diff(old_text, new_text)   # computed once per pair
    for span in old_spans:
        if span.kind == "changed":
            _apply_format(cursor, line_start + 1 + span.start,
                          line_start + 1 + span.end, syntax_formats.delete_word_bg)
elif line_is_paired_plus:
    _, new_spans = pair_diff(old_text, new_text)
    for span in new_spans:
        if span.kind == "changed":
            _apply_format(cursor, line_start + 1 + span.start,
                          line_start + 1 + span.end, syntax_formats.add_word_bg)
```

The paired-line detection is computed once per hunk by walking `hunk.lines` and recording `(minus_idx, plus_idx)` tuples where a `-` line is immediately followed by a `+` line.

**3. Filename plumbing.** `add_hunk_widget` / `render_hunk_lines` gain a `filename: str` argument; the caller (`diff.py`) already knows the path.

**4. Long-line guard.** Lines exceeding 2000 characters skip syntax and word passes — the line still renders with its background. This avoids pathological Pygments behavior on minified output.

## Theme tokens

Ten new roles on the `Palette` dataclass in `presentation/theme/tokens.py`:

| Role | Purpose |
|---|---|
| `syntax_keyword` | Keywords and builtins (`if`, `print`). |
| `syntax_function` | Function names in definitions and calls. |
| `syntax_class` | Class names. |
| `syntax_string` | String literals. |
| `syntax_number` | Numeric literals. |
| `syntax_comment` | Comments. |
| `syntax_operator` | Operators and punctuation. |
| `syntax_decorator` | `@decorator` markers. |
| `diff_add_word_bg` | Darker/more saturated overlay inside `+` lines. |
| `diff_delete_word_bg` | Darker/more saturated overlay inside `-` lines. |

Both builtin light and dark themes define all ten roles. Values are chosen so that:
- Syntax foregrounds meet WCAG AA contrast against `surface`, `diff_add_bg`, and `diff_delete_bg`.
- `diff_add_word_bg` is visibly darker/more saturated than `diff_add_bg`; same for delete.

No accessor changes — the existing `Palette.as_qcolor(role_name)` covers all new roles.

QSS template (`qss_template.py`) is untouched — these colors are applied via `QTextCharFormat`, not stylesheets.

## Performance

- **Per-line tokenize.** Pygments `lex()` on ~80-char inputs is sub-millisecond. A 500-line hunk renders in a few milliseconds.
- **Per-hunk pair scan.** Single linear pass over `hunk.lines`. Negligible.
- **Lazy realization.** `ViewportBlockLoader` only realizes hunks that become visible; highlighting runs only for those. Existing 10k-line-diff scenarios remain fast.
- **Lexer reuse.** `_lexer_for` is LRU-cached (size 128).
- **Long-line guard.** Skip syntax + word passes on lines > 2000 chars.
- **No threading.** Runs on the main thread inside the existing hunk-render call. Pygments is CPU-bound Python; threading adds more overhead than it saves on typical line sizes.

## Edge cases

- **Binary files** — no `Hunk` emitted by the existing pipeline; no new code path.
- **Unknown extensions / no extension** — `TextLexer` returns one plain-text token; syntax pass is a no-op.
- **Renamed files** — syntax lexer uses the new filename.
- **Submodule hunks** — rendered specially by existing code; skip syntax + word passes for submodule deltas (check `file_status.delta == "submodule"` when passing filename through).
- **Trailing whitespace changes** — detected by `pair_diff`; changed whitespace gets the word-bg overlay.
- **Pure insertion or deletion hunks** — no adjacent `-`/`+` pair; word-level pass does not activate.
- **Multiple adjacent `+` or `-`** — paired by position (`-a/-b/+c/+d` → pair `(a, c)` and `(b, d)`). Occasionally produces semantically-wrong pairing; acceptable per Question 3.
- **Unicode in code** — handled by Pygments and `_TOKEN_RE` (which uses `\w` in Python 3 = Unicode word).
- **Very long identifiers** — changed-word overlay spans the whole token. Not ideal but non-breaking.
- **Pygments exception mid-lex** — caught; `tokenize` returns `[]` and line renders plain.

## Testing

Pure-Python tests for the helpers; pytest-qt for the rendering integration.

**`tests/presentation/widgets/test_syntax_highlighter.py`** (no Qt):
- `tokenize("def foo():", "x.py")` produces `syntax_keyword` for `def`, `syntax_function` for `foo`, `syntax_operator` for `(`, `)`, `:`.
- Unknown extension → returns `[]`.
- Empty string → returns `[]`.
- Well-known filename pattern (`Makefile`) → non-empty spans.
- Token offsets are valid: `text[start:end]` is non-empty for every returned token.
- Pygments exception path: patch `_lexer_for` to return a lexer that raises → `tokenize` returns `[]`.

**`tests/presentation/widgets/test_word_diff.py`** (no Qt):
- Identical lines → no `"changed"` spans on either side.
- `pair_diff("foo = 1", "foo = 2")` → old's `1` and new's `2` are `"changed"`, rest `"same"`.
- Whitespace-only change → whitespace span is `"changed"`.
- Completely different lines → full line `"changed"` on both sides.
- Adjacent same-kind spans merged — verify by counting spans on a multi-word-change line.
- Empty old or new → the non-empty side is fully `"changed"`.
- Unicode identifiers unchanged across edits stay `"same"`.

**`tests/presentation/widgets/test_diff_block_rendering.py`** (pytest-qt):
- Render a `-a = 1` / `+a = 2` pair → `QTextDocument` has `diff_delete_word_bg` at position of `1` and `diff_add_word_bg` at position of `2`.
- Render a hunk with only `+` lines → no word-bg format anywhere.
- Render a 2001-char line → no syntax format applied (long-line guard).
- Render a Python hunk with `def foo()` → `syntax_keyword` format applied at `def`'s position (read back via `QTextCursor.charFormat()`).

**`tests/presentation/theme/test_tokens_syntax.py`** (extend if exists, else new):
- Both builtin light and dark themes expose all ten new roles.
- `diff_add_word_bg` differs from `diff_add_bg`; same for delete.

No end-to-end GUI smoke test; manual verification after implementation.

## Out of scope

- Side-by-side diff layout (separate feature).
- User-facing toggle for syntax highlighting or word-level diff.
- Character-level intra-line diff.
- Cross-hunk pairing via `SequenceMatcher.ratio()` heuristics.
- Syntax highlighting of commit messages, file headers, or UI chrome.
- Syntax highlighting of submodule delta hunks.
- Threading the highlighter.
- Language auto-detection for files without known extensions or filename patterns.
