"""The log line for an action skipped because another repo opened while the user was asked.

A confirmation box or dialog runs a nested event loop, and a repo switch
already on its way lands inside it. The window and each panel that asks
before acting check for that themselves, since each reports through its own
channel, but they word the skip here, so every one reads alike. It sits
outside main_window because widgets must not import the window's package.
"""

from __future__ import annotations


def skipped_after_repo_switch(op_name: str) -> str:
    """What the log says when another repo opened while the user was asked about *op_name*."""
    return f"{op_name} — skipped: another repo opened while you were deciding. Nothing was changed."
