"""Tests for the application (apply-to-join) process."""

from __future__ import annotations

import datetime

import pytest
from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from accounts.models import MembershipTenure, Profile, User
from admissions.models import Application, ApplicationInterview
from admissions.services import accept_application, reject_application

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.EXTERNAL, **kw):
    u = User.objects.create_user(email=email, password="x", **kw)
    u.profile.role = role
    u.profile.save()
    return u


def _board_member(email="board@x.test"):
    from committees.models import Committee
    u = User.objects.create_user(email=email, password="x")
    Committee.objects.get(slug="board").add_member(u, start_date=datetime.date(2026, 1, 1))
    return u


def _analyst(email="analyst@x.test"):
    return _user(email, role=Profile.Role.ANALYST)


def _coordinator(email="coord@x.test"):
    """An Applications Coordinator — the workgroup role that owns the
    application admin (assign / report / decide)."""
    from committees.models import Committee
    from workgroups.models import WorkgroupMembership
    u = _user(email, role=Profile.Role.ANALYST)
    wg = Committee.objects.get(slug="meeting-of-analysts").workgroup
    wg.add_member(u, role=WorkgroupMembership.Role.APPLICATIONS_COORDINATOR)
    return u


def _cv():
    return SimpleUploadedFile("cv.pdf", b"%PDF-1.4 fake", content_type="application/pdf")


# ---- Applicant intake --------------------------------------------------


def test_apply_start_is_public_but_submit_requires_login(client):
    # The track/eligibility intro is a public on-ramp...
    start = client.get(reverse("admissions:apply_start"))
    assert start.status_code == 200
    assert b"Apply \xe2\x80\x94" in start.content  # "Apply —" track buttons render
    # ...but actually submitting a track still requires signing in.
    resp = client.get(reverse("admissions:apply", args=["analyst"]))
    assert resp.status_code == 302
    assert "/accounts/login" in resp["Location"]


def test_guest_submits_analyst_application(client, django_capture_on_commit_callbacks):
    guest = _user("g@x.test", role=Profile.Role.EXTERNAL)
    client.force_login(guest)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("admissions:apply", args=["analyst"]), {
            "background": Application.Background.CLINICAL,
            "eligibility_note": "PsyD, licensed LCSW",
            "letter_of_intent": "I wish to study Lacan.",
            "cv": _cv(),
        })
    assert resp.status_code == 302
    app = Application.objects.get(applicant=guest)
    assert app.track == Application.Track.ANALYST
    assert app.status == Application.Status.SUBMITTED
    assert app.background == Application.Background.CLINICAL
    guest.profile.refresh_from_db()
    assert guest.profile.role == Profile.Role.PROSPECTIVE_APPLICANT
    assert any("received your LSP application" in m.subject for m in mail.outbox)


def test_scholar_application_has_no_background_field(client):
    guest = _user("s@x.test")
    client.force_login(guest)
    resp = client.post(reverse("admissions:apply", args=["scholar"]), {
        "eligibility_note": "2 years personal analysis",
        "letter_of_intent": "Scholar intent.",
        "cv": _cv(),
    })
    assert resp.status_code == 302
    assert Application.objects.get(applicant=guest).track == Application.Track.SCHOLAR


def test_scholar_eligibility_note_required(client):
    guest = _user("s2@x.test")
    client.force_login(guest)
    resp = client.post(reverse("admissions:apply", args=["scholar"]), {
        "eligibility_note": "",
        "letter_of_intent": "x",
        "cv": _cv(),
    })
    assert resp.status_code == 200  # re-rendered with errors
    assert not Application.objects.filter(applicant=guest).exists()


def test_invalid_track_403s(client):
    client.force_login(_user("g3@x.test"))
    assert client.get(reverse("admissions:apply", args=["nope"])).status_code == 403


def test_second_application_redirects_to_status(client):
    guest = _user("g4@x.test")
    Application.objects.create(
        applicant=guest, track=Application.Track.ANALYST, letter_of_intent="x",
    )
    client.force_login(guest)
    assert client.get(reverse("admissions:apply", args=["analyst"])).status_code == 302
    assert client.get(reverse("admissions:apply_start")).status_code == 302


# ---- Applications closed (task #717) -----------------------------------
#
# While the Applications Coordinator reworks intake, the front door is shut:
# no new applications, but everything already in flight keeps running.


@override_settings(APPLICATIONS_ENABLED=False)
def test_closed_apply_start_gives_the_coordinators_address(client):
    resp = client.get(reverse("admissions:apply_start"))
    assert resp.status_code == 200
    assert settings.APPLICATIONS_EMAIL.encode() in resp.content
    assert b"Apply \xe2\x80\x94" not in resp.content  # no "Apply —" track buttons


