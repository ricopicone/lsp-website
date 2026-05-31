"""Tests for the cartel CART-4 formation/joining workflow."""

from __future__ import annotations

import pytest

from accounts.models import Profile, User
from cartels.models import Cartel, CartelJoinRequest
from cartels.permissions import is_cartel_coordinator
from workgroups.models import Visibility, WorkgroupMembership

pytestmark = pytest.mark.django_db


def _member(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


def _coordinator(email="coord@x.test"):
    u = _member(email)
    u.profile.is_cartel_coordinator = True
    u.profile.save(update_fields=["is_cartel_coordinator"])
    return u


# ---- propose ----------------------------------------------------------

def test_propose_creates_proposed_cartel_with_generator_as_member():
    gen = _member("gen@x.test")
    invitee = _member("inv@x.test")
    cartel = Cartel.objects.propose(
        generator=gen, name="Speech and Writing",
        guiding_question="What is a letter?", invitees=[invitee],
    )
    assert cartel.status == Cartel.Status.PROPOSED
    assert cartel.workgroup.landing_visibility == Visibility.PRIVATE   # hidden pre-approval
    assert cartel.is_member(gen) is True
    assert cartel.invitations.filter(invited_user=invitee).exists()
    # not visible to the school yet
    assert cartel.workgroup.landing_visible_to(_member("outsider@x.test")) is False


# ---- coordinator review ------------------------------------------------

def test_is_cartel_coordinator_designation():
    assert is_cartel_coordinator(_member("plain@x.test")) is False
    assert is_cartel_coordinator(_coordinator()) is True


def test_approve_publishes_open_and_records_reviewer():
    gen = _member("gen@x.test")
    coord = _coordinator()
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(coord)
    assert cartel.status == Cartel.Status.OPEN
    assert cartel.reviewed_by == coord and cartel.reviewed_at is not None
    assert cartel.workgroup.landing_visibility == Visibility.MEMBERS   # now solicitable
    assert cartel.workgroup.landing_visible_to(_member("anymember@x.test")) is True


def test_decline_records_reason():
    cartel = Cartel.objects.propose(generator=_member("g@x.test"), name="C")
    cartel.decline(_coordinator(), note="Too close to an existing cartel.")
    assert cartel.status == Cartel.Status.DECLINED
    assert "existing cartel" in cartel.review_note


# ---- joining -----------------------------------------------------------

def test_seeded_invitee_joins_directly():
    gen = _member("g@x.test")
    invitee = _member("inv@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", invitees=[invitee])
    cartel.approve(_coordinator())
    cartel.accept_invitation(invitee)
    assert cartel.is_member(invitee) is True
    assert cartel.invitations.get(invited_user=invitee).accepted_at is not None


def test_uninvited_applicant_is_member_gated():
    gen = _member("g@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")

    req = cartel.request_to_join(applicant)
    assert req.status == CartelJoinRequest.Status.PENDING
    assert cartel.is_member(applicant) is False     # not yet — gated

    cartel.accept_request(req, decided_by=gen)       # an existing member accepts
    req.refresh_from_db()
    assert req.status == CartelJoinRequest.Status.ACCEPTED
    assert req.decided_by == gen
    assert cartel.is_member(applicant) is True        # now a member, can gate others


def test_decline_request_keeps_applicant_out():
    cartel = Cartel.objects.propose(generator=_member("g@x.test"), name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")
    req = cartel.request_to_join(applicant)
    cartel.decline_request(req, decided_by=cartel.generator)
    req.refresh_from_db()
    assert req.status == CartelJoinRequest.Status.DECLINED
    assert cartel.is_member(applicant) is False


def test_plus_one_is_a_membership_role():
    gen = _member("g@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    p1 = _member("plusone@x.test")
    cartel.add_member(p1, plus_one=True)
    assert cartel.workgroup.memberships.filter(
        user=p1, role=WorkgroupMembership.Role.PLUS_ONE, end_date__isnull=True
    ).exists()


# ---- views (end-to-end through HTTP) ----------------------------------

def test_propose_view_creates_cartel_and_redirects(client):
    gen = _member("gen@x.test")
    client.force_login(gen)
    resp = client.post("/cartels/propose/", {
        "name": "Speech and Writing",
        "guiding_question": "What is a letter?",
        "description": "Reading the Écrits.",
        "invitees": "",
    })
    assert resp.status_code == 302
    cartel = Cartel.objects.get(workgroup__name="Speech and Writing")
    assert cartel.status == Cartel.Status.PROPOSED
    assert cartel.is_member(gen)


def test_propose_view_blocks_non_members(client):
    from accounts.models import User
    # role defaults to external (not an LSP member)
    guest = User.objects.create_user(email="guest@x.test", password="x")
    client.force_login(guest)
    resp = client.post("/cartels/propose/", {"name": "X", "guiding_question": "Q"})
    assert resp.status_code == 404
    assert not Cartel.objects.filter(workgroup__name="X").exists()


def test_review_queue_gated_to_coordinator(client):
    plain = _member("plain@x.test")
    client.force_login(plain)
    assert client.get("/cartels/review/").status_code == 404
    client.force_login(_coordinator())
    assert client.get("/cartels/review/").status_code == 200


def test_coordinator_approves_via_view(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    coord = _coordinator()
    client.force_login(coord)
    resp = client.post(f"/cartels/review/{cartel.pk}/decide/", {"decision": "approve"})
    assert resp.status_code == 302
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.OPEN


def test_apply_and_member_accepts_via_views(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")

    client.force_login(applicant)
    resp = client.post(f"/cartels/{cartel.workgroup.slug}/apply/")
    assert resp.status_code == 302
    req = CartelJoinRequest.objects.get(cartel=cartel, applicant=applicant)
    assert req.status == CartelJoinRequest.Status.PENDING

    client.force_login(gen)   # an existing member gates
    resp = client.post(
        f"/cartels/{cartel.workgroup.slug}/requests/{req.pk}/decide/", {"decision": "accept"}
    )
    assert resp.status_code == 302
    assert cartel.is_member(applicant)


def test_propose_form_renders(client):
    client.force_login(_member("gen@x.test"))
    resp = client.get("/cartels/propose/")
    assert resp.status_code == 200
    assert b"Propose a cartel" in resp.content


def test_cartel_ui_composed_into_unified_groups_detail(client):
    """The cartel UI now renders on the unified /groups/<slug>/ page — guiding
    question, member-gating, and roster — composed from the cartel partial."""
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", guiding_question="What is a letter?")
    cartel.approve(_coordinator())
    cartel.request_to_join(_member("appl@x.test"))
    client.force_login(gen)
    resp = client.get(cartel.workgroup.get_absolute_url())   # /groups/<slug>/
    assert resp.status_code == 200
    assert b"What is a letter?" in resp.content   # guiding question
    assert b"Applications" in resp.content         # member-gating UI
    assert b"Members" in resp.content


def test_groups_detail_shows_apply_to_eligible_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    client.force_login(_member("outsider@x.test"))
    resp = client.get(cartel.workgroup.get_absolute_url())
    assert resp.status_code == 200
    assert b"Apply to join" in resp.content


def test_legacy_cartel_urls_redirect_to_groups(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    slug = cartel.workgroup.slug
    client.force_login(gen)
    assert client.get("/cartels/").status_code == 302
    assert client.get(f"/cartels/{slug}/").status_code == 302
    assert client.get(f"/cartels/{slug}/", follow=True).status_code == 200


def test_declined_cartel_can_be_edited_and_resubmitted(client):
    """Improvement 1: a declined proposal, edited by the generator, re-enters
    review (PROPOSED) and re-hides until re-approved."""
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", guiding_question="Q1")
    cartel.decline(_coordinator(), note="Sharpen the question.")
    client.force_login(gen)
    resp = client.post(f"/cartels/{cartel.workgroup.slug}/edit/", {
        "name": "C", "guiding_question": "A sharper question", "invitees": "",
    })
    assert resp.status_code == 302
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.PROPOSED
    assert cartel.guiding_question == "A sharper question"
    assert cartel.workgroup.landing_visibility == Visibility.PRIVATE   # hidden again
    # only the generator may edit
    client.force_login(_member("other@x.test"))
    assert client.get(f"/cartels/{cartel.workgroup.slug}/edit/").status_code == 404


def test_apply_captures_reason_shown_to_members(client):
    """Improvement 4: the application's 'why' is recorded and shown to members."""
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")
    client.force_login(applicant)
    client.post(f"/cartels/{cartel.workgroup.slug}/apply/", {"message": "I work on the letter."})
    req = CartelJoinRequest.objects.get(cartel=cartel, applicant=applicant)
    assert req.message == "I work on the letter."
    # a member sees the reason on the cartel page
    client.force_login(gen)
    resp = client.get(cartel.workgroup.get_absolute_url())
    assert b"I work on the letter." in resp.content


def test_member_can_close_and_archive(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    client.force_login(gen)
    client.post(f"/cartels/{cartel.workgroup.slug}/manage/", {"action": "close"})
    cartel.refresh_from_db()
    assert cartel.closed is True
    client.post(f"/cartels/{cartel.workgroup.slug}/manage/", {"action": "archive"})
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.ARCHIVED


def test_my_cartels_and_status_badge_on_kind_list(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(
        generator=gen, name="Speech and Writing", guiding_question="What is a letter?"
    )
    cartel.approve(_coordinator())
    client.force_login(gen)            # gen is a member of this cartel
    resp = client.get("/groups/cartels/")
    assert resp.status_code == 200
    assert b"My cartels" in resp.content
    assert b"Open \xc2\xb7 Join!" in resp.content   # status badge ("Open · Join!")


def test_workspace_tabs_shown_to_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    client.force_login(gen)
    resp = client.get(cartel.workgroup.get_absolute_url())
    assert resp.status_code == 200
    for tab in (b"Overview", b"Work", b"Settings"):
        assert tab in resp.content


def test_work_tab_splits_in_progress_and_released(client):
    from works.models import Work

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    Work.objects.create(title="Done Paper", slug="done", kind=Work.Kind.CARTEL,
                        listing_visibility=Work.Visibility.GROUP,
                        pdf_visibility=Work.Visibility.GROUP, workgroup=wg, in_progress=False)
    Work.objects.create(title="Draft Paper", slug="draft", kind=Work.Kind.CARTEL,
                        listing_visibility=Work.Visibility.GROUP,
                        pdf_visibility=Work.Visibility.GROUP, workgroup=wg, in_progress=True)
    client.force_login(gen)
    resp = client.get(f"{wg.get_absolute_url()}?tab=work")
    assert resp.status_code == 200
    assert b"In progress" in resp.content
    assert b"Draft Paper" in resp.content and b"Done Paper" in resp.content


def test_settings_dates_and_plus_one_flows(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    client.force_login(gen)

    # dates (generic workgroup setting)
    client.post(f"/groups/{wg.slug}/dates/", {"start_date": "2026-09-01", "end_date": "2027-05-01"})
    wg.refresh_from_db()
    assert str(wg.start_date) == "2026-09-01" and str(wg.end_date) == "2027-05-01"

    # internal plus-one
    p1 = _member("p1@x.test")
    cartel.add_member(p1)
    client.post(f"/cartels/{wg.slug}/plus-one/", {"user": p1.pk})
    assert wg.memberships.filter(
        user=p1, role=WorkgroupMembership.Role.PLUS_ONE, end_date__isnull=True
    ).exists()

    # external plus-one + invite
    client.post(f"/cartels/{wg.slug}/plus-one/external/",
                {"name": "Jane Ext", "affiliation": "Other Institute", "email": "jane@x.test"})
    ext = cartel.external_plus_ones.get()
    assert ext.name == "Jane Ext"
    client.post(f"/cartels/{wg.slug}/plus-one/external/{ext.pk}/invite/")
    ext.refresh_from_db()
    assert ext.invited_at is not None


def test_settings_endpoints_gated_to_members(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    client.force_login(_member("outsider@x.test"))   # not a member
    assert client.post(f"/groups/{wg.slug}/dates/", {}).status_code == 404
    assert client.post(f"/cartels/{wg.slug}/plus-one/external/", {"name": "X"}).status_code == 404
    # and the Settings tab isn't offered to a non-member
    resp = client.get(wg.get_absolute_url())
    assert b"Settings" not in resp.content


def test_discuss_and_chat_tabs_render_inline_for_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    assert wg.channels.filter(kind="forum").exists()
    assert wg.channels.filter(kind="chat").exists()

    client.force_login(gen)
    resp = client.get(wg.get_absolute_url())
    assert b"tab=discuss" in resp.content and b"tab=chat" in resp.content  # tabs offered

    d = client.get(f"{wg.get_absolute_url()}?tab=discuss")
    assert d.status_code == 200
    assert b"New thread" in d.content                 # inline forum
    c = client.get(f"{wg.get_absolute_url()}?tab=chat")
    assert c.status_code == 200
    assert b"data-chat" in c.content                  # inline chat (composer/stream)


def test_discuss_chat_tabs_hidden_from_non_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    client.force_login(_member("outsider@x.test"))
    resp = client.get(cartel.workgroup.get_absolute_url())
    assert b"tab=discuss" not in resp.content and b"tab=chat" not in resp.content


def test_proposed_cartel_hidden_from_other_members_on_kind_list(client):
    gen = _member("gen@x.test")
    Cartel.objects.propose(generator=gen, name="Secret Proposal")
    other = _member("other@x.test")
    client.force_login(other)
    resp = client.get("/groups/cartels/")
    assert b"Secret Proposal" not in resp.content   # private until approved
