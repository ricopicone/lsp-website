# Referral Spam Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop bot submissions on the public Find-an-Analyst form from being auto-acknowledged to harvested addresses and auto-distributed to the whole referral list, without adding friction for genuine requesters.

**Architecture:** Two layers. *Transport* checks (honeypot, fill timing, per-IP cap) reuse the existing `accounts/antibot.py` and drop near-certain bots silently, recording a content-free counter row. *Content* checks live in a new pure-function module `referrals/screening.py` and put suspicious submissions into a new `HELD` status that is never acknowledged and never distributed until a coordinator releases it. The automatic path can only ever *hold*; every terminal call is a human's.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI/Tailwind v4 templates.

**Spec:** `docs/superpowers/specs/2026-07-27-referral-spam-screening-design.md`

## Global Constraints

- **Never raise a validation error naming the bot check.** A caught bot gets the ordinary success page and learns nothing. No `ValidationError("Bot detected.")`.
- **CSS classes set in Python must exist in a template or plain CSS**, or Tailwind's template scan drops them from the prod build. `.hp-wrap` already exists in `assets/css/input.css:853`; reuse it, do not invent a new class.
- **No IP or user-agent may be stored on `ReferralRequest` or `BlockedSubmission`.** These rows carry sensitive clinical disclosures and are redacted on retention. The per-IP cap uses the cache only.
- **The automatic path never rejects, only holds.** `JUNK` is set by a coordinator, never by screening code.
- Member-facing site copy uses commas, not em dashes (see the `em-dash-prose-style` convention). Coordinator-facing admin copy follows the surrounding files.
- Use DaisyUI semantic tokens (`bg-base-100`, `text-base-content`, `badge-warning`, …), never hardcoded colors.
- Run `uv run pytest` and `uv run ruff check .` before every commit.

---

### Task 1: Content screening module

Pure functions, no Django, no I/O. Built first so every later task can rely on it.

**Files:**
- Create: `referrals/screening.py`
- Create: `referrals/test_screening.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `screening.screen(data: dict) -> str` — returns a human-readable reason string when the submission is suspicious, or `""` when it is clean. The reason doubles as the boolean (truthy = hold), which is why there is no separate flag.
  - `screening.looks_like_gibberish(value: str) -> bool`
  - `screening.count_case_transitions(value: str) -> int`
  - Constants `GIBBERISH_MIN_LENGTH`, `GIBBERISH_MIN_CASE_TRANSITIONS`, `MIN_NARRATIVE_LENGTH`, `URL_MARKERS`, `SCREENED_SHORT_FIELDS`.

- [ ] **Step 1: Write the failing tests**

Create `referrals/test_screening.py`. These payloads are the real ones from prod — do not paraphrase them.

```python
"""Screening heuristics (task #479).

The junk tokens below are verbatim from referral request 26-0727, and the
clean payloads are verbatim from 26-0727-2 (Tina) and 26-0722 (Maloney).
Real data is the whole point: a synthetic test would not have caught that
the originally-specified vowel-ratio rule flags "Pittsburgh".
"""

import pytest

from referrals import screening

JUNK_TOKENS = [
    "LEIAZKMKtfUBswyJuaS",
    "IzNydkEnQFrKxxKl",
    "lfNxcMPRAZNciaxtfNPOMQK",
    "iIcIlrhZIIwEImoxJld",
    "GtDlqAgHoujeYbXggDwPs",
]

# Every one of these must screen clean. Pittsburgh and they/them are here
# specifically because the rejected vowel-ratio rule flagged both.
CLEAN_TOKENS = [
    "Pittsburgh", "Edmonton", "English", "Spanish", "Frankfurt",
    "Bydgoszcz", "MacDonald", "McCann", "they/them", "she/her",
    "San Antonio Texas", "Edmonton, Alberta, Canada",
]

JUNK_PAYLOAD = {
    "name": "LEIAZKMKtfUBswyJuaS",
    "pronouns": "IzNydkEnQFrKxxKl",
    "email": "lauren_michele2005@hotmail.com",
    "location": "lfNxcMPRAZNciaxtfNPOMQK",
    "language": "iIcIlrhZIIwEImoxJld",
    "modality": "In person, By phone, By online video platform",
    "additional_information": "GtDlqAgHoujeYbXggDwPs",
}

CLEAN_PAYLOAD = {
    "name": "Tina",
    "pronouns": "she/her",
    "email": "tina@example.com",
    "location": "San Antonio Texas",
    "language": "English",
    "modality": "By online video platform",
    "additional_information": (
        "I am 58 years old and currently the primary caregiver for my 83 "
        "year old father, who has dementia. We had a difficult childhood, "
        "and caring for him has brought many unresolved emotions to the "
        "surface. I am looking for a therapist who can help me process "
        "those feelings and develop healthy tools for navigating this "
        "stage of my life."
    ),
}


@pytest.mark.parametrize("token", JUNK_TOKENS)
def test_junk_tokens_are_gibberish(token):
    assert screening.looks_like_gibberish(token) is True


@pytest.mark.parametrize("token", CLEAN_TOKENS)
def test_real_values_are_not_gibberish(token):
    assert screening.looks_like_gibberish(token) is False


def test_short_tokens_are_never_gibberish():
    # Below the length floor, even with many case transitions.
    assert screening.looks_like_gibberish("aBcDeF") is False


def test_non_alpha_tokens_are_never_screened():
    # The isalpha gate is what keeps "they/them" and hyphenated names out.
    assert screening.looks_like_gibberish("aBcDeFgHiJ/kL") is False


def test_case_transitions_counts_adjacent_changes():
    assert screening.count_case_transitions("Edmonton") == 1
    assert screening.count_case_transitions("MacDonald") == 3
    assert screening.count_case_transitions("LEIAZKMKtfUBswyJuaS") == 6


def test_junk_payload_is_held():
    assert screening.screen(JUNK_PAYLOAD) != ""


def test_clean_payload_screens_clean():
    assert screening.screen(CLEAN_PAYLOAD) == ""


def test_short_narrative_is_held():
    data = dict(CLEAN_PAYLOAD, additional_information="Need help.")
    assert "short" in screening.screen(data).lower()


def test_url_in_narrative_is_held():
    data = dict(
        CLEAN_PAYLOAD,
        additional_information=(
            "Great deals at http://spam.example.com, click now! " * 3
        ),
    )
    assert "link" in screening.screen(data).lower()


def test_url_in_short_field_is_held():
    data = dict(CLEAN_PAYLOAD, location="www.spam.example.com")
    assert "link" in screening.screen(data).lower()


def test_reason_names_the_field():
    assert "location" in screening.screen(JUNK_PAYLOAD)


def test_missing_keys_do_not_crash():
    assert screening.screen({}) != ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/test_screening.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'referrals.screening'`

- [ ] **Step 3: Write the implementation**

Create `referrals/screening.py`:

```python
"""Content screening for Find-an-Analyst submissions (task #479).

Referral request 26-0727 was a commodity form-spam bot: every visible text
input filled with a random mixed-case token, every checkbox checked. The
transport-level deterrents in ``accounts.antibot`` are the first line and
drop that class of bot outright; this module is the second, for anything
that gets past them.

Nothing here rejects. A hit puts the request in ``HELD`` for the
coordinator to release or mark junk, because every heuristic is fallible
and the cost of blocking a real person reaching out for an analyst is far
higher than the cost of a review click.
"""

from __future__ import annotations

#: Free-text fields short enough that a random token stands out. ``pronouns``
#: arrives already resolved through ``ReferralRequestForm.pronouns_display()``.
SCREENED_SHORT_FIELDS = ("name", "location", "language", "pronouns")

