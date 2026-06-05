"""Stage 2 — Parlêtre × Workgroups integration.

Auto-provisioning of a workgroup's channel, and the WORKGROUP access rules:
membership gates entry, and a workgroup channel is private to its group — no
staff bypass for any kind (cartel, working group, committee, seminar, reading
group).
"""

from __future__ import annotations

import datetime

import pytest

from accounts.models import Profile, User
from parletre.models import Channel
from parletre.permissions import channel_can_moderate, channel_visible
from workgroups.models import Workgroup, WorkgroupMembership

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.ANALYST, is_staff=False):
    u = User.objects.create_user(email=email, password="x", is_staff=is_staff)
    u.profile.role = role
    u.profile.save()
    return u


def _wg(kind=Workgroup.Kind.CARTEL, name="A Group", **kw):
    return Workgroup.objects.create(kind=kind, name=name, **kw)


def _join(wg, user, role=WorkgroupMembership.Role.MEMBER):
    return WorkgroupMembership.objects.create(
        workgroup=wg, user=user, role=role, start_date=datetime.date(2026, 1, 1)
    )


# ---- Auto-provisioning -------------------------------------------------

def test_workgroup_gets_forum_chat_video_channels_on_creation():
    wg = _wg(name="Speech and Writing")
    forum = wg.channels.get(kind=Channel.Kind.FORUM)
    chat = wg.channels.get(kind=Channel.Kind.CHAT)
    video = wg.channels.get(kind=Channel.Kind.VIDEO)
    assert forum.access == Channel.Access.WORKGROUP and forum.workgroup_id == wg.id
    assert chat.access == Channel.Access.WORKGROUP and chat.workgroup_id == wg.id
    assert video.access == Channel.Access.WORKGROUP and video.workgroup_id == wg.id
    assert wg.channels.count() == 3


def test_no_channel_when_has_channel_false():
    wg = _wg(name="Quiet Group", has_channel=False)
    assert wg.channels.count() == 0


def test_provision_is_idempotent():
    wg = _wg(name="Once Only")
    wg.description = "edited"
    wg.save()
    assert wg.channels.count() == 3   # forum + chat + video, not duplicated


def test_channel_category_matches_kind():
    cartel = _wg(kind=Workgroup.Kind.CARTEL, name="Cartel X")
    committee = _wg(kind=Workgroup.Kind.COMMITTEE, name="Finance Committee")
    assert cartel.channels.first().category.name == "Cartels"
    assert committee.channels.first().category.name == "Committees"


# ---- WORKGROUP access (visibility) ------------------------------------

def test_member_sees_channel_nonmember_does_not():
    wg = _wg()
    ch = wg.channels.first()
    insider = _user("in@x.test")
    outsider = _user("out@x.test")          # an LSP member, but not in the group
    _join(wg, insider)
    assert channel_visible(ch, insider) is True
    assert channel_visible(ch, outsider) is False


def test_cartel_channel_has_no_staff_bypass():
    wg = _wg(kind=Workgroup.Kind.CARTEL, name="Intimate Cartel")
    ch = wg.channels.first()
    staff = _user("staff@x.test", is_staff=True)
    assert channel_visible(ch, staff) is False
    assert channel_can_moderate(ch, staff) is False


def test_committee_channel_has_no_staff_bypass():
    # Workgroup channels are private to the group: no outsider, staff included,
    # may read or moderate them. (Previously committee/seminar kept a bypass.)
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Ethics Committee")
    ch = wg.channels.first()
    staff = _user("staff@x.test", is_staff=True)
    assert channel_visible(ch, staff) is False
    assert channel_can_moderate(ch, staff) is False


def test_seminar_channel_has_no_staff_bypass():
    wg = _wg(kind=Workgroup.Kind.SEMINAR, name="Clinic Seminar")
    ch = wg.channels.first()
    staff = _user("staff@x.test", is_staff=True)
    assert channel_visible(ch, staff) is False
    assert channel_can_moderate(ch, staff) is False


# ---- WORKGROUP moderation ---------------------------------------------

def test_chair_moderates_plus_one_and_plain_member_do_not():
    wg = _wg()
    ch = wg.channels.first()
    chair = _user("chair@x.test")
    plus_one = _user("plusone@x.test")
    plain = _user("plain@x.test")
    _join(wg, chair, role=WorkgroupMembership.Role.CHAIR)
    _join(wg, plus_one, role=WorkgroupMembership.Role.PLUS_ONE)
    _join(wg, plain)
    assert channel_can_moderate(ch, chair) is True
    # The plus-one is a guest, not a leader — it does not moderate.
    assert channel_can_moderate(ch, plus_one) is False
    assert channel_can_moderate(ch, plain) is False


