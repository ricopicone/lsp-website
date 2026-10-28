# Uploading a talk's recording (task #851)

## Why

Sheila Cavanagh wants the Scholarly Seminar Series' talks recorded, with the
presenter's consent, so members who can't come at the chosen time can watch
later. The site records only in its own room (Daily writes the file and a
webhook creates the `video.Recording`). A talk held on Zoom, as Marshall
Meyer's November 7 talk is, has no way to put its recording on the site.

## What it does

The coordinator's admin (`/admin-tools/scholarly-seminar-series/`) gets an
**Upload a recording** link on every talk whose date has come. The upload page
takes one video file (MP4, WebM or MOV, up to 4 GB), the date it was recorded
(the talk's date by default), who can watch it (LSP Members by default, as a
recording made in the site's room of a talk set to record), and a required
confirmation that the presenter agreed to its being shared on the site. Saving
lists the recording on the talk's page and the series page, and opens the
recording's own page, where its availability, notes, keeping and deletion work
as they do for any recording.

## Decisions

- **An upload is an ordinary `Recording`**, with a new `source` field
  (`daily` / `upload`). Everything that lists or plays recordings — the event
  page, the series page's Recording badge, the coordinator admin, the recording
  page with its availability form — reads that model, so none of it changes.
  A second model for uploaded video was the alternative; it would need every
  one of those surfaces taught about it.
- **`daily_recording_id` becomes nullable.** It is still unique for Daily's
  recordings. Every place that calls Daily about a recording (delete, access
  link, the retention purge, the Django admin's delete action) now asks the
  source first. Deleting is consolidated into `Recording.delete_files()`, which
  those three places share, so an upload is never sent to Daily and a Daily
  recording's file is never looked for in the wrong bucket.
- **Uploads live in the private bucket**, under
  `recordings/uploads/<event pk>/<random>.<ext>`, and play by a presigned GET
  from it. That is the bucket browsers already upload to for Works video, so its
  CORS and the instance role's permissions are known to work. Daily keeps
  writing to the recordings bucket.
- **The browser uploads straight to S3** by presigned POST (the Works pattern),
  so a large file never passes through the app server, and S3 enforces the size
  cap. Without JavaScript, or in development with no bucket, the file posts to
  the app server instead.
- **Consent is a condition of the upload**, not a field beside it, as the
  feature image's rights confirmation is. Who uploaded is `started_by`, and
  when is `created_at`.
- **Kept**: `keep=True`, the rule for every one-off event's recording, so the
  retention sweep never deletes it.
- **No notification**, as for a recording made in a one-off event's room today.
- **Gated to the coordinator role** (superusers pass), on series talks only.
  The upload code is not series-specific, so another role's admin could offer
  it later with one more entry point.

## Not doing

- Transcoding, trimming, thumbnails, or reading the duration from the file.
- Fetching recordings from Zoom's API.
- Uploads for seminars, reading groups or other event types.

## Known limitation

An upload started and never saved leaves its file in the bucket. There is no
lifecycle rule on this prefix; with one coordinator uploading a few talks a
year it is a handful of objects at most.
