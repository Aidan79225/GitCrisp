from git_gui.domain.entities import RebaseAction


def test_each_action_formats_as_the_keyword_git_reads_in_a_todo_line():
    oid = "abc1234"
    assert [f"{action} {oid}" for action in RebaseAction] == [
        "pick abc1234",
        "squash abc1234",
        "fixup abc1234",
        "drop abc1234",
    ]
