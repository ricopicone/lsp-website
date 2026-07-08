"""Tests for the cartel CART-4 formation/joining workflow."""

from __future__ import annotations

import datetime as _dt

import pytest
from django.core.exceptions import ValidationError as _ValidationError

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
    from core.models import StaffRole

    u = _member(email)
    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(u)
    return u


def _pc_member(email="pc@x.test"):
    """A Programming Committee member (the cartel approver)."""
    from committees.models import Committee

    u = _member(email)
    Committee.objects.get(slug="programming-committee").add_member(u)
    return u


# ---- propose ----------------------------------------------------------

def test_propose_creates_forming_cartel_visible_to_school():
    from workgroups.models import Visibility, WorkgroupProposal
    gen = _member("gen@x.test")
    invitee = _member("inv@x.test")
    cartel = Cartel.objects.propose(
        generator=gen, name="Speech and Writing",
        guiding_question="What is a letter?", invitees=[invitee],
    )
    assert cartel.registration_status == Cartel.RegistrationStatus.FORMING
    assert cartel.proposal.status == WorkgroupProposal.Status.OPEN
    assert cartel.workgroup.landing_visibility == Visibility.MEMBERS
    assert cartel.workgroup.content_visibility == Visibility.PRIVATE
    assert cartel.is_member(gen) is True
    assert cartel.invitations.filter(invited_user=invitee).exists()
    # visible to the school from the start (open call)
    assert cartel.workgroup.landing_visible_to(_member("outsider@x.test")) is True


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


def test_review_queue_open_to_pc_and_coordinator_not_plain(client):
    cartel = Cartel.objects.propose(generator=_member("gen@x.test"), name="C")  # noqa: F841
    client.force_login(_member("plain@x.test"))
    assert client.get("/cartels/review/").status_code == 404
    client.force_login(_coordinator())
    assert client.get("/cartels/review/").status_code == 200   # CC advises
    client.force_login(_pc_member())
    assert client.get("/cartels/review/").status_code == 200   # PC approves


