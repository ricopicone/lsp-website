# Opening an event's feature image at full size (task #504, follow-on)

**Status:** design approved 2026-08-05. Follows
`2026-08-04-event-feature-image-design.md`, which shipped and deployed
2026-08-05.

## The problem

The feature image renders in a band at most 340 px tall. That is the right size
for a page whose subject is the event, not the picture, but it leaves no way to
actually look at the image. Clicking it should open it, centred, at full size.

Doing so exposes a resolution question the band was hiding. The stored render is
bounded to 1600 × 900, which is ample for a 340 px band even at 2× density and
visibly soft filling a modal on a retina display.

## What was decided

**A second, larger render.** `FULL_BOX = (2400, 1350)` alongside the existing
`RENDER_BOX = (1600, 900)`, from the same crop. The event page keeps serving the
smaller file above the fold, where some members will meet it on a phone
connection; the modal serves the larger one.

Rejected: raising the single render to 2400, which makes every event page
download roughly twice the bytes to fill a 340 px band; and serving the 1600 as
it stands, which undercuts the point of the feature on exactly the displays most
likely to be used.

**The timing is the argument.** The feature deployed minutes before this was
asked and no event carries an image yet, so a second render costs no backfill.
That stops being true the moment faculty start uploading.

**Not the stored original.** It is bounded to 2400 px and would seem the obvious
candidate, but it is *uncropped* — serving it would show the parts faculty
deliberately framed out, and the modal would disagree with the page.

## Data

| Field | Purpose |
|---|---|
| `image_full` | the 2400 × 1350 render, blank when it would duplicate `image` |
| `image_full_width` / `image_full_height` | `width_field`/`height_field` targets |

`thumbnail()` never upscales, so an upload between the 800 px floor and 1600 px
would produce two byte-identical files. The full render is therefore stored only
when it is genuinely larger, and a `modal_image` property returns
`image_full or image` so no template has to know. That fallback also covers the
demo rows already in the local development database.

Both dimension columns must be assigned by hand after `image_full.save(…)`, for
the reason recorded in the previous spec: Django refreshes an ImageField's
dimension fields only when *replacing* an existing file.

## Behaviour

The partial wraps the `<img>` in a real anchor:

```html
<a href="{{ img.modal_image.url }}" class="cursor-zoom-in" …>
```

Without JavaScript that link opens the full image directly. It is focusable and
keyboard-operable because it is an anchor, so the accessible behaviour falls out
of the markup rather than being reconstructed with `role` and `tabindex`.

JavaScript intercepts the click and opens a `<dialog class="modal">` instead,
which is the house pattern (`payments/templates/payments/*/_note_modal.html` and
its neighbours). `<form method="dialog" class="modal-backdrop">` gives
click-outside dismissal, and Escape works for free.

The dialog centres the image at `max-w-[95vw] max-h-[85vh] w-auto h-auto` on a
transparent box, with no chrome competing with the picture, and repeats the
credit beneath it. One partial serves both the event page and the Workspace
masthead, so the masthead gains the behaviour without a second implementation.

Two things the scrim needs, both found by looking at the built page rather than
by reading the markup:

- DaisyUI dims from **`.modal[open]`**, specificity 0,2,0. A plain
  `.lsp-lightbox` class silently loses to it and you get DaisyUI's 40% black,
  which over the dark theme barely separates the picture from the page. The
  override has to carry `[open]` too.
- The caption must be a **fixed light colour**, not `text-base-content`. In the
  light theme that token is near-black, and it would be printed on a near-black
  scrim.

Both rules are plain CSS in `assets/css/input.css`, beside the `.hp-wrap`
precedent.

## Out of scope

- Pan and zoom inside the modal. The image is bounded at 2400 px; fitting the
  viewport is the whole of "full size" here.
- Any gallery or next/previous affordance. An event has one image.
- Backfill, since no image exists to backfill.

## Tests

Appended to `events/test_feature_image.py`:

- The rendered anchor points at the full render, not the page render.
- The dialog markup renders on the event page, and an event without an image
  renders neither anchor nor dialog.
- `render(…, box=FULL_BOX)` is bounded to 2400 × 1350 and keeps the crop's
  ratio.
- A source too small to exceed the page render stores no `image_full`, and
  `modal_image` falls back to `image`.
