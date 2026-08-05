# Event Feature Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let faculty put a feature image on an event from the event edit page, rendered on the event page, the Workspace masthead, and the OpenGraph share preview.

**Architecture:** A `OneToOne` `EventFeatureImage` row carries the image and its rights record. Uploads are normalized at upload time — cropped to a ratio between 1:1 and 2.5:1 and re-encoded to bounded WebP — so every render site sees a shape it can trust, and the layout bounds both dimensions instead of fixing the height. The image is edited by its own form posting to its own endpoint, because `event_edit_confirm.html` re-posts `EventEditForm` as hidden textareas and would drop a file input.

**Tech Stack:** Django 5.2, Pillow, pytest-django, Tailwind v4 + DaisyUI v5, vendored Cropper.js 1.6.2.

**Spec:** `docs/superpowers/specs/2026-08-04-event-feature-image-design.md`

## Global Constraints

- Ratio range: `1.0 ≤ width/height ≤ 2.5`, enforced server-side, not only in the cropper.
- Render fits a **1600 × 900** box, WebP quality 82, `method=6`, transparency flattened onto white.
- Retained original fits **2400 × 2400**, WebP quality 88.
- Reject uploads over **12 MB** before decoding; downscale sources past **6000 px** before cropping.
- Reject a render whose width would fall below **800 px**.
- DaisyUI semantic tokens only (`bg-base-100`, `text-base-content`, …) — never `bg-gray-100`.
- Tailwind scans templates only: any class must appear literally in a `.html` file.
- The feature image is **not** added to `events/review.py:REVIEWABLE_FIELDS`.
- Member-facing copy uses commas, not em dashes.
- `can_edit_event` is the gate and is unchanged.

---

### Task 1: The model

**Files:**
- Modify: `events/models.py` (append after `CEOrganizationLogo`)
- Modify: `events/admin.py`
- Create: `events/migrations/00XX_eventfeatureimage.py` (generated)
- Test: `events/test_feature_image.py`

**Interfaces:**
- Produces: `events.models.EventFeatureImage` with fields `event`, `image`, `image_width`, `image_height`, `original`, `crop`, `credit`, `alt`, `source`, `source_url`, `rights_confirmed_by`, `rights_confirmed_at`; `EventFeatureImage.Source` choices; property `alt_text`; and `Event.feature()` returning the row or `None`.

- [ ] **Step 1: Write the failing test**

```python
"""Feature image on an event (task #504)."""

from __future__ import annotations

from datetime import date

import pytest

from events.models import Event, EventFeatureImage


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.mark.django_db
def test_an_event_without_an_image_reports_none(event):
    assert event.feature() is None


@pytest.mark.django_db
def test_alt_text_falls_back_to_the_event_title(event):
    img = EventFeatureImage(event=event, source=EventFeatureImage.Source.OWN_WORK)
    assert img.alt_text == "Seminar XI"
    img.alt = "A pipe, captioned."
    assert img.alt_text == "A pipe, captioned."
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest events/test_feature_image.py -q`
Expected: FAIL — `ImportError: cannot import name 'EventFeatureImage'`.

- [ ] **Step 3: Add the model**

```python
class EventFeatureImage(models.Model):
    """The image an event leads with (task #504).

    A separate row rather than nine more fields on ``Event``: absence of the row
    *is* "no image", removal is a delete, and the rights record stays beside the
    file it licenses. The render is normalized at upload (see
    ``events.feature_images``) so every surface can trust its shape.
    """

    class Source(models.TextChoices):
        PUBLIC_DOMAIN = "public_domain", "Public domain"
        LICENSED = "licensed", "Licensed"
        OWN_WORK = "own_work", "My own work"
        PERMISSION = "permission", "Permission granted by the rights holder"

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="feature_image",
    )
    image = models.ImageField(
        upload_to="events/feature/%Y/",
        width_field="image_width", height_field="image_height",
        help_text="Rendered WebP. Derived from `original` via feature_images.render().",
    )
    # Denormalized: media lives in S3 in production, so reading image.width at
    # render time is a network round trip per page view. Also lets the <img>
    # reserve its space before the file arrives.
    image_width = models.PositiveIntegerField(default=0)
    image_height = models.PositiveIntegerField(default=0)
    original = models.ImageField(
        upload_to="events/feature/originals/%Y/", blank=True,
        help_text="The bounded upload, kept so the crop can be revised later.",
    )
    crop = models.JSONField(
        blank=True, null=True,
        help_text="Cropper.js rect in natural-image pixels, so the modal reopens where it was left.",
    )
    credit = models.CharField(
        max_length=200, blank=True,
        help_text="Shown small under the image, e.g. \"Rene Magritte, The Treachery of Images\".",
    )
    alt = models.CharField(
        max_length=300, blank=True,
        help_text="Description for screen readers. Blank falls back to the event title.",
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    source_url = models.URLField(blank=True, help_text="Required when the source is Licensed.")
    rights_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    rights_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Feature image for {self.event}"

    @property
    def alt_text(self) -> str:
        """What the ``alt`` attribute should say, never blank."""
        return self.alt or self.event.title
```

