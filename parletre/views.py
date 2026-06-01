"""Parlêtre views — the member-facing discussion board (M13.5a).

All views require login *and* board entry (:func:`permissions.can_enter_parletre`
— members, plus auditors confined to their seminar channel). Channels a user
can't access 404 rather than reveal their existence.

Covers the forum loop (browse / start / reply / chat / subscribe), reactions,
@mentions + notifications, unread tracking, attachments, the digest-settings
page, and the reply-by-email inbound webhook. Realtime chat transport
(WebSockets) is the remaining M13.5b increment.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import Profile

from .forms import (
    EditPostForm,
    NewPrivateChatForm,
    NewThreadForm,
    ParticipantsForm,
    PostForm,
)
from .inbound import process_inbound_email
from .models import (
    REACTION_EMOJI,
    Attachment,
    Channel,
    ChannelCategory,
    DigestPreference,
    Notification,
    Post,
    Reaction,
    Subscription,
    SubscriptionLevel,
    Thread,
    _unique_slug,
)
from .permissions import can_enter_parletre, is_member
from .reads import (
    mark_channel_read,
    mark_thread_read,
    thread_marker_at,
    unread_channel_ids,
    unread_thread_ids,
)
from .realtime import broadcast_chat_post
from .search import make_snippet, search_posts
from .services import notify_new_thread, notify_post

log = logging.getLogger("parletre")


def _attach_reactions(posts, user, can_moderate=False, ephemeral_cutoff=None):
    """Annotate each post with ``reaction_summary``, ``can_edit`` /
    ``can_delete`` flags, and ``is_redacted`` (already redacted, or past the
    channel's TTL — so the view blacks it out even before the cron persists
    the redaction). ``can_moderate`` is the channel-level moderator status
    (computed once). Expects ``reactions`` prefetched."""
    posts = list(posts)
    uid = user.id if getattr(user, "is_authenticated", False) else None
    for post in posts:
        summary: dict[str, dict] = {}
        for reaction in post.reactions.all():
            entry = summary.setdefault(
                reaction.emoji, {"emoji": reaction.emoji, "count": 0, "mine": False}
            )
            entry["count"] += 1
            if reaction.user_id == uid:
                entry["mine"] = True
        post.reaction_summary = list(summary.values())
        post.is_redacted = post.redacted or (
            ephemeral_cutoff is not None and post.created_at < ephemeral_cutoff
        )
        active = not post.deleted and not post.is_redacted
        post.can_edit = active and post.author_id is not None and post.author_id == uid
        post.can_delete = active and (post.author_id == uid or can_moderate)
    return posts


def _save_attachments(post, files) -> None:
    for f in files or []:
        Attachment.objects.create(
            post=post,
            file=f,
            original_name=f.name[:255],
            content_type=getattr(f, "content_type", "") or "",
            size=getattr(f, "size", 0) or 0,
        )


def _reply_parent(reply_to_id, channel):
    """Resolve a reply_to id to a valid parent: a non-deleted post in ``channel``."""
    if not reply_to_id:
        return None
    return (
        Post.objects.filter(pk=reply_to_id, channel=channel, deleted=False)
        .select_related("author")
        .first()
    )


def _post_url(post) -> str:
    base = post.thread.get_absolute_url() if post.thread_id else post.channel.get_absolute_url()
    return f"{base}#post-{post.id}"


def _visible_channel_or_404(user, slug: str) -> Channel:
    channel = get_object_or_404(
        Channel.objects.select_related("category", "committee"), slug=slug
    )
    if not channel.visible_to(user):
        raise Http404("No such channel.")
    return channel


def _ensure_auto_subscriptions(user, channels) -> None:
    """Force a subscription on every auto_subscribe channel the member can see
    (the Announcements pattern). Idempotent; safe to call on each visit."""
    for channel in channels:
        if channel.auto_subscribe:
            Subscription.objects.get_or_create(
                user=user,
                channel=channel,
                defaults={"level": SubscriptionLevel.ALL},
            )


@login_required
def index(request):
    """Overview of every channel the member may see, grouped by category."""
    if not can_enter_parletre(request.user):
        return render(request, "parletre/not_a_member.html", status=403)

    channels = list(
        Channel.objects.select_related("category", "committee", "workgroup")
        .prefetch_related("members", "moderators")
        .order_by("category__position", "position", "name")
    )
    visible = [c for c in channels if c.visible_to(request.user)]
    _ensure_auto_subscriptions(request.user, visible)
    # Give every member a digest preference (default weekly) on first visit.
    DigestPreference.objects.get_or_create(user=request.user)

    subs = {
        s.channel_id: s.level
        for s in Subscription.objects.filter(user=request.user)
    }
    # Unread is computed over every visible channel — including workgroup ones —
    # so the "Your groups" section can surface unread activity in a member's
    # cartels / committees / seminars without listing their channels here.
    unread = unread_channel_ids(request.user, visible)

    # The board lists only school-wide channels. A member's own spaces — each
    # workgroup's forum + chat (private to the group, reached via its Workspace)
    # and their private chats — are summarised under "Your groups & private
    # chats" instead of being mixed into the board's category listing.
    general = [
        c for c in visible
        if c.access not in (Channel.Access.WORKGROUP, Channel.Access.PRIVATE)
    ]
    wg_channels = [c for c in visible if c.access == Channel.Access.WORKGROUP]
    private_chats = [c for c in visible if c.access == Channel.Access.PRIVATE]

    # Group into categories, preserving order; uncategorised last.
    groups: list[tuple[str, list[Channel]]] = []
    seen: dict[object, list[Channel]] = {}
    for channel in general:
        channel.user_sub_level = subs.get(channel.id)
        channel.is_unread = channel.id in unread
        key = channel.category_id
        if key not in seen:
            label = channel.category.name if channel.category else "Other"
            bucket: list[Channel] = []
            seen[key] = bucket
            groups.append((label, bucket))
        seen[key].append(channel)

    my_spaces = _my_spaces(wg_channels, private_chats, unread)

    return render(
        request,
        "parletre/index.html",
        {
            "groups": groups,
            "my_spaces": my_spaces,
            "any_channels": bool(general) or bool(my_spaces),
        },
    )


#: Display order for "Your groups", mirroring the Groups overview (KIND_META).
_KIND_ORDER = {
    "seminar": 0,
    "cartel": 1,
    "committee": 2,
    "working_group": 3,
    "reading_group": 4,
}


def _my_spaces(wg_channels, private_chats, unread):
    """The member's own spaces for the "Your groups & private chats" section:
    one tile per workgroup (its forum + chat collapsed) plus one per private
    chat. Each tile is ``{url, name, label, is_unread}``; groups first (by
    kind, then name), then private chats (by name)."""
    by_group: dict[int, dict] = {}
    for channel in wg_channels:
        wg = channel.workgroup
        if wg is None:
            continue
        entry = by_group.get(wg.id)
        if entry is None:
            entry = {"wg": wg, "is_unread": False}
            by_group[wg.id] = entry
        if channel.id in unread:
            entry["is_unread"] = True

    group_tiles = [
        {
            "url": e["wg"].get_absolute_url(),
            "name": e["wg"].name,
            "label": e["wg"].get_kind_display(),
            "is_unread": e["is_unread"],
        }
        for e in sorted(
            by_group.values(),
            key=lambda e: (_KIND_ORDER.get(e["wg"].kind, 99), e["wg"].name),
        )
    ]
    chat_tiles = [
        {
            "url": c.get_absolute_url(),
            "name": c.name,
            "label": "Disappearing chat" if c.is_ephemeral else "Private chat",
            "is_unread": c.id in unread,
        }
        for c in sorted(private_chats, key=lambda c: c.name.lower())
    ]
    return group_tiles + chat_tiles


@login_required
def channel(request, slug):
    channel = _visible_channel_or_404(request.user, slug)
    can_post = channel.can_post(request.user)

    if request.method == "POST":
        # Chat-channel composer (forum channels post via new_thread / replies).
        if channel.is_forum:
            raise Http404()
        if not can_post:
            messages.error(request, "You can't post in this channel.")
            return redirect(channel)
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = Post.objects.create(
                channel=channel,
                author=request.user,
                body=form.cleaned_data["body"],
                reply_to=_reply_parent(form.cleaned_data.get("reply_to"), channel),
            )
            _save_attachments(post, form.cleaned_data.get("attachments"))
            notify_post(post)
            broadcast_chat_post(post)  # reach any live WebSocket clients
            # Return to the embedding page (e.g. a workgroup Workspace chat tab)
            # when a safe ?next was provided; otherwise the channel page.
            nxt = request.POST.get("next") or ""
            if nxt and url_has_allowed_host_and_scheme(
                nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(nxt)
            return redirect(channel)
    else:
        form = PostForm(initial={"reply_to": request.GET.get("reply_to") or None})

    sub = Subscription.objects.filter(user=request.user, channel=channel).first()
    context = {
        "channel": channel,
        "can_post": can_post,
        "can_moderate": channel.can_moderate(request.user),
        "form": form,
        "sub_level": sub.level if sub else None,
        "levels": SubscriptionLevel.choices,
        "reply_parent": _reply_parent(request.GET.get("reply_to"), channel),
    }

    if channel.is_forum:
        unread_ids = unread_thread_ids(request.user, channel)
        threads = list(
            channel.threads.select_related("author").annotate(
                reply_count=Count("posts"), last_post=Max("posts__created_at")
            )
        )
        for thread in threads:
            thread.is_unread = thread.id in unread_ids
        context["threads"] = threads
        return render(request, "parletre/channel_forum.html", context)

    # Chat: viewing the stream marks the channel read.
    mark_channel_read(request.user, channel)
    # Show all messages — expired ones are redacted (blacked out) on read,
    # not hidden, so the disappearing channel reads as a redacted transcript.
    chat_posts = channel.posts.filter(thread__isnull=True).select_related(
        "author", "reply_to", "reply_to__author"
    ).prefetch_related("reactions", "attachments").order_by("created_at")
    cutoff = (
        timezone.now() - timedelta(seconds=channel.message_ttl_seconds)
        if channel.is_ephemeral
        else None
    )
    context["posts"] = _attach_reactions(
        chat_posts, request.user, context["can_moderate"], cutoff
    )
    context["reaction_palette"] = REACTION_EMOJI
    # Member-created private chats: the creator manages / deletes; others leave.
    context["can_delete_chat"] = channel.can_delete(request.user)
    context["can_leave_chat"] = channel.can_leave(request.user)
    return render(request, "parletre/channel_chat.html", context)


def channel_inline_context(request, channel) -> dict:
    """Read-side context for rendering a channel's body inline (e.g. inside a
    workgroup's Workspace tab). Mirrors the GET path of :func:`channel`;
    posting still happens against the Parlêtre channel endpoints.
    """
    context = {
        "channel": channel,
        "can_post": channel.can_post(request.user),
        "can_moderate": channel.can_moderate(request.user),
        "inline": True,
    }
    if channel.is_forum:
        unread_ids = unread_thread_ids(request.user, channel)
        threads = list(
            channel.threads.select_related("author").annotate(
                reply_count=Count("posts"), last_post=Max("posts__created_at")
            )
        )
        for thread in threads:
            thread.is_unread = thread.id in unread_ids
        context["threads"] = threads
        return context

    mark_channel_read(request.user, channel)
    chat_posts = channel.posts.filter(thread__isnull=True).select_related(
        "author", "reply_to", "reply_to__author"
    ).prefetch_related("reactions", "attachments").order_by("created_at")
    cutoff = (
        timezone.now() - timedelta(seconds=channel.message_ttl_seconds)
        if channel.is_ephemeral
        else None
    )
    context["posts"] = _attach_reactions(
        chat_posts, request.user, context["can_moderate"], cutoff
    )
    context["reaction_palette"] = REACTION_EMOJI
    reply_to = request.GET.get("reply_to")
    context["reply_parent"] = _reply_parent(reply_to, channel)
    context["form"] = PostForm(initial={"reply_to": reply_to or None})
    return context


@login_required
def new_thread(request, slug):
    channel = _visible_channel_or_404(request.user, slug)
    if not channel.is_forum:
        raise Http404()
    if not channel.can_post(request.user):
        messages.error(request, "You can't start a thread in this channel.")
        return redirect(channel)

    if request.method == "POST":
        form = NewThreadForm(request.POST, request.FILES)
        if form.is_valid():
            thread = Thread.objects.create(
                channel=channel,
                title=form.cleaned_data["title"],
                author=request.user,
            )
            first_post = Post.objects.create(
                channel=channel,
                thread=thread,
                author=request.user,
                body=form.cleaned_data["body"],
            )
            _save_attachments(first_post, form.cleaned_data.get("attachments"))
            notify_new_thread(thread, first_post)
            return redirect(thread)
    else:
        form = NewThreadForm()

    return render(request, "parletre/new_thread.html", {"channel": channel, "form": form})


@login_required
def thread(request, slug, thread_slug):
    channel = _visible_channel_or_404(request.user, slug)
    thread = get_object_or_404(
        Thread.objects.select_related("author"), channel=channel, slug=thread_slug
    )
    can_post = channel.can_post(request.user) and not thread.locked

    if request.method == "POST":
        if not can_post:
            messages.error(
                request,
                "This thread is locked." if thread.locked else "You can't reply here.",
            )
            return redirect(thread)
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            now = timezone.now()
            post = Post.objects.create(
                channel=channel,
                thread=thread,
                author=request.user,
                body=form.cleaned_data["body"],
                reply_to=_reply_parent(form.cleaned_data.get("reply_to"), channel),
            )
            _save_attachments(post, form.cleaned_data.get("attachments"))
            thread.touch(now)
            notify_post(post)
            return redirect(_post_url(post))
    else:
        form = PostForm(initial={"reply_to": request.GET.get("reply_to") or None})

    # Capture the read watermark *before* marking this view read, so we can
    # point the member at the first post they haven't seen.
    marker_before = thread_marker_at(request.user, thread)
    thread_can_moderate = channel.can_moderate(request.user)
    thread_cutoff = (
        timezone.now() - timedelta(seconds=channel.message_ttl_seconds)
        if channel.is_ephemeral
        else None
    )
    posts = _attach_reactions(
        thread.posts.select_related("author", "reply_to", "reply_to__author")
        .prefetch_related("reactions", "attachments")
        .order_by("created_at"),
        request.user,
        thread_can_moderate,
        thread_cutoff,
    )
    first_unread_id = None
    if marker_before is not None:
        for post in posts:
            if post.created_at > marker_before:
                first_unread_id = post.id
                break
    mark_thread_read(request.user, thread)

    moderation_actions = [
        ("pin", "Unpin" if thread.pinned else "Pin"),
        ("lock", "Unlock" if thread.locked else "Lock"),
        ("resolve", "Mark unresolved" if thread.resolved else "Mark resolved"),
    ]
    return render(
        request,
        "parletre/thread.html",
        {
            "channel": channel,
            "thread": thread,
            "posts": posts,
            "form": form,
            "can_post": can_post,
            "can_moderate": thread_can_moderate,
            "moderation_actions": moderation_actions,
            "reaction_palette": REACTION_EMOJI,
            "first_unread_id": first_unread_id,
            "reply_parent": _reply_parent(request.GET.get("reply_to"), channel),
        },
    )


@login_required
def edit_post(request, post_id):
    """Edit a post's body (author only)."""
    post = get_object_or_404(
        Post.objects.select_related("channel", "thread"), pk=post_id
    )
    if not post.channel.visible_to(request.user) or not post.is_editable_by(request.user):
        raise Http404()
    if request.method == "POST":
        form = EditPostForm(request.POST)
        if form.is_valid():
            post.body = form.cleaned_data["body"]
            post.edited_at = timezone.now()
            post.save(update_fields=["body", "edited_at"])
            return redirect(_post_url(post))
    else:
        form = EditPostForm(initial={"body": post.body})
    return render(
        request,
        "parletre/edit_post.html",
        {"post": post, "channel": post.channel, "form": form},
    )


