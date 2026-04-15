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
