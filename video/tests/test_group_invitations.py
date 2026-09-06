"""A guest is never the first one in a group's room (task #694)."""
from __future__ import annotations

import pytest

from video import invitations as inv
from video.models import RoomInvitation

from .factories import daily_on, seminar, user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _daily_on():
    with daily_on:
        yield


@pytest.fixture
def present(monkeypatch):
    state = {"live": False}
    monkeypatch.setattr(
        "video.services.room_participant_count", lambda room: 1 if state["live"] else 0
    )
    return state


def group():
    return seminar().ensure_workgroup()


def test_an_invited_outsider_waits_for_an_empty_room(present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    with pytest.raises(inv.EntryRefused) as refused:
        inv.check_entry(inv.target_for(wg), guest, invitation=invitation)
    assert refused.value.waiting is True


def test_the_same_outsider_is_admitted_once_someone_is_in_it(present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    present["live"] = True
    inv.check_entry(inv.target_for(wg), guest, invitation=invitation)


def test_an_uninvited_stranger_is_refused_outright(present):
    present["live"] = True
    stranger = user("stranger@example.com")
    with pytest.raises(inv.EntryRefused) as refused:
        inv.check_entry(inv.target_for(group()), stranger)
    assert refused.value.waiting is False


def test_a_revoked_invitation_does_not_admit(present):
    wg = group()
    guest = user("guest@example.com")
    invitation = RoomInvitation.objects.create(workgroup=wg, invited_user=guest)
    invitation.revoke()
    present["live"] = True
    with pytest.raises(inv.EntryRefused):
        inv.check_entry(inv.target_for(wg), guest, invitation=invitation)


def test_a_member_never_meets_the_doorstep(present):
    """An invitation is a fallback for someone ``can_enter`` refuses, so a member
    who is also invited is admitted as a member, in an empty room."""
    ev = seminar()
    wg = ev.ensure_workgroup()
    lead = user("lead@example.com", is_faculty=True)
    ev.add_faculty(lead)
    inv.check_entry(inv.target_for(wg), lead)


def test_a_personal_room_is_refused_this_path():
    from .test_personal_rooms import member, room_for

    target = inv.target_for(room_for(member()))
    with pytest.raises(TypeError):
        inv.check_entry(target, user("someone@example.com"))


def test_a_group_room_gains_no_daily_lobby():
    from video import services

    assert services._desired_properties(group())["enable_knocking"] is False


# ---- the form -----------------------------------------------------------

def test_the_picker_leaves_out_people_already_on_the_roster():
    from video.forms_invitations import InvitationForm

    wg = group()
    inside = user("inside@example.com")
    outside = user("outside@example.com")
    wg.add_member(inside)
    form = InvitationForm(target=inv.target_for(wg))
    choices = set(form.fields["members"].queryset.values_list("pk", flat=True))
    assert outside.pk in choices
    assert inside.pk not in choices


def test_building_a_group_invitation_records_the_inviter_and_no_expiry():
    from video.forms_invitations import InvitationForm, Recipient

    wg = group()
    lead = user("lead@example.com")
    guest = user("guest@example.com")
    form = InvitationForm(target=inv.target_for(wg))
    invitation = form.build(Recipient(user=guest, name="", email=""), by=lead)
    assert invitation.workgroup == wg
    assert invitation.expires_at is None
    assert invitation.invited_by == lead


def test_a_group_guest_link_does_not_expire_either():
    from video.forms_invitations import InvitationForm, Recipient

    form = InvitationForm(target=inv.target_for(group()))
    invitation = form.build(Recipient(user=None, name="Jane Doe", email=""))
    assert invitation.is_guest
    assert invitation.expires_at is None
