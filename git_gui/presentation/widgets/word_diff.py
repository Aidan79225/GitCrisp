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