@login_required
@require_POST
def delete_post(request, post_id):
    """Soft-delete a post (author or channel moderator)."""
    post = get_object_or_404(
        Post.objects.select_related("channel", "thread"), pk=post_id
    )
    if not post.channel.visible_to(request.user) or not post.is_deletable_by(request.user):
        raise Http404()
    post.deleted = True
    post.save(update_fields=["deleted"])
    return redirect(_post_url(post))


@login_required
def search(request):
    """Search posts the member can see (DISC-4)."""
    if not can_enter_parletre(request.user):
        return render(request, "parletre/not_a_member.html", status=403)
    query = request.GET.get("q", "").strip()
    hits = search_posts(request.user, query)
    results = []
    for post in hits:
        target = post.thread or post.channel
        anchor = f"#post-{post.id}" if post.thread_id else ""
        results.append(
            {
                "post": post,
                "channel": post.channel,
                "thread": post.thread,
                "title": post.thread.title if post.thread_id else f"#{post.channel.slug}",
                "url": f"{target.get_absolute_url()}{anchor}",
                "snippet": make_snippet(post.body, query),
            }
        )
    return render(request, "parletre/search.html", {"q": query, "results": results})


@login_required
def preferences(request):
    """Member's Parlêtre email settings — the digest cadence."""
    if not can_enter_parletre(request.user):
        return render(request, "parletre/not_a_member.html", status=403)
    pref, _ = DigestPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        freq = request.POST.get("frequency", "")
        valid = {value for value, _label in DigestPreference.Frequency.choices}
        if freq in valid:
            pref.frequency = freq
            pref.save(update_fields=["frequency"])
            messages.success(request, "Digest preference saved.")
        return redirect("parletre:settings")
    return render(
        request,
        "parletre/settings.html",
        {"pref": pref, "choices": DigestPreference.Frequency.choices},
    )


