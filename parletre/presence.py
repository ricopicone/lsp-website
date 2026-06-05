"""Who's-online presence for Parlêtre — cache-backed, in-process.

Two scopes:
- **global**: anyone with a Parlêtre page open (refreshed by an HTTP heartbeat).
  Pure TTL model — an entry is "online" while it was touched within ``HEARTBEAT_TTL``.
- **per chat channel**: who currently has a chat open (the chat WebSocket).
  Connection-counted (handles multiple tabs) with a TTL backstop for unclean
  disconnects.

Runs on the single daphne prod process with the default LocMemCache, shared
between the HTTP views and the WS consumer (see config/asgi.py). No Redis, no DB.
"""
from __future__ import annotations

import time

from django.core.cache import cache

HEARTBEAT_TTL = 70           # seconds an entry stays online without a refresh
_CACHE_TTL = 900             # how long the cache holds the dict (entries pruned by ts)
_GLOBAL_KEY = "parletre:presence:global"
_CHAN_KEY = "parletre:presence:chan:{}"


def _display_name(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return "Someone"
    return (user.get_full_name() or user.email or "Someone").strip()


def _fresh(store: dict, now: float) -> dict:
    return {uid: e for uid, e in store.items() if now - e.get("ts", 0) <= HEARTBEAT_TTL}


def _roster(store: dict) -> list[dict]:
    return sorted(
        ({"id": uid, "name": e["name"]} for uid, e in store.items()),
        key=lambda e: e["name"].lower(),
    )


# --- global (anywhere in Parlêtre) --------------------------------------

def touch_global(user) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    now = time.time()
    store = _fresh(cache.get(_GLOBAL_KEY) or {}, now)
    store[user.id] = {"name": _display_name(user), "ts": now}
    cache.set(_GLOBAL_KEY, store, _CACHE_TTL)


def online_global() -> list[dict]:
    now = time.time()
    store = _fresh(cache.get(_GLOBAL_KEY) or {}, now)
    cache.set(_GLOBAL_KEY, store, _CACHE_TTL)
    return _roster(store)


# --- per chat channel ---------------------------------------------------

def _chan(channel_id) -> str:
    return _CHAN_KEY.format(channel_id)


def join_channel(channel_id, user) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    key, now = _chan(channel_id), time.time()
    store = _fresh(cache.get(key) or {}, now)
    entry = store.get(user.id) or {"conns": 0}
    entry.update(name=_display_name(user), ts=now, conns=entry.get("conns", 0) + 1)
    store[user.id] = entry
    cache.set(key, store, _CACHE_TTL)


def ping_channel(channel_id, user) -> None:
    """Refresh the TTL for a still-connected user (re-adds if it had lapsed)."""
    if not getattr(user, "is_authenticated", False):
        return
    key, now = _chan(channel_id), time.time()
    store = _fresh(cache.get(key) or {}, now)
    entry = store.get(user.id)
    if entry is None:
        entry = {"name": _display_name(user), "conns": 1}
    entry["ts"] = now
    store[user.id] = entry
    cache.set(key, store, _CACHE_TTL)


def leave_channel(channel_id, user) -> None:
    if not getattr(user, "is_authenticated", False):
        return
    key, now = _chan(channel_id), time.time()
    store = _fresh(cache.get(key) or {}, now)
    entry = store.get(user.id)
    if entry is not None:
        entry["conns"] = entry.get("conns", 1) - 1
        if entry["conns"] <= 0:
            del store[user.id]
        else:
            entry["ts"] = now
            store[user.id] = entry
        cache.set(key, store, _CACHE_TTL)


def online_channel(channel_id) -> list[str]:
    key, now = _chan(channel_id), time.time()
    store = _fresh(cache.get(key) or {}, now)
    cache.set(key, store, _CACHE_TTL)
    return [e["name"] for e in _roster(store)]
