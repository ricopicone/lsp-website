"""Django admin for Parlêtre.

Staff create channels and categories here and moderate as needed. Threads
and posts are created by members through the board UI, but appear here
(read-mostly) for moderation and audit.
"""

from __future__ import annotations

from django.contrib import admin

from .models import Channel, ChannelCategory, Post, Reaction, Subscription, Thread


@admin.register(ChannelCategory)
class ChannelCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "slug")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("position", "name")


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "kind", "category", "access", "post_policy", "archived")
    list_filter = ("kind", "access", "post_policy", "archived", "category")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members", "moderators")
    fieldsets = (
        (None, {"fields": ("name", "slug", "category", "kind", "description")}),
        (
            "Access",
            {
                "fields": ("access", "allowed_roles", "committee", "members", "moderators"),
                "description": "allowed_roles applies when access=Specific roles; "
                "committee when access=Committee; members when access=Private.",
            },
        ),
        (
            "Posting & subscriptions",
            {"fields": ("post_policy", "auto_subscribe", "default_subscription_level")},
        ),
        ("Display", {"fields": ("position", "archived")}),
    )


class PostInline(admin.TabularInline):
    model = Post
    fields = ("author", "body", "via_email", "deleted", "created_at")
    readonly_fields = ("created_at",)
    extra = 0


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = (
        "title", "channel", "author", "pinned", "locked", "resolved", "last_activity_at",
    )
    list_filter = ("channel", "pinned", "locked", "resolved")
    search_fields = ("title", "slug")
    raw_id_fields = ("channel", "author")
    inlines = [PostInline]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("__str__", "channel", "author", "via_email", "deleted", "created_at")
    list_filter = ("channel", "via_email", "deleted")
    search_fields = ("body",)
    raw_id_fields = ("channel", "thread", "author", "reply_to")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "level", "updated_at")
    list_filter = ("level", "channel")
    raw_id_fields = ("user", "channel")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("emoji", "post", "user", "created_at")
    raw_id_fields = ("post", "user")
