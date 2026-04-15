# Syntax Highlighting + Word-Level Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Pygments-based syntax highlighting and word-level intra-line diff to GitStack's existing unified-diff widget, with no layout change.

**Architecture:** Two new pure-function helper modules — `syntax_highlighter.py` (Pygments tokenize) and `word_diff.py` (`SequenceMatcher` over word-split tokens) — consumed by `diff_block.py`'s existing hunk-render pipeline. Per-line tokenization runs inside the existing lazy hunk loader; results are layered onto the current `QTextCharFormat` painting via `QTextCursor.mergeCharFormat`. Ten new MD3 theme tokens (eight syntax foregrounds + two word-level background overlays) extend the `Colors` dataclass and both built-in themes.

**Tech Stack:** Python 3.13, PySide6 (Qt), Pygments (new dependency), `difflib.SequenceMatcher` (stdlib), pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-04-14-syntax-highlight-word-diff-design.md`

---

## File Structure

**New files:**
- `git_gui/presentation/widgets/syntax_highlighter.py` — pure function `tokenize(text, filename) -> list[SyntaxToken]`.
- `git_gui/presentation/widgets/word_diff.py` — pure function `pair_diff(old, new) -> tuple[list[WordSpan], list[WordSpan]]`.
- `tests/presentation/widgets/test_syntax_highlighter.py`
- `tests/presentation/widgets/test_word_diff.py`
- `tests/presentation/widgets/test_diff_block_syntax.py` (rendering integration tests)
- `tests/presentation/theme/test_tokens_syntax.py`

**Modified files:**
- `pyproject.toml` — add `pygments >= 2.17` to dependencies.
- `git_gui/presentation/theme/tokens.py` — add 10 fields to `Colors` dataclass.
- `git_gui/presentation/theme/builtin/light.json` — values for 10 new tokens.
- `git_gui/presentation/theme/builtin/dark.json` — values for 10 new tokens.
- `git_gui/presentation/widgets/diff_block.py` — add `SyntaxFormats` dataclass + `make_syntax_formats()`; extend `_render_lines_range` to layer syntax + word passes; thread `filename` through `add_hunk_widget` / `render_hunk_content_lines` / `_render_lines_range`.
- `git_gui/presentation/widgets/diff.py` — pass `file_status.path` into the two `add_hunk_widget` call sites.

---

## Task 1: Add Pygments dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read current dependencies**

Run: `uv run python -c "import tomllib; d = tomllib.loads(open('pyproject.toml').read()); print(d['project']['dependencies'])"`
Note the existing list — you'll preserve it.

- [ ] **Step 2: Add pygments to `[project] dependencies`**

In `pyproject.toml`, find the `dependencies = [...]` block under `[project]`. Append `"pygments>=2.17"` to the list. Preserve formatting (each dep on its own line if that's the existing style).

- [ ] **Step 3: Sync the lockfile**

Run: `uv sync`
Expected: pygments and its (zero) runtime deps install; `uv.lock` updates.

- [ ] **Step 4: Verify the import works**

Run: `uv run python -c "from pygments.lexers import get_lexer_for_filename; print(get_lexer_for_filename('x.py'))"`
Expected: prints `<pygments.lexers.PythonLexer>` (or similar).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pygments dependency for diff syntax highlighting"
```

---

## Task 2: `syntax_highlighter.py` — tests

**Files:**
- Test: `tests/presentation/widgets/test_syntax_highlighter.py` (new)

This is a TDD red step. Do NOT implement `syntax_highlighter.py`. Do NOT commit. Task 3 commits both files together.

- [ ] **Step 1: Write failing tests**

Create `tests/presentation/widgets/test_syntax_highlighter.py`:

```python
from __future__ import annotations
import pytest

from git_gui.presentation.widgets.syntax_highlighter import (
    SyntaxToken, tokenize, _lexer_for,
)


def test_python_keyword_tokenized():
    tokens = tokenize("def foo():\n", "x.py")
    keywords = [t for t in tokens if t.kind == "syntax_keyword"]
    assert any(text_at(tokens, "def foo():\n", t) == "def" for t in keywords)


def test_python_function_name_tokenized():
    tokens = tokenize("def foo():\n", "x.py")
    funcs = [t for t in tokens if t.kind == "syntax_function"]
    assert any(text_at(tokens, "def foo():\n", t) == "foo" for t in funcs)


def test_python_string_literal_tokenized():
    tokens = tokenize('x = "hello"\n', "x.py")
    strings = [t for t in tokens if t.kind == "syntax_string"]
    # Combined start of any string span sits at the opening quote.
    assert any(text_at(tokens, 'x = "hello"\n', t).startswith('"') for t in strings)


def test_python_number_tokenized():
    tokens = tokenize("x = 42\n", "x.py")
    numbers = [t for t in tokens if t.kind == "syntax_number"]
    assert any(text_at(tokens, "x = 42\n", t) == "42" for t in numbers)


def test_python_comment_tokenized():
    tokens = tokenize("# a comment\n", "x.py")
    comments = [t for t in tokens if t.kind == "syntax_comment"]
    assert comments  # at least one comment span


def test_unknown_extension_returns_empty():
    tokens = tokenize("def foo():\n", "x.unknown_ext")
    # TextLexer produces only plain Token.Text; none map to a syntax role.
    assert tokens == []


def test_empty_string_returns_empty():
    assert tokenize("", "x.py") == []


def test_makefile_filename_is_recognized():
    # Pygments knows the Makefile filename pattern.
    tokens = tokenize("all: build\n\tcc -o foo foo.c\n", "Makefile")
    # Don't assert specific roles; just confirm it produced something.
    assert len(tokens) > 0


def test_token_offsets_are_valid():
    text = "def foo(x):\n    return x\n"
    tokens = tokenize(text, "x.py")
    for t in tokens:
        assert 0 <= t.start < t.end <= len(text)
        assert text[t.start:t.end]  # non-empty


def test_pygments_exception_returns_empty(monkeypatch):
    """If lex() raises, tokenize() returns [] rather than propagating."""
    from git_gui.presentation.widgets import syntax_highlighter as sh

    class _Boom:
        def get_tokens(self, _):
            raise RuntimeError("boom")

    monkeypatch.setattr(sh, "_lexer_for", lambda _: _Boom())
    # Also patch lex to use the lexer's get_tokens path — easiest to monkeypatch lex itself:
    def _bad_lex(_text, _lexer):
        raise RuntimeError("boom")
    monkeypatch.setattr(sh, "lex", _bad_lex)

    assert sh.tokenize("def foo():\n", "x.py") == []


def test_lexer_is_cached():
    # Same filename twice → same lexer instance.
    a = _lexer_for("x.py")
    b = _lexer_for("x.py")
    assert a is b


def text_at(_tokens, src: str, t: SyntaxToken) -> str:
    """Helper: return src[t.start:t.end]."""
    return src[t.start:t.end]
```

