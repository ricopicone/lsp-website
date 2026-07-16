"""The Meeting sees tuition standing and cannot approve past it (task #439)."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.advisor import set_advisor
from accounts.models import Profile, User
from formation.advancement import decide_advancement, open_advancement, present_advancement
from formation.models import Advancement
from payments.models import Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()


def _user(email, role=Profile.Role.EXTERNAL, **kw):
    u = User.objects.create_user(email=email, password="x", **kw)
    u.profile.role = role
    u.profile.save()
    return u


def _analyst(email="an@x.test"):
    return _user(email, role=Profile.Role.ANALYST)


def _candidate(email="cand@x.test", advisor=None):
    u = _user(email, role=Profile.Role.CANDIDATE)
    if advisor is not None:
        set_advisor(u, advisor, by=u)
    return u


def _year(start, amount="2000"):
    return TuitionPeriod.objects.create(
        name=f"AY {start}-{start + 1}", slug=f"gate-{start}",
        start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
        decision_due_date=date(start, 8, 31), tuition_amount=Decimal(amount))


def _enroll(u, tp, status=TuitionEnrollment.Status.COMMITTED):
    return TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=status, source="staff")


def _pay(u, amount):
    p = Payment.objects.create(
        user=u, payment_type=Payment.Type.TUITION, amount=Decimal(amount),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=p.pk).update(
        paid_at=datetime(2025, 10, 1, tzinfo=tz.utc))


def _owing_candidate(email="owe@x.test", advisor=None):
    """A Candidate with an open, unpaid tuition charge — blocked."""
    u = _candidate(email, advisor=advisor)
    _enroll(u, _year(2021))
    return u


def _settled_candidate(email="ok@x.test", advisor=None):
    """A Candidate with four fully-paid tuition years — clear."""
    u = _candidate(email, advisor=advisor)
    for i in range(4):
        _enroll(u, _year(2030 + i))
    _pay(u, "8000")
    return u


def _open_passage(member, advisor):
    """Open + present a Passage demande for ``member`` so it's ready for
    decision (mirrors formation/test_advancement.py's approve flow)."""
    adv = open_advancement(member, statement="I am ready.")
    present_advancement(adv, recommendation="Recommend.", by=advisor)
    return adv


# ---- service-layer pre-check ------------------------------------------------

def test_decide_blocked_leaves_advancement_open():
    advisor = _analyst()
    member = _owing_candidate(advisor=advisor)
    adv = _open_passage(member, advisor)

    with pytest.raises(ValidationError):
        decide_advancement(adv, approve=True, by=advisor, effective_ay=2026)

    adv.refresh_from_db()
    member.profile.refresh_from_db()
    assert adv.is_open
    assert member.profile.role == Profile.Role.CANDIDATE


def test_decline_never_blocked():
    advisor = _analyst()
    member = _owing_candidate(advisor=advisor)
    adv = _open_passage(member, advisor)

    # Should not raise — decline is never gated by tuition standing.
    decide_advancement(adv, approve=False, by=advisor, note="not yet")

    adv.refresh_from_db()
    member.profile.refresh_from_db()
    assert adv.status == Advancement.Status.DECLINED
    assert member.profile.role == Profile.Role.CANDIDATE


# ---- view-layer friendly error ---------------------------------------------

def test_decide_view_shows_friendly_error(client):
    advisor = _analyst()
    member = _owing_candidate(advisor=advisor)
    adv = _open_passage(member, advisor)

    client.force_login(_analyst("rev@x.test"))
    resp = client.post(reverse("formation:advancement_decide", args=[adv.pk]), {
        "decision": "approve", "effective_ay": "2026",
    })

    assert resp.status_code == 302
    assert resp.url == reverse("formation:advancement_detail", args=[adv.pk])
    messages = [str(m) for m in resp.wsgi_request._messages]
    assert any("Cannot approve" in m for m in messages)
    adv.refresh_from_db()
    assert adv.is_open


# ---- detail: tuition-standing panel -----------------------------------------

def test_detail_shows_tuition_standing(client):
    advisor = _analyst()
    blocked = _owing_candidate(email="blocked@x.test", advisor=advisor)
    blocked_adv = _open_passage(blocked, advisor)

    settled = _settled_candidate(email="settled@x.test", advisor=advisor)
    settled_adv = _open_passage(settled, advisor)

    client.force_login(_analyst("rev2@x.test"))

    resp = client.get(reverse("formation:advancement_detail", args=[blocked_adv.pk]))
    assert b"Tuition standing" in resp.content
    assert b"uncovered" in resp.content

    resp = client.get(reverse("formation:advancement_detail", args=[settled_adv.pk]))
    assert b"Tuition standing" in resp.content
    assert b"clear" in resp.content


# ---- queue: badge ------------------------------------------------------------

def test_queue_badges_blocked_rows(client):
    advisor = _analyst()
    member = _owing_candidate(advisor=advisor)
    _open_passage(member, advisor)

    client.force_login(_analyst("rev3@x.test"))
    resp = client.get(reverse("formation:advancement_queue"))
    assert b"tuition" in resp.content
