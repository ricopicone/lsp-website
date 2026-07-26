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
        parser.add_argument("--only-types", default=None,
                            help="Comma list of types to create (e.g. 'tuition'); "
                            "others are held back. Reconciles are unaffected.")
        parser.add_argument("--allow-overlaps", action="store_true",
                            help="Create rows even when they look like a ledger duplicate.")
        parser.add_argument("--sweep-unknown", action="store_true",
                            help="Provisionally type the leftover unknown charges "
                            "(source=ASSUMED): tuition for current students, "
                            "registration for those who've completed tuition.")
        parser.add_argument("--sweep-min", type=float, default=25.0,
                            help="Skip unknown charges below this amount when "
                            "sweeping (default 25, ignores card-test charges).")
        parser.add_argument("--verbose-rows", action="store_true",
                            help="List every charge and its planned action.")
        parser.add_argument("--dump-unknown", action="store_true",
                            help="List every still-unknown charge (payer, date, "
                            "description) to help classify the tail.")

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
            pi = _session_payment_intent_id(s)
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

    def build_context(self, default_type, only_types=None,
                      sweep_unknown=False, sweep_min=25.0):
        from decimal import Decimal

        from accounts.membership import current_academic_year_start
        from accounts.models import MembershipTenure, Profile, User
        from payments.models import DuesPeriod, TuitionEnrollment, TuitionPeriod
        from payments.stripe_import import TAG_RE, ay_of
        from payments.treasurer_import import NameMatcher

        payments = list(Payment.objects.all().only(
            "id", "stripe_payment_intent_id", "stripe_checkout_session_id",
            "status", "source", "method", "amount", "paid_at", "user_id", "notes",
            "payment_type",
        ))
        tags_seen = set()
        overlaps_by_user: dict = {}
        existing_dues_ay: dict = {}
        for p in payments:
            for m in TAG_RE.finditer(p.notes or ""):
                tags_seen.add(m.group(1))
            if not (p.user_id and p.status == Payment.Status.SUCCEEDED):
                continue
            # Dues are once-per-member-per-year: index every succeeded dues row
            # (any source/method) so a Stripe dues charge for that (member, AY)
            # is recognised as a duplicate.
            if p.payment_type == Payment.Type.DUES and p.paid_at:
                existing_dues_ay.setdefault((p.user_id, ay_of(p.paid_at.date())), p.pk)
            # Amount+date overlap candidates: succeeded ledger rows that carry
            # **no payment_intent**, so an id match is impossible and amount +
            # date is the only way to recognise the same money. Method is
            # deliberately not part of the test (task #474): the treasurer's
            # spreadsheet recorded the 2024 dues season as `method=stripe,
            # source=imported` rows with no intent, and skipping those left ~60
            # genuine duplicates looking like unrecorded charges.
            if (
                p.paid_at and not p.stripe_payment_intent_id
                and p.source in (Source.IMPORTED, Source.VERIFIED)
            ):
                overlaps_by_user.setdefault(p.user_id, []).append(
                    (p.amount, p.paid_at.date(), p.pk)
                )

        # Matcher pool. Deliberately NOT `is_active=True` (task #474): a
        # deceased member is deactivated by the Profile.deceased_on sync, and
        # excluding them doesn't merely miss a match — with no user_id the
        # duplicate check can't run at all, so payments already on their
        # account get reported as unrecorded money. Two of Barbara Freeman's
        # were, and committing would have doubled them.
        #
        # What must stay out is the never-verified signup — `is_active=False`
        # with no `email_verified_at`, the same pair `purge_unverified_signups`
        # treats as a bot row — so junk can't capture a real payment by name.
        # `deceased_on` re-admits regardless: only a staff action sets it, and
        # a member imported after the 0042 grandfather migration has no
        # `email_verified_at` to vouch for them.
        def _matchable(u):
            p = getattr(u, "profile", None)
            return bool(
                u.is_active
                or getattr(p, "email_verified_at", None)
                or getattr(p, "deceased_on", None)
            )

        users = [u for u in User.objects.select_related("profile") if _matchable(u)]
        email_to_user = {}
        for u in users:
            if u.email:
                email_to_user.setdefault(u.email.lower(), u.pk)
            pub = getattr(getattr(u, "profile", None), "public_email", "") or ""
            if pub:
                email_to_user.setdefault(pub.lower(), u.pk)

        # Per-year dues tiers + tuition amounts, for data-driven type inference.
        dues_amounts_by_ay: dict = {}
        dues_period_by_ay: dict = {}
        for dp in DuesPeriod.objects.all():
            ay = ay_of(dp.start_date)
            amts = {dp.dues_amount_pre_candidate, dp.dues_amount_candidate,
                    dp.dues_amount_analyst}
            dues_amounts_by_ay.setdefault(ay, set()).update(a for a in amts if a)
            dues_period_by_ay.setdefault(ay, dp.pk)
        tuition_by_ay = {
            ay_of(tp.start_date): tp.tuition_amount
            for tp in TuitionPeriod.objects.all()
        }

        # {(user_id, ay)} the member held a *non*-student role — blocks the
        # "multiple charges in an AY = installments" rule for them (e.g. an
        # analyst's repeat donations). Unknown role that year → allowed.
        cur_ay = current_academic_year_start()
        non_student_user_ays: set = set()
        for t in MembershipTenure.objects.exclude(role__in=Profile.IN_TRAINING_ROLES):
            last = t.end_ay if t.end_ay is not None else cur_ay
            for ay in range(t.start_ay, last + 1):
                non_student_user_ays.add((t.user_id, ay))

        # Members who have *completed* tuition — analysts/scholars (finished
        # training) or anyone with ≥4 tuition years on record. Used by the
        # --sweep-unknown pass: their leftover charges are assumed to be seminar
        # registrations, not tuition.
        completed_tuition_user_ids: set = {
            u.pk for u in users
            if getattr(getattr(u, "profile", None), "role", None)
            in (Profile.Role.ANALYST, Profile.Role.SCHOLAR)
        }
        tuition_years: dict = {}
        for te in (TuitionEnrollment.objects
                   .exclude(status=TuitionEnrollment.Status.SKIPPING)
                   .select_related("tuition_period")):
            tuition_years.setdefault(te.user_id, set()).add(
                ay_of(te.tuition_period.start_date)
            )
        for p in payments:
            if (p.payment_type == Payment.Type.TUITION and p.user_id
                    and p.status == Payment.Status.SUCCEEDED and p.paid_at):
                tuition_years.setdefault(p.user_id, set()).add(ay_of(p.paid_at.date()))
        completed_tuition_user_ids |= {
            uid for uid, yrs in tuition_years.items() if len(yrs) >= 4
        }

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
            dues_amounts_by_ay={k: frozenset(v) for k, v in dues_amounts_by_ay.items()},
            dues_period_by_ay=dues_period_by_ay,
            tuition_by_ay=tuition_by_ay,
            existing_dues_ay=existing_dues_ay,
            non_student_user_ays=non_student_user_ays,
            completed_tuition_user_ids=completed_tuition_user_ids,
            sweep_unknown=sweep_unknown,
            sweep_min=Decimal(str(sweep_min)),
            only_types=only_types,
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

        only_types = None
        if opts["only_types"]:
            only_types = {t.strip() for t in opts["only_types"].split(",") if t.strip()}
            bad = only_types - set(Payment.Type.values)
            if bad:
                raise CommandError(f"Unknown --only-types: {', '.join(sorted(bad))}")

        rows = [normalize_charge(c, sessions_by_pi=sessions_by_pi) for c in charges]
        ctx = self.build_context(
            opts["default_type"], only_types=only_types,
            sweep_unknown=opts["sweep_unknown"], sweep_min=opts["sweep_min"],
        )
        plans = plan_charges(rows, ctx, allow_overlaps=opts["allow_overlaps"])

        self._report(plans, committing=opts["commit"])

        if opts["verbose_rows"]:
            # Every charge and what's planned for it — the only way to see why
            # a specific charge is being skipped (the flag existed but was
            # never read until task #474, which is how a wrong "duplicate"
            # verdict stayed invisible).
            self.stdout.write(f"\nAll {len(plans)} charges:")
            for p in sorted(plans, key=lambda p: p.row.created):
                r = p.row
                who = r.name or r.email or "?"
                self.stdout.write(
                    f"  [{p.action:<17}] {r.charge_id}  ${r.amount:>9}  "
                    f"{r.created:%Y-%m-%d}  {who:<28.28}  {p.reason}"
                )

        if opts["dump_unknown"]:
            unknown = [p for p in plans if p.action == "needs_type"]
            self.stdout.write(f"\nAll {len(unknown)} unknown charges:")
            for p in sorted(unknown, key=lambda p: (p.row.amount, p.row.created)):
                r = p.row
                who = r.name or r.email or "?"
                self.stdout.write(
                    f"  ${r.amount:>8}  {r.created:%Y-%m-%d}  {who:<28.28}  "
                    f"{(r.description or '')[:50]}"
                )

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
        from collections import Counter, defaultdict
        from decimal import Decimal

        counts = Counter(p.action for p in plans)
        creates = [p for p in plans if p.action in ("create", "create_unmatched")]
        created_total = sum((p.row.amount for p in creates), Decimal("0"))
        self.stdout.write("")
        self.stdout.write(f"Charges examined: {len(plans)}")
        labels = {
            "create": "create (member matched)",
            "create_unmatched": "create (member UNMATCHED — link later)",
            "reconcile": "reconcile site payment (→ verified)",
            "reconcile_flag": "site payment pending/failed — COMPLETE via admin",
            "overlap": "skipped: likely ledger duplicate",
            "needs_type": "skipped: type unknown (use --default-type)",
            "skip_filtered": "skipped: held back by --only-types",
            "skip_already": "skipped: already imported",
            "skip_not_paid": "skipped: not a paid charge",
        }
        for action, label in labels.items():
            if counts.get(action):
                self.stdout.write(f"  {counts[action]:>4}  {label}")

        # Breakdown of what would be created, by inferred type.
        by_type: dict = defaultdict(lambda: [0, Decimal("0")])
        for p in creates:
            by_type[p.payment_type][0] += 1
            by_type[p.payment_type][1] += p.row.amount
        if by_type:
            self.stdout.write("\nNew rows by type:")
            for ptype, (n, total) in sorted(by_type.items()):
                self.stdout.write(f"  {n:>4}  {ptype:<13} ${total:,.2f}")
        provisional = [p for p in creates if p.provisional]
        if provisional:
            prov_total = sum((p.row.amount for p in provisional), Decimal("0"))
            self.stdout.write(
                f"  ({len(provisional)} of these are provisional sweeps, "
                f"${prov_total:,.2f}, recorded as source=ASSUMED)"
            )
        self.stdout.write(f"\n  New money to record: ${created_total:,.2f}")

        # Amount histogram for the still-unknown charges (helps pick a sweep).
        unknown = [p for p in plans if p.action == "needs_type"]
        if unknown:
            hist = Counter(str(p.row.amount) for p in unknown)
            self.stdout.write(f"\nType still unknown ({len(unknown)}), by amount:")
            for amt, n in hist.most_common(15):
                self.stdout.write(f"  {n:>4}  ${amt}")

        # Detail the rows that need a human eye (cap the noisy ones).
        attention = [p for p in plans if p.action in (
            "reconcile_flag", "create_unmatched",
        )]
        if attention:
            self.stdout.write("\nNeeds review:")
            for p in attention[:60]:
                r = p.row
                who = r.name or r.email or "?"
                self.stdout.write(
                    f"  [{p.action}] {r.charge_id}  ${r.amount}  {r.created:%Y-%m-%d}  "
                    f"{who} — {p.reason}"
                )
            if len(attention) > 60:
                self.stdout.write(f"  … and {len(attention) - 60} more")


def _session_payment_intent_id(session) -> str:
    """Return the ``payment_intent`` id from a Stripe ``checkout.Session``.

    Tolerant of both plain dicts and stripe-python SDK objects. Note the SDK's
    ``StripeObject`` (v15) does *not* expose a dict-style ``.get`` — accessing
    ``.get`` raises ``AttributeError`` — so we read via ``getattr``. The
    ``payment_intent`` may be a bare id string or, when expanded, an object
    whose ``id`` we dig out. Missing → ``""``.
    """
    pi = session.get("payment_intent") if isinstance(session, dict) \
        else getattr(session, "payment_intent", None)
    if pi is not None and not isinstance(pi, str):
        pi = pi.get("id") if isinstance(pi, dict) else getattr(pi, "id", None)
    return pi or ""


def _ts(date_str: str, *, end_of_day=False) -> int:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt_timezone.utc)
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.timestamp())


# Keep the dataclass importable for type hints in tests.
__all__ = ["Command", "StripeChargeRow"]
