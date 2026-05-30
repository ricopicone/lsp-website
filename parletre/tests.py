"""Tests for Parlêtre access control and model invariants.

The access model (who may see / post / moderate which channel) is the
security-sensitive heart of the board, so it carries the bulk of the tests.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import Profile
from committees.models import Committee, CommitteeMembership

from .models import Channel, Post, Subscription, SubscriptionLevel, Thread
from .rendering import render_markdown

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


# ---- markdown sanitisation ----------------------------------------------


def test_render_markdown_keeps_formatting_but_strips_xss():
    html = render_markdown("Hello **bold** and [ok](https://x.co)")
    assert "<strong>bold</strong>" in html
    assert 'href="https://x.co"' in html

    danger = render_markdown("[x](javascript:alert(1))\n\n<script>alert(1)</script>")
    assert "javascript:" not in danger
    assert "<script>" not in danger


# ---- views: gating & posting --------------------------------------------


@pytest.mark.django_db
def test_index_redirects_anonymous_to_login(client):
    resp = client.get(reverse("parletre:index"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_index_forbidden_for_non_member(client):
    guest = make_user("guest@x.co", role=Role.EXTERNAL)
    client.force_login(guest)
    resp = client.get(reverse("parletre:index"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_index_lists_open_channel_but_not_inaccessible_private(client):
    make_channel("open-one")
    private = make_channel("hush", access=Access.PRIVATE)
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.get(reverse("parletre:index"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Open One" in body
    assert private.name not in body
    # the privacy promise is on the page
    assert "including channels marked" in body


@pytest.mark.django_db
def test_inaccessible_channel_404s_rather_than_revealing(client):
    make_channel("hush", access=Access.PRIVATE)
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.get(reverse("parletre:channel", args=["hush"]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_member_can_start_thread_and_reply(client):
    ch = make_channel("general")
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)

    resp = client.post(
        reverse("parletre:new_thread", args=[ch.slug]),
        {"title": "On the sinthome", "body": "First."},
    )
    assert resp.status_code == 302
    thread = Thread.objects.get(channel=ch, title="On the sinthome")
    assert thread.posts.count() == 1
    before = thread.last_activity_at

    resp = client.post(thread.get_absolute_url(), {"body": "A reply."})
    assert resp.status_code == 302
    thread.refresh_from_db()
    assert thread.posts.count() == 2
    assert thread.last_activity_at >= before


@pytest.mark.django_db
def test_staff_only_channel_rejects_member_thread(client):
    ch = make_channel("announce", post_policy=Channel.PostPolicy.STAFF_ONLY)
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.post(
        reverse("parletre:new_thread", args=[ch.slug]),
        {"title": "Sneaky", "body": "Hi."},
    )
    # redirected back with an error message; no thread created
    assert resp.status_code == 302
    assert not Thread.objects.filter(channel=ch).exists()


@pytest.mark.django_db
def test_subscribe_sets_level_and_protects_announcements(client):
    ch = make_channel("general")
    announce = make_channel("announce", auto_subscribe=True)
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)

    client.post(reverse("parletre:subscribe", args=[ch.slug]), {"level": "all"})
    assert Subscription.objects.get(user=member, channel=ch).level == SubscriptionLevel.ALL

    # the announcements channel may be downgraded but not fully muted
    client.post(reverse("parletre:subscribe", args=[announce.slug]), {"level": "muted"})
    sub = Subscription.objects.filter(user=member, channel=announce).first()
    assert sub is None or sub.level != SubscriptionLevel.MUTED


@pytest.mark.django_db
def test_chat_channel_accepts_a_post(client):
    ch = make_channel("lounge", kind=Channel.Kind.CHAT)
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.post(ch.get_absolute_url(), {"body": "hello room"})
    assert resp.status_code == 302
    msg = Post.objects.get(channel=ch, thread__isnull=True)
    assert msg.body == "hello room"


@pytest.mark.django_db
def test_moderator_can_pin_but_member_cannot(client):
    ch = make_channel("general")
    mod = make_user("mod@x.co", role=Role.ANALYST)
    ch.moderators.add(mod)
    member = make_user("m@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=member)
    Post.objects.create(channel=ch, thread=thread, author=member, body="x")
    url = reverse("parletre:moderate_thread", args=[ch.slug, thread.slug])

    client.force_login(member)
    assert client.post(url, {"action": "pin"}).status_code == 404
    thread.refresh_from_db()
    assert not thread.pinned

    client.force_login(mod)
    assert client.post(url, {"action": "pin"}).status_code == 302
    thread.refresh_from_db()
    assert thread.pinned


# ---- template render smoke tests ----------------------------------------


@pytest.mark.django_db
def test_forum_channel_thread_and_new_thread_render(client):
    ch = make_channel("general")
    member = make_user("m@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="Hello", author=member)
    Post.objects.create(channel=ch, thread=thread, author=member, body="**hi**")
    client.force_login(member)
    assert client.get(ch.get_absolute_url()).status_code == 200
    assert client.get(thread.get_absolute_url()).status_code == 200
    assert client.get(reverse("parletre:new_thread", args=[ch.slug])).status_code == 200


@pytest.mark.django_db
def test_chat_channel_renders(client):
    ch = make_channel("lounge", kind=Channel.Kind.CHAT)
    member = make_user("m@x.co", role=Role.ANALYST)
    Post.objects.create(channel=ch, author=member, body="hi room")
    client.force_login(member)
    assert client.get(ch.get_absolute_url()).status_code == 200
