"""Parlêtre views — the member-facing discussion board (M13.5a).

All views require login *and* membership (:func:`permissions.is_member`).
Channels a member can't access 404 rather than reveal their existence.

This increment covers the read/write forum loop: browse channels, read and
start threads, reply, post in chat channels, and set a per-channel
subscription level. Reactions, in-app notifications, digests, reply-by-email,
and realtime chat transport are later increments.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import NewThreadForm, PostForm
from .models import (
    REACTION_EMOJI,
    Channel,
    Notification,
    Post,
    Reaction,
    Subscription,
    SubscriptionLevel,
    Thread,
)
from .permissions import is_member
from .services import notify_new_thread, notify_post


def _attach_reactions(posts, user):
    """Attach a ``reaction_summary`` list to each post: one entry per distinct
    emoji with its count and whether ``user`` is among the reactors. Expects
    ``reactions`` (and their users) prefetched."""
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
    return posts


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
    if not is_member(request.user):
        return render(request, "parletre/not_a_member.html", status=403)

    channels = list(
        Channel.objects.select_related("category", "committee")
        .prefetch_related("members", "moderators")
        .order_by("category__position", "position", "name")
    )
    visible = [c for c in channels if c.visible_to(request.user)]
    _ensure_auto_subscriptions(request.user, visible)

    subs = {
        s.channel_id: s.level
        for s in Subscription.objects.filter(user=request.user)
    }

    # Group into categories, preserving order; uncategorised last.
    groups: list[tuple[str, list[Channel]]] = []
    seen: dict[object, list[Channel]] = {}
    for channel in visible:
        channel.user_sub_level = subs.get(channel.id)
        key = channel.category_id
        if key not in seen:
            label = channel.category.name if channel.category else "Other"
            bucket: list[Channel] = []
            seen[key] = bucket
            groups.append((label, bucket))
        seen[key].append(channel)

    return render(
        request,
        "parletre/index.html",
        {"groups": groups, "any_channels": bool(visible)},
    )


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
        form = PostForm(request.POST)
        if form.is_valid():
            post = Post.objects.create(
                channel=channel, author=request.user, body=form.cleaned_data["body"]
            )
            notify_post(post)
            return redirect(channel)
    else:
        form = PostForm()

    sub = Subscription.objects.filter(user=request.user, channel=channel).first()
    context = {
        "channel": channel,
        "can_post": can_post,
        "can_moderate": channel.can_moderate(request.user),
        "form": form,
        "sub_level": sub.level if sub else None,
        "levels": SubscriptionLevel.choices,
    }

    if channel.is_forum:
        context["threads"] = (
            channel.threads.select_related("author")
            .annotate(reply_count=Count("posts"), last_post=Max("posts__created_at"))
        )
        return render(request, "parletre/channel_forum.html", context)

    context["posts"] = _attach_reactions(
        channel.posts.filter(thread__isnull=True)
        .select_related("author")
        .prefetch_related("reactions")
        .order_by("created_at"),
        request.user,
    )
    context["reaction_palette"] = REACTION_EMOJI
    return render(request, "parletre/channel_chat.html", context)


@login_required
def new_thread(request, slug):
    channel = _visible_channel_or_404(request.user, slug)
    if not channel.is_forum:
        raise Http404()
    if not channel.can_post(request.user):
        messages.error(request, "You can't start a thread in this channel.")
        return redirect(channel)

    if request.method == "POST":
        form = NewThreadForm(request.POST)
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
        form = PostForm(request.POST)
        if form.is_valid():
            now = timezone.now()
            post = Post.objects.create(
                channel=channel,
                thread=thread,
                author=request.user,
                body=form.cleaned_data["body"],
            )
            thread.touch(now)
            notify_post(post)
            return redirect(thread)
    else:
        form = PostForm()

    posts = _attach_reactions(
        thread.posts.select_related("author")
        .prefetch_related("reactions")
        .order_by("created_at"),
        request.user,
    )
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
            "can_moderate": channel.can_moderate(request.user),
            "moderation_actions": moderation_actions,
            "reaction_palette": REACTION_EMOJI,
        },
    )


@login_required
def notifications(request):
    """The member's notification feed (the nav bell). Viewing it marks all
    unread notifications read."""
    if not is_member(request.user):
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
