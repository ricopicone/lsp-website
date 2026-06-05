"""Parlêtre — the members-only discussion board (MEM-3 / DISC-1 … DISC-9).

The name is Lacan's *parlêtre* ("speaking-being"): the members of the school
are parlêtres, and this is where they speak. See the M13.5 milestone in
``LSP-Website-Phase2-Plan.md`` for the full design.

This module is the forum-core foundation (M13.5a): the data model and its
access logic. Channels group into categories; a forum channel holds threads,
each holding a chain of posts; a chat channel holds posts directly (``thread``
null). Reactions and per-channel subscriptions hang off the same objects.

Access control lives in :mod:`parletre.permissions`; the model methods here
(:meth:`Channel.visible_to` etc.) are thin delegators so callers can write
``channel.visible_to(request.user)`` naturally.

Not yet built here (later M13.5 increments): per-post attachments, read
markers / unread tracking, digest preferences, in-app notifications, and the
realtime chat transport (M13.5b).
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from . import permissions
from .rendering import render_markdown
from .storage import attachment_storage

#: The fixed palette of reaction emoji members may add to a post (DISC-3).
#: A closed set keeps input validated and the UI tidy.
REACTION_EMOJI = ("👍", "❤️", "🎉", "🤔", "👀", "✅")


def blackout(text: str) -> str:
    """Redact text: every non-whitespace character becomes a █ block,
    preserving word/line shape but not content."""
    return re.sub(r"\S", "█", text or "")


class SubscriptionLevel(models.TextChoices):
    """How much email a member wants from a channel. Shared by Channel
    (its default) and Subscription (a member's choice)."""

    ALL = "all", _("Every post")
    THREADS_ONLY = "threads_only", _("New threads only")
    MENTIONS_ONLY = "mentions_only", _("Mentions only")
    DIGEST = "digest", _("Digest only")
    MUTED = "muted", _("Muted")


def _unique_slug(model, base: str, *, scope: dict | None = None, fallback: str = "item") -> str:
    """A slug derived from ``base``, unique within ``scope`` (e.g. a channel).

    Appends ``-2``, ``-3``, … on collision. ``scope`` is an extra filter
    (such as ``{"channel": channel}``) so thread slugs need only be unique
    *within* their channel, not site-wide.
    """
    scope = scope or {}
    root = slugify(base) or fallback
    slug = root
    n = 2
    while model.objects.filter(slug=slug, **scope).exists():
        slug = f"{root}-{n}"
        n += 1
    return slug


class ChannelCategory(models.Model):
    """A sidebar grouping of channels (General, Committees, Cartels, …)."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    position = models.IntegerField(
        default=0, help_text="Sort order in the sidebar. Lower = earlier."
    )

    class Meta:
        verbose_name_plural = "channel categories"
        ordering = ("position", "name")

    def __str__(self) -> str:
        return self.name


class Channel(models.Model):
    """A space for discussion — either a threaded forum or a live chat."""

    class Kind(models.TextChoices):
        FORUM = "forum", _("Forum (threaded)")
        CHAT = "chat", _("Chat (live stream)")
        VIDEO = "video", _("Video (meeting room)")

    class Access(models.TextChoices):
        OPEN = "open", _("All LSP — every member")
        ROLE = "role", _("Specific roles")
        COMMITTEE = "committee", _("Committee")
        WORKGROUP = "workgroup", _("Workgroup")
        LSP_STAFF = "lsp_staff", _("LSP Staff")
        PRIVATE = "private", _("Private — named members")
        # "Open" means open to every *member* — never to the public. All of
        # Parlêtre sits behind the members-only gate (see permissions.is_member).
        # WORKGROUP gates by membership in the linked ``workgroup`` (cartels,
        # working groups, and — after the Stage-4 fold-in — committees), and is
        # auto-provisioned one channel per workgroup. The legacy COMMITTEE mode
        # + ``committee`` FK persist until that fold-in.

    class PostPolicy(models.TextChoices):
        OPEN = "open", _("Any member may post")
        STAFF_ONLY = "staff_only", _("Moderators / staff only")

    category = models.ForeignKey(
        ChannelCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="channels",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.FORUM)
    description = models.TextField(
        blank=True, help_text="One- or two-line topic shown under the channel name."
    )

    access = models.CharField(
        max_length=16,
        choices=Access.choices,
        default=Access.OPEN,
        help_text=(
            "Who may see and read this channel. Every channel — even Open — "
            "is members-only; Parlêtre is never visible to the public."
        ),
    )
    allowed_roles = models.JSONField(
        default=list,
        blank=True,
        help_text="When access=role: a list of Profile.role values (e.g. "
        "['analyst', 'candidate']).",
    )
    committee = models.ForeignKey(
        "committees.Committee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parletre_channels",
        help_text="When access=committee: members of this committee may enter; "
        "its chairs moderate.",
    )
    workgroup = models.ForeignKey(
        "workgroups.Workgroup",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="channels",
        help_text="When access=workgroup: members of this workgroup may enter; "
        "its chairs / plus-one moderate.",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="parletre_private_channels",
        help_text="When access=private: the explicit member list.",
    )
    moderators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="parletre_moderated_channels",
        help_text="May pin / lock / move / delete in this channel.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parletre_created_channels",
        help_text="The member who created this chat (member-made private chats "
        "only); they may manage participants and delete it.",
    )

    post_policy = models.CharField(
        max_length=16,
        choices=PostPolicy.choices,
        default=PostPolicy.OPEN,
        help_text="Use 'Moderators / staff only' for an announcements channel.",
    )
    auto_subscribe = models.BooleanField(
        default=False,
        help_text="Force every member subscribed (downgradable to digest, not "
        "off). Use for the list-wide Announcements channel.",
    )
    default_subscription_level = models.CharField(
        max_length=16,
        choices=SubscriptionLevel.choices,
        default=SubscriptionLevel.DIGEST,
        help_text="Subscription level applied when a member first joins, unless "
        "auto_subscribe overrides it.",
    )

    message_ttl_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="If set, messages here disappear this many seconds after posting "
        "(a 'disappearing' chat, e.g. Purloined Letters). Null = permanent.",
    )

    position = models.IntegerField(
        default=0, help_text="Sort order within the category. Lower = earlier."
    )
    archived = models.BooleanField(
        default=False, help_text="Hidden from members; lingers for moderators."
    )

    class RecordingMode(models.TextChoices):
        ON_DEMAND = "on_demand", "On demand — hosts can record"
        OFF = "off", "Off — no Record button"

    recording_mode = models.CharField(
        max_length=12, choices=RecordingMode.choices, default=RecordingMode.ON_DEMAND,
        help_text="For video channels: whether hosts see a Record button. Set to "
        "Off for open rooms like The Gaze.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("category__position", "position", "name")

    def __str__(self) -> str:
        return f"#{self.slug}"

    def get_absolute_url(self) -> str:
        return reverse("parletre:channel", args=[self.slug])

    @property
    def is_forum(self) -> bool:
        return self.kind == self.Kind.FORUM

    @property
    def is_video(self) -> bool:
        return self.kind == self.Kind.VIDEO

    @property
    def is_ephemeral(self) -> bool:
        """True for disappearing-message channels (a TTL is set)."""
        return bool(self.message_ttl_seconds)

    @property
    def ttl_display(self) -> str:
        """Human-friendly TTL, e.g. '24 hours' (empty for permanent channels)."""
        s = self.message_ttl_seconds
        if not s:
            return ""
        for unit, secs in (("day", 86400), ("hour", 3600), ("minute", 60)):
            if s % secs == 0:
                n = s // secs
                return f"{n} {unit}{'s' if n != 1 else ''}"
        return f"{s} seconds"

    @property
    def description_html(self) -> str:
        return render_markdown(self.description)

    # ---- Access (delegates to parletre.permissions) ----

    def visible_to(self, user) -> bool:
        return permissions.channel_visible(self, user)

    def can_post(self, user) -> bool:
        return permissions.channel_can_post(self, user)

    def can_moderate(self, user) -> bool:
        return permissions.channel_can_moderate(self, user)

    # ---- Member-created private chats (creator manage / delete; leave) ----

    def is_creator(self, user) -> bool:
        return (
            self.created_by_id is not None
            and getattr(user, "is_authenticated", False)
            and self.created_by_id == user.pk
        )

    def can_delete(self, user) -> bool:
        """A member-created private chat may be deleted by its creator."""
        return self.access == self.Access.PRIVATE and self.is_creator(user)

    def can_leave(self, user) -> bool:
        """A participant other than the creator may leave a member-created
        private chat (the creator deletes it instead)."""
        return (
            self.access == self.Access.PRIVATE
            and self.created_by_id is not None
            and getattr(user, "is_authenticated", False)
            and self.created_by_id != user.pk
            and self.members.filter(pk=user.pk).exists()
        )


class Thread(models.Model):
    """A titled conversation within a forum channel."""

    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="threads"
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="parletre_threads",
    )
    pinned = models.BooleanField(default=False)
    locked = models.BooleanField(
        default=False, help_text="No further replies; existing posts stay."
    )
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(
        default=timezone.now,
        help_text="Bumped on each new post; drives thread ordering.",
    )

    class Meta:
        ordering = ("-pinned", "-last_activity_at")
        constraints = [
            models.UniqueConstraint(
                fields=("channel", "slug"),
                name="parletre_unique_thread_slug_per_channel",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("parletre:thread", args=[self.channel.slug, self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(
                Thread, self.title, scope={"channel": self.channel}, fallback="thread"
            )
        super().save(*args, **kwargs)

    def touch(self, when=None) -> None:
        """Mark recent activity (call when a post is added)."""
        self.last_activity_at = when or timezone.now()
        self.save(update_fields=["last_activity_at"])


class Post(models.Model):
    """A single message — a forum reply (``thread`` set) or a chat message
    (``thread`` null). ``channel`` is always set, denormalised so chat
    messages and per-channel queries don't need to hop through a thread."""

    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="posts"
    )
    thread = models.ForeignKey(
        Thread,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="parletre_posts",
    )
    body = models.TextField(help_text="Markdown.")
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
        help_text="Set to quote / inline-reply to another post.",
    )
    via_email = models.BooleanField(
        default=False, help_text="Posted via reply-by-email (DISC-7)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted = models.BooleanField(
        default=False, help_text="Soft tombstone; body hidden but slot kept."
    )
    redacted = models.BooleanField(
        default=False,
        help_text="A disappearing-channel message whose content has been redacted "
        "(real text/files deleted; a blacked-out bar remains).",
    )

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        where = self.thread.title if self.thread_id else f"#{self.channel.slug}"
        who = self.author or "(removed)"
        return f"{who} in {where}"

    @property
    def body_html(self) -> str:
        """Sanitised, rendered Markdown — empty for a soft-deleted post."""
        if self.deleted:
            return ""
        return render_markdown(self.body)

    @property
    def redacted_display(self) -> str:
        """The current body rendered as redaction blocks (no content leaks —
        computed even before the cron persists the redaction)."""
        return blackout(self.body)

    @property
    def excerpt(self) -> str:
        """A short plain-text preview (for reply quoting / search)."""
        if self.deleted:
            return "(deleted)"
        text = " ".join(self.body.split())
        return text[:120] + ("…" if len(text) > 120 else "")

    def is_editable_by(self, user) -> bool:
        """Only the author may edit their own (non-deleted) post."""
        return (
            not self.deleted
            and self.author_id is not None
            and getattr(user, "is_authenticated", False)
            and self.author_id == user.id
        )

    def is_deletable_by(self, user) -> bool:
        """The author, or a moderator of the channel, may delete a post."""
        if self.deleted or not getattr(user, "is_authenticated", False):
            return False
        if self.author_id == user.id:
            return True
        return self.channel.can_moderate(user)


