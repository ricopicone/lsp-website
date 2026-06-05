"""WebSocket consumer for Parlêtre realtime chat (M13.5b).

One consumer per connected member per chat channel. On connect it enforces
the same access rules as the HTTP views (membership + channel visibility +
chat kind) and joins the channel's group. Messages received over the socket
become real ``Post`` rows (and fan out notifications/emails like any post),
then broadcast to everyone in the group. Lightweight join/leave presence is
broadcast too.
"""

from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import presence
from .models import Channel, Post
from .permissions import channel_can_post, channel_visible
from .realtime import chat_group, message_payload
from .services import notify_post

MAX_BODY = 10_000


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.channel_obj = await self._load_channel(self.slug)
        if (
            self.channel_obj is None
            or self.channel_obj.kind != Channel.Kind.CHAT
            or not await self._can_view()
        ):
            await self.close()
            return
        self.group = chat_group(self.channel_obj.id)
        self.display = self._display_name()
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        presence.join_channel(self.channel_obj.id, self.user)
        await self._broadcast_roster()

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            presence.leave_channel(self.channel_obj.id, self.user)
            await self._broadcast_roster()
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # A periodic keep-alive ping refreshes presence (no broadcast needed).
        if content.get("ping"):
            presence.ping_channel(self.channel_obj.id, self.user)
            return
        body = (content.get("body") or "").strip()[:MAX_BODY]
        if not body:
            return
        payload = await self._create_post(body, content.get("reply_to"))
        if payload is not None:
            await self.channel_layer.group_send(self.group, payload)

    async def _broadcast_roster(self):
        roster = presence.online_channel(self.channel_obj.id)
        await self.channel_layer.group_send(
            self.group, {"type": "presence.event", "roster": roster}
        )

    # --- group event handlers ---

    async def chat_message(self, event):
        await self.send_json(
            {
                "kind": "message",
                "id": event["id"],
                "author": event["author"],
                "body_html": event["body_html"],
                "created": event["created"],
                "reply_to": event.get("reply_to"),
            }
        )

    async def presence_event(self, event):
        await self.send_json({"kind": "presence", "roster": event["roster"]})

    # --- db-bound helpers ---

    @database_sync_to_async
    def _load_channel(self, slug):
        return Channel.objects.filter(slug=slug).select_related("committee").first()

    @database_sync_to_async
    def _can_view(self):
        return channel_visible(self.channel_obj, self.user)

    @database_sync_to_async
    def _create_post(self, body, reply_to_id=None):
        if not channel_can_post(self.channel_obj, self.user):
            return None
        reply_to = None
        if reply_to_id:
            reply_to = Post.objects.filter(
                pk=reply_to_id, channel=self.channel_obj
            ).first()
        post = Post.objects.create(
            channel=self.channel_obj, author=self.user, body=body, reply_to=reply_to
        )
        notify_post(post)
        return message_payload(post)

    def _display_name(self) -> str:
        user = self.user
        if not getattr(user, "is_authenticated", False):
            return "Someone"
        return user.get_full_name() or user.email
