"""Download headshot images and attach them to user Profiles.

Reads a TSV with columns: ``email``, ``name``, ``source``, ``source_url_or_file``,
``suggested_s3_key``. Looks each ``email`` up in the User table (case-insensitive)
and writes the source bytes into ``Profile.headshot`` using Django's storage
backend — which routes to S3 in production and the local filesystem in dev.

Skips rows whose email doesn't match a User.
Skips rows whose Profile already has a headshot unless ``--overwrite``.
"""

from __future__ import annotations

import mimetypes
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

_USER_AGENT = "Mozilla/5.0 (LSP-website-importer)"


def _fetch_bytes(source_url_or_file: str) -> tuple[bytes, str]:
    """Return (raw_bytes, suggested_extension) for either an http(s) URL or a
    local file path. Extension is best-effort, defaults to .jpg."""
    if source_url_or_file.startswith(("http://", "https://")):
        req = Request(source_url_or_file, headers={"User-Agent": _USER_AGENT})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ".jpg"
        # mimetypes returns ".jpe" for image/jpeg on some systems — normalize.
        if ext == ".jpe":
            ext = ".jpg"
        return data, ext
    p = Path(source_url_or_file)
    if not p.exists():
        raise FileNotFoundError(p)
    return p.read_bytes(), p.suffix.lower() or ".jpg"


class Command(BaseCommand):
    help = "Attach headshots from a TSV mapping (email → source URL or file)."

    def add_arguments(self, parser):
        parser.add_argument("tsv_path", type=Path, help="Path to headshot-mapping.tsv")
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace existing Profile.headshot images.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without downloading or writing.",
        )

    def handle(self, *args, tsv_path: Path, overwrite: bool, dry_run: bool, **opts):
        if not tsv_path.exists():
            raise CommandError(f"File not found: {tsv_path}")
        import csv

        attached = skipped_existing = skipped_missing_user = errors = 0
        with tsv_path.open(newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                email = (row.get("email") or "").strip()
                src = (row.get("source_url_or_file") or "").strip()
                if not email or not src:
                    continue
                user = User.objects.filter(email__iexact=email).select_related("profile").first()
                if user is None:
                    skipped_missing_user += 1
                    self.stdout.write(self.style.WARNING(f"  no user for {email}"))
                    continue
                profile = user.profile
                if profile.headshot and not overwrite:
                    skipped_existing += 1
                    continue
                if dry_run:
                    self.stdout.write(f"  would attach {email}  ← {src}")
                    attached += 1
                    continue
                try:
                    data, ext = _fetch_bytes(src)
                except Exception as exc:
                    errors += 1
                    self.stderr.write(f"  {email}: {exc}")
                    continue
                # Save under a deterministic filename keyed to email so reruns
                # don't accumulate random suffixes.
                safe = email.lower().replace("@", "_at_").replace("/", "_")
                filename = f"{safe}{ext}"
                profile.headshot.save(filename, ContentFile(data), save=True)
                attached += 1
                self.stdout.write(f"  attached {email}  ({len(data):,} bytes)")

        prefix = "Would " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}attach {attached}, skip {skipped_existing} (already had), "
                f"skip {skipped_missing_user} (no user), error {errors}."
            )
        )
