"""Parlêtre views — the member-facing discussion board (M13.5a).

All views require login *and* membership (:func:`permissions.is_member`).
Channels a member can't access 404 rather than reveal their existence.

Covers the forum loop (browse / start / reply / chat / subscribe), reactions,
@mentions + notifications, unread tracking, attachments, the digest-settings
page, and the reply-by-email inbound webhook. Realtime chat transport
(WebSockets) is the remaining M13.5b increment.
"""

from __future__ import annotations

import base64
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
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
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import Profile

from .forms import NewThreadForm, PostForm
from .inbound import process_inbound_email
from .models import (
    REACTION_EMOJI,
    Attachment,
    Channel,
    DigestPreference,
    Notification,
    Post,
    Reaction,
    Subscription,
    SubscriptionLevel,
    Thread,
)
from .permissions import is_member
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


def _save_attachments(post, files) -> None:
    for f in files or []:
        Attachment.objects.create(
            post=post,
            file=f,
            original_name=f.name[:255],
            content_type=getattr(f, "content_type", "") or "",
            size=getattr(f, "size", 0) or 0,
        )


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
    # Give every member a digest preference (default weekly) on first visit.
    DigestPreference.objects.get_or_create(user=request.user)

    subs = {
        s.channel_id: s.level
        for s in Subscription.objects.filter(user=request.user)
    }
    unread = unread_channel_ids(request.user, visible)

    # Group into categories, preserving order; uncategorised last.
    groups: list[tuple[str, list[Channel]]] = []
    seen: dict[object, list[Channel]] = {}
    for channel in visible:
        channel.user_sub_level = subs.get(channel.id)
        channel.is_unread = channel.id in unread
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
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = Post.objects.create(
                channel=channel, author=request.user, body=form.cleaned_data["body"]
            )
            _save_attachments(post, form.cleaned_data.get("attachments"))
            notify_post(post)
            broadcast_chat_post(post)  # reach any live WebSocket clients
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
    context["posts"] = _attach_reactions(
        channel.posts.filter(thread__isnull=True)
        .select_related("author")
        .prefetch_related("reactions", "attachments")
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
            )
            _save_attachments(post, form.cleaned_data.get("attachments"))
            thread.touch(now)
            notify_post(post)
            return redirect(thread)
    else:
        form = PostForm()

    # Capture the read watermark *before* marking this view read, so we can
    # point the member at the first post they haven't seen.
    marker_before = thread_marker_at(request.user, thread)
    posts = _attach_reactions(
        thread.posts.select_related("author")
        .prefetch_related("reactions", "attachments")
        .order_by("created_at"),
        request.user,
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
            "can_moderate": channel.can_moderate(request.user),
            "moderation_actions": moderation_actions,
            "reaction_palette": REACTION_EMOJI,
            "first_unread_id": first_unread_id,
        },
    )


@login_required
def search(request):
    """Search posts the member can see (DISC-4)."""
    if not is_member(request.user):
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
    if not is_member(request.user):
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
    if not is_member(request.user):
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
def attachment(request, attachment_id):
    """Serve an attachment, gated by the channel's access — so a private
    channel's files stay private. Never link the bare media URL."""
    att = get_object_or_404(
        Attachment.objects.select_related("post", "post__channel"), pk=attachment_id
    )
    if not att.post.channel.visible_to(request.user):
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