@login_required
def mention_search(request):
    """Autocomplete for @mentions: members matching ``q`` who can see the
    given channel. Returns the directory slug to insert (``@first-last``)."""
    if not can_enter_parletre(request.user):
        raise Http404()
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})

    User = get_user_model()
    qs = User.objects.filter(profile__role__in=Profile.DIRECTORY_ROLES)
    for term in q.split()[:3]:
        qs = qs.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
    candidates = qs.select_related("profile").order_by("first_name", "last_name")[:30]

    channel = Channel.objects.filter(slug=request.GET.get("channel", "")).first()
    results = []
    for user in candidates:
        if channel is not None and not channel.visible_to(user):
            continue
        results.append(
            {"slug": user.profile.directory_slug, "name": user.get_full_name() or user.email}
        )
        if len(results) >= 8:
            break
    return JsonResponse({"results": results})


# ---- member-created private chats --------------------------------------


@login_required
def member_search(request):
    """Autocomplete for the private-chat participant picker: members matching
    ``q`` (excluding the searcher). Returns user ids + names."""
    if not is_member(request.user):
        raise Http404()
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})

    qs = (
        get_user_model()
        .objects.filter(profile__role__in=Profile.DIRECTORY_ROLES)
        .exclude(pk=request.user.pk)
    )
    for term in q.split()[:3]:
        qs = qs.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
    candidates = qs.order_by("first_name", "last_name")[:8]
    results = [
        {"id": u.pk, "name": u.get_full_name() or u.email} for u in candidates
    ]
    return JsonResponse({"results": results})


