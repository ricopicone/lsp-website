# Feature image on an event (task #504)

**Status:** design approved 2026-08-04.

## The problem

An event page is all type. The 2026-27 program carries seminars, reading groups,
and special events whose faculty routinely have a painting, a book cover, or a
photograph in mind for the offering, and no way to put it there. The ask is an
option under the event edit page.

The hard part is not storing a file. It is that faculty will upload every shape
and size there is — a phone photo in portrait, a 4000 px scan of a canvas, a
square poster, a 3:1 banner — and one page layout has to hold all of them
without looking broken and without the page's shape swinging between one event
and the next.

## What was decided

**Three surfaces, not five.** The image appears on the event detail page, in the
seminar or reading group's Workspace masthead, and as the OpenGraph preview when
someone shares the link. It does *not* appear on the program page or the
events-list cards: a card thumbnail is a second, much squarer crop shape, and
solving it is a separate piece of work with its own visual question.

**Normalize at upload, within a range.** The image is cropped when it is
uploaded, not when it is displayed, so every render site sees a shape it can
trust. The crop is free rather than locked to a single ratio, clamped to
`1:1 ≤ ratio ≤ 2.5:1`. A single fixed ratio was the first proposal and was
rejected: it butchers a square poster, and the school's faculty reach for
artwork often enough that a forced 1.91:1 would be felt.

This follows `accounts/images.py`, whose docstring states the principle for the
headshot pipeline — normalize on the way in so the existing markup "just works"
everywhere — and departs from it only in allowing a range instead of a square.

**Constant height, varying width.** The band is bounded in *both* dimensions:
never taller than ~340 px on desktop, never wider than the content column. A
2.5:1 image therefore runs the column's full width; a square sits as a narrow
plate with white space beside it. Every event page keeps the same vertical
rhythm, nothing is re-cropped at display time, and on a phone — where the width
bound binds first — everything simply gets shorter. The rejected alternative,
constant width with height following the ratio, pushes the title of a
square-image event far below the fold.

**Rights are a condition of the upload.** A structured source (public domain /
licensed / own work / permission granted) plus a confirmation checkbox, both
required, both stamped with who confirmed and when. The school has been careful
about artwork copyright before — `core/page_artwork.py` carries artist and title
for every section hero — and an image on a public page is the one place a
takedown can arrive.

## Data

A `OneToOne` model, `events.EventFeatureImage`, rather than nine more fields on
the 1,722-line `Event`. Absence of the row *is* "no image"; removal is a row
delete; the whole feature reads in one file.

| Field | Purpose |
|---|---|
| `event` | `OneToOneField(Event, related_name="feature_image")` |
| `image` | the rendered WebP — what every surface shows |
| `image_width` / `image_height` | `width_field`/`height_field` targets |
| `original` | the bounded upload, kept so it can be re-cropped later |
| `crop` | JSON Cropper.js rect, so the modal reopens where they left it |
| `credit` | e.g. "René Magritte, *The Treachery of Images*" |
| `alt` | blank falls back to the event title |
| `source` | `public_domain` / `licensed` / `own_work` / `permission` |
| `source_url` | required when `source == licensed` |
| `rights_confirmed_by` / `rights_confirmed_at` | who ticked the box, and when |

The dimensions are denormalized deliberately. Media lives in S3 in production,
so reading `image.width` at render time is a network round trip per page view;
storing them also lets the `<img>` carry `width`/`height` and reserve its space
before the file arrives.

## Pipeline

New `events/feature_images.py`, a sibling of `ce_images.py` and
`accounts/images.py`. Neither existing module fits: one force-crops to a centred
square, the other never crops at all.

- Reject over **12 MB** before decoding. Downscale any source past **6000 px**
  before cropping.
- Enforce **`1.0 ≤ ratio ≤ 2.5` server-side**, not only in the cropper — a
  hand-rolled POST gets the same answer.
- Render to fit a **1600 × 900** box at the cropped ratio: a 2.5:1 lands
  1600×640, a square lands 900×900. WebP quality 82, `method=6`.
- Flatten transparency onto white, as the headshot pipeline does, so a
  transparent PNG reads identically in the light and dark themes.
- Re-encode the retained original bounded to **2400 px, WebP quality 88**. This
  is the compression answer at the second level: a 20 MB phone photo does not
  sit in S3 forever merely because re-cropping must stay possible.
