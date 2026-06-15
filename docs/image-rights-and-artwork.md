# Page artwork — inventory and image-rights note

The new site carries the old site's habit of setting each section's title over a
piece of artwork (task #259). This file is both the **swap reference** for those
images and a **note for the Board** about the rights question they raise.

## Note for the Board (decision needed)

**Two themes to choose from.** I've built the new site so it can present in two
looks, and the Board can pick:

- **Modern** (my recommendation) — a clean, content-first design. We can keep
  refining it together.
- **Classic** — clones the old site's design elements: artwork images behind
  large page titles, the old serif type, the old palette.

You can flip between them on the live site with the **"Style: Modern · Classic"**
switch in the footer, so it's easy to compare the same pages side by side.

**Why I'm advocating Modern.** Web design has moved away from the heavy "hero"
image banner—the big picture with a title sitting on top of it. The trend is to
put **content up front** rather than bury it below a tall decorative header, so a
visitor who came for information gets it immediately. The Classic style's large
hero titles, while striking, now read as **dated** for exactly that reason. (It's
also worth saying the modern look is not finished—it's a starting point we can
shape to taste.)

**On the images themselves.** The actual **artworks** (the Twombly, the Klee,
etc.) are the most beautiful option—and also the **riskiest** (see rights, below).
The substitute images we used where no artwork existed—library interiors and the
like—are lower-risk but have a bit of a **stock-photo feel**, which doesn't do
the school any favors. So the most attractive version of Classic is also the one
that carries the most legal exposure.

### The image-rights question

The old website set page titles over artworks—a Cy Twombly on the front page, a Paul Klee on the About page, and others elsewhere. We have carried that look onto the new site (in the Classic theme). Most of these images are works by 20th-century artists (Twombly, Klee, Kandinsky, Agnes Martin, Louise Nevelson, and others), several of which are **still under copyright**, and we do not hold licenses for them. A few are photographs of library interiors, which are lower-risk but not necessarily free of claims either.

**This is an institutional-risk decision for the Board, not a settled legal matter.** To be clear: the Web Coordinator is not a copyright lawyer, and this is not legal advice. There may be a **fair-use argument**—we are a non-profit school, the use is non-commercial, and the works appear small and as part of a larger editorial whole—but decorative banner use is one of the *weaker* fair-use postures (it is not commentary on or analysis of the artwork itself), so the argument is genuinely uncertain. A rights-holder could ask us to take an image down, and in the worst case seek damages.

**The Board needs to decide whether the visual benefit is worth that risk.** Options, roughly in order of decreasing risk:

1. **Use the artworks as-is** (current state), accepting the risk, and respond to any takedown request promptly.
2. **Keep only the lower-risk images** (library/architecture photographs, plus any works confirmed to be in the public domain) and drop the rest.
3. **License** specific images (e.g. via the artists' estates or Artists Rights Society) for the few the Board cares most about.
4. **Commission or source openly-licensed art** in the same spirit.

Whatever the choice, we should publish a short **image-credits** line/page that names the artists we can identify and offers a good-faith takedown contact. The machinery makes any of these reversible in one small code change—see below.

## How it's wired (for whoever maintains it)

- Heroes appear on **section-landing pages only** (not detail, list, form, or
  admin pages).
- The image→page mapping lives in **`core/page_artwork.py`** (`PAGE_ARTWORK`,
  keyed by the page's view name). The hero partial is
  `core/templates/core/_page_hero.html`; it renders the title over the image
  with a dark scrim for legibility and shows the `artist`/`title` credit in the
  corner when present.
- To **change** a banner: drop a file in `static/img/artwork/` and edit its
  entry. To **remove** one: delete the entry—the page falls back to a clean,
  image-less title header automatically. To remove **all** of them: empty the
  dict.
- Images are downsized JPEGs (~1600px). Originals came from the live old site
  and the school's `wix-files` archive.

## Current inventory

Attribution is only as good as what the old site recorded; many entries have no
known artist. "Source" notes whether the banner is the one the old site showed
for the equivalent page, or a reused image for a page that is new to this site.

| Page (view) | File | Attribution (as known) | Source |
|---|---|---|---|
| Front page (`core:landing`) | `front.jpg` | Cy Twombly, *Untitled* | old home page |
| About (`about`) | `about.jpg` | Paul Klee, *White Framed Polyphonically* | old About page |
| The School (`the_school`) | `the-school.jpg` | Wassily Kandinsky | reused |
| Program (`program`) | `program.jpg` | unknown | old seminars page |
| Events (`events:list`) | `events.jpg` | unknown | old Other Offerings page |
| Directory (`directory`) | `directory.jpg` | unknown | old Find-an-Analyst page |
| Works (`works:index`) | `works.jpg` | Louise Nevelson, *Cascade VII* | reused |
| Documents (`documents:index`) | `documents.jpg` | unknown | old Archive banner |
| Calendar (`core:calendar`) | `calendar.jpg` | George Peabody Library (photo) | reused |
| Groups (`workgroups:list`) | `groups.jpg` | Bibliothèque Mazarine, Paris (photo) | reused |
| Guides (`guides_index`) | `guides.jpg` | Beinecke Library, Yale (photo) | reused |
| Parlêtre (`parletre:index`) | `parletre.jpg` | Bibliothèque Sainte-Geneviève, Paris (photo) | reused |

In the Classic theme the front page shows the old home-page Twombly over the
school name; in Modern it keeps its bespoke text hero. The Twombly is only
available at ~600px from the old site, so it is a little soft under the scrim.
