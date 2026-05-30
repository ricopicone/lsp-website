"""Tests for Parlêtre access control and model invariants.

The access model (who may see / post / moderate which channel) is the
security-sensitive heart of the board, so it carries the bulk of the tests.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth import get_user_model

from accounts.models import Profile
from committees.models import Committee, CommitteeMembership

from .models import Channel, Subscription, Thread

User = get_user_model()
Role = Profile.Role
Access = Channel.Access


# ---- factories ----------------------------------------------------------


def make_user(email, role=Role.ANALYST, is_staff=False):
    user = User.objects.create_user(email=email, password="pw-test-12345")
    if is_staff:
        user.is_staff = True
        user.save(update_fields=["is_staff"])
    user.profile.role = role
    user.profile.save(update_fields=["role"])
    return user


def make_channel(slug="general", **kwargs):
    kwargs.setdefault("name", slug.replace("-", " ").title())
    return Channel.objects.create(slug=slug, **kwargs)


def make_committee(slug, name=None):
    """Fetch-or-create a committee (Board / PC / Staff are already seeded by
    a committees migration, so plain create() would collide on slug)."""
    committee, _ = Committee.objects.get_or_create(
        slug=slug, defaults={"name": name or slug.replace("-", " ").title()}
    )
    return committee


def add_to_committee(user, committee, role=CommitteeMembership.Role.MEMBER):
    return CommitteeMembership.objects.create(
        user=user,
        committee=committee,
        role_in_committee=role,
        start_date=datetime.date(2026, 1, 1),
    )


# ---- the board-wide gate: is_member -------------------------------------


@pytest.mark.django_db
def test_member_role_user_is_a_member():
    ch = make_channel()
    assert ch.visible_to(make_user("analyst@x.co", role=Role.ANALYST))
    assert ch.visible_to(make_user("scholar@x.co", role=Role.SCHOLAR))
    assert ch.visible_to(make_user("cand@x.co", role=Role.CANDIDATE))


@pytest.mark.django_db
def test_guest_student_and_applicant_are_not_members():
    ch = make_channel()
    assert not ch.visible_to(make_user("guest@x.co", role=Role.EXTERNAL))
    assert not ch.visible_to(make_user("student@x.co", role=Role.STUDENT))
    assert not ch.visible_to(make_user("appl@x.co", role=Role.PROSPECTIVE_APPLICANT))


@pytest.mark.django_db
def test_anonymous_user_sees_nothing():
    assert not make_channel().visible_to(None)


@pytest.mark.django_db
def test_committee_member_with_nonmember_role_still_gets_in():
    """An admin assistant carried as a guest role still belongs on the board."""
    ch = make_channel()
    staffer = make_user("aa@x.co", role=Role.EXTERNAL)
    board = make_committee("board", "Board")
    add_to_committee(staffer, board)
    assert ch.visible_to(staffer)


@pytest.mark.django_db
def test_expired_committee_membership_does_not_grant_entry():
    ch = make_channel()
    guest = make_user("ex@x.co", role=Role.EXTERNAL)
    board = make_committee("board", "Board")
    m = add_to_committee(guest, board)
    m.end_date = datetime.date(2026, 2, 1)
    m.save(update_fields=["end_date"])
    assert not ch.visible_to(guest)


# ---- per-channel access modes -------------------------------------------


@pytest.mark.django_db
def test_role_gated_channel():
    ch = make_channel("analysts", access=Access.ROLE, allowed_roles=["analyst"])
    assert ch.visible_to(make_user("a@x.co", role=Role.ANALYST))
    # a member of a different role is still a member, but not of this channel
    assert not ch.visible_to(make_user("c@x.co", role=Role.CANDIDATE))


@pytest.mark.django_db
def test_committee_gated_channel():
    pc = make_committee("programming-committee", "Programming Committee")
    ch = make_channel("pc", access=Access.COMMITTEE, committee=pc)
    on_pc = make_user("on@x.co", role=Role.ANALYST)
    add_to_committee(on_pc, pc)
    off_pc = make_user("off@x.co", role=Role.ANALYST)
    assert ch.visible_to(on_pc)
    assert not ch.visible_to(off_pc)


@pytest.mark.django_db
def test_private_channel_only_named_members():
    ch = make_channel("hush", access=Access.PRIVATE)
    inside = make_user("in@x.co", role=Role.ANALYST)
    outside = make_user("out@x.co", role=Role.ANALYST)
    ch.members.add(inside)
    assert ch.visible_to(inside)
    assert not ch.visible_to(outside)


@pytest.mark.django_db
def test_private_channel_is_private_even_from_staff():
    """Private means private: staff get no god-mode bypass here."""
    ch = make_channel("hush", access=Access.PRIVATE)
    staff = make_user("s@x.co", role=Role.EXTERNAL, is_staff=True)
    assert not ch.visible_to(staff)
    assert not ch.can_moderate(staff)


@pytest.mark.django_db
def test_private_channel_named_moderator_can_see_and_moderate():
    ch = make_channel("hush", access=Access.PRIVATE)
    mod = make_user("mod@x.co", role=Role.ANALYST)
    ch.moderators.add(mod)
    assert ch.visible_to(mod)
    assert ch.can_moderate(mod)


@pytest.mark.django_db
def test_staff_see_role_and_committee_channels_but_not_private():
    staff = make_user("s@x.co", role=Role.EXTERNAL, is_staff=True)
    private = make_channel("hush", access=Access.PRIVATE)
    role_ch = make_channel("analysts", access=Access.ROLE, allowed_roles=["analyst"])
    pc = make_committee("pc", "PC")
    committee_ch = make_channel("pc", access=Access.COMMITTEE, committee=pc)
    assert role_ch.visible_to(staff)
    assert committee_ch.visible_to(staff)
    assert not private.visible_to(staff)


@pytest.mark.django_db
def test_archived_channel_hidden_from_members_shown_to_moderators():
    ch = make_channel("old", archived=True)
    member = make_user("m@x.co", role=Role.ANALYST)
    staff = make_user("s@x.co", role=Role.EXTERNAL, is_staff=True)
    assert not ch.visible_to(member)
    assert ch.visible_to(staff)


# ---- posting & moderation -----------------------------------------------


@pytest.mark.django_db
def test_staff_only_channel_blocks_member_posts_but_allows_moderators():
    ch = make_channel("announce", post_policy=Channel.PostPolicy.STAFF_ONLY)
    member = make_user("m@x.co", role=Role.ANALYST)
    mod = make_user("mod@x.co", role=Role.ANALYST)
    ch.moderators.add(mod)
    assert ch.visible_to(member)          # everyone may read announcements
    assert not ch.can_post(member)        # but only moderators post
    assert ch.can_post(mod)


@pytest.mark.django_db
def test_committee_chair_moderates_its_channel_but_plain_member_does_not():
    pc = make_committee("pc", "PC")
    ch = make_channel("pc", access=Access.COMMITTEE, committee=pc)
    chair = make_user("chair@x.co", role=Role.ANALYST)
    add_to_committee(chair, pc, role=CommitteeMembership.Role.CHAIR)
    plain = make_user("plain@x.co", role=Role.ANALYST)
    add_to_committee(plain, pc)
    assert ch.can_moderate(chair)
    assert not ch.can_moderate(plain)


# ---- model invariants ---------------------------------------------------


@pytest.mark.django_db
def test_thread_slug_unique_within_channel_but_reusable_across_channels():
    a = make_channel("a")
    b = make_channel("b")
    t1 = Thread.objects.create(channel=a, title="The Mirror Stage")
    t2 = Thread.objects.create(channel=a, title="The Mirror Stage")
    t3 = Thread.objects.create(channel=b, title="The Mirror Stage")
    assert t1.slug == "the-mirror-stage"
    assert t2.slug == "the-mirror-stage-2"
    assert t3.slug == "the-mirror-stage"  # different channel, no collision


@pytest.mark.django_db
def test_subscription_is_unique_per_user_channel():
    from django.db import IntegrityError

    ch = make_channel()
    user = make_user("u@x.co", role=Role.ANALYST)
    Subscription.objects.create(user=user, channel=ch)
    with pytest.raises(IntegrityError):
        Subscription.objects.create(user=user, channel=ch)
