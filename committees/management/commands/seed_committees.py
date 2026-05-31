"""Seed the Board + Programming Committee rosters (and the LSP Staff
designation) from the About page (M10 setup). Idempotent — re-run as the
roster shifts.

Memberships are resolved by `first_name + last_name` match against existing
User accounts. Names that don't resolve are reported with a hint so the
Web Coordinator can adjust (typo, spelling variant, missing account).

Committee rosters live on the committee's workgroup
(``WorkgroupMembership``). LSP Staff is not a committee — its members get the
``Profile.is_lsp_staff`` designation instead.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from committees.models import Committee
from workgroups.models import WorkgroupMembership

Role = WorkgroupMembership.Role

# --- Current rosters (source: lacanschool.org/abouttheschool, 2025-26) ----

BOARD_2025_2026 = [
    ("Christopher", "Meyer",               Role.CHAIR),       # President
    ("Beatrice",    "Patsalides Hofmann",  Role.CO_CHAIR),    # Vice President
    ("Garrett",     "Tanner",              Role.TREASURER),
    ("Diana",       "Cuello",              Role.SECRETARY),
    ("Marcelo",     "Estrada",             Role.MEMBER),
    ("Annie",       "Rogers",              Role.MEMBER),
    ("Nathan",      "Lupo",                Role.MEMBER),
]

PROGRAMMING_COMMITTEE_2025_2026 = [
    ("Diana",      "Cuello",               Role.CHAIR),  # Convener
    ("Marcelo",    "Estrada",              Role.MEMBER),
    ("Christopher","Meyer",                Role.MEMBER),
    ("Sheila",     "Cavanagh",             Role.MEMBER),
    ("Casey",      "Butcher",              Role.MEMBER),
    # Wix About page spells it "Fisher"; the directory roster has "Fischer".
    ("Julien",     "Fischer",              Role.MEMBER),
    ("John",       "Kreitzberg",           Role.MEMBER),
]

# LSP Staff is now a designation (Profile.is_lsp_staff), not a committee.
LSP_STAFF_2025_2026 = [
    ("Diana",      "Cuello"),
    # Add Web Coordinator / Admin Assistant here when their User accounts exist.
]

COMMITTEE_ROSTERS = [
    ("board",                 BOARD_2025_2026),
    ("programming-committee", PROGRAMMING_COMMITTEE_2025_2026),
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
    help = "Seed Board + Programming Committee rosters and the LSP Staff designation."

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
        report = {"created": 0, "kept": 0, "closed": 0, "staff": 0, "unresolved": []}

        with transaction.atomic():
            for slug, roster in COMMITTEE_ROSTERS:
                committee = Committee.objects.filter(slug=slug).first()
                if committee is None:
                    self.stderr.write(f"  no committee with slug={slug!r}; skipping")
                    continue
                if not committee.public:
                    committee.public = True
                    committee.save(update_fields=["public"])
                wg = committee.workgroup
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

                    existing = wg.memberships.filter(user=user, end_date__isnull=True).first()
                    if existing:
                        if existing.role != role:
                            existing.role = role
                            existing.save(update_fields=["role"])
                        report["kept"] += 1
                        continue
                    committee.add_member(user, role=role, start_date=start)
                    report["created"] += 1
                    self.stdout.write(f"  {slug}: added {first} {last} ({role})")

                # Close out memberships not in the current roster.
                to_close = (wg.memberships
                            .filter(end_date__isnull=True)
                            .exclude(user_id__in=target_users))
                for m in to_close:
                    m.end_date = today
                    m.save(update_fields=["end_date"])
                    report["closed"] += 1
                    self.stdout.write(
                        f"  {slug}: closed {m.user.first_name} {m.user.last_name}"
                    )

            # LSP Staff designation.
            for first, last in LSP_STAFF_2025_2026:
                user = _find_user(first, last)
                if user is None:
                    report["unresolved"].append(("lsp-staff", first, last))
                    self.stderr.write(self.style.WARNING(
                        f"  lsp-staff: no User found for {first!r} {last!r}"
                    ))
                    continue
                from core.models import StaffRole

                role, _ = StaffRole.objects.get_or_create(
                    key=StaffRole.LSP_STAFF, defaults={"name": "LSP Staff"},
                )
                if not role.holders.filter(pk=user.pk).exists():
                    role.holders.add(user)
                    report["staff"] += 1
                    self.stdout.write(f"  lsp-staff: designated {first} {last}")

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f"{'Would ' if dry_run else ''}create {report['created']}, "
            f"keep {report['kept']}, close {report['closed']} memberships; "
            f"{report['staff']} LSP Staff designated. "
            f"{len(report['unresolved'])} unresolved name(s)."
        ))
