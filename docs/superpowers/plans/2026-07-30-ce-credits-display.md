# CE Credits and Accreditor Logos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let faculty record that an event is approved for continuing-education credits and display the accrediting bodies' logos compactly at the bottom of the About section on the event page and the Workspace Overview tab.

**Architecture:** A shared `events.CEOrganization` library (name, logo, url, statement) that grows by use, linked to `Event` by a `ManyToMany`; the credit count and its total/per-meeting basis live on the `Event`. Everything is edited on the existing event edit form, gated by the existing `can_edit_event`. One shared template partial renders it, included from `events/_event_summary.html`, which both surfaces already share.

**Tech Stack:** Django 5.2, pytest-django, Pillow, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-07-30-ce-credits-display-design.md`

## Global Constraints

- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both must be green before every commit.
- Python line length 100 (ruff `E`, `F`, `I`, `UP`).
- **Tailwind classes set in Python must also appear literally in some `.html` file** or the production CSS build drops them. Every widget class this plan sets in `events/forms.py` (`input input-bordered input-sm`, `select select-bordered select-sm`, `textarea textarea-bordered`) already appears in existing templates. Do not invent new ones in Python.
- Use DaisyUI semantic tokens (`bg-base-100`, `text-base-content`, …) in templates, **except** the deliberate paper-white logo chips described in Task 3, which carry an explaining comment.
- Member-facing copy uses commas, not em dashes.
- This worktree is `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/calm-willow`. Edit files there, not in the main repo checkout.
- Do not add CE fields to `events/review.py::REVIEWABLE_FIELDS`. CE applies immediately.

---

### Task 1: CE data model

**Files:**
- Create: `events/ce.py`
- Modify: `events/models.py` (add `CEOrganization` after `Speaker` ~line 190; add CE fields to `Event` after `open_to_guests`; add CE fields to `EventProposal` after `offers_ce` ~line 1117; add three kwargs to the `Event.objects.create(...)` call in `EventProposal.approve()` ~line 1302)
- Modify: `events/admin.py`
- Create: `events/migrations/0039_ce_credits.py` (generated)
- Test: `events/test_ce.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `events.ce.CECreditBasis` — `models.TextChoices` with `TOTAL = "total", "in total"` and `PER_MEETING = "per_meeting", "per meeting"`.
  - `events.ce.credits_label(offers_ce: bool, credits: Decimal | None, basis: str) -> str`.
  - `events.models.CEOrganization` with fields `name`, `logo`, `url`, `statement`, `added_by`, `created_at`.
  - `Event.offers_ce`, `Event.ce_credits`, `Event.ce_credits_basis`, `Event.ce_note`, `Event.ce_organizations`, and the property `Event.ce_credits_label`.
  - `EventProposal.ce_credits`, `EventProposal.ce_credits_basis`, and the property `EventProposal.ce_credits_label`.

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce.py`:

```python
"""CE credits + accreditor organizations (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import User
from events.ce import CECreditBasis, credits_label
from events.models import CEOrganization, Event, EventProposal


# ---- Credit-line phrasing ----------------------------------------------


def test_label_is_empty_when_ce_is_off():
    assert credits_label(False, Decimal("2"), CECreditBasis.TOTAL) == ""


def test_label_without_a_count_says_credits_are_available():
    assert credits_label(True, None, CECreditBasis.TOTAL) == "CE credits available."


def test_label_for_a_total():
    assert credits_label(True, Decimal("6.00"), CECreditBasis.TOTAL) == (
        "Approved for 6 CE credits."
    )


def test_label_per_meeting():
    assert credits_label(True, Decimal("2.00"), CECreditBasis.PER_MEETING) == (
        "Approved for 2 CE credits per meeting."
    )


def test_label_keeps_a_half_credit():
    assert credits_label(True, Decimal("1.50"), CECreditBasis.TOTAL) == (
        "Approved for 1.5 CE credits."
    )


def test_label_singular_for_one_credit():
    assert credits_label(True, Decimal("1.00"), CECreditBasis.PER_MEETING) == (
        "Approved for 1 CE credit per meeting."
    )


def test_label_does_not_go_scientific_on_round_tens():
    assert credits_label(True, Decimal("20.00"), CECreditBasis.TOTAL) == (
        "Approved for 20 CE credits."
    )


# ---- CEOrganization -----------------------------------------------------


@pytest.mark.django_db
def test_organization_names_are_unique_case_insensitively():
    CEOrganization.objects.create(name="American Psychological Association")
    with pytest.raises(IntegrityError), transaction.atomic():
        CEOrganization.objects.create(name="american psychological association")


def test_negative_credits_are_rejected():
    """Checked on the field's validators rather than through full_clean(), so
    the test can't fail for unrelated missing-field reasons."""
    field = Event._meta.get_field("ce_credits")
    with pytest.raises(ValidationError):
        field.run_validators(Decimal("-1"))


# ---- Proposal → Event carry --------------------------------------------


