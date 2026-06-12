"""Tests for the referral workflow (task #229)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.models import StaffRole

from . import services
from .models import (
    MessageTemplate,
    Mode,
    ReferralListMember,
    ReferralRequest,
    ReferralResponse,
    ReferralSettings,
)

pytestmark = pytest.mark.django_db


# ---- Fixtures ------------------------------------------------------------


@pytest.fixture
def coordinator():
    user = User.objects.create_user(
        email="diana@example.com", password="pw",
        first_name="Diana", last_name="Cuello",
    )
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.REFERRAL_COORDINATOR,
        defaults={"name": "Referral Coordinator"},
    )
    role.holders.add(user)
    return user


@pytest.fixture
def clinician():
    user = User.objects.create_user(
        email="analyst@example.com", password="pw",
        first_name="Anna", last_name="Analyst",
    )
    profile = user.profile
    profile.credentials = "PhD"
    profile.public_email = "anna.practice@example.com"
    profile.website = "https://anna.example.com"
    profile.save()
    return user


@pytest.fixture
def listed(clinician):
    return ReferralListMember.objects.create(
        user=clinician, onboarded_at=timezone.now(),
    )


def make_request(**overrides) -> ReferralRequest:
    defaults = dict(
        name="Alex Patient",
        pronouns="they/them",
        email="inquirer@example.com",
        location="Brooklyn, NY",
        language="English",
        modalities="By online video",
        additional_information="Looking for a Lacanian analyst.",
    )
    defaults.update(overrides)
    return ReferralRequest.objects.create(**defaults)


INTAKE_DATA = {
    "name": "Alex Patient",
    "pronouns": "they/them",
    "email": "inquirer@example.com",
    "location": "Brooklyn, NY",
    "language": "English",
    "modality": "By online video",
    "additional_information": "Looking for a Lacanian analyst.",
}


# ---- Template rendering ---------------------------------------------------


def test_render_template_substitutes_known_tokens_only():
    out = services.render_template(
        "Dear {name}, re {reference}: {unknown} stays {literal",
        {"name": "Alex", "reference": "R-2026-001"},
    )
    assert out == "Dear Alex, re R-2026-001: {unknown} stays {literal"


def test_message_template_get_restores_deleted_row():
    MessageTemplate.objects.filter(
        key=MessageTemplate.Key.ACKNOWLEDGMENT
    ).delete()
    tpl = MessageTemplate.get(MessageTemplate.Key.ACKNOWLEDGMENT)
    assert "Thank you very much for contacting" in tpl.body


# ---- Reference allocation --------------------------------------------------


def test_references_are_sequential_per_year():
    year = timezone.now().year
    first = make_request()
    second = make_request(email="other@example.com")
    assert first.reference == f"R-{year}-001"
    assert second.reference == f"R-{year}-002"


# ---- Intake (steps 1–2) -----------------------------------------------------


def test_intake_persists_and_sends_inquiry_and_ack(settings):
    settings.REFERRALS_EMAIL = "referrals@lacanschool.org"
    req = services.intake(INTAKE_DATA)
    assert req.pk and req.status == ReferralRequest.Status.ACKNOWLEDGED
    assert req.acknowledged_at is not None

    inquiry = next(
        m for m in mail.outbox if m.to == ["referrals@lacanschool.org"]
    )
    assert req.reference in inquiry.subject
    assert inquiry.reply_to == ["inquirer@example.com"]

    ack = next(m for m in mail.outbox if m.to == ["inquirer@example.com"])
    assert "Received your request for referral" in ack.subject
    assert "Dear Alex Patient," in ack.body
    assert "Diana C. Cuello" in ack.body
    assert ack.reply_to == ["referrals@lacanschool.org"]


def test_intake_review_mode_skips_ack():
    config = ReferralSettings.load()
    config.ack_mode = Mode.REVIEW
    config.save()
    req = services.intake(INTAKE_DATA)
    assert req.status == ReferralRequest.Status.NEW
    assert req.acknowledged_at is None
    assert all(m.to != ["inquirer@example.com"] for m in mail.outbox)


def test_intake_survives_email_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(services.emails, "send_coordinator_inquiry", _boom)
    monkeypatch.setattr(services.emails, "send_to_requester", _boom)
    req = services.intake(INTAKE_DATA)
    assert req.pk is not None


def test_intake_auto_distribution_when_enabled(
    listed, django_capture_on_commit_callbacks,
):
    config = ReferralSettings.load()
    config.distribution_mode = Mode.AUTO
    config.save()
    with django_capture_on_commit_callbacks(execute=True):
        req = services.intake(INTAKE_DATA)
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    assert any(m.to == ["analyst@example.com"] for m in mail.outbox)


# ---- Distribution (step 3) --------------------------------------------------


def test_distribute_emails_active_clinicians_anonymized(
    listed, django_capture_on_commit_callbacks,
):
    req = make_request()
    with django_capture_on_commit_callbacks(execute=True):
        count = services.distribute(req)
    assert count == 1
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    assert req.responses_due_at is not None

    msg = next(m for m in mail.outbox if m.to == ["analyst@example.com"])
    assert req.reference in msg.subject
    # Name and email are the two withheld fields.
    assert "Alex Patient" not in msg.body
    assert "inquirer@example.com" not in msg.body
    assert "Brooklyn, NY" in msg.body
    assert f"/referrals/{req.reference}/respond/" in msg.body


def test_distribute_skips_inactive_members(listed):
    listed.is_active = False
    listed.save()
    req = make_request()
    assert services.distribute(req) == 0


def test_distribution_window_respects_settings(listed):
    config = ReferralSettings.load()
    config.response_window_days = 21
    config.save()
    req = make_request()
    services.distribute(req)
    req.refresh_from_db()
    delta = req.responses_due_at - req.distributed_at
    assert timedelta(days=20, hours=23) < delta < timedelta(days=21, hours=1)


# ---- Respond page (step 4) --------------------------------------------------


def test_respond_requires_active_list_membership(client):
    outsider = User.objects.create_user(email="x@example.com", password="pw")
    req = make_request()
    client.force_login(outsider)
    resp = client.get(
        reverse("referrals:respond", args=[req.reference]),
    )
    assert resp.status_code == 403


def test_clinician_can_respond_and_update(client, listed, clinician):
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    client.force_login(clinician)
    url = reverse("referrals:respond", args=[req.reference])
    assert client.get(url).status_code == 200

    resp = client.post(url, {"available": "True", "message": "Happy to."})
    assert resp.status_code == 302
    response = ReferralResponse.objects.get(request=req, member=listed)
    assert response.available and response.message == "Happy to."

    client.post(url, {"available": "False", "message": ""})
    response.refresh_from_db()
    assert not response.available
    assert ReferralResponse.objects.filter(request=req).count() == 1


def test_respond_blocked_when_closed(client, listed, clinician):
    req = make_request(status=ReferralRequest.Status.CLOSED)
    client.force_login(clinician)
    url = reverse("referrals:respond", args=[req.reference])
    assert client.get(url).status_code == 200  # read-only notice
    assert client.post(url, {"available": "True"}).status_code == 403


# ---- Follow-up (step 5) ------------------------------------------------------


def test_followup_variant_none_substitutes_location():
    req = make_request()
    subject, body = services.build_followup(req)
    assert "no responses to your request" in body
    assert "membership in Brooklyn, NY is limited" in body


def test_followup_variant_single_includes_profile_details(listed):
    req = make_request()
    ReferralResponse.objects.create(request=req, member=listed)
    subject, body = services.build_followup(req)
    assert "the name of the clinician" in body
    assert "Anna Analyst" in body
    assert "PhD" in body
    assert "anna.practice@example.com" in body
    assert "https://anna.example.com" in body


def test_followup_variant_many_and_override(listed):
    other = User.objects.create_user(
        email="b@example.com", password="pw",
        first_name="Ben", last_name="Borromean",
    )
    member_b = ReferralListMember.objects.create(
        user=other, details_override="Ben B., LCSW\n555-0100",
    )
    req = make_request()
    ReferralResponse.objects.create(request=req, member=listed)
    ReferralResponse.objects.create(request=req, member=member_b)
    ReferralResponse.objects.create(  # not available: excluded
        request=req,
        member=ReferralListMember.objects.create(
            user=User.objects.create_user(email="c@example.com", password="pw"),
        ),
        available=False,
    )
    subject, body = services.build_followup(req)
    assert "the names of clinicians" in body
    assert "Anna Analyst" in body
    assert "Ben B., LCSW\n555-0100" in body  # override used verbatim
    assert "c@example.com" not in body


def test_send_followup_marks_replied(settings):
    req = make_request()
    services.send_followup(req, "Subject", "Body")
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.REPLIED
    assert req.replied_at is not None
    msg = mail.outbox[-1]
    assert msg.to == ["inquirer@example.com"]


# ---- Referral list + onboarding ---------------------------------------------


def test_add_to_list_sends_onboarding_in_auto_mode(clinician):
    member = services.add_to_list(clinician)
    assert member.onboarded_at is not None
    msg = mail.outbox[-1]
    assert msg.to == ["analyst@example.com"]
    assert msg.subject == "New Member Instructions"
    assert "Dear Anna Analyst," in msg.body
    assert "/accounts/profile/" in msg.body
    assert "update it in your profile" in msg.body


def test_add_to_list_review_mode_defers_onboarding(clinician):
    config = ReferralSettings.load()
    config.onboarding_mode = Mode.REVIEW
    config.save()
    member = services.add_to_list(clinician)
    assert member.onboarded_at is None
    assert mail.outbox == []


def test_add_to_list_reactivates_and_does_not_reonboard(clinician):
    member = services.add_to_list(clinician)
    sent = len(mail.outbox)
    member.is_active = False
    member.save()
    again = services.add_to_list(clinician)
    assert again.pk == member.pk and again.is_active
    assert len(mail.outbox) == sent


# ---- Retention / redaction ----------------------------------------------------


def test_purge_redacts_old_replied_requests():
    old = make_request()
    old.status = ReferralRequest.Status.REPLIED
    old.replied_at = timezone.now() - timedelta(days=400)
    old.coordinator_notes = "sensitive"
    old.save()
    recent = make_request(email="recent@example.com")
    recent.status = ReferralRequest.Status.REPLIED
    recent.replied_at = timezone.now() - timedelta(days=10)
    recent.save()

    assert services.purge_expired() == 1
    old.refresh_from_db()
    recent.refresh_from_db()
    assert old.is_purged
    assert old.name == "(redacted)" and old.email == ""
    assert "redacted" in old.additional_information
    assert old.coordinator_notes == ""
    assert not recent.is_purged and recent.name == "Alex Patient"


# ---- Permissions ----------------------------------------------------------------


def test_dashboard_forbidden_without_role(client):
    user = User.objects.create_user(email="m@example.com", password="pw")
    client.force_login(user)
    assert client.get(reverse("referrals:dashboard")).status_code == 403


def test_dashboard_forbidden_for_generic_staff(client):
    user = User.objects.create_user(
        email="staff@example.com", password="pw", is_staff=True,
    )
    client.force_login(user)
    assert client.get(reverse("referrals:dashboard")).status_code == 403


def test_coordinator_can_use_surface(client, coordinator):
    client.force_login(coordinator)
    req = make_request()
    assert client.get(reverse("referrals:dashboard")).status_code == 200
    assert client.get(
        reverse("referrals:detail", args=[req.reference])
    ).status_code == 200
    assert client.get(reverse("referrals:templates")).status_code == 200
    assert client.get(reverse("referrals:clinicians")).status_code == 200
    assert client.get(reverse("referrals:settings")).status_code == 200


def test_coordinator_actions_roundtrip(client, coordinator, listed):
    client.force_login(coordinator)
    req = make_request()
    # Acknowledge.
    client.post(reverse("referrals:send_ack", args=[req.reference]))
    req.refresh_from_db()
    assert req.acknowledged_at is not None
    # Record a manual response (escape hatch).
    client.post(
        reverse("referrals:record_response", args=[req.reference]),
        {"member": listed.pk, "available": "True", "message": "By phone."},
    )
    response = ReferralResponse.objects.get(request=req, member=listed)
    assert response.recorded_by == coordinator
    # Compose page prefills the draft; sending marks REPLIED.
    page = client.get(reverse("referrals:followup", args=[req.reference]))
    assert b"Anna Analyst" in page.content
    client.post(
        reverse("referrals:followup", args=[req.reference]),
        {"subject": "Re: your referral", "body": "Names below."},
    )
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.REPLIED
    # Close + reopen.
    client.post(reverse("referrals:close", args=[req.reference]))
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.CLOSED
    client.post(reverse("referrals:reopen", args=[req.reference]))
    req.refresh_from_db()
    assert req.status != ReferralRequest.Status.CLOSED


def test_template_edit_changes_outgoing_mail(client, coordinator):
    client.force_login(coordinator)
    client.post(
        reverse("referrals:template_edit", args=["acknowledgment"]),
        {"subject": "We hear you, {name}", "body": "Soon, {name}."},
    )
    req = make_request()
    services.send_acknowledgment(req)
    msg = mail.outbox[-1]
    assert msg.subject == "We hear you, Alex Patient"
    assert msg.body == "Soon, Alex Patient."


# ---- Cron command ---------------------------------------------------------------


def test_process_referrals_auto_followup(listed, django_capture_on_commit_callbacks):
    from django.core.management import call_command

    config = ReferralSettings.load()
    config.followup_mode = Mode.AUTO
    config.save()
    req = make_request()
    with django_capture_on_commit_callbacks(execute=True):
        services.distribute(req)
    ReferralRequest.objects.filter(pk=req.pk).update(
        responses_due_at=timezone.now() - timedelta(hours=1),
    )
    ReferralResponse.objects.create(request=req, member=listed)

    call_command("process_referrals")
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.REPLIED
    msg = next(m for m in mail.outbox if m.to == ["inquirer@example.com"])
    assert "Anna Analyst" in msg.body


def test_process_referrals_review_mode_leaves_requests(listed):
    from django.core.management import call_command

    req = make_request(
        status=ReferralRequest.Status.DISTRIBUTED,
    )
    ReferralRequest.objects.filter(pk=req.pk).update(
        responses_due_at=timezone.now() - timedelta(hours=1),
    )
    call_command("process_referrals")
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.DISTRIBUTED
