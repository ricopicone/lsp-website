"""Resolve a member's effective delivery for a category.

The result combines the category defaults with any per-user override, then
applies the hard constraints (locked email, channel capability). This is the
single source of truth both :func:`notifications.dispatch.notify` and the
settings page rely on.
"""

from __future__ import annotations

from dataclasses import dataclass

from .categories import EmailDelivery, meta_for


@dataclass(frozen=True)
class Resolved:
    in_app: bool
    email: bool  # True == send an immediate email
    # Whether the member is allowed to change each channel on the settings page.
    in_app_editable: bool
    email_editable: bool


def resolve(user, category: str) -> Resolved:
    """Effective delivery of ``category`` for ``user``."""
    meta = meta_for(category)

    in_app = meta.default_in_app
    email_choice = meta.default_email

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
        email = True
    elif not meta.email_capable:
        email = False
    else:
        email = email_choice == EmailDelivery.IMMEDIATE

    return Resolved(
        in_app=in_app,
        email=email,
        in_app_editable=meta.in_app_capable,
        email_editable=meta.email_capable and not meta.email_locked,
    )