#: A token shorter than this is never judged — real names and languages are
#: often short, and there is no signal in "Ana" or "Urdu".
GIBBERISH_MIN_LENGTH = 8

#: Adjacent upper<->lower changes before a token reads as machine-generated.
#: Every junk token from 26-0727 scores 5 or more; every real value we hold
#: (Pittsburgh, Edmonton, English, Frankfurt, Bydgoszcz) scores 1, and the
#: nearest real-world miss, "MacDonald", scores 3.
GIBBERISH_MIN_CASE_TRANSITIONS = 4

#: Real narratives run 600-900 characters. 26-0727's was 21.
MIN_NARRATIVE_LENGTH = 40

#: Link spam is the other standard vector; real requesters do not paste URLs.
URL_MARKERS = ("http", "www.", "[url=", "<a ")


def count_case_transitions(value: str) -> int:
    """Adjacent letter pairs that change between upper and lower case."""
    return sum(
        1
        for a, b in zip(value, value[1:])
        if a.isalpha() and b.isalpha() and a.isupper() != b.isupper()
    )


def looks_like_gibberish(value: str) -> bool:
    """Whether a short free-text field reads as a machine-generated token.

    Only pure-alphabetic strings of at least ``GIBBERISH_MIN_LENGTH`` are
    candidates. The ``isalpha`` gate is load-bearing: it excludes anything
    with a space, digit, slash, comma, or hyphen, which is what keeps
    "they/them", "San Antonio Texas", and hyphenated surnames out.

    Vowel ratio was evaluated as a second signal and rejected — at any
    threshold that catches the junk it also flags "Pittsburgh" (0.20),
    "Frankfurt" (0.22), and "Bydgoszcz" (0.11). See the design doc.

    Known limit: an all-lowercase token ("qwrtplkjhg") scores zero
    transitions and is not caught here.
    """
    token = (value or "").strip()
    if len(token) < GIBBERISH_MIN_LENGTH or not token.isalpha():
        return False
    return count_case_transitions(token) >= GIBBERISH_MIN_CASE_TRANSITIONS


def _has_link(value: str) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in URL_MARKERS)


def screen(data: dict) -> str:
    """Judge one submission.

    Returns a short reason the coordinator can read at a glance, or ``""``
    when the submission looks fine. The reason doubles as the boolean, so
    callers just check truthiness.
    """
    for field in SCREENED_SHORT_FIELDS:
        value = (data.get(field) or "").strip()
        if looks_like_gibberish(value):
            return f"The {field} field looks machine-generated ({value!r})."

    for field in (*SCREENED_SHORT_FIELDS, "additional_information"):
        if _has_link(data.get(field) or ""):
            return f"The {field} field contains a link."

    narrative = (data.get("additional_information") or "").strip()
    if len(narrative) < MIN_NARRATIVE_LENGTH:
        return (
            f"The description is only {len(narrative)} characters; real "
            f"requests run to several hundred."
        )

    return ""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest referrals/test_screening.py -v`
Expected: PASS, all cases.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check referrals/screening.py referrals/test_screening.py
git add referrals/screening.py referrals/test_screening.py
git commit -m "feat(referrals): content screening for Find-an-Analyst submissions (#479)"
```

---

### Task 2: Model states, held fields, and the blocked counter

One migration for every schema change in this plan, so there is a single deploy artifact.

**Files:**
- Modify: `referrals/models.py` (`ReferralRequest.Status`, new fields, new `BlockedSubmission`, `ReferralSettings.held_escalation_days`)
- Create: `referrals/migrations/0002_referral_screening.py` (generated — the real number may differ; use whatever `makemigrations` produces)
- Create: `referrals/test_models_screening.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `ReferralRequest.Status.HELD` (`"held"`), `ReferralRequest.Status.JUNK` (`"junk"`)
  - `ReferralRequest.held_reason: str`, `.held_at: datetime|None`, `.held_escalated_at: datetime|None`
  - `ReferralRequest.SUPPRESSED_STATUSES: tuple` — statuses that must never be acknowledged or distributed
  - `ReferralSettings.held_escalation_days: int` (default 3)
  - `BlockedSubmission` with `created_at`, `reason`, and `BlockedSubmission.Reason` choices `HONEYPOT` / `TIMING` / `RATE_LIMIT`

- [ ] **Step 1: Write the failing test**

Create `referrals/test_models_screening.py`:

```python
import pytest
from django.utils import timezone

from referrals.models import BlockedSubmission, ReferralRequest, ReferralSettings

pytestmark = pytest.mark.django_db


def test_held_and_junk_statuses_exist():
    assert ReferralRequest.Status.HELD == "held"
    assert ReferralRequest.Status.JUNK == "junk"


def test_suppressed_statuses_cover_held_and_junk():
    assert set(ReferralRequest.SUPPRESSED_STATUSES) == {
        ReferralRequest.Status.HELD, ReferralRequest.Status.JUNK,
    }


def test_open_statuses_exclude_held_and_junk():
    # HELD is the coordinator's problem but must not enter the normal
    # workflow, or process_referrals would try to follow it up.
    assert ReferralRequest.Status.HELD not in ReferralRequest.OPEN_STATUSES
    assert ReferralRequest.Status.JUNK not in ReferralRequest.OPEN_STATUSES


def test_held_fields_default_empty():
    req = ReferralRequest.objects.create(
        name="Tina", email="t@example.com", location="Texas", language="English",
    )
    assert req.held_reason == ""
    assert req.held_at is None
    assert req.held_escalated_at is None


def test_blocked_submission_stores_no_content():
    row = BlockedSubmission.objects.create(
        reason=BlockedSubmission.Reason.HONEYPOT,
    )
    assert row.created_at is not None
    # The whole point: nothing identifying, nothing to leak.
    field_names = {f.name for f in BlockedSubmission._meta.get_fields()}
    assert field_names == {"id", "created_at", "reason"}


def test_settings_has_escalation_days_default():
    assert ReferralSettings.load().held_escalation_days == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest referrals/test_models_screening.py -v`
Expected: FAIL — `AttributeError: type object 'Status' has no attribute 'HELD'`

- [ ] **Step 3: Edit the models**

In `referrals/models.py`, add to `ReferralRequest.Status` (after `CLOSED`):

```python
        HELD = "held", _("Held for review")
        JUNK = "junk", _("Junk")
```

Immediately below `OPEN_STATUSES`, add:

```python
    #: Statuses that must never be acknowledged or distributed. Screening
    #: puts a request in HELD; a coordinator puts it in JUNK. Guarded in
    #: services.send_acknowledgment and services.distribute so no future
    #: caller can leak one to the referral list.
    SUPPRESSED_STATUSES = (Status.HELD, Status.JUNK)
```

Add to `ReferralRequest`, next to the other timestamps:

```python
    held_reason = models.TextField(
        blank=True,
        help_text="Why screening held this submission, shown to the "
        "coordinator so they can judge it at a glance.",
    )
    held_at = models.DateTimeField(null=True, blank=True)
    held_escalated_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the unreviewed-hold reminder was emailed, so it "
        "is sent only once.",
    )
```

Add to `ReferralSettings`, after `retention_months`:

```python
    held_escalation_days = models.PositiveSmallIntegerField(
        default=3,
        help_text="Days a held submission may sit unreviewed before the "
        "coordinator is emailed about it. Held requests otherwise only "
        "ring the notification bell.",
    )
```

Add at the end of `referrals/models.py`:

```python
class BlockedSubmission(models.Model):
    """One Find-an-Analyst submission rejected by a transport-level check.

    Deliberately content-free: a timestamp and a reason, nothing else. No
    address, no IP, no submitted text. It exists only so the coordinator can
    see a hit rate — without it, a filter that silently broke and started
    eating real requests would look exactly like a filter that is working.
    """

    class Reason(models.TextChoices):
        HONEYPOT = "honeypot", _("Honeypot field filled")
        TIMING = "timing", _("Submitted too fast")
        RATE_LIMIT = "rate_limit", _("Rate limit")

    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.get_reason_display()} at {self.created_at:%Y-%m-%d %H:%M}"
