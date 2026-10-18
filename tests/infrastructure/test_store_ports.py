"""Port conformance for the JSON-backed stores main.py hands to MainWindow.

MainWindow and its mixins only ever see IRepoStore and IRemoteTagCache, so a
method the presentation layer calls has to be on the port, or a fake built
from the port fails with AttributeError where the real store would not."""

from __future__ import annotations

import inspect

import pytest

from git_gui.domain.ports import IRemoteTagCache, IRepoStore
from git_gui.infrastructure.remote_tag_cache import JsonRemoteTagCache
from git_gui.infrastructure.repo_store import JsonRepoStore
from tests.infrastructure.test_pygit2_ports import _abstract_method_names, _incompatibilities

_STORES = [(IRepoStore, JsonRepoStore), (IRemoteTagCache, JsonRemoteTagCache)]


def _public_methods(cls) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


@pytest.mark.parametrize(("port", "impl"), _STORES)
def test_the_store_implements_every_port_method(port, impl):
    assert set(_abstract_method_names(port)) <= _public_methods(impl)


@pytest.mark.parametrize(("port", "impl"), _STORES)
def test_the_store_signatures_match_the_port(port, impl):
    assert _incompatibilities(port, impl) == []


@pytest.mark.parametrize(("port", "impl"), _STORES)
def test_the_port_declares_everything_the_store_offers(port, impl):
    assert _public_methods(impl) - set(_abstract_method_names(port)) == set()