def test_workgroup_channel_post_gated_by_membership():
    from parletre.permissions import channel_can_post

    wg = _wg()
    ch = wg.channels.first()
    insider = _user("in@x.test")
    outsider = _user("out@x.test")
    _join(wg, insider)
    assert channel_can_post(ch, insider) is True
    assert channel_can_post(ch, outsider) is False


# ---- LSP Staff designation (Stage 4 fold-in) --------------------------

def test_is_lsp_staff_designation_grants_board_entry():
    from accounts.permissions import is_lsp_member

    staffer = _user("staff@x.test", role=Profile.Role.EXTERNAL)
    assert is_lsp_member(staffer) is False
    from core.models import StaffRole
    StaffRole.objects.get(key=StaffRole.LSP_STAFF).holders.add(staffer)
    assert is_lsp_member(staffer) is True


def test_lsp_staff_channel_gated_by_designation():
    ch = Channel.objects.create(
        name="Staff Room", slug="staff-room", kind=Channel.Kind.FORUM,
        access=Channel.Access.LSP_STAFF,
    )
    plain = _user("plain@x.test")                                   # member, not staff
    staffer = _user("desig@x.test", role=Profile.Role.EXTERNAL)
    from core.models import StaffRole
    StaffRole.objects.get(key=StaffRole.LSP_STAFF).holders.add(staffer)
    assert channel_visible(ch, staffer) is True
    assert channel_visible(ch, plain) is False


# ---- Auditors: outside registrants confined to their seminar channel --

def _paid_seminar(name, slug, auditor):
    """A seminar workgroup with an attached event and a PAID registration for
    ``auditor`` — the derived-membership path for offering workgroups."""
    from datetime import date
    from decimal import Decimal

    from events.models import Audience, Event, PriceTier
    from registrations.models import Registration

    wg = _wg(kind=Workgroup.Kind.SEMINAR, name=name)
    event = Event.objects.create(
        title=name, slug=slug,
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        workgroup=wg,
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.EXTERNAL, base_amount=Decimal("0.00"),
    )
    Registration.objects.create(
        user=auditor, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=Registration.Status.PAID,
    )
    return wg


def test_auditor_with_paid_seminar_registration_is_confined_to_that_channel():
    from parletre.permissions import (
        can_enter_parletre,
        channel_can_post,
        channel_visible,
    )

    auditor = _user("aud@x.test", role=Profile.Role.EXTERNAL)
    # No registration yet: not a member, can't enter Parlêtre.
    assert can_enter_parletre(auditor) is False

    wg = _paid_seminar("Masochism Seminar", "masochism", auditor)
    seminar_ch = wg.channels.get(kind=Channel.Kind.FORUM)

    # Now they may enter — and post in — exactly their seminar's channel.
    assert can_enter_parletre(auditor) is True
    assert channel_visible(seminar_ch, auditor) is True
    assert channel_can_post(seminar_ch, auditor) is True

    # But nothing the wider membership sees: not an OPEN ("every member") channel,
    open_ch = Channel.objects.create(
        name="Commons", slug="commons", kind=Channel.Kind.FORUM,
        access=Channel.Access.OPEN,
    )
    assert channel_visible(open_ch, auditor) is False

    # not a ROLE-gated channel (external isn't an allowed role),
    role_ch = Channel.objects.create(
        name="Analysts", slug="analysts", kind=Channel.Kind.FORUM,
        access=Channel.Access.ROLE, allowed_roles=[Profile.Role.ANALYST],
    )
    assert channel_visible(role_ch, auditor) is False

    # and not another seminar's channel they aren't registered for.
    other = _wg(kind=Workgroup.Kind.SEMINAR, name="Other Seminar")
    assert channel_visible(other.channels.get(kind=Channel.Kind.FORUM), auditor) is False


def test_message_payload_includes_reply_context():
    """Realtime reply: the broadcast payload carries the parent's author +
    excerpt so live clients render the reply context (no refresh)."""
    from parletre.models import Post
    from parletre.realtime import message_payload

    wg = _wg(name="Realtime Cartel")
    chat = wg.channels.get(kind="chat")
    author = _user("a@x.test")
    parent = Post.objects.create(channel=chat, author=author, body="the parent message")
    reply = Post.objects.create(channel=chat, author=author, body="a reply", reply_to=parent)

    payload = message_payload(reply)
    assert payload["id"] == reply.id
    assert payload["reply_to"]["id"] == parent.id
    assert payload["reply_to"]["author"]  # parent author name present
    assert message_payload(parent)["reply_to"] is None
