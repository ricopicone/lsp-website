"""A room invitation names exactly one target (task #694)."""
from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from video.models import RoomInvitation

from .factories import seminar, special_event, user
from .test_personal_rooms import member, room_for

pytestmark = pytest.mark.django_db


def _workgroup():
    return seminar().ensure_workgroup()


def test_a_workgroup_invitation_needs_no_personal_room():
    wg = _workgroup()
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane"
    )
    assert invitation.target_object == wg


def test_two_targets_are_refused():
    wg = _workgroup()
    room = room_for(member())
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomInvitation.objects.create(
            workgroup=wg, personal_room=room,
            token=RoomInvitation.new_token(), guest_name="Jane",
        )


def test_no_target_is_refused():
    with pytest.raises(IntegrityError), transaction.atomic():
        RoomInvitation.objects.create(
            token=RoomInvitation.new_token(), guest_name="Jane"
        )


def test_invited_by_records_who_opened_the_door():
    wg = _workgroup()
    lead = user("lead@example.com")
    invitation = RoomInvitation.objects.create(
        workgroup=wg, token=RoomInvitation.new_token(), guest_name="Jane",
        invited_by=lead,
    )
    assert invitation.invited_by == lead


# ---- the target adapter -------------------------------------------------

def test_an_offering_event_targets_its_workgroup():
    from video import invitations

    event = seminar()
    wg = event.ensure_workgroup()
    assert invitations.target_for_event(event).owner == wg


def test_a_one_off_event_targets_itself():
    from video import invitations

    event = special_event()
    assert invitations.target_for_event(event).owner == event


def test_a_group_invitation_never_expires():
    from video import invitations

    assert invitations.target_for(_workgroup()).default_expiry() is None


def test_a_personal_guest_link_still_expires_in_thirty_days():
    from video import invitations

    assert invitations.target_for(room_for(member())).default_expiry() is not None
