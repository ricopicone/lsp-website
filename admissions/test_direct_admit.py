"""Direct admission — admitting a member who never applied on the site (#476)."""

from __future__ import annotations

import pytest

from accounts.models import MembershipTenure, Profile, User
from admissions.models import Application
from admissions.services import admit_member

pytestmark = pytest.mark.django_db


def _user(email, **kw):
    return User.objects.create_user(email=email, password="x", **kw)


@pytest.fixture
def actor():
    return _user("wc@x.test", first_name="Web", last_name="Coordinator")


def test_admit_member_sets_role_standing_and_tenure(actor):
    member = _user("new@x.test", first_name="Nadia", last_name="New")

    admit_member(
        member, track=Application.Track.ANALYST,
        formation_background=Profile.FormationBackground.CLINICAL,
        effective_ay=2026, by=actor, tenure_note="Admitted directly.",
        background_note="Set at direct admission.",
    )

    member.refresh_from_db()
    assert member.profile.role == Profile.Role.PRE_CANDIDATE
    assert member.profile.standing == Profile.Standing.ACTIVE
    assert member.profile.formation_background == Profile.FormationBackground.CLINICAL
    tenure = MembershipTenure.open_for(member)
    assert tenure.start_ay == 2026
    assert "Admitted directly." in tenure.notes


def test_admit_member_scholar_track_admits_as_scholar_precandidate(actor):
    member = _user("scholar@x.test")

    admit_member(member, track=Application.Track.SCHOLAR, by=actor)

    member.refresh_from_db()
    assert member.profile.role == Profile.Role.PRE_CANDIDATE_SCHOLAR


def test_admit_member_leaves_background_unreviewed_when_blank(actor):
    member = _user("unknown-bg@x.test")

    admit_member(member, track=Application.Track.ANALYST,
                 formation_background="", by=actor)

    member.refresh_from_db()
    assert (member.profile.formation_background
            == Profile.FormationBackground.UNREVIEWED)


def test_both_routes_produce_the_same_membership_state(actor):
    """The whole point of the shared service: a member admitted directly and an
    applicant accepted through the site land in identical state."""
    from admissions.services import accept_application

    direct = _user("direct@x.test")
    admit_member(
        direct, track=Application.Track.ANALYST,
        formation_background=Profile.FormationBackground.CLINICAL,
        effective_ay=2026, by=actor,
    )

    applicant = _user("applied@x.test")
    application = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        background=Application.Background.CLINICAL,
        letter_of_intent="I would like to join.",
    )
    accept_application(application, by=actor, effective_ay=2026)

    for user in (direct, applicant):
        user.refresh_from_db()
    assert direct.profile.role == applicant.profile.role
    assert direct.profile.standing == applicant.profile.standing
    assert direct.profile.formation_background == applicant.profile.formation_background
    assert (MembershipTenure.open_for(direct).start_ay
            == MembershipTenure.open_for(applicant).start_ay)


def test_direct_acceptance_letter_renders_without_an_application():
    from django.core import mail

    from admissions.emails import send_direct_acceptance

    member = _user("cold@x.test", first_name="Cold", last_name="Admit")
    send_direct_acceptance(
        member, track=Application.Track.ANALYST,
        background=Application.Background.CLINICAL, note="Welcome aboard.",
    )

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Cold" in body
    assert "Analyst formation, Clinical" in body
    assert "Welcome aboard." in body
    # No leftover placeholders, and no fabricated application-status link.
    assert "{" not in body
    assert "/apply/status" not in body


def test_account_ready_link_lets_the_member_set_a_password(client):
    from django.core import mail

    from accounts.emails import send_account_ready

    member = _user("ready@x.test", first_name="Ready")
    member.set_unusable_password()
    member.save(update_fields=["password"])

    send_account_ready(member, track=Application.Track.ANALYST)

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Ready" in body
    # The set-password link is a real, working password-reset confirm URL.
    url = next(
        line.strip() for line in body.splitlines()
        if "/accounts/reset/" in line
    )
    path = url[url.index("/accounts/"):]
    resp = client.get(path, follow=True)
    resp = client.post(resp.request["PATH_INFO"], {
        "new_password1": "a-real-passphrase-42",
        "new_password2": "a-real-passphrase-42",
    })
    member.refresh_from_db()
    assert member.check_password("a-real-passphrase-42")