And on `Event`:

```python
    def feature(self):
        """This event's feature image row, or None (task #504).

        ``getattr`` with a default is safe here: Django's RelatedObjectDoesNotExist
        subclasses AttributeError precisely so this works.
        """
        return getattr(self, "feature_image", None)
```

Check `events/models.py` already imports `settings` from `django.conf`; add it if not.

- [ ] **Step 4: Make and apply the migration**

```bash
uv run python manage.py makemigrations events && uv run python manage.py migrate
```

- [ ] **Step 5: Register it in the admin**

In `events/admin.py`, an inline on the existing `EventAdmin`:

```python
class EventFeatureImageInline(admin.StackedInline):
    model = EventFeatureImage
    extra = 0
    readonly_fields = ("image_width", "image_height", "rights_confirmed_by", "rights_confirmed_at")
```

Add `EventFeatureImageInline` to `EventAdmin.inlines` (create the attribute if absent).

- [ ] **Step 6: Run the tests**

Run: `uv run pytest events/test_feature_image.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add events/models.py events/admin.py events/migrations events/test_feature_image.py
git commit -m "feat(events): EventFeatureImage model (task #504)"
```

---

### Task 2: The image pipeline

**Files:**
- Create: `events/feature_images.py`
- Test: `events/test_feature_image.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `events.feature_images` exposing `InvalidImage`, `MIN_RATIO = 1.0`, `MAX_RATIO = 2.5`, `RENDER_BOX = (1600, 900)`, `ORIGINAL_BOX = (2400, 2400)`, `MIN_RENDER_WIDTH = 800`, `MAX_SOURCE_DIM = 6000`, `MAX_UPLOAD_BYTES`, `render(source, crop: dict | None = None) -> ContentFile`, and `bound_original(source) -> ContentFile`.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_feature_image.py`:

```python
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from events import feature_images


def _upload(size=(2000, 1000), name="art.png", mode="RGB", fmt="PNG"):
    img = Image.new(mode, size, (10, 20, 30) if mode == "RGB" else (10, 20, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


def _rendered(blob):
    return Image.open(io.BytesIO(blob.read()))


def test_a_wide_upload_is_clamped_to_the_widest_ratio():
    out = _rendered(feature_images.render(_upload(size=(3000, 600))))  # 5:1
    assert out.width / out.height == pytest.approx(feature_images.MAX_RATIO, abs=0.02)


def test_a_portrait_upload_is_clamped_to_square():
    out = _rendered(feature_images.render(_upload(size=(900, 2400))))
    assert out.width / out.height == pytest.approx(1.0, abs=0.02)


def test_an_in_range_upload_keeps_its_own_ratio():
    out = _rendered(feature_images.render(_upload(size=(1800, 1000))))  # 1.8:1
    assert out.width / out.height == pytest.approx(1.8, abs=0.02)


def test_the_render_is_bounded_webp():
    out = _rendered(feature_images.render(_upload(size=(4000, 2000))))
    assert out.format == "WEBP"
    assert out.width <= feature_images.RENDER_BOX[0]
    assert out.height <= feature_images.RENDER_BOX[1]


def test_a_crop_rect_is_honoured():
    crop = {"x": 0, "y": 0, "width": 1200, "height": 800}
    out = _rendered(feature_images.render(_upload(size=(2000, 1000)), crop))
    assert out.width / out.height == pytest.approx(1.5, abs=0.02)


def test_a_too_small_image_is_refused():
    with pytest.raises(feature_images.InvalidImage):
        feature_images.render(_upload(size=(400, 300)))


def test_an_unreadable_upload_is_refused():
    bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
    with pytest.raises(feature_images.InvalidImage):
        feature_images.render(bad)


def test_the_stored_original_is_bounded_webp():
    out = _rendered(feature_images.bound_original(_upload(size=(5000, 3000))))
    assert out.format == "WEBP"
    assert max(out.size) <= feature_images.ORIGINAL_BOX[0]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_feature_image.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'events.feature_images'`.

- [ ] **Step 3: Write the module**

