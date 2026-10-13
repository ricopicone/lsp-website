"""Test builders for the elections app."""

from __future__ import annotations

from datetime import timedelta
from itertools import count

from django.utils import timezone

from accounts.models import User
from elections.models import Election, Nomination

_n = count(1)


def make_member(email=None, role="analyst", standing="active", first="Mem", last=None):
    i = next(_n)
    u = User.objects.create_user(
        email=email or f"m{i}@x.test", password="x",
        first_name=first, last_name=last or f"Ber{i}",
    )
    u.profile.role = role
    u.profile.standing = standing
    u.profile.save()
    return u


def make_election(phase="draft", **kw):
    """An election whose windows put ``timezone.now()`` in ``phase``."""
    now = timezone.now()
    d = timedelta(days=1)
    no, nc, vo, vc, slate = {
        "draft":      (now + d, now + 2 * d, now + 3 * d, now + 4 * d, False),
        "nominating": (now - d, now + d, now + 2 * d, now + 3 * d, False),
        "review":     (now - 2 * d, now - d, now + d, now + 2 * d, False),
        "slate":      (now - 3 * d, now - 2 * d, now + d, now + 2 * d, True),
        "voting":     (now - 3 * d, now - 2 * d, now - d, now + d, True),
        "closed":     (now - 4 * d, now - 3 * d, now - 2 * d, now - d, True),
    }[phase]
    defaults = dict(
        title="Board election", slug=f"board-{next(_n)}", seats=2,
        nominations_open_at=no, nominations_close_at=nc,
        voting_open_at=vo, voting_close_at=vc,
        slate_published_at=(nc if slate else None),
    )
    defaults.update(kw)
    return Election.objects.create(**defaults)


def make_nomination(election, user=None, status="accepted", letter="Why I would serve."):
    user = user or make_member()
    return Nomination.objects.create(
        election=election, user=user, letter=letter, status=status,
        role_at_submission=user.profile.role,
    )


def make_director(**kw):
    from datetime import date

    from committees.models import Committee
    from workgroups.models import WorkgroupMembership

    u = make_member(**kw)
    Committee.objects.get(slug="board").add_member(
        u, role=WorkgroupMembership.Role.MEMBER, start_date=date(2026, 1, 1),
    )
    return u


def make_administrator(**kw):
    from core.models import StaffRole

    u = make_member(**kw)
    StaffRole.objects.get(key=StaffRole.ELECTION_ADMINISTRATOR).holders.add(u)
    return u
