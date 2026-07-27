# Direct Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Web Coordinator admit a member who never applied on the site — creating the account and running the same admission the application path runs — from one form.

**Architecture:** A shared `admissions.services.admit_member()` holds what acceptance *means* (membership change + formation background); `accept_application()` is refactored onto it, and a new Web-Coordinator-gated form calls it directly. The form creates the `User`, then sends one of three things: the existing `decision_accept` letter, a new account-ready invitation, or nothing.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5 templates.

**Spec:** `docs/superpowers/specs/2026-07-27-direct-admission-design.md`

## Global Constraints

- The direct-admission surface lives in the **Web Coordinator's** admin (`/admin-tools/web-coordinator/admit/`), gated by `staff_role_required(StaffRole.WEB_COORDINATOR)`. It must NOT appear in the Applications Coordinator's console, and the account-ready message must NOT become an `admissions.MessageTemplate` key — `coordinator.messages_list` iterates `MessageTemplate.Key.values`, so a new key would surface in that console's Messages tab. (This amends §4 of the spec, which proposed a `MessageTemplate` key.)
- Site copy uses **commas, not em dashes** (member-facing copy convention). Code comments and docs use unspaced em dashes.
- Templates use DaisyUI semantic tokens (`bg-base-100`, `text-base-content`, `text-primary`), never hardcoded colors.
- Tailwind v4 scans templates only: any CSS class set in Python must also appear in an `.html` file.
- Run `uv run pytest <paths>` for tests and `uv run ruff check .` before each commit.
- This worktree is `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/nimble-meadow`. Edit files there, never in the main repo path.

---

### Task 1: The shared `admit_member()` service

**Files:**
- Modify: `admissions/services.py` (add `admit_member`, refactor `accept_application` at the bottom of the file)
- Test: `admissions/test_direct_admit.py` (create)

**Interfaces:**
- Consumes: `accounts.membership.record_membership_change`, `accounts.membership.current_academic_year_start`, `formation.background.set_background`, `admissions.models.Application.ADMIT_ROLE`.
- Produces:
  ```python
  admit_member(member, *, track, formation_background="", effective_ay=None,
               by, tenure_note="", background_note="") -> MembershipTenure
  ```
  `track` is an `Application.Track` value (`"analyst"` / `"scholar"`).
  `formation_background` is a `Profile.FormationBackground` value or `""` (empty leaves the member unreviewed and calls `set_background` not at all).

- [ ] **Step 1: Write the failing test**

Create `admissions/test_direct_admit.py`:

```python
"""Direct admission — admitting a member who never applied on the site (#476)."""

from __future__ import annotations

import pytest

from accounts.models import MembershipTenure, Profile, User
from admissions.models import Application
from admissions.services import admit_member
from core.models import StaffRole

pytestmark = pytest.mark.django_db


def _user(email, **kw):
    return User.objects.create_user(email=email, password="x", **kw)


@pytest.fixture
def actor():
    return _user("wc@x.test", first_name="Web", last_name="Coordinator")


def test_admit_member_sets_role_standing_and_tenure(actor):
    member = _user("new@x.test", first_name="Nadia", last_name="New")

    admit_member(
        member, track=Application.Track.ANALYST,
        formation_background=Profile.FormationBackground.CLINICAL,
        effective_ay=2026, by=actor, tenure_note="Admitted directly.",
        background_note="Set at direct admission.",
    )

    member.refresh_from_db()
    assert member.profile.role == Profile.Role.PRE_CANDIDATE
    assert member.profile.standing == Profile.Standing.ACTIVE
    assert member.profile.formation_background == Profile.FormationBackground.CLINICAL
    tenure = MembershipTenure.open_for(member)
    assert tenure.start_ay == 2026
    assert "Admitted directly." in tenure.notes


def test_admit_member_scholar_track_admits_as_scholar_precandidate(actor):
    member = _user("scholar@x.test")

    admit_member(member, track=Application.Track.SCHOLAR, by=actor)

    member.refresh_from_db()
    assert member.profile.role == Profile.Role.PRE_CANDIDATE_SCHOLAR


def test_admit_member_leaves_background_unreviewed_when_blank(actor):
    member = _user("unknown-bg@x.test")

    admit_member(member, track=Application.Track.ANALYST,
                 formation_background="", by=actor)

    member.refresh_from_db()
    assert (member.profile.formation_background
            == Profile.FormationBackground.UNREVIEWED)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest admissions/test_direct_admit.py -q`
Expected: FAIL — `ImportError: cannot import name 'admit_member' from 'admissions.services'`

- [ ] **Step 3: Add `admit_member` to `admissions/services.py`**

Insert immediately above the existing `accept_application` definition:

```python
# ---- Admission: the shared chokepoint -----------------------------------


@transaction.atomic
def admit_member(
    member, *, track, formation_background="", effective_ay=None, by,
    tenure_note="", background_note="",
):
    """Admit ``member`` as ``track``'s Precandidate — the membership change plus
    the formation background, and nothing route-specific.

    Shared by both admission routes: acceptance of a site application
    (:func:`accept_application`) and direct admission by the Web Coordinator
    (``admissions.direct_admit``). Keeping one function means the two cannot
    drift — a member admitted either way lands in the same state.

    ``formation_background`` is a ``Profile.FormationBackground`` value, or ""
    to leave the member unreviewed (the Meeting of Analysts determines it
    later). Returns the open ``MembershipTenure``.
    """
    effective_ay = effective_ay or current_academic_year_start()
    tenure = record_membership_change(
        member,
        role=Application.ADMIT_ROLE[track],
        standing=Profile.Standing.ACTIVE,
        effective_ay=effective_ay,
        notes=tenure_note,
        by=by,
    )
    if formation_background:
        from formation.background import set_background

        set_background(member, formation_background, by=by, note=background_note)
    return tenure
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest admissions/test_direct_admit.py -q`
Expected: 3 passed

