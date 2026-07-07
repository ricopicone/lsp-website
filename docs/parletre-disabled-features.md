# Parlêtre — features disabled for now (task #360)

At the board's website-review meeting, several Parlêtre spaces were **turned off
for now** and hidden from members. **Nothing was deleted.** Each is gated by a
feature flag that defaults off; flipping the flag back on restores the space
exactly as it was (channels, posts, subscriptions, private chats all intact).

This is the list to point to when advocating to bring any of them back. Tracked
in the project as tasks #383 (school-wide) and #384 (private chats).

## What's off

| Feature | Flag (host `.env`) | What it hides | Re-enable |
|---|---|---|---|
| School-wide chats — **The Lounge**, **Welcome** | `DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED` | Hidden from members (staff still see them) | Set the flag to `true`, restart |
| School-wide forum — **The Commons** | `DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED` | Hidden from members (staff still see them) | Set the flag to `true`, restart |
| School-wide video — **The Gaze** | `DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED` | Hidden from members (staff still see them) | Set the flag to `true`, restart |
| Disappearing chats — **Purloined Letters** | `DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED` | Hidden from members (staff still see it) | Set the flag to `true`, restart |
| **Private chats** (all existing + creating new) | `DJANGO_PARLETRE_PRIVATE_CHATS_ENABLED` | Hidden from everyone, incl. their creators; the "New private chat" button and its page are disabled (this also removes the disappearing-message option, which lived in that form) | Set the flag to `true`, restart |

Both flags default **off** in production and **on** in dev/test, so developers
still exercise the full board.

## Why (from the meeting)

In a school of psychoanalysis we are responsible for our speech (the *Purloined
Letters* point). The board chose to retire the school-wide social spaces and the
private/disappearing chats for now, keeping the working spaces.

## Still on (unchanged)

- **Announcements** forum.
- **LSP Staff** forum.
- All **group-specific** chats and forums (seminars, cartels, committees,
  working groups, reading groups), reached from each group's Workspace.

## How to re-enable

On the EC2 host (`~/lsp-website/.env`), set the relevant flag to `true` and
restart the app:

```
DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=true
DJANGO_PARLETRE_PRIVATE_CHATS_ENABLED=true
```

Bring them back independently — the two flags are separate. No migration or data
restore is needed; the spaces reappear as they were.
