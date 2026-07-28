"""Coordinator release / mark-junk actions (#479)."""

import pytest
from django.urls import reverse

from accounts.models import User
from core.models import StaffRole
from referrals import services
from referrals.models import ReferralRequest

pytestmark = pytest.mark.django_db

JUNK = {
    "name": "LEIAZKMKtfUBswyJuaS",
    "pronouns": "IzNydkEnQFrKxxKl",
    "email": "spam@example.com",
    "location": "lfNxcMPRAZNciaxtfNPOMQK",
    "language": "iIcIlrhZIIwEImoxJld",
    "modality": "In person",
    "additional_information": "GtDlqAgHoujeYbXggDwPs",
}


@pytest.fixture
def coordinator(client):
    user = User.objects.create_user(
        email="diana@example.com", password="pw",
        first_name="Diana", last_name="Cuello",
    )
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.REFERRAL_COORDINATOR,
        defaults={"name": "Referral Coordinator"},
    )
    role.holders.add(user)
    client.force_login(user)
    return user


def test_mark_junk_sets_status_and_audit_note(client, coordinator):
    req = services.intake(dict(JUNK))
    resp = client.post(reverse("referrals:mark_junk", args=[req.reference]))
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.JUNK
    assert "junk" in req.coordinator_notes.lower()
    assert coordinator.email in req.coordinator_notes


def test_unmark_junk_restores_to_new(client, coordinator):
    req = services.intake(dict(JUNK))
    client.post(reverse("referrals:mark_junk", args=[req.reference]))
    client.post(reverse("referrals:unmark_junk", args=[req.reference]))
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.NEW


def test_release_clears_the_hold(client, coordinator):
    req = services.intake(dict(JUNK))
    assert req.status == ReferralRequest.Status.HELD
    client.post(reverse("referrals:release", args=[req.reference]))
    req.refresh_from_db()
    assert req.status != ReferralRequest.Status.HELD
    assert req.held_reason == ""


def test_actions_require_the_coordinator_role(client):
    req = services.intake(dict(JUNK))
    user = User.objects.create_user(email="nobody@example.com", password="pw")
    client.force_login(user)
    resp = client.post(reverse("referrals:mark_junk", args=[req.reference]))
    assert resp.status_code == 403


def test_dashboard_shows_held_count(client, coordinator):
    services.intake(dict(JUNK))
    resp = client.get(reverse("referrals:dashboard"))
    assert resp.context["held_count"] == 1


def test_dashboard_filters_to_held(client, coordinator):
    services.intake(dict(JUNK))
    resp = client.get(reverse("referrals:dashboard"), {"status": "held"})
    assert list(resp.context["requests"])[0].status == ReferralRequest.Status.HELD


def test_junk_is_excluded_from_the_open_filter(client, coordinator):
    req = services.intake(dict(JUNK))
    client.post(reverse("referrals:mark_junk", args=[req.reference]))
    resp = client.get(reverse("referrals:dashboard"), {"status": "open"})
    assert list(resp.context["requests"]) == []
