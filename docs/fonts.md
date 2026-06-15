# Web fonts (self-hosted / bundled)

The site **bundles** its web fonts (`static/fonts/*.woff2`) instead of loading
them from the Google Fonts CDN. This was task #270: the CDN version flashed a
fallback font and reflowed on every page load (FOUT) because the browser had to
open a second cross-origin connection to `fonts.gstatic.com` before any text
could render. Same-origin files served by Django/WhiteNoise, preloaded for the
above-the-fold faces, are ready before first paint — no swap, no reflow.

## What's bundled

Only the **latin** and **latin-ext** subsets are kept (latin-ext covers accented
member names — María, Líza, Patsalides). Other scripts (Greek, Cyrillic,
Vietnamese) fall back to the system font for those glyphs.

| Family | Used by | Weights / styles |
|---|---|---|
| Inter | both themes (body sans) | 400, 500, 600, 700 |
| Cutive | modern theme (serif headings) | 400 |
| Cutive Mono | both themes (mono) | 400 |
| Playfair Display | Classic (`wix`) theme (serif) | 400/500/600/700 + italic 400/500/600 |
| Cinzel | Classic (`wix`) theme (display/all-caps) | 400, 600 |

## How it's wired

- `@font-face` declarations live in `assets/css/input.css` (just after the
  `@theme` block) and compile into `static/css/site.css` via the Tailwind build.
  `src: url('../fonts/<name>.woff2')` is relative to the built `site.css`, so it
  resolves to `static/fonts/`. WhiteNoise's `CompressedManifestStaticFilesStorage`
  rewrites those URLs to hashed filenames at `collectstatic` time.
- `core/templates/core/base.html` preloads the latin woff2 files that paint above
  the fold (Inter 400/600 always; Cutive 400 in modern, Playfair 400 + Cinzel 400
  in `wix`). `crossorigin` on the preload is required even same-origin — fonts are
  always fetched in CORS-anonymous mode, and without it the preload wouldn't match
  the real request.
- The font filenames encode family-weight-style-subset, e.g. `inter-600.woff2`
  (latin), `inter-600-ext.woff2` (latin-ext), `playfair-400i.woff2` (italic).

## Refreshing / adding a font

Re-download from Google Fonts and regenerate the `@font-face` blocks:

```python
# 1. Fetch the Google CSS with a modern UA so it serves woff2:
#    curl -A "Mozilla/5.0 ... Chrome/120" "https://fonts.googleapis.com/css2?family=..." -o /tmp/g.css
# 2. Then, for the latin + latin-ext blocks, download each woff2 to static/fonts/
#    and rewrite src to url('../fonts/<name>.woff2'). See the parsing script used
#    in task #270 (regex over the /* subset */ + @font-face comment pairs).
```

After changing fonts: rebuild CSS (`npm run build:css`) and update the preload
list in `base.html` if the above-the-fold faces changed.