- [ ] **Step 5: Refactor `accept_application` onto the shared service**

Replace the body of `accept_application` (keep the decorator and signature) with:

```python
@transaction.atomic
def accept_application(application: Application, *, by, effective_ay=None, note=""):
    """Accept an application: admit the applicant as the track's Precandidate
    (active standing) and mark the application accepted. Emails the applicant."""
    background = (
        Profile.FormationBackground.CLINICAL
        if application.background == Application.Background.CLINICAL
        else Profile.FormationBackground.ACADEMIC
    )
    admit_member(
        application.applicant,
        track=application.track,
        formation_background=background,
        effective_ay=effective_ay,
        by=by,
        tenure_note=(
            f"Admitted via application ({application.get_track_display()}). {note}"
        ).strip(),
        background_note="Set at acceptance from the application.",
    )
    application.status = Application.Status.ACCEPTED
    application.decided_at = timezone.now()
    application.decided_by = by
    application.decision_note = note
    application.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])
    notify_admissions.application_decision(application)
    return application
```

Note the pre-existing behaviour this preserves exactly: a blank `application.background` (the scholar track never collects one) maps to ACADEMIC, not to unreviewed.

- [ ] **Step 6: Verify the whole admissions suite still passes**

Run: `uv run pytest admissions/ -q`
Expected: all pass (the existing acceptance tests in `admissions/tests.py` and `test_coordinator.py` cover the refactored path)

- [ ] **Step 7: Add the equivalence test**

Append to `admissions/test_direct_admit.py`:

```python
def test_both_routes_produce_the_same_membership_state(actor):
    """The whole point of the shared service: a member admitted directly and an
    applicant accepted through the site land in identical state."""
    from admissions.services import accept_application

    direct = _user("direct@x.test")
    admit_member(
        direct, track=Application.Track.ANALYST,
        formation_background=Profile.FormationBackground.CLINICAL,
        effective_ay=2026, by=actor,
    )

    applicant = _user("applied@x.test")
    application = Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        background=Application.Background.CLINICAL,
        letter_of_intent="I would like to join.",
    )
    accept_application(application, by=actor, effective_ay=2026)

    for user in (direct, applicant):
        user.refresh_from_db()
    assert direct.profile.role == applicant.profile.role
    assert direct.profile.standing == applicant.profile.standing
    assert direct.profile.formation_background == applicant.profile.formation_background
    assert (MembershipTenure.open_for(direct).start_ay
            == MembershipTenure.open_for(applicant).start_ay)
```

- [ ] **Step 8: Run it**

Run: `uv run pytest admissions/test_direct_admit.py -q`
Expected: 4 passed

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check . && git add admissions/services.py admissions/test_direct_admit.py && git commit -m "feat: shared admit_member() service behind both admission routes (#476)"
```

---

### Task 2: Render the acceptance letter without an `Application`

**Files:**
- Modify: `admissions/emails.py:107-179` (`_formation_label`, `_guidelines_url`, `_applicant_context`, add `send_direct_acceptance`)
- Test: `admissions/test_direct_admit.py`

**Interfaces:**
- Consumes: `admissions.models.MessageTemplate`, `admissions.services.render_template`.
- Produces: `send_direct_acceptance(member, *, track, background="", note="") -> None` — sends the `decision_accept` template to a member admitted with no application. `background` is an `Application.Background` value or `""`.

- [ ] **Step 1: Write the failing test**

Append to `admissions/test_direct_admit.py`:

```python
def test_direct_acceptance_letter_renders_without_an_application():
    from django.core import mail

    from admissions.emails import send_direct_acceptance

    member = _user("cold@x.test", first_name="Cold", last_name="Admit")
    send_direct_acceptance(
        member, track=Application.Track.ANALYST,
        background=Application.Background.CLINICAL, note="Welcome aboard.",
    )

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Cold" in body
    assert "Analyst formation, Clinical" in body
    assert "Welcome aboard." in body
    # No leftover placeholders, and no fabricated application-status link.
    assert "{" not in body
    assert "/apply/status" not in body
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest admissions/test_direct_admit.py -q -k direct_acceptance`
Expected: FAIL — `ImportError: cannot import name 'send_direct_acceptance'`

- [ ] **Step 3: Refactor the context builder in `admissions/emails.py`**

Replace `_formation_label`, `_guidelines_url`, and `_applicant_context` with member-keyed versions plus thin application wrappers:

```python
def _formation_label(track: str, background: str = "") -> str:
    """e.g. 'Analyst formation, Clinical' — track plus background where given."""
    label = Application.Track(track).label
    if background:
        # "Clinical background" -> "Clinical"
        label += f", {Application.Background(background).label.replace(' background', '')}"
    return label


