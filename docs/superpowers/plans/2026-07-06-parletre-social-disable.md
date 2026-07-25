# Parlêtre Social Disable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reversibly hide Parlêtre's school-wide social channels + private chats behind two feature flags (both default off), with a docs file listing what's off and how to restore it.

**Architecture:** Two env-var flags gate the single visibility chokepoint `parletre.permissions.channel_visible` (which the index, channel view, search, websocket consumer, and digests all already call) plus the private-chat creation path. Nothing is deleted; flipping a flag restores everything.

**Tech Stack:** Django 5.2, Python 3.10, pytest-django, uv, Tailwind v4 + DaisyUI.

## Global Constraints

- Django 5.2 / Python 3.10+; deps via `uv`. Keep pytest + `uv run ruff check .` green.
- `accounts.User` custom user model. DaisyUI semantic tokens only in templates. New copy uses commas, not em dashes (task #352).
- Both flags **default OFF**: `DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED`, `DJANGO_PARLETRE_PRIVATE_CHATS_ENABLED`.
- Nothing deleted — reversible via env var. No data migration.
- LEAVE visible always: Announcements (`slug="announcements"`), LSP Staff (`access=lsp_staff`), all workgroup channels (`access=workgroup`).
- `Channel.Access` values: `OPEN`, `ROLE`, `COMMITTEE`, `WORKGROUP`, `PRIVATE`, `LSP_STAFF`.

---

### Task 1: Flags + `channel_visible` gating (covers all read/visibility paths)

**Files:**
- Modify: `config/settings/base.py` (two flags), `parletre/permissions.py` (`channel_visible` + helper)
- Test: `parletre/test_social_disable.py` (new)

**Interfaces:**
- Produces: settings `PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED`, `PARLETRE_PRIVATE_CHATS_ENABLED` (bools); `parletre.permissions._is_schoolwide_social(channel) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# parletre/test_social_disable.py
import pytest
from django.test import override_settings

from accounts.models import Profile, User
from parletre.models import Channel
from parletre.permissions import channel_visible


def _member(email, role=Profile.Role.ANALYST, is_staff=False):
    u = User.objects.create_user(email=email, password="x", is_staff=is_staff)
    u.profile.role = role
    u.profile.save()
    return u


def _channel(slug, access=Channel.Access.OPEN, kind=Channel.Kind.CHAT, ttl=None):
    return Channel.objects.create(slug=slug, name=slug.title(), access=access, kind=kind,
                                  message_ttl_seconds=ttl)


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=False, PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_member_cannot_see_schoolwide_social_when_off():
    m = _member("m@x.test")
    assert channel_visible(_channel("lounge"), m) is False
    assert channel_visible(_channel("the-commons", kind=Channel.Kind.FORUM), m) is False
    assert channel_visible(_channel("purloined-letters", ttl=86400), m) is False
    # Kept-visible channels stay visible:
    assert channel_visible(_channel("announcements", kind=Channel.Kind.FORUM), m) is True


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=False, PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_staff_still_sees_schoolwide_social_when_off():
    staff = _member("s@x.test", is_staff=True)
    assert channel_visible(_channel("lounge"), staff) is True


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=False, PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_private_chat_hidden_even_from_creator_when_off():
    creator = _member("c@x.test")
    ch = _channel("dm-1", access=Channel.Access.PRIVATE)
    ch.members.add(creator)
    ch.moderators.add(creator)   # creators are moderators
    assert channel_visible(ch, creator) is False


@pytest.mark.django_db
@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=True, PARLETRE_PRIVATE_CHATS_ENABLED=True)
def test_flags_on_restores_visibility():
    m = _member("m2@x.test")
    assert channel_visible(_channel("lounge"), m) is True
    ch = _channel("dm-2", access=Channel.Access.PRIVATE)
    ch.members.add(m)
    assert channel_visible(ch, m) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest parletre/test_social_disable.py -q`
Expected: FAIL (flags/gating not present; the "cannot see" tests fail because the channels are currently visible).

- [ ] **Step 3: Add the settings flags**

In `config/settings/base.py` (near other Parlêtre settings, e.g. `PARLETRE_USE_REDIS`):
```python
# Reversibly hide Parlêtre's school-wide social channels + private chats (task
# #360). Both default off; flip the env var to restore. See
# docs/parletre-disabled-features.md.
PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED = env.bool("DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED", default=False)
PARLETRE_PRIVATE_CHATS_ENABLED = env.bool("DJANGO_PARLETRE_PRIVATE_CHATS_ENABLED", default=False)
```

- [ ] **Step 4: Gate `channel_visible`**

In `parletre/permissions.py`: ensure `from django.conf import settings` is imported (add if missing). Add the helper above `channel_visible`:
```python
def _is_schoolwide_social(channel) -> bool:
    """The school-wide social channels retired in task #360: any disappearing
    channel (Purloined Letters), or any OPEN channel other than Announcements.
    Excludes LSP Staff (access=lsp_staff), workgroup, and Announcements."""
    if channel.message_ttl_seconds:
        return True
    return channel.access == channel.Access.OPEN and channel.slug != "announcements"
```
Then, inside `channel_visible`, immediately after the `can_enter_parletre` guard (before the `archived` check):
```python
    # Reversible #360 hides (default off): private chats vanish for everyone
    # (incl. creators — this sits above the moderator/membership checks below);
    # school-wide social channels vanish for regular members, staff retained.
    if channel.access == channel.Access.PRIVATE and not settings.PARLETRE_PRIVATE_CHATS_ENABLED:
        return False
    if _is_schoolwide_social(channel) and not settings.PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED:
        if not channel_can_moderate(channel, user):
            return False
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest parletre/test_social_disable.py -q`
Expected: PASS.

- [ ] **Step 6: Run the Parlêtre suite (regression: existing visibility tests)**

Run: `uv run pytest parletre/ -q`
Expected: PASS. If a pre-existing test created an OPEN or PRIVATE channel and asserted a member sees it *without* overriding the flags, update it to `@override_settings(PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED=True, PARLETRE_PRIVATE_CHATS_ENABLED=True)` — that test predates the flags and wants the pre-#360 behavior.

- [ ] **Step 7: Commit**

```bash
git add config/settings/base.py parletre/permissions.py parletre/test_social_disable.py
git commit -m "parletre: flag-gate school-wide social + private chat visibility (#360)"
```

---

### Task 2: Disable private-chat creation (view + button)

**Files:**
- Modify: `parletre/views.py` (`create_private_chat` gate; `index` context), `parletre/templates/parletre/index.html` (button)
- Test: `parletre/test_social_disable.py` (extend)

**Interfaces:**
- Consumes: `settings.PARLETRE_PRIVATE_CHATS_ENABLED` (Task 1).

- [ ] **Step 1: Write the failing tests**

```python
# parletre/test_social_disable.py (append)
from django.urls import reverse


@pytest.mark.django_db
@override_settings(PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_create_private_chat_blocked_when_off(client):
    m = _member("cc@x.test")
    client.force_login(m)
    resp = client.get(reverse("parletre:create_private_chat"), SERVER_NAME="localhost")
    assert resp.status_code == 403


@pytest.mark.django_db
@override_settings(PARLETRE_PRIVATE_CHATS_ENABLED=False)
def test_new_private_chat_button_hidden_when_off(client):
    m = _member("bb@x.test")
    client.force_login(m)
    body = client.get(reverse("parletre:index"), SERVER_NAME="localhost").content.decode()
    assert reverse("parletre:create_private_chat") not in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest parletre/test_social_disable.py -q -k "create_private or button"`
Expected: FAIL.

- [ ] **Step 3: Gate the creation view**

In `parletre/views.py`, ensure `from django.http import HttpResponseForbidden` is imported. In `create_private_chat`, right after the existing `is_member` guard:
```python
    if not settings.PARLETRE_PRIVATE_CHATS_ENABLED:
        return HttpResponseForbidden("Private chats are currently disabled.")
```
Ensure `from django.conf import settings` is imported in `parletre/views.py`.

- [ ] **Step 4: Pass the flag to the index template**

In `parletre/views.py` `index`, add to the render context dict:
```python
        "private_chats_enabled": settings.PARLETRE_PRIVATE_CHATS_ENABLED,
```

- [ ] **Step 5: Hide the button**

In `parletre/templates/parletre/index.html`, wrap the "New private chat" link (~line 10):
```html
    {% if private_chats_enabled %}
    <a href="{% url 'parletre:create_private_chat' %}" class="btn btn-sm btn-primary gap-1">{% icon "lock" %} New private chat</a>
    {% endif %}
```

- [ ] **Step 6: Run to verify pass + Parlêtre suite**

Run:
```bash
uv run pytest parletre/test_social_disable.py -q
uv run pytest parletre/ -q
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add parletre/views.py parletre/templates/parletre/index.html parletre/test_social_disable.py
git commit -m "parletre: disable private-chat creation when the flag is off (#360)"
```

---

### Task 3: Disabled-features doc

**Files:**
- Create: `docs/parletre-disabled-features.md`

- [ ] **Step 1: Write the doc**

Create `docs/parletre-disabled-features.md` with: a short intro (task #360, reversible, nothing deleted); a table with columns **Feature | Flag | What it hides | Re-enable**; rows for the school-wide social set (The Lounge, Welcome, The Commons, The Gaze, Purloined Letters → `DJANGO_PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED`) and private chats (`DJANGO_PARLETRE_PRIVATE_CHATS_ENABLED`); the meeting rationale; and a "Still on" line (Announcements, LSP Staff, group channels). Re-enable step: set the env var to `true` in `~/lsp-website/.env` on the host and restart; everything reappears intact.

- [ ] **Step 2: Commit**

```bash
git add docs/parletre-disabled-features.md
git commit -m "docs: list the Parletre features disabled by #360 + how to restore"
```

---

## Self-review (coverage map)

- Two flags default off (spec §Approach) → Task 1 Step 3.
- `channel_visible` gating covering index/view/search/websocket/digest (spec §Approach, §Other access paths) → Task 1 Step 4 (all those paths already route through `channel_visible` — verified in the spec exploration).
- School-wide hidden from members, staff retained; private hidden from all incl. creator (spec §Approach) → Task 1 tests.
- LSP Staff / Announcements / workgroup left visible (spec §Goal) → `_is_schoolwide_social` excludes them; asserted for Announcements in Task 1.
- Disable private-chat creation (view + button) (spec §Disabling private-chat creation) → Task 2.
- Docs file (spec §The disabled-features doc) → Task 3.
- Reversibility via flag-on (spec §Reversibility) → Task 1 `test_flags_on_restores_visibility`.

## Post-plan (controller, not a code task)
- Add a one-line pointer to the `launch-checklist` project memory: the two `DJANGO_PARLETRE_*_ENABLED` flags default off; flipping to true restores the spaces.
