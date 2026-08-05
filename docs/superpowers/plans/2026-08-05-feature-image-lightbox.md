# Feature Image Lightbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking an event's feature image opens it centred at full size, served from a second, larger render.

**Architecture:** `render()` grows a `box` parameter so a 2400×1350 `image_full` can be produced from the same crop as the 1600×900 page render, stored only when genuinely larger. The partial wraps the `<img>` in a real anchor to the full render — which is the no-JS behaviour and the accessible one — and JavaScript upgrades that click to a DaisyUI `<dialog class="modal">`.

**Tech Stack:** Django 5.2, Pillow, pytest-django, Tailwind v4 + DaisyUI v5 (no new dependency).

**Spec:** `docs/superpowers/specs/2026-08-05-feature-image-lightbox-design.md`

## Global Constraints

- `FULL_BOX = (2400, 1350)`; the existing `RENDER_BOX = (1600, 900)` is unchanged.
- `image_full` is stored **only when wider than** `image`; `modal_image` returns `image_full or image`.
- Dimension columns are assigned by hand after `.save()` — Django refreshes `width_field`/`height_field` only when *replacing* a file.
- No backfill, no new dependency, no pan/zoom, no gallery.
- DaisyUI semantic tokens only; any Tailwind class must appear literally in a `.html` file.
- Member-facing copy uses commas, not em dashes.

---

### Task 1: The larger render

**Files:**
- Modify: `events/feature_images.py`
- Modify: `events/models.py` (`EventFeatureImage`)
- Modify: `events/forms.py` (`EventFeatureImageForm`)
- Create: `events/migrations/00XX_eventfeatureimage_image_full.py` (generated)
- Test: `events/test_feature_image.py`

**Interfaces:**
- Produces: `feature_images.FULL_BOX`; `render(source, crop=None, box=RENDER_BOX)`; fields `image_full`, `image_full_width`, `image_full_height`; property `EventFeatureImage.modal_image`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_full_render_is_larger_and_keeps_the_ratio():
    out = _rendered(feature_images.render(_upload(size=(4000, 2000)),
                                          box=feature_images.FULL_BOX))
    assert out.width <= feature_images.FULL_BOX[0]
    assert out.height <= feature_images.FULL_BOX[1]
    assert out.width > feature_images.RENDER_BOX[0]
    assert out.width / out.height == pytest.approx(2.0, abs=0.02)


@pytest.mark.django_db
def test_a_big_upload_stores_a_separate_full_render(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event, upload=_upload(size=(4000, 2000)))
    img = event.feature()
    assert img.image_full
    assert img.image_full_width > img.image_width
    assert img.modal_image == img.image_full