```

- [ ] **Step 4: Generate the migration**

```bash
uv run python manage.py makemigrations referrals
```

Read the generated file and confirm it contains exactly: two `AddField` on `referralrequest` plus `held_escalated_at`, one `AddField` on `referralsettings`, one `AlterField` on `referralrequest.status`, and one `CreateModel` for `BlockedSubmission`. No `RemoveField`, no data loss.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest referrals/test_models_screening.py -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check referrals/
git add referrals/models.py referrals/migrations/ referrals/test_models_screening.py
git commit -m "feat(referrals): HELD/JUNK statuses and content-free blocked counter (#479)"
```

---

### Task 3: Transport deterrents on the Find-an-Analyst form

Swap the `type="hidden"` honeypot for the CSS-hidden text input the signup form uses, add the signed timestamp and the per-IP cap, and record a counter row on each block.

**Files:**
- Modify: `accounts/antibot.py` (make the minimum fill time a parameter)
- Modify: `accounts/forms.py:118-197` (`ReferralRequestForm`)
- Modify: `accounts/views.py:424-455` (`find_an_analyst`)
- Modify: `accounts/templates/accounts/find_an_analyst.html:63`
- Create: `referrals/test_intake_antibot.py`

**Interfaces:**
- Consumes: `referrals.models.BlockedSubmission` (Task 2).
- Produces:
  - `antibot.looks_too_fast(value: str, minimum: float = MIN_FILL_SECONDS) -> bool`
  - `antibot.REFERRAL_MIN_FILL_SECONDS = 10`
  - `ReferralRequestForm.honeypot_tripped -> bool` (property)
  - The view context key `honeypot_field`, mirroring `signup`.

- [ ] **Step 1: Write the failing tests**

Create `referrals/test_intake_antibot.py`:

```python
"""Transport-level deterrents on the public Find-an-Analyst form (#479).

A caught bot must get the ordinary success page: no ReferralRequest, no
mail, and no hint about which check burned it.
"""

import pytest
from django.core import mail
from django.urls import reverse

from accounts import antibot
from referrals.models import BlockedSubmission, ReferralRequest

pytestmark = pytest.mark.django_db


def _payload(**overrides):
    data = {
        "name": "Tina",
        "pronouns": "she/her",
        "pronouns_other": "",
        "email": "tina@example.com",
        "location": "San Antonio Texas",
        "language": "English",
        "modality": ["video"],
        "additional_information": (
            "I am looking for an analyst to help me work through a "
            "difficult period of caregiving and some longstanding grief."
        ),
        antibot.HONEYPOT_FIELD: "",
        antibot.TIMESTAMP_FIELD: antibot.sign_timestamp(
            __import__("django.utils.timezone", fromlist=["timezone"])
            .timezone.now()
            - __import__("datetime").timedelta(seconds=60)
        ),
    }
    data.update(overrides)
    return data


def test_clean_submission_creates_a_request(client):
    resp = client.post(reverse("find_an_analyst"), _payload())
    assert resp.status_code == 302
    assert ReferralRequest.objects.count() == 1


def test_honeypot_filled_is_dropped_silently(client):
    resp = client.post(
        reverse("find_an_analyst"),
        _payload(**{antibot.HONEYPOT_FIELD: "http://spam.example.com"}),
    )
    assert resp.status_code == 302          # the ordinary success redirect
    assert ReferralRequest.objects.count() == 0
    assert mail.outbox == []
    assert BlockedSubmission.objects.filter(
        reason=BlockedSubmission.Reason.HONEYPOT,
    ).count() == 1


def test_too_fast_submission_is_dropped_silently(client):
    resp = client.post(
        reverse("find_an_analyst"),
        _payload(**{antibot.TIMESTAMP_FIELD: antibot.sign_timestamp()}),
    )
    assert resp.status_code == 302
    assert ReferralRequest.objects.count() == 0
    assert mail.outbox == []
    assert BlockedSubmission.objects.filter(
        reason=BlockedSubmission.Reason.TIMING,
    ).count() == 1


def test_missing_timestamp_is_dropped(client):
    resp = client.post(reverse("find_an_analyst"), _payload(**{
        antibot.TIMESTAMP_FIELD: "",
    }))
    assert resp.status_code == 302
    assert ReferralRequest.objects.count() == 0


def test_honeypot_is_a_text_input_not_a_hidden_input(client):
    # The whole incident: commodity bots skip type="hidden" on purpose.
    resp = client.get(reverse("find_an_analyst"))
    html = resp.content.decode()
    assert f'name="{antibot.HONEYPOT_FIELD}"' in html
    assert f'type="hidden" name="{antibot.HONEYPOT_FIELD}"' not in html
    assert "hp-wrap" in html


def test_looks_too_fast_takes_a_minimum():
    from datetime import timedelta

    from django.utils import timezone

    stamp = antibot.sign_timestamp(timezone.now() - timedelta(seconds=5))
    assert antibot.looks_too_fast(stamp, minimum=2) is False
    assert antibot.looks_too_fast(stamp, minimum=10) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/test_intake_antibot.py -v`
Expected: FAIL — `test_honeypot_is_a_text_input_not_a_hidden_input` finds the hidden input, and `looks_too_fast` takes no `minimum`.

- [ ] **Step 3: Parameterise the minimum fill time**

In `accounts/antibot.py`, replace `looks_too_fast` and add the referral constant beneath `MIN_FILL_SECONDS`:

```python
#: The Find-an-Analyst form is a two-step wizard with seven fields; no human
#: clears it in ten seconds, so it can afford a stricter floor than signup.
REFERRAL_MIN_FILL_SECONDS = 10


def looks_too_fast(value: str, minimum: float = MIN_FILL_SECONDS) -> bool:
    """Whether this submission arrived faster than a human could type it.

    ``minimum`` is per-form: a short signup and a multi-step wizard have
    very different floors.
    """
    elapsed = seconds_since_render(value)
    if elapsed is None:
        return True
    return elapsed < minimum
```

- [ ] **Step 4: Rework the form**

In `accounts/forms.py`, delete the honeypot field declaration and `clean_website` from `ReferralRequestForm`:

```python
    # Honeypot — humans don't see it; bots fill it. Reject if non-empty.
    website = forms.CharField(required=False, widget=forms.HiddenInput())
```

and

```python
    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Bot detected.")
        return ""
```

Add to `ReferralRequestForm` instead (an `__init__` plus the property, mirroring `LightSignupForm`):

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A CSS-hidden *text* input, not type="hidden": request 26-0727 was a
        # bot that filled every visible input and skipped the hidden one,
        # which is what commodity bots do (task #479).
        self.fields[antibot.HONEYPOT_FIELD] = forms.CharField(
            required=False,
            label="Website",
            widget=forms.TextInput(attrs={
                "autocomplete": "off",
                "tabindex": "-1",
                "class": "hp-field",
            }),
        )
        self.fields[antibot.TIMESTAMP_FIELD] = forms.CharField(
            required=False,
            widget=forms.HiddenInput(),
            initial=antibot.sign_timestamp,
        )

    @property
    def honeypot_tripped(self) -> bool:
        """Whether a field a human never sees came back filled."""
        return bool(self.data.get(antibot.HONEYPOT_FIELD, "").strip())
