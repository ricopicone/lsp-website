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

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from . import permissions
from .rendering import render_markdown


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

    class Access(models.TextChoices):
        OPEN = "open", _("Open — every member")
        ROLE = "role", _("Specific roles")
        COMMITTEE = "committee", _("Committee")
        PRIVATE = "private", _("Private — named members")
        # "Open" means open to every *member* — never to the public. All of
        # Parlêtre sits behind the members-only gate (see permissions.is_member).
        # A CARTEL access mode + a ``cartel`` FK arrive with the cartels app
        # (M14), which auto-provisions one private channel per cartel.

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

    position = models.IntegerField(
        default=0, help_text="Sort order within the category. Lower = earlier."
    )
    archived = models.BooleanField(
        default=False, help_text="Hidden from members; lingers for moderators."
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
    def description_html(self) -> str:
        return render_markdown(self.description)

    # ---- Access (delegates to parletre.permissions) ----

    def visible_to(self, user) -> bool:
        return permissions.channel_visible(self, user)

    def can_post(self, user) -> bool:
        return permissions.channel_can_post(self, user)

    def can_moderate(self, user) -> bool:
        return permissions.channel_can_moderate(self, user)


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