def _guidelines_url(track: str) -> str:
    """The track's Formation Guidelines document (advisor/advisee
    responsibilities) — Scholar for the scholar track, else Analyst. Falls back
    to the documents index if the document isn't found."""
    from documents.models import Document

    label = "Scholar" if track == Application.Track.SCHOLAR else "Analyst"
    doc = Document.objects.filter(
        title__icontains=f"{label} Formation Guidelines"
    ).first()
    return _absolute("documents:detail", doc.slug) if doc else _absolute("documents:index")


def _member_context(member, *, track: str, background: str = "") -> dict:
    """Letter context for someone being admitted, keyed on the person and their
    track rather than on an ``Application`` — so the same acceptance letter
    renders for a direct admission, which has no application row."""
    from availability.emails import applications_coordinator_name
    return {
        "name": member.get_full_name() or member.email,
        "track": Application.Track(track).label,
        "formation": _formation_label(track, background),
        # Pre-sorted to analysts available to advise.
        "availability_url": _absolute("directory_availability") + "?only=advisor",
        "guidelines_url": _guidelines_url(track),
        "documents_url": _absolute("documents:index"),
        "profile_url": _absolute("profile_edit"),
        "mylsp_url": _absolute("formation:formation"),
        "applications_coordinator": applications_coordinator_name(),
    }


def _applicant_context(application: Application) -> dict:
    """``_member_context`` plus the application-only status link."""
    return {
        **_member_context(
            application.applicant,
            track=application.track,
            background=application.background,
        ),
        "status_url": _absolute("admissions:status"),
    }
```

- [ ] **Step 4: Add `send_direct_acceptance` at the end of `admissions/emails.py`**

```python
def send_direct_acceptance(member, *, track, background="", note="") -> None:
    """Send the acceptance letter to a member admitted with no site application.

    Deliberately the *same* ``decision_accept`` template the application route
    sends: however someone was admitted, the welcome they read is identical.
    """
    from .models import MessageTemplate
    from .services import render_template

    t = MessageTemplate.get(MessageTemplate.Key.DECISION_ACCEPT)
    note = (note or "").strip()
    ctx = {
        **_member_context(member, track=track, background=background),
        "note": f"{note}\n\n" if note else "",
    }
    _send(
        subject=render_template(t.subject, ctx),
        body=render_template(t.body, ctx),
        to=[member.email],
        reply_to=settings.APPLICATIONS_EMAIL,
        from_email=_applications_from(),
    )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest admissions/ -q`
Expected: all pass, including the existing decision-email tests that exercise `_applicant_context` through the application route

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && git add admissions/emails.py admissions/test_direct_admit.py && git commit -m "feat: render the acceptance letter for a member with no application (#476)"
```

---

### Task 3: The account-ready invitation email

**Files:**
- Modify: `accounts/emails.py` (add `send_account_ready` after `send_welcome`)
- Create: `accounts/templates/accounts/email/account_ready.txt`
- Create: `accounts/templates/accounts/email/account_ready.html`
- Test: `admissions/test_direct_admit.py`

**Interfaces:**
- Consumes: `accounts.emails._send_with_html`, `django.contrib.auth.tokens.default_token_generator`.
- Produces: `send_account_ready(user, *, track) -> None`. `track` is an `Application.Track` value, used only to pick the guidelines document link.

- [ ] **Step 1: Write the failing test**

Append to `admissions/test_direct_admit.py`:

```python
def test_account_ready_link_lets_the_member_set_a_password(client):
    from django.core import mail

    from accounts.emails import send_account_ready

    member = _user("ready@x.test", first_name="Ready")
    member.set_unusable_password()
    member.save(update_fields=["password"])

    send_account_ready(member, track=Application.Track.ANALYST)

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Ready" in body
    # The set-password link is a real, working password-reset confirm URL.
    url = next(
        line.strip() for line in body.splitlines()
        if "/accounts/password/reset/" in line
    )
    path = url[url.index("/accounts/"):]
    resp = client.get(path, follow=True)
    resp = client.post(resp.request["PATH_INFO"], {
        "new_password1": "a-real-passphrase-42",
        "new_password2": "a-real-passphrase-42",
    })
    member.refresh_from_db()
    assert member.check_password("a-real-passphrase-42")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest admissions/test_direct_admit.py -q -k account_ready`
Expected: FAIL — `ImportError: cannot import name 'send_account_ready'`

- [ ] **Step 3: Write the text template**

Create `accounts/templates/accounts/email/account_ready.txt`. Note the copy convention: commas, not em dashes.

```
{% autoescape off %}Dear{% if user.first_name %} {{ user.first_name }}{% endif %},

Welcome to the Lacanian School of Psychoanalysis. Your member account on the
school's website is set up and waiting for you, and it uses this email address.

Choose a password to get in:

  {{ set_password_url }}

That link is good for {{ ttl_days }} days. If it has expired by the time you
reach it, go to the log in page and choose "Email me a sign-in link", which
signs you in with one click and no password at all:

  {{ login_url }}

Once you are in, there are three things worth doing:

1. Choose an advisor. It is up to you to contact the analyst you select and
   ask them. These analysts are currently available to advise:

     {{ availability_url }}

   The Formation Guidelines explain what advisor and advisee owe each other:

     {{ guidelines_url }}

2. Build your member profile, a photo, a short bio, and your contact details:

     {{ profile_url }}

3. Visit My LSP, your member home, where your formation record lives:

     {{ mylsp_url }}

In the members-only documents area you will also find the checklist of what is
needed before you present your Passage:

  {{ documents_url }}

Questions, or trouble signing in? Just reply to this message.

Warmly,
Rico Picone
Web Coordinator and Developer
Lacanian School of Psychoanalysis
{% endautoescape %}
```