@override_settings(APPLICATIONS_ENABLED=False)
def test_closed_apply_start_keeps_the_tracks_and_eligibility(client):
    resp = client.get(reverse("admissions:apply_start"))
    assert b"Analyst" in resp.content and b"Scholar" in resp.content
    assert b"personal Lacanian analysis" in resp.content


@override_settings(APPLICATIONS_ENABLED=False)
def test_closed_apply_form_redirects_to_the_start_page(client):
    client.force_login(_user("closed1@x.test"))
    resp = client.get(reverse("admissions:apply", args=["analyst"]))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("admissions:apply_start")


@override_settings(APPLICATIONS_ENABLED=False)
def test_closed_apply_form_does_not_send_a_stranger_to_the_login_wall(client):
    # A stale bookmark shouldn't ask someone to make an account for a form
    # that isn't there any more.
    resp = client.get(reverse("admissions:apply", args=["scholar"]))
    assert resp["Location"] == reverse("admissions:apply_start")


@override_settings(APPLICATIONS_ENABLED=False)
def test_closed_apply_post_creates_no_application(client):
    guest = _user("closed2@x.test")
    client.force_login(guest)
    resp = client.post(reverse("admissions:apply", args=["analyst"]), {
        "background": Application.Background.CLINICAL,
        "eligibility_note": "PsyD, licensed LCSW",
        "letter_of_intent": "I wish to study Lacan.",
        "cv": _cv(),
    })
    assert resp.status_code == 302
    assert not Application.objects.filter(applicant=guest).exists()


@override_settings(APPLICATIONS_ENABLED=False)
def test_closed_door_does_not_strand_an_applicant_already_in_flight(client):
    guest = _user("closed3@x.test", role=Profile.Role.PROSPECTIVE_APPLICANT)
    Application.objects.create(
        applicant=guest, track=Application.Track.ANALYST, letter_of_intent="x",
        status=Application.Status.INTERVIEWING,
    )
    client.force_login(guest)
    start = client.get(reverse("admissions:apply_start"))
    assert start["Location"] == reverse("admissions:status")
    assert client.get(reverse("admissions:status")).status_code == 200


# ---- Reviewer flow -----------------------------------------------------


def test_review_queue_gated(client):
    # The Meeting of the Analysts owns admissions: a non-Analyst member (even a
    # Board member who isn't an Analyst) cannot reach the review queue.
    client.force_login(_user("plain@x.test", role=Profile.Role.MEMBER))
    assert client.get(reverse("admissions:review_queue")).status_code == 403
    client.force_login(_board_member("board-only@x.test"))
    assert client.get(reverse("admissions:review_queue")).status_code == 403


def test_analyst_can_reach_review_queue(client):
    # Every active Analyst is a Meeting-of-Analysts member (auto-derived role).
    client.force_login(_analyst("rev-gate@x.test"))
    assert client.get(reverse("admissions:review_queue")).status_code == 200


def test_coordinator_can_assign_and_report(client):
    coordinator = _coordinator("coord-assign@x.test")
    analyst = _analyst()
    applicant = _user("a@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST, letter_of_intent="x",
    )
    client.force_login(coordinator)
    client.post(reverse("admissions:review_assign", args=[app.pk]), {"interviewer": analyst.pk})
    app.refresh_from_db()
    assert app.status == Application.Status.INTERVIEWING
    iv = ApplicationInterview.objects.get(application=app, interviewer=analyst)
    client.post(reverse("admissions:review_report", args=[iv.pk]), {
        f"iv{iv.pk}-completed_at": "2026-03-01",
        f"iv{iv.pk}-report": "Strong candidate.",
    })
    iv.refresh_from_db()
    assert iv.is_complete


def test_accept_admits_as_precandidate_and_writes_tenure():
    board = _board_member()
    applicant = _user("acc@x.test", role=Profile.Role.PROSPECTIVE_APPLICANT)
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST, letter_of_intent="x",
    )
    accept_application(app, by=board, effective_ay=2026, note="Welcome")
    app.refresh_from_db()
    applicant.profile.refresh_from_db()
    assert app.status == Application.Status.ACCEPTED
    assert applicant.profile.role == Profile.Role.PRE_CANDIDATE
    assert applicant.profile.standing == Profile.Standing.ACTIVE
    t = MembershipTenure.objects.get(user=applicant, end_ay__isnull=True)
    assert t.role == Profile.Role.PRE_CANDIDATE and t.start_ay == 2026