```

Also update the class docstring:

```python
class ReferralRequestForm(forms.Form):
    """Find-an-Analyst inquiry — fields mirror the Wix Typeform exactly.

    Carries the same invisible deterrents as signup (task #471): a CSS-hidden
    honeypot text input and a signed render stamp. Both are inspected by the
    view rather than raised as errors here, so a caught bot sees the ordinary
    thank-you page and learns nothing (task #479).
    """
```

- [ ] **Step 5: Rework the view**

In `accounts/views.py`, replace the body of `find_an_analyst`:

```python
def find_an_analyst(request):
    """Public Find-an-Analyst page: referral form + interactive map of members.

    Handles form GET (display) and POST. A valid submission becomes a tracked
    ``referrals.ReferralRequest`` (the coordinator inquiry email and, in auto
    mode, the acknowledgment are sent by ``referrals.services.intake``).

    Transport-level bot checks run *before* intake, so a bot submitting a
    harvested address never causes the school to mail that stranger. A caught
    bot gets the ordinary success redirect (task #479).
    """
    submitted = request.GET.get("submitted") == "1"
    if request.method == "POST":
        from referrals.models import BlockedSubmission

        form = ReferralRequestForm(request.POST)
        ip = antibot.client_ip(request)
        success = redirect(f"{request.path}?submitted=1#submitted")

        blocked = None
        if form.honeypot_tripped:
            blocked = BlockedSubmission.Reason.HONEYPOT
        elif antibot.looks_too_fast(
            request.POST.get(antibot.TIMESTAMP_FIELD, ""),
            minimum=antibot.REFERRAL_MIN_FILL_SECONDS,
        ):
            blocked = BlockedSubmission.Reason.TIMING
        elif antibot.over_rate_limit(ip):
            blocked = BlockedSubmission.Reason.RATE_LIMIT

        if blocked is not None:
            logger.info("referral form blocked (%s) from %s", blocked, ip)
            BlockedSubmission.objects.create(reason=blocked)
            return success

        antibot.record_attempt(ip)
        if form.is_valid():
            from referrals.services import intake

            modality_labels = dict(form.fields["modality"].choices)
            intake({
                "name":      form.cleaned_data["name"],
                "pronouns":  form.pronouns_display(),
                "email":     form.cleaned_data["email"],
                "location":  form.cleaned_data["location"],
                "language":  form.cleaned_data["language"],
                "modality":  ", ".join(
                    modality_labels.get(v, v) for v in form.cleaned_data["modality"]
                ),
                "additional_information": form.cleaned_data["additional_information"],
            })
            return success
    else:
        form = ReferralRequestForm()
    return render(request, "accounts/find_an_analyst.html", {
        "form": form,
        "submitted": submitted,
        "honeypot_field": antibot.HONEYPOT_FIELD,
    })