- Reject anything whose rendered width would fall below **800 px**. A small
  image stretched across the band looks worse than no image at all.

## Editing

**Its own form, its own endpoint** — `events:feature_image`, POSTing to a view
gated by the unchanged `can_edit_event`. This is not a style preference.
`event_edit_confirm.html:39` re-posts the edit form's values as hidden
`<textarea>`s, and a file input cannot survive that round trip, so folding the
image into `EventEditForm` would silently drop uploads on exactly those events
that route through the change-review dialog. A second multipart form already
lives on this page for CE organizations (`event_edit.html:179`), so the pattern
is established. Keeping the image out of `EventEditForm` also makes its
exclusion from review structural rather than a rule someone must remember.

The fieldset shows the current image with **Replace** and **Remove**, the file
input, the credit and alt fields, the source select (its URL field revealed for
"licensed"), and the rights checkbox.

**The cropper** is the already-vendored `static/vendor/cropper-1.6.2.*`. Free
crop with the ratio range enforced by the drag handles, plus **Use the whole
image**, pre-selected whenever the upload already sits in range — which most
landscape photographs do, so most faculty never open the modal. Without
JavaScript the upload still works: the server applies the same validation, and
an out-of-range image returns a form error asking them to crop it first.

**Not reviewable.** The image is absent from `REVIEWABLE_FIELDS` and applies
immediately, as `schedule_note` does. The change-review loop (task #295) exists
to protect a description the Program Committee approved; there is no prior image
to diverge from, and `change_ratio` compares strings.

## Rendering

One partial, `events/_feature_image.html`, used by both page surfaces:

```html
<img class="max-h-[260px] sm:max-h-[340px] w-auto max-w-full rounded-xl
            ring-1 ring-base-300/60" width="…" height="…" alt="…">
```

The phone bound is the looser of the two, which reads backwards until you
notice that at phone widths anything wide is already bound by the column: the
height cap governs only the squarer end. Built at 200 px first, and a square
poster sat stranded beside empty space; 260 was measured, not guessed.

Bounding both dimensions rather than fixing the height is what makes the
constant-height rule hold without distortion: the image is never taller than the
band and never wider than the column, and it is never asked to be both at once.
`width` and `height` come from the denormalized columns, so nothing shifts on
load. Left-aligned to the text column, credit beneath in small muted type, `alt`
falling back to the event title so the markup is never bare.

Placement is between the breadcrumb and the `<h1>` on the event page, and above
the title in the Workspace masthead with a shorter 180 px cap, found through the
existing `Workgroup.primary_event()`.

## Social preview

`event_detail.html` gains an `extra_head` block emitting `og:title`,
`og:description` (tag-stripped, truncated), `og:url`, `og:image` with
`:width` / `:height` / `:alt`, and `twitter:card=summary_large_image` —
degrading to the text-only tags and `summary` for an event with no image.
Absolute URLs follow the established `settings.SITE_BASE_URL.rstrip("/") + …`
idiom; in production `image.url` is already an absolute S3 URL.

The site emits no OpenGraph markup at all today, so this is new machinery. It is
scoped to this one template rather than pushed into `base.html`: giving every
page on the site social metadata is a different task with different questions.

The WebP is served directly, with no JPEG twin. Every current major scraper
renders WebP, and a second stored file per event is a real cost against a
hypothetical one.

## Out of scope

- Program page and events-list card thumbnails.
- Any change to who may edit an event.
- Deleting the S3 object when an image is removed. The row goes; the file stays,
  as it does everywhere else on this site.
- Backfill. There are no existing images, and no event needs one.

## Tests

`events/test_feature_image.py`:

- Ratio clamping in both directions; the 800 px rendered-width floor; oversize
  and unreadable uploads; that the stored render is bounded WebP and the stored
  original is bounded too.
- The rights checkbox is required; `source_url` is required only for
  "licensed"; the confirmation stamp records the acting user.
- Upload, replace, and remove through the view; a user failing `can_edit_event`
  is refused.
- `alt` falls back to the event title; the credit renders when set.
- OpenGraph tags present with an image and absent without one.

The render tests need two kinds of event, which is not obvious until the first
one fails: a seminar's event page **redirects to its Workspace**, so the event
page must be exercised through a standalone special event and the masthead
through a seminar.