```python
"""Feature-image processing for an event (task #504).

Neither existing pipeline fits. ``accounts.images`` force-crops to a centred
square, which is right for an avatar and wrong for a canvas; ``ce_images``
never crops at all, which is right for a wordmark and leaves the page holding
whatever shape arrived. Here the shape is normalized at upload into a *range*
(square through 2.5:1) so a square poster survives intact while the render
sites still only ever meet a shape they can lay out.
"""

from __future__ import annotations

import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

#: Narrowest and widest a rendered feature image may be. A square keeps a
#: poster or an album cover intact; past 2.5:1 the band stops reading as an
#: image and starts reading as a rule across the page.
MIN_RATIO = 1.0
MAX_RATIO = 2.5

#: The render fits inside this box at whatever ratio the crop produced, so a
#: 2.5:1 lands 1600x640 and a square lands 900x900. Displayed at most 340 CSS
#: pixels tall, which leaves retina headroom.
RENDER_BOX = (1600, 900)

#: The retained original is bounded too: re-cropping later must stay possible,
#: but a 20 MB phone photo should not sit in S3 forever to make it so.
ORIGINAL_BOX = (2400, 2400)

#: Below this the band shows a blur, which looks worse than no image at all.
MIN_RENDER_WIDTH = 800

#: Downscale a huge source before cropping; reject an enormous file before
#: decoding it at all.
MAX_SOURCE_DIM = 6000
MAX_UPLOAD_BYTES = 12 * 1024 * 1024

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO", "HEIF", "HEIC"}


class InvalidImage(ValueError):
    """Raised when an upload is missing, unreadable, unsupported, or too small."""


def _open(source) -> Image.Image:
    """Decode ``source``, honour its EXIF rotation, and bound its dimensions."""
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
    if max(img.size) > MAX_SOURCE_DIM:
        img.thumbnail((MAX_SOURCE_DIM, MAX_SOURCE_DIM), Image.LANCZOS)
    return img


def _coerce_box(crop: dict | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Turn a Cropper.js rect into a clamped (left, top, right, bottom)."""
    if not crop:
        return None
    try:
        x = int(round(float(crop.get("x", 0))))
        y = int(round(float(crop.get("y", 0))))
        w = int(round(float(crop.get("width", 0))))
        h = int(round(float(crop.get("height", 0))))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    left = max(0, min(x, width))
    top = max(0, min(y, height))
    right = max(left + 1, min(x + w, width))
    bottom = max(top + 1, min(y + h, height))
    return (left, top, right, bottom)


def _clamp_ratio(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Shrink ``box`` about its centre until its ratio sits within range.

    The cropper enforces this client-side; a hand-rolled POST, a no-JS upload,
    and a whole-image default all arrive here instead.
    """
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    ratio = w / h
    if ratio > MAX_RATIO:
        new_w = int(round(h * MAX_RATIO))
        left += (w - new_w) // 2
        right = left + new_w
    elif ratio < MIN_RATIO:
        new_h = int(round(w / MIN_RATIO))
        top += (h - new_h) // 2
        bottom = top + new_h
    return (left, top, right, bottom)


def render(source, crop: dict | None = None) -> ContentFile:
    """Render ``source`` to a bounded WebP ``ContentFile`` within the ratio range.

    With no usable ``crop`` the whole image is used, narrowed about its centre
    only as far as the range demands. Raises :class:`InvalidImage`.
    """
    img = _open(source)
    width, height = img.size
    box = _clamp_ratio(_coerce_box(crop, width, height) or (0, 0, width, height))
    img = img.crop(box)

    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    # thumbnail() never upscales, so a small crop stays small and is refused
    # below rather than blown up into blur.
    img.thumbnail(RENDER_BOX, Image.LANCZOS)
    if img.width < MIN_RENDER_WIDTH:
        raise InvalidImage(
            f"That image is too small. It needs to be at least "
            f"{MIN_RENDER_WIDTH} pixels wide after cropping.",
        )

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=82, method=6)
    return ContentFile(buf.getvalue())


def bound_original(source) -> ContentFile:
    """Re-encode ``source`` as a bounded WebP, for later re-cropping."""
    img = _open(source)
    img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
    img.thumbnail(ORIGINAL_BOX, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=88, method=6)
    return ContentFile(buf.getvalue())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest events/test_feature_image.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add events/feature_images.py events/test_feature_image.py
git commit -m "feat(events): feature-image pipeline, ratio-clamped to 1:1-2.5:1 (task #504)"
```

---

### Task 3: Form, view, and URL

**Files:**
- Modify: `events/forms.py`
- Modify: `events/views.py`
- Modify: `events/urls.py`
- Test: `events/test_feature_image.py` (append)

**Interfaces:**
- Consumes: `EventFeatureImage`, `events.feature_images.render` / `.bound_original` / `.InvalidImage` / `.MAX_UPLOAD_BYTES`.
- Produces: `events.forms.EventFeatureImageForm` with non-model fields `upload`, `crop`, `rights_confirmed` and a `save(event, user)` signature; `events.views.event_feature_image`; URL name `events:feature_image`.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_feature_image.py`:

```python
from django.urls import reverse

