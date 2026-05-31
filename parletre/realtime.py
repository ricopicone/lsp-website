"""Realtime helpers for Parlêtre chat (M13.5b).

A chat channel maps to a Channels group; new posts are broadcast to it so
connected members see them live. The consumer broadcasts posts made over the
WebSocket; :func:`broadcast_chat_post` lets the plain-HTTP fallback path
(``views.channel``) broadcast too, so a no-JS post still reaches live clients.
"""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def chat_group(channel_id: int) -> str:
    return f"parletre_chat_{channel_id}"


def message_payload(post) -> dict:
    author = "(removed)"
    if post.author:
        author = post.author.get_full_name() or post.author.email
    return {
        "type": "chat.message",  # → ChatConsumer.chat_message
        "id": post.id,
        "author": author,
        "body_html": str(post.body_html),
        "created": post.created_at.isoformat(),
    }


def broadcast_chat_post(post) -> None:
    """Broadcast a chat post to its channel group (called from sync code)."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(chat_group(post.channel_id), message_payload(post))
