"""Tests for the invite → agree → connect interview-staffing flow (task #272)."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import Profile, User
from admissions import services
from admissions.models import (
    AdmissionsSettings,
    Application,
)
from availability import services as avail_services
from availability.models import AnalystFunction

pytestmark = pytest.mark.django_db


def _analyst(email, status=None, first="A", last="Nalyst"):
    u = User.objects.create_user(email=email, password="x", first_name=first, last_name=last)
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    if status is not None:
        fn = AnalystFunction.objects.get(slug="application-interviews")
        avail_services.set_availability(u.profile, fn, status)
    return u


@pytest.fixture
def application():
    applicant = User.objects.create_user(
        email="app@x.test", password="x", first_name="Aimee", last_name="Applicant",
    )
    return Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        letter_of_intent="x", status=Application.Status.SUBMITTED,
        submitted_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
    )


# ---- eligibility ----------------------------------------------------------


def test_eligible_pool_excludes_only_explicit_no(application):
    yes = _analyst("yes@x.test", status="yes")
    unknown = _analyst("unknown@x.test")  # no availability row → unknown
    no = _analyst("no@x.test", status="no")
    pool = services.eligible_interviewers(application)
    assert yes in pool
    assert unknown in pool
    assert no not in pool


def test_eligible_pool_excludes_applicant_and_personas(application):
    persona = _analyst("persona@x.test", status="yes")
    persona.profile.is_persona = True
    persona.profile.save()
    assert persona not in services.eligible_interviewers(application)


# ---- invitation -----------------------------------------------------------


def test_invite_emails_eligible_and_moves_to_interviewing(
    application, django_capture_on_commit_callbacks
):
    _analyst("yes@x.test", status="yes")
    _analyst("no@x.test", status="no")
    with django_capture_on_commit_callbacks(execute=True):
        n = services.invite_interviewers(application)
    assert n == 1  # only the YES analyst (NO excluded)
    assert len(mail.outbox) == 1
    application.refresh_from_db()
    assert application.status == Application.Status.INTERVIEWING
    assert application.interviewers_invited_at is not None


def test_invite_on_submit_respects_mode(application, django_capture_on_commit_callbacks):
    _analyst("yes@x.test", status="yes")
    cfg = AdmissionsSettings.load()
    cfg.invitation_mode = AdmissionsSettings.Mode.REVIEW  # the default
    cfg.save()
    with django_capture_on_commit_callbacks(execute=True):
        services.invite_on_submit(application)
    assert mail.outbox == []  # review-first: nothing auto-sent

    cfg.invitation_mode = AdmissionsSettings.Mode.AUTO
    cfg.save()
    with django_capture_on_commit_callbacks(execute=True):
        services.invite_on_submit(application)
    assert len(mail.outbox) == 1


# ---- agree + connect ------------------------------------------------------


def test_agree_creates_interview_and_emails_both(application):
    analyst = _analyst("yes@x.test", status="yes")
    iv, outcome = services.agree_to_interview(application, analyst)
    assert outcome == "agreed"
    assert iv.agreed_at is not None
    # Introduction email goes to BOTH applicant and analyst.
    assert len(mail.outbox) == 1
    assert set(mail.outbox[0].to) == {application.applicant.email, analyst.email}
    assert set(mail.outbox[0].reply_to) == {application.applicant.email, analyst.email}


def test_agree_is_full_once_two_agreed(application):
    a1 = _analyst("a1@x.test", status="yes")
    a2 = _analyst("a2@x.test", status="yes")
    a3 = _analyst("a3@x.test", status="yes")
    assert services.agree_to_interview(application, a1)[1] == "agreed"
    assert services.agree_to_interview(application, a2)[1] == "agreed"
    iv, outcome = services.agree_to_interview(application, a3)
    assert outcome == "full"
    assert iv is None
    assert application.interviews.count() == 2


def test_agree_again_is_already(application):
    a1 = _analyst("a1@x.test", status="yes")
    services.agree_to_interview(application, a1)
    _iv, outcome = services.agree_to_interview(application, a1)
    assert outcome == "already"


# ---- analyst page ---------------------------------------------------------


def test_analyst_page_gated(client, application):
    member = User.objects.create_user(email="m@x.test", password="x")
    client.force_login(member)
    assert client.get(reverse("admissions:analyst_dashboard")).status_code == 403


def test_analyst_can_agree_via_page(client, application):
    analyst = _analyst("yes@x.test", status="yes")
    application.interviewers_invited_at = datetime.datetime(
        2026, 6, 2, tzinfo=datetime.timezone.utc
    )
    application.status = Application.Status.INTERVIEWING
    application.save()
    client.force_login(analyst)
    resp = client.post(reverse("admissions:analyst_agree", args=[application.pk]))
    assert resp.status_code == 302
    assert application.interviews.filter(interviewer=analyst).exists()


def test_analyst_reports_interview(client, application):
    analyst = _analyst("yes@x.test", status="yes")
    services.add_interviewer(application, analyst)
    mail.outbox.clear()
    client.force_login(analyst)
    resp = client.post(reverse("admissions:analyst_report", args=[application.pk]), {
        "completed_at": "2026-06-20", "report": "A thoughtful candidate.",
    })
    assert resp.status_code == 302
    iv = application.interviews.get(interviewer=analyst)
    assert iv.is_complete
    assert iv.report == "A thoughtful candidate."


def test_dashboard_lists_request_for_eligible_analyst(client, application):
    analyst = _analyst("yes@x.test", status="yes")
    application.interviewers_invited_at = datetime.datetime(
        2026, 6, 2, tzinfo=datetime.timezone.utc
    )
    application.status = Application.Status.INTERVIEWING
    application.save()
    client.force_login(analyst)
    resp = client.get(reverse("admissions:analyst_dashboard"))
    assert resp.status_code == 200
    assert b"Aimee Applicant" in resp.content


# ---- weekly reminder command ----------------------------------------------


def test_reminder_command_emails_incomplete_only(application):
    from django.core.management import call_command

    a1 = _analyst("a1@x.test", status="yes")
    a2 = _analyst("a2@x.test", status="yes")
    services.add_interviewer(application, a1)
    iv2, _ = services.add_interviewer(application, a2)
    iv2.completed_at = datetime.date(2026, 6, 20)
    iv2.report = "Done"
    iv2.save()
    application.status = Application.Status.INTERVIEWING
    application.save(update_fields=["status"])
    mail.outbox.clear()

    call_command("send_interview_reminders")
    assert len(mail.outbox) == 1  # only the incomplete one
    assert a1.email in mail.outbox[0].to


def test_report_without_date_completes_today(client, application):
    analyst = _analyst("yes@x.test", status="yes")
    services.add_interviewer(application, analyst)
    client.force_login(analyst)
    # Submit a report but leave the date blank — should still complete (today).
    resp = client.post(reverse("admissions:analyst_report", args=[application.pk]), {
        "report": "Strong candidate.",
    })
    assert resp.status_code == 302
    iv = application.interviews.get(interviewer=analyst)
    assert iv.is_complete
    assert iv.completed_at is not None


def test_empty_report_is_rejected(client, application):
    analyst = _analyst("yes@x.test", status="yes")
    services.add_interviewer(application, analyst)
    client.force_login(analyst)
    resp = client.post(reverse("admissions:analyst_report", args=[application.pk]), {
        "report": "",
    })
    assert resp.status_code == 200  # re-rendered with errors, not saved
    iv = application.interviews.get(interviewer=analyst)
    assert not iv.is_complete
