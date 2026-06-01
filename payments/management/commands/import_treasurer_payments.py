"""Import the treasurer's historical tuition and dues ledgers (one-time backfill,
re-runnable as new yearly ledgers arrive).

Reads the per-academic-year Excel files, matches free-text payer names to
existing Users with high-confidence rules only (see ``payments.treasurer_import``),
and writes:

* **Tuition** — one ``Payment`` (type=TUITION) per ledger row, each linked to a
  reconstructed ``TuitionInstallment``, plus one ``TuitionEnrollment`` per
  (student, year) with status derived from the year's total vs. the period's
  full tuition.
* **Dues** — one ``Payment`` (type=DUES) per ledger row, attached to the year's
  ``DuesPeriod``. Rows tagged DONATION become type=DONATION with no period.

Safe by default: runs as a **dry-run** unless ``--commit`` is passed, is
**idempotent** (every created Payment is stamped with an import tag in ``notes``;
re-runs skip already-imported rows), and **atomic** per invocation. No receipts
are generated and no emails are sent — this is a back-office backfill.

Names that don't match a User at high confidence are **skipped and listed** in
the report for manual follow-up, never guessed.

Usage::

    # dry-run against whatever DB DJANGO_SETTINGS_MODULE points at
    python manage.py import_treasurer_payments --source-dir /path/to/treasurer-files
    # write for real
    python manage.py import_treasurer_payments --source-dir /path/to/... --commit
    # restrict to some datasets
    python manage.py import_treasurer_payments --datasets tuition-24-25 dues-25-26
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from payments.models import (
    DuesPeriod,
    Payment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
)
from payments.treasurer_import import (
    LedgerRow,
    NameMatcher,
    parse_dues_ledger,
    parse_tuition_ledger,
)

#: All Payment.notes from this importer start with this, for idempotency + audit.
IMPORT_TAG_PREFIX = "tz-import"

# Dues tiers observed in the ledgers (pre-candidate / candidate / analyst·scholar).
_DUES_TIERS = (Decimal("50"), Decimal("100"), Decimal("150"))


@dataclass(frozen=True)
class Dataset:
    key: str
    kind: str          # "tuition" | "dues"
    rel_path: str      # path relative to --source-dir
    ay_start: int      # academic-year start year (period runs Sep ay_start .. Aug ay_start+1)
    tuition_amount: Decimal | None = None  # full annual tuition, tuition datasets only


DATASETS: list[Dataset] = [
    Dataset("tuition-24-25", "tuition", "Tuition 24-25.xlsx", 2024, Decimal("2000")),
    Dataset("tuition-25-26", "tuition", "Treasurer 2026/Tuition 25-26.xlsx", 2025, Decimal("2500")),
    Dataset("dues-24-25", "dues", "Dues 24-25.xlsx", 2024),
    Dataset("dues-25-26", "dues", "Treasurer 2026/Dues 25-26.xlsx", 2025),
]


def _import_tag(dataset_key: str, row_index: int) -> str:
    return f"[{IMPORT_TAG_PREFIX}:{dataset_key}#{row_index}]"


def _aware(d: date | None):
    """A date -> aware datetime at local noon (avoids tz date-shift); None -> None."""
    if d is None:
        return None
    return timezone.make_aware(datetime.combine(d, time(12, 0)))


def _payment_method(raw_method: str) -> tuple[str, str]:
    """Map a ledger method string to (Payment.Method value, note suffix)."""
    m = (raw_method or "").strip().lower()
    if m == "stripe":
        return Payment.Method.STRIPE, ""
    if m:
        return Payment.Method.OFFLINE, f"method: {raw_method}"
    return Payment.Method.OFFLINE, "method unrecorded in ledger"


class Command(BaseCommand):
    help = "Import historical treasurer tuition/dues ledgers (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dir", required=True,
            help="Directory containing the treasurer xlsx files.",
        )
        parser.add_argument(
            "--datasets", nargs="*", default=None,
            help=f"Subset of dataset keys to import. Default: all "
                 f"({', '.join(d.key for d in DATASETS)}).",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write to the database. Without it, dry-run only.",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"]).expanduser()
        if not source_dir.is_dir():
            raise CommandError(f"--source-dir not found: {source_dir}")

        wanted = options["datasets"]
        datasets = [d for d in DATASETS if (wanted is None or d.key in wanted)]
        if not datasets:
            raise CommandError(f"No datasets match {wanted!r}.")

        commit = options["commit"]
        matcher = NameMatcher.from_queryset(
            User.objects.select_related("profile").all()
        )
        roster_size = User.objects.count()
        self.stdout.write(
            f"Roster: {roster_size} users. Mode: "
            + (self.style.WARNING("COMMIT") if commit else self.style.NOTICE("DRY-RUN"))
        )
        if roster_size == 0:
            self.stdout.write(self.style.ERROR(
                "Roster is empty — name matching needs the member roster. Run this "
                "against the production DB (or a snapshot)."
            ))

        # One transaction for the whole run; rolled back at the end on dry-run.
        with transaction.atomic():
            sid = transaction.savepoint()
            for ds in datasets:
                self._import_dataset(ds, source_dir, matcher, commit)
            if not commit:
                transaction.savepoint_rollback(sid)
                self.stdout.write(self.style.NOTICE(
                    "\nDRY-RUN complete — no changes written. Re-run with --commit to apply."
                ))
            else:
                transaction.savepoint_commit(sid)
                self.stdout.write(self.style.SUCCESS("\nCOMMIT complete."))

    # -- per-dataset -------------------------------------------------------

    def _import_dataset(self, ds: Dataset, source_dir: Path, matcher: NameMatcher, commit: bool):
        path = source_dir / ds.rel_path
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {ds.key}  ({ds.rel_path}) ==="))
        if not path.exists():
            self.stdout.write(self.style.ERROR(f"  missing file: {path}"))
            return

        rows = (parse_tuition_ledger(path) if ds.kind == "tuition"
                else parse_dues_ledger(path))
        sheet_total = sum((r.amount for r in rows), Decimal("0"))

        # Resolve names up front.
        matched: list[tuple[LedgerRow, int]] = []
        unmatched: list[LedgerRow] = []
        for r in rows:
            res = matcher.match(r.raw_name)
            if res.user_id is not None:
                matched.append((r, res.user_id))
            else:
                unmatched.append(r)

        if ds.kind == "tuition":
            created, skipped = self._import_tuition(ds, matched, commit)
        else:
            created, skipped = self._import_dues(ds, matched, commit)

        matched_total = sum((r.amount for r, _ in matched), Decimal("0"))
        unmatched_total = sum((r.amount for r in unmatched), Decimal("0"))

        self.stdout.write(
            f"  rows={len(rows)}  sheet_total=${sheet_total}\n"
            f"  matched={len(matched)} (${matched_total})  "
            f"unmatched={len(unmatched)} (${unmatched_total})\n"
            f"  payments created={created}  already-present(skipped)={skipped}"
        )
        if unmatched:
            distinct = sorted({r.raw_name for r in unmatched})
            self.stdout.write(self.style.WARNING(
                f"  UNMATCHED names ({len(distinct)} distinct) — need manual entry:"
            ))
            for n in distinct:
                self.stdout.write(f"      - {n}")

    # -- tuition -----------------------------------------------------------

    def _import_tuition(self, ds: Dataset, matched, commit: bool) -> tuple[int, int]:
        period = self._ensure_tuition_period(ds, commit)
        created = skipped = 0

        # Group matched rows by user so we can build one enrollment per student.
        by_user: dict[int, list[LedgerRow]] = {}
        for r, uid in matched:
            by_user.setdefault(uid, []).append(r)

        for uid, user_rows in by_user.items():
            user_rows.sort(key=lambda r: (r.paid_on or date.max, r.row_index))
            total = sum((r.amount for r in user_rows), Decimal("0"))
            status = (
                TuitionEnrollment.Status.PAID_IN_FULL
                if ds.tuition_amount and total >= ds.tuition_amount
                else TuitionEnrollment.Status.PAYMENT_PLAN
            )

            enrollment = None
            if commit and period is not None:
                enrollment, _ = TuitionEnrollment.objects.get_or_create(
                    user_id=uid, tuition_period=period,
                    defaults={"status": status,
                              "notes": f"Backfilled from {ds.rel_path}."},
                )
                # Refresh status from the (possibly more complete) ledger total.
                if enrollment.status != status:
                    enrollment.status = status
                    enrollment.save(update_fields=["status"])

            seq = 0
            for r in user_rows:
                tag = _import_tag(ds.key, r.row_index)
                if Payment.objects.filter(notes__contains=tag).exists():
                    skipped += 1
                    continue
                seq += 1
                if not commit:
                    created += 1
                    continue
                installment = None
                if enrollment is not None:
                    # Next free sequence within this enrollment (re-run safe).
                    base = enrollment.installments.count()
                    installment = TuitionInstallment.objects.create(
                        enrollment=enrollment,
                        sequence=base + 1,
                        due_date=r.paid_on or period.start_date,
                        amount=r.amount,
                        paid=True,
                        paid_at=_aware(r.paid_on),
                    )
                method, method_note = _payment_method("")  # tuition ledger has no method
                note_bits = [tag]
                if r.installment_label:
                    note_bits.append(f"installment: {r.installment_label}")
                if r.note:
                    note_bits.append(r.note)
                note_bits.append(method_note)
                Payment.objects.create(
                    payment_type=Payment.Type.TUITION,
                    user_id=uid,
                    amount=r.amount,
                    status=Payment.Status.SUCCEEDED,
                    method=method,
                    tuition_installment=installment,
                    paid_at=_aware(r.paid_on),
                    notes=" | ".join(b for b in note_bits if b),
                )
                created += 1
        return created, skipped

    # -- dues --------------------------------------------------------------

    def _import_dues(self, ds: Dataset, matched, commit: bool) -> tuple[int, int]:
        period = self._ensure_dues_period(ds, commit)
        created = skipped = 0
        for r, uid in matched:
            tag = _import_tag(ds.key, r.row_index)
            if Payment.objects.filter(notes__contains=tag).exists():
                skipped += 1
                continue
            if not commit:
                created += 1
                continue
            is_donation = "donation" in r.flags
            method, method_note = _payment_method(r.method)
            note_bits = [tag, r.note, method_note]
            Payment.objects.create(
                payment_type=(Payment.Type.DONATION if is_donation
                              else Payment.Type.DUES),
                user_id=uid,
                amount=r.amount,
                status=Payment.Status.SUCCEEDED,
                method=method,
                dues_period=(None if is_donation else period),
                paid_at=_aware(r.paid_on),
                notes=" | ".join(b for b in note_bits if b),
            )
            created += 1
        return created, skipped

    # -- period helpers ----------------------------------------------------

    def _ensure_tuition_period(self, ds: Dataset, commit: bool) -> TuitionPeriod | None:
        slug = f"ay-{ds.ay_start}-{ds.ay_start + 1}-tuition"
        period = TuitionPeriod.objects.filter(slug=slug).first()
        if period:
            return period
        if not commit:
            self.stdout.write(f"  would create TuitionPeriod {slug} (${ds.tuition_amount})")
            return None
        period = TuitionPeriod.objects.create(
            name=f"AY {ds.ay_start}–{ds.ay_start + 1}",
            slug=slug,
            start_date=date(ds.ay_start, 9, 1),
            decision_due_date=date(ds.ay_start, 8, 31),
            end_date=date(ds.ay_start + 1, 8, 31),
            tuition_amount=ds.tuition_amount,
        )
        self.stdout.write(self.style.SUCCESS(f"  created TuitionPeriod {period.name}"))
        return period

    def _ensure_dues_period(self, ds: Dataset, commit: bool) -> DuesPeriod | None:
        slug = f"ay-{ds.ay_start}-{ds.ay_start + 1}"
        period = DuesPeriod.objects.filter(slug=slug).first()
        if period:
            return period
        if not commit:
            tiers = "/".join(map(str, _DUES_TIERS))
            self.stdout.write(f"  would create DuesPeriod {slug} (tiers ${tiers})")
            return None
        pre, cand, analyst = _DUES_TIERS
        period = DuesPeriod.objects.create(
            name=f"AY {ds.ay_start}–{ds.ay_start + 1}",
            slug=slug,
            start_date=date(ds.ay_start, 9, 1),
            due_date=date(ds.ay_start, 10, 1),
            end_date=date(ds.ay_start + 1, 8, 31),
            dues_amount_pre_candidate=pre,
            dues_amount_candidate=cand,
            dues_amount_analyst=analyst,
        )
        self.stdout.write(self.style.SUCCESS(f"  created DuesPeriod {period.name}"))
        return period
