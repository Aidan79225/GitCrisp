from __future__ import annotations

from .tokens import Theme

# Global QSS is intentionally empty for now.
#
# Why: the existing widgets still use hardcoded colors via per-widget
# setStyleSheet calls and QColor literals (migration tasks 9-13 in the
# plan). A global QSS rule on QWidget cascades to *every* descendant —
# including QScrollBar — which forces Qt out of native rendering and
# produces a worse-looking app than before.
#
# After widgets are migrated to read colors from the Theme, we can add
# back targeted QSS rules that don't fight per-widget styling.
QSS_TEMPLATE = ""


def render(theme: Theme) -> str:
    return QSS_TEMPLATE