- [ ] **Step 4: Write the HTML template**

Create `accounts/templates/accounts/email/account_ready.html`:

```html
{% extends "email/base_email.html" %}
{% block title %}Your LSP member account is ready{% endblock %}
{% block preheader %}Choose a password and take your first steps as a member.{% endblock %}
{% block content %}
<h1 style="margin:0 0 16px 0; font-family:Georgia, 'Iowan Old Style', serif; font-weight:normal; font-size:24px; line-height:1.3; color:#1c1c29;">Welcome to LSP</h1>
<p style="margin:0 0 16px 0;">Dear{% if user.first_name %} {{ user.first_name }}{% endif %},</p>
<p style="margin:0 0 16px 0;">Welcome to the Lacanian School of Psychoanalysis. Your member account on the school's website is set up and waiting for you, and it uses this email address.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0;">
  <tr><td style="background-color:#1c1c29; border-radius:8px;">
    <a href="{{ set_password_url }}" style="display:inline-block; padding:12px 26px; font-family:-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; font-size:15px; font-weight:600; color:#e1ff00; text-decoration:none;">Choose your password</a>
  </td></tr>
</table>
<p style="margin:0 0 16px 0;">That link is good for {{ ttl_days }} days. If it has expired by the time you reach it, go to <a href="{{ login_url }}" style="color:#1c1c29;">the log in page</a> and choose <strong>Email me a sign-in link</strong>, which signs you in with one click and no password at all.</p>
<p style="margin:24px 0 8px 0;">Once you are in, there are three things worth doing:</p>
<ol style="margin:0 0 16px 0; padding-left:20px;">
  <li style="margin:0 0 10px 0;"><strong>Choose an advisor.</strong> It is up to you to contact the analyst you select and ask them. <a href="{{ availability_url }}" style="color:#1c1c29;">These analysts are currently available to advise</a>, and the <a href="{{ guidelines_url }}" style="color:#1c1c29;">Formation Guidelines</a> explain what advisor and advisee owe each other.</li>
  <li style="margin:0 0 10px 0;"><strong><a href="{{ profile_url }}" style="color:#1c1c29;">Build your member profile</a></strong>, a photo, a short bio, and your contact details.</li>
  <li style="margin:0 0 10px 0;"><strong><a href="{{ mylsp_url }}" style="color:#1c1c29;">Visit My LSP</a></strong>, your member home, where your formation record lives.</li>
</ol>
<p style="margin:0 0 16px 0;">In the <a href="{{ documents_url }}" style="color:#1c1c29;">members-only documents area</a> you will also find the checklist of what is needed before you present your Passage.</p>
<p style="margin:0 0 16px 0;">Questions, or trouble signing in? Just reply to this message.</p>
<p style="margin:24px 0 0 0;">Warmly,<br>
Rico Picone<br>
<span style="color:#8a847e;">Web Coordinator and Developer<br>
Lacanian School of Psychoanalysis</span></p>
{% endblock %}
```

- [ ] **Step 5: Add `send_account_ready` to `accounts/emails.py`**

Insert directly after `send_welcome`, before the `# --- Batch announcements` comment block:

```python
def send_account_ready(user, *, track) -> None:
    """Tell a directly-admitted member their account exists and how to get in.

    Sent by the Web Coordinator's direct-admission form to someone who was
    already welcomed to the school off-site, so it opens the account rather
    than announcing the decision (the full acceptance letter is
    ``admissions.emails.send_direct_acceptance``). The set-password link is
    Django's own password-reset token, so there's no second expiry mechanism
    to maintain; a lapsed link falls back to the magic sign-in link.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    from admissions.emails import _guidelines_url

    base = settings.SITE_BASE_URL.rstrip("/")
    set_password_url = base + reverse(
        "password_reset_confirm",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
        },
    )
    _send_with_html(
        "Your LSP member account is ready",
        user.email,
        "accounts/email/account_ready.txt",
        {
            "user": user,
            "set_password_url": set_password_url,
            "ttl_days": settings.PASSWORD_RESET_TIMEOUT // 86400,
            "login_url": base + reverse("login"),
            "availability_url": base + reverse("directory_availability") + "?only=advisor",
            "guidelines_url": _guidelines_url(track),
            "documents_url": base + reverse("documents:index"),
            "profile_url": base + reverse("profile_edit"),
            "mylsp_url": base + reverse("formation:formation"),
        },
    )
```

- [ ] **Step 6: Check `_send_with_html`'s signature before running**

Run: `grep -n "def _send_with_html" -A 20 accounts/emails.py`
If its parameters differ from `(subject, to_email, template, context)`, adapt the call above to match — do not change the helper.

- [ ] **Step 7: Run the test**

