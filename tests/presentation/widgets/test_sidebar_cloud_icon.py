"""Tags already on a remote carry a cloud icon in the sidebar.

The icon is the same for every pushed tag. Rendering it means parsing an SVG
and tinting it on the UI thread, which on a repo with thousands of pushed
tags took over a second per reload when it was done once per tag.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from git_gui.domain.entities import Tag
from git_gui.presentation.widgets.sidebar import SidebarWidget


@pytest.fixture
def sidebar(qtbot):
    sb = SidebarWidget(queries=MagicMock(), commands=MagicMock())
    qtbot.addWidget(sb)
    return sb


def _tag_rows(sb: SidebarWidget) -> dict:
    header = next(
        sb._model.item(r) for r in range(sb._model.rowCount()) if sb._model.item(r).text() == "TAGS"
    )
    return {header.child(r).text(): header.child(r) for r in range(header.rowCount())}


def _tags(*names: str) -> list[Tag]:
    return [
        Tag(
            name=n,
            target_oid=f"{n}-oid",
            is_annotated=False,
            message=None,
            tagger=None,
            timestamp=None,
        )
        for n in names
    ]


def test_pushed_tags_share_one_rendered_icon(sidebar):
    sidebar._on_load_done([], [], _tags("v1", "v2", "v3"), {"v1", "v2", "v3"}, {})

    icon_keys = {row.icon().cacheKey() for row in _tag_rows(sidebar).values()}

    assert len(icon_keys) == 1


def test_only_pushed_tags_carry_the_icon(sidebar):
    sidebar._on_load_done([], [], _tags("v1", "local-only"), {"v1"}, {})

    rows = _tag_rows(sidebar)

    assert not rows["v1"].icon().isNull()
    assert rows["local-only"].icon().isNull()
