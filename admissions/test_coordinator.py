"""Tests for the Applications Coordinator console (task #272)."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
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
                  args=[MessageTemplate.Key.INTERVIEWER_NUDGE])
    assert client.get(url).status_code == 200
    resp = client.post(url, {"subject": "Reminder", "body": "Hi {interviewer}, see {url}."})
    assert resp.status_code == 302
    assert MessageTemplate.get(MessageTemplate.Key.INTERVIEWER_NUDGE).subject == "Reminder"


def test_panel_appears_for_coordinator(client, coordinator):
    resp = client.get(reverse("admin_tools"))
    assert resp.status_code == 200
    assert b"Applications Coordinator Admin" in resp.content
