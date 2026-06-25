"""Tests for the Applications Coordinator console (task #272)."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from accounts.models import Profile, User
from admissions.models import Application, ApplicationInterview, MessageTemplate
from committees.models import Committee
from workgroups.models import WorkgroupMembership

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.EXTERNAL, **kw):
    u = User.objects.create_user(email=email, password="x", **kw)
    u.profile.role = role
    u.profile.save()
    return u


@pytest.fixture
def coordinator(client):
    user = _user("cecile@x.test", role=Profile.Role.ANALYST,
                 first_name="Cecile", last_name="Gouffrant")
    wg = Committee.objects.get(slug="meeting-of-analysts").workgroup
    wg.add_member(user, role=WorkgroupMembership.Role.APPLICATIONS_COORDINATOR)
    client.force_login(user)
    return user


@pytest.fixture
def application():
    applicant = _user("applicant@x.test", first_name="Aimee", last_name="Applicant")
    return Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        letter_of_intent="x", status=Application.Status.INTERVIEWING,
        submitted_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
    )


def test_dashboard_gated_to_coordinator(client):
    client.force_login(_user("nobody@x.test", role=Profile.Role.ANALYST))
    assert client.get(reverse("admissions:coordinator_dashboard")).status_code == 403


def test_dashboard_lists_applications(client, coordinator, application):
    resp = client.get(reverse("admissions:coordinator_dashboard"))
    assert resp.status_code == 200
    assert b"Aimee Applicant" in resp.content


def test_nudge_emails_pending_interviewers(
    client, coordinator, application, django_capture_on_commit_callbacks
):
    iv1 = ApplicationInterview.objects.create(
        application=application, interviewer=_user("i1@x.test", role=Profile.Role.ANALYST),
    )
    # A completed interview should NOT be nudged.
    ApplicationInterview.objects.create(
        application=application, interviewer=_user("i2@x.test", role=Profile.Role.ANALYST),
        completed_at=datetime.date(2026, 6, 10), report="Done",
    )
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("admissions:coordinator_nudge", args=[application.pk])
        )
    assert resp.status_code == 302
    assert len(mail.outbox) == 1
    assert iv1.interviewer.email in mail.outbox[0].to
    assert mail.outbox[0].reply_to == ["applications@lacanschool.org"]


def test_message_edit_saves(client, coordinator):
    url = reverse("admissions:coordinator_message_edit",
                  args=[MessageTemplate.Key.INVITATION])
    assert client.get(url).status_code == 200
    resp = client.post(url, {"subject": "Invite", "body": "Hi {interviewer}, see {agree_url}."})
    assert resp.status_code == 302
    assert MessageTemplate.get(MessageTemplate.Key.INVITATION).subject == "Invite"


def test_panel_appears_for_coordinator(client, coordinator):
    resp = client.get(reverse("admin_tools"))
    assert resp.status_code == 200
    assert b"Applications Coordinator Admin" in resp.content


# ---- Phase 3: editable applicant comms -----------------------------------


def test_acknowledgment_auto_sends_on_submit(application, django_capture_on_commit_callbacks):
    from admissions.models import AdmissionsSettings
    from admissions.services import acknowledge_on_submit

    assert AdmissionsSettings.load().acknowledgment_mode == AdmissionsSettings.Mode.AUTO
    with django_capture_on_commit_callbacks(execute=True):
        acknowledge_on_submit(application)
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "/apply/status/" in msg.body  # check-your-status link
    assert "LSP Applications Coordinator" in msg.body  # consistent signature
    assert "applications@lacanschool.org" in msg.from_email  # from the admissions mailbox
    application.refresh_from_db()
    assert application.acknowledged_at is not None


def test_acknowledgment_review_mode_holds(application, django_capture_on_commit_callbacks):
    from admissions.models import AdmissionsSettings
    from admissions.services import acknowledge_on_submit

    cfg = AdmissionsSettings.load()
    cfg.acknowledgment_mode = AdmissionsSettings.Mode.REVIEW
    cfg.save()
    with django_capture_on_commit_callbacks(execute=True):
        acknowledge_on_submit(application)
    assert mail.outbox == []
    application.refresh_from_db()
    assert application.acknowledged_at is None


def test_coordinator_send_acknowledgment(
    client, coordinator, application, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("admissions:coordinator_acknowledge", args=[application.pk])
        )
    assert resp.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].reply_to == ["applications@lacanschool.org"]
    application.refresh_from_db()
    assert application.acknowledged_at is not None


def test_decision_accept_letter_uses_template_links(application):
    from admissions.emails import send_application_decision
    from documents.models import Document

    Document.objects.create(
        title="Analyst Formation Guidelines", slug="analyst-formation-guidelines",
        category=Document.Category.FORMATION,
    )
    application.status = Application.Status.ACCEPTED
    application.save(update_fields=["status"])
    send_application_decision(application)
    body = mail.outbox[0].body
    assert "Congratulations" in body
    assert "/directory/availability/?only=advisor" in body  # advisors, pre-sorted
    assert "/documents/analyst-formation-guidelines/" in body  # responsibilities doc
    assert "/accounts/profile/" in body  # the profile-build invite
    assert "/formation/" in body  # My LSP
    assert mail.outbox[0].reply_to == ["applications@lacanschool.org"]


def test_admissions_settings_save(client, coordinator):
    from admissions.models import AdmissionsSettings

    resp = client.post(reverse("admissions:coordinator_settings"), {
        "acknowledgment_mode": AdmissionsSettings.Mode.REVIEW,
        "invitation_mode": AdmissionsSettings.Mode.AUTO,
    })
    assert resp.status_code == 302
    assert AdmissionsSettings.load().acknowledgment_mode == AdmissionsSettings.Mode.REVIEW
    assert AdmissionsSettings.load().invitation_mode == AdmissionsSettings.Mode.AUTO


def test_decision_template_editable(client, coordinator):
    url = reverse("admissions:coordinator_message_edit",
                  args=[MessageTemplate.Key.DECISION_ACCEPT])
    assert client.get(url).status_code == 200
    resp = client.post(url, {"subject": "Welcome!", "body": "Dear {name}, welcome."})
    assert resp.status_code == 302
    assert MessageTemplate.get(MessageTemplate.Key.DECISION_ACCEPT).subject == "Welcome!"


@override_settings(PREVIEW_TOUR_ENABLED=True, PREVIEW_TOUR_PUBLIC=True)
def test_consoles_render_with_walkthrough_link(client, coordinator):
    # With the tour enabled the "✦ Guided walkthrough" link renders — guards the
    # set_walkthrough reverse (namespaced core:set_walkthrough).
    assert client.get(reverse("admissions:coordinator_dashboard")).status_code == 200
    assert client.get(reverse("admissions:analyst_dashboard")).status_code == 200


def test_review_detail_shows_invite_for_coordinator(client, coordinator, application):
    # The applicant detail view offers Invite (primary) + the manual override.
    application.status = Application.Status.SUBMITTED
    application.save(update_fields=["status"])
    html = client.get(
        reverse("admissions:review_detail", args=[application.pk])
    ).content.decode()
    assert f"/admin-tools/applications/{application.pk}/invite/" in html
    assert "Invite interviewers" in html
    assert "Or add a specific interviewer" in html  # the override
