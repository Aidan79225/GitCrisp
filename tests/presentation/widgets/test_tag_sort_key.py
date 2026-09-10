"""Tests for the semantic-version tag sort key used in SidebarWidget."""

from __future__ import annotations

from git_gui.presentation.widgets.sidebar import _tag_sort_key


class TestTagSortKey:
    """_tag_sort_key should parse dot-separated numeric parts so that
    version-like tags sort by numeric value rather than string comparison."""

    def test_numeric_parts_compared_by_value(self):
        names = ["0.2.0", "0.10.0", "0.1.0"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        assert result == ["0.10.0", "0.2.0", "0.1.0"]

    def test_v_prefix_stripped(self):
        names = ["v1.0.0", "v0.9.0", "v1.2.0"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        assert result == ["v1.2.0", "v1.0.0", "v0.9.0"]

    def test_uppercase_v_prefix_stripped(self):
        names = ["V2.0", "V1.10", "V1.9"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        assert result == ["V2.0", "V1.10", "V1.9"]

    def test_non_numeric_tags_fall_back_to_string(self):
        names = ["beta", "alpha", "rc1"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        assert result == ["rc1", "beta", "alpha"]

    def test_numeric_tags_sort_before_non_numeric(self):
        key_numeric = _tag_sort_key("1.0.0")
        key_string = _tag_sort_key("release-candidate")
        assert key_numeric < key_string

    def test_single_component_version(self):
        names = ["3", "20", "1"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        assert result == ["20", "3", "1"]

    def test_mixed_numeric_and_non_numeric(self):
        names = ["v2.0.0", "nightly", "v1.0.0", "beta"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        # Non-numeric tags (True, ...) sort after numeric (False, ...) in reverse
        # In reverse=True: numeric descending first, then string descending
        # But since True > False, reverse makes False come first? Let's check:
        # Normal order: (False, [1,0,0]), (False, [2,0,0]), (True, "beta"), (True, "nightly")
        # reverse=True: (True, "nightly"), (True, "beta"), (False, [2,0,0]), (False, [1,0,0])
        assert result == ["nightly", "beta", "v2.0.0", "v1.0.0"]

    def test_real_world_sorting_scenario(self):
        names = ["0.1", "0.2.0", "0.10", "1.0.0", "0.9.1"]
        result = sorted(names, key=_tag_sort_key, reverse=True)
        assert result == ["1.0.0", "0.10", "0.9.1", "0.2.0", "0.1"]
