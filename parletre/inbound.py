"""Reply-by-email inbound processing (DISC-7).

Given the raw bytes of a received email, post the member's reply back to the
thread. Security rests on two checks, not on the transport: the Reply-To
token is HMAC-signed (can't be forged or retargeted — see
:mod:`parletre.tokens`), and the email's From must match the address the
token was minted for. Every message is recorded (:class:`InboundEmail`) for
idempotency (Message-ID) and audit.

The transport — SES inbound → SNS (→ S3) → the webhook — is wired at deploy
time; this module only needs the raw MIME, so it's fully unit-testable.
"""

from __future__ import annotations

import email
import email.policy
import logging
import re
from email.utils import getaddresses, parseaddr

from django.conf import settings
from django.contrib.auth import get_user_model

from . import tokens
from .models import Channel, InboundEmail, Post, Thread
from .services import notify_post

log = logging.getLogger("parletre")
User = get_user_model()

MAX_BODY = 50_000

# Lines at or below which the quoted history begins (top-posting assumed).
_QUOTE_MARKERS = [
    re.compile(r"^On .+ wrote:\s*$"),
    re.compile(r"^-+\s*Original Message\s*-+", re.IGNORECASE),
    re.compile(r"^_{5,}\s*$"),
    re.compile(r"^From:\s", re.IGNORECASE),
    re.compile(r"^Sent from my ", re.IGNORECASE),
]


def extract_reply(text: str) -> str:
    """Return just the new reply — drop quoted history and signatures."""
    out = []
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped == "--" or stripped == "-- ":  # signature delimiter
            break
        if stripped.startswith(">"):
            break
        if any(rx.match(stripped) for rx in _QUOTE_MARKERS):
            break
        out.append(line)
    return "\n".join(out).strip()


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _token_from_recipients(msg) -> str | None:
    domain = settings.PARLETRE_REPLY_DOMAIN.lower()
    headers = ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To")
    for _name, addr in getaddresses(
        [v for h in headers for v in msg.get_all(h, [])]
    ):
        a = addr.lower()
        if a.startswith("reply+") and a.endswith("@" + domain):
            return a[len("reply+"):].rsplit("@", 1)[0]
    return None


def _body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        return _strip_html(content)
    return content


def _record(status, *, message_id="", user=None, post=None) -> dict:
    InboundEmail.objects.create(
        message_id=message_id or "", status=status, user=user, post=post
    )
    return {"status": status}


def process_inbound_email(raw: bytes) -> dict:
    """Parse a received email and post the reply. Returns ``{"status": ...}``."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    message_id = (msg.get("Message-ID") or "").strip()

    if message_id and InboundEmail.objects.filter(message_id=message_id).exists():
        return {"status": InboundEmail.Status.DUPLICATE}

    token = _token_from_recipients(msg)
    if not token:
        return _record(InboundEmail.Status.NO_TOKEN, message_id=message_id)
    data = tokens.parse_token(token)
    if not data:
        return _record(InboundEmail.Status.BAD_TOKEN, message_id=message_id)

    user = User.objects.filter(pk=data["user_id"]).first()
    from_email = parseaddr(msg.get("From", ""))[1].lower()
    if user is None or not user.email or user.email.lower() != from_email:
        return _record(InboundEmail.Status.SENDER_MISMATCH, message_id=message_id, user=user)

    if data["kind"] == tokens.THREAD:
        thread = Thread.objects.select_related("channel").filter(pk=data["target_id"]).first()
        channel = thread.channel if thread else None
    else:
        thread = None
        channel = Channel.objects.filter(pk=data["target_id"]).first()
    if channel is None:
        return _record(InboundEmail.Status.NO_TARGET, message_id=message_id, user=user)
    if not channel.can_post(user) or (thread is not None and thread.locked):
        return _record(InboundEmail.Status.CANNOT_POST, message_id=message_id, user=user)

    body = extract_reply(_body_text(msg))[:MAX_BODY].strip()
    if not body:
        return _record(InboundEmail.Status.EMPTY, message_id=message_id, user=user)

    post = Post.objects.create(
        channel=channel, thread=thread, author=user, body=body, via_email=True
    )
    if thread is not None:
        thread.touch()
    notify_post(post)
    log.info("parletre: posted reply-by-email from %s to %s", from_email, channel.slug)
    return _record(InboundEmail.Status.POSTED, message_id=message_id, user=user, post=post)