class Reaction(models.Model):
    """An emoji reaction by one member on one post."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parletre_reactions",
    )
    emoji = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("post", "user", "emoji"),
                name="parletre_one_reaction_per_user_emoji",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} {self.emoji}"


class Subscription(models.Model):
    """A member's chosen notification level for a channel (DISC-5)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parletre_subscriptions",
    )
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="subscriptions"
    )
    level = models.CharField(
        max_length=16,
        choices=SubscriptionLevel.choices,
        default=SubscriptionLevel.DIGEST,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "channel"),
                name="parletre_one_subscription_per_user_channel",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} → #{self.channel.slug} ({self.level})"


class Notification(models.Model):
    """An in-app notification for the nav bell (DISC-3/DISC-5).

    Triggered by: being @mentioned, a reply in a thread you started, or a
    new thread in a channel you follow closely.
    """

    class Verb(models.TextChoices):
        MENTION = "mention", _("mentioned you")
        REPLY = "reply", _("replied in your thread")
        NEW_THREAD = "new_thread", _("started a thread")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parletre_notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    verb = models.CharField(max_length=16, choices=Verb.choices)
    post = models.ForeignKey(
        Post, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    thread = models.ForeignKey(
        Thread, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self) -> str:
        return f"{self.actor} {self.get_verb_display()} → {self.recipient}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    def url(self) -> str:
        """Where clicking the notification takes you."""
        if self.post_id and self.post.thread_id:
            return f"{self.post.thread.get_absolute_url()}#post-{self.post_id}"
        if self.thread_id:
            return self.thread.get_absolute_url()
        if self.post_id:
            return self.post.channel.get_absolute_url()
        return reverse("parletre:index")

    @property
    def context_label(self) -> str:
        """The thread/channel this notification points at, for display."""
        if self.thread_id:
            return self.thread.title
        if self.post_id:
            return f"#{self.post.channel.slug}"
        return ""


class ReadMarker(models.Model):
    """How far a member has read — keyed to a thread (forum) or a channel
    (chat). Drives unread badges and "jump to unread" (DISC-4)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parletre_read_markers",
    )
    thread = models.ForeignKey(
        Thread, null=True, blank=True, on_delete=models.CASCADE, related_name="read_markers"
    )
    channel = models.ForeignKey(
        Channel, null=True, blank=True, on_delete=models.CASCADE, related_name="read_markers"
    )
    last_read_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "thread"),
                condition=models.Q(thread__isnull=False),
                name="parletre_one_marker_per_user_thread",
            ),
            models.UniqueConstraint(
                fields=("user", "channel"),
                condition=models.Q(channel__isnull=False, thread__isnull=True),
                name="parletre_one_marker_per_user_channel",
            ),
        ]

    def __str__(self) -> str:
        where = self.thread or self.channel
        return f"{self.user} read {where} @ {self.last_read_at:%Y-%m-%d %H:%M}"


#: Per-file attachment size cap (10 MB).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class Attachment(models.Model):
    """A file attached to a post (DISC-3).

    Served only through the permission-checked download view
    (``parletre:attachment``), never by a bare media URL — so attachments in
    a private channel stay as private as the channel. Files are stored by
    :func:`parletre.storage.attachment_storage` *outside* the public media
    root, so no web server serves them directly.
    """

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="%Y/%m/", storage=attachment_storage)
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("uploaded_at",)

    def __str__(self) -> str:
        return self.original_name or self.file.name

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")


class DigestPreference(models.Model):
    """How often a member wants a batched email digest of their digest-level
    channels (DISC-6). One per member; absence means no digest."""

    class Frequency(models.TextChoices):
        OFF = "off", _("No digest")
        DAILY = "daily", _("Daily")
        WEEKLY = "weekly", _("Weekly")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parletre_digest",
    )
    frequency = models.CharField(
        max_length=8, choices=Frequency.choices, default=Frequency.WEEKLY
    )
    last_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.user} digest: {self.frequency}"


class InboundEmail(models.Model):
    """Audit + idempotency record for a reply-by-email message (DISC-7)."""

    class Status(models.TextChoices):
        POSTED = "posted", _("Posted")
        DUPLICATE = "duplicate", _("Duplicate")
        NO_TOKEN = "no_token", _("No reply token")
        BAD_TOKEN = "bad_token", _("Bad token")
        SENDER_MISMATCH = "sender_mismatch", _("Sender mismatch")
        NO_TARGET = "no_target", _("Target gone")
        CANNOT_POST = "cannot_post", _("Not allowed to post")
        EMPTY = "empty", _("Empty after quote-strip")

    message_id = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    post = models.ForeignKey(
        Post, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"inbound {self.status} ({self.message_id or 'no-id'})"
