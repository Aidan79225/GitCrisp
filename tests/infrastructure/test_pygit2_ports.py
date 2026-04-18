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
        name for name, obj in inspect.getmembers(port, predicate=inspect.isfunction)
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
