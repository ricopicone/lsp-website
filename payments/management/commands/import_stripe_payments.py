"""Import historical Stripe charges to supplement the imported/inferred ledger.

Dry-run by default; pass ``--commit`` to write. Reconciles charges that already
have a site ``Payment`` (by payment-intent / checkout-session / metadata) and
creates rows for charges taken outside this site, matching the member by email
then name (high-confidence only). Idempotent via a ``[stripe-import:<id>]`` tag.

Read access only: supply a **restricted, read-only** Stripe API key via
``--api-key`` or the ``STRIPE_IMPORT_KEY`` env var. The command never needs a
writable key, and (unless ``--use-settings-key``) won't fall back to the app's
configured ``STRIPE_SECRET_KEY``.

Examples::

    # Safe preview against the LSP account (reads STRIPE_IMPORT_KEY):
    export STRIPE_IMPORT_KEY=rk_live_...
    uv run python manage.py import_stripe_payments

    # Limit the window, then commit:
    uv run python manage.py import_stripe_payments --since 2022-01-01
    uv run python manage.py import_stripe_payments --commit

    # Sweep the leftovers whose type couldn't be inferred:
    uv run python manage.py import_stripe_payments --default-type donation --commit
"""

from __future__ import annotations

import os
from datetime import datetime
from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Source
from payments.models import Payment
from payments.stripe_import import (
    PlanContext,
    StripeChargeRow,
    apply_plan,
    normalize_charge,
    plan_charges,
)