- [ ] **Step 2: Verify tests fail at import**

Run: `uv run pytest tests/presentation/widgets/test_syntax_highlighter.py -v`
Expected: collection error with `ModuleNotFoundError: No module named 'git_gui.presentation.widgets.syntax_highlighter'`.

- [ ] **Step 3: Do NOT commit.** Leave the file untracked. Task 3 commits both files together.

---

## Task 3: `syntax_highlighter.py` — implementation

**Files:**
- Create: `git_gui/presentation/widgets/syntax_highlighter.py`

- [ ] **Step 1: Create the module**

Create `git_gui/presentation/widgets/syntax_highlighter.py` with this exact content:

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
    """A syntax-highlighted span: char offsets into the input text + a role name."""
    start: int
    end: int
    kind: str  # one of the MD3 syntax_* role names


_ROLE_MAP = {
    PygmentsToken.Keyword:        "syntax_keyword",
    PygmentsToken.Name.Builtin:   "syntax_keyword",
    PygmentsToken.Name.Function:  "syntax_function",
    PygmentsToken.Name.Class:     "syntax_class",
    PygmentsToken.String:         "syntax_string",
    PygmentsToken.Number:         "syntax_number",
    PygmentsToken.Comment:        "syntax_comment",
    PygmentsToken.Operator:       "syntax_operator",
    PygmentsToken.Name.Decorator: "syntax_decorator",
}


@lru_cache(maxsize=128)
def _lexer_for(filename: str) -> Lexer:
    try:
        return get_lexer_for_filename(filename, stripnl=False)
    except ClassNotFound:
        return TextLexer(stripnl=False)


def tokenize(text: str, filename: str) -> list[SyntaxToken]:
    """Tokenize *text* using the Pygments lexer inferred from *filename*.

    Returns spans that map to one of the syntax_* theme roles. Plain-text
    regions are omitted (the renderer applies the line's default format).
    """
    if not text:
        return []
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

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/presentation/widgets/test_syntax_highlighter.py -v`
Expected: all 11 tests pass.

- [ ] **Step 3: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/syntax_highlighter.py tests/presentation/widgets/test_syntax_highlighter.py
git commit -m "feat(diff): add syntax_highlighter pure function via Pygments"
```

---

## Task 4: `word_diff.py` — tests

**Files:**
- Test: `tests/presentation/widgets/test_word_diff.py` (new)

TDD red step. Do NOT implement. Do NOT commit.

- [ ] **Step 1: Write failing tests**

Create `tests/presentation/widgets/test_word_diff.py`:

```python
from __future__ import annotations
import pytest

from git_gui.presentation.widgets.word_diff import WordSpan, pair_diff


def _kinds(spans):
    return [s.kind for s in spans]


def _changed_text(line: str, spans):
    return [line[s.start:s.end] for s in spans if s.kind == "changed"]


def test_identical_lines_have_no_changed_spans():
    old, new = pair_diff("foo = 1", "foo = 1")
    assert all(s.kind == "same" for s in old)
    assert all(s.kind == "same" for s in new)


def test_single_word_change_marks_only_that_word():
    old, new = pair_diff("foo = 1", "foo = 2")
    assert _changed_text("foo = 1", old) == ["1"]
    assert _changed_text("foo = 2", new) == ["2"]


def test_completely_different_lines_are_fully_changed():
    old, new = pair_diff("abc", "xyz")
    # Every word/char span on each side is "changed".
    assert all(s.kind == "changed" for s in old)
    assert all(s.kind == "changed" for s in new)


def test_whitespace_only_change_is_detected():
    # Trailing space added.
    old, new = pair_diff("foo", "foo ")
    assert _changed_text("foo ", new) == [" "]


def test_empty_old_marks_full_new_as_changed():
    old, new = pair_diff("", "abc")
    assert old == []
    assert _changed_text("abc", new) == ["abc"]


def test_empty_new_marks_full_old_as_changed():
    old, new = pair_diff("abc", "")
    assert _changed_text("abc", old) == ["abc"]
    assert new == []


def test_adjacent_same_kind_spans_are_merged():
    # "foo bar baz" → "foo BAR BAZ": "BAR BAZ" is one merged "changed" span on new side?
    # SequenceMatcher will likely produce one "replace" opcode covering both words,
    # which yields a single span covering "bar baz" (old) and "BAR BAZ" (new).
    # Our merge step should not split them.
    old, new = pair_diff("foo bar baz", "foo BAR BAZ")
    new_changed = [s for s in new if s.kind == "changed"]
    # All "changed" spans should be contiguous (no gap between adjacent same-kind spans).
    for a, b in zip(new_changed, new_changed[1:]):
        assert a.end < b.start  # gap exists (a "same" span between them)


def test_unicode_identifiers_unchanged_stay_same():
    old, new = pair_diff("αβγ = 1", "αβγ = 2")
    # The αβγ token should appear as "same" on both sides.
    assert any(s.kind == "same" and "αβγ" in "αβγ = 1"[s.start:s.end] for s in old)


def test_spans_cover_input_with_no_overlap():
    """Returned spans should be non-overlapping and cover the changed regions."""
    old, new = pair_diff("a b c", "a B c")
    for spans in (old, new):
        prev_end = 0
        for s in spans:
            assert s.start >= prev_end
            prev_end = s.end


def test_word_span_is_frozen_dataclass():
    span = WordSpan(start=0, end=3, kind="same")
    with pytest.raises(Exception):
        span.start = 1  # type: ignore[misc]
```

