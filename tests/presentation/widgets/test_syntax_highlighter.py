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
