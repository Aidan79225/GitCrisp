"""Port-coverage test for Pygit2Repository.

Every abstract method declared on IRepositoryReader and IRepositoryWriter
must be resolvable on Pygit2Repository and callable. Guards against a
method accidentally dropped during the mixin extraction."""

from __future__ import annotations

import inspect

from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.infrastructure.pygit2 import Pygit2Repository


def _abstract_method_names(port) -> list[str]:
    return [
        name
        for name, obj in inspect.getmembers(port, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]


def test_pygit2_repository_implements_every_reader_method():
    for name in _abstract_method_names(IRepositoryReader):
        impl = getattr(Pygit2Repository, name, None)
        assert impl is not None, f"Pygit2Repository missing reader method: {name}"
        assert callable(impl), f"Pygit2Repository.{name} is not callable"


def test_pygit2_repository_implements_every_writer_method():
    for name in _abstract_method_names(IRepositoryWriter):
        impl = getattr(Pygit2Repository, name, None)
        assert impl is not None, f"Pygit2Repository missing writer method: {name}"
        assert callable(impl), f"Pygit2Repository.{name} is not callable"


def _port_params(fn) -> list[inspect.Parameter]:
    return [p for name, p in inspect.signature(fn).parameters.items() if name != "self"]


def _incompatibilities(port, impl_cls) -> list[str]:
    """Signature mismatches between a port's methods and their implementation.

    Presence alone is not enough: the callers live in `application`, which mypy
    checks against the *port*, while nothing type-checks the adapter against it
    (main.py, the only place the two meet, is outside mypy's file list). A
    renamed keyword or a newly-required parameter therefore reaches runtime
    unannounced.
    """
    problems: list[str] = []
    for name in _abstract_method_names(port):
        impl = getattr(impl_cls, name, None)
        if impl is None:
            continue  # covered by the presence tests above
        declared = _port_params(getattr(port, name))
        implemented = _port_params(impl)
        if any(
            p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for p in implemented
        ):
            continue  # *args/**kwargs accepts whatever the port declares

        by_name = {p.name: p for p in implemented}
        positional_kinds = (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        declared_positional = [p.name for p in declared if p.kind in positional_kinds]
        implemented_positional = [p.name for p in implemented if p.kind in positional_kinds]
        if implemented_positional[: len(declared_positional)] != declared_positional:
            problems.append(
                f"{impl_cls.__name__}.{name} takes {implemented_positional}, "
                f"port declares {declared_positional}"
            )
            continue

        for p in declared:
            if p.kind is inspect.Parameter.KEYWORD_ONLY and p.name not in by_name:
                problems.append(f"{impl_cls.__name__}.{name} is missing keyword '{p.name}'")

        declared_names = {p.name for p in declared}
        for p in implemented:
            if p.name not in declared_names and p.default is inspect.Parameter.empty:
                problems.append(
                    f"{impl_cls.__name__}.{name} requires '{p.name}', which no caller passes"
                )
    return problems


def test_pygit2_repository_reader_signatures_match_the_port():
    assert _incompatibilities(IRepositoryReader, Pygit2Repository) == []


def test_pygit2_repository_writer_signatures_match_the_port():
    assert _incompatibilities(IRepositoryWriter, Pygit2Repository) == []
