"""WebSocket consumer for the live nav bell.

One consumer per connected member. It joins the member's personal group and
forwards :func:`notifications.realtime.broadcast_to_user` events to the browser.
The socket is read-only from the client's side (no inbound actions) — marking
read still goes through the HTTP views.
"""

from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Notification
from .realtime import user_group


class BellConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close()
            return
        self.group = user_group(user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        # Send the current count on connect so a freshly opened tab is accurate.
        await self.send_json({"unread": await self._unread(user.id), "item": None})

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def notify_event(self, event):
        await self.send_json({"unread": event["unread"], "item": event.get("item")})

    @database_sync_to_async
    def _unread(self, user_id):
        return Notification.objects.filter(
            recipient_id=user_id, read_at__isnull=True
        ).count()