@pytest.mark.django_db
def test_approve_carries_ce_intent_onto_the_minted_event():
    proposer = User.objects.create_user(email="proposer@x.test")
    reviewer = User.objects.create_user(email="pc@x.test")
    proposal = EventProposal.objects.create(
        proposed_by=proposer,
        event_type=Event.Type.SEMINAR,
        title="Seminar on the Sinthome",
        description="A year with Seminar XXIII.",
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        offers_ce=True,
        ce_credits=Decimal("2.00"),
        ce_credits_basis=CECreditBasis.PER_MEETING,
    )
    event = proposal.approve(reviewer)
    assert event.offers_ce is True
    assert event.ce_credits == Decimal("2.00")
    assert event.ce_credits_basis == CECreditBasis.PER_MEETING
    assert event.ce_credits_label == "Approved for 2 CE credits per meeting."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce.py -v -p no:xdist`
Expected: FAIL, collection error `ModuleNotFoundError: No module named 'events.ce'`.

- [ ] **Step 3: Create the CE helper module**

Create `events/ce.py`:

```python
"""Continuing-education credits (task #486).

The credit sentence is shared by the ``Event`` (what the public page shows) and
the ``EventProposal`` (the estimate the Programming Committee sees in its
queue), so the phrasing lives here rather than in either model.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models


class CECreditBasis(models.TextChoices):
    """Whether a credit count covers the whole event or each meeting.

    A one-day special event quotes a total; a year-long seminar quotes credits
    per meeting, since its total depends on how many meetings actually happen.
    """

    TOTAL = "total", "in total"
    PER_MEETING = "per_meeting", "per meeting"


def _plain(amount: Decimal) -> str:
    """``Decimal`` as a human would write it: 6.00 -> "6", 1.50 -> "1.5".

    ``normalize()`` alone turns 20.00 into 2E+1, so the result is formatted
    with ``:f`` to force plain notation.
    """
    return f"{amount.normalize():f}"


def credits_label(offers_ce: bool, credits: Decimal | None, basis: str) -> str:
    """The one-line CE sentence for an event, or "" when CE is off.

    An event can be marked as offering CE before the body has told the faculty
    member how many credits it carries, so a missing count is a normal state
    rather than an error.
    """
    if not offers_ce:
        return ""
    if credits is None:
        return "CE credits available."
    unit = "credit" if credits == 1 else "credits"
    suffix = " per meeting" if basis == CECreditBasis.PER_MEETING else ""
    return f"Approved for {_plain(credits)} CE {unit}{suffix}."
```

- [ ] **Step 4: Add the `CEOrganization` model**

In `events/models.py`, add these imports near the existing ones at the top of the file:

```python
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db.models.functions import Lower

from .ce import CECreditBasis, credits_label
```

Then add the model immediately after the `Speaker` class (before `class SpeakerInvitation`):

```python
class CEOrganization(models.Model):
    """A body that accredits events for continuing-education credits.

    A shared library rather than a per-event upload: the same accreditor
    approves many events, and its logo and mandated approval language should be
    correctable in one place. Faculty add an entry inline when theirs is not
    listed yet, so nobody curates the collection, it accretes from use.
    """

    name = models.CharField(max_length=120)
    logo = models.ImageField(upload_to="ce-organizations/")
    url = models.URLField(
        blank=True,
        help_text="The organization's site. Links the logo when set.",
    )
    statement = models.TextField(
        blank=True,
        help_text="Approval language this body requires on approved events. "
        "Shown under its logo on every event that claims it.",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ce_organizations_added",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), name="ce_organization_name_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 5: Add the CE fields to `Event`**

In `events/models.py`, find the `open_to_guests` field on `Event` and add immediately after it:

```python
    # ---- Continuing education (task #486) ----
    #: Master switch. Ticked once an accrediting body has approved the event;
    #: drives whether the CE panel renders at all.
    offers_ce = models.BooleanField(
        default=False, verbose_name="Approved for CE credits",
    )
    ce_credits = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Leave blank if the body has not set a count yet.",
    )
    ce_credits_basis = models.CharField(
        max_length=12, choices=CECreditBasis.choices, default=CECreditBasis.TOTAL,
    )
    ce_note = models.TextField(
        blank=True,
        help_text="Anything specific to this event, e.g. full attendance "
        "required for credit.",
    )
    ce_organizations = models.ManyToManyField(
        "events.CEOrganization", blank=True, related_name="events",
        verbose_name="Approved by",
    )
```

And add this property to `Event` (next to its other display properties):

```python
    @property
    def ce_credits_label(self) -> str:
        """The public CE sentence, or "" when this event offers no credits."""
        return credits_label(self.offers_ce, self.ce_credits, self.ce_credits_basis)
```

- [ ] **Step 6: Add the estimate fields to `EventProposal` and carry them at approval**

In `events/models.py`, directly after `EventProposal.offers_ce`:

```python
    #: The count the proposer *expects* to offer. Accreditation happens after
    #: the proposal (faculty apply to GPPA separately), so this is an estimate;
    #: the real figure is confirmed on the event edit form once approval lands.
    ce_credits = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="If you know it yet. You can set or change this later.",
    )
    ce_credits_basis = models.CharField(
        max_length=12, choices=CECreditBasis.choices, default=CECreditBasis.TOTAL,
    )
```

Add the matching property to `EventProposal`:

```python
    @property
    def ce_credits_label(self) -> str:
        return credits_label(self.offers_ce, self.ce_credits, self.ce_credits_basis)
```

In `EventProposal.approve()`, add three kwargs to the existing `Event.objects.create(...)` call, after `contact=self.contact,`:

```python
            offers_ce=self.offers_ce,
            ce_credits=self.ce_credits,
            ce_credits_basis=self.ce_credits_basis,
```

- [ ] **Step 7: Register the organization admin**

In `events/admin.py`, add `CEOrganization` to the existing `from .models import ...` line, then append:

```python
@admin.register(CEOrganization)
class CEOrganizationAdmin(admin.ModelAdmin):
    """Staff escape hatch: replace a bad logo, correct mandated wording, or
    delete a duplicate that slipped past the case-insensitive name guard."""

    list_display = ("name", "url", "added_by", "created_at")
    search_fields = ("name",)
    readonly_fields = ("created_at",)
```

- [ ] **Step 8: Generate the migration**

Run: `uv run python manage.py makemigrations events -n ce_credits`
Expected: creates `events/migrations/0039_ce_credits.py` containing the new model, four `Event` fields, and two `EventProposal` fields. Read the generated file and confirm there is no `RemoveField` or data operation in it.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce.py -v -p no:xdist`
Expected: PASS, 10 tests.

- [ ] **Step 10: Run the full events suite and lint**

Run: `uv run pytest events/ -q && uv run ruff check .`
Expected: all pass, no lint errors.

- [ ] **Step 11: Commit**

```bash
git add events/ce.py events/models.py events/admin.py events/migrations/0039_ce_credits.py events/test_ce.py
git commit -m "feat(events): record CE credits and accreditor organizations (#486)"
```

---

### Task 2: Logo normalization

**Files:**
- Create: `events/ce_images.py`
- Test: `events/test_ce_images.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `events.ce_images.InvalidImage` — a `ValueError` subclass.
  - `events.ce_images.MAX_UPLOAD_BYTES` — `int`, 8 MB.
  - `events.ce_images.normalize_logo(source) -> django.core.files.base.ContentFile` — WebP bytes, aspect ratio and alpha preserved, fitted inside `MAX_BOX`.

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce_images.py`:

```python
"""Accreditor-logo normalization (task #486)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from events.ce_images import InvalidImage, normalize_logo


def _png_bytes(size=(400, 200), mode="RGBA", color=(10, 20, 30, 255)) -> bytes:
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_output_is_webp():
    out = normalize_logo(io.BytesIO(_png_bytes()))
    assert Image.open(io.BytesIO(out.read())).format == "WEBP"


def test_a_small_logo_is_left_at_its_own_size():
    out = normalize_logo(io.BytesIO(_png_bytes(size=(300, 120))))
    assert Image.open(io.BytesIO(out.read())).size == (300, 120)


def test_an_oversized_logo_is_fitted_inside_the_box_without_distortion():
    out = normalize_logo(io.BytesIO(_png_bytes(size=(4000, 1000))))
    width, height = Image.open(io.BytesIO(out.read())).size
    assert width <= 800 and height <= 400
    assert width == 800 and height == 200      # 4:1 aspect ratio preserved


def test_transparency_survives():
    """A wordmark is dark-on-transparent; flattening it onto white would put a
    hard rectangle on the page."""
    src = io.BytesIO(_png_bytes(size=(200, 100), color=(10, 20, 30, 0)))
    out = normalize_logo(src)
    img = Image.open(io.BytesIO(out.read()))
    assert img.mode == "RGBA"
    assert img.getpixel((100, 50))[3] == 0


def test_an_opaque_logo_is_accepted():
    out = normalize_logo(io.BytesIO(_png_bytes(mode="RGB", color=(200, 30, 30))))
    assert Image.open(io.BytesIO(out.read())).format == "WEBP"


def test_a_non_image_is_rejected():
    with pytest.raises(InvalidImage):
        normalize_logo(io.BytesIO(b"this is definitely not an image"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_images.py -v -p no:xdist`
Expected: FAIL, `ModuleNotFoundError: No module named 'events.ce_images'`.

- [ ] **Step 3: Write the implementation**

Create `events/ce_images.py`:

```python
"""Accreditor-logo processing (task #486).

Deliberately *not* ``accounts.images``: that pipeline force-crops to a centred
square and flattens transparency onto white, which is right for a headshot and
would mangle a wordmark. A logo keeps its aspect ratio and its alpha channel,
and is merely bounded so one faculty member's 4000px PNG does not become the
heaviest asset on the event page.
"""

from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

#: Largest stored logo, in pixels. Rendered at max 144x48 CSS pixels, so this
#: leaves generous headroom for retina without storing anything absurd.
MAX_BOX = (800, 400)

#: Reject an upload larger than this outright, before decoding it.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB

#: Pillow format names we accept. Everything is re-encoded to WebP on the way
#: out, so the stored format is uniform regardless of what was uploaded.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}


class InvalidImage(ValueError):
    """Raised when an upload is missing, unreadable, or an unsupported type."""


def normalize_logo(source) -> ContentFile:
    """Render ``source`` to a WebP ``ContentFile`` bounded by :data:`MAX_BOX`.

    Preserves aspect ratio and transparency. Raises :class:`InvalidImage` for
    unreadable or unsupported uploads.
    """
    try:
        source.seek(0)
    except (AttributeError, OSError):
        pass

    try:
        img = Image.open(source)
        img.load()
    except Exception as exc:  # Pillow raises a grab-bag of errors here.
        raise InvalidImage("Could not read that image.") from exc

    if img.format and img.format.upper() not in ALLOWED_FORMATS:
        raise InvalidImage(f"Unsupported image type: {img.format}.")

    img = ImageOps.exif_transpose(img)
    # RGBA throughout: WebP carries alpha, and a logo is usually a dark
    # wordmark on transparency.
    img = img.convert("RGBA")
    # thumbnail() is a no-op when the image already fits, which is what we want
    # — never upscale a small logo into blur.
    img.thumbnail(MAX_BOX, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=90, method=6)
    return ContentFile(buf.getvalue())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_images.py -v -p no:xdist`
Expected: PASS, 6 tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add events/ce_images.py events/test_ce_images.py
git commit -m "feat(events): normalize accreditor logos to bounded WebP (#486)"
```

---

### Task 3: Public display

**Files:**
- Create: `events/templates/events/_ce_credits.html`
- Modify: `events/templates/events/_event_summary.html:75-81` (the About block)
- Test: `events/test_ce_display.py`

**Interfaces:**
- Consumes: `Event.offers_ce`, `Event.ce_credits_label`, `Event.ce_organizations`, `Event.ce_note`, `CEOrganization.{name,logo,url,statement}` from Task 1.
- Produces: the partial `events/_ce_credits.html`, which expects `event` in context and nothing else.

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce_display.py`:

```python
"""CE panel rendering on the event page and the Workspace Overview (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from events.ce import CECreditBasis
from events.models import CEOrganization, Event


@pytest.fixture
def logo():
    """A 1x1 PNG is enough — these tests care about markup, not pixels."""
    return SimpleUploadedFile(
        "apa.png",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        content_type="image/png",
    )


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Working with Masochism", slug="masochism",
        description="A day on the economy of masochism.",
        start_date=date(2026, 10, 3), end_date=date(2026, 10, 3),
        published=True, status=Event.Status.OPEN,
    )


@pytest.mark.django_db
def test_no_ce_panel_when_ce_is_off(client, event):
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"Continuing education" not in response.content


@pytest.mark.django_db
def test_ce_panel_shows_the_credit_line(client, event):
    event.offers_ce = True
    event.ce_credits = Decimal("6.00")
    event.save()
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"Continuing education" in response.content
    assert b"Approved for 6 CE credits." in response.content


@pytest.mark.django_db
def test_ce_panel_renders_when_the_event_has_no_description(client, event):
    """About is wrapped in {% if event.description %}; the CE panel must not be
    swallowed by an event whose description is not written yet."""
    event.description = ""
    event.offers_ce = True
    event.save()
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"CE credits available." in response.content


@pytest.mark.django_db
def test_ce_panel_shows_logo_statement_and_note(client, event, logo, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(
        name="American Psychological Association",
        logo=logo,
        url="https://www.apa.org/",
        statement="LSP maintains responsibility for this program and its content.",
    )
    event.offers_ce = True
    event.ce_credits = Decimal("2.00")
    event.ce_credits_basis = CECreditBasis.PER_MEETING
    event.ce_note = "Full attendance is required for credit."
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Approved for 2 CE credits per meeting." in body
    assert 'alt="American Psychological Association logo"' in body
    assert "https://www.apa.org/" in body
    assert "LSP maintains responsibility for this program and its content." in body
    assert "Full attendance is required for credit." in body


@pytest.mark.django_db
def test_ce_panel_appears_on_the_workspace_overview(client, event):
    """The Overview tab shares events/_event_summary.html, so it gets the panel
    from the same partial. A Workspace is gated (landing_visible_to), so this
    signs in an LSP member rather than browsing anonymously."""
    from accounts.models import Profile

    member = User.objects.create_user(email="member-ce@x.test")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save()
    client.force_login(member)

    event.event_type = Event.Type.SEMINAR
    event.offers_ce = True
    event.ce_credits = Decimal("2.00")
    event.ce_credits_basis = CECreditBasis.PER_MEETING
    event.save()
    workgroup = event.ensure_workgroup()
    response = client.get(workgroup.get_absolute_url())
    assert b"Approved for 2 CE credits per meeting." in response.content
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_display.py -v -p no:xdist`
Expected: FAIL, four tests asserting on CE content find none of it.

- [ ] **Step 3: Write the partial**

Create `events/templates/events/_ce_credits.html`:

```html
{% comment %}Continuing-education credits + accreditor logos (task #486).

Rendered at the bottom of About in events/_event_summary.html, and standing on
its own when the event has no description yet. Expects: event.

The logo chips are deliberately paper-white in BOTH themes rather than a
DaisyUI token: accreditor logos are near-universally dark-on-transparent and
would disappear against the dark theme. Same reasoning as the header crest.
{% endcomment %}
<div class="space-y-3 rounded-xl border border-base-300/60 bg-base-200/40 p-4">
  <p class="text-xs uppercase tracking-wide text-base-content/50">Continuing education</p>

  <p class="text-sm text-base-content/90">{{ event.ce_credits_label }}</p>

  {% with orgs=event.ce_organizations.all %}
  {% if orgs %}
  <div class="flex flex-wrap items-center gap-3">
    {% for org in orgs %}
    <span class="inline-flex items-center rounded-lg bg-white p-2">
      {% if org.url %}<a href="{{ org.url }}" target="_blank" rel="noopener">{% endif %}
      <img src="{{ org.logo.url }}" alt="{{ org.name }} logo"
           class="max-h-12 max-w-36 object-contain">
      {% if org.url %}</a>{% endif %}
    </span>
    {% endfor %}
  </div>
  {% for org in orgs %}
  {% if org.statement %}
  <p class="text-xs leading-relaxed text-base-content/60">{{ org.statement }}</p>
  {% endif %}
  {% endfor %}
  {% endif %}
  {% endwith %}

  {% if event.ce_note %}
  <p class="text-xs leading-relaxed text-base-content/60">{{ event.ce_note }}</p>
  {% endif %}
</div>
```

- [ ] **Step 4: Include it from the About block**

In `events/templates/events/_event_summary.html`, replace lines 75-81 (the whole `{# ---------- About ---------- #}` block) with:

```html
{# ---------- About (+ CE panel, which stands alone if there's no body) ---------- #}
{% if event.description %}
<section class="space-y-3">
  <h2 class="font-serif text-xl text-base-content border-b border-base-300/60 pb-2">About</h2>
  <div class="text-base-content/90 leading-relaxed space-y-4">{{ event.description|inline_italics|linebreaks }}</div>
  {% if event.offers_ce %}{% include "events/_ce_credits.html" %}{% endif %}
</section>
{% elif event.offers_ce %}
<section class="space-y-3">
  {% include "events/_ce_credits.html" %}
</section>
{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_display.py -v -p no:xdist`
Expected: PASS, 5 tests.

- [ ] **Step 6: Run the full events + workgroups suites**

Run: `uv run pytest events/ workgroups/ -q && uv run ruff check .`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add events/templates/events/_ce_credits.html events/templates/events/_event_summary.html events/test_ce_display.py
git commit -m "feat(events): show CE credits and accreditor logos under About (#486)"
```

---

### Task 4: CE on the event edit form (and the stale button label)

**Files:**
- Modify: `events/forms.py:12-27` (rename `EventDescriptionForm` → `EventEditForm`, add CE fields)
- Modify: `events/views.py:25` (import), `:327`, `:339`, `:375-381` (the non-reviewable apply branch), `:488`
- Modify: `events/templates/events/event_edit.html` (CE section before the Save button)
- Modify: `events/templates/events/event_detail.html:42` and `workgroups/templates/workgroups/detail.html:76` ("Edit description" → "Edit event")
- Modify: `events/tests.py:385-388`, `events/test_faculty_views.py:144,154,225`
- Test: `events/test_ce_edit.py`

**Interfaces:**
- Consumes: `Event` CE fields from Task 1.
- Produces: `events.forms.EventEditForm` (the former `EventDescriptionForm`, same constructor signature) and the view context keys `ce_organizations` (a `CEOrganization` queryset) and `selected_ce_values` (a list of `str` primary keys).

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce_edit.py`:

```python
"""Editing CE on the event edit form (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from events.ce import CECreditBasis
from events.models import CEOrganization, Event, EventChangeRequest


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi", description="initial body",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-ce@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def org(db):
    return CEOrganization.objects.create(name="GPPA")


def _post(event, **overrides):
    data = {
        "title": event.title,
        "description": event.description,
        "readings": "",
        "schedule_note": "",
        "contact": "",
        "fee_note": "",
        "ce_credits_basis": CECreditBasis.TOTAL,
        "ce_note": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_faculty_can_record_ce(client, event, faculty, org):
    client.force_login(faculty)
    response = client.post(reverse("events:edit", args=[event.slug]), _post(
        event, offers_ce="on", ce_credits="2", ce_credits_basis=CECreditBasis.PER_MEETING,
        ce_note="Full attendance required.", ce_organizations=[str(org.pk)],
    ))
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.offers_ce is True
    assert event.ce_credits == Decimal("2")
    assert event.ce_credits_basis == CECreditBasis.PER_MEETING
    assert event.ce_note == "Full attendance required."
    assert list(event.ce_organizations.all()) == [org]


@pytest.mark.django_db
def test_ce_applies_immediately_on_an_approved_event(client, event, faculty, org):
    """CE is a factual accreditation record, not program content the PC vetted,
    so it must not raise the certify-or-submit dialog."""
    from events.models import EventProposal

    proposer = User.objects.create_user(email="prop-ce@x.test")
    EventProposal.objects.create(
        proposed_by=proposer, event_type=Event.Type.SEMINAR, title=event.title,
        description=event.description, start_date=event.start_date,
        end_date=event.end_date, status=EventProposal.Status.APPROVED,
        minted_event=event,
    )
    assert event.requires_change_review()

    client.force_login(faculty)
    response = client.post(reverse("events:edit", args=[event.slug]), _post(
        event, offers_ce="on", ce_credits="6", ce_organizations=[str(org.pk)],
    ))
    assert response.status_code == 302          # straight through, no dialog
    event.refresh_from_db()
    assert event.offers_ce is True
    assert list(event.ce_organizations.all()) == [org]
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_ce_saves_alongside_a_reviewable_change(client, event, faculty, org):
    """The reviewable-change branch applies non-reviewable fields directly, and
    a ManyToMany cannot go through setattr()/update_fields."""
    from events.models import EventProposal

    proposer = User.objects.create_user(email="prop-ce2@x.test")
    EventProposal.objects.create(
        proposed_by=proposer, event_type=Event.Type.SEMINAR, title=event.title,
        description=event.description, start_date=event.start_date,
        end_date=event.end_date, status=EventProposal.Status.APPROVED,
        minted_event=event,
    )
    client.force_login(faculty)
    response = client.post(reverse("events:edit", args=[event.slug]), _post(
        event, description="A wholly rewritten body for the seminar.",
        offers_ce="on", ce_organizations=[str(org.pk)], decision="minor",
    ))
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.offers_ce is True
    assert list(event.ce_organizations.all()) == [org]


@pytest.mark.django_db
def test_edit_page_lists_the_organizations_with_the_current_ones_ticked(
    client, event, faculty, org,
):
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)
    client.force_login(faculty)
    body = client.get(reverse("events:edit", args=[event.slug])).content.decode()
    assert 'name="ce_organizations" value="%d"' % org.pk in body
    assert "GPPA" in body


@pytest.mark.django_db
def test_edit_affordance_is_labelled_edit_event(client, event, faculty):
    client.force_login(faculty)
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Edit event" in body
    assert "Edit description" not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_edit.py -v -p no:xdist`
Expected: FAIL — CE values are not saved and the button still reads "Edit description".

- [ ] **Step 3: Rename the form and add the CE fields**

In `events/forms.py`, replace the `EventDescriptionForm` class with:

```python
class EventEditForm(forms.ModelForm):
    """Faculty-facing edit form for an event's public content (PROG-7).

    Named for the whole page, not just the description: it has carried title,
    readings, schedule, contact, fee, and now CE for some time.
    """

    class Meta:
        model = Event
        fields = (
            "title", "description", "readings", "schedule_note", "contact",
            "fee_note", "record_video", "speaker_spotlight", "open_to_guests",
            "offers_ce", "ce_credits", "ce_credits_basis", "ce_note",
            "ce_organizations",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "description": forms.Textarea(attrs={"rows": 12, "cols": 80}),
            "readings": forms.Textarea(attrs={"rows": 8, "cols": 80}),
            "schedule_note": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            "fee_note": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            "ce_note": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            # Rendered by hand in the template so each option carries its logo.
            "ce_organizations": forms.CheckboxSelectMultiple,
            "ce_credits": forms.NumberInput(
                attrs={"class": "input input-bordered input-sm", "step": "0.5", "min": "0"},
            ),
            "ce_credits_basis": forms.Select(
                attrs={"class": "select select-bordered select-sm"},
            ),
        }
```

- [ ] **Step 4: Update the view**

In `events/views.py`:

1. Line 25 — change the import to `from .forms import EventEditForm, PricingCodeForm`.
2. Lines 327, 339, 488 — replace each `EventDescriptionForm` with `EventEditForm`.
3. Add this helper directly above `event_edit`:

```python
def _ce_edit_context(form):
    """Organization checkboxes for the edit form.

    Rendered by hand rather than through the widget so each option can show its
    logo. ``BoundField.value()`` gives the *submitted* selection when the form
    is bound, so a failed POST re-renders with the user's ticks intact.
    """
    from .models import CEOrganization

    return {
        "ce_organizations": CEOrganization.objects.all(),
        "selected_ce_values": [str(v) for v in (form["ce_organizations"].value() or [])],
    }
```

4. In the GET branch (line 326-332), add `**_ce_edit_context(form),` to the render context.
5. In the invalid-form branch (line 341-343), add `**_ce_edit_context(form),` and `"speaker_invites": _speaker_invite_rows(event),`.
6. In the dialog branch (line 361-368), no change — `event_edit_confirm.html` re-posts the form's values as hidden inputs, which already covers multi-value fields.
7. Replace the non-reviewable apply block (lines 375-381) with:

```python
    # Apply non-reviewable changes immediately either way. ManyToMany fields
    # (ce_organizations) can go through neither setattr() nor update_fields, so
    # they're set separately.
    m2m_names = {f.name for f in Event._meta.many_to_many}
    nonreviewable = [
        f for f in form.changed_data if f not in REVIEWABLE_FIELDS
    ]
    concrete = [f for f in nonreviewable if f not in m2m_names]
    if concrete:
        for f in concrete:
            setattr(event, f, cd[f])
        event.save(update_fields=concrete)
    for f in nonreviewable:
        if f in m2m_names:
            getattr(event, f).set(cd[f])
```

- [ ] **Step 5: Add the CE section to the edit template**

In `events/templates/events/event_edit.html`, insert this immediately before the `<button type="submit" class="btn btn-primary">Save</button>` line:

```html
    <section class="space-y-3 border-t border-base-300/60 pt-6">
      <h2 class="font-serif text-lg text-base-content">Continuing education</h2>

      <label class="flex items-start gap-2 cursor-pointer">
        {{ form.offers_ce }}
        <span class="label-text">
          Approved for CE credits
          <span class="block text-xs text-base-content/60">Tick this once an accrediting body has approved the event. It adds a CE panel at the bottom of the About section on the event page.</span>
        </span>
      </label>

      <div class="flex flex-wrap items-end gap-3">
        <div class="space-y-1">
          <label for="id_ce_credits" class="block text-xs text-base-content/60">Credits</label>
          {{ form.ce_credits }}
        </div>
        <div class="space-y-1">
          <label for="id_ce_credits_basis" class="block text-xs text-base-content/60">Counted</label>
          {{ form.ce_credits_basis }}
        </div>
      </div>
      <p class="text-xs text-base-content/60">Leave the count blank if the body hasn't set one yet, the page will say credits are available.</p>
      {% if form.ce_credits.errors %}
      <p class="text-xs text-error">{{ form.ce_credits.errors|join:", " }}</p>
      {% endif %}

      <div class="space-y-2">
        <span class="block text-xs text-base-content/60">Approved by</span>
        {% for org in ce_organizations %}
        <label class="flex cursor-pointer items-center gap-3">
          <input type="checkbox" name="ce_organizations" value="{{ org.pk }}"
                 class="checkbox checkbox-sm"
                 {% if org.pk|stringformat:"s" in selected_ce_values %}checked{% endif %}>
          <span class="inline-flex items-center rounded bg-white p-1.5">
            <img src="{{ org.logo.url }}" alt="{{ org.name }} logo"
                 class="max-h-8 max-w-28 object-contain">
          </span>
          <span class="text-sm text-base-content">{{ org.name }}</span>
        </label>
        {% empty %}
        <p class="text-xs text-base-content/50">No organizations listed yet. Add yours below the form.</p>
        {% endfor %}
      </div>

      <div class="form-control space-y-1">
        <label for="id_ce_note" class="block text-xs text-base-content/60">Note for this event</label>
        {{ form.ce_note }}
        <p class="text-xs text-base-content/60">Anything specific to this event, e.g. "full attendance is required for credit".</p>
      </div>
    </section>
```

- [ ] **Step 6: Rename the edit affordance**

In `events/templates/events/event_detail.html:42` and `workgroups/templates/workgroups/detail.html:76`, change the link text `Edit description` to `Edit event`.

Update the three stale assertions:
- `events/test_faculty_views.py:144` — `assert b"Edit description" not in response.content` → `assert b"Edit event" not in response.content`
- `events/test_faculty_views.py:154` — `assert b"Edit description" in response.content` → `assert b"Edit event" in response.content`
- `events/test_faculty_views.py:225` — `assert b"Edit description" in response.content` → `assert b"Edit event" in response.content`

And in `events/tests.py:385-388`, change the import and assertion to use `EventEditForm`:

```python
    from events.forms import EventEditForm, ProgramEventForm

    assert "open_to_guests" in EventEditForm.Meta.fields
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_edit.py -v -p no:xdist`
Expected: PASS, 5 tests.

- [ ] **Step 8: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all pass. If anything else still references `EventDescriptionForm`, fix it — `grep -rn EventDescriptionForm --include=*.py .` must return nothing.

- [ ] **Step 9: Commit**

```bash
git add events/forms.py events/views.py events/templates/events/event_edit.html events/templates/events/event_detail.html workgroups/templates/workgroups/detail.html events/tests.py events/test_faculty_views.py events/test_ce_edit.py
git commit -m "feat(events): edit CE on the event form, rename it Edit event (#486)"
```

---

### Task 5: Add an organization inline

**Files:**
- Modify: `events/forms.py` (append `CEOrganizationForm`)
- Modify: `events/views.py` (append `ce_organization_add`)
- Modify: `events/urls.py`
- Modify: `events/templates/events/event_edit.html` (add-organization form, outside the main form)
- Test: `events/test_ce_organization_add.py`

**Interfaces:**
- Consumes: `normalize_logo` / `InvalidImage` / `MAX_UPLOAD_BYTES` from Task 2, `CEOrganization` from Task 1, `_ce_edit_context` and `EventEditForm` from Task 4.
- Produces: `events.forms.CEOrganizationForm` with `save(added_by=None, commit=True) -> CEOrganization`; the URL name `events:ce_organization_add` taking `slug`; the edit-page context key `ce_org_form`.

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce_organization_add.py`:

```python
"""Adding an accreditor to the shared library from an event (task #486)."""

from __future__ import annotations

import io
from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events.models import CEOrganization, Event


def _logo(name="apa.png", size=(400, 200)) -> SimpleUploadedFile:
    img = Image.new("RGBA", size, (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-org@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider@x.test")


@pytest.mark.django_db
def test_adding_an_organization_attaches_it_to_this_event(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {
            "name": "American Psychological Association",
            "url": "https://www.apa.org/",
            "statement": "LSP maintains responsibility for this program.",
            "logo": _logo(),
        },
    )
    assert response.status_code == 302
    org = CEOrganization.objects.get(name="American Psychological Association")
    assert org.added_by == faculty
    assert list(event.ce_organizations.all()) == [org]


@pytest.mark.django_db
def test_the_stored_logo_is_normalized_webp(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    client.post(reverse("events:ce_organization_add", args=[event.slug]), {
        "name": "GPPA", "logo": _logo(size=(4000, 1000)),
    })
    org = CEOrganization.objects.get(name="GPPA")
    img = Image.open(org.logo.path)
    assert img.format == "WEBP"
    assert img.size == (800, 200)


@pytest.mark.django_db
def test_a_duplicate_name_points_at_the_existing_entry(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    CEOrganization.objects.create(name="American Psychological Association")
    client.force_login(faculty)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "american psychological association", "logo": _logo()},
    )
    assert response.status_code == 200
    assert b"is already listed" in response.content
    assert CEOrganization.objects.count() == 1


@pytest.mark.django_db
def test_an_unreadable_logo_is_reported(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    bad = SimpleUploadedFile("x.png", b"not an image at all", content_type="image/png")
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Nope", "logo": bad},
    )
    assert response.status_code == 200
    assert not CEOrganization.objects.filter(name="Nope").exists()


@pytest.mark.django_db
def test_someone_who_cannot_edit_the_event_cannot_seed_the_library(
    client, event, outsider, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(outsider)
    response = client.post(
        reverse("events:ce_organization_add", args=[event.slug]),
        {"name": "Sneaky", "logo": _logo()},
    )
    assert response.status_code == 403
    assert not CEOrganization.objects.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_organization_add.py -v -p no:xdist`
Expected: FAIL, `NoReverseMatch: 'ce_organization_add' is not a valid view function or pattern name`.

- [ ] **Step 3: Write the form**

Append to `events/forms.py` (and add `CEOrganization` to the `from .models import ...` line at the top):

```python
class CEOrganizationForm(forms.ModelForm):
    """Add an accrediting body to the shared library, from an event page.

    The library is not curated, so the guard rails are here: a case-insensitive
    name check that points at the existing entry rather than minting a second
    one, and logo normalization so nobody's 4000px PNG lands on an event page.
    """

    class Meta:
        model = CEOrganization
        fields = ("name", "logo", "url", "statement")
        widgets = {
            "name": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "url": forms.URLInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "statement": forms.Textarea(
                attrs={"class": "textarea textarea-bordered w-full", "rows": 3},
            ),
        }

    def clean_name(self):
        name = (self.cleaned_data["name"] or "").strip()
        existing = CEOrganization.objects.filter(name__iexact=name).first()
        if existing is not None:
            raise forms.ValidationError(
                f"{existing.name} is already listed. Tick it in the list above "
                "instead of adding it again."
            )
        return name

    def clean_logo(self):
        from .ce_images import MAX_UPLOAD_BYTES, InvalidImage, normalize_logo

        raw = self.cleaned_data["logo"]
        if getattr(raw, "size", 0) > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("That image is too large (8 MB max).")
        try:
            self._logo_webp = normalize_logo(raw)
        except InvalidImage as exc:
            raise forms.ValidationError(str(exc)) from exc
        return raw

    def save(self, added_by=None, commit=True):
        from django.utils.text import slugify

        org = super().save(commit=False)
        org.added_by = added_by
        org.logo.save(
            f"{slugify(org.name) or 'ce-organization'}.webp", self._logo_webp, save=False,
        )
        if commit:
            org.save()
        return org
```

- [ ] **Step 4: Write the view**

In `events/views.py`, append after `event_edit`:

```python
@login_required
@require_POST
def ce_organization_add(request, slug: str):
    """Add an accrediting body to the shared library and apply it to this event.

    Reaching this from an event can only mean "this event is approved by it", so
    the new organization is ticked on straight away. Gated by can_edit_event: the
    library is shared, so only someone who can edit *some* event may seed it.
    """
    from .forms import CEOrganizationForm

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to edit this event.")

    org_form = CEOrganizationForm(request.POST, request.FILES)
    if org_form.is_valid():
        org = org_form.save(added_by=request.user)
        event.ce_organizations.add(org)
        messages.success(request, f"Added {org.name} and applied it to this event.")
        return redirect("events:edit", slug=event.slug)

    form = EventEditForm(instance=event)
    return render(request, "events/event_edit.html", {
        "event": event, "form": form, "ce_org_form": org_form,
        "speaker_invites": _speaker_invite_rows(event),
        **_ce_edit_context(form),
        **_schedule_editor_context(event),
    })
```

- [ ] **Step 5: Wire the URL**

In `events/urls.py`, add after the `edit_schedule` line:

```python
    path("<slug:slug>/ce-organizations/add/",
         views.ce_organization_add, name="ce_organization_add"),
```

- [ ] **Step 6: Add the form to the edit template**

In `events/templates/events/event_edit.html`, insert this **after** the closing `</form>` of the main edit form (line 112) and before the `{% if show_schedule_editor %}` block. It must be outside the main form, since HTML forbids nested forms:

```html
  <section class="space-y-3 border-t border-base-300/60 pt-6">
    <h2 class="font-serif text-lg text-base-content">Add a CE organization</h2>
    <p class="text-xs text-base-content/60">
      If the body that approved your event isn't in the list above, add it here.
      It becomes available to every other event, so use the organization's full
      name and its official logo. A transparent PNG looks best.
    </p>
    <form method="post" enctype="multipart/form-data"
          action="{% url 'events:ce_organization_add' event.slug %}" class="space-y-3">
      {% csrf_token %}
      {% with f=ce_org_form %}
      <div class="space-y-1">
        <label for="id_name" class="block text-xs text-base-content/60">Name</label>
        <input type="text" name="name" id="id_name" required
               value="{% if f %}{{ f.name.value|default_if_none:'' }}{% endif %}"
               class="input input-bordered input-sm w-full">
        {% if f.name.errors %}<p class="text-xs text-error">{{ f.name.errors|join:", " }}</p>{% endif %}
      </div>
      <div class="space-y-1">
        <label for="id_logo" class="block text-xs text-base-content/60">Logo</label>
        <input type="file" name="logo" id="id_logo" accept="image/*" required
               class="file-input file-input-bordered file-input-sm w-full">
        {% if f.logo.errors %}<p class="text-xs text-error">{{ f.logo.errors|join:", " }}</p>{% endif %}
      </div>
      <div class="space-y-1">
        <label for="id_url" class="block text-xs text-base-content/60">Website (optional)</label>
        <input type="url" name="url" id="id_url"
               value="{% if f %}{{ f.url.value|default_if_none:'' }}{% endif %}"
               class="input input-bordered input-sm w-full">
        {% if f.url.errors %}<p class="text-xs text-error">{{ f.url.errors|join:", " }}</p>{% endif %}
      </div>
      <div class="space-y-1">
        <label for="id_statement" class="block text-xs text-base-content/60">Required approval language (optional)</label>
        <textarea name="statement" id="id_statement" rows="3"
                  class="textarea textarea-bordered w-full">{% if f %}{{ f.statement.value|default_if_none:'' }}{% endif %}</textarea>
        <p class="text-xs text-base-content/60">Wording this body requires on approved events. Shown under its logo on every event that claims it.</p>
        {% if f.statement.errors %}<p class="text-xs text-error">{{ f.statement.errors|join:", " }}</p>{% endif %}
      </div>
      {% endwith %}
      <button type="submit" class="btn btn-outline btn-sm">Add organization</button>
    </form>
  </section>
```

Note: `file-input file-input-bordered file-input-sm` is a DaisyUI class trio written directly in this template, so the Tailwind scan picks it up.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_organization_add.py -v -p no:xdist`
Expected: PASS, 5 tests.

- [ ] **Step 8: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add events/forms.py events/views.py events/urls.py events/templates/events/event_edit.html events/test_ce_organization_add.py
git commit -m "feat(events): add a CE organization to the shared library inline (#486)"
```

---

### Task 6: CE estimate on the proposal form

**Files:**
- Modify: `events/forms.py` (`EventProposalForm.Meta.fields` and `__init__`)
- Modify: `events/templates/events/propose_event.html:192-199` (the CE block)
- Modify: `events/templates/events/program_admin/proposals.html:46`
- Test: `events/test_ce_proposal.py`

**Interfaces:**
- Consumes: `EventProposal.ce_credits`, `EventProposal.ce_credits_basis`, `EventProposal.ce_credits_label` from Task 1.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Write the failing tests**

Create `events/test_ce_proposal.py`:

```python
"""CE intent on the event proposal (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from events.ce import CECreditBasis
from events.models import Event, EventProposal

# Every propose POST carries these: submit intent (vs save), the location
# dropdown, and the external-speaker formset's management form. Copied from
# events/test_event_proposal.py::_MGMT — keep the two in step.
_MGMT = {
    "action": "submit",
    "location_kind": "online_insite",
    "speakers-TOTAL_FORMS": "0", "speakers-INITIAL_FORMS": "0",
    "speakers-MIN_NUM_FORMS": "0", "speakers-MAX_NUM_FORMS": "1000",
}


@pytest.fixture
def proposer(db):
    u = User.objects.create_user(email="proposer-ce@x.test", password="x")
    u.profile.role = Profile.Role.ANALYST
    u.profile.is_faculty = True
    u.profile.save()
    return u


@pytest.mark.django_db
def test_proposal_form_accepts_a_credit_estimate(client, proposer):
    client.force_login(proposer)
    response = client.post(reverse("propose_event"), {
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Seminar on Anxiety",
        "description": "A year with Seminar X.",
        "start_date": "2026-09-01",
        "end_date": "2027-05-01",
        "fee_type": "free",
        "schedule_choice": "tbd",
        "offers_ce": "on",
        "ce_credits": "2",
        "ce_credits_basis": CECreditBasis.PER_MEETING,
    })
    assert response.status_code == 302
    proposal = EventProposal.objects.get(title="Seminar on Anxiety")
    assert proposal.offers_ce is True
    assert proposal.ce_credits == Decimal("2")
    assert proposal.ce_credits_basis == CECreditBasis.PER_MEETING


@pytest.mark.django_db
def test_the_estimate_is_optional(client, proposer):
    client.force_login(proposer)
    response = client.post(reverse("propose_event"), {
        **_MGMT,
        "event_type": Event.Type.SEMINAR,
        "title": "Seminar on Transference",
        "description": "A year with Seminar VIII.",
        "start_date": "2026-09-01",
        "end_date": "2027-05-01",
        "fee_type": "free",
        "schedule_choice": "tbd",
        "offers_ce": "on",
    })
    assert response.status_code == 302
    proposal = EventProposal.objects.get(title="Seminar on Transference")
    assert proposal.offers_ce is True
    assert proposal.ce_credits is None
    assert proposal.ce_credits_label == "CE credits available."
```

The propose view is project-level, not namespaced: `reverse("propose_event")` (`config/urls.py:83`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_proposal.py -v -p no:xdist`
Expected: FAIL — `ce_credits` is not a form field, so it is dropped and `proposal.ce_credits` stays `None` in the first test.

- [ ] **Step 3: Add the fields to the proposal form**

In `events/forms.py`, in `EventProposalForm.Meta.fields`, change `"offers_ce",` to:

```python
            "offers_ce", "ce_credits", "ce_credits_basis",
```

In `EventProposalForm.Meta.widgets`, add:

```python
            "ce_credits": forms.NumberInput(
                attrs={"class": "input input-bordered input-sm", "step": "0.5", "min": "0"},
            ),
            "ce_credits_basis": forms.Select(
                attrs={"class": "select select-bordered select-sm"},
            ),
```

In `EventProposalForm.__init__`, next to the existing `offers_ce` label line, add:

```python
        self.fields["ce_credits"].label = "Credits you expect to offer"
        self.fields["ce_credits_basis"].label = "Counted"
```

- [ ] **Step 4: Show them on the propose page**

In `events/templates/events/propose_event.html`, inside the existing `{# ---- CE (offerings) ---- #}` block, add immediately after the `{% include "events/_proposal_field.html" with field=form.offers_ce %}` line:

```html
      <div class="flex flex-wrap items-end gap-3 pl-6">
        {% include "events/_proposal_field.html" with field=form.ce_credits %}
        {% include "events/_proposal_field.html" with field=form.ce_credits_basis %}
      </div>
```

- [ ] **Step 5: Show the estimate in the PC queue**

In `events/templates/events/program_admin/proposals.html:46`, replace the CE line with:

```html
          {% if p.offers_ce %}<p class="text-xs text-base-content/60">Requests CE credits{% if p.ce_credits %} ({{ p.ce_credits|floatformat:"-2" }} {{ p.get_ce_credits_basis_display }}){% endif %}.</p>{% endif %}
```

`floatformat:"-2"` drops the trailing zeros, so it reads "Requests CE credits (2 per meeting)."

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_proposal.py -v -p no:xdist`
Expected: PASS, 2 tests.

- [ ] **Step 7: Run the full suite and lint**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all pass.

- [ ] **Step 8: Rebuild the CSS and eyeball the page**

Run: `npm run build:css`
Then start the dev server and open an event edit page and its public page to confirm the CE section renders, the logo chips stay white in the dark theme, and the add-organization form posts.

- [ ] **Step 9: Commit**

```bash
git add events/forms.py events/templates/events/propose_event.html events/templates/events/program_admin/proposals.html events/test_ce_proposal.py
git commit -m "feat(events): collect a CE credit estimate on the proposal (#486)"
```

---

## Notes for the reviewer

- **Not built, by design:** a CE marker on `/program/` or `/events/` listings, per-organization credit counts, certificates or attendance tracking, and re-recording the 2025-26 seminar's hand-typed CE sentence as structured data. All are listed as out of scope in the spec.
- **The proposal's CE block stays scoped to `data-types="seminar reading_group"`.** Special events do not request CE on the proposal, because the GPPA guidance text in that block is seminar-specific ("email the program committee with your email of approval from GPPA by May 15th"). Special events record CE on the event edit form after approval, which is where CE is really recorded for every type anyway.
- **`bg-white` on the logo chips is deliberate** and carries an explaining comment in the partial. It is the one place this feature departs from the DaisyUI-token authoring rule, following the header-crest precedent.
