"""Purge Stripe test-mode payments that slipped into the database.

Identifies test payments by their unmistakable test-mode markers — a
``cs_test_…`` checkout-session id or ``livemode=False`` — and deletes them
(their Receipt cascades). A test charge has no business in real accounting.

Refuses to touch a payment linked to a Registration unless ``--force`` (so a
real registration isn't silently orphaned). Dry-run by default.

    uv run python manage.py purge_test_payments            # preview
    uv run python manage.py purge_test_payments --commit
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from payments.models import Payment


class Command(BaseCommand):
    help = "Delete Stripe test-mode payments (cs_test_ / livemode=False)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Actually delete (default: dry-run preview).")
        parser.add_argument("--force", action="store_true",
                            help="Also delete test payments linked to a Registration.")

    def handle(self, *args, **opts):
        test = (
            Payment.objects.filter(
                Q(stripe_checkout_session_id__startswith="cs_test_")
                | Q(livemode=False)
            )
            .select_related("user", "registration")
            .order_by("paid_at")
        )
        if not test.exists():
            self.stdout.write("No test-mode payments found. Clean.")
            return

        deletable, skipped = [], []
        for p in test:
            (skipped if (p.registration_id and not opts["force"]) else deletable).append(p)

        self.stdout.write(f"Found {test.count()} test-mode payment(s):")
        for p in test:
            tag = " [linked to registration — skipped]" if p in skipped else ""
            who = p.user.email if p.user_id else (p.email or "?")
            sess = p.stripe_checkout_session_id or "—"
            when = p.paid_at.strftime("%Y-%m-%d") if p.paid_at else "(no paid_at)"
            self.stdout.write(
                f"  #{p.id} {p.status} ${p.amount} {p.payment_type} {who} "
                f"{when} {sess}{tag}"
            )
        if skipped:
            self.stdout.write(
                f"\n{len(skipped)} linked to a registration — pass --force to include."
            )

        if not opts["commit"]:
            self.stdout.write(self.style.WARNING(
                f"\nDry run — would delete {len(deletable)}. Re-run with --commit."
            ))
            return

        with transaction.atomic():
            n, _ = Payment.objects.filter(
                id__in=[p.id for p in deletable]
            ).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {len(deletable)} test payment(s) (and cascaded receipts)."
        ))
