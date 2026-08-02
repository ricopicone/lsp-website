"""Resolve a member's effective delivery for a category.

The result combines the category defaults with any per-user override, then
applies the hard constraints (locked email, channel capability). This is the
single source of truth both :func:`notifications.dispatch.notify` and the
settings page rely on.

A category may vary its email default per recipient
(:attr:`~notifications.categories.CategoryMeta.default_email_for`) — used to
aim a queue's email at the role that owns it. Because the settings page reads
this same function, it shows each member their true effective delivery.
"""

from __future__ import annotations

from dataclasses import dataclass

from .categories import EmailDelivery, meta_for


@dataclass(frozen=True)
class Resolved:
    in_app: bool
    email: bool  # True == send an immediate email
    email_mode: str  # immediate | digest | off
    # Whether the member is allowed to change each channel on the settings page.
    in_app_editable: bool
    email_editable: bool


def resolve(user, category: str) -> Resolved:
    """Effective delivery of ``category`` for ``user``."""
    meta = meta_for(category)

    in_app = meta.default_in_app
    email_choice = meta.default_email
    # A category may aim its email at the role that owns it, so the default can
    # differ per recipient (a queue's Treasurer is emailed, the rest of the
    # committee gets the bell). A stored override still wins, below.
    if meta.default_email_for is not None:
        email_choice = meta.default_email_for(user)

    pref = getattr(user, "notification_preference", None)
    if pref is not None:
        override = pref.get(category)
        if "in_app" in override:
            in_app = bool(override["in_app"])
        if "email" in override:
            email_choice = override["email"]

    # Apply capability + lock constraints.
    if not meta.in_app_capable:
        in_app = False
    if meta.email_locked:
        email_mode = EmailDelivery.IMMEDIATE
    elif not meta.email_capable:
        email_mode = EmailDelivery.OFF
    else:
        email_mode = email_choice

    return Resolved(
        in_app=in_app,
        email=email_mode == EmailDelivery.IMMEDIATE,
        email_mode=email_mode,
        in_app_editable=meta.in_app_capable,
        email_editable=meta.email_capable and not meta.email_locked,
    )
