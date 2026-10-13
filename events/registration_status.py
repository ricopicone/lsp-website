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

#: Why registration can't open on an event whose fee is to be announced.
FEE_TBA_REFUSAL = (
    "The fee is still to be announced, so registration can't open yet. "
    "Set the fee on the event's edit page first."
)


def open_refusal(event: Event) -> str | None:
    """Why ``event`` can't open for registration, or ``None`` when it can.

    A fee to be announced (task #769) has no price tier, so a register page
    would have nothing to charge. This is refused rather than warned about,
    unlike a merely missing tier: the PC chose "to be announced" on purpose,
    and setting the fee is the one step that clears it.
    """
    if event.fee_tba:
        return FEE_TBA_REFUSAL
    return None


def set_registration_status(event: Event, action: str) -> str | None:
    """Apply ``action`` ("open" or "close") to ``event``.

    Returns the new status, or ``None`` when the action is a no-op for the
    event's current status — including an unrecognized action — or when
    :func:`open_refusal` blocks the opening, so a caller can tell a real flip
    from a double-pressed button (check ``open_refusal`` first to say why).
    Publishing (``Event.published``) is a separate decision and is never
    touched here.
    """
    if action == "open" and open_refusal(event):
        return None
    if action == "open" and event.status in OPENABLE:
        new_status = Event.Status.OPEN
    elif action == "close" and event.status == Event.Status.OPEN:
        new_status = Event.Status.CLOSED
    else:
        return None
    event.status = new_status
    event.save(update_fields=("status",))
    return new_status
