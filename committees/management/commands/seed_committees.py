"""Seed the Board + Programming Committee with current rosters from the
About page (M10 setup). Idempotent — re-run as the roster shifts.

Memberships are resolved by `first_name + last_name` match against existing
User accounts. Names that don't resolve are reported with a hint so the
Web Coordinator can adjust (typo, spelling variant, missing account).

Each named member is granted an *active* membership (end_date=None) with
their listed role. Previously-active memberships not in the current list
are *closed* (end_date set to today) — that way the historical record
sticks around while only the current roster reads as active.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from committees.models import Committee, CommitteeMembership

# --- Current rosters (source: lacanschool.org/abouttheschool, 2025-26) ----
#
# Roles map to CommitteeMembership.Role values. "Convener" maps to chair
# semantics in the spec; we use CHAIR here.

BOARD_2025_2026 = [
    ("Christopher", "Meyer",               CommitteeMembership.Role.CHAIR),       # President
    ("Beatrice",    "Patsalides Hofmann",  CommitteeMembership.Role.CO_CHAIR),    # Vice President
    ("Garrett",     "Tanner",              CommitteeMembership.Role.TREASURER),
    ("Diana",       "Cuello",              CommitteeMembership.Role.SECRETARY),
    ("Marcelo",     "Estrada",             CommitteeMembership.Role.MEMBER),
    ("Annie",       "Rogers",              CommitteeMembership.Role.MEMBER),
    ("Nathan",      "Lupo",                CommitteeMembership.Role.MEMBER),
]

PROGRAMMING_COMMITTEE_2025_2026 = [
    ("Diana",      "Cuello",               CommitteeMembership.Role.CHAIR),  # Convener
    ("Marcelo",    "Estrada",              CommitteeMembership.Role.MEMBER),
    ("Christopher","Meyer",                CommitteeMembership.Role.MEMBER),
    ("Sheila",     "Cavanagh",             CommitteeMembership.Role.MEMBER),
    ("Casey",      "Butcher",              CommitteeMembership.Role.MEMBER),
    # Wix About page spells it "Fisher"; the directory roster has "Fischer".
    ("Julien",     "Fischer",              CommitteeMembership.Role.MEMBER),
    ("John",       "Kreitzberg",           CommitteeMembership.Role.MEMBER),
]

LSP_STAFF_2025_2026 = [
    ("Diana",      "Cuello",               CommitteeMembership.Role.REFERRAL_COORDINATOR),
    # Add Web Coordinator / Admin Assistant here when their User accounts exist.
]

ROSTERS = [
    ("board",                 BOARD_2025_2026,                 True),
    ("programming-committee", PROGRAMMING_COMMITTEE_2025_2026, True),
    ("lsp-staff",             LSP_STAFF_2025_2026,             True),
]


def _find_user(first: str, last: str) -> User | None:
    # Try exact match first, then case-insensitive, then last-name only.
    qs = User.objects.filter(first_name=first, last_name=last)
    if qs.exists():
        return qs.first()
    qs = User.objects.filter(first_name__iexact=first, last_name__iexact=last)
    if qs.exists():
        return qs.first()
    qs = User.objects.filter(last_name__iexact=last)
    if qs.count() == 1:
        return qs.first()
    return None


class Command(BaseCommand):
    help = "Seed Board + Programming Committee with current rosters from the About page."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--start-date",
            default="2025-09-01",
            help="Default start_date for new memberships (the academic year).",
        )

    def handle(self, *args, dry_run: bool, start_date: str, **opts):
        start = date.fromisoformat(start_date)
        today = date.today()
        report = {"created": 0, "kept": 0, "closed": 0, "unresolved": []}

        with transaction.atomic():
            for slug, roster, public in ROSTERS:
                committee = Committee.objects.filter(slug=slug).first()
                if committee is None:
                    self.stderr.write(f"  no committee with slug={slug!r}; skipping")
                    continue
                if not committee.public and public:
                    committee.public = True
                    committee.save(update_fields=["public"])

                target_users: set[int] = set()

                for first, last, role in roster:
                    user = _find_user(first, last)
                    if user is None:
                        report["unresolved"].append((slug, first, last))
                        self.stderr.write(self.style.WARNING(
                            f"  {slug}: no User found for {first!r} {last!r}"
                        ))
                        continue
                    target_users.add(user.pk)

                    existing = (committee.memberships
                                .filter(user=user, end_date__isnull=True)
                                .first())
                    if existing:
                        if existing.role_in_committee != role:
                            existing.role_in_committee = role
                            existing.save(update_fields=["role_in_committee"])
                        report["kept"] += 1
                        continue
                    CommitteeMembership.objects.create(
                        committee=committee, user=user,
                        role_in_committee=role, start_date=start,
                    )
                    report["created"] += 1
                    self.stdout.write(f"  {slug}: added {first} {last} ({role})")

                # Close out memberships not in the current roster.
                to_close = (committee.memberships
                            .filter(end_date__isnull=True)
                            .exclude(user_id__in=target_users))
                for m in to_close:
                    m.end_date = today
                    m.save(update_fields=["end_date"])
                    report["closed"] += 1
                    self.stdout.write(
                        f"  {slug}: closed {m.user.first_name} {m.user.last_name}"
                    )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"{'Would ' if dry_run else ''}create {report['created']}, "
            f"keep {report['kept']}, close {report['closed']} memberships. "
            f"{len(report['unresolved'])} unresolved name(s)."
        ))
