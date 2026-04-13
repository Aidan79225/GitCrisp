from __future__ import annotations
import pytest
from PySide6.QtWidgets import QDialogButtonBox
from git_gui.domain.entities import MergeStrategy
from git_gui.presentation.dialogs.merge_dialog import MergeDialog, MergeRequest


def test_default_strategy_is_no_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="Merge branch 'feature'")
    qtbot.addWidget(dlg)
    assert dlg._radio_no_ff.isChecked()


def test_ff_possible_all_radios_enabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    assert dlg._radio_no_ff.isEnabled()
    assert dlg._radio_ff_only.isEnabled()
    assert dlg._radio_allow_ff.isEnabled()


def test_ff_not_possible_ff_only_disabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    assert dlg._radio_ff_only.isEnabled() is False
    assert "Cannot fast-forward" in dlg._radio_ff_only.toolTip()


def test_no_ff_message_editor_enabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_no_ff.setChecked(True)
    assert dlg._message_edit.isEnabled() is True


def test_ff_only_message_editor_disabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_ff_only.setChecked(True)
    assert dlg._message_edit.isEnabled() is False


def test_allow_ff_can_ff_message_editor_disabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    assert dlg._message_edit.isEnabled() is False


def test_allow_ff_cannot_ff_message_editor_enabled(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    assert dlg._message_edit.isEnabled() is True


def test_analysis_label_can_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    assert "fast-forwarded" in dlg._analysis_label.text()


def test_analysis_label_cannot_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    assert "requires a merge commit" in dlg._analysis_label.text()


def test_result_value_no_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="Merge branch 'feature'")
    qtbot.addWidget(dlg)
    dlg._radio_no_ff.setChecked(True)
    dlg._message_edit.setPlainText("Custom message")
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.NO_FF
    assert result.message == "Custom message"


def test_result_value_ff_only(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_ff_only.setChecked(True)
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.FF_ONLY
    assert result.message is None


def test_result_value_allow_ff_can_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=True, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.ALLOW_FF
    assert result.message is None


def test_result_value_allow_ff_cannot_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    dlg._radio_allow_ff.setChecked(True)
    dlg._message_edit.setPlainText("Merge msg")
    result = dlg.result_value()
    assert result.strategy == MergeStrategy.ALLOW_FF
    assert result.message == "Merge msg"


def test_merge_button_disabled_when_ff_only_and_cannot_ff(qtbot):
    dlg = MergeDialog("feature", "main", can_ff=False, default_message="msg")
    qtbot.addWidget(dlg)
    # ff-only radio is disabled, but force it for safety-net test
    dlg._radio_ff_only.setEnabled(True)
    dlg._radio_ff_only.setChecked(True)
    merge_btn = dlg._buttons.button(QDialogButtonBox.Ok)
    assert merge_btn.isEnabled() is False