from accounts.models import User


@pytest.fixture
def faculty(db, event):
    u = User.objects.create_user(email="fac-img@x.test")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider-img@x.test")


def _post(client, event, **extra):
    data = {
        "upload": _upload(size=(2000, 1000)),
        "source": EventFeatureImage.Source.OWN_WORK,
        "rights_confirmed": "on",
    }
    data.update(extra)
    return client.post(reverse("events:feature_image", args=[event.slug]), data)


@pytest.mark.django_db
def test_faculty_can_upload_a_feature_image(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event, credit="Rene Magritte")

    img = event.feature()
    assert img is not None
    assert img.credit == "Rene Magritte"
    assert img.image_width and img.image_height
    assert img.original
    assert img.rights_confirmed_by == faculty
    assert img.rights_confirmed_at is not None


@pytest.mark.django_db
def test_the_rights_checkbox_is_required(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = client.post(
        reverse("events:feature_image", args=[event.slug]),
        {"upload": _upload(), "source": EventFeatureImage.Source.OWN_WORK},
    )
    assert response.status_code == 200
    assert event.feature() is None


@pytest.mark.django_db
def test_a_licensed_source_needs_a_url(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = _post(client, event, source=EventFeatureImage.Source.LICENSED)
    assert response.status_code == 200
    assert "source_url" in response.context["feature_image_form"].errors
    assert event.feature() is None


@pytest.mark.django_db
def test_metadata_can_be_edited_without_re_uploading(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event)
    client.post(
        reverse("events:feature_image", args=[event.slug]),
        {"source": EventFeatureImage.Source.OWN_WORK,
         "rights_confirmed": "on", "credit": "Later credit"},
    )
    event.refresh_from_db()
    assert event.feature().credit == "Later credit"


@pytest.mark.django_db
def test_the_image_can_be_removed(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event)
    client.post(reverse("events:feature_image", args=[event.slug]), {"remove": "1"})
    event.refresh_from_db()
    assert event.feature() is None


@pytest.mark.django_db
def test_someone_who_cannot_edit_the_event_is_refused(client, event, outsider, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(outsider)
    assert _post(client, event).status_code == 403
    assert event.feature() is None


@pytest.mark.django_db
def test_a_too_small_image_is_reported_on_the_form(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    response = _post(client, event, upload=_upload(size=(400, 300)))
    assert response.status_code == 200
    assert "upload" in response.context["feature_image_form"].errors
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_feature_image.py -q`
Expected: FAIL — `NoReverseMatch: 'feature_image' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the form**

In `events/forms.py`:

```python
class EventFeatureImageForm(forms.ModelForm):
    """The feature image and its rights record (task #504).

    Deliberately not folded into ``EventEditForm``: ``event_edit_confirm.html``
    re-posts that form's values as hidden textareas, and a file input cannot
    survive the round trip, so an upload would vanish on exactly those events
    that route through change review.
    """

    upload = forms.ImageField(
        required=False,
        label="Image file",
        widget=forms.ClearableFileInput(attrs={"class": "file-input file-input-bordered file-input-sm w-full",
                                               "accept": "image/*"}),
    )
    crop = forms.CharField(required=False, widget=forms.HiddenInput)
    rights_confirmed = forms.BooleanField(
        required=True,
        label="I have the right to publish this image on the school's site.",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )

    class Meta:
        model = EventFeatureImage
        fields = ("credit", "alt", "source", "source_url")
        widgets = {
            "credit": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "alt": forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
            "source": forms.Select(attrs={"class": "select select-bordered select-sm w-full"}),
            "source_url": forms.URLInput(attrs={"class": "input input-bordered input-sm w-full"}),
        }

    def clean_crop(self):
        raw = self.cleaned_data.get("crop")
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def clean_upload(self):
        upload = self.cleaned_data.get("upload")
        if upload and upload.size > feature_images.MAX_UPLOAD_BYTES:
            megabytes = feature_images.MAX_UPLOAD_BYTES // (1024 * 1024)
            raise forms.ValidationError(f"That file is too large. The limit is {megabytes} MB.")
        return upload

    def clean(self):
        cleaned = super().clean()
        upload = cleaned.get("upload")

        if not upload and not (self.instance and self.instance.pk):
            self.add_error("upload", "Choose an image to upload.")

        if cleaned.get("source") == EventFeatureImage.Source.LICENSED and not cleaned.get("source_url"):
            self.add_error("source_url", "Give the source of the licence for a licensed image.")

        # Render here, not in save(), so an unreadable or too-small image comes
        # back as a form error instead of a 500.
        self.render_blob = self.original_blob = None
        if upload:
            try:
                self.render_blob = feature_images.render(upload, cleaned.get("crop"))
                self.original_blob = feature_images.bound_original(upload)
            except feature_images.InvalidImage as exc:
                self.add_error("upload", str(exc))
        return cleaned

    def save(self, event, user):
        """Attach the image to ``event``, stamping who confirmed the rights."""
        obj = super().save(commit=False)
        obj.event = event
        if self.render_blob is not None:
            obj.image.save(f"{event.slug}.webp", self.render_blob, save=False)
            obj.original.save(f"{event.slug}-original.webp", self.original_blob, save=False)
            obj.crop = self.cleaned_data.get("crop")
        obj.rights_confirmed_by = user
        obj.rights_confirmed_at = timezone.now()
        obj.save()
        return obj
```

Add the imports `json`, `from django.utils import timezone`, `from . import feature_images`, and `EventFeatureImage` to the model import at the top of `events/forms.py` if they aren't already there.

- [ ] **Step 4: Add the view**

In `events/views.py`, beside `ce_organization_add`:

```python
@login_required
@require_POST
def event_feature_image(request, slug: str):
    """Set, replace, or remove an event's feature image (task #504).

    Its own endpoint rather than a field on EventEditForm: the change-review
    dialog re-posts that form as hidden textareas, which a file input cannot
    survive. Keeping it separate also makes its exclusion from review
    structural rather than a rule someone has to remember.
    """
    from .forms import EventFeatureImageForm
    from .models import EventFeatureImage

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to edit this event.")

    if request.POST.get("remove"):
        EventFeatureImage.objects.filter(event=event).delete()
        messages.success(request, "Feature image removed.")
        return redirect("events:edit", slug=event.slug)

    image_form = EventFeatureImageForm(
        request.POST, request.FILES, instance=event.feature(),
    )
    if image_form.is_valid():
        image_form.save(event=event, user=request.user)
        messages.success(request, "Feature image saved.")
        return redirect("events:edit", slug=event.slug)

    form = EventEditForm(instance=event)
    return render(request, "events/event_edit.html", {
        "event": event, "form": form, "feature_image_form": image_form,
        "speaker_invites": _speaker_invite_rows(event),
        **_ce_edit_context(form),
        **_schedule_editor_context(event),
    })
```

- [ ] **Step 5: Add the URL**

In `events/urls.py`, beside the CE routes:

```python
    path("<slug:slug>/feature-image/", views.event_feature_image, name="feature_image"),
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest events/test_feature_image.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add events/forms.py events/views.py events/urls.py events/test_feature_image.py
git commit -m "feat(events): feature-image form, endpoint, and rights record (task #504)"
```

---

### Task 4: The edit-page fieldset and cropper

**Files:**
- Modify: `events/templates/events/event_edit.html`
- Create: `events/templates/events/_feature_image_form.html`
- Modify: `events/views.py` (`event_edit` context)
- Test: `events/test_feature_image.py` (append)

**Interfaces:**
- Consumes: `EventFeatureImageForm`, URL `events:feature_image`.
- Produces: context key `feature_image_form` on the event edit page.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_the_edit_page_offers_the_feature_image_form(client, event, faculty):
    client.force_login(faculty)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 200
    assert "feature_image_form" in response.context
    assert reverse("events:feature_image", args=[event.slug]) in response.content.decode()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest events/test_feature_image.py -q -k edit_page`
Expected: FAIL — `feature_image_form` not in context.

- [ ] **Step 3: Put the form in the edit view's context**

In `events/views.py:event_edit`, in every `render(...)` of `events/event_edit.html`, add:

```python
        "feature_image_form": EventFeatureImageForm(instance=event.feature()),
```

(import it at the top of the function alongside the other form imports).

- [ ] **Step 4: Write the fieldset partial**

`events/templates/events/_feature_image_form.html`, its own `<form>` because HTML forbids nesting:

```html
{% load static %}
{# Feature image (task #504). Its own multipart form and endpoint: the
   change-review dialog re-posts the edit form as hidden textareas, which a
   file input cannot survive. #}
<section class="space-y-3 border-t border-base-300/60 pt-6">
  <h2 class="font-serif text-lg text-base-content">Feature image</h2>
  <p class="text-xs text-base-content/60">
    An image shown at the top of the event page, in the workspace, and when
    someone shares the link. Anything from a square to a wide banner works, and
    you can adjust the framing after choosing a file. It must be at least 800
    pixels wide.
  </p>

  {% with img=event.feature %}
  {% if img %}
  <figure class="space-y-1">
    <img src="{{ img.image.url }}" width="{{ img.image_width }}" height="{{ img.image_height }}"
         alt="{{ img.alt_text }}"
         class="max-h-[160px] w-auto max-w-full rounded-lg ring-1 ring-base-300/60">
    {% if img.credit %}<figcaption class="text-xs text-base-content/55">{{ img.credit }}</figcaption>{% endif %}
  </figure>
  <form method="post" action="{% url 'events:feature_image' event.slug %}">
    {% csrf_token %}
    <button type="submit" name="remove" value="1" class="btn btn-ghost btn-xs">Remove image</button>
  </form>
  {% endif %}
  {% endwith %}

  <form method="post" enctype="multipart/form-data"
        action="{% url 'events:feature_image' event.slug %}" class="space-y-3"
        id="feature-image-form">
    {% csrf_token %}
    {% with f=feature_image_form %}
    <div class="space-y-1">
      <label for="{{ f.upload.id_for_label }}" class="block text-xs text-base-content/60">
        {% if event.feature %}Replace the image{% else %}Image file{% endif %}
      </label>
      {{ f.upload }}
      {% if f.upload.errors %}<p class="text-xs text-error">{{ f.upload.errors|join:", " }}</p>{% endif %}
    </div>

    <div id="feature-image-preview" class="hidden space-y-2">
      <img id="feature-image-preview-img" alt=""
           class="max-h-[160px] w-auto max-w-full rounded-lg ring-1 ring-base-300/60">
      <button type="button" id="feature-image-adjust" class="btn btn-outline btn-xs">Adjust framing</button>
    </div>
    {{ f.crop }}

    <div class="space-y-1">
      <label for="{{ f.credit.id_for_label }}" class="block text-xs text-base-content/60">Credit (optional)</label>
      {{ f.credit }}
      <p class="text-xs text-base-content/60">Shown small under the image, for example the artist and the title of the work.</p>
    </div>

    <div class="space-y-1">
      <label for="{{ f.alt.id_for_label }}" class="block text-xs text-base-content/60">Description for screen readers (optional)</label>
      {{ f.alt }}
      <p class="text-xs text-base-content/60">Left blank, this falls back to the event title.</p>
    </div>

    <div class="space-y-1">
      <label for="{{ f.source.id_for_label }}" class="block text-xs text-base-content/60">Where this image came from</label>
      {{ f.source }}
      {% if f.source.errors %}<p class="text-xs text-error">{{ f.source.errors|join:", " }}</p>{% endif %}
    </div>

    <div class="space-y-1">
      <label for="{{ f.source_url.id_for_label }}" class="block text-xs text-base-content/60">Link to the licence or the source (required for a licensed image)</label>
      {{ f.source_url }}
      {% if f.source_url.errors %}<p class="text-xs text-error">{{ f.source_url.errors|join:", " }}</p>{% endif %}
    </div>

    <label class="flex items-start gap-2 text-xs text-base-content/80">
      {{ f.rights_confirmed }}
      <span>{{ f.rights_confirmed.label }}</span>
    </label>
    {% if f.rights_confirmed.errors %}<p class="text-xs text-error">{{ f.rights_confirmed.errors|join:", " }}</p>{% endif %}

    <button type="submit" class="btn btn-outline btn-sm">Save image</button>
    {% endwith %}
  </form>

  {# ---- Framing modal ------------------------------------------------- #}
  <dialog id="feature-cropper-modal" class="modal">
    <div class="modal-box max-w-3xl">
      <h3 class="font-serif text-lg mb-3">Adjust the framing</h3>
      <p class="text-xs text-base-content/60 mb-3">
        Drag to choose what the image shows. The frame can be anything from a
        square to two and a half times as wide as it is tall.
      </p>
      <div class="bg-base-200 rounded-lg overflow-hidden">
        <img id="feature-cropper-image" alt="" style="max-width:100%;display:block">
      </div>
      <div class="modal-action">
        <button type="button" class="btn btn-ghost" id="feature-cropper-cancel">Cancel</button>
        <button type="button" class="btn btn-primary" id="feature-cropper-apply">Use this framing</button>
      </div>
    </div>
  </dialog>
</section>
```

- [ ] **Step 5: Include it and load the cropper**

In `events/templates/events/event_edit.html`, after the CE-organization section, add:

```html
  {% include "events/_feature_image_form.html" %}
```

and in the page's `{% block extra_head %}` (create it if the template has none, matching the `{% load static %}` already at the top):

```html
<link rel="stylesheet" href="{% static 'vendor/cropper-1.6.2.min.css' %}">
```

At the bottom of `_feature_image_form.html`, the script. Cropper.js has no built-in ratio *range*, so the `crop` event clamps the box back into range as it is dragged:

```html
<script src="{% static 'vendor/cropper-1.6.2.min.js' %}"></script>
<script>
(function () {
  var MIN_RATIO = 1.0, MAX_RATIO = 2.5;
  var input   = document.getElementById("{{ feature_image_form.upload.id_for_label }}");
  var preview = document.getElementById("feature-image-preview");
  var previewImg = document.getElementById("feature-image-preview-img");
  var adjust  = document.getElementById("feature-image-adjust");
  var modal   = document.getElementById("feature-cropper-modal");
  var image   = document.getElementById("feature-cropper-image");
  var cropField = document.getElementById("{{ feature_image_form.crop.auto_id }}");
  var cropper = null, dataUrl = null;

  if (!input) return;

  input.addEventListener("change", function () {
    var file = input.files && input.files[0];
    cropField.value = "";
    if (!file) { preview.classList.add("hidden"); return; }
    var reader = new FileReader();
    reader.onload = function (e) {
      dataUrl = e.target.result;
      previewImg.src = dataUrl;
      preview.classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  });

  adjust.addEventListener("click", function () {
    if (!dataUrl) return;
    image.src = dataUrl;
    modal.showModal();
    cropper = new Cropper(image, {
      viewMode: 1, autoCropArea: 1, background: false, movable: false,
      zoomable: false, rotatable: false,
      crop: function (event) {
        var w = event.detail.width, h = event.detail.height;
        if (!w || !h) return;
        var ratio = w / h;
        if (ratio > MAX_RATIO) { cropper.setData({ width: h * MAX_RATIO }); }
        else if (ratio < MIN_RATIO) { cropper.setData({ height: w / MIN_RATIO }); }
      }
    });
  });

  function close() {
    if (cropper) { cropper.destroy(); cropper = null; }
    modal.close();
  }

  document.getElementById("feature-cropper-cancel").addEventListener("click", close);
  document.getElementById("feature-cropper-apply").addEventListener("click", function () {
    if (cropper) {
      var d = cropper.getData(true);
      cropField.value = JSON.stringify({ x: d.x, y: d.y, width: d.width, height: d.height });
      previewImg.src = cropper.getCroppedCanvas({ maxWidth: 800 }).toDataURL("image/png");
    }
    close();
  });
})();
</script>
```

- [ ] **Step 6: Rebuild the CSS and run the tests**

```bash
npm run build:css && uv run pytest events/ -q
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add events/templates/events/ events/views.py events/test_feature_image.py
git commit -m "feat(events): feature-image fieldset and framing cropper on the edit page (task #504)"
```

---

### Task 5: Rendering on the event page and the Workspace

**Files:**
- Create: `events/templates/events/_feature_image.html`
- Modify: `events/templates/events/event_detail.html`
- Modify: `workgroups/templates/workgroups/detail.html`
- Test: `events/test_feature_image.py` (append)

**Interfaces:**
- Consumes: `Event.feature()`, `EventFeatureImage.alt_text`, `Workgroup.primary_event()`.
- Produces: the partial `events/_feature_image.html`, taking `img` and optional `size_class`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_the_event_page_shows_the_image_and_its_credit(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event, credit="Rene Magritte")
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert event.feature().image.url in body
    assert "Rene Magritte" in body


@pytest.mark.django_db
def test_the_alt_attribute_falls_back_to_the_title(client, event, faculty, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event)
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert 'alt="Seminar XI"' in body


@pytest.mark.django_db
def test_an_event_without_an_image_renders_no_figure(client, event):
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "lsp-feature-image" not in body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_feature_image.py -q -k "event_page or alt_attribute"`
Expected: FAIL — the image URL is absent from the page.

- [ ] **Step 3: Write the partial**

`events/templates/events/_feature_image.html`:

```html
{% comment %}
  An event's feature image (task #504).

  Both dimensions are bounded rather than the height being fixed: the image is
  never taller than the band and never wider than the column, and is never asked
  to be both at once, so a 2.5:1 runs full width, a square sits as a narrow
  plate, and on a phone everything simply gets shorter. Nothing is cropped at
  display time; the shape was settled at upload.

  Args:
    img        — an EventFeatureImage (nothing renders without one).
    size_class — the height bounds; defaults to the event-page band.
{% endcomment %}
{% if img %}
<figure class="lsp-feature-image space-y-1.5">
  <img src="{{ img.image.url }}" width="{{ img.image_width }}" height="{{ img.image_height }}"
       alt="{{ img.alt_text }}"
       class="{{ size_class|default:'max-h-[200px] sm:max-h-[340px]' }} w-auto max-w-full rounded-xl ring-1 ring-base-300/60">
  {% if img.credit %}
  <figcaption class="text-xs text-base-content/55">{{ img.credit }}</figcaption>
  {% endif %}
</figure>
{% endif %}
```

- [ ] **Step 4: Render it on the event page**

In `events/templates/events/event_detail.html`, inside `<header>`, between the breadcrumb `</nav>` and the `<h1>`:

```html
    {% include "events/_feature_image.html" with img=event.feature %}
```

- [ ] **Step 5: Render it on the Workspace masthead**

In `workgroups/templates/workgroups/detail.html`, inside the masthead's content column, immediately before the `<h1>`:

```html
        {% with feature=workgroup.primary_event.feature %}
        {% if feature %}
        {% include "events/_feature_image.html" with img=feature size_class="max-h-[140px] sm:max-h-[180px]" %}
        {% endif %}
        {% endwith %}
```

- [ ] **Step 6: Rebuild the CSS and run the tests**

```bash
npm run build:css && uv run pytest events/ workgroups/ -q
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add events/templates workgroups/templates events/test_feature_image.py
git commit -m "feat(events): render the feature image on the event page and workspace (task #504)"
```

---

### Task 6: OpenGraph share preview

**Files:**
- Modify: `events/views.py` (`event_detail` context)
- Modify: `events/templates/events/event_detail.html`
- Test: `events/test_feature_image.py` (append)

**Interfaces:**
- Consumes: `Event.feature()`, `settings.SITE_BASE_URL`.
- Produces: context keys `og_url` and `og_image` on the event detail page.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_the_event_page_carries_opengraph_tags_with_an_image(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.SITE_BASE_URL = "https://lacanschool.org"
    client.force_login(faculty)
    _post(client, event)
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert 'property="og:title" content="Seminar XI"' in body
    assert 'property="og:image"' in body
    assert 'name="twitter:card" content="summary_large_image"' in body
    assert "https://lacanschool.org/events/seminar-xi/" in body


@pytest.mark.django_db
def test_an_event_without_an_image_still_carries_text_opengraph_tags(client, event, settings):
    settings.SITE_BASE_URL = "https://lacanschool.org"
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert 'property="og:title" content="Seminar XI"' in body
    assert 'property="og:image"' not in body
    assert 'name="twitter:card" content="summary"' in body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_feature_image.py -q -k opengraph`
Expected: FAIL — no `og:` markup on the page.

- [ ] **Step 3: Add the absolute-URL helper and the context**

In `events/views.py`:

```python
def _absolute(url: str) -> str:
    """An absolute URL for sharing. In production media is already absolute (S3)."""
    if url.startswith(("http://", "https://")):
        return url
    return settings.SITE_BASE_URL.rstrip("/") + url
```

In `event_detail`'s context, alongside the existing keys:

```python
        "og_url": _absolute(reverse("events:detail", args=[event.slug])),
        "og_image": _absolute(event.feature().image.url) if event.feature() else "",
```

- [ ] **Step 4: Emit the tags**

In `events/templates/events/event_detail.html`, after the `{% block title %}` line:

```html
{% block extra_head %}
{# Share preview (task #504). Scoped to this template on purpose: giving the
   whole site social metadata is a separate task with separate questions. #}
<meta property="og:title" content="{{ event.title }}">
<meta property="og:type" content="website">
<meta property="og:url" content="{{ og_url }}">
<meta property="og:site_name" content="Lacanian School of Psychoanalysis">
{% if event.description %}
<meta property="og:description" content="{{ event.description|striptags|truncatewords:30 }}">
{% endif %}
{% with img=event.feature %}
{% if img %}
<meta property="og:image" content="{{ og_image }}">
<meta property="og:image:width" content="{{ img.image_width }}">
<meta property="og:image:height" content="{{ img.image_height }}">
<meta property="og:image:alt" content="{{ img.alt_text }}">
<meta name="twitter:card" content="summary_large_image">
{% else %}
<meta name="twitter:card" content="summary">
{% endif %}
{% endwith %}
{% endblock %}
```

- [ ] **Step 5: Run the whole suite and the linter**

```bash
uv run pytest -q && uv run ruff check .
```
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add events/views.py events/templates/events/event_detail.html events/test_feature_image.py
git commit -m "feat(events): OpenGraph share preview for an event (task #504)"
```

---

## Self-review

**Spec coverage.** Model → Task 1. Pipeline, ratio clamp, bounds, compression → Task 2. Own form and endpoint, rights, cropper, no-JS parity → Tasks 3 and 4. Both render surfaces and the layout rule → Task 5. OpenGraph → Task 6. Not-in-`REVIEWABLE_FIELDS` needs no code, since the field is never added; the constraint is recorded above.

**Names used consistently across tasks:** `EventFeatureImage`, `Event.feature()`, `alt_text`, `feature_images.render`, `feature_images.bound_original`, `EventFeatureImageForm.save(event, user)`, context keys `feature_image_form`, `og_url`, `og_image`, URL name `events:feature_image`.