def test_pc_approves_but_coordinator_cannot(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")

    # The Cartel Coordinator may NOT approve (advisory only).
    client.force_login(_coordinator())
    assert client.post(
        f"/cartels/review/{cartel.pk}/decide/", {"decision": "approve"}
    ).status_code == 404
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.PROPOSED

    # The Program Committee approves & publishes.
    client.force_login(_pc_member())
    resp = client.post(f"/cartels/review/{cartel.pk}/decide/", {"decision": "approve"})
    assert resp.status_code == 302
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.OPEN


def test_coordinator_feedback_is_advisory(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    client.force_login(_coordinator())
    resp = client.post(
        f"/cartels/review/{cartel.pk}/feedback/",
        {"feedback": "Consider merging with the Letter cartel."},
    )
    assert resp.status_code == 302
    cartel.refresh_from_db()
    assert "Letter cartel" in cartel.coordinator_feedback
    assert cartel.status == Cartel.Status.PROPOSED   # feedback does not gate
    # a PC member can't leave coordinator feedback
    client.force_login(_pc_member())
    r = client.post(f"/cartels/review/{cartel.pk}/feedback/", {"feedback": "x"})
    assert r.status_code == 404


def test_apply_and_member_accepts_via_views(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    applicant = _member("appl@x.test")

    client.force_login(applicant)
    resp = client.post(f"/cartels/{cartel.workgroup.slug}/apply/")
    assert resp.status_code == 302
    req = CartelJoinRequest.objects.get(workgroup=cartel.workgroup, applicant=applicant)
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
    req = CartelJoinRequest.objects.get(workgroup=cartel.workgroup, applicant=applicant)
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


def test_open_cartel_details_editable_by_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", guiding_question="Q1")
    cartel.approve(_coordinator())
    member = _member("m@x.test")
    cartel.add_member(member)
    client.force_login(member)   # any member, not only the generator
    resp = client.post(f"/cartels/{cartel.workgroup.slug}/edit/", {
        "name": "Renamed cartel",
        "guiding_question": "A sharper question",
        "description": "New overview.",
    })
    assert resp.status_code == 302
    cartel.refresh_from_db()
    cartel.workgroup.refresh_from_db()
    assert cartel.guiding_question == "A sharper question"
    assert cartel.workgroup.name == "Renamed cartel"
    assert cartel.workgroup.description == "New overview."
    # Editing an open cartel must NOT bounce it back into review.
    assert cartel.status == Cartel.Status.OPEN


def test_edit_open_cartel_blocks_non_members(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C", guiding_question="Q1")
    cartel.approve(_coordinator())
    client.force_login(_member("outsider@x.test"))
    resp = client.post(f"/cartels/{cartel.workgroup.slug}/edit/", {
        "name": "Hijacked", "guiding_question": "Q", "description": "",
    })
    assert resp.status_code == 404


def test_internal_plus_one_can_be_unset(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    p1 = _member("p1@x.test")
    cartel.add_member(p1)
    client.force_login(gen)
    client.post(f"/cartels/{wg.slug}/plus-one/", {"user": p1.pk})
    assert wg.memberships.filter(
        user=p1, role=WorkgroupMembership.Role.PLUS_ONE, end_date__isnull=True
    ).exists()
    # Posting with no member selected clears the plus-one (back to member).
    client.post(f"/cartels/{wg.slug}/plus-one/", {})
    assert not wg.memberships.filter(
        role=WorkgroupMembership.Role.PLUS_ONE, end_date__isnull=True
    ).exists()
    assert wg.memberships.filter(
        user=p1, role=WorkgroupMembership.Role.MEMBER, end_date__isnull=True
    ).exists()


def test_external_plus_one_can_be_removed(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    client.force_login(gen)
    client.post(f"/cartels/{wg.slug}/plus-one/external/", {"name": "Jane Ext"})
    ext = cartel.external_plus_ones.get()
    client.post(f"/cartels/{wg.slug}/plus-one/external/{ext.pk}/remove/")
    assert not cartel.external_plus_ones.exists()


def test_archived_cartel_can_be_reactivated_by_member(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    client.force_login(gen)
    client.post(f"/cartels/{wg.slug}/manage/", {"action": "archive"})
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.ARCHIVED
    # The Settings tab + reactivate control stay reachable to the (now frozen)
    # stored member after archiving.
    resp = client.get(f"{wg.get_absolute_url()}?tab=settings")
    assert resp.status_code == 200
    assert b"Reactivate cartel" in resp.content
    client.post(f"/cartels/{wg.slug}/manage/", {"action": "reactivate"})
    cartel.refresh_from_db()
    assert cartel.status == Cartel.Status.OPEN
    assert cartel.workgroup.is_archived is False


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
                        content_visibility=Work.Visibility.GROUP, workgroup=wg, in_progress=False)
    Work.objects.create(title="Draft Paper", slug="draft", kind=Work.Kind.CARTEL,
                        listing_visibility=Work.Visibility.GROUP,
                        content_visibility=Work.Visibility.GROUP, workgroup=wg, in_progress=True)
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


def test_chat_inline_has_reply_and_reaction_in_action_row(client):
    from parletre.models import Post

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    chat = cartel.workgroup.channels.get(kind="chat")
    Post.objects.create(channel=chat, author=gen, body="hello")
    client.force_login(gen)
    resp = client.get(f"{cartel.workgroup.get_absolute_url()}?tab=chat")
    assert resp.status_code == 200
    assert b">Reply<" in resp.content              # reply in the action row
    assert b"Add a reaction" in resp.content        # reaction picker moved into the row
    assert b"reply_to=" in resp.content             # reply link present


def test_chat_reply_honored_inline_and_returns_via_next(client):
    from parletre.models import Post

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_coordinator())
    wg = cartel.workgroup
    chat = wg.channels.get(kind="chat")
    post = Post.objects.create(channel=chat, author=gen, body="hi")
    client.force_login(gen)

    # ?reply_to is honored inline — the composer's hidden reply_to is set.
    g = client.get(f"{wg.get_absolute_url()}?tab=chat&reply_to={post.id}")
    assert g.status_code == 200
    assert f'value="{post.id}"'.encode() in g.content

    # Posting a reply returns to the workspace chat tab (next), not Parlêtre.
    nxt = f"{wg.get_absolute_url()}?tab=chat"
    r = client.post(
        f"/parletre/{chat.slug}/",
        {"body": "a reply", "reply_to": post.id, "next": nxt},
    )
    assert r.status_code == 302 and r.url == nxt
    assert Post.objects.filter(channel=chat, reply_to=post).exists()


def test_tasks_tab_add_toggle_delete(client):
    from workgroups.models import WorkgroupTask

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")   # cartel seed has has_tasks=True
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    client.force_login(gen)

    # Tasks tab is offered to a member
    resp = client.get(wg.get_absolute_url())
    assert b"tab=tasks" in resp.content

    # add (with an assignee + due date)
    client.post(f"/groups/{wg.slug}/tasks/add/", {
        "title": "Read Écrits", "assignees": [gen.pk], "due_date": "2099-03-01",
    })
    task = WorkgroupTask.objects.get(workgroup=wg)
    assert task.title == "Read Écrits" and not task.done
    assert list(task.assignees.all()) == [gen]
    assert task.due_date.isoformat() == "2099-03-01"

    # toggle done
    client.post(f"/groups/{wg.slug}/tasks/{task.pk}/toggle/")
    task.refresh_from_db()
    assert task.done and task.completed_at is not None

    # the tab renders the task
    resp = client.get(f"{wg.get_absolute_url()}?tab=tasks")
    assert b"Read \xc3\x89crits" in resp.content

    # delete
    client.post(f"/groups/{wg.slug}/tasks/{task.pk}/delete/")
    assert not WorkgroupTask.objects.filter(pk=task.pk).exists()


def test_tasks_endpoints_gated_to_members(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    client.force_login(_member("outsider@x.test"))   # not a member
    assert client.post(f"/groups/{wg.slug}/tasks/add/", {"title": "x"}).status_code == 404
    resp = client.get(wg.get_absolute_url())
    assert b"tab=tasks" not in resp.content


def test_task_reassign_multiple_and_due_date(client):
    from workgroups.models import WorkgroupTask

    gen = _member("gen@x.test")
    other = _member("other@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    cartel.add_member(other)
    outsider = _member("outsider@x.test")   # not a member — must be ignored
    client.force_login(gen)

    client.post(f"/groups/{wg.slug}/tasks/add/", {"title": "T"})
    task = WorkgroupTask.objects.get(workgroup=wg)

    # Reassign to two members + the outsider; outsider is filtered out.
    client.post(f"/groups/{wg.slug}/tasks/{task.pk}/assign/", {
        "assignees": [gen.pk, other.pk, outsider.pk], "due_date": "2099-05-01",
    })
    task.refresh_from_db()
    assert set(task.assignees.all()) == {gen, other}
    assert task.due_date.isoformat() == "2099-05-01"

    # Clearing the due date and assignees.
    client.post(f"/groups/{wg.slug}/tasks/{task.pk}/assign/", {"due_date": ""})
    task.refresh_from_db()
    assert task.due_date is None and task.assignees.count() == 0


def test_task_overdue_and_search(client):
    from datetime import date, timedelta

    from workgroups.models import WorkgroupTask

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    client.force_login(gen)

    overdue = WorkgroupTask.objects.create(
        workgroup=wg, title="Overdue item", due_date=date.today() - timedelta(days=1))
    future = WorkgroupTask.objects.create(
        workgroup=wg, title="Future item", due_date=date.today() + timedelta(days=30))
    assert overdue.is_overdue and not future.is_overdue

    # Completed tasks are never flagged overdue.
    overdue.set_done(True)
    assert not overdue.is_overdue

    # Search filters the open list by title.
    resp = client.get(f"{wg.get_absolute_url()}?tab=tasks&q=Future")
    assert b"Future item" in resp.content and b"Overdue item" not in resp.content

    # The completed section surfaces done tasks.
    resp = client.get(f"{wg.get_absolute_url()}?tab=tasks")
    assert b"Completed (1)" in resp.content


def test_schedule_tab_add_and_delete(client):
    from workgroups.models import WorkgroupMeeting

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")   # cartel seed has has_calendar=True
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    client.force_login(gen)

    # Schedule tab is offered to a member
    resp = client.get(wg.get_absolute_url())
    assert b"tab=schedule" in resp.content

    # add a meeting
    client.post(f"/groups/{wg.slug}/meetings/add/", {
        "starts_at": "2099-01-15T18:00",
        "title": "First session",
        "location": "https://zoom.example/abc",
    })
    meeting = WorkgroupMeeting.objects.get(workgroup=wg)
    assert meeting.title == "First session" and meeting.created_by == gen

    # it renders under Upcoming (future date)
    resp = client.get(f"{wg.get_absolute_url()}?tab=schedule")
    assert b"First session" in resp.content

    # delete
    client.post(f"/groups/{wg.slug}/meetings/{meeting.pk}/delete/")
    assert not WorkgroupMeeting.objects.filter(pk=meeting.pk).exists()


def test_schedule_endpoints_gated_to_members(client):
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    client.force_login(_member("outsider@x.test"))   # not a member
    assert client.post(
        f"/groups/{wg.slug}/meetings/add/", {"starts_at": "2099-01-15T18:00"}
    ).status_code == 404
    resp = client.get(wg.get_absolute_url())
    assert b"tab=schedule" not in resp.content


def test_cartel_workspace_shows_kind_breadcrumb(client):
    """A cartel Workspace links back to the Cartels directory (its only
    structural parent — cartels self-form, so there's no program link)."""
    from django.urls import reverse

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    client.force_login(gen)

    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert reverse("workgroups:kind_cartels").encode() in resp.content   # ← Cartels
    assert b"/program/?year=" not in resp.content                        # no program for cartels


def test_open_cartel_listed_publicly_on_program(client):
    """An Open cartel active during the AY appears on the public program page
    (name + guiding question); Proposed cartels and the roster do not."""
    from events.models import Program, current_academic_year

    year = current_academic_year()
    Program.objects.create(academic_year=year, published=True)

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(
        generator=gen, name="The Sinthome", guiding_question="What is the sinthome?",
    )
    cartel.approve(_pc_member())   # → OPEN, reviewed_at=now → overlaps current AY

    # A still-Proposed cartel must NOT leak onto the program.
    Cartel.objects.propose(generator=gen, name="Secret Proposal")

    resp = client.get(f"/program/?year={year}")   # anonymous
    assert resp.status_code == 200
    assert b"The Sinthome" in resp.content
    assert b"What is the sinthome?" in resp.content
    assert b"Secret Proposal" not in resp.content


def test_cartel_not_listed_on_non_overlapping_year(client):
    from datetime import date

    from events.models import Program

    Program.objects.create(academic_year="2099-2100", published=True)
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="Past Cartel")
    cartel.approve(_pc_member())
    cartel.workgroup.start_date = date(2024, 9, 1)
    cartel.workgroup.end_date = date(2025, 5, 1)
    cartel.workgroup.save(update_fields=["start_date", "end_date"])

    resp = client.get("/program/?year=2099-2100")
    assert resp.status_code == 200
    assert b"Past Cartel" not in resp.content


def test_cartel_workspace_links_to_its_program(client):
    from events.models import Program, current_academic_year

    year = current_academic_year()
    Program.objects.create(academic_year=year, published=True)
    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())

    client.force_login(gen)
    resp = client.get(cartel.workgroup.get_absolute_url())
    assert resp.status_code == 200
    assert f"/program/?year={year}".encode() in resp.content   # ← Program <year>


def test_nested_group_links_back_to_parent_workgroup(client):
    """A nested group (e.g. a cartel under a parent working group) shows a
    stable back link to its parent — the cartel analog of seminar→program."""
    from workgroups.models import Workgroup, build_workgroup

    gen = _member("gen@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.approve(_pc_member())
    wg = cartel.workgroup
    parent = build_workgroup(
        Workgroup.Kind.WORKING_GROUP, name="Working Group on Cartels",
        slug="wg-on-cartels", landing_visibility="members",
    )
    wg.parent = parent
    wg.save(update_fields=["parent"])

    client.force_login(gen)
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert parent.get_absolute_url().encode() in resp.content
    assert b"Working Group on Cartels" in resp.content


def test_proposed_cartel_hidden_from_other_members_on_kind_list(client):
    gen = _member("gen@x.test")
    Cartel.objects.propose(generator=gen, name="Secret Proposal")
    other = _member("other@x.test")
    client.force_login(other)
    resp = client.get("/groups/cartels/")
    assert b"Secret Proposal" not in resp.content   # private until approved


# ---- registration_status / CartelQuestion (task #392) ----------------


def test_registration_status_defaults_to_forming():
    cartel = Cartel.objects.create_with_workgroup(name="C")
    assert cartel.registration_status == Cartel.RegistrationStatus.FORMING


def test_cartel_question_unique_per_member():
    from cartels.models import CartelQuestion
    cartel = Cartel.objects.create_with_workgroup(name="C")
    u = _member("q@x.test")
    CartelQuestion.objects.create(cartel=cartel, member=u, text="What is a letter?")
    assert cartel.member_questions.get(member=u).text == "What is a letter?"
    import pytest as _pytest
    from django.db import IntegrityError
    with _pytest.raises(IntegrityError):
        CartelQuestion.objects.create(cartel=cartel, member=u, text="dup")


# ---- submit-to-PC gate (task #392 step 3) -----------------------------


def _forming_cartel_ready(gen_email="g@x.test", n_members=3):
    """A forming cartel with n cartelisands + an internal plus-one + a valid
    1-year window (ready to submit)."""
    gen = _member(gen_email)
    # name includes gen_email so calling this helper more than once per test
    # (different gen_email each time) doesn't collide on Workgroup.slug.
    cartel = Cartel.objects.propose(generator=gen, name=f"Ready ({gen_email})")
    for i in range(1, n_members):
        cartel.add_member(_member(f"m{i}-{gen_email}"))
    plus = _member(f"plus-{gen_email}")
    cartel.set_internal_plus_one(plus)
    wg = cartel.workgroup
    wg.start_date = _dt.date(2026, 9, 1)
    wg.end_date = _dt.date(2027, 9, 1)   # 365 days
    wg.save(update_fields=["start_date", "end_date"])
    return cartel


def test_cartelisand_count_excludes_plus_one():
    cartel = _forming_cartel_ready(n_members=3)
    assert cartel.cartelisand_count() == 3   # plus-one not counted


def test_submit_blocked_without_plus_one():
    gen = _member("g@x.test")
    cartel = Cartel.objects.propose(generator=gen, name="C")
    cartel.add_member(_member("m2@x.test"))
    cartel.add_member(_member("m3@x.test"))
    wg = cartel.workgroup
    wg.start_date = _dt.date(2026, 9, 1)
    wg.end_date = _dt.date(2027, 9, 1)
    wg.save(update_fields=["start_date", "end_date"])
    assert cartel.registration_checklist()["plus_one"] is False
    with pytest.raises(_ValidationError):
        cartel.submit_for_registration(by=gen)


def test_submit_blocked_when_too_few_or_too_many():
    small = _forming_cartel_ready("small@x.test", n_members=2)   # 2 cartelisands
    assert small.registration_checklist()["count"] is False
    big = _forming_cartel_ready("big@x.test", n_members=6)       # 6 cartelisands
    assert big.registration_checklist()["count"] is False


def test_submit_blocked_when_duration_out_of_range():
    cartel = _forming_cartel_ready("dur@x.test")
    wg = cartel.workgroup
    wg.end_date = _dt.date(2029, 9, 1)   # ~3 years, too long
    wg.save(update_fields=["end_date"])
    assert cartel.registration_checklist()["duration"] is False
    with pytest.raises(_ValidationError):
        cartel.submit_for_registration(by=cartel.generator)


def test_submit_succeeds_when_gate_passes_questions_optional():
    cartel = _forming_cartel_ready("ok@x.test")
    check = cartel.registration_checklist()
    assert check["can_submit"] is True
    assert check["questions_done"] == 0   # no questions entered, still submittable
    cartel.submit_for_registration(by=cartel.generator)
    assert cartel.registration_status == Cartel.RegistrationStatus.SUBMITTED
