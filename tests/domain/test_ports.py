from unittest.mock import MagicMock
from git_gui.domain.ports import IRepositoryReader, IRepositoryWriter
from git_gui.domain.entities import Commit, Branch, FileStatus, Hunk
from datetime import datetime


def _make_commit():
    return Commit(oid="abc", message="msg", author="A", timestamp=datetime.now(), parents=[])


def test_reader_protocol_methods():
    reader = MagicMock(spec=IRepositoryReader)
    commit = _make_commit()
    reader.get_commits.return_value = [commit]
    reader.get_branches.return_value = []
    reader.get_commit_files.return_value = []
    reader.get_file_diff.return_value = []
    reader.get_working_tree.return_value = []
    reader.get_stashes.return_value = []

    assert reader.get_commits(limit=10) == [commit]
    assert reader.get_branches() == []


def test_writer_protocol_methods():
    writer = MagicMock(spec=IRepositoryWriter)
    commit = _make_commit()
    writer.commit.return_value = commit

    writer.stage(["file.py"])
    writer.stage.assert_called_once_with(["file.py"])

    result = writer.commit("msg")
    assert result == commit
