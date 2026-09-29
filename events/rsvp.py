"""RSVPs for the School's own gatherings (task #756).

A Day of Assembly or Working Day admits every member without registration, so
the Register button is gone from them; the RSVP takes its place as a headcount
the Program Committee can plan by — for a hybrid gathering, the in-person
headcount in particular. It gates nothing: a member who never RSVPs still
joins, and one who RSVPs is told nothing they wouldn't be told anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Event, EventRSVP


def can_rsvp(event, user) -> bool:
    """Members RSVP to a gathering; guests register instead."""
    return event.admits_member(user)


def asks_attendance(event) -> bool:
    """Only a hybrid gathering needs to know *how* someone is coming."""
    return event.format == Event.Format.HYBRID


def implied_attendance(event) -> str:
    """The attendance an RSVP records when the event's format already says it."""
    if event.format == Event.Format.IN_PERSON:
        return EventRSVP.Attendance.IN_PERSON
    return EventRSVP.Attendance.ONLINE


def record(event, user, attendance: str = "") -> EventRSVP:
    """Record or update ``user``'s RSVP. A hybrid event needs ``attendance``;
    any other takes the format's. Raises ``ValueError`` on a missing or
    unknown choice, and ``PermissionError`` for someone who can't RSVP."""
    if not can_rsvp(event, user):
        raise PermissionError("Only members RSVP to this event.")
    if asks_attendance(event):
        if attendance not in EventRSVP.Attendance.values:
            raise ValueError("Choose in person or online.")
    else:
        attendance = implied_attendance(event)
    rsvp, _ = EventRSVP.objects.update_or_create(
        event=event, user=user, defaults={"attendance": attendance},
    )
    return rsvp


def withdraw(event, user) -> bool:
    """Remove ``user``'s RSVP; True if there was one."""
    deleted, _ = EventRSVP.objects.filter(event=event, user=user).delete()
    return bool(deleted)


@dataclass(frozen=True)
class Summary:
    total: int
    in_person: int
    online: int
    rsvps: list


def summary(event) -> Summary:
    """Counts and the list, for the people running the event."""
    rsvps = list(event.rsvps.select_related("user"))
    in_person = sum(1 for r in rsvps if r.attendance == EventRSVP.Attendance.IN_PERSON)
    return Summary(
        total=len(rsvps), in_person=in_person, online=len(rsvps) - in_person,
        rsvps=rsvps,
    )
