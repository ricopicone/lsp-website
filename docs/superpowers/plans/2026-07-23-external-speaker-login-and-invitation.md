# External Speaker Login + Invitation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an external `events.Speaker` have an optional login that confers the same per-event presenter access internal speakers have, and give the Programming Committee a prepare-on-add / confirm-before-send invitation flow to onboard them.

**Architecture:** Add an optional `Speaker.user` login link; broaden `Event.is_presenter()` to recognize it (everything downstream — faculty view, access details, video room entry/moderation — already flows through `is_presenter`/`can_edit_event`). Add a `SpeakerInvitation` token (own token, because Django password reset skips unusable-password accounts) plus a PC-gated invite panel on the event edit page and a set-password landing view.

**Tech Stack:** Django 5.2, pytest-django, existing token patterns (`EmailChangeRequest`/`MagicLoginLink`), `core.email`, Daily video services (unchanged — already routes through `can_edit_event`).

## Global Constraints

- Django 5.2 / Python 3.10+; deps via `uv` (`uv run pytest`, `uv run ruff check .`).
- Tokens: opaque single-use via `secrets.token_urlsafe(32)`, stored plaintext in a `unique` field — match `EmailChangeRequest`/`MagicLoginLink`, NOT the hashed `DevApiToken` pattern.
- Consumption of any single-use emailed link must be POST-gated (email scanners GET-prefetch links — memory `auth-email-scanner-and-reset-gotchas`).
- Invited external-speaker users: `role=Profile.Role.EXTERNAL` (default), `public=False`, unusable password. This keeps them off the directory (`_directory_qs` gates on `role in DIRECTORY_ROLES AND public=True`) and they join no workgroup, so no roster leak.
- Member-facing copy: commas, not em dashes (memory `em-dash-prose-style`).
- Templates set in Python must appear in a template too (Tailwind scan) — N/A here (no new dynamic classes), but keep it in mind.
- PC/staff gate: reuse `events.permissions.can_edit_event` (per-event) for the invite surface, matching the event edit page it lives on.
- Run the full suite (`uv run pytest -q -n auto`) + `uv run ruff check .` before the final commit; do not merge until the Deploy run is green (memory `pushed-is-not-deployed`).

---

### Task 1: `Speaker.user` login link (model + admin + migration)

**Files:**
- Modify: `events/models.py` (the `Speaker` class, ~line 135-165)
- Modify: `events/admin.py:183-189` (`SpeakerAdmin`)
- Create: `events/migrations/00NN_speaker_user.py` (via makemigrations)
- Test: `events/tests.py` (append)

**Interfaces:**
- Produces: `Speaker.user` (nullable OneToOne to `accounts.User`, `related_name="external_speaker"`), reverse accessor `user.external_speaker`.

- [ ] **Step 1: Write the failing test**

Append to `events/tests.py`:

```python
@pytest.mark.django_db
def test_speaker_can_link_a_login_user():
    from events.models import Speaker
    u = User.objects.create_user(email="derek@example.com")
    s = Speaker.objects.create(name="Derek Hook", slug="derek-hook", email="derek@example.com")
    s.user = u
    s.save()
    s.refresh_from_db()
    assert s.user == u
    assert u.external_speaker == s
```

