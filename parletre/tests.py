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
from committees.models import Committee
from workgroups.models import WorkgroupMembership

from .models import Channel, Post, Subscription, SubscriptionLevel, Thread
from .rendering import render_markdown

User = get_user_model()
Role = Profile.Role
Access = Channel.Access


# ---- factories ----------------------------------------------------------


def make_user(email, role=Role.ANALYST, is_staff=False, first="", last=""):
    user = User.objects.create_user(email=email, password="pw-test-12345")
    user.is_staff = is_staff
    user.first_name = first
    user.last_name = last
    user.save(update_fields=["is_staff", "first_name", "last_name"])
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


def add_to_committee(user, committee, role=WorkgroupMembership.Role.MEMBER):
    return committee.add_member(user, role=role, start_date=datetime.date(2026, 1, 1))


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
    committee_ch = make_channel("pc-legacy", access=Access.COMMITTEE, committee=pc)
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
    ch = make_channel("pc-legacy", access=Access.COMMITTEE, committee=pc)
    chair = make_user("chair@x.co", role=Role.ANALYST)
    add_to_committee(chair, pc, role=WorkgroupMembership.Role.CHAIR)
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
def test_index_summarises_workgroup_channels_under_your_groups(client):
    """A workgroup's forum/chat are not listed among the board's channels; the
    group instead appears once under "Your groups" for its members, and not at
    all for non-members."""
    from workgroups.models import Workgroup

    wg = Workgroup.objects.create(kind=Workgroup.Kind.CARTEL, name="Sinthome Cartel")
    forum = wg.channels.get(kind=Channel.Kind.FORUM)

    member = make_user("in@x.co", role=Role.ANALYST)
    wg.memberships.create(
        user=member, role=WorkgroupMembership.Role.MEMBER,
        start_date=datetime.date(2026, 1, 1),
    )
    client.force_login(member)
    body = client.get(reverse("parletre:index")).content.decode()
    assert "Your groups" in body
    assert wg.name in body
    assert wg.get_absolute_url() in body
    # the group's channel itself is not listed as a board channel
    assert forum.get_absolute_url() not in body

    other = make_user("out@x.co", role=Role.ANALYST)
    client.force_login(other)
    body = client.get(reverse("parletre:index")).content.decode()
    assert wg.name not in body
    assert "Your groups" not in body


@pytest.mark.django_db
def test_private_chats_listed_under_your_spaces(client):
    """Private chats appear in the "Your groups & private chats" section (with a
    type badge), not in the board's category listing."""
    member = make_user("m@x.co", role=Role.ANALYST)
    regular = make_channel("plans", kind=Channel.Kind.CHAT, access=Access.PRIVATE)
    regular.members.add(member)
    poof = make_channel(
        "poof", kind=Channel.Kind.CHAT, access=Access.PRIVATE, message_ttl_seconds=3600
    )
    poof.members.add(member)

    client.force_login(member)
    body = client.get(reverse("parletre:index")).content.decode()
    assert "Your groups &amp; private chats" in body
    assert regular.get_absolute_url() in body and poof.get_absolute_url() in body
    assert "Private chat" in body          # regular chat badge
    assert "Disappearing chat" in body     # ephemeral chat badge

    # someone not in the chats sees neither them nor the section.
    outsider = make_user("out@x.co", role=Role.ANALYST)
    client.force_login(outsider)
    body = client.get(reverse("parletre:index")).content.decode()
    assert regular.get_absolute_url() not in body
    assert "Your groups" not in body


@pytest.mark.django_db
def test_inaccessible_channel_404s_rather_than_revealing(client):
    make_channel("hush", access=Access.PRIVATE)
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.get(reverse("parletre:channel", args=["hush"]))
    assert resp.status_code == 404


# ---- member-created private chats ---------------------------------------


@pytest.mark.django_db
def test_member_creates_regular_private_chat(client):
    creator = make_user("c@x.co", role=Role.ANALYST, first="Cara", last="Creator")
    other = make_user("o@x.co", role=Role.ANALYST, first="Otto", last="Other")
    outsider = make_user("out@x.co", role=Role.ANALYST)
    client.force_login(creator)

    # the form page renders
    get = client.get(reverse("parletre:create_private_chat"))
    assert get.status_code == 200 and b"New private chat" in get.content

    resp = client.post(
        reverse("parletre:create_private_chat"),
        {"name": "Secret Plans", "lifetime": "", "participants": [other.pk]},
    )
    chan = Channel.objects.get(name="Secret Plans")
    assert resp.status_code == 302 and resp.url == chan.get_absolute_url()
    assert chan.kind == Channel.Kind.CHAT
    assert chan.access == Access.PRIVATE
    assert chan.message_ttl_seconds is None and not chan.is_ephemeral
    assert set(chan.members.all()) == {creator, other}
    assert creator in chan.moderators.all()
    # visibility follows the private-channel rules: members only.
    assert chan.visible_to(creator) and chan.visible_to(other)
    assert not chan.visible_to(outsider)
    # DM-style: both members are subscribed so they're notified of messages.
    assert Subscription.objects.filter(channel=chan, user=other).exists()


