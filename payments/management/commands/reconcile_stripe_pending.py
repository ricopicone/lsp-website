"""Settle stale PENDING Stripe payments against Stripe (task #474).

Every member sent to Checkout leaves a PENDING ``Payment`` row behind, and a
session that is never completed expires unpaid after ~24h. This asks Stripe for
the verdict on each stale row and applies it:

- expired session  → the payment is marked ABANDONED (no money moved)
- completed/paid   → the payment is settled through the normal success chain,
                     which is how a *missed* completion webhook gets recovered
- still open       → left alone

Safe to re-run; it only ever touches rows Stripe has already decided. Meant for
a daily timer on the host, alongside the other payment crons::

    uv run python manage.py reconcile_stripe_pending
    uv run python manage.py reconcile_stripe_pending --dry-run --hours 6
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from payments.stripe_sync import (
    STALE_AFTER_HOURS,
    fetch_session,
    settle_from_session,
    stale_pending_payments,
)


class Command(BaseCommand):
    help = "Settle stale pending Stripe payments (abandoned or missed-webhook)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=STALE_AFTER_HOURS,
            help=f"Only payments pending longer than this (default {STALE_AFTER_HOURS}).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        payments = list(stale_pending_payments(hours=opts["hours"]))
        if not payments:
            self.stdout.write("No stale pending Stripe payments.")
            return

        counts = {"abandoned": 0, "completed": 0, "open": 0, "error": 0}
        for payment in payments:
            label = (
                f"payment #{payment.pk} ${payment.amount} "
                f"{payment.payment_type} "
                f"({payment.user.email if payment.user_id else payment.email or '—'}, "
                f"pending since {payment.created_at:%Y-%m-%d %H:%M})"
            )
            try:
                session = fetch_session(payment.stripe_checkout_session_id)
            except Exception as exc:                    # pragma: no cover - network
                counts["error"] += 1
                self.stderr.write(f"  ! {label}: Stripe lookup failed — {exc}")
                continue

            if dry_run:
                status = session["status"] if "status" in session else "?"
                paid = session["payment_status"] if "payment_status" in session else "?"
                would = (
                    "complete" if paid == "paid" or status == "complete"
                    else "abandon" if status == "expired"
                    else "leave alone"
                )
                counts["completed" if would == "complete"
                       else "abandoned" if would == "abandon" else "open"] += 1
                self.stdout.write(
                    f"  would {would}: {label} — Stripe says "
                    f"status={status} payment_status={paid}"
                )
                continue

            outcome = settle_from_session(payment, session)
            if outcome == "completed":
                counts["completed"] += 1
                self.stdout.write(self.style.SUCCESS(f"  settled as paid: {label}"))
            elif outcome == "abandoned":
                counts["abandoned"] += 1
                self.stdout.write(f"  abandoned: {label}")
            else:
                counts["open"] += 1
                self.stdout.write(f"  still open at Stripe: {label}")

        self.stdout.write(
            f"{len(payments)} stale pending payment(s): "
            f"{counts['completed']} settled as paid, "
            f"{counts['abandoned']} abandoned, "
            f"{counts['open']} left open"
            + (f", {counts['error']} lookup error(s)" if counts["error"] else "")
            + (" (dry run — nothing written)" if dry_run else "")
        )