def _private_chats_category():
    """The board category member-created private chats live under (created on
    demand, sitting above the workgroup categories)."""
    cat, _ = ChannelCategory.objects.get_or_create(
        name="Private chats", defaults={"slug": "private-chats", "position": 15}
    )
    return cat


def _subscribe_all(users, channel) -> None:
    """Give each user an ALL-level subscription to a private chat so they're
    notified of new messages (the DM expectation). Idempotent."""
    for user in users:
        Subscription.objects.get_or_create(
            user=user, channel=channel, defaults={"level": SubscriptionLevel.ALL}
        )


def _selected_participants(form):
    """The participant User objects currently chosen on a participants form —
    submitted values on a bound form, ``initial`` otherwise — so the picker can
    re-render its chips (e.g. after a validation error)."""
    field = form.fields["participants"]
    if form.is_bound:
        data = form.data
        ids = data.getlist("participants") if hasattr(data, "getlist") else []
    else:
        ids = [getattr(u, "pk", u) for u in (form.initial.get("participants") or [])]
    return list(field.queryset.filter(pk__in=ids))


@login_required
def create_private_chat(request):
    """A member starts a private chat — regular or disappearing — with the
    members they pick. They become its moderator (so they can manage it)."""
    if not is_member(request.user):
        return render(request, "parletre/not_a_member.html", status=403)

    if request.method == "POST":
        form = NewPrivateChatForm(request.POST, creator=request.user)
        if form.is_valid():
            participants = list(form.cleaned_data["participants"])
            with transaction.atomic():
                chan = Channel.objects.create(
                    name=form.cleaned_data["name"],
                    slug=_unique_slug(Channel, form.cleaned_data["name"], fallback="chat"),
                    kind=Channel.Kind.CHAT,
                    access=Channel.Access.PRIVATE,
                    category=_private_chats_category(),
                    message_ttl_seconds=form.cleaned_data["lifetime"],
                    created_by=request.user,
                )
                members = [request.user, *participants]
                chan.members.set(members)
                chan.moderators.add(request.user)
                _subscribe_all(members, chan)
            return redirect(chan)
    else:
        form = NewPrivateChatForm(creator=request.user)
    return render(
        request,
        "parletre/create_private_chat.html",
        {"form": form, "selected": _selected_participants(form)},
    )