Run: `uv run pytest admissions/test_direct_admit.py -q -k account_ready`
Expected: PASS. If `settings.PASSWORD_RESET_TIMEOUT` is unset, Django's default is 259200 seconds, so `ttl_days` renders as 3.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . && git add accounts/emails.py accounts/templates/accounts/email/account_ready.txt accounts/templates/accounts/email/account_ready.html admissions/test_direct_admit.py && git commit -m "feat: account-ready invitation email for a directly-admitted member (#476)"
```

---

### Task 4: The direct-admission form

**Files:**
- Modify: `admissions/forms.py` (append `DirectAdmitForm`)
- Test: `admissions/test_direct_admit.py`

**Interfaces:**
- Produces: `DirectAdmitForm` with cleaned fields `email`, `first_name`, `last_name`, `track`, `formation_background`, `effective_ay`, `note`, `send`; and `form.existing_user` — the matched `User` when the email already has an account with no application, else `None`.
- `send` choices: `"letter"` (full acceptance letter), `"account"` (account-ready invitation), `"none"`.

- [ ] **Step 1: Write the failing test**

Append to `admissions/test_direct_admit.py`:

```python
def _form_data(**over):
    data = {
        "email": "new@x.test", "first_name": "Nadia", "last_name": "New",
        "track": Application.Track.ANALYST,
        "formation_background": Profile.FormationBackground.CLINICAL,
        "effective_ay": 2026, "note": "", "send": "account",
    }
    data.update(over)
    return data


def test_form_accepts_a_brand_new_email():
    from admissions.forms import DirectAdmitForm

    form = DirectAdmitForm(_form_data())
    assert form.is_valid(), form.errors
    assert form.existing_user is None


def test_form_promotes_an_existing_account_with_no_application():
    from admissions.forms import DirectAdmitForm

    existing = _user("selfsignup@x.test")
    form = DirectAdmitForm(_form_data(email="SelfSignup@x.test"))
    assert form.is_valid(), form.errors
    assert form.existing_user == existing


@pytest.mark.parametrize("status", [
    Application.Status.SUBMITTED,
    Application.Status.INTERVIEWING,
    Application.Status.ACCEPTED,
    Application.Status.REJECTED,
])
def test_form_refuses_someone_who_applied_on_the_site(status):
    from admissions.forms import DirectAdmitForm

    applicant = _user("applied@x.test")
    Application.objects.create(
        applicant=applicant, track=Application.Track.ANALYST,
        letter_of_intent="x", status=status,
    )
    form = DirectAdmitForm(_form_data(email="applied@x.test"))
    assert not form.is_valid()
    assert "application" in " ".join(form.errors["email"]).lower()