def test_accept_scholar_admits_as_precandidate_scholar():
    board = _board_member()
    applicant = _user("sch@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.SCHOLAR, letter_of_intent="x",
    )
    accept_application(app, by=board, effective_ay=2026)
    applicant.profile.refresh_from_db()
    assert applicant.profile.role == Profile.Role.PRE_CANDIDATE_SCHOLAR


def test_accept_sets_clinical_background_for_clinical_analyst():
    from accounts.models import Profile

    board = _board_member()
    applicant = _user("clin@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        background=Application.Background.CLINICAL, letter_of_intent="x",
    )
    accept_application(app, by=board, effective_ay=2026)
    applicant.profile.refresh_from_db()
    assert applicant.profile.formation_background == Profile.FormationBackground.CLINICAL


def test_accept_academic_or_scholar_stays_academic():
    from accounts.models import Profile

    board = _board_member()
    applicant = _user("acad@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.SCHOLAR, letter_of_intent="x",
    )
    accept_application(app, by=board, effective_ay=2026)
    applicant.profile.refresh_from_db()
    assert applicant.profile.formation_background == Profile.FormationBackground.ACADEMIC


def test_reject_sets_status():
    board = _board_member()
    applicant = _user("rej@x.test", role=Profile.Role.PROSPECTIVE_APPLICANT)
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST, letter_of_intent="x",
    )
    reject_application(app, by=board, note="Not at this time")
    app.refresh_from_db()
    applicant.profile.refresh_from_db()
    assert app.status == Application.Status.REJECTED
    assert applicant.profile.role == Profile.Role.PROSPECTIVE_APPLICANT


def test_decide_via_view_with_on_commit_email(client, django_capture_on_commit_callbacks):
    coordinator = _coordinator("coord-decide@x.test")
    applicant = _user("v@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST, letter_of_intent="x",
    )
    client.force_login(coordinator)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(reverse("admissions:review_decide", args=[app.pk]), {
            "decision": "accept", "effective_ay": "2026", "note": "Welcome",
        })
    assert resp.status_code == 302
    app.refresh_from_db()
    assert app.status == Application.Status.ACCEPTED
    assert any("welcome" in m.subject.lower() for m in mail.outbox)


def test_meeting_member_view_is_read_only(client):
    """A Meeting of Analysts member sees applications but cannot act — assign and
    decide are the Applications Coordinator's."""
    analyst = _analyst("ro@x.test")
    applicant = _user("ro-app@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST, letter_of_intent="x",
    )
    client.force_login(analyst)
    assert client.get(reverse("admissions:review_detail", args=[app.pk])).status_code == 200
    assert client.post(
        reverse("admissions:review_assign", args=[app.pk]), {"interviewer": analyst.pk}
    ).status_code == 403
    assert client.post(
        reverse("admissions:review_decide", args=[app.pk]), {"decision": "accept"}
    ).status_code == 403


# ---- CV privacy --------------------------------------------------------


def test_cv_download_gated(client):
    applicant = _user("cvowner@x.test")
    app = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST, letter_of_intent="x",
        cv=_cv(),
    )
    url = reverse("admissions:cv_download", args=[app.pk])
    client.force_login(_user("stranger@x.test"))
    assert client.get(url).status_code == 404
    client.force_login(applicant)
    assert client.get(url).status_code == 200
    client.force_login(_analyst("rev3@x.test"))
    assert client.get(url).status_code == 200


# ---- Template render smoke ---------------------------------------------


def test_apply_start_and_form_render(client):
    client.force_login(_user("r1@x.test"))
    assert b"Apply to join" in client.get(reverse("admissions:apply_start")).content
    r = client.get(reverse("admissions:apply", args=["analyst"]))
    assert r.status_code == 200 and b"Letter of intent" in r.content


def test_status_page_renders(client):
    applicant = _user("r2@x.test")
    Application.objects.create(
        applicant=applicant, track=Application.Track.SCHOLAR, letter_of_intent="x",
    )
    client.force_login(applicant)
    r = client.get(reverse("admissions:status"))
    assert r.status_code == 200 and b"My application" in r.content


def test_review_pages_render(client):
    reviewer = _analyst("rev4@x.test")
    analyst = _analyst()
    app = Application.objects.create(
        applicant=_user("r3@x.test"), track=Application.Track.ANALYST,
        letter_of_intent="hello", cv=_cv(),
    )
    ApplicationInterview.objects.create(application=app, interviewer=analyst)
    client.force_login(reviewer)
    assert client.get(reverse("admissions:review_queue")).status_code == 200
    r = client.get(reverse("admissions:review_detail", args=[app.pk]))
    assert r.status_code == 200
    assert b"Letter of intent" in r.content and b"Interviews" in r.content
