"""Import the referral list from a Google Groups members-export CSV.

One-time (but re-runnable/idempotent) migration of the
``lsp-members-accepting-analysands`` Google Group into the in-site referral
list. Expects the export format from ``admin.google.com → Groups → Members
→ Export``: columns ``Group Email``, ``Member Email``, ``Member Name``,
``Member Role``, ``Member Type``.

Only ``MEMBER``-role ``USER`` rows are imported (the group's OWNER/MANAGER
rows are the admin and referrals service accounts, not clinicians). Each
email is matched to a site account by login email, then by the profile's
public email. **No email is sent** — these clinicians are already on the
coordinator's list; the New Member Instructions remain a per-row button on
the clinicians page.
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from accounts.models import User
from referrals.models import ReferralListMember


class Command(BaseCommand):
    help = (
        "Import referral-list clinicians from a Google Groups members "
        "export CSV. Idempotent; sends no email."
    )

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the Google Groups export CSV.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report matches without writing anything.",
        )

    def handle(self, *args, **opts):
        path = Path(opts["csv_path"])
        if not path.exists():
            raise CommandError(f"No such file: {path}")
        dry = opts["dry_run"]

        with path.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))

        added = reactivated = already = 0
        skipped_roles: list[str] = []
        unmatched: list[str] = []
        matched_names: list[str] = []

        with transaction.atomic():
            for row in rows:
                email = (row.get("Member Email") or "").strip()
                if not email:
                    continue
                if (row.get("Member Type") or "").strip().upper() != "USER":
                    skipped_roles.append(email)
                    continue
                if (row.get("Member Role") or "").strip().upper() != "MEMBER":
                    skipped_roles.append(email)
                    continue

                user = (
                    User.objects.filter(is_active=True)
                    .filter(
                        Q(email__iexact=email)
                        | Q(profile__public_email__iexact=email)
                    )
                    .select_related("profile")
                    .first()
                )
                if user is None:
                    unmatched.append(email)
                    continue
                matched_names.append(
                    f"{user.get_full_name() or user.email} <{email}>"
                )

                if dry:
                    member = ReferralListMember.objects.filter(user=user).first()
                    if member is None:
                        added += 1
                    elif not member.is_active:
                        reactivated += 1
                    else:
                        already += 1
                    continue

                member, created = ReferralListMember.objects.get_or_create(
                    user=user,
                )
                if created:
                    added += 1
                elif not member.is_active:
                    member.is_active = True
                    member.save(update_fields=["is_active"])
                    reactivated += 1
                else:
                    already += 1

        verb = "Would add" if dry else "Added"
        for name in matched_names:
            self.stdout.write(f"  matched: {name}")
        if skipped_roles:
            self.stdout.write(
                "Skipped (not a MEMBER-role user): " + ", ".join(skipped_roles)
            )
        if unmatched:
            self.stdout.write(self.style.WARNING(
                "UNMATCHED (no site account by login or public email): "
                + ", ".join(unmatched)
            ))
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {added}, reactivated {reactivated}, already listed "
            f"{already}, unmatched {len(unmatched)}. No email was sent — "
            "send New Member Instructions per clinician from "
            "/admin-tools/referrals/clinicians/ if wanted."
        ))
