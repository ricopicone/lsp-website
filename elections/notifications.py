"""Election notices (task #813): a bell row plus an email, through the one
notifications chokepoint. Batches pace their email through ThrottledSender
so a whole-membership send stays under the SES rate."""

from __future__ import annotations

from django.urls import reverse

from notifications.categories import Category
from notifications.dispatch import notify
from payments.sending import ThrottledSender

from . import emails


def tab_url() -> str:
    return reverse("formation:formation") + "?tab=election"


def _one(user, election, title, send):
    notify(user, Category.ELECTIONS, title=title, url=tab_url(), target=election,
           email_fn=lambda: send(user, election))


def _batch(users, election, title, send) -> int:
    sender = ThrottledSender()
    n = 0
    for u in users:
        notify(u, Category.ELECTIONS, title=title, url=tab_url(), target=election,
               email_fn=lambda u=u: sender.send(send, u, election))
        n += 1
    return n


def call(users, e) -> int:
    return _batch(users, e, f"Call for nominations: {e.title}", emails.send_call)


def candidacy_accepted(users, e) -> int:
    return _batch(users, e, f"Your candidacy is on the slate: {e.title}",
                  emails.send_candidacy_accepted)


def voting_open(users, e) -> int:
    return _batch(users, e, f"Voting is open: {e.title}", emails.send_voting_open)


def reminder(users, e) -> int:
    return _batch(users, e, f"Reminder, please vote: {e.title}", emails.send_reminder)


def results(users, e) -> int:
    return _batch(users, e, f"Results: {e.title}", emails.send_results)


def nomination_received(user, e) -> None:
    _one(user, e, f"Nomination received: {e.title}", emails.send_nomination_received)


def ballot_recorded(user, e) -> None:
    _one(user, e, f"Ballot recorded: {e.title}", emails.send_ballot_recorded)
