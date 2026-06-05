"""Thin Daily.co REST client (https://docs.daily.co/reference).

Bearer-authenticated against ``DAILY_API_URL`` with ``DAILY_API_KEY``. Uses
``requests`` (already a dependency via Stripe). All failures raise
``DailyError``; callers degrade gracefully (fall back to ``access_info``).
"""
from __future__ import annotations

import base64
import hashlib
import hmac

import requests
from django.conf import settings


class DailyError(Exception):
    """Any non-success response from the Daily API."""


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.DAILY_API_KEY}",
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{settings.DAILY_API_URL.rstrip('/')}/{path.lstrip('/')}"


def create_room(name: str, *, properties: dict | None = None) -> dict:
    """Create a private room. If it already exists, return the existing one."""
    payload = {
        "name": name,
        "privacy": "private",
        "properties": properties or {},
    }
    resp = requests.post(_url("rooms"), json=payload, headers=_headers(), timeout=15)
    if resp.status_code == 200:
        return resp.json()
    # Daily returns 400 with an "already exists" error when the name is taken.
    if resp.status_code == 400 and "exist" in resp.text.lower():
        return get_room(name)
    raise DailyError(f"create_room({name}) -> {resp.status_code}: {resp.text}")


def update_room(name: str, properties: dict) -> dict:
    """Update a room's config (e.g. toggle enable_recording)."""
    resp = requests.post(
        _url(f"rooms/{name}"), json={"properties": properties}, headers=_headers(), timeout=15
    )
    if resp.status_code == 200:
        return resp.json()
    raise DailyError(f"update_room({name}) -> {resp.status_code}: {resp.text}")


def get_room(name: str) -> dict | None:
    """Fetch a room, or ``None`` if it doesn't exist (404) — lets callers detect a
    room that was deleted on Daily's side and recreate it."""
    resp = requests.get(_url(f"rooms/{name}"), headers=_headers(), timeout=15)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    raise DailyError(f"get_room({name}) -> {resp.status_code}: {resp.text}")


def delete_room(name: str) -> bool:
    resp = requests.delete(_url(f"rooms/{name}"), headers=_headers(), timeout=15)
    if resp.status_code in (200, 404):
        return True
    raise DailyError(f"delete_room({name}) -> {resp.status_code}: {resp.text}")


def get_presence() -> dict:
    """GET /presence — active participants grouped by room (near-real-time, up to
    ~15s lag). Returns a ``{room_name: [participant, ...]}`` map, tolerating either
    the ``{"data": {...}}`` wrapper or a flat top-level map.
    """
    resp = requests.get(_url("presence"), headers=_headers(), timeout=10)
    if resp.status_code != 200:
        raise DailyError(f"get_presence -> {resp.status_code}: {resp.text}")
    payload = resp.json()
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return {k: v for k, v in payload.items() if k != "total_count" and isinstance(v, list)}


# --- recordings ----------------------------------------------------------

def get_recording(recording_id: str) -> dict | None:
    resp = requests.get(
        _url(f"recordings/{recording_id}"), headers=_headers(), timeout=15
    )
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    raise DailyError(f"get_recording({recording_id}) -> {resp.status_code}: {resp.text}")


def recording_access_link(recording_id: str) -> str | None:
    """A temporary, playable URL for a recording stored on Daily (or our bucket
    with allow_api_access). ``None`` if the recording isn't available."""
    resp = requests.get(
        _url(f"recordings/{recording_id}/access-link"), headers=_headers(), timeout=15
    )
    if resp.status_code == 200:
        return resp.json().get("download_link") or resp.json().get("link")
    if resp.status_code in (404, 425):  # 425: not ready yet
        return None
    raise DailyError(
        f"recording_access_link({recording_id}) -> {resp.status_code}: {resp.text}"
    )


def delete_recording(recording_id: str) -> bool:
    resp = requests.delete(
        _url(f"recordings/{recording_id}"), headers=_headers(), timeout=15
    )
    if resp.status_code in (200, 404):
        return True
    raise DailyError(f"delete_recording({recording_id}) -> {resp.status_code}: {resp.text}")


def verify_webhook(timestamp: str, raw_body: bytes, signature: str) -> bool:
    """Verify a Daily webhook: base64 HMAC-SHA256 over ``timestamp + "." + body``,
    keyed by the base64-decoded ``DAILY_WEBHOOK_SECRET``. Constant-time compare."""
    secret = getattr(settings, "DAILY_WEBHOOK_SECRET", "")
    if not (secret and timestamp and signature):
        return False
    try:
        key = base64.b64decode(secret)
    except (ValueError, TypeError):
        return False
    msg = timestamp.encode() + b"." + raw_body
    computed = base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(computed, signature)


def create_meeting_token(
    *, room_name: str, user_name: str = "", is_owner: bool = False, exp: int | None = None
) -> str:
    """Mint a short-lived meeting token scoped to ``room_name``.

    ``is_owner`` grants moderator controls (faculty/leaders). ``exp`` is a unix
    timestamp after which the token is rejected.
    """
    props: dict = {"room_name": room_name, "is_owner": is_owner}
    if user_name:
        props["user_name"] = user_name
    if exp is not None:
        props["exp"] = exp
    resp = requests.post(
        _url("meeting-tokens"), json={"properties": props}, headers=_headers(), timeout=15
    )
    if resp.status_code == 200:
        return resp.json()["token"]
    raise DailyError(f"create_meeting_token({room_name}) -> {resp.status_code}: {resp.text}")