- [ ] **Step 2: Verify tests fail at import**

Run: `uv run pytest tests/presentation/widgets/test_word_diff.py -v`
Expected: `ModuleNotFoundError: No module named 'git_gui.presentation.widgets.word_diff'`.

- [ ] **Step 3: Do NOT commit.** Task 5 commits both files together.

---

## Task 5: `word_diff.py` — implementation

**Files:**
- Create: `git_gui/presentation/widgets/word_diff.py`

- [ ] **Step 1: Create the module**

Create `git_gui/presentation/widgets/word_diff.py` with this exact content:

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal


@dataclass(frozen=True)
class WordSpan:
    start: int
    end: int
    kind: Literal["same", "changed"]


# Tokenize on word, whitespace, and punctuation boundaries — keep all three.
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
    """Return (old_spans, new_spans) marking which word tokens changed.

    Each returned list has WordSpans covering disjoint character ranges of its
    input. Adjacent same-kind spans are merged.
    """
    old_tokens = _split(old_line)
    new_tokens = _split(new_line)
    matcher = SequenceMatcher(
        a=[t[2] for t in old_tokens],
        b=[t[2] for t in new_tokens],
        autojunk=False,
    )

    old_spans: list[WordSpan] = []
    new_spans: list[WordSpan] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        kind: Literal["same", "changed"] = "same" if tag == "equal" else "changed"
        if i1 != i2:
            old_spans.append(WordSpan(
                start=old_tokens[i1][0],
                end=old_tokens[i2 - 1][1],
                kind=kind,
            ))
        if j1 != j2:
            new_spans.append(WordSpan(
                start=new_tokens[j1][0],
                end=new_tokens[j2 - 1][1],
                kind=kind,
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

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/presentation/widgets/test_word_diff.py -v`
Expected: all 10 tests pass.

- [ ] **Step 3: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 4: Commit**

```bash
git add git_gui/presentation/widgets/word_diff.py tests/presentation/widgets/test_word_diff.py
git commit -m "feat(diff): add word_diff pure function for intra-line pairing"
```

---

## Task 6: Theme tokens — add 10 new color roles

**Files:**
- Modify: `git_gui/presentation/theme/tokens.py`
- Modify: `git_gui/presentation/theme/builtin/light.json`
- Modify: `git_gui/presentation/theme/builtin/dark.json`
- Test: `tests/presentation/theme/test_tokens_syntax.py` (new)

- [ ] **Step 1: Write failing test for the new tokens**

Create `tests/presentation/theme/test_tokens_syntax.py`:

```python
from __future__ import annotations
import pytest

from git_gui.presentation.theme.loader import load_builtin_theme


SYNTAX_ROLES = [
    "syntax_keyword",
    "syntax_function",
    "syntax_class",
    "syntax_string",
    "syntax_number",
    "syntax_comment",
    "syntax_operator",
    "syntax_decorator",
    "diff_added_word_overlay",
    "diff_removed_word_overlay",
]


@pytest.mark.parametrize("theme_name", ["light", "dark"])
@pytest.mark.parametrize("role", SYNTAX_ROLES)
def test_role_present_on_theme(theme_name, role):
    theme = load_builtin_theme(theme_name)
    value = getattr(theme.colors, role)
    assert isinstance(value, str)
    assert value.startswith("#")  # hex color
    # Acceptable hex lengths: #RGB, #RRGGBB, #AARRGGBB
    assert len(value) in (4, 7, 9)


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_word_overlay_differs_from_line_overlay(theme_name):
    """The word-level overlay must be visually distinct from the line overlay."""
    theme = load_builtin_theme(theme_name)
    assert theme.colors.diff_added_word_overlay != theme.colors.diff_added_overlay
    assert theme.colors.diff_removed_word_overlay != theme.colors.diff_removed_overlay
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/presentation/theme/test_tokens_syntax.py -v`
Expected: failure — either `AttributeError` (fields not on `Colors`) or `KeyError` from JSON loading.

If `load_builtin_theme` doesn't exist with that exact name, find the correct loader function. Search: `Grep pattern="def load_builtin|def load_theme" path=git_gui/presentation/theme`. Adjust the import in the test if needed.

- [ ] **Step 3: Add fields to the `Colors` dataclass**

In `git_gui/presentation/theme/tokens.py`, locate the `Colors` dataclass (around line 7). After the existing `hover_overlay: str` field (the last field), add:

```python
    # Syntax highlighting (Pygments token roles)
    syntax_keyword: str
    syntax_function: str
    syntax_class: str
    syntax_string: str
    syntax_number: str
    syntax_comment: str
    syntax_operator: str
    syntax_decorator: str
    # Word-level diff overlays (layered over line overlays)
    diff_added_word_overlay: str
    diff_removed_word_overlay: str
```

- [ ] **Step 4: Add values to `dark.json`**

Open `git_gui/presentation/theme/builtin/dark.json`. Find the existing `"diff_added_overlay"` / `"diff_removed_overlay"` lines. After the last entry of the colors block (likely `"hover_overlay"`), add:

```json
    "syntax_keyword":     "#ff7b72",
    "syntax_function":    "#d2a8ff",
    "syntax_class":       "#f0c674",
    "syntax_string":      "#a5d6ff",
    "syntax_number":      "#79c0ff",
    "syntax_comment":     "#8b949e",
    "syntax_operator":    "#ff7b72",
    "syntax_decorator":   "#d2a8ff",
    "diff_added_word_overlay":   "#80238636",
    "diff_removed_word_overlay": "#80f85149"
```

(Insert before the closing `}` of the colors object. The last existing line currently lacks a trailing comma; add one to it before inserting your block, and ensure your block's last entry has no trailing comma.)

The syntax colors are sourced from the GitHub Dark theme palette, chosen to harmonize with the existing diff backgrounds (`#1d3a26` add, `#67060c`-ish remove). The word overlays use hex alpha `80` (~50%) — twice as opaque as the existing line overlays' `50` — to read clearly through the line background.

- [ ] **Step 5: Add values to `light.json`**

Open `git_gui/presentation/theme/builtin/light.json`. Apply the same insertion with these values:

```json
    "syntax_keyword":     "#cf222e",
    "syntax_function":    "#8250df",
    "syntax_class":       "#953800",
    "syntax_string":      "#0a3069",
    "syntax_number":      "#0550ae",
    "syntax_comment":     "#6e7781",
    "syntax_operator":    "#cf222e",
    "syntax_decorator":   "#8250df",
    "diff_added_word_overlay":   "#80aceebb",
    "diff_removed_word_overlay": "#80ffcecb"
```

(Same comma rule: ensure the prior last line ends with `,` and your last entry doesn't.)

- [ ] **Step 6: Run the theme tests**

Run: `uv run pytest tests/presentation/theme/test_tokens_syntax.py -v`
Expected: all 20 parametrized tests pass.

- [ ] **Step 7: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add git_gui/presentation/theme/tokens.py git_gui/presentation/theme/builtin/light.json git_gui/presentation/theme/builtin/dark.json tests/presentation/theme/test_tokens_syntax.py
git commit -m "feat(theme): add 10 syntax + word-overlay color roles"
```

---

## Task 7: `SyntaxFormats` dataclass + `make_syntax_formats()`

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`

- [ ] **Step 1: Add the dataclass**

In `git_gui/presentation/widgets/diff_block.py`, immediately after the existing `DiffFormats` dataclass (around line 69), add:

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
    # Word-level overlays (set BackgroundColor only — merge over line bg + syntax fg)
    added_word_overlay: QTextCharFormat
    removed_word_overlay: QTextCharFormat


# Maps the syntax_highlighter SyntaxToken.kind string → a SyntaxFormats attribute name.
_KIND_TO_ATTR = {
    "syntax_keyword":   "keyword",
    "syntax_function":  "function",
    "syntax_class":     "class_",
    "syntax_string":    "string",
    "syntax_number":    "number",
    "syntax_comment":   "comment",
    "syntax_operator":  "operator",
    "syntax_decorator": "decorator",
}
```

- [ ] **Step 2: Add the factory function**

Immediately after `make_diff_formats()` (around line 154), add:

```python
def make_syntax_formats() -> SyntaxFormats:
    """Build a SyntaxFormats dataclass from the active theme's palette."""
    c = get_theme_manager().current.colors

    def _fg(role: str) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(c.as_qcolor(role))
        return f

    def _bg(role: str) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setBackground(c.as_qcolor(role))
        return f

    return SyntaxFormats(
        keyword=_fg("syntax_keyword"),
        function=_fg("syntax_function"),
        class_=_fg("syntax_class"),
        string=_fg("syntax_string"),
        number=_fg("syntax_number"),
        comment=_fg("syntax_comment"),
        operator=_fg("syntax_operator"),
        decorator=_fg("syntax_decorator"),
        added_word_overlay=_bg("diff_added_word_overlay"),
        removed_word_overlay=_bg("diff_removed_word_overlay"),
    )
```

- [ ] **Step 3: Sanity-check via Python REPL**

Run: `uv run python -c "from git_gui.presentation.widgets.diff_block import make_syntax_formats, SyntaxFormats; from PySide6.QtWidgets import QApplication; QApplication([]); from git_gui.presentation.theme import ThemeManager, set_theme_manager; set_theme_manager(ThemeManager(QApplication.instance())); f = make_syntax_formats(); print(type(f).__name__, isinstance(f.keyword, type(f.keyword)))"`

Expected: prints `SyntaxFormats True`. (If it errors on theme manager init, that's OK — Step 4 verifies via the test suite.)

- [ ] **Step 4: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py
git commit -m "feat(diff): add SyntaxFormats dataclass and factory"
```

---

## Task 8: Integrate syntax highlighting in `_render_lines_range` — tests

**Files:**
- Test: `tests/presentation/widgets/test_diff_block_syntax.py` (new)

TDD red step. Do NOT implement integration. Do NOT commit.

- [ ] **Step 1: Write failing tests**

Create `tests/presentation/widgets/test_diff_block_syntax.py`:

```python
from __future__ import annotations
import pytest
from PySide6.QtWidgets import QPlainTextEdit

from git_gui.domain.entities import Hunk
from git_gui.presentation.widgets.diff_block import (
    make_diff_formats, make_syntax_formats, render_hunk_content_lines,
)


def _editor_for_hunk(qtbot, hunk: Hunk, filename: str) -> QPlainTextEdit:
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    diff_formats = make_diff_formats()
    syntax_formats = make_syntax_formats()
    cursor = editor.textCursor()
    render_hunk_content_lines(
        cursor, hunk, diff_formats,
        syntax_formats=syntax_formats, filename=filename,
    )
    return editor


def _format_at(editor: QPlainTextEdit, line_index: int, col: int):
    """Return the QTextCharFormat at (line_index, col) in the editor."""
    block = editor.document().findBlockByNumber(line_index)
    text = block.text()
    assert col < len(text), f"col {col} out of range for line {text!r}"
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + col + 1)  # +1 to read the char before
    return cursor.charFormat()


def test_python_keyword_gets_syntax_color(qtbot):
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[(" ", "def foo():\n")],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # The line layout is "<prefix>def foo():" — prefix length is 11 chars
    # ("   1    1  " = 4+1+4+2 = 11). The 'd' of "def" sits at col 11.
    # Read the format at the position of 'd'.
    fmt = _format_at(editor, 0, 11)
    fg = fmt.foreground().color().name()
    syntax_kw = make_syntax_formats().keyword.foreground().color().name()
    assert fg == syntax_kw


def test_long_line_skips_syntax_pass(qtbot):
    long_line = "x = " + "a" * 2100 + "\n"  # > 2000 chars total
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[(" ", long_line)],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # The 'x' at col 11 should NOT have any syntax color applied —
    # it should keep the default fg from DiffFormats.fmt_default.
    fmt = _format_at(editor, 0, 11)
    fg = fmt.foreground().color().name()
    diff_default = make_diff_formats().fmt_default.foreground().color().name()
    assert fg == diff_default


def test_unknown_extension_no_syntax_format(qtbot):
    hunk = Hunk(
        header="@@ -1,1 +1,1 @@",
        lines=[(" ", "def foo():\n")],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.unknownext")
    # 'd' at col 11 should NOT be colored as a keyword.
    fmt = _format_at(editor, 0, 11)
    fg = fmt.foreground().color().name()
    syntax_kw = make_syntax_formats().keyword.foreground().color().name()
    assert fg != syntax_kw
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest tests/presentation/widgets/test_diff_block_syntax.py -v`
Expected: failures because `render_hunk_content_lines` does not yet accept `syntax_formats=` / `filename=` keyword args (TypeError).

- [ ] **Step 3: Do NOT commit.** Task 9 commits both files together.

---

## Task 9: Integrate syntax highlighting — implementation

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`

- [ ] **Step 1: Update `_render_lines_range` to apply syntax formats**

Replace the existing `_render_lines_range` function (lines 198-229) with this version. The change: accept `syntax_formats` and `filename` (both optional, default `None` — when either is `None`, the function behaves exactly as today). When both are provided, after inserting each line, run a syntax pass over the content portion.

```python
_LONG_LINE_LIMIT = 2000


def _render_lines_range(
    cursor, hunk, formats, start, end,
    syntax_formats=None, filename=None,
) -> None:
    """Render hunk.lines[start:end] into cursor, tracking line numbers.

    When *syntax_formats* and *filename* are both given, layer Pygments-driven
    syntax coloring onto the inserted content via mergeCharFormat.
    """
    from PySide6.QtGui import QTextCursor
    from git_gui.presentation.widgets.syntax_highlighter import tokenize

    old_line, new_line = parse_hunk_header(hunk.header)
    for origin, _ in hunk.lines[:start]:
        if origin == "+":
            new_line += 1
        elif origin == "-":
            old_line += 1
        else:
            old_line += 1
            new_line += 1

    apply_syntax = syntax_formats is not None and filename is not None

    for origin, content in hunk.lines[start:end]:
        if origin == "+":
            cursor.setBlockFormat(formats.blk_added)
            cursor.setCharFormat(formats.fmt_added)
            prefix = f"     {new_line:>4}  "
            new_line += 1
        elif origin == "-":
            cursor.setBlockFormat(formats.blk_removed)
            cursor.setCharFormat(formats.fmt_removed)
            prefix = f"{old_line:>4}       "
            old_line += 1
        else:
            cursor.setBlockFormat(formats.blk_default)
            cursor.setCharFormat(formats.fmt_default)
            prefix = f"{old_line:>4} {new_line:>4}  "
            old_line += 1
            new_line += 1

        line_with_eol = content if content.endswith("\n") else content + "\n"
        full_text = prefix + line_with_eol

        # Record where the content starts (after the prefix) — used by syntax pass
        # to compute absolute positions in the document.
        content_doc_start = cursor.position() + len(prefix)

        cursor.insertText(full_text)

        if not apply_syntax:
            continue
        if len(line_with_eol) > _LONG_LINE_LIMIT:
            continue

        # Strip the trailing newline from the content we feed the lexer.
        content_text = line_with_eol.rstrip("\n")
        if not content_text:
            continue
        tokens = tokenize(content_text, filename)
        if not tokens:
            continue

        for tok in tokens:
            tok_cursor = QTextCursor(cursor.document())
            tok_cursor.setPosition(content_doc_start + tok.start)
            tok_cursor.setPosition(
                content_doc_start + tok.end,
                QTextCursor.KeepAnchor,
            )
            attr = _KIND_TO_ATTR.get(tok.kind)
            if attr is None:
                continue
            tok_cursor.mergeCharFormat(getattr(syntax_formats, attr))
```

- [ ] **Step 2: Plumb `syntax_formats` + `filename` through `render_hunk_content_lines`**

Replace the existing `render_hunk_content_lines` (lines 232-269) with:

```python
def render_hunk_content_lines(
    cursor, hunk: Hunk, formats: DiffFormats,
    syntax_formats: "SyntaxFormats | None" = None,
    filename: str | None = None,
) -> int:
    """Insert the +/-/context lines of *hunk* into *cursor*.

    For small hunks (<= _CHUNK_SIZE lines), renders synchronously.
    For large hunks, renders the first chunk immediately and schedules
    the rest via QTimer.singleShot to keep the UI responsive.

    When *syntax_formats* and *filename* are both given, the syntax pass
    layers Pygments-driven coloring on each rendered line.
    """
    if not hunk.lines:
        return 0

    total = len(hunk.lines)
    if total <= _CHUNK_SIZE:
        _render_lines_range(
            cursor, hunk, formats, 0, total,
            syntax_formats=syntax_formats, filename=filename,
        )
        return total

    _render_lines_range(
        cursor, hunk, formats, 0, _CHUNK_SIZE,
        syntax_formats=syntax_formats, filename=filename,
    )

    from PySide6.QtCore import QTimer
    state = {"start": _CHUNK_SIZE}

    def _next_chunk():
        try:
            start = state["start"]
            end = min(start + _CHUNK_SIZE, total)
            _render_lines_range(
                cursor, hunk, formats, start, end,
                syntax_formats=syntax_formats, filename=filename,
            )
            state["start"] = end
            if end < total:
                QTimer.singleShot(0, _next_chunk)
        except RuntimeError:
            pass

    QTimer.singleShot(0, _next_chunk)
    return total
```

- [ ] **Step 3: Run the syntax-rendering tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_block_syntax.py -v`
Expected: all 3 tests pass.

- [ ] **Step 4: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions. (Existing call sites pass no `syntax_formats`/`filename`, so behavior is unchanged for them.)

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py tests/presentation/widgets/test_diff_block_syntax.py
git commit -m "feat(diff): apply Pygments syntax highlighting per line"
```

---

## Task 10: Word-level diff integration — tests

**Files:**
- Modify: `tests/presentation/widgets/test_diff_block_syntax.py`

TDD red step. Do NOT implement. Do NOT commit.

- [ ] **Step 1: Append word-level rendering tests**

Append to `tests/presentation/widgets/test_diff_block_syntax.py`:

```python
def _bg_color_at(editor: QPlainTextEdit, line_index: int, col: int) -> str:
    """Return the QTextCharFormat background color at (line_index, col) as hex."""
    block = editor.document().findBlockByNumber(line_index)
    cursor = editor.textCursor()
    cursor.setPosition(block.position() + col + 1)
    fmt = cursor.charFormat()
    bg = fmt.background().color()
    return bg.name(bg.HexArgb)


def test_paired_minus_plus_marks_changed_word_with_overlay(qtbot):
    """A -/+ pair where only one token differs: that token gets the word overlay."""
    hunk = Hunk(
        header="@@ -1,2 +1,2 @@",
        lines=[
            ("-", "x = 1\n"),
            ("+", "x = 2\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")

    # Prefix on - line: "   1       " (4+7 = 11 chars). Content "x = 1" → '1' at col 11+4 = 15.
    minus_bg = _bg_color_at(editor, 0, 15)
    plus_bg = _bg_color_at(editor, 1, 15)

    expected_removed = make_syntax_formats().removed_word_overlay.background().color().name(0x80)
    # We don't compare colors strictly (they merge with line bg); we just assert
    # the overlay differs from the unchanged-region background.
    minus_unchanged_bg = _bg_color_at(editor, 0, 11)  # the 'x'
    plus_unchanged_bg = _bg_color_at(editor, 1, 11)
    assert minus_bg != minus_unchanged_bg
    assert plus_bg != plus_unchanged_bg


def test_pure_addition_hunk_has_no_word_overlay(qtbot):
    """A hunk with only + lines (no adjacent -) gets no word-level overlay."""
    hunk = Hunk(
        header="@@ -1,0 +1,2 @@",
        lines=[
            ("+", "x = 1\n"),
            ("+", "y = 2\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # No paired - line, so no character should carry the added_word_overlay bg.
    overlay_color = make_syntax_formats().added_word_overlay.background().color().name()
    bg_at_value = _bg_color_at(editor, 0, 15)  # the '1'
    # The bg should NOT be the bare overlay color (it can be the line bg or unset).
    # We just confirm it doesn't match the overlay's solid color.
    assert bg_at_value != overlay_color


def test_non_adjacent_minus_plus_not_paired(qtbot):
    """- followed by context, then +: not adjacent, no word-level pairing."""
    hunk = Hunk(
        header="@@ -1,3 +1,3 @@",
        lines=[
            ("-", "x = 1\n"),
            (" ", "noop\n"),
            ("+", "x = 2\n"),
        ],
    )
    editor = _editor_for_hunk(qtbot, hunk, "x.py")
    # The '1' on the - line and '2' on the + line should NOT carry the word overlay.
    minus_bg_at_change = _bg_color_at(editor, 0, 15)  # '1'
    minus_bg_at_unchanged = _bg_color_at(editor, 0, 11)  # 'x'
    # Without pairing, all chars on the - line share the same line background.
    assert minus_bg_at_change == minus_bg_at_unchanged
```

- [ ] **Step 2: Verify the new tests fail**

Run: `uv run pytest tests/presentation/widgets/test_diff_block_syntax.py -v`
Expected: the 3 new tests fail (word-level pass not implemented yet); the 3 existing syntax tests still pass.

- [ ] **Step 3: Do NOT commit.** Task 11 commits both together.

---

## Task 11: Word-level diff integration — implementation

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`

- [ ] **Step 1: Add a pair-index helper**

In `git_gui/presentation/widgets/diff_block.py`, immediately before `_render_lines_range`, add:

```python
def _build_pair_index(lines: list[tuple[str, str]]) -> dict[int, tuple[str, str]]:
    """Map paired -/+ line indices to (old_content, new_content).

    A pair is formed only when a '-' line is immediately followed by a '+' line.
    Both indices map to the same (old, new) tuple so the renderer can look up
    either side.
    """
    pairs: dict[int, tuple[str, str]] = {}
    i = 0
    n = len(lines)
    while i < n - 1:
        if lines[i][0] == "-" and lines[i + 1][0] == "+":
            old = lines[i][1].rstrip("\n")
            new = lines[i + 1][1].rstrip("\n")
            pairs[i] = (old, new)
            pairs[i + 1] = (old, new)
            i += 2
        else:
            i += 1
    return pairs
```

- [ ] **Step 2: Extend `_render_lines_range` to apply word overlays**

In the `_render_lines_range` function (added in Task 9), add a `pair_index` parameter and a per-line word-level pass. The full updated function:

```python
def _render_lines_range(
    cursor, hunk, formats, start, end,
    syntax_formats=None, filename=None,
    pair_index=None,
) -> None:
    from PySide6.QtGui import QTextCursor
    from git_gui.presentation.widgets.syntax_highlighter import tokenize
    from git_gui.presentation.widgets.word_diff import pair_diff

    old_line, new_line = parse_hunk_header(hunk.header)
    for origin, _ in hunk.lines[:start]:
        if origin == "+":
            new_line += 1
        elif origin == "-":
            old_line += 1
        else:
            old_line += 1
            new_line += 1

    apply_syntax = syntax_formats is not None and filename is not None
    pair_index = pair_index or {}

    for idx in range(start, end):
        origin, content = hunk.lines[idx]
        if origin == "+":
            cursor.setBlockFormat(formats.blk_added)
            cursor.setCharFormat(formats.fmt_added)
            prefix = f"     {new_line:>4}  "
            new_line += 1
        elif origin == "-":
            cursor.setBlockFormat(formats.blk_removed)
            cursor.setCharFormat(formats.fmt_removed)
            prefix = f"{old_line:>4}       "
            old_line += 1
        else:
            cursor.setBlockFormat(formats.blk_default)
            cursor.setCharFormat(formats.fmt_default)
            prefix = f"{old_line:>4} {new_line:>4}  "
            old_line += 1
            new_line += 1

        line_with_eol = content if content.endswith("\n") else content + "\n"
        full_text = prefix + line_with_eol
        content_doc_start = cursor.position() + len(prefix)
        cursor.insertText(full_text)

        if not apply_syntax:
            continue
        if len(line_with_eol) > _LONG_LINE_LIMIT:
            continue

        content_text = line_with_eol.rstrip("\n")
        if not content_text:
            continue

        # Pass 2 — syntax tokens
        tokens = tokenize(content_text, filename)
        for tok in tokens:
            tok_cursor = QTextCursor(cursor.document())
            tok_cursor.setPosition(content_doc_start + tok.start)
            tok_cursor.setPosition(
                content_doc_start + tok.end,
                QTextCursor.KeepAnchor,
            )
            attr = _KIND_TO_ATTR.get(tok.kind)
            if attr is None:
                continue
            tok_cursor.mergeCharFormat(getattr(syntax_formats, attr))

        # Pass 3 — word-level overlay (only for paired -/+)
        if idx not in pair_index or origin == " ":
            continue
        old_text, new_text = pair_index[idx]
        old_spans, new_spans = pair_diff(old_text, new_text)
        spans, overlay = (
            (old_spans, syntax_formats.removed_word_overlay)
            if origin == "-"
            else (new_spans, syntax_formats.added_word_overlay)
        )
        for span in spans:
            if span.kind != "changed":
                continue
            ws_cursor = QTextCursor(cursor.document())
            ws_cursor.setPosition(content_doc_start + span.start)
            ws_cursor.setPosition(
                content_doc_start + span.end,
                QTextCursor.KeepAnchor,
            )
            ws_cursor.mergeCharFormat(overlay)
```

- [ ] **Step 3: Build the pair index in `render_hunk_content_lines`**

Update `render_hunk_content_lines` to compute the pair index once per hunk and thread it into both call sites of `_render_lines_range`:

```python
def render_hunk_content_lines(
    cursor, hunk: Hunk, formats: DiffFormats,
    syntax_formats: "SyntaxFormats | None" = None,
    filename: str | None = None,
) -> int:
    if not hunk.lines:
        return 0

    pair_index = _build_pair_index(hunk.lines) if syntax_formats and filename else {}

    total = len(hunk.lines)
    if total <= _CHUNK_SIZE:
        _render_lines_range(
            cursor, hunk, formats, 0, total,
            syntax_formats=syntax_formats, filename=filename,
            pair_index=pair_index,
        )
        return total

    _render_lines_range(
        cursor, hunk, formats, 0, _CHUNK_SIZE,
        syntax_formats=syntax_formats, filename=filename,
        pair_index=pair_index,
    )

    from PySide6.QtCore import QTimer
    state = {"start": _CHUNK_SIZE}

    def _next_chunk():
        try:
            start = state["start"]
            end = min(start + _CHUNK_SIZE, total)
            _render_lines_range(
                cursor, hunk, formats, start, end,
                syntax_formats=syntax_formats, filename=filename,
                pair_index=pair_index,
            )
            state["start"] = end
            if end < total:
                QTimer.singleShot(0, _next_chunk)
        except RuntimeError:
            pass

    QTimer.singleShot(0, _next_chunk)
    return total
```

- [ ] **Step 4: Run the rendering tests**

Run: `uv run pytest tests/presentation/widgets/test_diff_block_syntax.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py tests/presentation/widgets/test_diff_block_syntax.py
git commit -m "feat(diff): apply word-level overlay on paired -/+ lines"
```

---

## Task 12: Plumb `filename` and `syntax_formats` through `add_hunk_widget`

**Files:**
- Modify: `git_gui/presentation/widgets/diff_block.py`
- Modify: `git_gui/presentation/widgets/diff.py`

So far the syntax pipeline only fires when callers pass `syntax_formats` + `filename`. This task wires them in at the public API.

- [ ] **Step 1: Extend `add_hunk_widget` signature**

In `git_gui/presentation/widgets/diff_block.py`, update `add_hunk_widget` (around line 286) to accept the new args. Replace the current signature and inner `_render` definition:

```python
def add_hunk_widget(
    parent_layout: QVBoxLayout,
    hunk: Hunk,
    formats: DiffFormats,
    *,
    extra_left_widgets: list[QWidget] | None = None,
    extra_right_widgets: list[QWidget] | None = None,
    on_header_clicked: Callable[[], None] | None = None,
    syntax_formats: "SyntaxFormats | None" = None,
    filename: str | None = None,
) -> None:
    """Append a header row + sized-to-fit diff editor for one hunk into parent_layout.

    When *syntax_formats* and *filename* are both given, the diff editor renders
    with Pygments syntax highlighting and word-level intra-line diff.
    """
    if extra_left_widgets is None:
        extra_left_widgets = []
    if extra_right_widgets is None:
        extra_right_widgets = []

    # --- Header row (unchanged) ---
    header_row = QWidget()
    header_layout = QHBoxLayout(header_row)
    header_layout.setContentsMargins(0, HEADER_ROW_VPAD, 0, HEADER_ROW_VPAD)
    header_layout.setSpacing(4)
    for w in extra_left_widgets:
        header_layout.addWidget(w)
    header_text = hunk.header.strip()
    if on_header_clicked is not None:
        header_label = _ClickableLabel(header_text, on_header_clicked)
    else:
        header_label = QLabel(header_text)
    header_label.setStyleSheet(f"color: {_hunk_header_color()};")
    header_layout.addWidget(header_label)
    header_layout.addStretch()
    for w in extra_right_widgets:
        header_layout.addWidget(w)
    header_row.setFixedHeight(HEADER_ROW_HEIGHT + HEADER_ROW_VPAD * 2)

    # --- Diff editor ---
    editor = make_diff_editor()

    def _render(current_formats: DiffFormats) -> int:
        editor.clear()
        cursor = editor.textCursor()
        count = render_hunk_content_lines(
            cursor, hunk, current_formats,
            syntax_formats=syntax_formats, filename=filename,
        )
        editor.setTextCursor(cursor)
        return count

    line_count = _render(formats)

    line_height = editor.fontMetrics().lineSpacing()
    margins = editor.contentsMargins()
    doc_margin = editor.document().documentMargin() * 2
    total_height = int(line_count * line_height + doc_margin + margins.top() + margins.bottom() + 4)
    editor.setFixedHeight(max(total_height, 4))
    editor.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _rebuild() -> None:
        header_label.setStyleSheet(f"color: {_hunk_header_color()};")
        # Rebuild syntax_formats from the new theme too — but only if syntax was active.
        new_syntax = make_syntax_formats() if syntax_formats is not None else None
        # Reuse the closure's filename/sf-or-None toggle by re-rendering:
        editor.clear()
        cursor = editor.textCursor()
        render_hunk_content_lines(
            cursor, hunk, make_diff_formats(),
            syntax_formats=new_syntax, filename=filename,
        )
        editor.setTextCursor(cursor)

    connect_widget(editor, rebuild=_rebuild)

    parent_layout.addWidget(header_row)
    parent_layout.addWidget(editor)
```

- [ ] **Step 2: Update `diff.py` to pass `filename` and a shared `syntax_formats`**

Open `git_gui/presentation/widgets/diff.py`. Find the existing import block (around line 16) and add `make_syntax_formats` and `SyntaxFormats` to the symbols imported from `diff_block`:

```python
from git_gui.presentation.widgets.diff_block import (
    make_file_block, make_diff_formats, make_syntax_formats, add_hunk_widget,
)
```

Then find the `__init__` where `self._formats = make_diff_formats()` is set (search for `make_diff_formats`). Immediately after, add:

```python
        self._syntax_formats = make_syntax_formats()
```

Find both call sites of `add_hunk_widget` (search for `add_hunk_widget(`). The plan reviewed two earlier — at `diff.py:331` and `diff.py:359`. Each call needs `syntax_formats` and `filename` added.

For the call site that renders a single file's hunks, the surrounding context provides the path. For example:

```python
add_hunk_widget(
    inner, hunk, self._formats,
    on_header_clicked=on_click,
    syntax_formats=self._syntax_formats,
    filename=path,
)
```

Use the file's `path` from the local scope. If a call site does not have a path in scope, look up the calling context — both surveyed sites have `path` or `file_status.path` available (search a few lines above the `add_hunk_widget(` call).

If the theme rebuild path also needs `_syntax_formats` refreshed, add a sibling line wherever `self._formats = make_diff_formats()` is reassigned (search for that pattern).

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: no regressions. The rendering tests from Task 11 still pass.

- [ ] **Step 4: Manual smoke test**

Run: `uv run python main.py`. Open any repository and click a commit with code changes (any `.py`, `.js`, `.go` file). Verify visually:
- Keywords (`def`, `class`, `if`, `import`) are colored.
- Strings, numbers, comments are colored.
- A `-line / +line` pair where only some words differ shows the changed words with a brighter background overlay.
- Toggling `View → Appearance...` between light and dark themes preserves the highlights and re-renders correctly.

If anything looks off, STOP and report — do not proceed to commit.

- [ ] **Step 5: Commit**

```bash
git add git_gui/presentation/widgets/diff_block.py git_gui/presentation/widgets/diff.py
git commit -m "feat(diff): wire syntax + word-level diff into DiffWidget"
```

---

## Task 13: README + final suite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full test run**

Run: `uv run pytest tests/ -v`
Expected: no failures, no new warnings. Paste the summary line in your report. If anything fails, STOP and report `BLOCKED`.

- [ ] **Step 2: Update README**

In `README.md`, find the existing `### Commit Graph & History` or `### Working Tree & Staging` section. Locate a sensible place to mention diff improvements (the "Working Tree & Staging" feature list mentions inline diff today). Append a new line under the working-tree section's bullet list, or add a new sub-section if cleaner. Add:

```markdown
- **Syntax highlighting** in diff hunks (Pygments — supports hundreds of languages)
- **Word-level intra-line diff** highlights changed words within `-`/`+` line pairs
```

(Pick the location that reads best inline — likely under the existing "Inline diff viewer" bullet in the "Working Tree & Staging" section.)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document syntax highlighting + word-level diff in README"
```

---

## Self-Review Checklist

After completing the implementation, verify against the spec:

1. **Pygments dependency** added (Task 1).
2. **`syntax_highlighter.py`** with `tokenize()` returning `SyntaxToken` spans, LRU-cached lexer lookup, exception-safe (Tasks 2-3).
3. **`word_diff.py`** with `pair_diff()` returning `WordSpan` lists, adjacent-merge, no Qt (Tasks 4-5).
4. **10 theme tokens** added to `Colors` and both built-in themes (Task 6).
5. **`SyntaxFormats` dataclass + factory** (Task 7).
6. **Per-line syntax pass** layered via `mergeCharFormat`; long-line guard at 2000 chars (Tasks 8-9).
7. **Word-level pass** keyed off adjacent `-`/`+` pair index (Tasks 10-11).
8. **Public API plumbed** — `add_hunk_widget` accepts `syntax_formats` + `filename`; `diff.py` passes them (Task 12).
9. **Theme switch** still re-renders correctly (verified in Task 12 manual smoke).
10. **README updated** (Task 13).
