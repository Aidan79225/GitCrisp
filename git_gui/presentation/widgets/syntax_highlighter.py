from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pygments import lex
from pygments.lexer import Lexer
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import Token as PygmentsToken
from pygments.util import ClassNotFound

from git_gui.presentation.theme import ColorRole


@dataclass(frozen=True)
class SyntaxToken:
    """A syntax-highlighted span: char offsets into the input text + its colour role."""

    start: int
    end: int
    kind: ColorRole  # one of the SYNTAX_* roles


_ROLE_MAP = {
    PygmentsToken.Keyword: ColorRole.SYNTAX_KEYWORD,
    PygmentsToken.Name.Builtin: ColorRole.SYNTAX_KEYWORD,
    PygmentsToken.Name.Function: ColorRole.SYNTAX_FUNCTION,
    PygmentsToken.Name.Class: ColorRole.SYNTAX_CLASS,
    PygmentsToken.String: ColorRole.SYNTAX_STRING,
    PygmentsToken.Number: ColorRole.SYNTAX_NUMBER,
    PygmentsToken.Comment: ColorRole.SYNTAX_COMMENT,
    PygmentsToken.Operator: ColorRole.SYNTAX_OPERATOR,
    PygmentsToken.Name.Decorator: ColorRole.SYNTAX_DECORATOR,
}


_BOM = "﻿"


@lru_cache(maxsize=128)
def _lexer_for(filename: str) -> Lexer:
    try:
        return get_lexer_for_filename(filename, stripnl=False)
    except ClassNotFound:
        return TextLexer(stripnl=False)


def tokenize(text: str, filename: str) -> list[SyntaxToken]:
    """Tokenize *text* using the Pygments lexer inferred from *filename*.

    Returns spans that map to one of the SYNTAX_* theme roles. Plain-text
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
    # Pygments drops a leading byte-order mark before lexing, and ends its
    # input with a newline if it lacks one; offsets have to be counted against
    # the text the caller drew, not the text Pygments lexed.
    offset = len(_BOM) if text.startswith(_BOM) else 0
    for tok_type, value in pairs:
        start, offset = offset, min(offset + len(value), len(text))
        role = _resolve_role(tok_type)
        if role is not None and start < offset:
            tokens.append(SyntaxToken(start, offset, role))
    return tokens


def _resolve_role(tok_type) -> ColorRole | None:
    for key, role in _ROLE_MAP.items():
        if tok_type in key:
            return role
    return None
