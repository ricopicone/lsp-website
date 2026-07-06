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


# ---- sandbox (task #272) --------------------------------------------------


def test_sandbox_application_invites_only_personas(application):
    real = _analyst("real@x.test", status="yes")
    persona = _analyst("p@x.test", status="yes")
    persona.profile.is_persona = True
    persona.profile.save()
    # Make this a sandbox application (persona applicant).
    application.applicant.profile.is_persona = True
    application.applicant.profile.save()
    pool = services.eligible_interviewers(application)
    assert persona in pool
    assert real not in pool


def test_seed_sandbox_creates_cast_and_sample_apps():
    from io import StringIO

    from django.core.management import call_command

    owner = User.objects.create_user(email="coach@x.test", password="x")
    call_command("seed_sandbox", "--owner", "coach@x.test", stdout=StringIO())

    cast = Profile.objects.filter(persona_owner=owner, is_persona=True)
    assert cast.count() == 5  # 3 analysts + 2 applicants
    apps = Application.objects.filter(applicant__profile__persona_owner=owner)
    assert apps.count() == 2
    interviewing = apps.get(status=Application.Status.INTERVIEWING)
    assert interviewing.interviews.count() == 2
    assert all(iv.is_complete for iv in interviewing.interviews.all())

    # Re-running with --reset keeps it idempotent (same counts, no duplicates).
    call_command("seed_sandbox", "--owner", "coach@x.test", "--reset", stdout=StringIO())
    assert Profile.objects.filter(persona_owner=owner, is_persona=True).count() == 5
    assert Application.objects.filter(applicant__profile__persona_owner=owner).count() == 2


def test_full_application_shows_covered(client, application):
    application.status = Application.Status.INTERVIEWING
    application.save(update_fields=["status"])
    services.add_interviewer(application, _analyst("a1@x.test", status="yes"))
    services.add_interviewer(application, _analyst("a2@x.test", status="yes"))
    viewer = _analyst("v@x.test", status="yes")
    client.force_login(viewer)
    html = client.get(
        reverse("admissions:analyst_interview", args=[application.pk])
    ).content.decode()
    assert "already covered" in html


def test_sandbox_interview_offers_act_as_to_superuser(client, application):
    application.applicant.profile.is_persona = True
    application.applicant.profile.save()
    application.status = Application.Status.INTERVIEWING
    application.save(update_fields=["status"])
    p = _analyst("pa@x.test", status="yes")
    p.profile.is_persona = True
    p.profile.save()
    su = User.objects.create_superuser(email="su-act@x.test", password="x")
    client.force_login(su)
    html = client.get(
        reverse("admissions:analyst_interview", args=[application.pk])
    ).content.decode()
    assert "Act as" in html  # impersonation shortcut offered
    assert "already covered" not in html  # not the misleading message
    assert f"/impersonate/{p.pk}/" in html


# ---- sandbox containment of the manual-assign override --------------------


def test_sandbox_assign_form_excludes_real_analysts(application):
    from admissions.forms import AssignInterviewerForm

    application.applicant.profile.is_persona = True
    application.applicant.profile.save()
    real = _analyst("real-leak@x.test", status="yes")
    persona = _analyst("persona-ok@x.test", status="yes")
    persona.profile.is_persona = True
    persona.profile.save()
    pool = list(AssignInterviewerForm(application=application).fields["interviewer"].queryset)
    assert persona in pool
    assert real not in pool  # a real analyst can't be picked for a sandbox app


def test_add_interviewer_refuses_sandbox_mismatch(application):
    # Defense in depth: even bypassing the form, a real analyst can't be added
    # to a sandbox application (which would email them for real).
    application.applicant.profile.is_persona = True
    application.applicant.profile.save()
    real = _analyst("real2@x.test", status="yes")
    import pytest as _pytest
    with _pytest.raises(ValueError):
        services.add_interviewer(application, real)
    assert not application.interviews.exists()
    assert mail.outbox == []  # no leak


# ---- sandbox "simulate analyst responses" shortcut ------------------------


def test_simulate_fills_and_reports_for_sandbox(application):
    application.applicant.profile.is_persona = True
    application.applicant.profile.save()
    application.status = Application.Status.INTERVIEWING
    application.save(update_fields=["status"])
    # Two persona analysts available to be drawn in.
    for i in range(2):
        a = _analyst(f"sim{i}@x.test", status="yes")
        a.profile.is_persona = True
        a.profile.save()

    n = services.simulate_interviews(application)
    assert n == 2
    ivs = list(application.interviews.all())
    assert len(ivs) == 2
    assert all(iv.is_complete for iv in ivs)  # decision-ready
    # Introductions were generated (to the personas → redirected by the backend).
    assert len(mail.outbox) >= 2


def test_simulate_refused_for_real_application(application):
    import pytest as _pytest
    with _pytest.raises(ValueError):
        services.simulate_interviews(application)  # applicant is real


def test_simulate_button_via_view(client, application):
    application.applicant.profile.is_persona = True
    application.applicant.profile.save()
    application.status = Application.Status.INTERVIEWING
    application.save(update_fields=["status"])
    a = _analyst("simv@x.test", status="yes")
    a.profile.is_persona = True
    a.profile.save()
    su = User.objects.create_superuser(email="su-sim@x.test", password="x")
    client.force_login(su)
    resp = client.post(reverse("admissions:coordinator_simulate", args=[application.pk]))
    assert resp.status_code == 302
    assert application.interviews.filter(interviewer=a).exists()