@pytest.mark.django_db
def test_member_creates_disappearing_chat(client):
    creator = make_user("c@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    client.force_login(creator)

    client.post(
        reverse("parletre:create_private_chat"),
        {"name": "Poof", "lifetime": "86400", "participants": [other.pk]},
    )
    chan = Channel.objects.get(name="Poof")
    assert chan.message_ttl_seconds == 86400 and chan.is_ephemeral


@pytest.mark.django_db
def test_private_chat_requires_a_participant(client):
    creator = make_user("c@x.co", role=Role.ANALYST)
    client.force_login(creator)
    resp = client.post(
        reverse("parletre:create_private_chat"),
        {"name": "Lonely", "lifetime": ""},
    )
    assert resp.status_code == 200  # re-rendered with errors
    assert not Channel.objects.filter(name="Lonely").exists()


@pytest.mark.django_db
def test_member_search_matches_excludes_self_and_gates_nonmembers(client):
    me = make_user("me@x.co", role=Role.ANALYST, first="Searcher", last="One")
    target = make_user("t@x.co", role=Role.ANALYST, first="Findme", last="Target")
    client.force_login(me)

    results = client.get(reverse("parletre:member_search"), {"q": "Findme"}).json()["results"]
    assert target.pk in [r["id"] for r in results]
    mine = client.get(reverse("parletre:member_search"), {"q": "Searcher"}).json()["results"]
    assert me.pk not in [r["id"] for r in mine]

    guest = make_user("g@x.co", role=Role.EXTERNAL)
    client.force_login(guest)
    assert client.get(reverse("parletre:member_search"), {"q": "Findme"}).status_code == 404


@pytest.mark.django_db
def test_creator_manages_participants(client):
    creator = make_user("c@x.co", role=Role.ANALYST)
    a = make_user("a@x.co", role=Role.ANALYST)
    b = make_user("b@x.co", role=Role.ANALYST)
    chan = make_channel("dm", kind=Channel.Kind.CHAT, access=Access.PRIVATE)
    chan.members.set([creator, a])
    chan.moderators.add(creator)
    Subscription.objects.create(user=a, channel=chan, level=SubscriptionLevel.ALL)

    client.force_login(creator)
    # the manage page renders for the creator
    get = client.get(reverse("parletre:manage_participants", args=[chan.slug]))
    assert get.status_code == 200 and b"Participants" in get.content

    resp = client.post(
        reverse("parletre:manage_participants", args=[chan.slug]),
        {"participants": [b.pk]},
    )
    assert resp.status_code == 302
    assert set(chan.members.all()) == {creator, b}  # creator always kept; a removed
    assert chan.visible_to(b) and not chan.visible_to(a)
    # the removed member's subscription is cleared so they stop being notified.
    assert not Subscription.objects.filter(user=a, channel=chan).exists()

    # a plain member (not a moderator) can't reach the manage surface.
    client.force_login(b)
    assert client.get(
        reverse("parletre:manage_participants", args=[chan.slug])
    ).status_code == 404


@pytest.mark.django_db
def test_created_via_view_records_creator(client):
    creator = make_user("c@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    client.force_login(creator)
    client.post(
        reverse("parletre:create_private_chat"),
        {"name": "Owned", "lifetime": "", "participants": [other.pk]},
    )
    chan = Channel.objects.get(name="Owned")
    assert chan.created_by == creator
    assert chan.can_delete(creator) and not chan.can_delete(other)
    assert chan.can_leave(other) and not chan.can_leave(creator)


@pytest.mark.django_db
def test_participant_can_leave_creator_cannot(client):
    creator = make_user("c@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    chan = make_channel("dm", kind=Channel.Kind.CHAT, access=Access.PRIVATE)
    chan.created_by = creator
    chan.save(update_fields=["created_by"])
    chan.members.set([creator, other])
    chan.moderators.add(creator)
    Subscription.objects.create(user=other, channel=chan, level=SubscriptionLevel.ALL)

    # the creator can't "leave" (they delete instead)
    client.force_login(creator)
    assert client.post(reverse("parletre:leave_chat", args=[chan.slug])).status_code == 404

    # a participant leaves: dropped, unsubscribed, and loses access
    client.force_login(other)
    resp = client.post(reverse("parletre:leave_chat", args=[chan.slug]))
    assert resp.status_code == 302
    assert other not in chan.members.all()
    assert not chan.visible_to(other)
    assert not Subscription.objects.filter(user=other, channel=chan).exists()


@pytest.mark.django_db
def test_creator_deletes_chat_others_cannot(client):
    creator = make_user("c@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    chan = make_channel("dm", kind=Channel.Kind.CHAT, access=Access.PRIVATE)
    chan.created_by = creator
    chan.save(update_fields=["created_by"])
    chan.members.set([creator, other])
    url = reverse("parletre:delete_chat", args=[chan.slug])

    # a participant who isn't the creator can't delete (even via POST)
    client.force_login(other)
    assert client.get(url).status_code == 404
    assert client.post(url).status_code == 404
    assert Channel.objects.filter(pk=chan.pk).exists()

    # the creator confirms (GET) then deletes (POST)
    client.force_login(creator)
    assert client.get(url).status_code == 200
    resp = client.post(url)
    assert resp.status_code == 302
    assert not Channel.objects.filter(pk=chan.pk).exists()


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


# ---- reactions ----------------------------------------------------------


@pytest.mark.django_db
def test_react_toggles_on_and_off(client):
    from .models import Reaction
    ch = make_channel("general")
    member = make_user("m@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=member)
    post = Post.objects.create(channel=ch, thread=thread, author=member, body="x")
    client.force_login(member)
    url = reverse("parletre:react", args=[post.id])

    client.post(url, {"emoji": "👍"})
    assert Reaction.objects.filter(post=post, user=member, emoji="👍").count() == 1
    # toggling the same emoji again removes it
    client.post(url, {"emoji": "👍"})
    assert Reaction.objects.filter(post=post, user=member, emoji="👍").count() == 0


@pytest.mark.django_db
def test_react_rejects_emoji_outside_palette(client):
    ch = make_channel("general")
    member = make_user("m@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=member)
    post = Post.objects.create(channel=ch, thread=thread, author=member, body="x")
    client.force_login(member)
    resp = client.post(reverse("parletre:react", args=[post.id]), {"emoji": "💣"})
    assert resp.status_code == 404


@pytest.mark.django_db
def test_react_blocked_on_invisible_channel(client):
    from .models import Reaction
    ch = make_channel("hush", access=Access.PRIVATE)
    insider = make_user("in@x.co", role=Role.ANALYST)
    ch.members.add(insider)
    thread = Thread.objects.create(channel=ch, title="T", author=insider)
    post = Post.objects.create(channel=ch, thread=thread, author=insider, body="x")
    outsider = make_user("out@x.co", role=Role.ANALYST)
    client.force_login(outsider)
    resp = client.post(reverse("parletre:react", args=[post.id]), {"emoji": "👍"})
    assert resp.status_code == 404
    assert Reaction.objects.count() == 0


# ---- mentions & notifications -------------------------------------------


def _named_member(first, last, email):
    """A member whose directory_slug is predictable (first-last)."""
    u = make_user(email, role=Role.ANALYST, first=first, last=last)
    return u


@pytest.mark.django_db
def test_mention_creates_notification(client):
    from .models import Notification
    ch = make_channel("commons")
    author = _named_member("Posy", "Poster", "posy@x.co")
    target = _named_member("Mona", "Member", "mona@x.co")
    assert target.profile.directory_slug == "mona-member"
    client.force_login(author)
    client.post(
        reverse("parletre:new_thread", args=[ch.slug]),
        {"title": "Hi", "body": "Welcome @mona-member to the school!"},
    )
    n = Notification.objects.get(recipient=target)
    assert n.verb == Notification.Verb.MENTION
    assert n.actor == author


@pytest.mark.django_db
def test_reply_notifies_thread_author_not_self(client):
    from .models import Notification
    ch = make_channel("commons")
    author = _named_member("Ana", "Author", "ana@x.co")
    replier = _named_member("Ray", "Replier", "ray@x.co")
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    Post.objects.create(channel=ch, thread=thread, author=author, body="first")

    # author replies to own thread -> no self-notification
    client.force_login(author)
    client.post(thread.get_absolute_url(), {"body": "my own follow-up"})
    assert not Notification.objects.filter(recipient=author).exists()

    # someone else replies -> author gets a REPLY notification
    client.force_login(replier)
    client.post(thread.get_absolute_url(), {"body": "a reply"})
    n = Notification.objects.get(recipient=author)
    assert n.verb == Notification.Verb.REPLY


@pytest.mark.django_db
def test_new_thread_notifies_close_followers(client):
    from .models import Notification, Subscription, SubscriptionLevel
    ch = make_channel("commons")
    author = _named_member("Ann", "Author", "ann@x.co")
    follower = _named_member("Fay", "Follower", "fay@x.co")
    digester = _named_member("Dot", "Digest", "dot@x.co")
    Subscription.objects.create(user=follower, channel=ch, level=SubscriptionLevel.ALL)
    Subscription.objects.create(user=digester, channel=ch, level=SubscriptionLevel.DIGEST)

    client.force_login(author)
    client.post(reverse("parletre:new_thread", args=[ch.slug]), {"title": "News", "body": "hi"})

    assert Notification.objects.filter(
        recipient=follower, verb=Notification.Verb.NEW_THREAD
    ).exists()
    # digest-level followers don't get an in-app new-thread ping
    assert not Notification.objects.filter(recipient=digester).exists()


@pytest.mark.django_db
def test_notifications_page_marks_all_read(client):
    from .models import Notification
    recipient = _named_member("Reed", "Recipient", "reed@x.co")
    actor = _named_member("Axe", "Actor", "axe@x.co")
    Notification.objects.create(
        recipient=recipient, actor=actor, verb=Notification.Verb.MENTION
    )
    assert Notification.objects.filter(recipient=recipient, read_at__isnull=True).count() == 1
    client.force_login(recipient)
    resp = client.get(reverse("parletre:notifications"))
    assert resp.status_code == 200
    assert Notification.objects.filter(recipient=recipient, read_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_bell_unread_count_in_nav(client):
    from .models import Notification
    member = _named_member("Bell", "Ringer", "bell@x.co")
    actor = _named_member("Axe", "Actor", "axe2@x.co")
    Notification.objects.create(recipient=member, actor=actor, verb=Notification.Verb.MENTION)
    client.force_login(member)
    resp = client.get(reverse("parletre:index"))
    assert resp.context["parletre_unread"] == 1
    # the bell is now an inline SVG icon, not an emoji
    assert 'aria-label="Notifications"' in resp.content.decode()


# ---- unread tracking ----------------------------------------------------


@pytest.mark.django_db
def test_thread_unread_until_viewed_then_clears(client):
    from .reads import unread_thread_ids
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    reader = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    Post.objects.create(channel=ch, thread=thread, author=author, body="hi")

    # never-read thread is unread for the reader
    assert thread.id in unread_thread_ids(reader, ch)

    # viewing it marks it read
    client.force_login(reader)
    client.get(thread.get_absolute_url())
    assert thread.id not in unread_thread_ids(reader, ch)


@pytest.mark.django_db
def test_new_reply_makes_thread_unread_again(client):
    from .reads import unread_thread_ids
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    reader = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    Post.objects.create(channel=ch, thread=thread, author=author, body="hi")

    client.force_login(reader)
    client.get(thread.get_absolute_url())
    assert thread.id not in unread_thread_ids(reader, ch)

    # a later reply (by someone else) bumps last_activity -> unread again
    client.force_login(author)
    client.post(thread.get_absolute_url(), {"body": "more"})
    assert thread.id in unread_thread_ids(reader, ch)


@pytest.mark.django_db
def test_index_marks_channel_unread(client):
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    reader = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    Post.objects.create(channel=ch, thread=thread, author=author, body="hi")

    client.force_login(reader)
    resp = client.get(reverse("parletre:index"))
    channels = [c for _label, chans in resp.context["groups"] for c in chans]
    target = next(c for c in channels if c.slug == "commons")
    assert target.is_unread is True


@pytest.mark.django_db
def test_thread_view_reports_first_unread(client):
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    reader = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    Post.objects.create(channel=ch, thread=thread, author=author, body="one")

    client.force_login(reader)
    client.get(thread.get_absolute_url())          # read up to here

    client.force_login(author)
    client.post(thread.get_absolute_url(), {"body": "two"})  # new post

    client.force_login(reader)
    resp = client.get(thread.get_absolute_url())
    second = Post.objects.filter(thread=thread).order_by("created_at").last()
    assert resp.context["first_unread_id"] == second.id


@pytest.mark.django_db
def test_chat_view_marks_channel_read(client):
    from .reads import unread_channel_ids
    ch = make_channel("lounge", kind=Channel.Kind.CHAT)
    author = make_user("a@x.co", role=Role.ANALYST)
    reader = make_user("r@x.co", role=Role.ANALYST)
    Post.objects.create(channel=ch, author=author, body="hello")

    client.force_login(reader)
    assert ch.id in unread_channel_ids(reader, [ch])
    client.get(ch.get_absolute_url())
    assert ch.id not in unread_channel_ids(reader, [ch])


# ---- attachments --------------------------------------------------------


def _upload(name, content=b"hello", content_type="text/plain"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.mark.django_db
def test_new_thread_with_attachment(client):
    from .models import Attachment
    ch = make_channel("commons")
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.post(
        reverse("parletre:new_thread", args=[ch.slug]),
        {"title": "With file", "body": "see attached",
         "attachments": _upload("notes.txt", b"important")},
    )
    assert resp.status_code == 302
    att = Attachment.objects.get()
    assert att.original_name == "notes.txt"
    assert att.size == len(b"important")
    assert att.post.thread.channel == ch


@pytest.mark.django_db
def test_reply_accepts_multiple_attachments(client):
    from .models import Attachment
    ch = make_channel("commons")
    member = make_user("m@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=member)
    Post.objects.create(channel=ch, thread=thread, author=member, body="first")
    client.force_login(member)
    resp = client.post(
        thread.get_absolute_url(),
        {"body": "two files",
         "attachments": [_upload("a.txt", b"a"), _upload("b.png", b"\x89PNG", "image/png")]},
    )
    assert resp.status_code == 302
    assert Attachment.objects.count() == 2
    assert Attachment.objects.filter(content_type="image/png").get().is_image


@pytest.mark.django_db
def test_attachment_download_gated_by_channel_visibility(client):
    from .models import Attachment
    ch = make_channel("hush", access=Access.PRIVATE)
    insider = make_user("in@x.co", role=Role.ANALYST)
    ch.members.add(insider)
    thread = Thread.objects.create(channel=ch, title="T", author=insider)
    post = Post.objects.create(channel=ch, thread=thread, author=insider, body="x")
    att = Attachment.objects.create(
        post=post, file=_upload("secret.txt", b"top secret"),
        original_name="secret.txt", content_type="text/plain", size=10,
    )
    url = reverse("parletre:attachment", args=[att.id])

    # an outsider can't download it
    outsider = make_user("out@x.co", role=Role.ANALYST)
    client.force_login(outsider)
    assert client.get(url).status_code == 404

    # the insider can
    client.force_login(insider)
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"top secret" in b"".join(resp.streaming_content)


@pytest.mark.django_db
def test_attachment_rejects_oversized_file(client):
    from .models import MAX_ATTACHMENT_BYTES
    ch = make_channel("commons")
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    big = _upload("big.bin", b"x" * (MAX_ATTACHMENT_BYTES + 1), "application/octet-stream")
    resp = client.post(
        reverse("parletre:new_thread", args=[ch.slug]),
        {"title": "Too big", "body": "oops", "attachments": big},
    )
    # form re-renders with an error; no thread created
    assert resp.status_code == 200
    assert not Thread.objects.filter(channel=ch).exists()


@pytest.mark.django_db
def test_attachment_stored_privately_and_has_no_public_url():
    """Attachments live outside the public media root, and FieldFile.url
    raises (base_url=None) so no public link can be built by accident."""
    from django.conf import settings

    from .models import Attachment
    ch = make_channel("commons")
    member = make_user("m@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=member)
    post = Post.objects.create(channel=ch, thread=thread, author=member, body="x")
    att = Attachment.objects.create(
        post=post, file=_upload("p.txt", b"data"),
        original_name="p.txt", content_type="text/plain", size=4,
    )
    assert att.file.storage.location == settings.PARLETRE_ATTACHMENTS_ROOT
    assert str(settings.MEDIA_ROOT) not in att.file.path
    with pytest.raises(ValueError):
        _ = att.file.url


# ---- mention autocomplete ----------------------------------------------


@pytest.mark.django_db
def test_mention_search_returns_matching_members(client):
    make_user("a@x.co", role=Role.ANALYST, first="Mona", last="Member")
    make_user("b@x.co", role=Role.ANALYST, first="Carl", last="Candidate")
    searcher = make_user("s@x.co", role=Role.ANALYST, first="Sue", last="Searcher")
    client.force_login(searcher)
    resp = client.get(reverse("parletre:mention_search"), {"q": "mona"})
    assert resp.status_code == 200
    slugs = [r["slug"] for r in resp.json()["results"]]
    assert "mona-member" in slugs
    assert "carl-candidate" not in slugs


@pytest.mark.django_db
def test_mention_search_excludes_members_who_cant_see_channel(client):
    ch = make_channel("hush", access=Access.PRIVATE)
    insider = make_user("in@x.co", role=Role.ANALYST, first="Iris", last="Inside")
    make_user("out@x.co", role=Role.ANALYST, first="Ida", last="Inside")  # not in channel
    ch.members.add(insider)
    searcher = make_user("s@x.co", role=Role.ANALYST, first="Sue", last="Searcher")
    ch.members.add(searcher)
    client.force_login(searcher)
    resp = client.get(
        reverse("parletre:mention_search"), {"q": "inside", "channel": ch.slug}
    )
    slugs = [r["slug"] for r in resp.json()["results"]]
    assert "iris-inside" in slugs
    assert "ida-inside" not in slugs   # can't see the private channel


@pytest.mark.django_db
def test_mention_search_requires_membership(client):
    guest = make_user("g@x.co", role=Role.EXTERNAL)
    client.force_login(guest)
    assert client.get(reverse("parletre:mention_search"), {"q": "x"}).status_code == 404


@pytest.mark.django_db
def test_mention_search_empty_query(client):
    m = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(m)
    resp = client.get(reverse("parletre:mention_search"), {"q": ""})
    assert resp.json()["results"] == []


# ---- reply tokens -------------------------------------------------------


def test_reply_token_roundtrip_and_tamper_detection():
    from .tokens import THREAD, make_token, parse_token
    tok = make_token(THREAD, 7, 42)
    assert parse_token(tok) == {"kind": "t", "target_id": 7, "user_id": 42}
    assert parse_token(tok[:-1] + ("y" if tok[-1] != "y" else "z")) is None
    assert parse_token("not-a-token") is None


# ---- immediate notification emails --------------------------------------


@pytest.mark.django_db
def test_all_subscriber_gets_immediate_email_on_post(mailoutbox):
    from .services import notify_post
    ch = make_channel("commons")
    author = make_user("a@x.co", first="Ana", last="Author")
    follower = make_user("f@x.co", role=Role.ANALYST)
    Subscription.objects.create(user=follower, channel=ch, level=SubscriptionLevel.ALL)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="hi all")
    notify_post(post)
    assert [m.to for m in mailoutbox] == [[follower.email]]


@pytest.mark.django_db
def test_mention_emails_even_at_digest_level_but_not_when_muted(mailoutbox):
    from .services import notify_post
    ch = make_channel("commons")
    author = make_user("a@x.co", first="Ana", last="Author")
    target = make_user("t@x.co", role=Role.ANALYST, first="Mona", last="Member")
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    # no subscription row -> effective level is the channel default (digest)
    post = Post.objects.create(
        channel=ch, thread=thread, author=author, body="hello @mona-member"
    )
    notify_post(post)
    assert [m.to for m in mailoutbox] == [[target.email]]

    mailoutbox.clear()
    Subscription.objects.create(user=target, channel=ch, level=SubscriptionLevel.MUTED)
    post2 = Post.objects.create(
        channel=ch, thread=thread, author=author, body="again @mona-member"
    )
    notify_post(post2)
    assert mailoutbox == []


@pytest.mark.django_db
def test_digest_level_gets_no_immediate_email(mailoutbox):
    from .services import notify_post
    ch = make_channel("commons")
    author = make_user("a@x.co")
    quiet = make_user("q@x.co", role=Role.ANALYST)
    Subscription.objects.create(user=quiet, channel=ch, level=SubscriptionLevel.DIGEST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="hi")
    notify_post(post)
    assert mailoutbox == []


@pytest.mark.django_db
def test_reply_to_carries_token_when_enabled(mailoutbox, settings):
    from .services import notify_post
    from .tokens import parse_token
    settings.PARLETRE_REPLY_ENABLED = True
    settings.PARLETRE_REPLY_DOMAIN = "parletre.lacanschool.org"
    ch = make_channel("commons")
    author = make_user("a@x.co")
    follower = make_user("f@x.co", role=Role.ANALYST)
    Subscription.objects.create(user=follower, channel=ch, level=SubscriptionLevel.ALL)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="hi")
    notify_post(post)
    reply_to = mailoutbox[0].reply_to[0]
    assert reply_to.startswith("reply+") and "@parletre.lacanschool.org" in reply_to
    token = reply_to[len("reply+"):].split("@", 1)[0]
    parsed = parse_token(token)
    assert parsed == {"kind": "t", "target_id": thread.id, "user_id": follower.id}


@pytest.mark.django_db
def test_reply_to_is_support_when_disabled(mailoutbox, settings):
    from .services import notify_post
    settings.PARLETRE_REPLY_ENABLED = False
    ch = make_channel("commons")
    author = make_user("a@x.co")
    follower = make_user("f@x.co", role=Role.ANALYST)
    Subscription.objects.create(user=follower, channel=ch, level=SubscriptionLevel.ALL)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="hi")
    notify_post(post)
    assert mailoutbox[0].reply_to == [settings.SUPPORT_EMAIL]


# ---- digests ------------------------------------------------------------


@pytest.mark.django_db
def test_build_sections_only_includes_digest_channels_and_others_posts():
    from datetime import timedelta

    from django.utils import timezone

    from .digests import build_sections
    me = make_user("me@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)

    digest_ch = make_channel("commons")
    loud_ch = make_channel("loud")
    Subscription.objects.create(user=me, channel=digest_ch, level=SubscriptionLevel.DIGEST)
    Subscription.objects.create(user=me, channel=loud_ch, level=SubscriptionLevel.ALL)

    t1 = Thread.objects.create(channel=digest_ch, title="Digest thread", author=other)
    Post.objects.create(channel=digest_ch, thread=t1, author=other, body="new")
    # my own post shouldn't appear
    Post.objects.create(channel=digest_ch, thread=t1, author=me, body="mine")
    # a loud channel is emailed immediately, not in the digest
    t2 = Thread.objects.create(channel=loud_ch, title="Loud", author=other)
    Post.objects.create(channel=loud_ch, thread=t2, author=other, body="loud")

    since = timezone.now() - timedelta(days=1)
    sections = build_sections(me, since)
    assert len(sections) == 1
    assert sections[0]["channel"] == digest_ch
    posts = sections[0]["groups"][0]["posts"]
    assert [p.body for p in posts] == ["new"]   # not "mine", not "loud"


@pytest.mark.django_db
def test_digest_command_sends_and_advances_watermark(mailoutbox):
    from django.core.management import call_command

    from .models import DigestPreference
    me = make_user("me@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    ch = make_channel("commons")
    Subscription.objects.create(user=me, channel=ch, level=SubscriptionLevel.DIGEST)
    DigestPreference.objects.create(user=me, frequency=DigestPreference.Frequency.DAILY)
    t = Thread.objects.create(channel=ch, title="Hi", author=other)
    Post.objects.create(channel=ch, thread=t, author=other, body="news")

    call_command("send_discussion_digests")
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [me.email]
    pref = DigestPreference.objects.get(user=me)
    assert pref.last_sent_at is not None

    # running again immediately sends nothing (cadence not yet due, nothing new)
    mailoutbox.clear()
    call_command("send_discussion_digests")
    assert mailoutbox == []


@pytest.mark.django_db
def test_digest_off_sends_nothing(mailoutbox):
    from django.core.management import call_command

    from .models import DigestPreference
    me = make_user("me@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    ch = make_channel("commons")
    Subscription.objects.create(user=me, channel=ch, level=SubscriptionLevel.DIGEST)
    DigestPreference.objects.create(user=me, frequency=DigestPreference.Frequency.OFF)
    t = Thread.objects.create(channel=ch, title="Hi", author=other)
    Post.objects.create(channel=ch, thread=t, author=other, body="news")
    call_command("send_discussion_digests")
    assert mailoutbox == []


@pytest.mark.django_db
def test_settings_page_updates_digest_frequency(client):
    from .models import DigestPreference
    me = make_user("me@x.co", role=Role.ANALYST)
    client.force_login(me)
    resp = client.post(reverse("parletre:settings"), {"frequency": "daily"})
    assert resp.status_code == 302
    assert DigestPreference.objects.get(user=me).frequency == "daily"


# ---- reply-by-email inbound ---------------------------------------------


def _raw_email(to_addr, from_addr, body, *, subject="Re: a thread", message_id="<m1@ex>"):
    from email.message import EmailMessage
    m = EmailMessage()
    m["To"] = to_addr
    m["From"] = from_addr
    m["Subject"] = subject
    if message_id:
        m["Message-ID"] = message_id
    m.set_content(body)
    return m.as_bytes()


def _reply_addr(kind, target_id, user_id):
    from .tokens import make_token
    return f"reply+{make_token(kind, target_id, user_id)}@parletre.lacanschool.org"


def test_extract_reply_strips_quote_and_signature():
    from .inbound import extract_reply
    raw = "My new reply.\n\nOn Tue, Ana wrote:\n> the original\n> more"
    assert extract_reply(raw) == "My new reply."
    assert extract_reply("Top line\n-- \nRay\nblog.example") == "Top line"


@pytest.mark.django_db
def test_inbound_posts_reply_from_matching_sender():
    from .inbound import process_inbound_email
    from .tokens import THREAD
    ch = make_channel("commons")
    author = make_user("a@x.co")
    replier = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    Post.objects.create(channel=ch, thread=thread, author=author, body="orig")

    raw = _raw_email(
        _reply_addr(THREAD, thread.id, replier.id), replier.email,
        "Here is my reply.\n\nOn Tue, A wrote:\n> orig",
    )
    res = process_inbound_email(raw)
    assert res["status"] == "posted"
    post = thread.posts.get(via_email=True)
    assert post.author == replier
    assert post.body == "Here is my reply."


@pytest.mark.django_db
def test_inbound_rejects_bad_token_and_sender_mismatch():
    from .inbound import process_inbound_email
    from .models import Post as P
    from .tokens import THREAD
    ch = make_channel("commons")
    author = make_user("a@x.co")
    replier = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)

    bad = _raw_email("reply+garbage@parletre.lacanschool.org", replier.email, "hi")
    assert process_inbound_email(bad)["status"] == "bad_token"

    # valid token but the email comes From someone else
    spoof = _raw_email(
        _reply_addr(THREAD, thread.id, replier.id), "imposter@x.co", "hi",
        message_id="<m2@ex>",
    )
    assert process_inbound_email(spoof)["status"] == "sender_mismatch"
    assert not P.objects.filter(via_email=True).exists()


@pytest.mark.django_db
def test_inbound_is_idempotent_on_message_id():
    from .inbound import process_inbound_email
    from .tokens import THREAD
    ch = make_channel("commons")
    author = make_user("a@x.co")
    replier = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    raw = _raw_email(
        _reply_addr(THREAD, thread.id, replier.id), replier.email, "once",
        message_id="<dupe@ex>",
    )
    assert process_inbound_email(raw)["status"] == "posted"
    assert process_inbound_email(raw)["status"] == "duplicate"
    assert thread.posts.filter(via_email=True).count() == 1


@pytest.mark.django_db
def test_inbound_blocks_locked_thread():
    from .inbound import process_inbound_email
    from .tokens import THREAD
    ch = make_channel("commons")
    author = make_user("a@x.co")
    replier = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author, locked=True)
    raw = _raw_email(_reply_addr(THREAD, thread.id, replier.id), replier.email, "hi")
    assert process_inbound_email(raw)["status"] == "cannot_post"


@pytest.mark.django_db
def test_inbound_webhook_processes_sns_notification(client):
    import base64
    import json

    from .tokens import THREAD
    ch = make_channel("commons")
    author = make_user("a@x.co")
    replier = make_user("r@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    raw = _raw_email(_reply_addr(THREAD, thread.id, replier.id), replier.email, "via sns")

    envelope = {
        "Type": "Notification",
        "Message": json.dumps({"content": base64.b64encode(raw).decode()}),
    }
    resp = client.post(
        reverse("parletre:inbound"), data=json.dumps(envelope),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"
    assert thread.posts.filter(via_email=True, body="via sns").exists()


@pytest.mark.django_db
def test_inbound_webhook_rejects_wrong_topic(client, settings):
    import json
    settings.PARLETRE_SNS_TOPIC_ARN = "arn:aws:sns:expected"
    resp = client.post(
        reverse("parletre:inbound"),
        data=json.dumps({"Type": "Notification", "TopicArn": "arn:aws:sns:other"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


# ---- realtime chat (WebSocket consumer, M13.5b) -------------------------


def _ws(user, slug):
    from channels.routing import URLRouter
    from channels.testing import WebsocketCommunicator

    from .routing import websocket_urlpatterns
    comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f"/ws/parletre/{slug}/")
    comm.scope["user"] = user
    return comm


@pytest.mark.django_db(transaction=True)
def test_chat_consumer_posts_and_broadcasts():
    from asgiref.sync import async_to_sync
    member = make_user("m@x.co", role=Role.ANALYST)
    ch = make_channel("lounge", kind=Channel.Kind.CHAT)

    async def scenario():
        comm = _ws(member, ch.slug)
        connected, _ = await comm.connect()
        assert connected
        first = await comm.receive_json_from()        # our own join presence
        assert first["kind"] == "presence" and first["event"] == "join"
        await comm.send_json_to({"body": "hello **live**"})
        msg = await comm.receive_json_from()
        assert msg["kind"] == "message"
        assert "<strong>live</strong>" in msg["body_html"]
        assert msg["author"]  # has a display name
        await comm.disconnect()

    async_to_sync(scenario)()
    assert Post.objects.filter(channel=ch, body="hello **live**", thread__isnull=True).exists()


@pytest.mark.django_db(transaction=True)
def test_chat_consumer_rejects_non_member():
    from asgiref.sync import async_to_sync
    guest = make_user("g@x.co", role=Role.EXTERNAL)
    ch = make_channel("lounge", kind=Channel.Kind.CHAT)

    async def scenario():
        comm = _ws(guest, ch.slug)
        connected, _ = await comm.connect()
        assert not connected
        await comm.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db(transaction=True)
def test_chat_consumer_rejects_forum_channel():
    from asgiref.sync import async_to_sync
    member = make_user("m@x.co", role=Role.ANALYST)
    ch = make_channel("forum-ch")  # default kind = forum

    async def scenario():
        comm = _ws(member, ch.slug)
        connected, _ = await comm.connect()
        assert not connected
        await comm.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db(transaction=True)
def test_chat_consumer_staff_only_channel_blocks_member_send():
    from asgiref.sync import async_to_sync
    member = make_user("m@x.co", role=Role.ANALYST)
    ch = make_channel("announce-chat", kind=Channel.Kind.CHAT,
                      post_policy=Channel.PostPolicy.STAFF_ONLY)

    async def scenario():
        comm = _ws(member, ch.slug)
        connected, _ = await comm.connect()
        assert connected                              # may read
        await comm.receive_json_from()                # join presence
        await comm.send_json_to({"body": "sneak"})    # but not post
        assert await comm.receive_nothing(timeout=0.3)
        await comm.disconnect()

    async_to_sync(scenario)()
    assert not Post.objects.filter(channel=ch).exists()


# ---- search (DISC-4) ----------------------------------------------------


@pytest.mark.django_db
def test_search_finds_body_and_thread_title_matches():
    from .search import search_posts
    member = make_user("m@x.co", role=Role.ANALYST)
    ch = make_channel("commons")
    t1 = Thread.objects.create(channel=ch, title="On the sinthome", author=member)
    Post.objects.create(channel=ch, thread=t1, author=member, body="a note about jouissance")
    t2 = Thread.objects.create(channel=ch, title="Cartel logistics", author=member)
    Post.objects.create(channel=ch, thread=t2, author=member, body="meeting at noon")

    body_hits = search_posts(member, "jouissance")
    assert [p.thread_id for p in body_hits] == [t1.id]
    # a thread-title term matches its posts too
    title_hits = search_posts(member, "sinthome")
    assert t1.id in [p.thread_id for p in title_hits]


@pytest.mark.django_db
def test_search_excludes_invisible_channels_and_deleted():
    from .search import search_posts
    member = make_user("m@x.co", role=Role.ANALYST)
    visible = make_channel("commons")
    private = make_channel("hush", access=Access.PRIVATE)  # member not in it
    tv = Thread.objects.create(channel=visible, title="T", author=member)
    Post.objects.create(channel=visible, thread=tv, author=member, body="needle here")
    insider = make_user("in@x.co", role=Role.ANALYST)
    private.members.add(insider)
    tp = Thread.objects.create(channel=private, title="P", author=insider)
    Post.objects.create(channel=private, thread=tp, author=insider, body="needle in private")
    # a deleted post shouldn't match
    Post.objects.create(
        channel=visible, thread=tv, author=member, body="needle deleted", deleted=True
    )

    hits = search_posts(member, "needle")
    bodies = [p.body for p in hits]
    assert "needle here" in bodies
    assert "needle in private" not in bodies   # private channel hidden
    assert "needle deleted" not in bodies


@pytest.mark.django_db
def test_search_view_renders_results(client):
    member = make_user("m@x.co", role=Role.ANALYST)
    ch = make_channel("commons")
    t = Thread.objects.create(channel=ch, title="T", author=member)
    Post.objects.create(channel=ch, thread=t, author=member, body="the mirror stage essay")
    client.force_login(member)
    resp = client.get(reverse("parletre:search"), {"q": "mirror"})
    assert resp.status_code == 200
    assert b"<mark>mirror</mark>" in resp.content   # match highlighted in the snippet


@pytest.mark.django_db
def test_search_empty_query_returns_no_results(client):
    member = make_user("m@x.co", role=Role.ANALYST)
    client.force_login(member)
    resp = client.get(reverse("parletre:search"), {"q": ""})
    assert resp.status_code == 200
    assert resp.context["results"] == []


def test_make_snippet_highlights_and_escapes():
    from .search import make_snippet
    out = make_snippet("Discussing <b>jouissance</b> & the Real", "jouissance")
    assert "<mark>jouissance</mark>" in out
    assert "&lt;b&gt;" in out and "&amp;" in out   # original HTML/amp escaped


# ---- edit / delete / reply (post actions) -------------------------------


@pytest.mark.django_db
def test_author_can_edit_own_post(client):
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="original")
    client.force_login(author)
    resp = client.post(reverse("parletre:edit_post", args=[post.id]), {"body": "edited now"})
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.body == "edited now"
    assert post.edited_at is not None


@pytest.mark.django_db
def test_non_author_cannot_edit(client):
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="original")
    client.force_login(other)
    resp = client.post(reverse("parletre:edit_post", args=[post.id]), {"body": "hax"})
    assert resp.status_code == 404
    post.refresh_from_db()
    assert post.body == "original"


@pytest.mark.django_db
def test_author_can_delete_own_post(client):
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="bye")
    client.force_login(author)
    resp = client.post(reverse("parletre:delete_post", args=[post.id]))
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.deleted is True


@pytest.mark.django_db
def test_moderator_can_delete_others_but_member_cannot(client):
    ch = make_channel("commons")
    author = make_user("a@x.co", role=Role.ANALYST)
    mod = make_user("mod@x.co", role=Role.ANALYST)
    ch.moderators.add(mod)
    bystander = make_user("b@x.co", role=Role.ANALYST)
    thread = Thread.objects.create(channel=ch, title="T", author=author)
    post = Post.objects.create(channel=ch, thread=thread, author=author, body="x")

    client.force_login(bystander)
    assert client.post(reverse("parletre:delete_post", args=[post.id])).status_code == 404
    post.refresh_from_db()
    assert post.deleted is False

    client.force_login(mod)
    assert client.post(reverse("parletre:delete_post", args=[post.id])).status_code == 302
    post.refresh_from_db()
    assert post.deleted is True


@pytest.mark.django_db
def test_chat_reply_sets_reply_to(client):
    ch = make_channel("lounge", kind=Channel.Kind.CHAT)
    member = make_user("m@x.co", role=Role.ANALYST)
    parent = Post.objects.create(channel=ch, author=member, body="parent message")
    client.force_login(member)
    client.post(ch.get_absolute_url(), {"body": "a reply", "reply_to": parent.id})
    child = Post.objects.filter(channel=ch, body="a reply").get()
    assert child.reply_to_id == parent.id


@pytest.mark.django_db
def test_reply_to_in_other_channel_is_ignored(client):
    a = make_channel("a", kind=Channel.Kind.CHAT)
    b = make_channel("b", kind=Channel.Kind.CHAT)
    member = make_user("m@x.co", role=Role.ANALYST)
    foreign = Post.objects.create(channel=b, author=member, body="elsewhere")
    client.force_login(member)
    client.post(a.get_absolute_url(), {"body": "hi", "reply_to": foreign.id})
    child = Post.objects.filter(channel=a, body="hi").get()
    assert child.reply_to_id is None   # cross-channel parent rejected, not an error


@pytest.mark.django_db
def test_edit_404_on_invisible_channel(client):
    ch = make_channel("hush", access=Access.PRIVATE)
    insider = make_user("in@x.co", role=Role.ANALYST)
    ch.members.add(insider)
    thread = Thread.objects.create(channel=ch, title="T", author=insider)
    post = Post.objects.create(channel=ch, thread=thread, author=insider, body="secret")
    outsider = make_user("out@x.co", role=Role.ANALYST)
    client.force_login(outsider)
    assert client.get(reverse("parletre:edit_post", args=[post.id])).status_code == 404


# ---- disappearing messages (Purloined Letters) --------------------------


@pytest.mark.django_db
def test_ephemeral_chat_redacts_expired_keeps_fresh(client):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone
    ch = make_channel("ple", kind=Channel.Kind.CHAT, message_ttl_seconds=3600)
    member = make_user("m@x.co", role=Role.ANALYST)
    old = Post.objects.create(channel=ch, author=member, body="old one")
    Post.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=2))
    fresh = Post.objects.create(channel=ch, author=member, body="fresh one")

    client.force_login(member)
    body = client.get(ch.get_absolute_url()).content.decode()
    assert "fresh one" in body and "old one" not in body   # old is blacked out, fresh shows

    call_command("purge_expired_messages")
    old.refresh_from_db()
    assert old.redacted is True and "█" in old.body         # redacted in place, not deleted
    assert Post.objects.filter(id=old.id).exists()
    fresh.refresh_from_db()
    assert not fresh.redacted                                # fresh untouched


@pytest.mark.django_db
def test_ephemeral_channel_skips_notifications(mailoutbox):
    from .models import Notification
    from .services import notify_post
    ch = make_channel("ple", kind=Channel.Kind.CHAT, message_ttl_seconds=3600)
    author = make_user("a@x.co", role=Role.ANALYST)
    follower = make_user("f@x.co", role=Role.ANALYST)
    Subscription.objects.create(user=follower, channel=ch, level=SubscriptionLevel.ALL)
    post = Post.objects.create(channel=ch, author=author, body="hello @f-follower")
    notify_post(post)
    assert Notification.objects.count() == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_search_and_digest_exclude_ephemeral():
    from datetime import timedelta

    from django.utils import timezone

    from .digests import build_sections
    from .search import search_posts
    me = make_user("me@x.co", role=Role.ANALYST)
    other = make_user("o@x.co", role=Role.ANALYST)
    ch = make_channel("ple", kind=Channel.Kind.CHAT, message_ttl_seconds=3600)
    Subscription.objects.create(user=me, channel=ch, level=SubscriptionLevel.DIGEST)
    Post.objects.create(channel=ch, author=other, body="needle in disappearing chat")
    assert search_posts(me, "needle") == []
    assert build_sections(me, timezone.now() - timedelta(days=1)) == []


@pytest.mark.django_db
def test_seed_creates_purloined_letters():
    from django.core.management import call_command
    call_command("seed_parletre")
    ch = Channel.objects.get(slug="purloined-letters")
    assert ch.is_ephemeral and ch.message_ttl_seconds == 86400
    assert ch.kind == Channel.Kind.CHAT
    assert ch.ttl_display == "1 day"


# ---- redacted disappearing messages -------------------------------------


def test_blackout_preserves_shape_not_content():
    from .models import blackout
    assert blackout("Has everyone read?") == "███ ████████ █████"
    assert blackout("a b\nc") == "█ █\n█"
    assert blackout("") == ""


@pytest.mark.django_db
def test_expired_message_is_redacted_on_read_not_hidden(client):
    from datetime import timedelta

    from django.utils import timezone
    ch = make_channel("ple", kind=Channel.Kind.CHAT, message_ttl_seconds=3600)
    member = make_user("m@x.co", role=Role.ANALYST)
    old = Post.objects.create(channel=ch, author=member, body="secret words here")
    Post.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=2))
    client.force_login(member)
    body = client.get(ch.get_absolute_url()).content.decode()
    assert "secret words here" not in body   # real content never sent
    assert "█" in body                        # shown as a redaction bar


@pytest.mark.django_db
def test_purge_command_redacts_body_and_deletes_files_keeps_row():
    from datetime import timedelta

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command
    from django.utils import timezone

    from .models import Attachment
    ch = make_channel("ple", kind=Channel.Kind.CHAT, message_ttl_seconds=3600)
    member = make_user("m@x.co", role=Role.ANALYST)
    old = Post.objects.create(channel=ch, author=member, body="will vanish soon")
    att = Attachment.objects.create(
        post=old, file=SimpleUploadedFile("p.txt", b"data"),
        original_name="p.txt", content_type="text/plain", size=4,
    )
    Post.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=2))

    call_command("purge_expired_messages")
    old.refresh_from_db()
    assert old.redacted is True
    assert "will" not in old.body and "█" in old.body
    att.refresh_from_db()
    assert not att.file                                  # real file gone
    assert Attachment.objects.filter(id=att.id).exists()  # row kept (for the black box)


@pytest.mark.django_db
def test_redacted_attachment_download_is_404(client):
    from datetime import timedelta

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    from .models import Attachment
    ch = make_channel("ple", kind=Channel.Kind.CHAT, message_ttl_seconds=3600)
    member = make_user("m@x.co", role=Role.ANALYST)
    old = Post.objects.create(channel=ch, author=member, body="x")
    att = Attachment.objects.create(
        post=old, file=SimpleUploadedFile("s.txt", b"top secret"),
        original_name="s.txt", content_type="text/plain", size=10,
    )
    Post.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=2))
    client.force_login(member)
    # past TTL → refused even before the cron persists redaction
    assert client.get(reverse("parletre:attachment", args=[att.id])).status_code == 404