def _private_chat_or_404(user, slug):
    """A private channel ``user`` may moderate (its creator / a moderator);
    404 otherwise — the manage surface for member-created chats."""
    channel = _visible_channel_or_404(user, slug)
    if channel.access != Channel.Access.PRIVATE or not channel.can_moderate(user):
        raise Http404("No such channel.")
    return channel


@login_required
def manage_participants(request, slug):
    """Add or remove a private chat's participants (creator/moderator only).
    The creator stays a member; people dropped lose access and notifications."""
    channel = _private_chat_or_404(request.user, slug)

    if request.method == "POST":
        form = ParticipantsForm(request.POST, creator=request.user)
        if form.is_valid():
            members = [request.user, *form.cleaned_data["participants"]]
            with transaction.atomic():
                channel.members.set(members)
                _subscribe_all(members, channel)
                # Drop subscriptions for anyone no longer in the chat, so they
                # stop being notified / digested about a channel they can't see.
                member_ids = [u.pk for u in members]
                Subscription.objects.filter(channel=channel).exclude(
                    user_id__in=member_ids
                ).delete()
            return redirect(channel)
    else:
        current = list(channel.members.exclude(pk=request.user.pk))
        form = ParticipantsForm(
            creator=request.user, initial={"participants": current}
        )
    return render(
        request,
        "parletre/manage_participants.html",
        {"form": form, "channel": channel, "selected": _selected_participants(form)},
    )


