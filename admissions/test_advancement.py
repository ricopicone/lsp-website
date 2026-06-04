"""Tests for formation advancement — the palimpsest/passage demande pipeline."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.advisor import set_advisor
from accounts.models import MembershipTenure, Profile, User
from admissions.advancement import (
    can_open_advancement,
    decide_advancement,
    kind_for,
    open_advancement,
    present_advancement,
)
from admissions.models import Advancement

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.EXTERNAL, **kw):
    u = User.objects.create_user(email=email, password="x", **kw)
    u.profile.role = role
    u.profile.save()
    return u


def _precandidate(email="pc@x.test", advisor=None):
    u = _user(email, role=Profile.Role.PRE_CANDIDATE)
    if advisor is not None:
        set_advisor(u, advisor, by=u)
    return u


def _analyst(email="an@x.test"):
    return _user(email, role=Profile.Role.ANALYST)


# ---- eligibility -----------------------------------------------------------

def test_kind_for_role():
    assert kind_for(_precandidate("a@x.test")) == Advancement.Kind.PALIMPSEST
    assert kind_for(_user("cand@x.test", role=Profile.Role.CANDIDATE)) == Advancement.Kind.PASSAGE
    assert kind_for(_analyst("an2@x.test")) is None


def test_can_open_blocked_by_existing_open():
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    assert can_open_advancement(member) is True
    open_advancement(member, statement="ready")
    assert can_open_advancement(member) is False  # one in flight already


# ---- service flow ----------------------------------------------------------

def test_open_snapshots_advisor_and_role_and_emails(django_capture_on_commit_callbacks):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    with django_capture_on_commit_callbacks(execute=True):
        adv = open_advancement(member, statement="I am ready for the palimpsest.")
    assert adv.advisor == advisor
    assert adv.from_role == Profile.Role.PRE_CANDIDATE
    assert adv.kind == Advancement.Kind.PALIMPSEST
    assert adv.advance_role == Profile.Role.CANDIDATE
    assert any(advisor.email in m.to for m in mail.outbox)


def test_present_marks_presented_and_emails_member(django_capture_on_commit_callbacks):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    adv = open_advancement(member, statement="ready")
    with django_capture_on_commit_callbacks(execute=True):
        present_advancement(adv, recommendation="Strongly recommend.", by=advisor)
    adv.refresh_from_db()
    assert adv.status == Advancement.Status.PRESENTED
    assert adv.presented_at is not None
    assert any(member.email in m.to for m in mail.outbox)


def test_approve_advances_role_and_writes_tenure(django_capture_on_commit_callbacks):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    adv = open_advancement(member, statement="ready")
    present_advancement(adv, recommendation="yes", by=advisor)
    with django_capture_on_commit_callbacks(execute=True):
        decide_advancement(adv, approve=True, by=advisor, effective_ay=2026, note="Bravo")
    adv.refresh_from_db()
    member.profile.refresh_from_db()
    assert adv.status == Advancement.Status.APPROVED
    assert member.profile.role == Profile.Role.CANDIDATE
    t = MembershipTenure.objects.get(user=member, end_ay__isnull=True)
    assert t.role == Profile.Role.CANDIDATE and t.start_ay == 2026
    assert any("approved" in m.subject.lower() for m in mail.outbox)


def test_decline_leaves_role(django_capture_on_commit_callbacks):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    adv = open_advancement(member, statement="ready")
    with django_capture_on_commit_callbacks(execute=True):
        decide_advancement(adv, approve=False, by=advisor, note="not yet")
    adv.refresh_from_db()
    member.profile.refresh_from_db()
    assert adv.status == Advancement.Status.DECLINED
    assert member.profile.role == Profile.Role.PRE_CANDIDATE


# ---- views -----------------------------------------------------------------

def test_member_must_choose_advisor_first(client):
    member = _precandidate()  # no advisor
    client.force_login(member)
    resp = client.post(reverse("admissions:advancement"), {"statement": "ready"})
    assert resp.status_code == 302
    # Bounced back to the Formation hub (where the Advisor picker lives) — no
    # demande opened until an Advisor is chosen.
    assert reverse("admissions:formation") in resp.url
    assert not Advancement.objects.filter(member=member).exists()


def test_member_opens_demande_via_view(client, django_capture_on_commit_callbacks):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    client.force_login(member)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("admissions:advancement"), {"statement": "I am ready."})
    assert resp.status_code == 302
    assert Advancement.objects.filter(member=member, status="requested").exists()


def test_advisor_presents_via_view(client):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    adv = open_advancement(member, statement="ready")
    client.force_login(advisor)
    resp = client.post(reverse("admissions:advise_present", args=[adv.pk]), {
        f"a{adv.pk}-recommendation": "I recommend them.",
        f"a{adv.pk}-presented_at": "",
    })
    assert resp.status_code == 302
    adv.refresh_from_db()
    assert adv.status == Advancement.Status.PRESENTED


def test_advancement_review_gated(client):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    open_advancement(member, statement="ready")
    # Non-analyst can't reach the Meeting's review surface.
    client.force_login(_user("nobody@x.test", role=Profile.Role.MEMBER))
    assert client.get(reverse("admissions:advancement_queue")).status_code == 403
    client.force_login(_analyst("rev@x.test"))
    assert client.get(reverse("admissions:advancement_queue")).status_code == 200


def test_decide_via_view_approves(client, django_capture_on_commit_callbacks):
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    adv = open_advancement(member, statement="ready")
    present_advancement(adv, recommendation="yes", by=advisor)
    client.force_login(_analyst("rev2@x.test"))
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("admissions:advancement_decide", args=[adv.pk]), {
            "decision": "approve", "effective_ay": "2026",
        })
    assert resp.status_code == 302
    member.profile.refresh_from_db()
    assert member.profile.role == Profile.Role.CANDIDATE


# ---- reminders -------------------------------------------------------------

def test_reminder_sends_then_throttles_then_stops_after_presented():
    advisor = _analyst()
    member = _precandidate(advisor=advisor)
    adv = open_advancement(member, statement="ready")
    mail.outbox.clear()

    call_command("send_advancement_reminders")
    assert any(advisor.email in m.to for m in mail.outbox)
    adv.refresh_from_db()
    assert adv.last_reminded_at is not None

    # Within the interval → throttled.
    mail.outbox.clear()
    call_command("send_advancement_reminders")
    assert mail.outbox == []

    # Force the throttle open, but presented demandes are no longer reminded.
    present_advancement(adv, recommendation="done", by=advisor)
    Advancement.objects.filter(pk=adv.pk).update(
        last_reminded_at=timezone.now() - datetime.timedelta(days=30)
    )
    mail.outbox.clear()
    call_command("send_advancement_reminders")
    assert mail.outbox == []


# ---- admin surface ---------------------------------------------------------

def test_meeting_of_analysts_admin_reachable_by_analyst(client):
    client.force_login(_analyst("moa@x.test"))
    resp = client.get(reverse("meeting_of_analysts_admin"))
    assert resp.status_code == 200
    assert b"Meeting of Analysts Admin" in resp.content


def test_meeting_of_analysts_admin_denied_to_member(client):
    client.force_login(_user("plain2@x.test", role=Profile.Role.MEMBER))
    assert client.get(reverse("meeting_of_analysts_admin")).status_code == 403
