# CE Accreditor Naming and Zoom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Name each continuing-education accreditor in the event's CE panel, grow its logo chips, and let each mark open at full size in a modal — then fix the one accreditor on prod whose "logo" is a composite hiding the mandated approval text.

**Architecture:** All display work lands in one template, `events/templates/events/_ce_credits.html`, which is rendered at most once per page. The panel changes from a flat "every org's logos, then every org's statements" list into a per-organization group (name → logos → statement), each logo becomes a real anchor to its own file, and one shared `<dialog>` per page upgrades those anchors to a lightbox. The stored-resolution bound in `events/ce_images.py` rises so a zoomed mark is not a downsampled one. Prod data is corrected last, after the code is live.

**Tech Stack:** Django 5.2 templates, Tailwind v4 + DaisyUI v5, Pillow (WebP), pytest-django, S3 (django-storages), AWS SSM for prod execution.

## Global Constraints

- **DaisyUI semantic tokens only** (`bg-base-100`, `text-base-content`, …), never hardcoded colors — **except** the accreditor chips and the modal plate, which are `bg-white` in both themes because accreditor marks are dark-on-transparent. This is a sanctioned, pre-existing exception (task #486).
- **Tailwind v4 scans templates only.** Any class named in Python would be stripped from the prod build. Every class in this plan lives in a `.html` file, so this is satisfied by construction.
- **Django messages render once**, from `core/_messages.html`. Never add a per-page loop. (Not touched here; stated because it is test-enforced.)
- **CE stays out of `events/review.py::REVIEWABLE_FIELDS`.** Nothing in this plan touches that list.
- **The approval statement is transcribed verbatim, with no trailing period** (Rico, 2026-08-05).
- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Both must be green before any push — a single failing test silently aborts the deploy.

---

### Task 1: Raise the stored-logo bound

`events/ce_images.MAX_BOX` is 800×**400**. Both logos about to be uploaded are squarish (459×431 and 605×548), so that bound would *downsample* them — 426×400 and 441×400 — discarding exactly the resolution the new zoom modal wants. Raise the box to 1200×600.

**Files:**
- Modify: `events/ce_images.py:17-19`
- Test: `events/test_ce_images.py:30-34` (modify), plus one new test

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `MAX_BOX = (1200, 600)`. `normalize_logo(source) -> ContentFile` is unchanged in signature and behavior; only the bound moves.

- [ ] **Step 1: Update the existing bound test to the new box, and add the squarish-mark regression test**

In `events/test_ce_images.py`, replace `test_an_oversized_logo_is_fitted_inside_the_box_without_distortion` with the version below and add the new test after it:

```python
def test_an_oversized_logo_is_fitted_inside_the_box_without_distortion():
    out = normalize_logo(io.BytesIO(_png_bytes(size=(4000, 1000))))
    width, height = Image.open(io.BytesIO(out.read())).size
    assert width <= 1200 and height <= 600
    assert width == 1200 and height == 300      # 4:1 aspect ratio preserved


def test_a_squarish_seal_is_stored_without_downsampling():
    """The real APA Approved Sponsor mark is 459x431. The former 800x400 box
    shrank it to 426x400, throwing away resolution the full-size modal (task
    #506) then wants back — and no original is retained for a logo, so that
    loss was permanent."""
    out = normalize_logo(io.BytesIO(_png_bytes(size=(459, 431))))
    assert Image.open(io.BytesIO(out.read())).size == (459, 431)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_images.py -v`
Expected: FAIL — `test_an_oversized_logo_is_fitted_inside_the_box_without_distortion` asserts `width == 1200` but gets 800; `test_a_squarish_seal_is_stored_without_downsampling` gets `(426, 400)`.

- [ ] **Step 3: Raise the bound**

In `events/ce_images.py`, replace lines 17-19:

```python
#: Largest stored logo, in pixels. Rendered at max 192x64 CSS pixels on the
#: event page and opened at full size in a modal (task #506), so the box leaves
#: headroom for retina and for that modal. The former 800x400 was actively wrong
#: for a squarish mark: it downsampled a 459x431 accreditor seal to 426x400, and
#: no original is retained for a logo, so that loss could not be undone.
MAX_BOX = (1200, 600)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_images.py -v`
Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add events/ce_images.py events/test_ce_images.py
git commit -m "feat(events): store accreditor logos at 1200x600 (task #506)"
```

---

### Task 2: Group the CE panel by organization and name each one

Today the panel flattens every organization's logos into one row, then lists every statement after it. With two accreditors that is ambiguous — which statement belongs to which body? Grouping per organization fixes that and gives the name a natural home. The organization's `url` link moves from the logo to the **name**, which is what frees the image to become a click target in Task 3.

**Files:**
- Modify: `events/templates/events/_ce_credits.html` (whole file)
- Test: `events/test_ce_display.py`

**Interfaces:**
- Consumes: `MAX_BOX` from Task 1 only indirectly (no code dependency).
- Produces: the per-org group markup Task 3 wraps. Each logo chip is a `<span class="… bg-white p-2">` in this task; Task 3 turns that span into an `<a>`.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_ce_display.py`:

```python
@pytest.mark.django_db
def test_the_panel_names_the_accrediting_organization(client, event, settings, tmp_path):
    """The logos alone said nothing about who accredited the event (task #506)."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(
        name="Greater Pittsburgh Psychological Association",
        url="https://gppa.wildapricot.org/",
    )
    org.add_logos([_blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Greater Pittsburgh Psychological Association" in body


@pytest.mark.django_db
def test_the_name_carries_the_outbound_link(client, event, settings, tmp_path):
    """The link used to wrap the logo, which would collide with click-to-zoom;
    it belongs on the name now (task #506)."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="GPPA", url="https://gppa.wildapricot.org/")
    org.add_logos([_blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert '<a href="https://gppa.wildapricot.org/" target="_blank" rel="noopener"' in body
    assert ">GPPA</a>" in body


@pytest.mark.django_db
def test_an_organization_without_a_url_renders_its_name_as_plain_text(client, event):
    org = CEOrganization.objects.create(name="Unlinked Accreditor")
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "Unlinked Accreditor" in body
    assert 'href=""' not in body


@pytest.mark.django_db
def test_each_statement_sits_inside_its_own_organizations_group(client, event, settings, tmp_path):
    """Two accreditors must not have their mandated language pooled at the
    bottom, where either statement reads as applying to both sets of marks."""
    settings.MEDIA_ROOT = str(tmp_path)
    first = CEOrganization.objects.create(name="Alpha Board", statement="Alpha says so.")
    first.add_logos([_blob()])
    second = CEOrganization.objects.create(name="Beta Board", statement="Beta says so.")
    second.add_logos([_blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(first, second)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    # Ordering is CEOrganization.Meta.ordering = ("name",), so Alpha precedes Beta.
    assert body.index("Alpha Board") < body.index("Alpha says so.") < body.index("Beta Board")
    assert body.index("Beta Board") < body.index("Beta says so.")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_display.py -v`
Expected: FAIL — the name is not rendered (`test_the_panel_names_the_accrediting_organization`), the link is on the logo not the name, and both statements currently render after both logo rows.

- [ ] **Step 3: Rewrite the panel body**

Replace the whole of `events/templates/events/_ce_credits.html` with:

```html
{% comment %}Continuing-education credits + accreditor logos (tasks #486, #506).

Rendered at the bottom of About in events/_event_summary.html, and standing on
its own when the event has no description yet. Expects: event.

Grouped per organization — name, then its marks, then the approval language it
requires — rather than every logo in one row and every statement after them,
which with two accreditors leaves each statement reading as if it applied to
both sets of marks.

The name carries the outbound link that used to wrap the logo. That is not a
style preference: it frees the image itself to be the click target.

The logo chips are deliberately paper-white in BOTH themes rather than a
DaisyUI token: accreditor logos are near-universally dark-on-transparent and
would disappear against the dark theme. Same reasoning as the header crest.
{% endcomment %}
<div class="space-y-3 rounded-xl border border-base-300/60 bg-base-200/40 p-4">
  <p class="text-xs uppercase tracking-wide text-base-content/50">Continuing education</p>

  <p class="text-sm text-base-content/90">{{ event.ce_credits_label }}</p>

  {% with orgs=event.ce_organizations.all %}
  {% for org in orgs %}
  <div class="space-y-2">
    <p class="text-sm text-base-content/80">
      {% if org.url %}<a href="{{ org.url }}" target="_blank" rel="noopener" class="link link-hover">{{ org.name }}</a>{% else %}{{ org.name }}{% endif %}
    </p>

    {% if org.logos.all %}
    <div class="flex flex-wrap items-center gap-3">
      {% for logo in org.logos.all %}
      <span class="inline-flex items-center rounded-lg border border-base-300/60 bg-white p-2">
        <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
             class="max-h-16 max-w-48 object-contain">
      </span>
      {% endfor %}
    </div>
    {% endif %}

    {% if org.statement %}
    <p class="text-xs leading-relaxed text-base-content/60">{{ org.statement }}</p>
    {% endif %}
  </div>
  {% endfor %}
  {% endwith %}

  {% if event.ce_note %}
  <p class="text-xs leading-relaxed text-base-content/60">{{ event.ce_note }}</p>
  {% endif %}
</div>
```

- [ ] **Step 4: Run the full CE test file to verify it passes**

Run: `uv run pytest events/test_ce_display.py -v`
Expected: all PASS, including the pre-existing `test_ce_panel_shows_logo_statement_and_note` (it asserts `alt="American Psychological Association logo"` and that the url appears in the body — both still true) and `test_every_logo_in_the_set_is_shown`.

- [ ] **Step 5: Commit**

```bash
git add events/templates/events/_ce_credits.html events/test_ce_display.py
git commit -m "feat(events): group the CE panel by accreditor and name each one (task #506)"
```

---

### Task 3: Open a mark at full size

Each logo becomes a real anchor to its own file, and one shared `<dialog>` per page upgrades the click to a lightbox — the task #504 pattern. The anchor is what makes the control work with no JavaScript, focusable, and keyboard-operable without added `role` or `tabindex`. One dialog rather than one per logo is safe because this partial renders at most once per page (`_event_summary.html:80` and `:84` are an `{% if %}`/`{% elif %}`), and it scales to N logos across M organizations.

The modal image sits on a **white plate**: the APA seal's background is fully transparent, and `.lsp-lightbox[open]` is 88% black, so a bare mark would vanish.

**Files:**
- Modify: `events/templates/events/_ce_credits.html`
- Modify: `assets/css/input.css:861` (comment only)
- Test: `events/test_ce_display.py`

**Interfaces:**
- Consumes: the per-org group markup from Task 2.
- Produces: each chip is `<a href="{{ logo.image.url }}" data-ce-logo data-ce-caption="{{ org.name }}">`; the dialog is `id="ce-logo-modal"` with `[data-ce-logo-image]` and `[data-ce-logo-caption]` inside it.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_ce_display.py`:

```python
@pytest.mark.django_db
def test_every_logo_is_an_anchor_to_its_own_file(client, event, settings, tmp_path):
    """The no-JS path, and what makes each mark individually zoomable: two marks
    on one accreditor must link to two different files, not one shared modal
    target (task #506)."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="Two Marks")
    first, second = org.add_logos([_blob(), _blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert f'href="{first.image.url}" ' in body
    assert f'href="{second.image.url}" ' in body
    assert first.image.url != second.image.url
    assert body.count("data-ce-logo ") == 2


@pytest.mark.django_db
def test_the_lightbox_is_rendered_once_for_the_whole_panel(client, event, settings, tmp_path):
    """One dialog, whatever the number of marks — the partial renders at most
    once per page, so a dialog per logo would only duplicate markup and ids."""
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="Three Marks")
    org.add_logos([_blob(), _blob(), _blob()])
    event.offers_ce = True
    event.save()
    event.ce_organizations.add(org)

    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert body.count('id="ce-logo-modal"') == 1
    assert "lsp-lightbox" in body


@pytest.mark.django_db
def test_no_lightbox_when_the_event_claims_no_organization(client, event):
    """An event marked as offering CE before an accreditor is recorded should
    not carry a dialog with nothing to show."""
    event.offers_ce = True
    event.save()
    body = client.get(reverse("events:detail", args=[event.slug])).content.decode()
    assert "CE credits available." in body
    assert 'id="ce-logo-modal"' not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest events/test_ce_display.py -v`
Expected: FAIL — the logos are `<span>`s with no `href`, and no `ce-logo-modal` exists.

- [ ] **Step 3: Turn the chips into anchors and add the shared dialog**

In `events/templates/events/_ce_credits.html`, replace the logo `<span>`…`</span>` block from Task 2:

```html
      <span class="inline-flex items-center rounded-lg border border-base-300/60 bg-white p-2">
        <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
             class="max-h-16 max-w-48 object-contain">
      </span>
```

with the anchor version — a real link to the file, which the script below upgrades to the modal:

```html
      <a href="{{ logo.image.url }}" data-ce-logo data-ce-caption="{{ org.name }}"
         aria-label="Open the {{ org.name }} logo at full size"
         class="inline-flex cursor-zoom-in items-center rounded-lg border border-base-300/60 bg-white p-2">
        <img src="{{ logo.image.url }}" alt="{{ org.name }} logo"
             class="max-h-16 max-w-48 object-contain">
      </a>
```

Then, still inside the `{% with orgs=… %}` block and immediately after `{% endfor %}` (so it is emitted once, and only when there is something to open), insert:

```html
  {% if orgs %}
  <dialog id="ce-logo-modal" class="modal lsp-lightbox">
    <div class="modal-box w-auto max-w-none overflow-visible bg-transparent p-0 shadow-none">
      {# A white plate, not the bare scrim: an accreditor mark is dark-on-transparent
         and would vanish against .lsp-lightbox[open]'s 88% black. #}
      <div class="rounded-lg bg-white p-6 shadow-2xl">
        <img data-ce-logo-image src="" alt=""
             class="max-h-[75vh] max-w-[90vw] h-auto w-auto object-contain">
      </div>
      <p data-ce-logo-caption class="lsp-lightbox-caption mt-3 text-center text-xs"></p>
    </div>
    {# DaisyUI's click-outside idiom; Escape closes a <dialog> for free. #}
    <form method="dialog" class="modal-backdrop"><button aria-label="Close">close</button></form>
  </dialog>

  <script>
  (function () {
    var modal = document.getElementById("ce-logo-modal");
    if (!modal || typeof modal.showModal !== "function") return;
    var image = modal.querySelector("[data-ce-logo-image]");
    var caption = modal.querySelector("[data-ce-logo-caption]");
    document.querySelectorAll("[data-ce-logo]").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        var name = link.getAttribute("data-ce-caption");
        image.src = link.getAttribute("href");
        image.alt = name + " logo";
        caption.textContent = name;
        modal.showModal();
      });
    });
  })();
  </script>
  {% endif %}
```

- [ ] **Step 4: Widen the lightbox CSS comment**

In `assets/css/input.css`, replace line 861's opening phrase so the rules no longer read as belonging to one caller:

```css
/* Lightbox scrim, shared by the event feature image (task #504) and the CE
   accreditor logos (task #506). Plain CSS, and note the `[open]`: DaisyUI
```

Leave the rest of that comment and both rules exactly as they are.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest events/test_ce_display.py events/test_ce_images.py events/test_ce.py events/test_ce_edit.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite and the linter**

Run: `uv run pytest -q && uv run ruff check .`
Expected: green. A single failing test silently aborts the deploy, so this gate is not optional.

- [ ] **Step 7: Commit**

```bash
git add events/templates/events/_ce_credits.html events/test_ce_display.py assets/css/input.css
git commit -m "feat(events): open a CE accreditor mark at full size (task #506)"
```

---

### Task 4: Verify in a browser

The task #504 lightbox work found two scrim bugs by looking rather than by reading markup. Do the same here — especially the white plate, whose whole purpose is a contrast problem no test can see.

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: nothing; a go/no-go before deploying.

- [ ] **Step 1: Build the CSS and seed a local event with two accreditors**

```bash
npm run build:css
```

Then, in `uv run python manage.py shell`, create a published event that offers CE and claims two organizations — one with a transparent-background mark and one with an opaque white one, mirroring the APA seal and the GPPA mark — so both extremes of the plate problem are on screen. Give one organization two logos and a statement, the other one logo and no `url`.

- [ ] **Step 2: Run the dev server and open the event page**

```bash
uv run python manage.py runserver
```

Open `http://localhost:8000/events/<slug>/` in Chrome.

- [ ] **Step 3: Check the resting panel in both themes and at three widths**

Confirm: each organization's name sits above its own marks with its own statement beneath; the chips are visibly larger than before; the transparent-background mark is legible on the white chip in **both** the light and dark themes (toggle it); nothing overflows horizontally at 375px, 768px, and 1280px.

- [ ] **Step 4: Check the modal**

Click each mark in turn. Confirm: the modal opens showing **that** mark, not another; the mark is clearly legible against the white plate on the dark scrim; the caption reads the organization's name in a light color that is readable on the scrim (this is the trap from #504 — `text-base-content` in the light theme is near-black type on a near-black scrim, which is why `.lsp-lightbox-caption` exists).

- [ ] **Step 5: Check all three dismissal paths**

Close the modal by (a) clicking the backdrop outside the plate, (b) pressing **Escape with a real key press** — a synthetic `KeyboardEvent` does not trigger the UA default, so this must be an actual keystroke — and (c) reopening and confirming Tab reaches the close control. Then confirm the no-JS path: the chip's `href` points at the logo file, so a middle-click or "Open link in new tab" shows the image directly.

- [ ] **Step 6: Commit nothing; report findings**

If anything is wrong, fix it in the relevant task's files, re-run `uv run pytest -q`, and commit the fix before proceeding.

---

### Task 5: Merge and deploy

**Files:** none (git + CI).

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: the code live on prod, which Task 6 requires — the prod data fix creates two logo rows whose files must be normalized by the *new* `MAX_BOX`.

- [ ] **Step 1: Merge the branch to main and push**

```bash
git checkout main && git merge --no-ff jade-cedar -m "Merge jade-cedar: name and enlarge the CE accreditors (task #506)" && git push
```

- [ ] **Step 2: Watch the Deploy workflow to green**

```bash
gh run watch --repo ricopicone/lsp-website
```

Expected: the test suite passes, then SSM triggers `~/bin/deploy.sh` on EC2. **A push to main is not a deploy** — a single failing test aborts it silently. Confirm the Deploy run itself is green on this SHA before continuing.

---

### Task 6: Correct the GPPA data on prod

Replace the composite with the accreditor's two original marks, and move the mandated paragraph out of the pixels and into `statement`. Runs after the deploy so the new `MAX_BOX` governs the stored files.

Source files: `/Users/picone/Downloads/cesforseminar/image2.png` (APA Approved Sponsor seal, 459×431, transparent) and `image4.jpg` (GPPA mark, 605×548, opaque). `image1.png` is the statement as a picture of text and is **not** uploaded.

The new logos are appended as `sort_order` 2 and 3 and the composite (order 1) is deleted afterwards — appending first avoids `add_logos()` regenerating the filename `…-1.webp` and colliding with the object already in S3.

**Files:**
- Create (scratch, not committed): a local normalize script and an SSM payload.
- Modify: prod database rows only.

**Interfaces:**
- Consumes: `normalize_logo` and `MAX_BOX` from Task 1, live on prod after Task 5.
- Produces: `CEOrganization` #2 with two logo rows, a populated `statement`, and `url = "https://gppa.wildapricot.org/"`.

- [ ] **Step 1: Normalize the two marks locally with the deployed pipeline**

Using the repo's own `events.ce_images.normalize_logo` (so the stored files are identical in kind to any faculty upload), write both to the scratchpad as `gppa-apa.webp` and `gppa-mark.webp`. Print each result's pixel size and assert it matches the source size — with `MAX_BOX = (1200, 600)` neither should be downsampled (459×431 and 605×548). If either shrank, Task 1 did not deploy and this task must stop.

- [ ] **Step 2: Confirm how the existing object is stored, then upload both files to S3**

```bash
aws s3api head-object --profile lsp --bucket lsp-website-media-uswest2 --key ce-organizations/greater-pittsburgh-psychological-association-1.webp
```

Note its `ContentType` and check whether the bucket serves objects publicly via policy or per-object ACL (`aws s3api get-bucket-policy --profile lsp --bucket lsp-website-media-uswest2`). Upload the two new files to the exact keys `add_logos()` would have produced, matching that content type and access:

```bash
aws s3 cp --profile lsp --content-type image/webp <scratch>/gppa-apa.webp s3://lsp-website-media-uswest2/ce-organizations/greater-pittsburgh-psychological-association-2.webp
```

```bash
aws s3 cp --profile lsp --content-type image/webp <scratch>/gppa-mark.webp s3://lsp-website-media-uswest2/ce-organizations/greater-pittsburgh-psychological-association-3.webp
```

Verify both are publicly readable with an unauthenticated `curl -I` against their `https://lsp-website-media-uswest2.s3.us-west-2.amazonaws.com/…` URLs. Expected: `200` and `content-type: image/webp`.

- [ ] **Step 3: Create the rows and populate the fields on prod**

Run this through SSM. Prod notes: wrap in `sudo -iu ec2-user bash -c '…'`, the running service is `web_blue` (confirm with `docker compose ps`), pipe a base64'd script into `manage.py shell`, and pass the whole thing via `--cli-input-json file://…` because `aws ssm send-command --parameters` chokes on shell metacharacters.

```python
from events.models import CEOrganization, CEOrganizationLogo

org = CEOrganization.objects.get(name__iexact="Greater Pittsburgh Psychological Association")
print("before:", [(l.pk, l.sort_order, l.image.name) for l in org.logos.all()])

for order, key in [
    (2, "ce-organizations/greater-pittsburgh-psychological-association-2.webp"),
    (3, "ce-organizations/greater-pittsburgh-psychological-association-3.webp"),
]:
    CEOrganizationLogo.objects.get_or_create(
        organization=org, sort_order=order, defaults={"image": key},
    )

org.logos.filter(sort_order=1).delete()

org.url = "https://gppa.wildapricot.org/"
org.statement = (
    "Greater Pittsburgh Psychological Association is approved by the American "
    "Psychological Association to sponsor continuing education for psychologists. "
    "Greater Pittsburgh Psychological Association maintains responsibility for "
    "this program and its content"
)
org.save()

org.refresh_from_db()
print("after:", [(l.pk, l.sort_order, l.image.name, l.image.width, l.image.height) for l in org.logos.all()])
print("url:", org.url)
print("statement:", org.statement)
```

Expected output: two rows at orders 2 and 3, sized 459×431 and 605×548, the url set, and the statement ending in `…this program and its content` with **no** trailing period.

- [ ] **Step 4: Verify the rendered panel on both claiming events**

Both `topology-direction-of-treatment-2026-27` and `sounding-out-the-signifier-2026-27` are seminars, so their event pages 302 to the member-gated Workspace. Sign in and open each Workspace Overview in Chrome. Confirm on both: the organization's name renders and links to `gppa.wildapricot.org`; two separate marks appear, each opening its own modal at full size; the approval paragraph renders as **real, selectable text** beneath them; and the old composite — with its baked-in paragraph — is gone.

- [ ] **Step 5: Record the outcome**

Update the task #506 briefing with what shipped, and add the CLAUDE.md status entry for the feature following the house style of the surrounding entries.

---

## Self-Review

**Spec coverage:** data fix → Task 6; per-org grouping → Task 2; name + link move → Task 2; 64×192 chips → Task 2; shared dialog + real anchors + white plate → Task 3; `MAX_BOX` → Task 1; CSS comment widening → Task 3; out-of-scope items (edit surfaces, `REVIEWABLE_FIELDS`, no JPEG twin, no per-logo caption) are untouched by every task. Tests named in the spec map to Tasks 1–3.

**Placeholder scan:** no TBDs; every code step carries the actual content. Task 4 and Task 6 step 1 describe verification and a scratch script rather than committed code, which is appropriate — both state their expected results and their failure condition.

**Type consistency:** `MAX_BOX` is `(1200, 600)` in Task 1 and referenced as such in Tasks 4 and 6. The attribute names `data-ce-logo`, `data-ce-caption`, `data-ce-logo-image`, `data-ce-logo-caption`, and `id="ce-logo-modal"` are identical across Task 3's markup, its script, and its tests. `add_logos()` returns the created rows, which Task 3's `first, second = org.add_logos([...])` relies on — confirmed against `events/models.py:232-249`.
