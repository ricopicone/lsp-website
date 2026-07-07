# Parlêtre — reversibly disable school-wide social + private chats

**Date:** 2026-07-06
**Task:** #360 (parent) → #375 (disappearing chats), #376 (school-wide chats),
#377 (school-wide forums), #378 (school-wide video), #379 (private chats).
**Source:** Annie Rogers / Diana Cuello / Garrett website-review meeting (task #345).
**Rationale (Purloined Letters):** in a school of psychoanalysis we are
responsible for our speech; the board wants the school-wide social spaces and
private/disappearing chats retired for now, without deleting anything.

## Goal

Hide these Parlêtre spaces from members **reversibly** (nothing deleted; a flag
flip brings them back intact), and keep a repo doc listing what's off so Rico can
advocate to re-enable:

- **Disappearing chats** (Purloined Letters) — #375
- **School-wide chats** (The Lounge, Welcome) — #376
- **School-wide forums** (The Commons) — #377
- **School-wide video** (The Gaze) — #378
- **Private chats** (all existing + the ability to create new) — #379

**Leave untouched:** group-specific chats/forums (workgroup channels), the
Announcements forum, the LSP Staff forum.

## Approach — two feature flags (no data touched)

Two env-var flags, both **default OFF**, read in `config/settings/base.py`:

- `PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED = env.bool("DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED", default=False)`
- `PARLETRE_PRIVATE_CHATS_ENABLED = env.bool("DJANGO_PARLETRE_PRIVATE_CHATS_ENABLED", default=False)`

Enforced in the single visibility gate `parletre.permissions.channel_visible`
(which `Channel.visible_to`, the index, the channel view, and digests all use).
Add, near the top of `channel_visible` (after the `can_enter_parletre` check):

```python
# Private chats: hidden from EVERYONE when disabled, incl. their creators —
# placed above the moderator/membership check below.
if channel.access == Channel.Access.PRIVATE and not settings.PARLETRE_PRIVATE_CHATS_ENABLED:
    return False
# School-wide social spaces: hidden from regular members when disabled; staff
# keep access (to manage / decide on restoring).
if _is_schoolwide_social(channel) and not settings.PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED:
    if not channel_can_moderate(channel, user):
        return False
```

Helper in `parletre/permissions.py`:

```python
def _is_schoolwide_social(channel) -> bool:
    """The school-wide social channels retired in #360: any open channel other
    than Announcements, plus any disappearing channel (Purloined Letters).
    Excludes LSP Staff (access=lsp_staff), workgroup channels, and Announcements."""
    if channel.message_ttl_seconds:            # disappearing (Purloined Letters)
        return True
    return channel.access == Channel.Access.OPEN and channel.slug != "announcements"
```

**Why this is correct against prod data:** LSP Staff is `access=lsp_staff` (its
own mode), workgroup channels are `access=workgroup`, Announcements is excluded
by slug — none match `_is_schoolwide_social`. The Lounge / Welcome / The Commons
/ The Gaze are `access=open`; Purloined Letters matches on `message_ttl_seconds`.

## Disabling private-chat creation

When `PARLETRE_PRIVATE_CHATS_ENABLED` is off:

- `parletre.views.create_private_chat` returns 403 (or redirects to the Parlêtre
  index with a message) before doing any work.
- The "New private chat" button in `parletre/templates/parletre/index.html` (line
  ~10) is wrapped so it only renders when the flag is on. Expose the flag to the
  template via the index view context (add `private_chats_enabled` to the context)
  — do not rely on a global context processor.

## Other access paths must honor the flags

`channel_visible` is the primary gate, but verify (and fix if needed) that these
also refuse a hidden channel:

- **Direct channel view** (`parletre.views.channel` / `channel_chat`) — already
  gated by `channel_visible`; confirm.
- **Search** (`parletre/search.py`) — must filter results through
  `channel_visible` (or exclude hidden channels), so a hidden channel's posts
  don't surface in search.
- **WebSocket join** (`parletre/consumers.py`) — the consumer's channel-access
  check must enforce the same gate, so a member can't stream a hidden channel by
  slug.
- **Digests** (`parletre` digest builder) — must not email activity from hidden
  channels.

## The disabled-features doc (Rico's advocacy list)

Create `docs/parletre-disabled-features.md`: a table of each disabled feature,
its flag, exactly what it hides, the meeting rationale, and the one-line
re-enable step (set the env var to `true` on the host + restart). This is the
source of truth Rico points to when advocating to bring them back. Also add a
one-line pointer in the `launch-checklist` project memory noting the two flags
default off and that flipping them restores the spaces.

## Reversibility

Set either flag to `true` in the host `.env` and restart — the channels, posts,
subscriptions, and private chats all reappear exactly as they were. No migration,
no data change, no deletion.

## Testing

With both flags OFF (the default):
- A regular member's Parlêtre index shows none of the five social channels and no
  private chat; Announcements, LSP Staff, and workgroup channels still show.
- A **staff** member still sees the school-wide social channels (but not private
  chats they aren't in — private is hidden from all).
- `channel_visible` returns False for an open non-Announcements channel (regular
  member), a disappearing channel, and a private chat (even its creator).
- `create_private_chat` GET/POST returns 403; the "New private chat" button is
  absent from the index.
- Search does not surface a hidden channel's posts for a regular member.

With a flag overridden ON (via `override_settings`): the corresponding channels
become visible again, and `create_private_chat` works.

## Out of scope

- Deleting any channel, post, or private chat.
- Removing the disappearing-message code path (kept; just no channel uses it once
  Purloined Letters is hidden and private-chat creation is off).
- Changing group-specific, Announcements, or LSP Staff channels.
