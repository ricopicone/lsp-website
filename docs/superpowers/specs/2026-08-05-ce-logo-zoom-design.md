# Naming and enlarging the CE accreditors (task #506)

An event's continuing-education panel showed accreditor logos as anonymous
thumbnails: no organization name, and a chip bounded to 48×144 CSS pixels.
The task asks for two things — make the marks bigger, ideally zoomable, and put
the organization's name in the listing.

Looking at the one accreditor on prod turned a display task into a display **and
data** task, which is where most of the value is.

## What prod actually holds

`CEOrganization` #2, *Greater Pittsburgh Psychological Association*, carries a
single `CEOrganizationLogo` — `greater-pittsburgh-psychological-association-1.webp`,
645×360. That one file is a composite of three things:

1. the APA **Approved Sponsor** seal,
2. the **GPPA** wordmark,
3. and, boxed beneath the seal, the APA-mandated approval paragraph
   **rasterized as tiny text**.

Its `statement` and `url` fields are both empty. Two published events claim it:
`topology-direction-of-treatment-2026-27` and `sounding-out-the-signifier-2026-27`.

So the composite is why the panel reads as too small. The seal and the wordmark
survive being scaled to ~86×48; the paragraph does not, and no zoom fixes it
well — the stored file is 645px wide, and `ce_images.MAX_BOX` retains no
original to go back to.

The original three files from the accreditor's email were recovered
(`image1.png` 189×105, `image2.png` 459×431, `image4.jpg` 605×548) and are
exactly the three panels of the composite. **Two of them are logos; the third is
the statement.** Adding all three as logo rows would preserve the defect: at
189px `image1` is unreadable at any chip size, its dark text sits on a partly
transparent background so it half-disappears on the dark theme, and it cannot be
selected, searched, read aloud, or reflowed on a phone. That file *is* the
`statement` field, which already renders as real text under the logos and has
been empty this whole time. The requirement APA imposes has been met only in
pixels.

## Decisions

### The data is fixed, not just the display

The composite row is replaced by two rows — the APA seal and the GPPA mark — and
the paragraph moves into `CEOrganization.statement` verbatim from the source
image, **without a trailing period** (Rico, 2026-08-05; the accreditor's own file
omits it and matching it exactly is the safer choice for mandated language):

> Greater Pittsburgh Psychological Association is approved by the American
> Psychological Association to sponsor continuing education for psychologists.
> Greater Pittsburgh Psychological Association maintains responsibility for this
> program and its content

`url` is set to `https://gppa.wildapricot.org/`.

This is what makes "individually zoomable" mean anything: with one composite
there is one thing to zoom, and the interesting half of it is text that should
never have been an image.

### The panel groups by organization

Today's template flattens every organization's logos into one row and then lists
every statement after it. With one accreditor that reads fine; with two it is
ambiguous which statement belongs to which body, and adding the name to a flat
row would repeat that name once per logo (GPPA would say it twice, side by side).

Each organization becomes its own group: **name, then its logo row, then its
statement.** The name is the external link when `org.url` is set.

That link move is load-bearing, not cosmetic. The logo is currently wrapped in an
anchor to `org.url`, so a click-to-zoom would collide with it. Showing the name
gives the outbound link a better home and frees the image to be the zoom target.

### Chips grow to 64×192

From `max-h-12 max-w-36` to `max-h-16 max-w-48` — a square seal goes 48→64px, a
wide wordmark gains 48px of width. Enough to answer "a bit too small" without
the chips reading as a design element of the page rather than a footnote to the
CE line. The zoom carries the fine detail.

### The zoom follows the task #504 lightbox

One shared `<dialog class="modal lsp-lightbox">` for the whole panel. The include
renders at most once per page — `_event_summary.html:80` and `:84` are an
`{% if %}`/`{% elif %}` — so a single dialog is safe, and JavaScript swaps its
`src` and caption from whichever anchor was clicked. This scales to N logos
across M organizations without N copies of the dialog markup.

Each logo is a **real anchor to its own file**, exactly as `_feature_image.html`
does it: with no JavaScript the click opens the image directly, and the control
is focusable and keyboard-operable because of what it is rather than through
added `role` and `tabindex`. Escape and click-outside come free from `<dialog>`
plus the `modal-backdrop` form.

**The modal image sits on a white plate**, not bare on the scrim the way the
feature-image lightbox does. Accreditor marks are dark-on-transparent — verified:
the APA seal's background is fully transparent — and the `.lsp-lightbox[open]`
scrim is 88% black. This is the same reasoning that already makes the chips
`bg-white` in both themes. The caption is the organization's name, using the
existing `.lsp-lightbox-caption` class.

### `MAX_BOX` rises to 1200×600

`ce_images.MAX_BOX` is 800×**400**, which the incoming files show to be actively
wrong for a squarish mark: it would downsample the seal 459×431 → 426×400 and the
GPPA mark 605×548 → 441×400, throwing away resolution the zoom then wants back.
At 1200×600 both store at native size.

No original is retained for a logo and nothing reprocesses existing rows, so this
only ever helps future uploads — but GPPA's are being re-uploaded now, which
makes this the free moment. The docstring comment claiming logos are "rendered at
max 144x48 CSS pixels" becomes 192×64.

## Deliberately out of scope

- **The edit surfaces keep their small chips.** `event_edit.html`'s picker
  (`max-h-8`) and `ce_organization_edit.html`'s list (`max-h-12`) are pickers,
  not the listing being read. Growing them serves nobody's stated problem.
- **CE stays out of `events/review.py::REVIEWABLE_FIELDS`.** An accreditation is
  an outside body's factual decision, not program content the PC vetted.
- **No JPEG twin, no responsive `srcset`.** A logo bounded to 1200×600 is a
  small WebP; the complexity would buy nothing.
- **No per-logo caption or alt-text field.** The organization name is the caption
  for every mark it owns.

## Components

| Unit | Change |
|---|---|
| `events/templates/events/_ce_credits.html` | Per-org grouping; name (linked when `url` is set); chips at `max-h-16 max-w-48` wrapped in per-logo anchors; one shared lightbox dialog + its script. |
| `assets/css/input.css` | Reuses `.lsp-lightbox` / `.lsp-lightbox-caption` unchanged; only its "Feature-image lightbox (task #504)" comment widens, since the rules now serve two callers. The white plate is a Tailwind utility in the template, so no new CSS. |
| `events/ce_images.py` | `MAX_BOX` → `(1200, 600)`; stale render-size comment corrected. |
| prod data | GPPA: composite row replaced by two logo rows; `statement` and `url` populated. Run through `CEOrganization.add_logos()` + `normalize_logo()` so the stored files are identical in kind to any faculty upload. |

## Testing

`events/test_ce_display.py` gains:

- the organization's name renders in the panel;
- grouping is per-organization — with two accreditors, each statement renders
  inside its own group, so a second body's language cannot read as attaching to
  the first body's marks;
- every logo is an anchor whose `href` is that logo's own file (the no-JS path,
  and the thing that makes each mark individually zoomable);
- an organization with no `url` renders its name as plain text rather than an
  empty link.

`events/test_ce_images.py` pins the new `MAX_BOX` bound and that a 459×431 upload
is stored without downsampling.

The prod data change is a one-time operation, not code, and is verified by
reading the rendered panel on both claiming events after it runs.
