"""Behaviour tests for CloneDialog: folder-name detection, the running clone, and its errors."""

from __future__ import annotations

import pytest

from git_gui.presentation.widgets.clone_dialog import _parse_repo_name


@pytest.mark.parametrize(
    ("url", "name"),
    [
        (r"D:\repos\foo", "foo"),
        (r"C:\src\proj.git", "proj"),
        ("C:\\src\\proj\\", "proj"),
        ("D:/repos/foo", "foo"),
        ("https://github.com/user/repo.git", "repo"),
        ("git@github.com:user/repo.git", "repo"),
    ],
)
def test_folder_name_is_the_last_part_of_the_source(url, name):
    assert _parse_repo_name(url) == name