@login_required
@require_POST
def leave_chat(request, slug):
    """A participant (not the creator) leaves a private chat: dropped from the
    member list, their subscription cleared, and they lose access."""
    channel = _visible_channel_or_404(request.user, slug)
    if not channel.can_leave(request.user):
        raise Http404("No such channel.")
    with transaction.atomic():
        channel.members.remove(request.user)
        channel.moderators.remove(request.user)
        Subscription.objects.filter(channel=channel, user=request.user).delete()
    messages.success(request, f"You’ve left “{channel.name}.”")
    return redirect("parletre:index")


@login_required
def delete_chat(request, slug):
    """The creator deletes a private chat (GET confirms, POST deletes). Removes
    the channel and everything in it."""
    channel = _visible_channel_or_404(request.user, slug)
    if not channel.can_delete(request.user):
        raise Http404("No such channel.")
    if request.method == "POST":
        name = channel.name
        channel.delete()
        messages.success(request, f"Deleted “{name}.”")
        return redirect("parletre:index")
    return render(request, "parletre/delete_chat.html", {"channel": channel})


@login_required
def notifications(request):
    """The member's notification feed (the nav bell). Viewing it marks all
    unread notifications read."""
    if not can_enter_parletre(request.user):
        return render(request, "parletre/not_a_member.html", status=403)
    items = list(
        Notification.objects.filter(recipient=request.user)
        .select_related(
            "actor", "thread", "thread__channel", "post", "post__channel", "post__thread"
        )
        .order_by("-created_at")[:100]
    )
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return render(request, "parletre/notifications.html", {"items": items})


@login_required
@require_POST
def react(request, post_id):
    """Toggle the current user's emoji reaction on a post (DISC-3)."""
    post = get_object_or_404(
        Post.objects.select_related("channel", "thread"), pk=post_id
    )
    if not post.channel.visible_to(request.user):
        raise Http404()
    emoji = request.POST.get("emoji", "")
    if emoji not in REACTION_EMOJI:
        raise Http404()
    existing = Reaction.objects.filter(
        post=post, user=request.user, emoji=emoji
    ).first()
    if existing:
        existing.delete()
    else:
        Reaction.objects.create(post=post, user=request.user, emoji=emoji)
    if post.thread_id:
        return redirect(f"{post.thread.get_absolute_url()}#post-{post.id}")
    return redirect(post.channel)