class Command(BaseCommand):
    help = "Import historical Stripe charges (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true",
                            help="Write changes (default: dry-run preview).")
        parser.add_argument("--api-key", default=None,
                            help="Stripe restricted read-only key (else $STRIPE_IMPORT_KEY).")
        parser.add_argument("--use-settings-key", action="store_true",
                            help="Allow falling back to settings.STRIPE_SECRET_KEY.")
        parser.add_argument("--since", default=None, help="Only charges on/after YYYY-MM-DD.")
        parser.add_argument("--until", default=None, help="Only charges on/before YYYY-MM-DD.")
        parser.add_argument("--default-type", default=None,
                            choices=Payment.Type.values,
                            help="Type for charges whose type can't be inferred.")
        parser.add_argument("--allow-overlaps", action="store_true",
                            help="Create rows even when they look like a ledger duplicate.")
        parser.add_argument("--verbose-rows", action="store_true",
                            help="List every charge and its planned action.")

    # -- fetch (live Stripe; not unit-tested) --------------------------------

    def _resolve_key(self, opts):
        key = opts["api_key"] or os.environ.get("STRIPE_IMPORT_KEY")
        if not key and opts["use_settings_key"]:
            from django.conf import settings
            key = getattr(settings, "STRIPE_SECRET_KEY", "")
        if not key:
            raise CommandError(
                "No Stripe key. Pass --api-key or set STRIPE_IMPORT_KEY "
                "(a restricted, read-only key)."
            )
        return key

    def _fetch(self, key, since, until):
        import stripe
        created = {}
        if since:
            created["gte"] = _ts(since)
        if until:
            created["lte"] = _ts(until, end_of_day=True)
        # Sessions first → payment_intent -> session map for site-checkout links.
        sess_params = {"limit": 100}
        if created:
            sess_params["created"] = created
        sessions_by_pi = {}
        for s in stripe.checkout.Session.list(api_key=key, **sess_params).auto_paging_iter():
            pi = s.get("payment_intent")
            if isinstance(pi, dict):
                pi = pi.get("id")
            if pi:
                sessions_by_pi[pi] = s
        charge_params = {"limit": 100, "expand": ["data.customer"]}
        if created:
            charge_params["created"] = created
        charges = list(
            stripe.Charge.list(api_key=key, **charge_params).auto_paging_iter()
        )
        return charges, sessions_by_pi

    # -- context from the DB -------------------------------------------------

    def build_context(self, default_type):
        from accounts.models import User
        from payments.stripe_import import TAG_RE
        from payments.treasurer_import import NameMatcher

        payments = list(Payment.objects.all().only(
            "id", "stripe_payment_intent_id", "stripe_checkout_session_id",
            "status", "source", "method", "amount", "paid_at", "user_id", "notes",
        ))
        tags_seen = set()
        overlaps_by_user: dict = {}
        for p in payments:
            for m in TAG_RE.finditer(p.notes or ""):
                tags_seen.add(m.group(1))
            # Overlap candidates: succeeded offline rows from the treasurer ledger.
            if (
                p.user_id and p.paid_at
                and p.status == Payment.Status.SUCCEEDED
                and p.method == Payment.Method.OFFLINE
                and p.source in (Source.IMPORTED, Source.VERIFIED)
            ):
                overlaps_by_user.setdefault(p.user_id, []).append(
                    (p.amount, p.paid_at.date(), p.pk)
                )

        users = list(
            User.objects.filter(is_active=True).select_related("profile")
        )
        email_to_user = {}
        for u in users:
            if u.email:
                email_to_user.setdefault(u.email.lower(), u.pk)
            pub = getattr(getattr(u, "profile", None), "public_email", "") or ""
            if pub:
                email_to_user.setdefault(pub.lower(), u.pk)

        return PlanContext(
            valid_types=set(Payment.Type.values),
            tags_seen=tags_seen,
            payment_by_pi={
                p.stripe_payment_intent_id: p
                for p in payments if p.stripe_payment_intent_id
            },
            payment_by_session={
                p.stripe_checkout_session_id: p
                for p in payments if p.stripe_checkout_session_id
            },
            payment_by_pk={p.pk: p for p in payments},
            email_to_user=email_to_user,
            matcher=NameMatcher.from_queryset(users),
            overlaps_by_user=overlaps_by_user,
            default_type=default_type,
        )

    # -- main ---------------------------------------------------------------

    def handle(self, *args, **opts):
        key = self._resolve_key(opts)
        self.stdout.write("Fetching charges from Stripe…")
        try:
            charges, sessions_by_pi = self._fetch(key, opts["since"], opts["until"])
        except Exception as exc:  # network / auth / SDK
            raise CommandError(f"Stripe fetch failed: {exc}") from exc

        rows = [normalize_charge(c, sessions_by_pi=sessions_by_pi) for c in charges]
        ctx = self.build_context(opts["default_type"])
        plans = plan_charges(rows, ctx, allow_overlaps=opts["allow_overlaps"])

        self._report(plans, committing=opts["commit"])

        if opts["commit"]:
            with transaction.atomic():
                counts = apply_plan(plans)
            self.stdout.write(self.style.SUCCESS(
                f"Committed: {counts['create'] + counts['create_unmatched']} created, "
                f"{counts['reconcile'] + counts['reconcile_flag']} reconciled."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run with --commit to apply."
            ))

    def _report(self, plans, *, committing):
        from collections import Counter
        from decimal import Decimal

        counts = Counter(p.action for p in plans)
        created_total = sum(
            (p.row.amount for p in plans if p.action in ("create", "create_unmatched")),
            Decimal("0"),
        )
        self.stdout.write("")
        self.stdout.write(f"Charges examined: {len(plans)}")
        labels = {
            "create": "create (member matched)",
            "create_unmatched": "create (member UNMATCHED — link later)",
            "reconcile": "reconcile site payment (→ verified)",
            "reconcile_flag": "site payment pending/failed — COMPLETE via admin",
            "overlap": "skipped: likely ledger duplicate",
            "needs_type": "skipped: type unknown (use --default-type)",
            "skip_already": "skipped: already imported",
            "skip_not_paid": "skipped: not a paid charge",
        }
        for action, label in labels.items():
            if counts.get(action):
                self.stdout.write(f"  {counts[action]:>4}  {label}")
        self.stdout.write(f"\n  New money to record: ${created_total:,.2f}")

        # Detail the rows that need a human eye.
        attention = [p for p in plans if p.action in (
            "reconcile_flag", "overlap", "create_unmatched", "needs_type",
        )]
        if attention:
            self.stdout.write("\nNeeds review:")
            for p in attention:
                r = p.row
                who = r.name or r.email or "?"
                self.stdout.write(
                    f"  [{p.action}] {r.charge_id}  ${r.amount}  {r.created:%Y-%m-%d}  "
                    f"{who} — {p.reason}"
                )


def _ts(date_str: str, *, end_of_day=False) -> int:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt_timezone.utc)
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.timestamp())


# Keep the dataclass importable for type hints in tests.
__all__ = ["Command", "StripeChargeRow"]