(`User` is already imported at the top of `events/tests.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest events/tests.py::test_speaker_can_link_a_login_user -v`
Expected: FAIL — `Speaker` has no attribute/field `user`.

- [ ] **Step 3: Add the field**

In `events/models.py`, inside `class Speaker`, after the `email` field:

```python
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_speaker",
        help_text=(
            "Optional login for this external presenter (task #463). Linking a "
            "user lets them join the meeting and see the event's presenter view, "
            "scoped to events they present. Leave blank for display-only speakers."
        ),
    )
```

(`settings` is already imported in `events/models.py`.)

- [ ] **Step 4: Make + apply the migration**

Run: `uv run python manage.py makemigrations events && uv run python manage.py migrate`
Expected: a new `events/migrations/00NN_speaker_user.py` adding the field; migrate OK.

- [ ] **Step 5: Expose the link in admin**

In `events/admin.py`, update `SpeakerAdmin`:

```python
@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    list_display = ("name", "affiliation", "email", "public", "user")
    list_filter = ("public",)
    search_fields = ("name", "affiliation", "email", "bio")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("user",)
    raw_id_fields = ()
```

(If `autocomplete_fields = ("user",)` errors because `UserAdmin` lacks `search_fields`, fall back to `raw_id_fields = ("user",)` and drop `autocomplete_fields`.)

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest events/tests.py::test_speaker_can_link_a_login_user -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add events/models.py events/admin.py events/migrations/
git commit -m "feat(events): optional login link on external Speaker (task #463)"
```

---

### Task 2: `is_presenter` recognizes a linked external speaker

**Files:**
- Modify: `events/models.py` (`Event.is_presenter`, ~line 462-481)
- Test: `events/test_faculty_views.py` (append), `events/test_location.py` (append)

**Interfaces:**
- Consumes: `Speaker.user` (Task 1), `Event.speakers` M2M (`related_name="events"`).
- Produces: `Event.is_presenter(user)` returns true for a user linked to any external `Speaker` on a non-offering event. No new symbols; `can_edit_event`, `can_enter_event`, `is_owner` inherit the behavior unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_faculty_views.py` (after the special-event section):

```python
def test_linked_external_speaker_gets_presenter_access(client, special_event):
    from events.models import Speaker
    u = User.objects.create_user(email="ext@example.com", first_name="Derek", last_name="Hook")
    s = Speaker.objects.create(name="Derek Hook", slug="derek-hook-1", email="ext@example.com", user=u)
    special_event.speakers.add(s)
    assert special_event.is_presenter(u) is True
    from events.permissions import can_edit_event
    assert can_edit_event(u, special_event) is True
    client.force_login(u)
    resp = client.get(reverse("events:detail", args=[special_event.slug]))
    assert b"Faculty view" in resp.content


def test_linked_external_speaker_can_enter_room(db):
    from events.models import Speaker
    from video.services import can_enter_event, is_owner
    e = Event.objects.create(
        title="Talk", slug="ext-room", event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 1), end_date=date(2030, 9, 1),
        published=True, status=Event.Status.OPEN,
    )
    u = User.objects.create_user(email="ext2@example.com")
    s = Speaker.objects.create(name="Guest", slug="guest-1", email="ext2@example.com", user=u)
    e.speakers.add(s)
    assert can_enter_event(e, u) is True
    assert is_owner(e, u) is True


def test_linked_external_speaker_on_offering_gets_nothing(db):
    from events.models import Speaker
    e = Event.objects.create(
        title="Sem", slug="ext-sem", event_type=Event.Type.SEMINAR,
        start_date=date(2030, 9, 1), end_date=date(2031, 5, 1),
    )
    u = User.objects.create_user(email="ext3@example.com")
    s = Speaker.objects.create(name="Guest", slug="guest-2", email="ext3@example.com", user=u)
    e.speakers.add(s)
    assert e.is_presenter(u) is False


def test_linked_external_speaker_absent_from_directory(client, db):
    from events.models import Speaker
    from accounts.views import _directory_qs
    u = User.objects.create_user(email="ext4@example.com", first_name="Derek", last_name="Hook")
    Speaker.objects.create(name="Derek Hook", slug="derek-hook-2", email="ext4@example.com", user=u)
    assert u not in [p.user for p in _directory_qs()]
```

(`special_event` fixture, `User`, `Event`, `date`, `reverse` already exist in `events/test_faculty_views.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/test_faculty_views.py -k "linked_external_speaker" -v`
Expected: the first two/three FAIL (is_presenter returns False); the directory + offering ones PASS already.

- [ ] **Step 3: Extend `is_presenter`**

In `events/models.py`, `Event.is_presenter`, change the final return:

```python
    def is_presenter(self, user) -> bool:
        """... (keep the existing docstring) ..."""
        if not getattr(user, "is_authenticated", False):
            return False
        if self.event_type in self.ANNUAL_PROGRAM_TYPES:
            return False
        if self.member_speakers.filter(pk=user.pk).exists():
            return True
        # External presenters with a linked login (task #463) are presenters of
        # this one event too — same per-event grant, via the Speaker.user link.
        return self.speakers.filter(user=user).exists()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest events/test_faculty_views.py -k "linked_external_speaker" -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add events/models.py events/test_faculty_views.py
git commit -m "feat(events): linked external speakers get per-event presenter access (task #463)"
```

---

### Task 3: `SpeakerInvitation` token model

**Files:**
- Modify: `events/models.py` (add a token generator + the model; near the other event models)
- Create: `events/migrations/00NN_speakerinvitation.py` (via makemigrations)
- Modify: `events/admin.py` (register, read-only)
- Test: `events/test_speaker_invitations.py` (create)

**Interfaces:**
- Produces:
  - `events.models.SpeakerInvitation(speaker FK, user FK related_name="speaker_invitations", token, created_at, expires_at, used_at)`
  - `SpeakerInvitation.DEFAULT_TTL = timedelta(days=30)`
  - `.is_expired(now=None) -> bool`, `.is_valid -> bool` (property), `.consume() -> None`
  - `.refresh(expires_at=None) -> None` (new token + reset expiry/used)

- [ ] **Step 1: Write the failing tests**

Create `events/test_speaker_invitations.py`:

```python
"""External-speaker invitation token (task #463)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from events.models import Event, Speaker, SpeakerInvitation

pytestmark = pytest.mark.django_db


def _speaker_with_user(email="d@x.test"):
    u = User.objects.create_user(email=email)
    s = Speaker.objects.create(name="Derek Hook", slug="dh-inv", email=email, user=u)
    return s, u


def test_invitation_is_valid_until_expiry_and_use():
    s, u = _speaker_with_user()
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() + timedelta(days=10)
    )
    assert inv.token
    assert inv.is_valid is True
    inv.consume()
    assert inv.used_at is not None
    assert inv.is_valid is False


def test_invitation_expired_is_invalid():
    s, u = _speaker_with_user("e@x.test")
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert inv.is_expired() is True
    assert inv.is_valid is False


def test_refresh_issues_new_token_and_clears_use():
    s, u = _speaker_with_user("f@x.test")
    inv = SpeakerInvitation.objects.create(
        speaker=s, user=u, expires_at=timezone.now() - timedelta(days=1)
    )
    old = inv.token
    inv.consume()
    inv.refresh()
    assert inv.token != old
    assert inv.used_at is None
    assert inv.is_valid is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/test_speaker_invitations.py -v`
Expected: ImportError — `SpeakerInvitation` does not exist.

- [ ] **Step 3: Add the token generator + model**

In `events/models.py`, near the top-level helpers add:

```python
import secrets  # (add near the other stdlib imports if not present)


def _speaker_invitation_token() -> str:
    """Opaque, single-use token for an external-speaker invitation link."""
    return secrets.token_urlsafe(32)
```

Then add the model (after the `Speaker` class or near `EventMemberSpeaker`):

```python
class SpeakerInvitation(models.Model):
    """A pending invitation for an external speaker to activate a login.

    Own token (not Django's password reset, which silently skips
    unusable-password accounts — memory ``auth-email-scanner-and-reset-gotchas``).
    Opaque + single-use; a generous expiry (default 30 days) so an invitation
    sent well before the event still works. Refreshing supersedes the prior link.
    """

    DEFAULT_TTL = timedelta(days=30)

    speaker = models.ForeignKey(
        "events.Speaker", on_delete=models.CASCADE, related_name="invitations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="speaker_invitations",
    )
    token = models.CharField(
        max_length=64, unique=True, default=_speaker_invitation_token, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        state = "used" if self.used_at else ("expired" if self.is_expired() else "pending")
        return f"invite {self.speaker.name} ({state})"

    def is_expired(self, now=None) -> bool:
        return (now or timezone.now()) > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and not self.is_expired()

    def consume(self) -> None:
        if self.used_at is None:
            self.used_at = timezone.now()
            self.save(update_fields=["used_at"])

    def refresh(self, expires_at=None) -> None:
        self.token = _speaker_invitation_token()
        self.used_at = None
        self.expires_at = expires_at or (timezone.now() + self.DEFAULT_TTL)
        self.save(update_fields=["token", "used_at", "expires_at"])
```

Ensure `from datetime import timedelta` (or `timedelta` import) is available in `events/models.py`; it uses `_dt`/`datetime` already — add `from datetime import timedelta` at top if not present.

- [ ] **Step 4: Make + apply the migration**

Run: `uv run python manage.py makemigrations events && uv run python manage.py migrate`
Expected: new migration creating `SpeakerInvitation`.

- [ ] **Step 5: Register (read-only) in admin**

In `events/admin.py` add:

```python
@admin.register(SpeakerInvitation)
class SpeakerInvitationAdmin(admin.ModelAdmin):
    list_display = ("speaker", "user", "created_at", "expires_at", "used_at")
    readonly_fields = ("token", "created_at")
    autocomplete_fields = ("speaker", "user")
```

Add `SpeakerInvitation` to the import at the top of `events/admin.py`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest events/test_speaker_invitations.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add events/models.py events/admin.py events/migrations/ events/test_speaker_invitations.py
git commit -m "feat(events): SpeakerInvitation token model (task #463)"
```

---

### Task 4: Provision/link + send service and email

**Files:**
- Create: `events/speaker_invitations.py` (service + email)
- Create: `events/templates/events/email/speaker_invitation.txt`
- Test: `events/test_speaker_invitations.py` (append)

**Interfaces:**
- Consumes: `SpeakerInvitation` (Task 3), `Speaker.user` (Task 1), `core.email.school_from`? (not required — use `settings.DEFAULT_FROM_EMAIL` like `accounts/emails.py`).
- Produces:
  - `events.speaker_invitations.default_invitation_message(speaker, event) -> str`
  - `events.speaker_invitations.provision_login(speaker) -> User` (create-or-link, idempotent)
  - `events.speaker_invitations.send_invitation(speaker, event, message: str) -> SpeakerInvitation`

- [ ] **Step 1: Write the failing tests**

Append to `events/test_speaker_invitations.py`:

```python
from django.core import mail

from accounts.models import Profile


def _special_event(slug="inv-talk"):
    return Event.objects.create(
        title="Working with Masochism", slug=slug,
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 6), end_date=date(2030, 9, 6),
        published=True, status=Event.Status.OPEN,
    )


def test_provision_login_creates_external_user():
    from events.speaker_invitations import provision_login
    s = Speaker.objects.create(name="Derek Hook", slug="dh-prov", email="derek@x.test")
    u = provision_login(s)
    s.refresh_from_db()
    assert s.user == u
    assert u.email == "derek@x.test"
    assert u.profile.role == Profile.Role.EXTERNAL
    assert u.profile.public is False
    assert u.has_usable_password() is False
    assert u.first_name == "Derek" and u.last_name == "Hook"


def test_provision_login_links_existing_user_not_duplicate():
    from events.speaker_invitations import provision_login
    existing = User.objects.create_user(email="dup@x.test", first_name="Dup")
    s = Speaker.objects.create(name="Dup Person", slug="dup-p", email="dup@x.test")
    u = provision_login(s)
    assert u == existing
    assert User.objects.filter(email="dup@x.test").count() == 1


def test_send_invitation_creates_token_and_sends_one_email():
    from events.speaker_invitations import send_invitation
    e = _special_event()
    s = Speaker.objects.create(name="Derek Hook", slug="dh-send", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="Looking forward to it.")
    assert inv.is_valid
    assert inv.user.email == "derek@x.test"
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert inv.token in body            # activation link present
    assert "Looking forward to it." in body   # custom message included
    assert mail.outbox[0].to == ["derek@x.test"]


def test_send_invitation_resend_refreshes_token():
    from events.speaker_invitations import send_invitation
    e = _special_event("inv-talk-2")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-resend", email="derek@x.test")
    e.speakers.add(s)
    inv1 = send_invitation(s, e, message="first")
    t1 = inv1.token
    inv2 = send_invitation(s, e, message="second")
    assert inv2.pk == inv1.pk           # same invitation row, refreshed
    assert inv2.token != t1
    assert len(mail.outbox) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/test_speaker_invitations.py -k "provision or send_invitation" -v`
Expected: ImportError — `events.speaker_invitations` does not exist.

- [ ] **Step 3: Create the email template**

Create `events/templates/events/email/speaker_invitation.txt`:

```
Dear {{ speaker.name }},

{{ message }}

To get set up, please activate your account and choose a password:

{{ activation_url }}

Joining the meeting is simple. Once you have signed in, open the event page:

{{ event_url }}

You will find the meeting room right there, no separate link needed. When the
event begins, a Join button appears on that page, that is where you and the
attendees join. Attendees join the same way, they register and the button
appears for them when the event starts, so if anyone asks how to join you can
point them to that page.

If you have any questions, reply to this email or contact us at {{ support_email }}.

Warm regards,
The Lacanian School of Psychoanalysis
```

- [ ] **Step 4: Create the service module**

Create `events/speaker_invitations.py`:

```python
"""External-speaker invitation: provision-or-link a login, mint a token, send
the invitation email (task #463). Kept separate from the event views so the
provisioning logic is testable in isolation."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.models import Profile, User

from .models import Speaker, SpeakerInvitation


def _split_name(name: str) -> tuple[str, str]:
    name = (name or "").strip()
    if " " in name:
        first, last = name.rsplit(" ", 1)
        return first, last
    return name, ""


def default_invitation_message(speaker: Speaker, event) -> str:
    """The pre-filled, editable note the PC sees in the confirm panel."""
    return (
        f"You are warmly invited to present at {event.title}. We use our own "
        "in-site video meeting for the event, so we would like to set you up "
        "with a login here on the Lacanian School website."
    )


def provision_login(speaker: Speaker) -> User:
    """Return the login for this external speaker, creating one if needed.

    Idempotent: links an existing user with the speaker's email rather than
    duplicating. New users are external (off the directory), non-public, with an
    unusable password until they activate via the invitation token.
    """
    if speaker.user_id:
        return speaker.user
    email = (speaker.email or "").strip().lower()
    if not email:
        raise ValueError("Speaker has no email to invite.")
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        first, last = _split_name(speaker.name)
        user = User.objects.create_user(
            email=email, first_name=first, last_name=last,
        )
        # New login: keep it off the directory and unusable until activation.
        user.set_unusable_password()
        user.save(update_fields=["password"])
        profile = user.profile
        profile.role = Profile.Role.EXTERNAL
        profile.public = False
        profile.save(update_fields=["role", "public"])
    speaker.user = user
    speaker.save(update_fields=["user"])
    return user


def send_invitation(speaker: Speaker, event, message: str) -> SpeakerInvitation:
    """Provision-or-link the login, mint/refresh the token, send the email."""
    user = provision_login(speaker)
    inv = SpeakerInvitation.objects.filter(speaker=speaker, user=user).first()
    if inv is None:
        from django.utils import timezone
        inv = SpeakerInvitation.objects.create(
            speaker=speaker, user=user,
            expires_at=timezone.now() + SpeakerInvitation.DEFAULT_TTL,
        )
    else:
        inv.refresh()
    base = settings.SITE_BASE_URL.rstrip("/")
    activation_url = base + reverse("events:speaker_invitation_accept", args=[inv.token])
    event_url = base + reverse("events:detail", args=[event.slug])
    body = render_to_string("events/email/speaker_invitation.txt", {
        "speaker": speaker,
        "event": event,
        "message": message,
        "activation_url": activation_url,
        "event_url": event_url,
        "support_email": settings.SUPPORT_EMAIL,
    })
    EmailMessage(
        subject=f"Invitation to present at {event.title}",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[settings.SUPPORT_EMAIL],
    ).send(fail_silently=False)
    return inv
```

Note: `reverse("events:speaker_invitation_accept", ...)` is wired in Task 6. Until then the send tests will error on `NoReverseMatch` — so **run Task 4's tests after Task 6's URL exists**, or add the URL now. To keep tasks independently testable, add the URL + a stub view in this task's Step 5.

- [ ] **Step 5: Add the URL now (view arrives in Task 6)**

The `events:` namespace lives in `events/urls.py` (`app_name = "events"`, included at
`events/` in `config/urls.py:143`). The `detail` route is `<slug:slug>/`, a
**catch-all** — so any fixed-path route MUST be listed BEFORE it or the slug
converter swallows it. Register the accept route at the TOP of `urlpatterns` in
`events/urls.py` (its name resolves for `reverse` even before the view is real):

```python
urlpatterns = [
    path("speakers/invitation/<str:token>/",
         views.speaker_invitation_accept, name="speaker_invitation_accept"),
    path("", views.event_list, name="list"),
    path("<slug:slug>/", views.event_detail, name="detail"),
    # ... the rest unchanged ...
]
```

Add a minimal placeholder in `events/views.py` so the import resolves:

```python
def speaker_invitation_accept(request, token):  # fleshed out in Task 6
    raise Http404()
```

(`Http404` is already imported in `events/views.py`.) Full activation URL becomes
`/events/speakers/invitation/<token>/`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest events/test_speaker_invitations.py -v`
Expected: all PASS (outbox has the email; token + message in body).

- [ ] **Step 7: Commit**

```bash
git add events/speaker_invitations.py events/templates/events/email/speaker_invitation.txt events/views.py events/urls.py events/test_speaker_invitations.py
git commit -m "feat(events): external-speaker invitation service + email (task #463)"
```

---

### Task 5: Invite panel + send view on the event edit page

**Files:**
- Modify: `events/views.py` (`event_edit` GET context; new `speaker_invite` view)
- Modify: `events/templates/events/event_edit.html` (add the panel section)
- Modify: `config/urls.py` (add the send route)
- Test: `events/test_speaker_invitations.py` (append)

**Interfaces:**
- Consumes: `events.speaker_invitations.send_invitation` / `default_invitation_message` (Task 4), `can_edit_event`.
- Produces:
  - `events.views.speaker_invite(request, slug, speaker_id)` (POST only) → sends, redirects to `events:edit`.
  - `event_edit` GET context key `speaker_invites`: list of `{speaker, status, default_message}` where `status` ∈ `{"ready", "invited", "active"}`.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_speaker_invitations.py`:

```python
from django.urls import reverse as _reverse

from committees.models import Committee


def _pc_user():
    u = User.objects.create_user(email="pc@x.test")
    Committee.objects.get_or_create(
        slug="programming-committee", defaults={"name": "Programming Committee"}
    )[0].add_member(u, start_date=date(2026, 1, 1))
    return u


def test_edit_page_shows_ready_to_invite_panel(client):
    e = _special_event("panel-1")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-panel", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.get(_reverse("events:edit", args=[e.slug]))
    assert b"Ready to invite" in resp.content
    assert b"Derek Hook" in resp.content


def test_no_email_speaker_gets_no_panel(client):
    e = _special_event("panel-2")
    s = Speaker.objects.create(name="No Email", slug="no-email")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.get(_reverse("events:edit", args=[e.slug]))
    assert b"Ready to invite" not in resp.content


def test_confirm_send_invites(client):
    e = _special_event("panel-3")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-send2", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(_pc_user())
    resp = client.post(
        _reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "Please join us."}, follow=True,
    )
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.user is not None
    assert len(mail.outbox) == 1


def test_speaker_invite_forbidden_for_non_pc(client):
    e = _special_event("panel-4")
    s = Speaker.objects.create(name="Derek", slug="dh-forbid", email="derek@x.test")
    e.speakers.add(s)
    client.force_login(User.objects.create_user(email="rando@x.test"))
    resp = client.post(
        _reverse("events:speaker_invite", args=[e.slug, s.pk]),
        {"message": "x"},
    )
    assert resp.status_code == 403
    s.refresh_from_db()
    assert s.user is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/test_speaker_invitations.py -k "panel or confirm_send or forbidden" -v`
Expected: FAIL — no `events:speaker_invite` route / no panel markup.

- [ ] **Step 3: Add the send view + edit-page context**

In `events/views.py`, add:

```python
@login_required
@require_POST
def speaker_invite(request, slug, speaker_id):
    """PC/staff confirm-and-send an external-speaker invitation (task #463)."""
    from .models import Speaker
    from .speaker_invitations import send_invitation

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to invite speakers.")
    speaker = get_object_or_404(Speaker, pk=speaker_id, events=event)
    if not (speaker.email or "").strip():
        messages.error(request, f"{speaker.name} has no email to invite.")
        return redirect("events:edit", slug=event.slug)
    message = request.POST.get("message", "").strip()
    send_invitation(speaker, event, message)
    messages.success(request, f"Invitation sent to {speaker.name} ({speaker.email}).")
    return redirect("events:edit", slug=event.slug)


def _speaker_invite_rows(event):
    """Per-speaker invite state for the edit page."""
    from .speaker_invitations import default_invitation_message
    rows = []
    for s in event.speakers.all().select_related("user"):
        if not (s.email or "").strip():
            continue
        if s.user_id and s.user.has_usable_password():
            status = "active"
        elif s.user_id and s.invitations.filter(used_at__isnull=True).exists():
            status = "invited"
        elif s.user_id:
            status = "invited"   # provisioned; awaiting activation
        else:
            status = "ready"
        rows.append({
            "speaker": s,
            "status": status,
            "default_message": default_invitation_message(s, event),
        })
    return rows
```

Then in `event_edit`, the GET branch (~line 326-330), add the rows to context:

```python
    if request.method != "POST":
        form = EventDescriptionForm(instance=event)
        return render(request, "events/event_edit.html", {
            "event": event, "form": form,
            "speaker_invites": _speaker_invite_rows(event),
            **_schedule_editor_context(event),
        })
```

(`require_POST`, `messages`, `get_object_or_404`, `HttpResponseForbidden`, `redirect`, `can_edit_event` are all already imported in `events/views.py`.)

- [ ] **Step 4: Add the panel to the template**

In `events/templates/events/event_edit.html`, before the closing `</div>` of the `max-w-2xl` wrapper (after the edit `<form>`), add:

```html
  {% if speaker_invites %}
  <section class="space-y-3 border-t border-base-300/60 pt-6">
    <h2 class="font-serif text-lg text-base-content">External speakers</h2>
    {% for row in speaker_invites %}
    <div class="rounded-lg border border-base-300 p-3 space-y-2">
      <div class="flex items-center justify-between gap-2">
        <span class="font-medium text-base-content">{{ row.speaker.name }}</span>
        {% if row.status == "ready" %}
        <span class="badge badge-warning badge-sm">Ready to invite</span>
        {% elif row.status == "invited" %}
        <span class="badge badge-outline badge-sm">Invited, awaiting sign-in</span>
        {% else %}
        <span class="badge badge-success badge-sm">Active</span>
        {% endif %}
      </div>
      <p class="text-xs text-base-content/60">{{ row.speaker.email }}</p>
      {% if row.status != "active" %}
      <form method="post" action="{% url 'events:speaker_invite' event.slug row.speaker.pk %}" class="space-y-2">
        {% csrf_token %}
        <textarea name="message" rows="3" class="textarea textarea-bordered w-full text-sm">{{ row.default_message }}</textarea>
        <button type="submit" class="btn btn-primary btn-sm">
          {% if row.status == "invited" %}Resend invitation{% else %}Confirm &amp; send invitation{% endif %}
        </button>
      </form>
      {% endif %}
    </div>
    {% endfor %}
  </section>
  {% endif %}
```

- [ ] **Step 5: Add the URL**

In `events/urls.py`. This path starts with a slug, so it does NOT collide with the
`<slug:slug>/` detail catch-all only because it's more specific (longer prefix
match) — but to be safe, place it BEFORE the `<slug:slug>/` detail route too:

```python
    path("<slug:slug>/speakers/<int:speaker_id>/invite/",
         views.speaker_invite, name="speaker_invite"),
```

Order in `urlpatterns`: `speaker_invitation_accept` (Task 4), `list`, then
`speaker_invite`, then `detail` (`<slug:slug>/`), then the rest. Django matches
top-to-bottom, and `<slug:slug>/speakers/<int>/invite/` has extra path segments
the bare `<slug:slug>/` can't match, but keeping it above `detail` avoids any
ambiguity.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest events/test_speaker_invitations.py -k "panel or confirm_send or forbidden" -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add events/views.py events/templates/events/event_edit.html events/urls.py events/test_speaker_invitations.py
git commit -m "feat(events): PC invite panel + send action on the event edit page (task #463)"
```

---

### Task 6: Invitation accept (set-password) landing + login

**Files:**
- Modify: `events/views.py` (flesh out `speaker_invitation_accept`)
- Create: `events/templates/events/speaker_invitation_accept.html`
- Create: `events/templates/events/speaker_invitation_invalid.html`
- Test: `events/test_speaker_invitations.py` (append)

**Interfaces:**
- Consumes: `SpeakerInvitation` (Task 3), `django.contrib.auth.forms.SetPasswordForm`, `django.contrib.auth.login`.
- Produces: `events.views.speaker_invitation_accept(request, token)` — GET renders the set-password form; POST sets the password, consumes the token, logs in, redirects to the event page.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_speaker_invitations.py`:

```python
def test_accept_sets_password_and_logs_in(client):
    from events.speaker_invitations import send_invitation
    e = _special_event("accept-1")
    s = Speaker.objects.create(name="Derek Hook", slug="dh-accept", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="hi")
    url = _reverse("events:speaker_invitation_accept", args=[inv.token])
    # GET shows the form, does NOT consume (scanner-safe).
    assert client.get(url).status_code == 200
    inv.refresh_from_db()
    assert inv.used_at is None
    # POST sets the password, consumes, logs in, redirects to the event.
    resp = client.post(url, {"new_password1": "Sw0rdfish!42", "new_password2": "Sw0rdfish!42"})
    assert resp.status_code == 302
    assert resp.url == _reverse("events:detail", args=[e.slug])
    inv.refresh_from_db()
    assert inv.used_at is not None
    inv.user.refresh_from_db()
    assert inv.user.has_usable_password() is True
    # They can now enter the room.
    from video.services import can_enter_event
    assert can_enter_event(e, inv.user) is True


def test_accept_rejects_expired_token(client):
    from events.speaker_invitations import send_invitation
    e = _special_event("accept-2")
    s = Speaker.objects.create(name="Derek", slug="dh-exp", email="derek@x.test")
    e.speakers.add(s)
    inv = send_invitation(s, e, message="hi")
    inv.expires_at = timezone.now() - timedelta(minutes=1)
    inv.save(update_fields=["expires_at"])
    resp = client.get(_reverse("events:speaker_invitation_accept", args=[inv.token]))
    assert resp.status_code == 410


def test_accept_rejects_unknown_token(client):
    resp = client.get(_reverse("events:speaker_invitation_accept", args=["nope"]))
    assert resp.status_code == 410
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest events/test_speaker_invitations.py -k "accept" -v`
Expected: FAIL — the view raises Http404 (placeholder).

- [ ] **Step 3: Flesh out the view**

Replace the placeholder `speaker_invitation_accept` in `events/views.py`:

```python
def speaker_invitation_accept(request, token):
    """Activate an invited external-speaker login: set a password, sign in, and
    land on the event page (task #463).

    Consumption happens only on the POST that sets the password, so email
    security scanners that GET-prefetch the link can't burn it
    (memory ``auth-email-scanner-and-reset-gotchas``).
    """
    from django.contrib.auth import login
    from django.contrib.auth.forms import SetPasswordForm

    from .models import SpeakerInvitation

    inv = (
        SpeakerInvitation.objects
        .filter(token=token)
        .select_related("user", "speaker")
        .first()
    )
    if inv is None or not inv.is_valid or not inv.user.is_active:
        return render(request, "events/speaker_invitation_invalid.html", status=410)

    event = inv.speaker.events.order_by("start_date").first()
    if request.method == "POST":
        form = SetPasswordForm(inv.user, request.POST)
        if form.is_valid():
            form.save()
            inv.consume()
            login(request, inv.user)
            if event is not None:
                return redirect("events:detail", slug=event.slug)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = SetPasswordForm(inv.user)
    return render(request, "events/speaker_invitation_accept.html", {
        "form": form, "invitation": inv, "event": event,
    })
```

(`render`, `redirect`, `settings` already imported in `events/views.py`.)

- [ ] **Step 4: Create the templates**

Create `events/templates/events/speaker_invitation_accept.html`:

```html
{% extends "core/base.html" %}
{% block title %}Activate your account · LSP{% endblock %}
{% block content %}
<div class="max-w-md mx-auto space-y-6">
  <header class="space-y-1">
    <h1 class="font-serif text-2xl text-base-content">Welcome{% if invitation %}, {{ invitation.speaker.name }}{% endif %}</h1>
    <p class="text-sm text-base-content/70">
      Choose a password to activate your account{% if event %} for {{ event.title }}{% endif %}.
      After signing in you'll land on the event page, where you can open the
      meeting room when the event begins.
    </p>
  </header>
  <form method="post" class="space-y-4">
    {% csrf_token %}
    {% for field in form %}
    <div class="form-control space-y-1">
      <label class="label-text" for="{{ field.id_for_label }}">{{ field.label }}</label>
      {{ field }}
      {% if field.errors %}<p class="text-xs text-error">{{ field.errors|join:", " }}</p>{% endif %}
      {% if field.help_text %}<p class="text-xs text-base-content/50">{{ field.help_text|safe }}</p>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn btn-primary">Set password &amp; sign in</button>
  </form>
</div>
{% endblock %}
```

Create `events/templates/events/speaker_invitation_invalid.html`:

```html
{% extends "core/base.html" %}
{% block title %}Invitation link · LSP{% endblock %}
{% block content %}
<div class="max-w-md mx-auto space-y-3">
  <h1 class="font-serif text-2xl text-base-content">This invitation link isn't valid</h1>
  <p class="text-sm text-base-content/70">
    It may have expired or already been used. Please contact us and we'll send a
    fresh invitation.
  </p>
</div>
{% endblock %}
```

The set-password fields need DaisyUI classes for consistency; the default widgets render as plain inputs. That's acceptable (matches the password-reset-confirm page's approach); no Tailwind-in-Python concern.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest events/test_speaker_invitations.py -k "accept" -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add events/views.py events/templates/events/speaker_invitation_accept.html events/templates/events/speaker_invitation_invalid.html events/test_speaker_invitations.py
git commit -m "feat(events): external-speaker invitation set-password landing (task #463)"
```

---

### Task 7: Full-suite green + lint

**Files:** none (verification only)

- [ ] **Step 1: Lint**

Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 2: Full test suite**

Run: `uv run pytest -q -n auto`
Expected: all pass (no regressions).

- [ ] **Step 3: Fix any template-lint failure**

If `core/test_templates.py::test_no_multiline_hash_comments_in_templates` fails, convert any multi-line `{# #}` to `{% comment %}…{% endcomment %}` (this repo forbids multi-line `{# #}`).

- [ ] **Step 4: Commit (only if fixes were needed)**

```bash
git add -A && git commit -m "test(events): keep suite + lint green for external-speaker work (task #463)"
```

---

## Self-Review

**Spec coverage:**
- Part 1 `Speaker.user` → Task 1. `is_presenter` recognizes link → Task 2. `role=EXTERNAL`/`public=False`/off-directory → Task 4 (`provision_login`) + Task 2 (directory test).
- Part 2 token → Task 3. Provision-or-link + email → Task 4. Prepare-on-add/confirm panel on edit page → Task 5. Set-password landing + login + redirect → Task 6. Editable body → Task 5 (textarea) + Task 4 (`message` into template). PC/staff-only → Task 5 (403) + Task 6 (410 for bad token). Scanner-safe consumption → Task 6 (GET doesn't consume).
- Testing section of the spec → covered across Tasks 2, 4, 5, 6.

**Placeholder scan:** The Task 4 stub view is intentional and replaced in Task 6; every other step ships real code. No TBD/TODO.

**Type consistency:** `send_invitation(speaker, event, message)`, `provision_login(speaker)`, `default_invitation_message(speaker, event)`, `SpeakerInvitation.is_valid` (property), `.consume()`, `.refresh()`, `_speaker_invite_rows(event)` returning `{speaker,status,default_message}`, route names `events:speaker_invite` / `events:speaker_invitation_accept` — all consistent across tasks.

**Deferred (Part 3):** speaker spotlight — not in this plan.