@login_required
def attachment(request, attachment_id):
    """Serve an attachment, gated by the channel's access — so a private
    channel's files stay private. Never link the bare media URL."""
    att = get_object_or_404(
        Attachment.objects.select_related("post", "post__channel"), pk=attachment_id
    )
    if not att.post.channel.visible_to(request.user):
        raise Http404()
    # Redacted (or past-TTL) attachments are gone — never serve their bytes.
    ch = att.post.channel
    if att.post.redacted or (
        ch.is_ephemeral
        and att.post.created_at < timezone.now() - timedelta(seconds=ch.message_ttl_seconds)
    ):
        raise Http404()
    response = FileResponse(
        att.file.open("rb"),
        content_type=att.content_type or "application/octet-stream",
    )
    disposition = "inline" if att.is_image else "attachment"
    name = (att.original_name or att.file.name).replace('"', "")
    response["Content-Disposition"] = f'{disposition}; filename="{name}"'
    return response


@login_required
@require_POST
def subscribe(request, slug):
    channel = _visible_channel_or_404(request.user, slug)
    level = request.POST.get("level", "")
    valid = {value for value, _label in SubscriptionLevel.choices}
    if level not in valid:
        messages.error(request, "Unknown subscription level.")
        return redirect(channel)
    # Auto-subscribe channels (Announcements) may be downgraded to digest but
    # not muted entirely.
    if channel.auto_subscribe and level == SubscriptionLevel.MUTED:
        messages.error(request, "You can't fully mute the announcements channel.")
        return redirect(channel)
    Subscription.objects.update_or_create(
        user=request.user, channel=channel, defaults={"level": level}
    )
    messages.success(request, "Notification preference updated.")
    return redirect(channel)


@login_required
@require_POST
def moderate_thread(request, slug, thread_slug):
    """Toggle pin / lock / resolved on a thread (moderators only)."""
    channel = _visible_channel_or_404(request.user, slug)
    if not channel.can_moderate(request.user):
        raise Http404()
    thread = get_object_or_404(Thread, channel=channel, slug=thread_slug)
    action = request.POST.get("action")
    if action == "pin":
        thread.pinned = not thread.pinned
    elif action == "lock":
        thread.locked = not thread.locked
    elif action == "resolve":
        thread.resolved = not thread.resolved
    else:
        raise Http404()
    thread.save(update_fields=[{"pin": "pinned", "lock": "locked", "resolve": "resolved"}[action]])
    return redirect(thread)


# ---- reply-by-email inbound webhook (DISC-7) ----------------------------


def _raw_email_from_ses(ses_message: dict) -> bytes | None:
    """Pull the raw MIME from an SES notification — inline ``content`` if SNS
    carried it, else fetched from the S3 receipt bucket (boto3, if available)."""
    content = ses_message.get("content")
    if content:
        try:
            return base64.b64decode(content)
        except Exception:
            return None
    action = (ses_message.get("receipt") or {}).get("action") or {}
    bucket, key = action.get("bucketName"), action.get("objectKey")
    if bucket and key:
        try:
            import boto3  # optional; only used when SES stores to S3
            obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
            return obj["Body"].read()
        except Exception:
            log.exception("parletre: could not fetch inbound email from s3://%s/%s", bucket, key)
    return None


@csrf_exempt
@require_POST
def inbound(request):
    """SNS endpoint for reply-by-email. Handles subscription confirmation and
    SES 'email received' notifications. The real security is the signed reply
    token + sender match inside process_inbound_email."""
    try:
        envelope = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("invalid JSON")

    topic = getattr(settings, "PARLETRE_SNS_TOPIC_ARN", "")
    if topic and envelope.get("TopicArn") != topic:
        return HttpResponseForbidden("unexpected topic")

    msg_type = envelope.get("Type")
    if msg_type == "SubscriptionConfirmation":
        url = envelope.get("SubscribeURL")
        if url:
            try:
                import urllib.request
                urllib.request.urlopen(url, timeout=5)  # noqa: S310 (AWS https URL)
            except Exception:
                log.exception("parletre: SNS subscription confirmation failed")
        return HttpResponse("subscription confirmation received")

    if msg_type == "Notification":
        try:
            ses_message = json.loads(envelope.get("Message", "{}"))
        except ValueError:
            return HttpResponseBadRequest("invalid SES message")
        raw = _raw_email_from_ses(ses_message)
        if raw is None:
            return HttpResponse("no email content")
        result = process_inbound_email(raw)
        return JsonResponse(result)

    return HttpResponse("ignored")