def test_form_allows_an_unreviewed_background():
    from admissions.forms import DirectAdmitForm

    form = DirectAdmitForm(_form_data(formation_background=""))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["formation_background"] == ""
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest admissions/test_direct_admit.py -q -k form`
Expected: FAIL — `ImportError: cannot import name 'DirectAdmitForm'`

- [ ] **Step 3: Read the existing form conventions**

Run: `sed -n 1,60p admissions/forms.py`
Use the same widget-class constant / styling approach the file already uses for its text inputs and selects. If it defines something like `_INPUT`, reuse it rather than inventing new class strings.

- [ ] **Step 4: Append `DirectAdmitForm` to `admissions/forms.py`**

```python
class DirectAdmitForm(forms.Form):
    """Admit a member who never applied on the site (task #476).

    Lives in the Web Coordinator's admin, not the Applications Coordinator's
    console: someone who applied here is admitted from their application, and
    the two surfaces are deliberately kept apart. The guard below is the
    structural half of that — an email belonging to any application, in any
    status, is refused outright rather than offered an override.
    """

    SEND_LETTER = "letter"
    SEND_ACCOUNT = "account"
    SEND_NONE = "none"
    SEND_CHOICES = [
        (SEND_ACCOUNT, "Account-ready invitation, they've already been welcomed"),
        (SEND_LETTER, "Full acceptance letter, they've heard nothing yet"),
        (SEND_NONE, "Nothing, I'll write to them myself"),
    ]

    email = forms.EmailField(label="Email")
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150)
    track = forms.ChoiceField(label="Formation", choices=Application.Track.choices)
    formation_background = forms.ChoiceField(
        label="Background", required=False,
        choices=[("", "Not yet reviewed")] + [
            (v, label) for v, label in Profile.FormationBackground.choices
            if v != Profile.FormationBackground.UNREVIEWED
        ],
        help_text="Determines the control-analysis requirement. Leave unreviewed "
                  "if the Meeting of Analysts hasn't determined it.",
    )
    effective_ay = forms.TypedChoiceField(
        label="Effective academic year", coerce=int,
        choices=[], help_text="The year their membership starts.",
    )
    note = forms.CharField(
        label="Note", required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded on the membership timeline, and included in the "
                  "acceptance letter if you send one.",
    )
    send = forms.ChoiceField(
        label="Send", choices=SEND_CHOICES, initial=SEND_ACCOUNT,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing_user = None
        self.fields["effective_ay"].choices = academic_year_choices(
            start=current_academic_year_start() - 5
        )
        self.fields["effective_ay"].initial = current_academic_year_start()

    def clean_email(self) -> str:
        email = BaseUserManager.normalize_email(self.cleaned_data["email"]).strip()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return email
        application = Application.objects.filter(applicant=user).first()
        if application is not None:
            raise forms.ValidationError(
                f"{email} applied through the site "
                f"({application.get_status_display().lower()}). Admit them from "
                "their application in the Applications Coordinator's console, "
                "not here."
            )
        self.existing_user = user
        return email
```

Add the imports this needs at the top of `admissions/forms.py`:

```python
from django.contrib.auth.models import BaseUserManager

from accounts.membership import academic_year_choices, current_academic_year_start
from accounts.models import Profile, User
```

(Check what the file already imports first; add only what's missing.)

- [ ] **Step 5: Run the form tests**

Run: `uv run pytest admissions/test_direct_admit.py -q -k form`
Expected: 7 passed (the refusal test is parametrized over four statuses)

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && git add admissions/forms.py admissions/test_direct_admit.py && git commit -m "feat: DirectAdmitForm with an absolute guard against site applicants (#476)"
```

---

### Task 5: The view, URL, template, and landing card

**Files:**
- Create: `admissions/direct_admit.py`
- Create: `admissions/templates/admissions/direct_admit.html`
- Modify: `admissions/urls.py` (import the module, add the path)
- Modify: `core/templates/core/staff/admin/web_coordinator.html` (section card)
- Test: `admissions/test_direct_admit.py`

**Interfaces:**
- Consumes: `DirectAdmitForm`, `admit_member`, `send_direct_acceptance`, `send_account_ready`, `core.access.staff_role_required`, `core.models.StaffRole.WEB_COORDINATOR`.
- Produces: URL name `admissions:direct_admit` at `/admin-tools/web-coordinator/admit/`.

- [ ] **Step 1: Write the failing tests**

Append to `admissions/test_direct_admit.py`:

```python
from django.urls import reverse  # add to the imports at the top of the file


@pytest.fixture
def wc(client):
    user = _user("webcoord@x.test", first_name="Web", last_name="Coordinator")
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"},
    )
    role.holders.add(user)
    client.force_login(user)
    return user


def test_page_is_gated_to_the_web_coordinator(client):
    url = reverse("admissions:direct_admit")
    assert client.get(url).status_code in (302, 403)  # anonymous

    client.force_login(_user("nobody@x.test"))
    assert client.get(url).status_code == 403


def test_admit_creates_the_account_and_sends_the_invitation(client, wc):
    from django.core import mail

    from accounts.models import WelcomeEmail

    resp = client.post(reverse("admissions:direct_admit"), _form_data(), follow=True)
    assert resp.status_code == 200

    member = User.objects.get(email="new@x.test")
    assert member.profile.role == Profile.Role.PRE_CANDIDATE
    assert member.profile.standing == Profile.Standing.ACTIVE
    assert member.profile.year_joined == 2026
    # Staff-vouched, so it must not read as an unconfirmed signup: the
    # purge sweeps is_active=False accounts with a null email_verified_at.
    assert member.profile.email_verified_at is not None
    assert not member.has_usable_password()
    # The launch welcome sweep must not mail them a second sign-in letter.
    assert WelcomeEmail.objects.filter(user=member).exists()
    assert len(mail.outbox) == 1
    assert "account is ready" in mail.outbox[0].subject.lower()


def test_admit_can_send_the_full_acceptance_letter(client, wc):
    from django.core import mail

    client.post(reverse("admissions:direct_admit"), _form_data(send="letter"))

    assert len(mail.outbox) == 1
    assert "accepted" in mail.outbox[0].subject.lower()


def test_admit_can_send_nothing_and_still_suppresses_the_launch_welcome(client, wc):
    from django.core import mail

    from accounts.models import WelcomeEmail

    client.post(reverse("admissions:direct_admit"), _form_data(send="none"))

    assert mail.outbox == []
    assert WelcomeEmail.objects.filter(user__email="new@x.test").exists()


def test_admit_promotes_an_existing_self_signup(client, wc):
    existing = _user("selfsignup@x.test")
    assert existing.profile.role == Profile.Role.EXTERNAL

    client.post(reverse("admissions:direct_admit"),
                _form_data(email="selfsignup@x.test", send="none"))

    existing.refresh_from_db()
    assert existing.profile.role == Profile.Role.PRE_CANDIDATE
    assert User.objects.filter(email__iexact="selfsignup@x.test").count() == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest admissions/test_direct_admit.py -q -k "page_is_gated or admit_"`
Expected: FAIL — `NoReverseMatch: 'direct_admit' is not a valid view function or pattern name`

- [ ] **Step 3: Write the view**

Create `admissions/direct_admit.py`:

```python
"""Admitting a member who never applied on the site (task #476).

Deliberately in the **Web Coordinator's** admin rather than the Applications
Coordinator's console. That console is the application process; a second
admission button inside it would invite reaching for the shortcut instead of
deciding the application in front of you. Different role, different surface,
and :class:`admissions.forms.DirectAdmitForm` refuses anyone who has an
application row at all.

The admission itself is not reimplemented here: it goes through
``services.admit_member``, the same chokepoint ``accept_application`` uses.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.emails import send_account_ready
from accounts.models import Profile, User, WelcomeEmail
from core.access import staff_role_required
from core.models import StaffRole

from .emails import send_direct_acceptance
from .forms import DirectAdmitForm
from .services import admit_member


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def direct_admit(request):
    form = DirectAdmitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member = _admit(form, by=request.user)
        messages.success(
            request,
            f"Admitted {member.get_full_name()} ({member.email}). "
            "Dues charges are minted by the treasurer's Sync charges.",
        )
        return redirect("admissions:direct_admit")
    return render(request, "admissions/direct_admit.html", {"form": form})


@transaction.atomic
def _admit(form, *, by) -> User:
    data = form.cleaned_data
    member = form.existing_user
    if member is None:
        member = User.objects.create_user(
            email=data["email"],
            password=None,  # unusable: they set one from the invitation
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
    else:
        member.first_name = data["first_name"]
        member.last_name = data["last_name"]
        member.save(update_fields=["first_name", "last_name"])

    profile = member.profile
    profile.year_joined = data["effective_ay"]
    # Staff-vouched, so this account is not an unconfirmed self-signup —
    # a null email_verified_at is what marks those for purging (#471).
    if profile.email_verified_at is None:
        profile.email_verified_at = timezone.now()
    profile.save(update_fields=["year_joined", "email_verified_at"])

    admit_member(
        member,
        track=data["track"],
        formation_background=data["formation_background"],
        effective_ay=data["effective_ay"],
        by=by,
        tenure_note=(
            "Admitted directly by the Web Coordinator, no site application. "
            f"{data['note']}"
        ).strip(),
        background_note="Set at direct admission.",
    )

    send = data["send"]
    if send == DirectAdmitForm.SEND_LETTER:
        send_direct_acceptance(
            member, track=data["track"],
            background=_application_background(data["formation_background"]),
            note=data["note"],
        )
    elif send == DirectAdmitForm.SEND_ACCOUNT:
        send_account_ready(member, track=data["track"])

    # Whatever we sent (including nothing), keep the launch welcome sweep off
    # them: send_welcome_emails picks up any active account without this row,
    # and a second "here's how to sign in" letter would only confuse.
    WelcomeEmail.objects.get_or_create(user=member)
    return member


def _application_background(formation_background: str) -> str:
    """Map a ``Profile.FormationBackground`` to the ``Application.Background``
    value the letter's formation label is built from."""
    from .models import Application

    return {
        Profile.FormationBackground.CLINICAL: Application.Background.CLINICAL,
        Profile.FormationBackground.ACADEMIC: Application.Background.ACADEMIC,
    }.get(formation_background, "")
```

- [ ] **Step 4: Check `User.objects.create_user` accepts `password=None`**

Run: `grep -n "def create_user" -A 20 accounts/models.py`
Confirm a `None` password produces an unusable password (Django's default `set_password(None)` behaviour). If the manager requires a password argument, use `User.objects.create_user(...)` then `member.set_unusable_password(); member.save(update_fields=["password"])`.

- [ ] **Step 5: Wire the URL**

In `admissions/urls.py`, add `direct_admit` to the module imports:

```python
from . import analyst, coordinator, direct_admit as direct_admit_views, views
```

and add this path with a comment, after the Applications Coordinator console block:

```python
    # --- Direct admission (Web Coordinator, NOT the Applications Coordinator:
    #     someone who applied on the site is admitted from their application) ---
    path("admin-tools/web-coordinator/admit/", direct_admit_views.direct_admit,
         name="direct_admit"),
```

- [ ] **Step 6: Write the page template**

Create `admissions/templates/admissions/direct_admit.html`:

```html
{% extends "core/base.html" %}
{% block title %}Admit a member · Web Coordinator · Lacanian School of Psychoanalysis{% endblock %}

{% block content %}
<div class="space-y-6 max-w-2xl">
  <nav class="text-sm"><a href="{% url 'web_coordinator_admin' %}" class="link link-hover text-base-content/60">← Web Coordinator Admin</a></nav>

  <header class="space-y-2">
    <p class="font-mono text-xs uppercase tracking-[0.2em] text-base-content/45">Staff · Web Coordinator</p>
    <h1 class="font-serif text-3xl text-base-content tracking-tight">Admit a member without an application</h1>
    <p class="text-base-content/70">Creates the account, records the membership, and sends the member their way in.</p>
  </header>

  <div role="note" class="rounded-lg border border-base-300 bg-base-200/50 p-4 text-sm text-base-content/80">
    <p class="font-medium text-base-content">Only for members admitted outside the site.</p>
    <p class="mt-1">Someone accepted by the Meeting of the Analysts before the application process moved here, or admitted by another route. Anyone who applied on the site is admitted from their application, in the Applications Coordinator's console.</p>
  </div>

  {% if messages %}
    {% for m in messages %}
    <div role="alert" class="alert {% if m.tags %}alert-{{ m.tags }}{% endif %}"><span>{{ m }}</span></div>
    {% endfor %}
  {% endif %}

  <form method="post" class="space-y-5">
    {% csrf_token %}
    {% if form.non_field_errors %}
      <div role="alert" class="alert alert-error"><span>{{ form.non_field_errors }}</span></div>
    {% endif %}
    {% for field in form %}
      <div class="space-y-1">
        <label for="{{ field.id_for_label }}" class="block text-sm font-medium text-base-content">{{ field.label }}</label>
        {{ field }}
        {% if field.help_text %}<p class="text-xs text-base-content/60">{{ field.help_text }}</p>{% endif %}
        {% for error in field.errors %}<p class="text-xs text-error">{{ error }}</p>{% endfor %}
      </div>
    {% endfor %}
    <button type="submit" class="btn btn-primary">Admit member</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Add the card to the Web Coordinator landing**

In `core/templates/core/staff/admin/web_coordinator.html`, add as the first section (before Aphorisms):

```html
  {% url 'admissions:direct_admit' as admit_url %}
  {% include "core/staff/admin/_section.html" with title="Admit a member" body="Create an account and record the membership for a member admitted outside the site, then send them their way in." link_label="Admit a member" link=admit_url %}
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest admissions/test_direct_admit.py -q`
Expected: all pass. If the form widgets render without DaisyUI classes, that's cosmetic — check the page visually in step 9, and add widget classes in `DirectAdmitForm.__init__` only if needed, remembering that a class set in Python must also appear in an `.html` file (Tailwind scans templates only).

- [ ] **Step 9: Check the page renders**

Run: `npm run build:css && uv run python manage.py runserver` and visit `/admin-tools/web-coordinator/admit/` as a Web Coordinator. Confirm the note reads clearly, the radio group for **Send** is legible, and the form submits.

- [ ] **Step 10: Run the full suite and lint**

Run: `uv run pytest -q -x && uv run ruff check .`
Expected: green

- [ ] **Step 11: Commit**

```bash
git add admissions/direct_admit.py admissions/urls.py admissions/templates/admissions/direct_admit.html core/templates/core/staff/admin/web_coordinator.html admissions/test_direct_admit.py && git commit -m "feat: direct-admission form in the Web Coordinator admin (#476)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `CLAUDE.md` (append to the Status "Done" list, after the task #474 entries)
- Modify: `docs/superpowers/specs/2026-07-27-direct-admission-design.md` (record the §4 amendment)

- [ ] **Step 1: Amend the spec**

In §4 of the spec, replace the first paragraph ("A new `account_ready` `MessageTemplate` key…") with:

```markdown
A new account-ready invitation, sent by `accounts.emails.send_account_ready` from
plain templates in `accounts/templates/accounts/email/account_ready.{txt,html}`.

**Amended during planning:** the spec originally made this an
`admissions.MessageTemplate` key so the coordinator could reword it in place.
That would have defeated the placement decision — `coordinator.messages_list`
iterates `MessageTemplate.Key.values`, so the key would appear in the
Applications Coordinator's Messages tab, putting a direct-admission artifact
back in the console we deliberately kept it out of. The full acceptance letter
option still uses the shared `decision_accept` template, which belongs to
admissions either way.
```

- [ ] **Step 2: Add the CLAUDE.md status entry**

Append to the Status "Done" list:

```markdown
- **Direct admission** (task #476). A member admitted outside the site had no
  path in: `Application` is a `OneToOne` on a `User` requiring a letter of
  intent, so the coordinator couldn't retro-create one, and admitting by hand
  meant four surfaces (Django admin for the account, Board membership admin for
  role/standing, the MoA backgrounds page, the profile editor) with **no letter
  at the end**. Now one form at `/admin-tools/web-coordinator/admit/`
  (`admissions/direct_admit.py`, `StaffRole.WEB_COORDINATOR`-gated) creates the
  account and admits them. The admission itself is **not** reimplemented:
  `admissions.services.admit_member()` is the shared chokepoint (membership
  change + formation background) that `accept_application()` was refactored
  onto, so the two routes can't drift; the tenure note records which one was
  used. The form is in the **Web Coordinator's** admin on purpose, not the
  Applications Coordinator's console: a second admission button inside the
  application process invites reaching for the shortcut. The structural half of
  that is the form's guard, which refuses any email with an `Application` row in
  **any** status, with no override, and links to that application instead; an
  account with no application (a self-signup at `role=external`) is promoted in
  place. New accounts get an unusable password (password reset is the way in,
  and `ReplyToPasswordResetForm` deliberately reaches unusable-password rows)
  plus a stamped `email_verified_at`, since a null there means "self-signup that
  never confirmed" and would make a staff-vouched account look like a bot row to
  `purge_unverified_signups`. Send is a choice of the full `decision_accept`
  letter (rendered without an application via the new `_member_context`), a new
  **account-ready invitation** for someone already welcomed off-site
  (`accounts.emails.send_account_ready`, a 3-day `password_reset_confirm` link
  with the magic-link fallback), or nothing — and **all three write a
  `WelcomeEmail` row**, or the next `send_welcome_emails` run would mail the new
  member a second, contradictory sign-in letter. Dues charges stay with the
  treasurer's Sync charges; the success message says so.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-07-27-direct-admission-design.md && git commit -m "docs: record direct admission (#476)"
```

---

## Self-Review

**Spec coverage:** §1 placement/gating → Task 5 (view, URL, card, gate test) and the note copy in the template. §2 shared service → Task 1. §3 form, account creation, unusable password, `email_verified_at`, `year_joined`, collision guard, existing-account promotion → Tasks 4 and 5. §4 email + three send choices + `WelcomeEmail` suppression → Tasks 3 and 5 (amended: plain templates, not a `MessageTemplate` key — recorded in Task 6). §5 rendering without an `Application` → Task 2. §6 out of scope → the success message in Task 5 names Sync charges. Testing section → covered across Tasks 1–5.

**Types:** `admit_member(member, *, track, formation_background="", effective_ay=None, by, tenure_note="", background_note="")` is defined in Task 1 and called with exactly those keywords in Tasks 1 and 5. `send_direct_acceptance(member, *, track, background="", note="")` defined in Task 2, called in Task 5 with an `Application.Background` value produced by `_application_background`. `send_account_ready(user, *, track)` defined in Task 3, called in Task 5. `DirectAdmitForm.SEND_LETTER/SEND_ACCOUNT/SEND_NONE` defined in Task 4, used in Task 5.
