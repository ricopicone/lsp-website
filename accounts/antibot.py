"""Invisible bot deterrents for public forms (task #471).

Three cheap checks that cost a human nothing and stop commodity spam bots:
a honeypot field, a minimum fill time, and a per-IP cap.

Kept apart from any one form so each check is testable on its own and the
other public forms (the Find-an-Analyst referral form) can adopt them later.

**Ordering matters where these are used.** The honeypot and the rate limit
must reject *before* any mail is sent — a bot signing up as a stranger's
address would otherwise still make the school mail that stranger.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.core.signing import BadSignature, dumps, loads
from django.utils import timezone

#: Field names. Deliberately plausible — a field called "honeypot" is a
#: giveaway to any bot that bothers to look.
HONEYPOT_FIELD = "website"
TIMESTAMP_FIELD = "form_ts"

_SALT = "accounts.antibot"

#: Minimum seconds between rendering the form and submitting it. Conservative:
#: password managers and autofill can legitimately be quick, and the resulting
#: error is recoverable rather than a silent drop.
MIN_FILL_SECONDS = 2

#: The Find-an-Analyst form is a two-step wizard with seven fields; no human
#: clears it in ten seconds, so it can afford a stricter floor than signup
#: (task #479).
REFERRAL_MIN_FILL_SECONDS = 10

#: Per-IP signup cap. Generous — real members share institutional IPs, and a
#: seminar cohort signing up from one campus must not lock itself out.
RATE_LIMIT = 5
RATE_WINDOW = timedelta(hours=1)


def sign_timestamp(when=None) -> str:
    """A tamper-proof stamp of when the form was rendered.

    ``when`` is injectable so tests can age a form without patching clocks.
    """
    moment = when or timezone.now()
    return dumps(moment.timestamp(), salt=_SALT)


def seconds_since_render(value: str) -> float | None:
    """Seconds since the form was rendered, or ``None`` if the stamp is
    missing or forged (which is itself bot-shaped)."""
    if not value:
        return None
    try:
        rendered_at = loads(value, salt=_SALT)
    except BadSignature:
        return None
    return timezone.now().timestamp() - float(rendered_at)


def looks_too_fast(value: str, minimum: float = MIN_FILL_SECONDS) -> bool:
    """Whether this submission arrived faster than a human could type it.

    ``minimum`` is per-form: a short signup and a multi-step wizard have
    very different floors.
    """
    elapsed = seconds_since_render(value)
    if elapsed is None:
        return True
    return elapsed < minimum


def client_ip(request) -> str:
    """The caller's IP, honouring the proxy header set by the host nginx."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _rate_key(ip: str) -> str:
    return f"antibot:signup:{ip}"


def over_rate_limit(ip: str) -> bool:
    """Whether this IP has already used up its hourly allowance."""
    if not ip:
        return False
    return cache.get(_rate_key(ip), 0) >= RATE_LIMIT


def record_attempt(ip: str) -> None:
    """Count one signup attempt against ``ip``."""
    if not ip:
        return
    key = _rate_key(ip)
    # add() only sets when absent, so the window starts at the first attempt
    # and is not extended by later ones.
    cache.add(key, 0, int(RATE_WINDOW.total_seconds()))
    try:
        cache.incr(key)
    except ValueError:  # entry expired between add() and incr()
        cache.set(key, 1, int(RATE_WINDOW.total_seconds()))
