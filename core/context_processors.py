"""Template context processors for the ``core`` app."""

from __future__ import annotations

import random

from .aphorisms import APHORISMS


def aphorism(request):
    """One Lacanian aphorism per page render. Surfaces in the footer."""
    return {"aphorism": random.choice(APHORISMS) if APHORISMS else None}