```

Note: the per-IP cap shares `antibot`'s single cache key with signup, which is intentional — one IP flooding either public form is the same signal.

- [ ] **Step 6: Update the template**

In `accounts/templates/accounts/find_an_analyst.html`, replace line 63:

```django
        {{ form.website }}{# honeypot, visually hidden via HiddenInput #}
```

with:

```django
        {{ form.form_ts }}
        {# Honeypot: a real text input, moved off-screen by .hp-wrap rather
           than type="hidden" — commodity bots skip hidden inputs (#479). #}
        <div class="hp-wrap" aria-hidden="true">
          <label for="{{ form.website.id_for_label }}">Website</label>
          {{ form.website }}
        </div>
```

Both new fields sit outside the `.referral-step` fieldsets, so the wizard's `validateCurrent()` never sees them and step navigation is unaffected.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest referrals/test_intake_antibot.py accounts/ -v`
Expected: PASS. If any existing `accounts` test posts to this form, it will now fail on the timing check — fix it by including a backdated `antibot.sign_timestamp(...)`, not by weakening the check.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check accounts/ referrals/
git add accounts/antibot.py accounts/forms.py accounts/views.py accounts/templates/accounts/find_an_analyst.html referrals/test_intake_antibot.py
git commit -m "fix(referrals): CSS-hidden honeypot, fill timing, and IP cap on Find-an-Analyst (#479)"
```

---

### Task 4: Hold suspicious submissions at intake, and guard the send paths

**Files:**
- Modify: `referrals/services.py` (`intake`, `send_acknowledgment`, `distribute`)
- Modify: `referrals/notifications.py` (add the coordinator alert)
- Create: `referrals/test_intake_holding.py`

**Interfaces:**
- Consumes: `screening.screen` (Task 1); `ReferralRequest.Status.HELD`, `.SUPPRESSED_STATUSES`, `.held_reason`, `.held_at` (Task 2).
- Produces:
  - `services.SuppressedStatusError` — raised by `send_acknowledgment` and `distribute` when called on a suppressed request.
  - `notifications.referral_held(request_obj) -> None`
  - `services.release(req: ReferralRequest) -> None` — clears the hold and resumes the normal chain.

- [ ] **Step 1: Write the failing tests**

Create `referrals/test_intake_holding.py`:

```python
"""Held submissions never reach the referral list or the requester (#479)."""

import pytest
from django.core import mail

from referrals import services
from referrals.models import (
    Mode,
    ReferralListMember,
    ReferralRequest,
    ReferralSettings,
)

pytestmark = pytest.mark.django_db

JUNK = {
    "name": "LEIAZKMKtfUBswyJuaS",
    "pronouns": "IzNydkEnQFrKxxKl",
    "email": "lauren_michele2005@hotmail.com",
    "location": "lfNxcMPRAZNciaxtfNPOMQK",
    "language": "iIcIlrhZIIwEImoxJld",
    "modality": "In person, By phone, By online video platform",
    "additional_information": "GtDlqAgHoujeYbXggDwPs",
}

CLEAN = {
    "name": "Tina",
    "pronouns": "she/her",
    "email": "tina@example.com",
    "location": "San Antonio Texas",
    "language": "English",
    "modality": "By online video platform",
    "additional_information": (
        "I am looking for a therapist who can help me process some "
        "longstanding grief and the strain of caring for my father."
    ),
}


@pytest.fixture
def auto_everything():
    config = ReferralSettings.load()
    config.ack_mode = Mode.AUTO
    config.distribution_mode = Mode.AUTO
    config.save()
    return config


def test_junk_is_held_and_sends_nothing(auto_everything):
    req = services.intake(dict(JUNK))
    assert req.status == ReferralRequest.Status.HELD
    assert req.held_at is not None
    assert "location" in req.held_reason
    # Nothing to the harvested address, nothing to the referral list.
    assert mail.outbox == []
    assert req.distributed_at is None
    assert req.acknowledged_at is None


def test_clean_request_still_flows_automatically(auto_everything):
    req = services.intake(dict(CLEAN))
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    assert req.acknowledged_at is not None
    assert req.distributed_at is not None


def test_distribute_refuses_a_held_request():
    req = services.intake(dict(JUNK))
    with pytest.raises(services.SuppressedStatusError):
        services.distribute(req)


def test_acknowledge_refuses_a_held_request():
    req = services.intake(dict(JUNK))
    with pytest.raises(services.SuppressedStatusError):
        services.send_acknowledgment(req)


def test_distribute_refuses_a_junk_request():
    req = services.intake(dict(CLEAN))
    req.status = ReferralRequest.Status.JUNK
    req.save(update_fields=["status"])
    with pytest.raises(services.SuppressedStatusError):
        services.distribute(req)


def test_release_resumes_the_normal_chain(auto_everything):
    req = services.intake(dict(JUNK))
    mail.outbox.clear()
    services.release(req)
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.DISTRIBUTED
    assert req.held_reason == ""
    assert req.held_at is None


def test_release_under_review_mode_only_clears_the_hold():
    config = ReferralSettings.load()
    config.ack_mode = Mode.REVIEW
    config.distribution_mode = Mode.REVIEW
    config.save()
    req = services.intake(dict(JUNK))
    services.release(req)
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.NEW
    assert req.distributed_at is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/test_intake_holding.py -v`
Expected: FAIL — `AttributeError: module 'referrals.services' has no attribute 'SuppressedStatusError'`

- [ ] **Step 3: Add the coordinator bell**

Append to `referrals/notifications.py`:

```python
def referral_held(request_obj) -> None:
    """Tell the Referral Coordinator a submission was held for review.

    Bell only, by design (task #479) — held requests are usually junk and
    should not add to the coordinator's inbox. A hold left unreviewed is
    escalated to email by ``process_referrals``.

    Superusers are deliberately *not* included: they implicitly pass the
    permission gate, but bell-notifying every superuser about every bot
    submission is noise. Only explicit role holders are told.
    """
    from core.models import StaffRole

    role = StaffRole.objects.filter(
        key=StaffRole.REFERRAL_COORDINATOR,
    ).first()
    if role is None:
        return
    for user in role.holders.all():
        notify(
            user, Category.REFERRAL_REQUEST,
            title=f"Referral request {request_obj.reference} held for review",
            body=request_obj.held_reason,
            url=reverse("referrals:detail", args=[request_obj.reference]),
            target=request_obj,
            dedupe=True,
        )
```

Verified: `core/access.py` has no role-holders helper, and `StaffRole` (`core/models.py:53`) carries a `holders` M2M (`core/models.py:97`) whose reverse accessor is `user.staff_roles`. Query the role directly as above; do not add a helper to `core/access.py` for one caller.

- [ ] **Step 4: Add the guards and the hold branch**

In `referrals/services.py`, add near the top (after `logger`):

```python
class SuppressedStatusError(RuntimeError):
    """Raised when a held or junk request is asked to send something.

    The hold in ``intake`` is the fix; this is what keeps it fixed. Any
    future caller — cron, view, admin action — hits this rather than
    quietly mailing 36 clinicians about a bot submission (task #479).
    """


def _refuse_if_suppressed(req: ReferralRequest, action: str) -> None:
    if req.status in ReferralRequest.SUPPRESSED_STATUSES:
        raise SuppressedStatusError(
            f"Refusing to {action} {req.reference}: status is "
            f"{req.get_status_display()}."
        )
```

Add as the first line of `send_acknowledgment`:

```python
    _refuse_if_suppressed(req, "acknowledge")
```

and as the first line of `distribute`:

```python
    _refuse_if_suppressed(req, "distribute")
```

In `intake`, replace everything from `req = ReferralRequest.objects.create(` through the end of the function with:

```python
    from . import screening

    held_reason = screening.screen(data)
    req = ReferralRequest.objects.create(
        name=data["name"],
        pronouns=data.get("pronouns", ""),
        email=data["email"],
        location=data["location"],
        language=data["language"],
        modalities=data.get("modality", ""),
        additional_information=data.get("additional_information", ""),
        status=(
            ReferralRequest.Status.HELD if held_reason
            else ReferralRequest.Status.NEW
        ),
        held_reason=held_reason,
        held_at=timezone.now() if held_reason else None,
    )
    if held_reason:
        # Nothing sends: not the coordinator inquiry, not the acknowledgment
        # to what may be a harvested address, not the distribution.
        logger.info("Held referral %s: %s", req.reference, held_reason)
        try:
            notifications.referral_held(req)
        except Exception:
            logger.exception(
                "Failed to notify the coordinator about held referral %s",
                req.reference,
            )
        return req

    try:
        emails.send_coordinator_inquiry(
            req, _absolute(reverse("referrals:detail", args=[req.reference])),
        )
    except Exception:
        logger.exception(
            "Failed to email referral inquiry %s to the coordinator",
            req.reference,
        )
    if config.ack_mode == Mode.AUTO:
        try:
            send_acknowledgment(req)
        except Exception:
            logger.exception(
                "Failed to send referral acknowledgment for %s", req.reference,
            )
    if config.distribution_mode == Mode.AUTO:
        try:
            distribute(req)
        except Exception:
            logger.exception(
                "Failed to auto-distribute referral %s", req.reference,
            )
    return req
```

Add `release` after `intake`:

```python
def release(req: ReferralRequest) -> ReferralRequest:
    """Clear a hold and resume the normal post-intake chain.

    A released request is treated exactly as a clean one would have been:
    the coordinator inquiry goes out, and the acknowledgment and
    distribution follow whatever the auto/review toggles say.
    """
    if req.status != ReferralRequest.Status.HELD:
        return req
    config = ReferralSettings.load()
    req.status = ReferralRequest.Status.NEW
    req.held_reason = ""
    req.held_at = None
    req.held_escalated_at = None
    req.save(update_fields=[
        "status", "held_reason", "held_at", "held_escalated_at",
    ])
    try:
        emails.send_coordinator_inquiry(
            req, _absolute(reverse("referrals:detail", args=[req.reference])),
        )
    except Exception:
        logger.exception(
            "Failed to email released referral %s to the coordinator",
            req.reference,
        )
    if config.ack_mode == Mode.AUTO:
        try:
            send_acknowledgment(req)
        except Exception:
            logger.exception(
                "Failed to acknowledge released referral %s", req.reference,
            )
    if config.distribution_mode == Mode.AUTO:
        try:
            distribute(req)
        except Exception:
            logger.exception(
                "Failed to distribute released referral %s", req.reference,
            )
    req.refresh_from_db()
    return req
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest referrals/ -v`
Expected: PASS, including the pre-existing `referrals/tests.py`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check referrals/
git add referrals/services.py referrals/notifications.py referrals/test_intake_holding.py
git commit -m "feat(referrals): hold screened submissions and guard the send paths (#479)"
```

---

### Task 5: Coordinator release, mark-junk, and dashboard surfacing

**Files:**
- Modify: `referrals/views.py` (three new views, dashboard context)
- Modify: `referrals/urls.py` (three new routes)
- Modify: `referrals/templates/referrals/detail.html`
- Modify: `referrals/templates/referrals/dashboard.html`
- Create: `referrals/test_coordinator_actions.py`

**Interfaces:**
- Consumes: `services.release` (Task 4); `ReferralRequest.Status.HELD` / `.JUNK`, `BlockedSubmission` (Task 2).
- Produces: URL names `referrals:release`, `referrals:mark_junk`, `referrals:unmark_junk`.

- [ ] **Step 1: Write the failing tests**

Create `referrals/test_coordinator_actions.py`:

```python
"""Coordinator release / mark-junk actions (#479)."""

import pytest
from django.urls import reverse

from accounts.models import User
from core.models import StaffRole
from referrals import services
from referrals.models import ReferralRequest

pytestmark = pytest.mark.django_db

JUNK = {
    "name": "LEIAZKMKtfUBswyJuaS",
    "pronouns": "IzNydkEnQFrKxxKl",
    "email": "spam@example.com",
    "location": "lfNxcMPRAZNciaxtfNPOMQK",
    "language": "iIcIlrhZIIwEImoxJld",
    "modality": "In person",
    "additional_information": "GtDlqAgHoujeYbXggDwPs",
}


@pytest.fixture
def coordinator(client):
    user = User.objects.create_user(
        email="coord@example.com", password="pw12345!", is_superuser=True,
        is_staff=True,
    )
    client.force_login(user)
    return user


def test_mark_junk_sets_status_and_audit_note(client, coordinator):
    req = services.intake(dict(JUNK))
    resp = client.post(reverse("referrals:mark_junk", args=[req.reference]))
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.JUNK
    assert "junk" in req.coordinator_notes.lower()
    assert coordinator.email in req.coordinator_notes


def test_unmark_junk_restores_to_new(client, coordinator):
    req = services.intake(dict(JUNK))
    client.post(reverse("referrals:mark_junk", args=[req.reference]))
    client.post(reverse("referrals:unmark_junk", args=[req.reference]))
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.NEW


def test_release_clears_the_hold(client, coordinator):
    req = services.intake(dict(JUNK))
    assert req.status == ReferralRequest.Status.HELD
    client.post(reverse("referrals:release", args=[req.reference]))
    req.refresh_from_db()
    assert req.status != ReferralRequest.Status.HELD
    assert req.held_reason == ""


def test_actions_require_the_coordinator_role(client):
    req = services.intake(dict(JUNK))
    user = User.objects.create_user(email="nobody@example.com", password="pw12345!")
    client.force_login(user)
    resp = client.post(reverse("referrals:mark_junk", args=[req.reference]))
    assert resp.status_code == 403


def test_dashboard_shows_held_count(client, coordinator):
    services.intake(dict(JUNK))
    resp = client.get(reverse("referrals:dashboard"))
    assert resp.context["held_count"] == 1


def test_dashboard_filters_to_held(client, coordinator):
    services.intake(dict(JUNK))
    resp = client.get(reverse("referrals:dashboard"), {"status": "held"})
    assert list(resp.context["requests"])[0].status == ReferralRequest.Status.HELD


def test_junk_is_excluded_from_the_open_filter(client, coordinator):
    req = services.intake(dict(JUNK))
    client.post(reverse("referrals:mark_junk", args=[req.reference]))
    resp = client.get(reverse("referrals:dashboard"), {"status": "open"})
    assert list(resp.context["requests"]) == []
```

Adjust the `coordinator` fixture if `User.objects.create_user` in this codebase needs different arguments — check `referrals/tests.py` for the existing pattern and copy it, including how it grants `StaffRole.REFERRAL_COORDINATOR`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/test_coordinator_actions.py -v`
Expected: FAIL — `NoReverseMatch: 'mark_junk' is not a valid view function or pattern name`

- [ ] **Step 3: Add the views**

In `referrals/views.py`, after `reopen`:

```python
@coordinator_required
@require_POST
def release(request, reference):
    """Clear a screening hold: the request resumes the normal chain."""
    req = _get_request(reference)
    services.release(req)
    messages.success(
        request,
        f"{req.reference} released. It now follows the normal workflow.",
    )
    return redirect("referrals:detail", reference=reference)


def _audit_note(req, request, text: str) -> None:
    """Append a stamped line to coordinator_notes (the override trail)."""
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{stamp}] {text} — {request.user.email}"
    req.coordinator_notes = (
        f"{req.coordinator_notes}\n{line}".strip()
        if req.coordinator_notes else line
    )


@coordinator_required
@require_POST
def mark_junk(request, reference):
    """Mark a request as junk. Available on any status — this is the escape
    hatch for the coherent-but-fake submission no heuristic will catch."""
    req = _get_request(reference)
    req.status = ReferralRequest.Status.JUNK
    _audit_note(req, request, "Marked as junk")
    req.save(update_fields=["status", "coordinator_notes"])
    messages.success(request, f"{req.reference} marked as junk.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def unmark_junk(request, reference):
    """Undo a junk marking; the request returns to the normal workflow."""
    req = _get_request(reference)
    req.status = ReferralRequest.Status.NEW
    req.held_reason = ""
    req.held_at = None
    _audit_note(req, request, "Unmarked as junk")
    req.save(update_fields=[
        "status", "held_reason", "held_at", "coordinator_notes",
    ])
    messages.success(request, f"{req.reference} restored.")
    return redirect("referrals:detail", reference=reference)
```

- [ ] **Step 4: Add the dashboard context**

In `referrals/views.py`, in `dashboard`, add to the render context:

```python
        "held_count": ReferralRequest.objects.filter(
            status=ReferralRequest.Status.HELD,
        ).count(),
        "blocked_30d": BlockedSubmission.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=30),
        ).count(),
```

and add the imports `from datetime import timedelta` and `BlockedSubmission` to the `.models` import block.

- [ ] **Step 5: Add the routes**

In `referrals/urls.py`, beside the `close`/`reopen` routes:

```python
    path(f"{_ADMIN}/<str:reference>/release/", views.release, name="release"),
    path(f"{_ADMIN}/<str:reference>/junk/", views.mark_junk, name="mark_junk"),
    path(f"{_ADMIN}/<str:reference>/unjunk/", views.unmark_junk,
         name="unmark_junk"),
```

- [ ] **Step 6: Add the templates**

In `referrals/templates/referrals/detail.html`, add above the existing action buttons:

```django
{% if req.status == "held" %}
<div role="alert" class="alert alert-warning">
  <div>
    <p class="font-medium">Held for review, nothing has been sent.</p>
    <p class="text-sm">{{ req.held_reason }}</p>
    <p class="text-xs opacity-70">
      No acknowledgment went to the requester and the referral list has not
      been contacted. Release it to resume the normal workflow, or mark it
      junk.
    </p>
  </div>
  <div class="flex gap-2">
    <form method="post" action="{% url 'referrals:release' req.reference %}">
      {% csrf_token %}
      <button class="btn btn-sm btn-primary">Release</button>
    </form>
    <form method="post" action="{% url 'referrals:mark_junk' req.reference %}">
      {% csrf_token %}
      <button class="btn btn-sm btn-ghost">Mark as junk</button>
    </form>
  </div>
</div>
{% elif req.status == "junk" %}
<div role="alert" class="alert">
  <p class="text-sm">Marked as junk.</p>
  <form method="post" action="{% url 'referrals:unmark_junk' req.reference %}">
    {% csrf_token %}
    <button class="btn btn-sm btn-ghost">Not junk</button>
  </form>
</div>
{% else %}
<form method="post" action="{% url 'referrals:mark_junk' req.reference %}">
  {% csrf_token %}
  <button class="btn btn-sm btn-ghost">Mark as junk</button>
</form>
{% endif %}
```

Match the surrounding markup in that file — read it first and follow its button and card conventions rather than pasting this verbatim if it clashes.

In `referrals/templates/referrals/dashboard.html`, add near the existing open-count heading:

```django
{% if held_count %}
<a href="?status=held" class="badge badge-warning gap-1">
  {{ held_count }} held for review
</a>
{% endif %}
{% if blocked_30d %}
<span class="text-xs text-base-content/60">
  {{ blocked_30d }} automated submission{{ blocked_30d|pluralize }} blocked in
  the last 30 days
</span>
{% endif %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest referrals/ -v`
Expected: PASS

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check referrals/
git add referrals/views.py referrals/urls.py referrals/templates/ referrals/test_coordinator_actions.py
git commit -m "feat(referrals): release, mark-junk, and held/blocked surfacing (#479)"
```

---

### Task 6: Daily escalation and counter pruning

**Files:**
- Modify: `referrals/services.py` (`escalate_stale_holds`, `prune_blocked_submissions`)
- Modify: `referrals/emails.py` (`send_held_escalation`)
- Modify: `referrals/management/commands/process_referrals.py`
- Create: `referrals/test_escalation.py`

**Interfaces:**
- Consumes: `ReferralRequest.Status.HELD`, `.held_at`, `.held_escalated_at`, `ReferralSettings.held_escalation_days`, `BlockedSubmission` (Task 2).
- Produces:
  - `services.escalate_stale_holds(now=None) -> int`
  - `services.prune_blocked_submissions(now=None) -> int`
  - `emails.send_held_escalation(request_obj, manage_url: str) -> None`

- [ ] **Step 1: Write the failing tests**

Create `referrals/test_escalation.py`:

```python
"""Stale-hold escalation and counter pruning (#479)."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from referrals import services
from referrals.models import BlockedSubmission, ReferralRequest, ReferralSettings

pytestmark = pytest.mark.django_db


def _held(age_days: int) -> ReferralRequest:
    req = ReferralRequest.objects.create(
        name="Maybe Real", email="person@example.com", location="Pittsburgh",
        language="English", status=ReferralRequest.Status.HELD,
        held_reason="The description is only 12 characters.",
    )
    ReferralRequest.objects.filter(pk=req.pk).update(
        held_at=timezone.now() - timedelta(days=age_days),
    )
    req.refresh_from_db()
    return req


def test_fresh_hold_is_not_escalated():
    _held(age_days=1)
    assert services.escalate_stale_holds() == 0
    assert mail.outbox == []


def test_stale_hold_is_escalated_once():
    req = _held(age_days=5)
    assert services.escalate_stale_holds() == 1
    assert len(mail.outbox) == 1
    req.refresh_from_db()
    assert req.held_escalated_at is not None
    # Second run must not re-send.
    assert services.escalate_stale_holds() == 0
    assert len(mail.outbox) == 1


def test_released_hold_is_not_escalated():
    req = _held(age_days=5)
    req.status = ReferralRequest.Status.NEW
    req.save(update_fields=["status"])
    assert services.escalate_stale_holds() == 0


def test_escalation_threshold_follows_settings():
    config = ReferralSettings.load()
    config.held_escalation_days = 10
    config.save()
    _held(age_days=5)
    assert services.escalate_stale_holds() == 0


def test_prune_drops_rows_over_a_year_old():
    old = BlockedSubmission.objects.create(
        reason=BlockedSubmission.Reason.HONEYPOT,
    )
    BlockedSubmission.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=400),
    )
    BlockedSubmission.objects.create(reason=BlockedSubmission.Reason.TIMING)
    assert services.prune_blocked_submissions() == 1
    assert BlockedSubmission.objects.count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/test_escalation.py -v`
Expected: FAIL — `AttributeError: module 'referrals.services' has no attribute 'escalate_stale_holds'`

- [ ] **Step 3: Add the escalation email**

Append to `referrals/emails.py`. This mirrors `send_coordinator_inquiry` (same `_coordinator_from()` sender, same `referrals_address()` recipient, same `_html_alternative()` HTML part), but **without** a `reply_to` of the requester — replying to a suspected bot's harvested address is the last thing we want.

```python
def send_held_escalation(request_obj, manage_url: str) -> None:
    """One reminder that a held submission is still unreviewed.

    Held requests ring the bell only, by design. This is the backstop so a
    genuine requester wrongly held cannot wait indefinitely (task #479).

    Unlike ``send_coordinator_inquiry`` this sets no Reply-To: a held
    request may well be a bot using a stranger's address, and a stray reply
    to it is exactly the unsolicited mail the hold exists to prevent.
    """
    body = (
        f"Referral request {request_obj.reference} was held by the spam "
        f"screen and has not been reviewed.\n\n"
        f"Reason: {request_obj.held_reason}\n\n"
        f"Nothing has been sent to the requester and the referral list has "
        f"not been contacted. If this is a real request, release it:\n\n"
        f"{manage_url}\n"
    )
    msg = EmailMultiAlternatives(
        subject=(
            f"Referral {request_obj.reference} is still held for review"
        ),
        body=body,
        from_email=_coordinator_from(),
        to=[referrals_address()],
    )
    msg.attach_alternative(_html_alternative(body), "text/html")
    msg.send(fail_silently=False)
```

Verified against `referrals/emails.py`: `referrals_address()`, `_coordinator_from()`, and `_html_alternative()` all already exist there, and `EmailMultiAlternatives` is already imported. No refactor needed.

- [ ] **Step 4: Add the services**

Append to `referrals/services.py`:

```python
#: How long a content-free BlockedSubmission row is kept.
BLOCKED_RETENTION_DAYS = 365


def escalate_stale_holds(now=None) -> int:
    """Email the coordinator about holds left unreviewed past the threshold.

    Sends once per request (``held_escalated_at``). Returns how many were
    escalated.
    """
    config = ReferralSettings.load()
    now = now or timezone.now()
    cutoff = now - timedelta(days=config.held_escalation_days)
    stale = ReferralRequest.objects.filter(
        status=ReferralRequest.Status.HELD,
        held_at__lte=cutoff,
        held_escalated_at__isnull=True,
    )
    count = 0
    for req in stale:
        try:
            emails.send_held_escalation(
                req,
                _absolute(reverse("referrals:detail", args=[req.reference])),
            )
        except Exception:
            logger.exception(
                "Failed to escalate held referral %s", req.reference,
            )
            continue
        req.held_escalated_at = now
        req.save(update_fields=["held_escalated_at"])
        count += 1
    return count


def prune_blocked_submissions(now=None) -> int:
    """Drop blocked-submission counter rows past their retention."""
    from .models import BlockedSubmission

    now = now or timezone.now()
    cutoff = now - timedelta(days=BLOCKED_RETENTION_DAYS)
    deleted, _ = BlockedSubmission.objects.filter(
        created_at__lt=cutoff,
    ).delete()
    return deleted
```

- [ ] **Step 5: Wire the command**

In `referrals/management/commands/process_referrals.py`, extend the module docstring's job list with:

```
* Escalate any submission held by the spam screen that has sat unreviewed
  past ``held_escalation_days``, and prune expired blocked-submission
  counter rows.
```

In `handle`, before the final success line (and inside the non-dry-run path):

```python
        escalated = services.escalate_stale_holds(now)
        pruned = services.prune_blocked_submissions(now)
```

and extend the success message:

```python
        self.stdout.write(self.style.SUCCESS(
            f"Sent {sent} follow-up(s), redacted {purged} request(s), "
            f"escalated {escalated} held request(s), pruned {pruned} "
            f"blocked-submission row(s). Errors: {errored}."
        ))
```

In the `--dry-run` branch, add a line reporting how many holds *would* be escalated, using the same filter but without sending.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest referrals/ -v`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check referrals/
git add referrals/services.py referrals/emails.py referrals/management/commands/process_referrals.py referrals/test_escalation.py
git commit -m "feat(referrals): escalate stale holds and prune the blocked counter (#479)"
```

---

### Task 7: Coordinator guide, project docs, and the prod cleanup

**Files:**
- Modify: `core/docs/referrals-guide.md`
- Modify: `CLAUDE.md` (status section)
- Create: `referrals/management/commands/mark_referral_junk.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `manage.py mark_referral_junk <reference> [--note TEXT]`

- [ ] **Step 1: Write the failing test**

Append to `referrals/test_coordinator_actions.py`:

```python
def test_mark_referral_junk_command(capsys):
    from django.core.management import call_command

    req = services.intake(dict(JUNK))
    call_command("mark_referral_junk", req.reference, "--note", "bot, task #479")
    req.refresh_from_db()
    assert req.status == ReferralRequest.Status.JUNK
    assert "bot, task #479" in req.coordinator_notes
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest referrals/test_coordinator_actions.py::test_mark_referral_junk_command -v`
Expected: FAIL — `CommandError: Unknown command: 'mark_referral_junk'`

- [ ] **Step 3: Write the command**

Create `referrals/management/commands/mark_referral_junk.py`:

```python
"""Mark a referral request as junk from the command line.

Exists for the prod cleanup of 26-0727 (task #479), which predates the
JUNK status. The coordinator's normal route is the button on the request
page; this is for one-off staff work over SSM where no browser is handy.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from referrals.models import ReferralRequest


class Command(BaseCommand):
    help = "Mark a referral request as junk, with an audit note."

    def add_arguments(self, parser):
        parser.add_argument("reference", help="e.g. 26-0727")
        parser.add_argument(
            "--note", default="Marked as junk",
            help="Text appended to the coordinator notes.",
        )

    def handle(self, *args, **opts):
        try:
            req = ReferralRequest.objects.get(reference=opts["reference"])
        except ReferralRequest.DoesNotExist:
            raise CommandError(f"No referral request {opts['reference']!r}.")

        stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
        line = f"[{stamp}] {opts['note']} — manage.py mark_referral_junk"
        req.coordinator_notes = (
            f"{req.coordinator_notes}\n{line}".strip()
            if req.coordinator_notes else line
        )
        req.status = ReferralRequest.Status.JUNK
        req.save(update_fields=["status", "coordinator_notes"])
        self.stdout.write(self.style.SUCCESS(
            f"{req.reference} marked as junk."
        ))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest referrals/ -v`
Expected: PASS

- [ ] **Step 5: Update the coordinator guide**

Add a section to `core/docs/referrals-guide.md`. Mind the rendered-markdown gotcha: a `+`, `-`, or `*` starting a wrapped line inside a list item silently becomes a nested bullet.

```markdown
## Held submissions and junk

Some submissions are automated. In July 2026 a bot filled every field on the
Find-an-Analyst form with random text, and because acknowledgment and
distribution were both set to automatic, it was acknowledged to a stranger's
address and sent to the whole referral list before anyone saw it.

Two things now sit in front of that.

Submissions that are obviously automated are dropped before they ever become a
request. You never see them. The dashboard shows a count of how many were
blocked in the last 30 days, so you can tell the screen is working.

Submissions that only look suspicious are **held**. A held request is on the
dashboard behind the "held for review" badge, and it rings your notification
bell. Nothing has been sent: no acknowledgment to the requester, no message to
the referral list. You have two buttons:

1. **Release** puts it back into the normal workflow, exactly as if it had
   never been held. If acknowledgment and distribution are set to automatic,
   they happen the moment you release it.
2. **Mark as junk** closes it out. Junk requests are hidden from the open list.

If a held request sits unreviewed for a few days, you get an email about it.
That threshold is the "held escalation days" setting.

The screen is deliberately cautious, so it will sometimes hold a real request:
an unusual name or a very short description can trip it. That is why it holds
rather than deletes. **Mark as junk** is also available on any request, for the
occasional submission that is clearly not a real referral but was written by a
person and so could never be caught automatically.
```

- [ ] **Step 6: Update CLAUDE.md**

Add to the Status section's list, after the "Direct admission" entry, following the surrounding entries' voice and level of detail:

```markdown
- **Referral spam screening** (task #479). Referral request `26-0727` was a
  commodity form-spam bot: every visible text input filled with a random
  mixed-case token, every checkbox checked, and a harvested real address in
  the email field. It got through because `ReferralRequestForm`'s honeypot was
  a `forms.HiddenInput` — `type="hidden"`, the one variant commodity bots skip
  on purpose — while the signup form's (task #471, `accounts/antibot.py`) is a
  CSS-hidden **text** input, which this bot demonstrably would have filled.
  Prod runs `ack=auto dist=auto`, so the school auto-acknowledged a stranger
  and distributed gibberish to the entire referral list; one clinician
  responded to it. Now two layers. **Transport** (`accounts/antibot.py`, newly
  adopted here with a per-form `looks_too_fast(minimum=…)` — 10s for this
  two-step wizard vs. signup's 2s) drops near-certain bots to the ordinary
  thank-you page, recording a deliberately **content-free** `BlockedSubmission`
  row (timestamp + reason, no address, no IP, nothing to leak) so the hit rate
  is visible — without it, a screen that silently broke and started eating real
  requests would look identical to one that works. **Content**
  (`referrals/screening.py`, a pure function) puts anything suspicious into the
  new `Status.HELD`: not acknowledged, not distributed, bell to the coordinator
  only, with `services.SuppressedStatusError` guarding `send_acknowledgment`
  and `distribute` so no future caller can leak one. The heuristics are
  gibberish detection (≥8 chars, `isalpha()`, ≥4 upper/lower transitions), a
  40-character narrative floor, and URL markers. **Vowel ratio was specified,
  built, and rejected**: at any threshold catching the junk it also flags
  `Pittsburgh` (0.20 — an actually-submitted location), `Frankfurt`, and
  `they/them`; case transitions separate the populations cleanly (junk scores
  5–15, every real value scores 1). The screen only ever *holds* — `JUNK` is
  set by a human, via a Mark-as-junk button available on any request for the
  coherent-but-fake submission no heuristic will catch. `process_referrals`
  escalates a hold left unreviewed past `held_escalation_days` (default 3) to
  one email, bounding what a false positive costs someone in distress. Design:
  `docs/superpowers/specs/2026-07-27-referral-spam-screening-design.md`.
```

- [ ] **Step 7: Full suite, lint, commit**

```bash
uv run pytest
uv run ruff check .
git add core/docs/referrals-guide.md CLAUDE.md referrals/
git commit -m "docs(referrals): coordinator guide and status entry for spam screening (#479)"
```

- [ ] **Step 8: Deploy and clean up prod**

Merge to `main` and confirm the Deploy workflow goes **green** — a single failing test silently aborts the deploy, so a successful push is not a deploy (`pushed-is-not-deployed`).

Then mark the original junk request, over SSM (the service is `web_blue` or `web_green`, never `web` — find it with `docker compose ps --services --status running`):

```bash
uv run python manage.py mark_referral_junk 26-0727 --note "Bot submission, task #479"
```

Finally, confirm on prod that `ReferralSettings.held_escalation_days` is 3 and that no genuine request was retro-held by the migration (screening runs at intake only, so none should be — verify `ReferralRequest.objects.filter(status="held").count() == 0`).

---

## Self-Review

**Spec coverage.** §1 split → Tasks 1 and 3. §2 form fix → Task 3. §3 states/fields → Task 2. §4 intake branch and guards → Task 4. §5 coordinator actions → Task 5. §6 heuristics → Task 1. §7 blocked counter → Tasks 2 (model), 3 (recording), 5 (display), 6 (pruning). §8 escalation → Task 6. §9 tests → distributed across every task, with the real payloads in Tasks 1 and 4. §10 ops → Task 7.

**Deviation from the spec, deliberate:** `screen()` returns a reason string (empty when clean) rather than the `(suspicious, reason)` tuple the spec describes. The reason doubles as the boolean, so the tuple carried no information. Noted here rather than silently changed.

**Known ordering constraint:** Task 3's tests import `BlockedSubmission`, so Task 2 must land first. Task 4 imports `screening`, so Task 1 must land first. Tasks 1 and 2 are independent of each other and can run in parallel; 3 and 4 both depend on them; 5 depends on 4; 6 depends on 2; 7 depends on all.

**Codebase facts verified while writing this plan**, so no task rests on a guess: `core/access.py` has no role-holders helper and `StaffRole.holders` is the M2M to query (`core/models.py:97`); `referrals/emails.py` already provides `referrals_address()`, `_coordinator_from()`, and `_html_alternative()`; the public URL name is `find_an_analyst` (`config/urls.py:54`); `accounts/views.py` already defines `logger` (line 48); `.hp-wrap` exists in `assets/css/input.css:853` and is the class the signup template uses (`signup.html:39`) — note the *widget* class in `LightSignupForm` is `hp-field`, which has no CSS rule and does nothing, so the wrapper div is what actually hides the input.

**One judgement call left to the implementer:** Task 5 Step 6's template markup should follow whatever card and button conventions `detail.html` and `dashboard.html` already use; the blocks given are correct Django but may need reshaping to match. That is styling, not behavior, and the tests in Step 1 pin the behavior.
