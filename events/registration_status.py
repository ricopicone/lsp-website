"""Opening and closing registration for one event.

``Event.status`` is what every registration surface reads — the register view's
gate (``registrations/views.py``), the event page's CTA, and the listing badge —
but flipping it lived only inside the Registrar console's own view, so the
faculty and conveners running an offering could not close their own
registration. This is the one definition of what open and close mean; the
console and the faculty control both call it, so they cannot drift.

The Programming Committee's per-program bulk view stays as it is: it flips a
whole program with a queryset ``update()`` and never touches one event.
"""

from __future__ import annotations

from .models import Event

#: Statuses that "open" flips to OPEN. A draft is included so the first opening
#: is the same action as a reopening, matching the Registrar console.
OPENABLE = (Event.Status.DRAFT, Event.Status.CLOSED)


def set_registration_status(event: Event, action: str) -> str | None:
    """Apply ``action`` ("open" or "close") to ``event``.

    Returns the new status, or ``None`` when the action is a no-op for the
    event's current status — including an unrecognized action — so a caller can
    tell a real flip from a double-pressed button. Publishing
    (``Event.published``) is a separate decision and is never touched here.
    """
    if action == "open" and event.status in OPENABLE:
        new_status = Event.Status.OPEN
    elif action == "close" and event.status == Event.Status.OPEN:
        new_status = Event.Status.CLOSED
    else:
        return None
    event.status = new_status
    event.save(update_fields=("status",))
    return new_status
