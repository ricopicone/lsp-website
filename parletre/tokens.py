"""Signed reply tokens for reply-by-email (DISC-7).

A notification email about thread T sent to member U carries a
``Reply-To: reply+<token>@PARLETRE_REPLY_DOMAIN`` where ``<token>`` encodes
(target, recipient) and an HMAC signature. When U replies, the inbound
handler parses the token, verifies the signature, and posts the reply to T
as U. The token is single-purpose and carries no secret — just the target
kind/id and the user id, signed so it can't be forged or retargeted.

Tokens use only dot-atom-safe characters (letters, digits, ``.`` ``-`` ``_``)
so they're valid in an email local part.
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings

# kind markers: a thread, or a (chat) channel
THREAD = "t"
CHANNEL = "c"


def _secret() -> bytes:
    return (getattr(settings, "PARLETRE_REPLY_SECRET", "") or settings.SECRET_KEY).encode()


def _sign(payload: str) -> str:
    # Lowercase hex so the token survives any case-normalisation of the email
    # address it travels in (base64 would not).
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:24]


def make_token(kind: str, target_id: int, user_id: int) -> str:
    """A signed, email-safe token binding a reply target to a recipient."""
    payload = f"{kind}{target_id}.{user_id}"
    return f"{payload}.{_sign(payload)}"


def parse_token(token: str) -> dict | None:
    """Verify ``token`` and return ``{"kind", "target_id", "user_id"}`` or None."""
    try:
        payload, sig = token.rsplit(".", 1)
        kind_and_target, user_part = payload.split(".", 1)
        kind, target_id = kind_and_target[0], int(kind_and_target[1:])
        user_id = int(user_part)
    except (ValueError, IndexError):
        return None
    if kind not in (THREAD, CHANNEL):
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    return {"kind": kind, "target_id": target_id, "user_id": user_id}
