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


def _author_name(user) -> str:
    return (user.get_full_name() or user.email) if user else "(removed)"


def message_payload(post) -> dict:
    reply_to = None
    if post.reply_to_id:
        reply_to = {
            "id": post.reply_to_id,
            "author": _author_name(post.reply_to.author),
            "excerpt": post.reply_to.excerpt,
        }
    return {
        "type": "chat.message",  # → ChatConsumer.chat_message
        "id": post.id,
        "author": _author_name(post.author),
        "body_html": str(post.body_html),
        "created": post.created_at.isoformat(),
        "reply_to": reply_to,
    }


def broadcast_chat_post(post) -> None:
    """Broadcast a chat post to its channel group (called from sync code)."""
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(chat_group(post.channel_id), message_payload(post))