@pytest.mark.django_db
def test_a_modest_upload_stores_no_duplicate(
    client, event, faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(faculty)
    _post(client, event, upload=_upload(size=(1200, 600)))
    img = event.feature()
    assert not img.image_full
    assert img.modal_image == img.image
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_feature_image.py -q -p no:randomly -k "full_render or full or duplicate"`
Expected: FAIL — `AttributeError: module 'events.feature_images' has no attribute 'FULL_BOX'`.

- [ ] **Step 3: Parameterize the renderer**

In `events/feature_images.py`, beside `RENDER_BOX`:

```python
#: The modal serves this one. Bounded rather than unbounded because the point is
#: to look at the image, not to ship a 6000px scan to a phone.
FULL_BOX = (2400, 1350)
```

Change the signature and the one `thumbnail` call:

```python
def render(source, crop: dict | None = None, box: tuple[int, int] = RENDER_BOX) -> ContentFile:
    """Render ``source`` to a bounded WebP ``ContentFile`` inside the ratio range.

    ``box`` selects the size: the page band uses :data:`RENDER_BOX`, the
    full-size modal :data:`FULL_BOX`. Both come from the same crop, so they can
    never disagree about framing.
    """
```

```python
    img.thumbnail(box, Image.LANCZOS)
```

The `MIN_RENDER_WIDTH` check stays as it is: it guards the page render, and a
`FULL_BOX` pass on the same source can only be larger.

- [ ] **Step 4: Add the fields**

In `events/models.py`, after `image_height` on `EventFeatureImage`:

```python
    image_full = models.ImageField(
        upload_to="events/feature/full/%Y/", blank=True,
        width_field="image_full_width", height_field="image_full_height",
        help_text=(
            "Larger render for the full-size modal. Blank when the upload was "
            "too small for this to differ from `image`."
        ),
    )
    image_full_width = models.PositiveIntegerField(default=0)
    image_full_height = models.PositiveIntegerField(default=0)
```

And beside `alt_text`:

```python
    @property
    def modal_image(self):
        """The file the full-size view serves.

        ``image_full`` is absent whenever the upload was too small for it to
        differ, so this keeps every template from having to know that.
        """
        return self.image_full or self.image
```

- [ ] **Step 5: Save it in the form**

In `events/forms.py`, in `clean()`, beside the existing renders:

```python
        self.render_blob = self.original_blob = self.full_blob = None
        if upload:
            try:
                self.render_blob = feature_images.render(upload, cleaned.get("crop"))
                self.full_blob = feature_images.render(
                    upload, cleaned.get("crop"), box=feature_images.FULL_BOX,
                )
                self.original_blob = feature_images.bound_original(upload)
            except feature_images.InvalidImage as exc:
                self.add_error("upload", str(exc))
```

And in `save()`, after the page render is stored:

```python
            # thumbnail() never upscales, so a source between the 800px floor and
            # RENDER_BOX yields two identical files. Keep the larger one only
            # when it is actually larger; modal_image falls back.
            obj.image_full.delete(save=False)
            obj.image_full = None
            obj.image_full_width = obj.image_full_height = 0
            full = Image.open(self.full_blob)
            self.full_blob.seek(0)
            if full.width > obj.image_width:
                obj.image_full.save(f"{event.slug}-full.webp", self.full_blob, save=False)
                obj.image_full_width, obj.image_full_height = full.size
```

Add `from PIL import Image` to the imports of `events/forms.py`.

- [ ] **Step 6: Make and apply the migration**

```bash
uv run python manage.py makemigrations events && uv run python manage.py migrate
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest events/test_feature_image.py -q -p no:randomly`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add events/feature_images.py events/models.py events/forms.py events/migrations events/test_feature_image.py
git commit -m "feat(events): a larger render for the full-size view (task #504)"
```

---

### Task 2: The anchor and the modal

**Files:**
- Modify: `events/templates/events/_feature_image.html`
- Test: `events/test_feature_image.py`

**Interfaces:**
- Consumes: `EventFeatureImage.modal_image`, `.alt_text`, `.credit`.
- Produces: the rendered anchor and `<dialog id="feature-image-modal">`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_the_image_links_to_the_full_render(
    client, special_event, special_faculty, settings, tmp_path,
):
    settings.MEDIA_ROOT = str(tmp_path)
    client.force_login(special_faculty)
    _post(client, special_event, upload=_upload(size=(4000, 2000)))
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    img = special_event.feature()
    assert f'href="{img.image_full.url}"' in body
    assert 'id="feature-image-modal"' in body


@pytest.mark.django_db
def test_an_event_without_an_image_renders_no_modal(client, special_event):
    body = client.get(reverse("events:detail", args=[special_event.slug])).content.decode()
    assert "feature-image-modal" not in body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_feature_image.py -q -p no:randomly -k "links_to_the_full or no_modal"`
Expected: FAIL — no `href` and no dialog in the page.

- [ ] **Step 3: Rewrite the partial**

`events/templates/events/_feature_image.html` — the `<img>` and its classes are
unchanged; it gains an anchor around it and a dialog after it:

```html
{% if img %}
<figure class="lsp-feature-image space-y-1.5">
  {% comment %}
    A real anchor, not a div with a click handler: without JavaScript it opens
    the full render directly, and it is focusable and keyboard-operable because
    of what it is. The script below upgrades the click to the modal.
  {% endcomment %}
  <a href="{{ img.modal_image.url }}" class="block cursor-zoom-in"
     data-feature-image-open aria-label="Open the image at full size">
    <img src="{{ img.image.url }}"
         width="{{ img.image_width }}" height="{{ img.image_height }}"
         alt="{{ img.alt_text }}"
         class="{{ size_class|default:'max-h-[260px] sm:max-h-[340px]' }} w-auto max-w-full rounded-xl ring-1 ring-base-300/60">
  </a>
  {% if img.credit %}
  <figcaption class="text-xs text-base-content/55">{{ img.credit }}</figcaption>
  {% endif %}
</figure>

<dialog id="feature-image-modal" class="modal">
  <div class="modal-box max-w-none w-auto bg-transparent shadow-none p-0 overflow-visible">
    <img src="{{ img.modal_image.url }}" alt="{{ img.alt_text }}"
         class="max-w-[95vw] max-h-[90vh] w-auto h-auto rounded-lg shadow-2xl">
    {% if img.credit %}
    <p class="mt-2 text-center text-xs text-base-content/70">{{ img.credit }}</p>
    {% endif %}
  </div>
  {# DaisyUI's click-outside-to-close idiom; Escape works on <dialog> for free. #}
  <form method="dialog" class="modal-backdrop"><button aria-label="Close">close</button></form>
</dialog>

<script>
(function () {
  var modal = document.getElementById("feature-image-modal");
  var link = document.querySelector("[data-feature-image-open]");
  if (!modal || !link || typeof modal.showModal !== "function") return;
  link.addEventListener("click", function (e) {
    e.preventDefault();
    modal.showModal();
  });
})();
</script>
{% endif %}
```

- [ ] **Step 4: Run the tests and rebuild the CSS**

```bash
uv run pytest events/ workgroups/ -q -p no:randomly && npm run build:css
```
Expected: PASS.

- [ ] **Step 5: Look at it**

Start the server, open an event with an image, click it, and confirm: the image
centres at full size, Escape closes it, clicking the backdrop closes it, and the
page behind does not scroll under the modal.

- [ ] **Step 6: Commit**

```bash
git add events/templates/events/_feature_image.html events/test_feature_image.py
git commit -m "feat(events): open the feature image at full size in a modal (task #504)"
```

---

## Self-review

**Spec coverage.** Second render, the store-only-when-larger rule, and
`modal_image` → Task 1. Anchor, no-JS fallback, dialog, credit, both surfaces
(one partial) → Task 2. No backfill and no new dependency are constraints, not
tasks.

**Names used consistently:** `FULL_BOX`, `render(source, crop, box)`,
`image_full`, `image_full_width`, `image_full_height`, `modal_image`,
`feature-image-modal`, `data-feature-image-open`.

**One risk worth naming:** the partial renders a `<script>` and a fixed element
id, so a page including it twice would bind only the first. An event has one
feature image and each surface includes the partial once, which the tests pin by
asserting a single dialog.
