from __future__ import annotations

import threading
from collections.abc import Callable

# Runs a widget's slow read off the GUI thread. Widgets take one as a
# parameter, so a test can hold the work and run it in the order it chooses.
BackgroundRunner = Callable[[Callable[[], None]], None]


def start_daemon_thread(work: Callable[[], None]) -> None:
    """Run *work* on a daemon thread, so a read still going never holds the app open."""
    threading.Thread(target=work, daemon=True).start()
