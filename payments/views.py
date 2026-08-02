"""Public payment views: webhook, dues, donations, thanks, exports, dashboard."""

from __future__ import annotations

import csv
import logging
from collections import Counter
from datetime import date, datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from registrations.models import Registration

from . import coverage
from .forms import DonationForm, TuitionDecisionForm
from .models import (
    Charge,
    DuesPeriod,
    LedgerSubmission,
    Payment,
    PaymentMemberAction,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
    TuitionPlanApplication,
)
from .notifications import (
    notify_coverage_rebilled,
    notify_plan_application_submitted,
)
from .operations import complete_payment
from .stripe_checkout import (
    create_donation_session,
    create_dues_session,
    create_tuition_session,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _is_staff(user):
    """Gate for the treasurer/financial area: Django staff or the Treasurer role."""
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    from core.access import has_staff_role
    from core.models import StaffRole

    return has_staff_role(user, StaffRole.TREASURER)


TREASURER_TABS = [
    ("overview", "Overview"),
    ("accounts", "Accounts"),
    ("payments", "Payments"),
    ("reconcile", "Reconcile"),
    ("settings", "Settings"),
    ("exports",  "Exports"),
    ("help",     "Help"),
]


def _treasurer_tab_links() -> list[tuple[str, str, str]]:
    """Returns [(key, label, url), ...] used by the tab nav."""
    from django.urls import reverse
    name_to_url = {
        "overview": reverse("treasurer"),
        "accounts": reverse("treasurer_accounts"),
        "payments": reverse("treasurer_payments"),
        "reconcile": reverse("treasurer_reconcile"),
        "settings": reverse("treasurer_settings"),
        "exports":  reverse("treasurer_exports"),
        "help":     reverse("treasurer_help"),
    }
    return [(key, label, name_to_url[key]) for key, label in TREASURER_TABS]


def _treasurer_render(request, tab_key: str, template: str, ctx: dict):
    """Common render helper: injects the tab nav into every treasurer page."""
    ctx = {**ctx, "tab_key": tab_key, "tabs": _treasurer_tab_links()}
    return render(request, template, ctx)


@login_required
@user_passes_test(_is_staff)
def treasurer_dashboard(request):
    """Overview tab — ledger tiles + one consolidated needs-attention queue."""
    from payments import ledger

    rows = ledger.accounts_overview()
    owing = [r for r in rows if r["owes"]]
    return _treasurer_render(request, "overview", "payments/treasurer/overview.html", {
        "collected": ledger.collected_this_ay(),
        "total_outstanding": sum((r["owes"] for r in owing), Decimal("0")),
        "owing_count": len(owing),
        "credit_count": sum(1 for r in rows if r["credit"]),
        "account_count": len(rows),
        "attention": _attention_queue(rows),
    })


def _charge_conflicts(rows=None) -> list[dict]:
    """Charge conflicts: staff-adjusted charges skipped by the minting sync.

    When the tuition-enrollment sync runs, it never edits a charge that a
    treasurer has touched (staff_adjusted=True) — if the charge and the
    enrollment disagree, the charge is flagged as a conflict instead.
    """
    from payments.charges import tuition_charge_conflicts

    if rows is None:
        from payments import ledger
        rows = ledger.accounts_overview()

    conflicts = list(tuition_charge_conflicts())
    conflicts += [
        {"user": r["user"], "charge": None, "expected_rate": None,
         "problem": f"${r['tuition_overpaid']} paid beyond the tuition "
                    "obligation while a year is marked Skipping — a skipped "
                    "year was probably actually paid."}
        for r in rows if r["conflict"]
    ]
    return conflicts


def _attention_queue(rows) -> dict:
    """Everything that needs the treasurer, in one place."""
    from accounts.models import Profile, Source
    from payments import ledger

    period = TuitionPeriod.current()
    undecided, committed_unpaid = [], []
    if period is not None:
        enrollments = list(
            TuitionEnrollment.objects.filter(tuition_period=period)
            .select_related("user"))
        decided_ids = {e.user_id for e in enrollments}
        in_training = User.objects.filter(
            is_active=True, profile__is_persona=False,
            profile__standing=Profile.Standing.ACTIVE,
            profile__role__in=Profile.IN_TRAINING_ROLES,
        ).select_related("profile")
        # Batched — the per-member tuition_decision_exempt() would rebuild a
        # whole member_account for each in-training member (task #443).
        exempt_ids = ledger.decision_exempt_ids(rows)
        undecided = [u for u in in_training
                     if u.id not in decided_ids and u.id not in exempt_ids]
        committed_unpaid = [
            e for e in enrollments
            if e.status == TuitionEnrollment.Status.COMMITTED]
    conflicts = _charge_conflicts(rows)
    return {
        "undecided": undecided,
        "committed_unpaid": committed_unpaid,
        "conflicts": conflicts,
        "assumed_count": Payment.objects.filter(source=Source.ASSUMED).count(),
        "no_payer_count": Payment.objects.filter(
            source=Source.STRIPE, user__isnull=True).count(),
        "submission_count": LedgerSubmission.objects.filter(
            status=LedgerSubmission.Status.PENDING).count(),
        "member_action_count": PaymentMemberAction.objects.filter(
            created_at__gte=_member_actions_since()).count(),
        "member_action_days": MEMBER_ACTION_WINDOW_DAYS,
        "tuition_period": period,
    }


@login_required
@user_passes_test(_is_staff)
def treasurer_accounts(request):
    """Accounts tab — every member's unified-ledger standing (task #439).

    Filters and sort live in the querystring so filtered views are linkable
    (the replacement for the old per-category rosters)."""
    from payments import ledger

    rows = ledger.accounts_overview()
    q = (request.GET.get("q") or "").strip().lower()
    balance = request.GET.get("balance") or ""
    role = request.GET.get("role") or ""
    sort = request.GET.get("sort") or "balance"

    if q:
        rows = [r for r in rows
                if q in (r["user"].get_full_name() or "").lower()
                or q in r["user"].email.lower()]
    if balance == "owing":
        rows = [r for r in rows if r["owes"]]
    elif balance == "credit":
        rows = [r for r in rows if r["credit"]]
    elif balance == "square":
        rows = [r for r in rows if r["balance"] == 0]
    if role:
        rows = [r for r in rows if r["user"].profile.role == role]

    if sort == "name":
        rows.sort(key=lambda r: (r["user"].last_name or "",
                                 r["user"].first_name or "", r["user"].email))
    elif sort == "paid":
        rows.sort(key=lambda r: -r["paid"])
    elif sort == "last":
        rows.sort(key=lambda r: (r["last_payment"] is None,
                                 -(r["last_payment"].timestamp()
                                   if r["last_payment"] else 0)))
    # default: accounts_overview's most-owed-first ordering

    from accounts.models import Profile
    # "balance" is the default sort — don't count it as an active filter, or
    # the Clear link (gated on filter_qs) shows even with nothing to clear.
    filter_qs = urlencode({k: v for k, v in (
        ("q", q), ("balance", balance), ("role", role),
        ("sort", sort if sort != "balance" else "")) if v})
    return _treasurer_render(request, "accounts", "payments/treasurer/accounts.html", {
        "rows": rows,
        "q": q,
        "selected_balance": balance,
        "selected_role": role,
        "selected_sort": sort,
        "role_choices": Profile.Role.choices,
        "filter_qs": filter_qs,
        "total_owed": sum((r["owes"] for r in rows), Decimal("0")),
        # Pre-backfill/pre-sync state: with no charges minted every obligation
        # reads $0 and payments show as credit — say so instead of confusing.
        "ledger_empty": not Charge.objects.exclude(
            status=Charge.Status.VOID).exists(),
    })


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_sync_charges(request):
    """Mint any missing current-year dues charges (manual sync button)."""
    from payments.charges import sync_dues_charges

    period = DuesPeriod.current()
    if period is not None:
        n = sync_dues_charges(period)
        messages.success(request, f"Synced — {n} dues charge(s) minted for {period.name}.")
    else:
        messages.error(request, "No current dues period.")
    return redirect("treasurer_accounts")


@login_required
@user_passes_test(_is_staff)
def treasurer_reconcile(request):
    """Reconcile provisional payments (source=ASSUMED) — the recurring-charge
    sweep booked as tuition pending the member survey. Grouped by payer so a
    single answer ("those were seminars") re-types all of one person's charges,
    and unmatched payers can be linked to a member."""
    from accounts.models import Source

    if request.method == "POST":
        if request.POST.get("form") == "no_payer":
            return _no_payer_apply(request)
        return _reconcile_apply(request)

    assumed = list(
        Payment.objects.filter(source=Source.ASSUMED)
        .select_related("user")
        .order_by("-paid_at")
    )
    group_list = _payer_groups(assumed)

    # "No payer": confidently-typed Stripe charges linked to no member. Disjoint
    # from the assumed queue above; Reconcile would otherwise never surface them.
    no_payer = list(
        Payment.objects.filter(source=Source.STRIPE, user__isnull=True)
        .select_related("user")
        .order_by("-paid_at")
    )
    no_payer_groups = _payer_groups(no_payer)

    need_members = any(not g["matched"] for g in group_list) or bool(no_payer_groups)
    submissions = list(
        LedgerSubmission.objects.filter(status=LedgerSubmission.Status.PENDING)
        .select_related("user")
    )
    _annotate_submission_warnings(submissions)
    member_actions = _recent_member_actions()
    return _treasurer_render(request, "reconcile", "payments/treasurer/reconcile.html", {
        "groups": group_list,
        "assumed_count": len(assumed),
        "assumed_total": sum((p.amount for p in assumed), Decimal("0")),
        "no_payer_groups": no_payer_groups,
        "no_payer_count": len(no_payer),
        "no_payer_total": sum((p.amount for p in no_payer), Decimal("0")),
        "type_choices": Payment.Type.choices,
        "member_options": _reconcile_member_options() if need_members else [],
        "charge_conflicts": _charge_conflicts(),
        "submissions": submissions,
        "member_actions": member_actions,
        "member_actions_days": MEMBER_ACTION_WINDOW_DAYS,
    })


#: How far back the "member-changed payments" review queue looks. Members have
#: full statement parity on their own payments (task #439); this is the
#: treasurer's passive review window over those changes (task #443).
MEMBER_ACTION_WINDOW_DAYS = 30


def _member_actions_since():
    from datetime import timedelta

    from django.utils import timezone as _tz
    return _tz.now() - timedelta(days=MEMBER_ACTION_WINDOW_DAYS)


def _recent_member_actions() -> list:
    """Member self-service statement actions inside the review window, newest
    first — one flat list, each with its payment + member preloaded."""
    return list(
        PaymentMemberAction.objects
        .filter(created_at__gte=_member_actions_since())
        .select_related("payment", "user")
    )


def _payer_groups(payments) -> list[dict]:
    """Group payments by payer — member if linked, else email, else the payer
    name parsed from the import note, else the charge alone — with a preselected
    current type and newest-charge-first ordering. Shared by the Reconcile
    (assumed) and No-payer (Stripe/unlinked) sections."""
    groups: dict = {}
    for p in payments:
        if p.user_id:
            key, who, matched = f"user:{p.user_id}", (
                p.user.get_full_name() or p.user.email), True
        else:
            name = _payer_name_from_notes(p)
            if p.email:
                key = f"email:{p.email.lower()}"
            elif name:
                key = f"name:{name.lower()}"
            else:
                key = f"pmt:{p.pk}"
            who = name or p.email or "unknown payer"
            matched = False
        g = groups.setdefault(key, {
            "key": key, "who": who, "matched": matched, "email": p.email or "",
            "payer_name": _payer_name_from_notes(p),
            "payments": [], "total": Decimal("0"), "types": set(),
            "type_counts": Counter(),
        })
        g["payments"].append(p)
        g["total"] += p.amount
        g["types"].add(p.get_payment_type_display())
        g["type_counts"][p.payment_type] += 1
    for g in groups.values():
        g["current_type"] = g["type_counts"].most_common(1)[0][0]
        g["latest"] = max((p.paid_at for p in g["payments"] if p.paid_at),
                          default=None)
    return sorted(
        groups.values(),
        key=lambda g: g["latest"].timestamp() if g["latest"] else 0.0,
        reverse=True,
    )


def _set_payer_name(notes: str, name: str) -> str:
    """Rewrite (or append) the ``(unmatched payer: …)`` note segment to ``name``."""
    import re
    notes = notes or ""
    if re.search(r"\(unmatched payer:[^)]*\)", notes):
        return re.sub(r"\(unmatched payer:[^)]*\)", f"(unmatched payer: {name})", notes)
    return (notes + f" (unmatched payer: {name})").strip()


def _no_payer_apply(request):
    """Resolve a subset of the No-payer queue (``source=STRIPE`` + no member):
    link to a member, keep as a named payer, or mark an anonymous donation.
    Every resolution promotes ``source`` to ``VERIFIED`` (treasurer-reviewed),
    which is what removes the charge from the queue. Constrained to the queue so
    a stale/forged id can't touch a confirmed row."""
    from accounts.models import Source

    ids = request.POST.getlist("payment_ids")
    action = request.POST.get("action") or "save"
    if not ids:
        messages.error(request, "Select at least one charge.")
        return redirect("treasurer_reconcile")

    qs = Payment.objects.filter(source=Source.STRIPE, user__isnull=True, pk__in=ids)
    n = qs.count()
    if not n:
        messages.error(request, "Those charges were already resolved.")
        return redirect("treasurer_reconcile")

    if action == "anonymous":
        qs.update(payment_type=Payment.Type.DONATION, source=Source.VERIFIED)
        messages.success(request, f"Marked {n} charge(s) as anonymous donation(s).")
        return redirect("treasurer_reconcile")

    new_type = request.POST.get("payment_type")
    if new_type not in Payment.Type.values:
        messages.error(request, "Choose a valid category.")
        return redirect("treasurer_reconcile")

    assign = (request.POST.get("assign_user") or "").strip()
    if assign:
        user = _resolve_assign_user(assign)
        if user is None:
            messages.error(request, f"No member found for '{assign}'.")
            return redirect("treasurer_reconcile")
        qs.update(payment_type=new_type, user=user, source=Source.VERIFIED)
        messages.success(request, f"Linked {n} charge(s) to {user.email} as {new_type}.")
        return redirect("treasurer_reconcile")

    # Named (or unchanged) non-member payer.
    payer_name = (request.POST.get("payer_name") or "").strip()
    rows = list(qs)
    for p in rows:
        p.payment_type = new_type
        p.source = Source.VERIFIED
        if payer_name:
            p.notes = _set_payer_name(p.notes, payer_name)
    Payment.objects.bulk_update(rows, ["payment_type", "source", "notes"])
    who = f" for {payer_name}" if payer_name else ""
    messages.success(request, f"Saved {n} charge(s){who} as {new_type}.")
    return redirect("treasurer_reconcile")


def _payer_name_from_notes(payment) -> str:
    import re
    m = re.search(r"unmatched payer:\s*([^)]+)\)", payment.notes or "")
    return m.group(1).strip() if m else ""


def _reconcile_member_options() -> list[dict]:
    """Members offered in the "Link to member" autocomplete, as
    ``{"value": "Full Name (email)"}`` — the value carries both so typing
    either a name or an address filters the datalist; the apply view parses
    the email back out. Personas and inactive accounts are excluded."""
    members = (
        User.objects.filter(is_active=True)
        .exclude(profile__is_persona=True)
        .select_related("profile")
        .order_by("first_name", "last_name", "email")
    )
    return [{"value": f"{m.profile.display_full_name} ({m.email})"} for m in members]


def _resolve_assign_user(assign: str):
    """Resolve the "Link to member" field to a User. Accepts a raw email, a
    numeric id, or a ``Name (email)`` autocomplete value (email extracted)."""
    import re
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", assign)
    lookup = m.group(0) if m else assign
    return (
        User.objects.filter(email__iexact=lookup).first()
        or (User.objects.filter(pk=lookup).first() if lookup.isdigit() else None)
    )


def _reconcile_apply(request):
    """Re-type (and optionally link) a *selected subset* of ASSUMED payments.
    Unselected payments stay assumed and reappear on the next load."""
    from accounts.models import Source

    ids = request.POST.getlist("payment_ids")
    new_type = request.POST.get("payment_type")
    assign = (request.POST.get("assign_user") or "").strip()

    if not ids:
        messages.error(request, "Select at least one payment to reconcile.")
        return redirect("treasurer_reconcile")
    if new_type not in Payment.Type.values:
        messages.error(request, "Choose a valid type.")
        return redirect("treasurer_reconcile")

    # Constrained to ASSUMED so a stale/forged id can't touch a confirmed row.
    qs = Payment.objects.filter(source=Source.ASSUMED, pk__in=ids)

    assigned_user = None
    if assign:
        assigned_user = _resolve_assign_user(assign)
        if assigned_user is None:
            messages.error(request, f"No member found for '{assign}'.")
            return redirect("treasurer_reconcile")

    fields = {"payment_type": new_type, "source": Source.STAFF}
    if assigned_user is not None:
        fields["user"] = assigned_user
    n = qs.count()
    qs.update(**fields)
    if not n:
        messages.error(request, "Those payments were already reconciled.")
        return redirect("treasurer_reconcile")
    note = f"→ {new_type}" + (f", linked {assigned_user.email}" if assigned_user else "")
    messages.success(request, f"Reconciled {n} payment(s) {note}.")
    return redirect("treasurer_reconcile")


def _annotate_submission_warnings(submissions) -> None:
    """Soft advisory badges for the Reconcile tab's Member submissions queue
    (task #439 review finding #4a), set as ``.warnings`` (a list of strings)
    on each submission in place.

    Two heuristics, both advisory only — nothing here blocks approve/decline,
    it just flags what's worth a second look before clicking:

    - **Possible duplicate** — another PENDING submission by the same member
      with an identical (kind, category, amount, claimed_date). Members
      sometimes re-submit a report they think didn't go through.
    - **No matching charge on file** — a *payment* claim in dues/tuition
      whose claimed date falls in an AY window with no non-void charge for
      that member/category/period. Approving still mints the payment (per
      spec, the treasurer's call) but it will simply sit as a credit on the
      balance rather than covering anything, unless the matching charge is
      also on file (or approved from a companion charge claim).

    Computed over the queue's already-small PENDING batch — no more than one
    query per payment-claim row for the charge check."""
    from collections import Counter

    def _key(s):
        return (s.user_id, s.kind, s.category, s.amount, s.claimed_date)

    counts = Counter(_key(s) for s in submissions)
    for s in submissions:
        warnings = []
        if counts[_key(s)] > 1:
            warnings.append(
                "Possible duplicate claim — another pending submission from "
                "this member looks identical.")
        if (s.kind == LedgerSubmission.Kind.PAYMENT
                and s.category in (Payment.Type.DUES, Payment.Type.TUITION)):
            period = _strict_period_for(s.category, s.claimed_date)
            has_charge = False
            if period is not None:
                fk = ("dues_period" if s.category == Payment.Type.DUES
                      else "tuition_period")
                has_charge = Charge.objects.filter(
                    user=s.user, category=s.category, **{fk: period},
                ).exclude(status=Charge.Status.VOID).exists()
            if not has_charge:
                warnings.append(
                    "No matching charge on file for this window — "
                    "approving credits the balance directly rather than "
                    "covering a fee.")
        s.warnings = warnings


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_submission_decide(request, submission_id: int):
    """Approve or decline a member's history-submission claim (Reconcile
    tab's Member submissions queue, task #439 §3).

    Approve mints the matching Payment/Charge exactly per spec: a payment
    is dated ``claimed_date`` at noon UTC and bound to the covering dues/
    tuition period; a charge is OPEN + ``staff_adjusted`` (so the minting
    syncs never touch it) with its dues/tuition period FK bound — the syncs
    key idempotency on (user, period), so a period-less charge would get
    double-minted by the next rollover/enrollment sync (see
    ``treasurer_charge_add``). Both carry ``source=SELF_REPORTED`` — the
    member's own say-so, honor-system era — and a note naming the
    submission and the deciding treasurer. Decline just records the note;
    nothing is minted. Idempotent AND race-safe: the row is fetched under
    ``select_for_update`` (mirroring the Stripe-webhook pattern), so a
    double-submitted decide sees the already-decided status and no-ops.
    """
    from datetime import timezone as dt_timezone

    from accounts.models import Source

    decision = request.POST.get("decision")
    if decision not in ("approve", "decline"):
        messages.error(request, "Choose approve or decline.")
        return redirect("treasurer_reconcile")
    note = (request.POST.get("note") or "").strip()[:2000]

    with transaction.atomic():
        submission = get_object_or_404(
            LedgerSubmission.objects.select_for_update(), pk=submission_id)
        if submission.status != LedgerSubmission.Status.PENDING:
            messages.error(request, "That submission was already decided.")
            return redirect("treasurer_reconcile")

        header = (f"Member-reported history (submission #{submission.id}), "
                  f"approved by treasurer {request.user.email}.")
        mint_note = header + (
            f"\n{submission.details}" if submission.details else "")

        if decision == "approve":
            if submission.kind == LedgerSubmission.Kind.PAYMENT:
                kwargs = {}
                if submission.category == Payment.Type.DUES:
                    kwargs["dues_period"] = _strict_period_for(
                        Payment.Type.DUES, submission.claimed_date)
                elif submission.category == Payment.Type.TUITION:
                    kwargs["tuition_period"] = _strict_period_for(
                        Payment.Type.TUITION, submission.claimed_date)
                paid_at = datetime(
                    submission.claimed_date.year, submission.claimed_date.month,
                    submission.claimed_date.day, 12, 0, tzinfo=dt_timezone.utc,
                )
                payment = Payment.objects.create(
                    payment_type=submission.category, user=submission.user,
                    amount=submission.amount, status=Payment.Status.SUCCEEDED,
                    method=Payment.Method.OFFLINE, source=Source.SELF_REPORTED,
                    paid_at=paid_at, notes=mint_note, **kwargs,
                )
                submission.created_payment = payment
            else:
                # Defense in depth — the member form now refuses these too.
                if submission.category not in Charge.Category.values:
                    messages.error(
                        request,
                        f"'{submission.category}' isn't a valid charge "
                        "category — decline this submission or ask the "
                        "member to re-submit it as a payment instead.",
                    )
                    return redirect("treasurer_reconcile")
                # Bind the AY period for dues/tuition — the minting syncs key
                # idempotency on (user, period); a period-less charge would
                # get double-minted by the next sync. Mirrors
                # treasurer_charge_add, incl. the duplicate-charge guard.
                period_kwargs = {}
                eff = submission.claimed_date
                period = _strict_period_for(
                    submission.category, submission.claimed_date)
                if period is not None:
                    fk = ("dues_period"
                          if submission.category == Charge.Category.DUES
                          else "tuition_period")
                    dup = Charge.objects.filter(
                        user=submission.user, category=submission.category,
                        **{fk: period},
                    ).exclude(status=Charge.Status.VOID).exists()
                    if dup:
                        messages.error(
                            request,
                            f"A {submission.category} charge for "
                            f"{period.name} already exists on this account "
                            "— adjust the existing charge instead, then "
                            "decline this submission with a note.",
                        )
                        return redirect("treasurer_reconcile")
                    period_kwargs[fk] = period
                    eff = period.start_date
                charge = Charge.objects.create(
                    user=submission.user, category=submission.category,
                    amount=submission.amount,
                    effective_date=eff,
                    status=Charge.Status.OPEN, source=Source.SELF_REPORTED,
                    staff_adjusted=True, notes=mint_note, **period_kwargs,
                )
                submission.created_charge = charge
            submission.status = LedgerSubmission.Status.APPROVED
        else:
            submission.status = LedgerSubmission.Status.DECLINED
        submission.decision_note = note
        submission.decided_by = request.user
        submission.decided_at = timezone.now()
        submission.save()

    from . import notifications as _payment_notifications
    _payment_notifications.ledger_submission_decided(submission)

    messages.success(
        request,
        f"Submission #{submission.id} {submission.get_status_display().lower()}.")
    return redirect("treasurer_reconcile")


def _safe_next(request, fallback: str):
    """Honor a validated ?next= so member-page forms return there."""
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback)


def _parse_amount(raw: str) -> Decimal | None:
    """A positive money amount that fits the payment fields
    (max_digits=8, decimal_places=2), or None."""
    from decimal import InvalidOperation
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        return None
    if not amount.is_finite() or amount <= 0 or amount > Decimal("999999.99"):
        return None
    if amount != amount.quantize(Decimal("0.01")):
        return None  # more than 2 decimal places
    return amount


@login_required
@user_passes_test(_is_staff)
def treasurer_member_detail(request, user_id: int):
    """Per-member account: statement, balance tiles, actions (task #439)."""
    from payments import ledger
    from payments.models import Charge
    from registrations.models import Registration

    target = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    acct = ledger.member_account(target)
    _attach_split_info(
        [ln["obj"] for ln in acct["lines"] if ln["kind"] == "payment"])
    registrations = list(
        Registration.objects.filter(user=target)
        .select_related("event", "price_tier")
        .order_by("-created_at")
    )
    current_dues = DuesPeriod.current()
    current_tuition = TuitionPeriod.current()
    return _treasurer_render(
        request, "accounts", "payments/treasurer/member_detail.html",
        {
            "target": target,
            "acct": acct,
            "registrations": registrations,
            "charge_categories": Charge.Category.choices,
            "payment_categories": Payment.Type.choices,
            "member_options": _reconcile_member_options(),
            "unenrolled_tuition_periods": TuitionPeriod.objects.exclude(
                enrollments__user=target),
            "today": timezone.now().date(),
            "dues_periods": DuesPeriod.objects.all(),  # newest first (Meta.ordering)
            "tuition_periods": TuitionPeriod.objects.all(),
            "current_dues_period_id": current_dues.id if current_dues else None,
            "current_tuition_period_id": current_tuition.id if current_tuition else None,
        },
    )


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_charge_add(request, user_id: int):
    """Manually add a charge to a member's account (do-not-over-automate).

    Dues/tuition charges must bind their period FK — the minting syncs
    (``sync_dues_charges`` / ``sync_tuition_charges``) key idempotency on
    (user, period), so a period-less manual charge would get double-minted
    by the next rollover/Sync click.
    """
    from accounts.models import Source

    from .models import Charge

    target = get_object_or_404(User, pk=user_id)
    category = request.POST.get("category")
    if category not in Charge.Category.values:
        messages.error(request, "Choose a valid category.")
        return redirect("treasurer_member_detail", user_id=target.id)
    amount = _parse_amount(request.POST.get("amount", ""))
    if amount is None:
        messages.error(request, "Enter a positive amount.")
        return redirect("treasurer_member_detail", user_id=target.id)

    period_kwargs = {}
    eff = None
    if category == Charge.Category.DUES:
        period = _resolve_period(
            request.POST.get("dues_period"), DuesPeriod, DuesPeriod.current())
        if period is not None:
            dup = Charge.objects.filter(
                user=target, category=Charge.Category.DUES, dues_period=period,
            ).exclude(status=Charge.Status.VOID).exists()
            if dup:
                messages.error(
                    request,
                    f"A dues charge for {period.name} already exists on this "
                    "account — adjust the existing charge instead.",
                )
                return redirect("treasurer_member_detail", user_id=target.id)
            period_kwargs["dues_period"] = period
            eff = period.start_date
    elif category == Charge.Category.TUITION:
        period = _resolve_period(
            request.POST.get("tuition_period"), TuitionPeriod, TuitionPeriod.current())
        if period is not None:
            dup = Charge.objects.filter(
                user=target, category=Charge.Category.TUITION, tuition_period=period,
            ).exclude(status=Charge.Status.VOID).exists()
            if dup:
                messages.error(
                    request,
                    f"A tuition charge for {period.name} already exists on "
                    "this account — adjust the existing charge instead.",
                )
                return redirect("treasurer_member_detail", user_id=target.id)
            period_kwargs["tuition_period"] = period
            eff = period.start_date

    if eff is None:
        try:
            eff = date.fromisoformat(request.POST.get("effective_date", ""))
        except ValueError:
            eff = timezone.now().date()
    note = (request.POST.get("note") or "").strip()
    charge = Charge.objects.create(
        user=target, category=category, amount=amount, effective_date=eff,
        source=Source.STAFF, staff_adjusted=True, **period_kwargs,
    )
    charge.add_note(
        f"Added by treasurer {request.user.email}." + (f" {note}" if note else ""))
    messages.success(request, f"Added a ${amount} {category} charge.")
    return redirect("treasurer_member_detail", user_id=target.id)


def _resolve_period(posted_id, model, fallback):
    """Resolve a posted period id against ``model``, falling back to
    ``fallback`` (typically ``Model.current()``) when unposted/invalid."""
    if posted_id:
        try:
            return model.objects.filter(pk=posted_id).first() or fallback
        except (TypeError, ValueError):
            return fallback
    return fallback


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_charge_update(request, charge_id: int):
    """Adjust / waive / void / reopen one charge, with an audit note.

    Status gating (task #439 fix 4b): adjust/waive only from OPEN, void from
    OPEN or WAIVED, reopen only from WAIVED. Reopening a VOID charge is
    deliberately not offered here — it risks colliding with the partial
    unique constraint on (user, dues_period)/(user, tuition_period) if a
    sync has since minted a fresh row for that period; use *Add a charge*
    instead.
    """
    from .models import Charge

    charge = get_object_or_404(Charge, pk=charge_id)
    action = request.POST.get("action")
    email = request.user.email
    if action == "adjust":
        if charge.status != Charge.Status.OPEN:
            messages.error(request, "Only an open charge can be adjusted.")
            return redirect("treasurer_member_detail", user_id=charge.user_id)
        amount = _parse_amount(request.POST.get("amount", ""))
        if amount is None:
            messages.error(request, "Enter a positive amount.")
            return redirect("treasurer_member_detail", user_id=charge.user_id)
        charge.add_note(f"Amount ${charge.amount} → ${amount} by treasurer {email}.",
                        save=False)
        charge.amount = amount
    elif action == "waive":
        if charge.status != Charge.Status.OPEN:
            messages.error(request, "Only an open charge can be waived.")
            return redirect("treasurer_member_detail", user_id=charge.user_id)
        charge.add_note(f"Waived by treasurer {email}.", save=False)
        charge.status = Charge.Status.WAIVED
    elif action == "void":
        if charge.status not in (Charge.Status.OPEN, Charge.Status.WAIVED):
            messages.error(request, "Only an open or waived charge can be voided.")
            return redirect("treasurer_member_detail", user_id=charge.user_id)
        charge.add_note(f"Voided by treasurer {email}.", save=False)
        charge.status = Charge.Status.VOID
    elif action == "reopen":
        if charge.status != Charge.Status.WAIVED:
            messages.error(request, "Only a waived charge can be reopened.")
            return redirect("treasurer_member_detail", user_id=charge.user_id)
        charge.add_note(f"Reopened by treasurer {email}.", save=False)
        charge.status = Charge.Status.OPEN
    else:
        messages.error(request, "Unknown action.")
        return redirect("treasurer_member_detail", user_id=charge.user_id)
    charge.staff_adjusted = True
    charge.save(update_fields=("amount", "status", "staff_adjusted", "notes"))
    return redirect("treasurer_member_detail", user_id=charge.user_id)


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_record_payment(request, user_id: int):
    """Record an offline payment of any category (replaces the per-category
    record buttons). Tuition keeps the enrollment+installment side-effects."""
    target = get_object_or_404(User, pk=user_id)
    category = request.POST.get("category")
    if category not in Payment.Type.values:
        messages.error(request, "Choose a valid category.")
        return redirect("treasurer_member_detail", user_id=target.id)
    amount = _parse_amount(request.POST.get("amount", ""))
    if amount is None:
        messages.error(request, "Enter a positive amount.")
        return redirect("treasurer_member_detail", user_id=target.id)

    note = (f"Offline {category} payment recorded by treasurer "
            f"{request.user.email} on {timezone.now().date()}.")
    with transaction.atomic():
        kwargs = {}
        if category == Payment.Type.TUITION:
            period = TuitionPeriod.current()
            if period is not None:
                prior = TuitionEnrollment.objects.filter(
                    user=target, tuition_period=period,
                ).first()
                prior_status = prior.status if prior else None
                full_amount = amount >= period.tuition_amount
                if full_amount:
                    enr, created = TuitionEnrollment.objects.update_or_create(
                        user=target, tuition_period=period,
                        defaults={"status": TuitionEnrollment.Status.COMMITTED})
                    if created or prior_status != enr.status:
                        # Audit the status flip — update_or_create can
                        # silently overwrite an explicit decision (e.g.
                        # Skipping).
                        was = (
                            f" (was {TuitionEnrollment.Status(prior_status).label})"
                            if prior_status else ""
                        )
                        enr.notes = (
                            (enr.notes + "\n" if enr.notes else "")
                            + f"[{timezone.now().date()}] Treasurer "
                            f"({request.user.email}) set status to Committed "
                            f"while recording an offline tuition payment{was}."
                        )
                        enr.save(update_fields=("notes",))
                    installment = TuitionInstallment.objects.create(
                        enrollment=enr, sequence=enr.installments.count() + 1,
                        due_date=period.decision_due_date, amount=amount)
                    kwargs["tuition_installment"] = installment
                else:
                    # A partial payment stands alone — it must not flip the
                    # enrollment to PAID_IN_FULL (that mislabels the
                    # decision record and grants covered-tier event access
                    # via Gate 2). No installment is created; leave the
                    # enrollment at its existing status (COMMITTED if this
                    # is the first decision on record).
                    if prior is None:
                        enr = TuitionEnrollment.objects.create(
                            user=target, tuition_period=period,
                            status=TuitionEnrollment.Status.COMMITTED)
                    else:
                        enr = prior
                    enr.notes = (
                        (enr.notes + "\n" if enr.notes else "")
                        + f"[{timezone.now().date()}] Treasurer "
                        f"({request.user.email}) recorded a partial offline "
                        f"tuition payment of ${amount}; year not marked paid "
                        "in full."
                    )
                    enr.save(update_fields=("notes",))
        elif category == Payment.Type.DUES:
            kwargs["dues_period"] = DuesPeriod.current()
        payment = Payment.objects.create(
            payment_type=category, user=target, amount=amount,
            method=Payment.Method.OFFLINE, status=Payment.Status.PENDING,
            notes=note, **kwargs)
    complete_payment(payment)
    messages.success(request, f"Recorded a ${amount} offline {category} payment.")
    return redirect("treasurer_member_detail", user_id=target.id)


@login_required
@user_passes_test(_is_staff)
def treasurer_exports(request):
    """Exports tab — CSV downloads grouped and described for non-technical staff."""
    return _treasurer_render(request, "exports", "payments/treasurer/exports.html", {})


@login_required
@user_passes_test(_is_staff)
def treasurer_help(request):
    """Help tab — renders the treasurer guide markdown doc."""
    from core.docs import render_doc
    return _treasurer_render(request, "help", "payments/treasurer/help.html", {
        "rendered_html": render_doc("treasurer-guide"),
    })


@login_required
@user_passes_test(_is_staff)
def treasurer_payments(request):
    """Payments tab — list of payments with filters + per-row actions."""
    payment_type = request.GET.get("type") or ""
    status = request.GET.get("status") or ""

    qs = Payment.objects.select_related(
        "user", "registration__event", "tuition_period",
    ).order_by(Coalesce("paid_at", "created_at").desc())  # transaction date, task #437
    if payment_type:
        qs = qs.filter(payment_type=payment_type)
    if status:
        qs = qs.filter(status=status)

    from accounts.models import Source

    page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))
    # Preserve the active filters across page links.
    filter_qs = urlencode({k: v for k, v in (
        ("type", payment_type), ("status", status)) if v})
    # Flag whether any row on this page is a provisional (assumed) type, so the
    # asterisk legend only shows when there's an asterisk to explain.
    has_assumed = any(p.source == Source.ASSUMED for p in page_obj)

    _attach_split_info(list(page_obj))
    # Payer column: the member's name when linked; otherwise whatever the
    # Stripe import knew — the parsed payer name, falling back to the
    # payment's own email. Never just "anonymous".
    for p in page_obj:
        if p.user_id:
            p.payer_label = (p.user.get_full_name() or "").strip() or p.user.email
            p.payer_detail = ""
        else:
            name = _payer_name_from_notes(p)
            p.payer_label = name or p.email or "unknown payer"
            p.payer_detail = p.email if (name and p.email) else ""

    return _treasurer_render(request, "payments", "payments/treasurer/payments.html", {
        "payments":           page_obj,
        "page_obj":           page_obj,
        "filter_qs":          filter_qs,
        "has_assumed":        has_assumed,
        "assumed_source":     Source.ASSUMED,
        "type_choices":       Payment.Type.choices,
        "status_choices":     Payment.Status.choices,
        "selected_type":      payment_type,
        "selected_status":    status,
        "total_count":        page_obj.paginator.count,
        "dues_periods":       DuesPeriod.objects.all(),  # newest first (Meta.ordering)
        "tuition_periods":    TuitionPeriod.objects.all(),
        "member_options":     _reconcile_member_options(),
    })


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_note(request, payment_id: int):
    """Append a treasurer note to a payment (staff-only; members never see
    Payment.notes — their own channel is member_note)."""
    payment = get_object_or_404(Payment, pk=payment_id)
    note = (request.POST.get("note") or "").strip()[:2000]
    if not note:
        messages.error(request, "Write a note first.")
        return _safe_next(request, "treasurer_payments")
    line = (f"[{timezone.now().date()}] Note by treasurer "
            f"{request.user.email}: {note}")
    payment.notes = (payment.notes + "\n" + line) if payment.notes else line
    payment.save(update_fields=("notes",))
    messages.success(request, "Note added.")
    return _safe_next(request, "treasurer_payments")


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_charge_note(request, charge_id: int):
    """Append a treasurer note to a charge. Deliberately does NOT set
    staff_adjusted — a comment must not freeze the row against the sync."""
    charge = get_object_or_404(Charge, pk=charge_id)
    note = (request.POST.get("note") or "").strip()[:2000]
    if not note:
        messages.error(request, "Write a note first.")
        return _safe_next(request, "treasurer_payments")
    charge.add_note(f"Note by treasurer {request.user.email}: {note}")
    messages.success(request, "Note added.")
    return _safe_next(request, "treasurer_payments")


@require_POST
def treasurer_suspend_access(request, user_id: int):
    """Suspend/restore a member's seminar-group access (task #450 phase D).

    A human, audited treasurer action only — nothing automatic ever sets
    ``Profile.seminar_access_suspended`` (do-not-over-automate). While set,
    the member drops out of the *registrant-derived* portion of every
    seminar/reading-group Workgroup roster (``Event.has_access_registrant`` /
    ``access_registrant_users``) — faculty standing is untouched. Gated like
    ``payments.views_plan_review`` (``core.access.gate_or_login``): anonymous
    → login redirect, signed-in non-treasurer → 404, so the endpoint doesn't
    reveal member ids to outsiders.
    """
    from core.access import gate_or_login

    if not _is_staff(request.user):
        return gate_or_login(request)

    target = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    action = request.POST.get("action")
    reason = (request.POST.get("reason") or "").strip()
    if action not in ("suspend", "restore"):
        messages.error(request, "Unknown action.")
        return redirect("treasurer_member_detail", user_id=target.id)
    if not reason:
        messages.error(request, "Give a short reason first.")
        return redirect("treasurer_member_detail", user_id=target.id)

    profile = target.profile
    email = request.user.email
    if action == "suspend":
        profile.seminar_access_suspended = True
        profile.add_note(f"Suspended by treasurer {email}. {reason}", save=False)
        messages.success(request, "Seminar group access suspended.")
    else:
        profile.seminar_access_suspended = False
        profile.add_note(f"Restored by treasurer {email}. {reason}", save=False)
        messages.success(request, "Seminar group access restored.")
    profile.save(update_fields=("seminar_access_suspended", "notes"))
    return redirect("treasurer_member_detail", user_id=target.id)


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_split(request, payment_id: int):
    """Split one payment into sibling rows with different categories.

    The parent row keeps its identity (Stripe ids, receipt) with its amount
    reduced to the first part; siblings copy date/method/member/email. The
    part amounts must sum exactly to the original. Registration parts can
    mint a matching settlement charge (honor-system event fees). Refunding
    any part later refunds the entire original charge — see
    ``treasurer_payment_refund``.
    """
    from accounts.models import Source

    payment = get_object_or_404(Payment, pk=payment_id)
    if payment.status != Payment.Status.SUCCEEDED:
        messages.error(request, "Only succeeded payments can be split.")
        return _safe_next(request, "treasurer_payments")
    if payment.registration_id:
        messages.error(
            request,
            "This payment settles an event registration and cannot be split.")
        return _safe_next(request, "treasurer_payments")
    if payment.user_id is None:
        messages.error(
            request,
            "This payment has no member attached. Link it to a member on "
            "the Reconcile tab first.")
        return _safe_next(request, "treasurer_payments")
    if payment.split_from_id or payment.split_parts.exists():
        messages.error(request, "This payment is already part of a split.")
        return _safe_next(request, "treasurer_payments")

    types = request.POST.getlist("part_type")
    amounts = request.POST.getlist("part_amount")
    settle_rows = set(request.POST.getlist("part_settle"))
    parts = []
    for i, (t, raw) in enumerate(zip(types, amounts)):
        if not (raw or "").strip():
            continue  # empty extra row in the form
        amount = _parse_amount(raw)
        if t not in Payment.Type.values or amount is None:
            messages.error(
                request, "Each part needs a valid category and amount.")
            return _safe_next(request, "treasurer_payments")
        settle = str(i) in settle_rows and t == Payment.Type.REGISTRATION
        parts.append((t, amount, settle))
    if len(parts) < 2:
        messages.error(request, "A split needs at least two parts.")
        return _safe_next(request, "treasurer_payments")
    if sum((a for _, a, _ in parts), Decimal("0")) != payment.amount:
        messages.error(
            request, f"The parts must add up to exactly ${payment.amount}.")
        return _safe_next(request, "treasurer_payments")

    labels = dict(Payment.Type.choices)
    old_type, old_amount = payment.payment_type, payment.amount
    when = (payment.paid_at or payment.created_at).date()
    today = timezone.now().date()
    breakdown = ", ".join(f"${a} {labels[t]}" for t, a, _ in parts)
    extra_flash = ""
    with transaction.atomic():
        first_type, first_amount, first_settle = parts[0]
        details = []
        # A split always unlinks a tuition installment — the single-installment
        # linkage no longer describes the (now divided) money — and unwinds it
        # if nothing else backs it. This runs regardless of the first part's
        # category (a same-category first part would otherwise keep the full
        # installment marked paid against a reduced amount).
        if payment.tuition_installment_id:
            details.append(
                f"unlinked installment #{payment.tuition_installment_id}")
            _installment = payment.tuition_installment
            payment.tuition_installment = None
            extra_flash += _unwind_installment(
                payment, _installment, treasurer_email=request.user.email,
                cause="split across categories")
        if first_type != old_type:
            _details, _extra = _apply_category_change(
                payment, first_type, treasurer_email=request.user.email)
            details += _details
            extra_flash += _extra
        payment.amount = first_amount
        payment.source = Source.VERIFIED
        audit = (f"[{today}] Split ${old_amount} {labels[old_type]} into "
                 f"{breakdown} by treasurer {request.user.email}."
                 + (f" ({'; '.join(details)})" if details else ""))
        payment.notes = (
            (payment.notes + "\n" + audit) if payment.notes else audit)
        payment.save()

        settle_targets = [(payment, first_amount)] if first_settle else []
        for t, a, settle in parts[1:]:
            child = _create_split_child(
                payment, t, a, when,
                source=Source.VERIFIED,
                actor_label=f"treasurer {request.user.email}",
                original=f"${old_amount} {labels[old_type]}",
            )
            if settle:
                settle_targets.append((child, a))
        for target, amount in settle_targets:
            _mint_settlement_charge(
                payment, amount, when,
                source=Source.STAFF,
                actor_label=f"treasurer {request.user.email}",
                cause=(f"the split of payment #{payment.pk} "
                       f"(part: payment #{target.pk})"),
            )
    flash = f"Split into {breakdown}."
    if settle_targets:
        flash += " Inserted matching Registration charge(s)."
    flash += extra_flash
    messages.success(request, flash)
    return _safe_next(request, "treasurer_payments")




@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_refund(request, payment_id: int):
    """Refund a SUCCEEDED payment.

    Stripe payments: calls Stripe's refund API + marks REFUNDED. Cascade
    to the linked Registration arrives via the charge.refunded webhook.

    Offline payments: marks REFUNDED for accounting + cascades to any
    linked Registration immediately. The treasurer sends the actual
    reimbursement (cash, check, etc.) out-of-band — the page's confirm
    prompt makes that explicit.
    """
    from .refund import RefundError, refund_payment

    payment = get_object_or_404(Payment, pk=payment_id)
    if payment.status != Payment.Status.SUCCEEDED:
        return _safe_next(request, "treasurer_payments")

    # Split payments refund as a whole: the money was one charge, so
    # refunding any part refunds the entire original amount — the Stripe
    # refund goes through the parent (which holds the payment intent) and
    # every sibling row flips to REFUNDED with an audit note.
    parent = payment.split_from or payment
    family = list(parent.split_parts.all())
    family = [parent, *family] if family else None
    target = parent if family else payment

    if target.method == Payment.Method.STRIPE:
        try:
            refund_payment(target)
        except RefundError as exc:
            logger.exception("Refund failed for payment %s: %s", target.id, exc)
            return _safe_next(request, "treasurer_payments")
    else:
        _record_offline_refund(target, treasurer=request.user)
        # Cascade to Registration (the Stripe path gets this via webhook).
        if target.registration_id:
            Registration.objects.filter(
                pk=target.registration_id,
                status=Registration.Status.PAID,
            ).update(status=Registration.Status.REFUNDED)
            from .charges import void_registration_charge
            void_registration_charge(target.registration, "Offline refund recorded.")

    if family:
        audit = (
            f"[{timezone.now().date()}] Refunded as part of the entire "
            f"original split charge by treasurer {request.user.email}."
        )
        for part in family:
            if part.pk == target.pk or part.status == Payment.Status.REFUNDED:
                continue
            part.status = Payment.Status.REFUNDED
            part.notes = (part.notes + "\n" + audit) if part.notes else audit
            part.save(update_fields=("status", "notes"))
    return _safe_next(request, "treasurer_payments")


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_resend_receipt(request, payment_id: int):
    """Re-email the Receipt for a payment.

    Common when a member loses the original email or asks for a copy.
    No-op if the payment doesn't have a Receipt (yet) — e.g. PENDING
    payments haven't been completed and have no Receipt to send.
    """
    from .emails import send_receipt
    payment = get_object_or_404(Payment, pk=payment_id)
    if payment.split_from_id or payment.split_parts.exists():
        messages.error(
            request,
            "This payment was split, so the original receipt no longer "
            "matches its parts. Send the member corrected details manually.",
        )
        return _safe_next(request, "treasurer_payments")
    if not hasattr(payment, "receipt"):
        return _safe_next(request, "treasurer_payments")
    try:
        send_receipt(payment)
    except Exception:
        logger.exception("Failed to resend receipt for payment %s", payment.id)
    return _safe_next(request, "treasurer_payments")


def _record_offline_refund(payment: Payment, *, treasurer) -> None:
    """Mark an offline payment REFUNDED with an audit note. No money moves —
    the treasurer handles reimbursement manually."""
    payment.status = Payment.Status.REFUNDED
    audit = (
        f"[{timezone.now().date()}] Offline refund recorded by treasurer "
        f"{treasurer.email} (for accounting; reimbursement sent separately)."
    )
    payment.notes = (payment.notes + "\n" + audit) if payment.notes else audit
    payment.save(update_fields=("status", "notes"))


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_apply_success(request, payment_id: int):
    """Apply success-side-effects for a PENDING offline Payment.

    Mirrors the "Apply payment success" admin action, in-treasurer.
    """
    payment = get_object_or_404(Payment, pk=payment_id)
    if payment.status == Payment.Status.PENDING:
        complete_payment(payment)
    return _safe_next(request, "treasurer_payments")


def _int_or_none(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _mint_settlement_charge(payment, amount, when, *, source, actor_label,
                            cause):
    """Insert the honor-system-era settlement Charge that pairs with a
    payment re-categorized (or split) into Registration — the original event
    fee was never recorded, so the pair nets to zero exactly where it sits in
    the statement. Shared by the treasurer and member retype/split paths
    (task #439): ``source``/``actor_label`` carry each side's provenance and
    attribution ("treasurer x@y" vs "member x@y"); ``cause`` is the
    mid-sentence description ("re-categorization of payment #N" / "the split
    of payment #N (part: payment #M)")."""
    return Charge.objects.create(
        user_id=payment.user_id,
        category=Charge.Category.REGISTRATION,
        amount=amount,
        effective_date=when,
        source=source,
        staff_adjusted=True,
        notes=(f"[{timezone.now().date()}] Settlement charge inserted with "
               f"{cause} by {actor_label} — the original event fee was "
               "never recorded."),
    )


def _settle_registration_charge_only(request, payment, *, source, actor_label,
                                     redirect_url, member_log=False):
    """Insert the matching settlement Charge for a payment that is *already*
    categorized as Registration, without changing its category (task #468
    follow-up). Same honor-system rationale as the re-categorize-and-settle
    path — it just spares the re-categorize-away-and-back dance when the
    category is already right. Shared by the treasurer and member statement
    actions: ``source``/``actor_label`` carry each side's provenance and
    attribution; ``member_log`` records a member statement action for the
    treasurer's Reconcile queue."""
    if payment.registration_id:
        messages.error(
            request,
            "This payment settles an event registration, which already has "
            "its charge. Use the refund or comp flows instead.",
        )
        return _safe_next(request, redirect_url)
    if payment.user_id is None:
        messages.error(
            request,
            "This payment has no member attached. Link it to a member on the "
            "Reconcile tab first.",
        )
        return _safe_next(request, redirect_url)

    with transaction.atomic():
        when = (payment.paid_at or payment.created_at).date()
        _mint_settlement_charge(
            payment, payment.amount, when,
            source=source, actor_label=actor_label,
            cause=f"payment #{payment.pk}",
        )
        audit = (f"[{timezone.now().date()}] Inserted a matching Registration "
                 f"charge by {actor_label}.")
        payment.notes = (
            (payment.notes + "\n" + audit) if payment.notes else audit)
        payment.save(update_fields=["notes"])
        if member_log:
            _log_member_action(
                payment, request.user, PaymentMemberAction.Action.RETYPE,
                "inserted matching Registration charge")
    messages.success(
        request,
        "Inserted a matching Registration charge dated with the payment.")
    return _safe_next(request, redirect_url)


def _create_split_child(parent, part_type, amount, when, *, source,
                        actor_label, original):
    """Create one sibling Payment row of a split: copies method/email/
    currency/livemode/paid_at off the (already-mutated) parent, binds the
    part's AY period via ``_period_for``, and records the audit note. Shared
    by the treasurer and member split paths (task #439); ``original``
    describes the pre-split row ("$400 Tuition") and ``actor_label`` the
    actor ("treasurer x@y" vs "member x@y")."""
    return Payment.objects.create(
        user_id=parent.user_id,
        payment_type=part_type,
        amount=amount,
        status=Payment.Status.SUCCEEDED,
        method=parent.method,
        email=parent.email,
        currency=parent.currency,
        livemode=parent.livemode,
        source=source,
        split_from=parent,
        paid_at=parent.paid_at,
        dues_period=(_period_for(part_type, when)
                     if part_type == Payment.Type.DUES else None),
        tuition_period=(_period_for(part_type, when)
                        if part_type == Payment.Type.TUITION else None),
        notes=(f"[{timezone.now().date()}] Split from payment #{parent.pk} "
               f"({original}) by {actor_label}; the original receipt covers "
               "the full amount."),
    )


def _period_for(new_type, when):
    """The AY period containing ``when`` for a dues/tuition category, falling
    back to the current one. None for other categories.

    NOT for binding a raw member-claimed date (history submissions) — see
    ``_strict_period_for``: falling back to "whatever's current right now"
    is right when re-categorizing an already-dated payment (the treasurer's
    best guess still needs *a* period selected), but wrong for a decade-old
    claim, where it would mis-attribute the money to this AY.
    """
    if new_type == Payment.Type.DUES:
        model = DuesPeriod
    elif new_type == Payment.Type.TUITION:
        model = TuitionPeriod
    else:
        return None
    return (model.objects.filter(
        start_date__lte=when, end_date__gte=when).first() or model.current())


def _strict_period_for(category, when):
    """The AY period whose window actually contains ``when`` — NO
    ``current()`` fallback. None for other categories, or when no period's
    window covers the date.

    Used only for binding a member's raw claimed date (history submissions,
    task #439 review finding #1): an out-of-window claim (e.g. tuition paid
    in 2012, long before any period on file) must stay unbound rather than
    getting mis-attributed to whatever period happens to be current today —
    that would corrupt the double-payment guard (``has_dues_payment_for``)
    and the per-year sync's idempotency key.
    """
    if category == Payment.Type.DUES:
        model = DuesPeriod
    elif category == Payment.Type.TUITION:
        model = TuitionPeriod
    else:
        return None
    return model.objects.filter(start_date__lte=when, end_date__gte=when).first()


def _apply_category_change(payment, new_type, *, treasurer_email,
                           actor_label="treasurer",
                           dues_period_post=None, tuition_period_post=None):
    """Mutate ``payment``'s category and its category FKs; the caller saves,
    inside the same transaction.

    Clears FKs that no longer apply, binds the new category's period (posted
    id → payment-date window → current), and unwinds a no-longer-backed
    tuition installment. The enrollment's decision status is never
    auto-changed (do-not-over-automate) — a dated review note is appended
    instead. Returns ``(audit_details, extra_flash)``.

    ``actor_label`` attributes the internal installment-review note ("by
    treasurer …" vs "by member …") — the treasurer statement actions and the
    member statement actions (task #439) share this helper.
    """
    details = []
    unlinked_installment = None
    if payment.dues_period_id and new_type != Payment.Type.DUES:
        details.append(f"was {payment.dues_period}")
        payment.dues_period = None
    if new_type != Payment.Type.TUITION:
        if payment.tuition_period_id:
            details.append(f"was {payment.tuition_period}")
            payment.tuition_period = None
        if payment.tuition_installment_id:
            details.append(
                f"unlinked installment #{payment.tuition_installment_id}")
            unlinked_installment = payment.tuition_installment
            payment.tuition_installment = None

    when = (payment.paid_at or payment.created_at).date()
    if new_type == Payment.Type.DUES:
        payment.dues_period = _resolve_period(
            dues_period_post, DuesPeriod, _period_for(new_type, when))
    elif new_type == Payment.Type.TUITION:
        payment.tuition_period = _resolve_period(
            tuition_period_post, TuitionPeriod, _period_for(new_type, when))
    payment.payment_type = new_type

    extra_flash = _unwind_installment(
        payment, unlinked_installment, treasurer_email=treasurer_email,
        actor_label=actor_label, cause="re-categorized away from tuition")
    return details, extra_flash


def _unwind_installment(payment, installment, *, treasurer_email, cause,
                         actor_label="treasurer"):
    """After ``payment`` stops backing ``installment``: reset its paid flag if
    no other succeeded payment covers it — but do NOT auto-change the
    enrollment's status (a decision record; do-not-over-automate): leave a
    dated review note for the treasurer instead. Returns the extra flash."""
    if installment is None:
        return ""
    still_backed = installment.payments.filter(
        status=Payment.Status.SUCCEEDED,
    ).exclude(pk=payment.pk).exists()
    if still_backed:
        return ""
    was_paid = installment.paid
    if was_paid:
        installment.paid = False
        installment.paid_at = None
        installment.save(update_fields=("paid", "paid_at"))
    enrollment = installment.enrollment
    outcome = "unpaid again" if was_paid else "unlinked"
    review_note = (
        f"[{timezone.now().date()}] Payment #{payment.id} "
        f"{cause} by {actor_label} "
        f"{treasurer_email}; installment "
        f"#{installment.sequence} {outcome} — review "
        "this year's decision status."
    )
    enrollment.notes = (
        (enrollment.notes + "\n" if enrollment.notes else "")
        + review_note)
    enrollment.save(update_fields=("notes",))
    return (" Review the member's tuition decision for "
            f"{enrollment.tuition_period.name}.")


def _attach_split_info(payments) -> None:
    """Annotate ``.is_split`` and ``.split_family_total`` on payment objects
    (drives the split badge + whole-charge refund warning). Two queries."""
    from collections import defaultdict

    ids = [p.pk for p in payments]
    if not ids:
        return
    parent_ids = set(Payment.objects.filter(
        split_from_id__in=ids).values_list("split_from_id", flat=True))
    family_parent = {}
    for p in payments:
        if p.split_from_id:
            family_parent[p.pk] = p.split_from_id
        elif p.pk in parent_ids:
            family_parent[p.pk] = p.pk
    parents = set(family_parent.values())
    totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    if parents:
        for row in (Payment.objects.filter(
                Q(pk__in=parents) | Q(split_from_id__in=parents))
                .values("pk", "split_from_id", "amount")):
            totals[row["split_from_id"] or row["pk"]] += row["amount"]
    for p in payments:
        pid = family_parent.get(p.pk)
        p.is_split = pid is not None
        p.split_family_total = totals.get(pid) if pid else None



@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_assign(request, payment_id: int):
    """Assign (or reassign) a payment to a member's account.

    Mirrors the Reconcile queue's semantics: member resolved from the
    autocomplete value, provenance promoted to VERIFIED, and a dated audit
    note recording who the money was attributed to before. Registration-
    settling payments refuse — the registration owns its member.
    """
    from accounts.models import Source

    payment = get_object_or_404(Payment, pk=payment_id)
    if payment.registration_id:
        messages.error(
            request,
            "This payment settles an event registration, which owns its "
            "member. Correct the registration instead.",
        )
        return _safe_next(request, "treasurer_payments")
    assign = (request.POST.get("assign_user") or "").strip()
    target = _resolve_assign_user(assign) if assign else None
    if target is None:
        messages.error(request, f"No member found for '{assign}'.")
        return _safe_next(request, "treasurer_payments")
    if target.id == payment.user_id:
        messages.error(request, "That payment is already on this account.")
        return _safe_next(request, "treasurer_payments")

    if payment.user_id:
        old_label = (payment.user.get_full_name() or "").strip() or ""
        old_label = f"{old_label} ({payment.user.email})".strip()
    else:
        old_label = (_payer_name_from_notes(payment) or payment.email
                     or "no member")
    with transaction.atomic():
        payment.user = target
        payment.source = Source.VERIFIED
        audit = (f"[{timezone.now().date()}] Assigned to {target.email} by "
                 f"treasurer {request.user.email}. (was {old_label})")
        payment.notes = (
            (payment.notes + "\n" + audit) if payment.notes else audit)
        payment.save(update_fields=("user", "source", "notes"))
    who = target.get_full_name() or target.email
    messages.success(request, f"Assigned to {who}.")
    return _safe_next(request, "treasurer_payments")


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_payment_retype(request, payment_id: int):
    """Re-categorize a payment (treasurer override — donation flips allowed).

    The member's own statement action (``my_payment_retype``, task #439)
    also allows donation flips now (full parity); this is the audited
    staff counterpart, VERIFIED-provenance and unscoped to any one member."""
    from accounts.models import Source

    payment = get_object_or_404(Payment, pk=payment_id)
    new_type = request.POST.get("payment_type")
    if new_type not in Payment.Type.values:
        messages.error(request, "Choose a valid category.")
        return _safe_next(request, "treasurer_payments")
    settle = bool(request.POST.get("settle_charge"))
    if new_type == payment.payment_type:
        # Same category is normally a no-op — EXCEPT inserting the matching
        # settlement charge for an already-Registration payment, so the
        # treasurer needn't re-categorize away and back just to reach the
        # settle box (task #468 follow-up).
        if settle and new_type == Payment.Type.REGISTRATION:
            from accounts.models import Source
            return _settle_registration_charge_only(
                request, payment, source=Source.STAFF,
                actor_label=f"treasurer {request.user.email}",
                redirect_url="treasurer_payments")
        messages.error(request, "That payment already has that category.")
        return _safe_next(request, "treasurer_payments")
    if payment.registration_id:
        messages.error(
            request,
            "This payment settles an event registration. Use the refund or "
            "comp flows instead, or correct the registration link in the "
            "Django admin first.",
        )
        return _safe_next(request, "treasurer_payments")
    if payment.user_id is None and new_type in (
        Payment.Type.DUES, Payment.Type.TUITION,
    ):
        messages.error(
            request,
            "This payment has no member attached. Link it to a member on "
            "the Reconcile tab first.",
        )
        return _safe_next(request, "treasurer_payments")
    if settle and new_type != Payment.Type.REGISTRATION:
        messages.error(
            request,
            "The settle option applies only when re-categorizing to "
            "Registration.",
        )
        return _safe_next(request, "treasurer_payments")
    if settle and payment.user_id is None:
        messages.error(
            request,
            "This payment has no member attached. Link it to a member on "
            "the Reconcile tab first.",
        )
        return _safe_next(request, "treasurer_payments")

    labels = dict(Payment.Type.choices)
    old_type = payment.payment_type
    with transaction.atomic():
        details, extra_flash = _apply_category_change(
            payment, new_type,
            treasurer_email=request.user.email,
            dues_period_post=request.POST.get("dues_period"),
            tuition_period_post=request.POST.get("tuition_period"),
        )
        payment.source = Source.VERIFIED
        audit = (f"[{timezone.now().date()}] Re-categorized "
                 f"{labels[old_type]} → {labels[new_type]} by treasurer "
                 f"{request.user.email}."
                 + (f" ({'; '.join(details)})" if details else ""))
        payment.notes = (
            (payment.notes + "\n" + audit) if payment.notes else audit)
        payment.save()

        flash = f"Re-categorized as {labels[new_type]}."
        if settle:
            # Honor-system era: the event fee this payment settled was never
            # recorded as a charge. Insert the matching charge dated with the
            # payment so the pair nets to zero exactly where it sits in the
            # statement — no phantom credit, no invented debt.
            when = (payment.paid_at or payment.created_at).date()
            _mint_settlement_charge(
                payment, payment.amount, when,
                source=Source.STAFF,
                actor_label=f"treasurer {request.user.email}",
                cause=f"re-categorization of payment #{payment.pk}",
            )
            flash += (" Inserted a matching Registration charge dated "
                      "with the payment.")
        flash += extra_flash
    messages.success(request, flash)
    return _safe_next(request, "treasurer_payments")



_INLINE_TUITION_STATUSES = {
    "committed":    "Committed",
    "skipping":     "Skipping",
}


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_tuition_set_status(request, user_id: int):
    """Set a user's tuition status for the current period (treasurer action).

    Used by the inline resolution buttons on the tuition reconciliation
    queue. ``status`` is one of: committed, skipping.
    """
    status = request.POST.get("status", "")
    if status not in _INLINE_TUITION_STATUSES:
        return _safe_next(request, "treasurer")
    target = get_object_or_404(User, pk=user_id)
    # An explicit period id targets any year (treasurer history repair,
    # task #439); default stays the current year for the queue buttons.
    period_id = request.POST.get("period")
    if period_id:
        period = TuitionPeriod.objects.filter(pk=_int_or_none(period_id)).first()
    else:
        period = TuitionPeriod.current()
    if period is None:
        messages.error(request, "Choose a valid academic year.")
        return _safe_next(request, "treasurer")
    with transaction.atomic():
        enr, _ = TuitionEnrollment.objects.update_or_create(
            user=target, tuition_period=period,
            defaults={"status": status},
        )
        enr.notes = (
            (enr.notes + "\n" if enr.notes else "")
            + f"[{timezone.now().date()}] Treasurer ({request.user.email}) "
            f"set {period.name} status to {_INLINE_TUITION_STATUSES[status]}."
        )
        enr.save(update_fields=("notes",))
    return _safe_next(request, "treasurer")


@login_required
@user_passes_test(_is_staff)
def treasurer_settings(request):
    """Settings tab — edit dues + tuition amounts for every academic year.

    Two formsets: one for every DuesPeriod row, one for every
    TuitionPeriod row. Single submit saves all changes atomically.
    """
    from django.forms import modelformset_factory

    from .forms import DuesPeriodRowForm, TuitionPeriodRowForm
    dues_qs = DuesPeriod.objects.order_by("-start_date")
    tuition_qs = TuitionPeriod.objects.order_by("-start_date")

    DuesFormSet = modelformset_factory(
        DuesPeriod, form=DuesPeriodRowForm, extra=0,
    )
    TuitionFormSet = modelformset_factory(
        TuitionPeriod, form=TuitionPeriodRowForm, extra=0,
    )

    if request.method == "POST":
        dues_formset = DuesFormSet(
            request.POST, queryset=dues_qs, prefix="dues",
        )
        tuition_formset = TuitionFormSet(
            request.POST, queryset=tuition_qs, prefix="tuition",
        )
        if dues_formset.is_valid() and tuition_formset.is_valid():
            with transaction.atomic():
                dues_formset.save()
                tuition_formset.save()
            return redirect(request.path + "?saved=1#saved")
    else:
        dues_formset = DuesFormSet(queryset=dues_qs, prefix="dues")
        tuition_formset = TuitionFormSet(queryset=tuition_qs, prefix="tuition")

    # Zip each form with its instance so the template can render the AY
    # name and date window alongside the editable fields.
    dues_rows = list(zip(dues_formset.forms, dues_qs))
    tuition_rows = list(zip(tuition_formset.forms, tuition_qs))

    # Pick out the current-AY form for each formset so the template can
    # render its reminder_interval_days field in the dedicated cadence
    # section (the same field stays hidden in the per-row table).
    current_dues = DuesPeriod.current()
    current_tuition = TuitionPeriod.current()
    current_dues_form = next(
        (f for f, p in dues_rows if p == current_dues), None,
    )
    current_tuition_form = next(
        (f for f, p in tuition_rows if p == current_tuition), None,
    )

    return _treasurer_render(request, "settings", "payments/treasurer/settings.html", {
        "dues_formset":          dues_formset,
        "tuition_formset":       tuition_formset,
        "dues_rows":             dues_rows,
        "tuition_rows":          tuition_rows,
        "current_dues_period":   current_dues,
        "current_tuition_period": current_tuition,
        "current_dues_form":     current_dues_form,
        "current_tuition_form":  current_tuition_form,
        "saved":                 request.GET.get("saved") == "1",
    })


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        logger.warning("Stripe webhook rejected: %s", exc)
        return HttpResponseBadRequest("Invalid signature.")

    event_type = event["type"]
    event_id = event["id"] if "id" in event else "?"

    # Keep Stripe test-mode events out of real accounting (production). Genuine
    # protection is the live webhook secret rejecting test signatures above;
    # this is belt-and-suspenders for a window where test keys are configured.
    if getattr(settings, "STRIPE_LIVE_ONLY", False):
        livemode = event["livemode"] if "livemode" in event else True
        if not livemode:
            logger.warning(
                "Ignoring Stripe TEST-mode event (type=%s id=%s) — STRIPE_LIVE_ONLY",
                event_type, event_id,
            )
            return HttpResponse(status=200)

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(event["data"]["object"])
        elif event_type == "checkout.session.expired":
            _handle_checkout_expired(event["data"]["object"])
        elif event_type == "charge.refunded":
            _handle_charge_refunded(event["data"]["object"])
        else:
            logger.info("Stripe webhook ignored (type=%s id=%s)", event_type, event_id)
    except Exception:
        # Log the full traceback explicitly — Django's default LOGGING strips
        # it in production. Returning 500 tells Stripe to retry.
        logger.exception(
            "Stripe webhook handler failed (type=%s id=%s)", event_type, event_id
        )
        return HttpResponse("internal error", status=500)

    return HttpResponse(status=200)


def _handle_checkout_completed(session) -> None:
    """Idempotently mark the Payment + Registration as paid and issue a Receipt.

    ``session`` may be a plain dict (in tests) or a ``stripe.StripeObject``
    (in production). Both support bracket subscript and ``in`` membership,
    but ``StripeObject`` does *not* expose ``dict.get`` — use brackets only.
    """
    session_id = session["id"] if "id" in session else None
    if not session_id:
        logger.warning("checkout.session.completed without id; ignoring")
        return

    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(
                stripe_checkout_session_id=session_id
            )
        except Payment.DoesNotExist:
            logger.warning(
                "No Payment for stripe_checkout_session_id=%s; ignoring", session_id
            )
            return

        if payment.status == Payment.Status.SUCCEEDED:
            return  # already processed — idempotent no-op

        # Stripe-specific bookkeeping — payment_intent + the authoritative
        # live/test flag go onto the row before the generic success machinery.
        fields = []
        intent_id = session["payment_intent"] if "payment_intent" in session else None
        if intent_id:
            payment.stripe_payment_intent_id = intent_id
            fields.append("stripe_payment_intent_id")
        livemode = session["livemode"] if "livemode" in session else True
        if payment.livemode != livemode:
            payment.livemode = livemode
            fields.append("livemode")
        if fields:
            payment.save(update_fields=fields)

    # Run the shared success side-effects (idempotent across paths).
    complete_payment(payment)


def _handle_checkout_expired(session) -> None:
    """The member never finished Checkout and Stripe closed the session.

    No money moved, so this only retires the PENDING Payment row (task #474) —
    the Registration stays AWAITING_PAYMENT so the member can still pay and the
    registration reminders keep nudging them.
    """
    from .stripe_sync import abandon_payment

    session_id = session["id"] if "id" in session else None
    if not session_id:
        logger.warning("checkout.session.expired without id; ignoring")
        return

    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(
                stripe_checkout_session_id=session_id
            )
        except Payment.DoesNotExist:
            logger.info(
                "No Payment for expired session %s; ignoring", session_id
            )
            return
        abandon_payment(
            payment,
            reason="Stripe checkout expired unpaid — no payment was taken.",
        )


@login_required
def dues_pay(request):
    """Membership dues entry point (REG-12) — tiered by role per DuesPeriod.

    Falls back to the per-tier defaults from settings if no period covers
    today (which shouldn't happen in production once the bootstrap data
    migration + auto-rollover command are running).
    """
    from . import ledger
    from .dues import has_dues_payment_for
    from .models import DuesPeriod

    period = DuesPeriod.current()

    # Already paid for the current cycle — show a friendly status panel.
    # Two checks: the unified-ledger state (covered/waived by the sweep) OR a
    # direct FK-bound dues payment for this period. The direct check is the
    # double-payment guard — it must hold even when no charge has been minted
    # yet (state None) or when backfilled older charges eat the pot (state
    # "unpaid" despite this year's dues literally being paid).
    if period is not None and (
        ledger.member_account(request.user)["dues_state"] in ("paid", "waived")
        or has_dues_payment_for(request.user, period)
    ):
        return render(
            request,
            "payments/dues_already_paid.html",
            {"period": period},
        )

    role = request.user.profile.role
    if period is not None:
        amount = period.amount_for_role(role)
    else:
        # No period configured — fall back to settings defaults.
        amount = _settings_dues_amount_for_role(role)

    if amount is None:
        # Role isn't on the dues tier table (e.g. external, member).
        return render(
            request,
            "payments/dues.html",
            {
                "amount": None, "period": period,
                "role_display": request.user.profile.get_role_display(),
            },
        )

    if request.method == "POST":
        payment = Payment.objects.create(
            payment_type=Payment.Type.DUES,
            user=request.user,
            amount=amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            dues_period=period,
        )
        session = create_dues_session(payment)
        return redirect(session.url)
    return render(
        request,
        "payments/dues.html",
        {"amount": amount, "period": period},
    )


def _settings_dues_amount_for_role(role: str) -> Decimal | None:
    """Fallback resolver when no DuesPeriod is configured."""
    field_to_setting = {
        "pre_candidate":         "DUES_PRE_CANDIDATE_AMOUNT",
        "pre_candidate_scholar": "DUES_PRE_CANDIDATE_AMOUNT",
        "candidate":             "DUES_CANDIDATE_AMOUNT",
        "candidate_scholar":     "DUES_CANDIDATE_AMOUNT",
        "analyst":               "DUES_ANALYST_AMOUNT",
        "scholar":               "DUES_ANALYST_AMOUNT",
    }
    setting_name = field_to_setting.get(role)
    if not setting_name:
        return None
    return Decimal(str(getattr(settings, setting_name)))


def donate(request):
    """Donation entry point (REG-13). Anonymous-friendly."""
    if request.method == "POST":
        form = DonationForm(request.POST, user=request.user)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            dedication = (form.cleaned_data.get("dedication") or "").strip()
            is_auth = request.user.is_authenticated
            email = request.user.email if is_auth else form.cleaned_data["email"]

            payment = Payment.objects.create(
                payment_type=Payment.Type.DONATION,
                user=request.user if is_auth else None,
                email="" if is_auth else email,
                amount=amount,
                method=Payment.Method.STRIPE,
                status=Payment.Status.PENDING,
                notes=dedication,
            )
            session = create_donation_session(payment, customer_email=email)
            return redirect(session.url)
    else:
        form = DonationForm(user=request.user)
    return render(request, "payments/donate.html", {"form": form})


@login_required
@user_passes_test(_is_staff)
def transactions_csv(request):
    """Staff-only CSV export of Payments (REG-15).

    Query params (all optional):
    - ``type``: comma-separated payment_type values to include
    - ``since``: ``YYYY-MM-DD`` lower bound on the transaction date (inclusive)
    - ``until``: ``YYYY-MM-DD`` upper bound on the transaction date (inclusive)

    "Transaction date" is ``paid_at`` when set, else ``created_at`` — the real
    payment date, not the row-insertion/import date. See
    ``Payment.transaction_date``. (Task #437.)
    """
    qs = (
        Payment.objects.select_related("user", "registration__event", "receipt")
        .annotate(_txn_date=Coalesce("paid_at", "created_at"))
        .order_by("_txn_date")
    )
    types_raw = (request.GET.get("type") or "").strip()
    if types_raw:
        types = [t.strip() for t in types_raw.split(",") if t.strip()]
        qs = qs.filter(payment_type__in=types)
    since = _parse_date(request.GET.get("since"))
    if since is not None:
        qs = qs.filter(_txn_date__date__gte=since)
    until = _parse_date(request.GET.get("until"))
    if until is not None:
        qs = qs.filter(_txn_date__date__lte=until)

    filename_bits = ["transactions"]
    if types_raw:
        filename_bits.append(types_raw.replace(",", "-"))
    if since:
        filename_bits.append(f"from-{since.isoformat()}")
    if until:
        filename_bits.append(f"to-{until.isoformat()}")
    filename = "-".join(filename_bits) + ".csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        "id", "created_at", "paid_at", "payment_type", "amount", "currency",
        "status", "method", "user_email", "anonymous_email", "event_title",
        "receipt_number", "stripe_payment_intent_id",
        "stripe_checkout_session_id", "notes",
    ])
    for p in qs:
        writer.writerow([
            p.id,
            p.created_at.isoformat(),
            p.paid_at.isoformat() if p.paid_at else "",
            p.payment_type,
            p.amount,
            p.currency,
            p.status,
            p.method,
            p.user.email if p.user_id else "",
            p.email,
            (p.registration.event.title if p.registration_id else ""),
            (p.receipt.receipt_number if hasattr(p, "receipt") else ""),
            p.stripe_payment_intent_id,
            p.stripe_checkout_session_id,
            (p.notes or "").replace("\n", " | "),
        ])
    return response


@login_required
@user_passes_test(_is_staff)
def balances_csv(request):
    """Every member's ledger standing as CSV (task #439)."""
    from payments import ledger

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="lsp-balances.csv"'
    writer = csv.writer(response)
    writer.writerow(["name", "email", "role", "obligation", "paid", "balance",
                     "owes", "credit", "tuition_years_covered", "dues_state",
                     "dues_obligation", "dues_balance"])
    for r in ledger.accounts_overview():
        writer.writerow([
            r["user"].get_full_name(), r["user"].email,
            r["user"].profile.role, r["obligation"], r["paid"], r["balance"],
            r["owes"], r["credit"], r["tuition_covered"], r["dues_state"] or "",
            r["dues_obligation"], r["dues_balance"]])
    return response


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def payment_thanks(request, payment_id: int):
    """Generic post-Stripe thank-you page for non-registration payments.

    Doesn't require auth (anonymous donations need to reach it) and shows
    only generic info (type + amount + receipt number if available).
    """
    payment = get_object_or_404(
        Payment.objects.exclude(payment_type=Payment.Type.REGISTRATION),
        pk=payment_id,
    )
    return render(request, "payments/thanks.html", {"payment": payment})


@login_required
def receipt_download(request, payment_id: int):
    """Serve the member's own receipt as a downloadable text file. 404 unless the
    requester owns the payment (or is staff) and a Receipt exists. Reuses the same
    template the receipt email renders, so the download matches what was emailed."""
    payment = get_object_or_404(Payment, pk=payment_id)
    if not (payment.user_id == request.user.id or request.user.is_staff):
        raise Http404
    receipt = getattr(payment, "receipt", None)
    if receipt is None:
        raise Http404
    body = render_to_string("payments/email/receipt.txt", {
        "payment": payment,
        "receipt": receipt,
        "support_email": settings.SUPPORT_EMAIL,
    })
    resp = HttpResponse(body, content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{receipt.receipt_number}.txt"'
    return resp


def payments_index(request):
    """Central Payments page. Authenticated members see what's due, links out to
    dues / tuition / donate, and their own payment history with downloadable
    receipts. Anonymous visitors see a public gateway: sign in to manage payments,
    or donate anonymously (task #414). Deliberately does NOT redirect anon users
    to login. Composes existing surfaces, does not reimplement them."""
    if not request.user.is_authenticated:
        return render(request, "payments/gateway.html")

    from payments.dues import is_dues_obligated

    user = request.user
    profile = user.profile
    payments = (
        Payment.objects.filter(Q(user=user) | Q(email__iexact=user.email))
        .select_related("receipt")
        .order_by(Coalesce("paid_at", "created_at").desc())  # transaction date, task #437
    )
    return render(request, "payments/index.html", {
        "payments": payments,
        "dues_obligated": is_dues_obligated(user),
        "owes_tuition": profile.owes_tuition,
        "tuition_enrollment": profile.current_tuition_enrollment(),
    })


def _handle_charge_refunded(charge: dict) -> None:
    """Idempotently mark Payment + Registration as REFUNDED.

    Fires for refunds we initiated synchronously (no-op since we already
    updated) and for refunds initiated directly in the Stripe Dashboard
    (the cross-channel case we actually need this for).
    """
    intent_id = charge["payment_intent"] if "payment_intent" in charge else None
    if not intent_id:
        return
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(
            stripe_payment_intent_id=intent_id,
        ).first()
        if payment is None:
            logger.info(
                "charge.refunded for unknown payment_intent=%s; ignoring", intent_id
            )
            return
        if payment.status != Payment.Status.REFUNDED:
            payment.status = Payment.Status.REFUNDED
            payment.save(update_fields=("status",))
        # A refund of the original intent refunds the whole split family —
        # only the parent carries the intent id, so cascade to siblings here
        # (mirrors treasurer_payment_refund's whole-charge semantics).
        siblings = list(payment.split_parts.exclude(
            status=Payment.Status.REFUNDED))
        if siblings:
            audit = (f"[{timezone.now().date()}] Refunded as part of the "
                     "entire original split charge (Stripe refund webhook).")
            for part in siblings:
                part.status = Payment.Status.REFUNDED
                part.notes = (
                    (part.notes + "\n" + audit) if part.notes else audit)
                part.save(update_fields=("status", "notes"))
        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id,
                status=Registration.Status.PAID,
            ).update(status=Registration.Status.REFUNDED)
            from .charges import void_registration_charge
            void_registration_charge(payment.registration, "Stripe refund (webhook).")


def _account_tab_url(**params) -> str:
    """The Account tab of the member's My LSP hub — where the member
    statement actions (retype/split/note, task #439) return to."""
    from urllib.parse import urlencode

    from django.urls import reverse

    query = {"tab": "account", **{k: v for k, v in params.items() if v}}
    return reverse("formation:formation") + "?" + urlencode(query)


def _resolve_tuition_period(request) -> TuitionPeriod | None:
    """Resolve the target TuitionPeriod from an optional POST ``period`` slug.

    Mirrors ``tuition_decision``'s validation (task #450 phase A/B): only the
    current period and the next-by-start_date upcoming period are valid
    targets — an unknown/stale slug falls back to current for backcompat.
    Used by the pay-in-full and plan-setup views (task #450 phase B #5) so a
    member can pay for / set up a plan against next year's tuition ahead of
    time, not just the current year's.
    """
    period = TuitionPeriod.current()
    requested = request.POST.get("period", "")
    if requested:
        upcoming = TuitionPeriod.upcoming()
        allowed = {p.slug: p for p in (period, upcoming) if p is not None}
        period = allowed.get(requested, period)
    return period


@login_required
def tuition_decision(request):
    """Record the annual tuition decision (M7.5).

    The tuition surface (decision form, installments, payment history) lives on
    the member's Formation hub. This endpoint only handles the decision form's
    POST; every other request just redirects there.
    """
    profile = request.user.profile
    period = _resolve_tuition_period(request)

    if request.method == "POST" and profile.owes_tuition and period is not None:
        form = TuitionDecisionForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data["status"]
            # Skipping a year whose events tuition already covered re-bills
            # those events (task #485). Warn first: the member sees the cost,
            # confirms, and only then is anything recorded or billed.
            if status == "skipping" and not request.POST.get("confirm"):
                rows = [
                    {"registration": r, "amount": coverage.retro_amount(r.price_tier)}
                    for r in coverage.covered_registrations(request.user, period)
                ]
                rows = [r for r in rows if r["amount"] > 0]
                if rows:
                    return render(request, "payments/skip_confirm.html", {
                        "period": period,
                        "period_slug": request.POST.get("period", ""),
                        "rows": rows,
                        "total": sum(r["amount"] for r in rows),
                        "account_url": _account_tab_url(),
                    })
            with transaction.atomic():
                if status == "payment_plan":
                    # Applying for a payment plan is a request to the Board,
                    # not a self-serve status (task #450 phase B) — the
                    # enrollment records PLAN_REQUESTED (not PAYMENT_PLAN;
                    # that's reached only once the Board approves) and a
                    # PENDING TuitionPlanApplication carries the reasons for
                    # their review.
                    TuitionEnrollment.objects.update_or_create(
                        user=request.user, tuition_period=period,
                        defaults={
                            "status": TuitionEnrollment.Status.PLAN_REQUESTED,
                        },
                    )
                    application, created = (
                        TuitionPlanApplication.objects.get_or_create(
                            user=request.user, tuition_period=period,
                            status=TuitionPlanApplication.Status.PENDING,
                            defaults={
                                "reasons": form.cleaned_data["reasons"],
                            },
                        )
                    )
                    if not created:
                        # Re-submitting while still pending updates the
                        # reasons in place rather than erroring or stacking
                        # duplicate rows (the partial unique constraint only
                        # allows one PENDING application per user/period).
                        application.reasons = form.cleaned_data["reasons"]
                        application.save(update_fields=["reasons"])
                    notify_plan_application_submitted(application)
                else:
                    TuitionEnrollment.objects.update_or_create(
                        user=request.user, tuition_period=period,
                        defaults={"status": status},
                    )
                # Bill or restore the events tuition coverage paid for. A
                # paying decision (committed / plan request) restores coverage,
                # so committing returns their access without money moving.
                if status == "skipping":
                    billed = coverage.bill_skipped_coverage(request.user, period)
                else:
                    billed = []
                    coverage.unbill_skipped_coverage(request.user, period)
            if billed:
                notify_coverage_rebilled(request.user, period, billed)
            messages.success(request, "Your tuition decision has been recorded.")
        else:
            messages.error(request, "Please choose one of the listed options.")
    return redirect(_account_tab_url())


@login_required
@require_POST
def tuition_pay_in_full(request):
    """Pay this year's tuition in a single Stripe transaction (M7.5).

    Creates a single TuitionInstallment for the full annual amount + a
    Payment + a Stripe Checkout Session, and redirects to Stripe. The
    webhook (or the treasurer's "Apply payment success" action) will
    flip the enrollment to PAID_IN_FULL via complete_payment.
    """
    profile = request.user.profile
    if not profile.owes_tuition:
        return redirect(_account_tab_url())
    period = _resolve_tuition_period(request)
    if period is None:
        return redirect(_account_tab_url())
    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()
    if enrollment is None:
        return redirect(_account_tab_url())
    if enrollment.installments.exists():
        # Already on a payment plan / has installments — direct to pay one
        # rather than minting a parallel "full" installment.
        return redirect(_account_tab_url())
    with transaction.atomic():
        installment = TuitionInstallment.objects.create(
            enrollment=enrollment, sequence=1,
            due_date=period.decision_due_date,
            amount=period.tuition_amount,
        )
        payment = Payment.objects.create(
            payment_type=Payment.Type.TUITION,
            user=request.user,
            amount=period.tuition_amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            tuition_installment=installment,
        )
    session = create_tuition_session(payment)
    return redirect(session.url)


@login_required
@require_POST
def tuition_setup_plan(request):
    """Create the installment rows for a PAYMENT_PLAN enrollment (M7.5).

    Accepts ``installment_count`` of 2 (Sept + Feb) or 9 (monthly Sept–May).
    Idempotent: if installments already exist, redirects back without
    creating duplicates so a refresh of the POST doesn't multiply rows.
    """
    profile = request.user.profile
    if not profile.owes_tuition:
        return redirect(_account_tab_url())
    period = _resolve_tuition_period(request)
    if period is None:
        return redirect(_account_tab_url())
    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()
    if enrollment is None or enrollment.status != TuitionEnrollment.Status.PAYMENT_PLAN:
        return redirect(_account_tab_url())
    if enrollment.installments.exists():
        return redirect(_account_tab_url())
    try:
        count = int(request.POST.get("installment_count", "0"))
    except (TypeError, ValueError):
        return redirect(_account_tab_url())
    if count not in (2, 9):
        return redirect(_account_tab_url())

    schedule = _build_installment_schedule(period, count)
    with transaction.atomic():
        for seq, (due_date, amount) in enumerate(schedule, start=1):
            TuitionInstallment.objects.create(
                enrollment=enrollment, sequence=seq,
                due_date=due_date, amount=amount,
            )
    return redirect(_account_tab_url())


def _build_installment_schedule(
    period: TuitionPeriod, count: int,
) -> list[tuple[date, Decimal]]:
    """Return a list of ``(due_date, amount)`` tuples summing to tuition_amount.

    For ``count=2``: September (period.decision_due_date) and February.
    For ``count=9``: monthly from September through May.
    Rounding goes onto the final installment so the sum is exact.
    """
    from calendar import monthrange
    total = period.tuition_amount
    start_year = period.start_date.year

    def _last_day(year, month):
        return monthrange(year, month)[1]

    def _clamp(year, month, day=1):
        return date(year, month, min(day, _last_day(year, month)))

    if count == 2:
        # Sept (decision_due) + Feb of the following year (1st).
        dates = [period.decision_due_date, _clamp(start_year + 1, 2, 1)]
    elif count == 9:
        # Sept, Oct, Nov, Dec, Jan, Feb, Mar, Apr, May.
        months = [(start_year, 9), (start_year, 10), (start_year, 11),
                  (start_year, 12), (start_year + 1, 1), (start_year + 1, 2),
                  (start_year + 1, 3), (start_year + 1, 4), (start_year + 1, 5)]
        dates = [_clamp(y, m, 1) for y, m in months]
    else:
        return []

    base = (total / count).quantize(Decimal("0.01"))
    amounts = [base] * (count - 1)
    amounts.append(total - sum(amounts))  # remainder goes on the last
    return list(zip(dates, amounts))


@login_required
@require_POST
def tuition_pay_installment(request, installment_id: int):
    """Pay a specific tuition installment via Stripe (M7.5).

    Only the owning user can pay their installment. Re-paying a paid
    installment is a no-op redirect.
    """
    installment = get_object_or_404(
        TuitionInstallment.objects.select_related("enrollment"),
        pk=installment_id, enrollment__user=request.user,
    )
    if installment.paid:
        return redirect(_account_tab_url())
    with transaction.atomic():
        payment = Payment.objects.create(
            payment_type=Payment.Type.TUITION,
            user=request.user,
            amount=installment.amount,
            method=Payment.Method.STRIPE,
            status=Payment.Status.PENDING,
            tuition_installment=installment,
        )
    session = create_tuition_session(payment)
    return redirect(session.url)


def _log_member_action(payment, user, action: str, summary: str) -> None:
    """Record a member's self-service statement action so the treasurer's
    Reconcile queue can surface it (task #443). Append-only; never read back
    into ledger math."""
    PaymentMemberAction.objects.create(
        payment=payment, user=user, action=action, summary=summary[:200])


@login_required
@require_POST
def my_payment_retype(request, payment_id: int):
    """Member statement action: re-categorize one of the member's OWN
    payments (task #439, member Account v2 — full treasurer parity).

    Mirrors ``treasurer_payment_retype`` mechanically (shares
    ``_apply_category_change`` / ``_unwind_installment``), with these
    deltas: scoped to ``request.user`` (a stale/forged id 404s rather than
    touching another member's row — never a cross-account leak); no
    donation-flip block (Rico 2026-07-16 — full parity, the old
    ``my_payments_update`` restriction does not carry forward);
    ``payment.source`` is promoted to ``SELF_REPORTED`` (not ``VERIFIED`` —
    a member's own say-so, distinct from a treasurer's); the audit note and
    any settle-charge note are attributed to the member. Registration-
    settling payments still refuse (the registration owns that link)."""
    from accounts.models import Source

    payment = get_object_or_404(Payment, pk=payment_id, user=request.user)
    new_type = request.POST.get("payment_type")
    if new_type not in Payment.Type.values:
        messages.error(request, "Choose a valid category.")
        return _safe_next(request, _account_tab_url())
    settle = bool(request.POST.get("settle_charge"))
    if new_type == payment.payment_type:
        # Same category is a no-op EXCEPT inserting the matching settlement
        # charge for an already-Registration payment (task #468 follow-up).
        if settle and new_type == Payment.Type.REGISTRATION:
            return _settle_registration_charge_only(
                request, payment, source=Source.SELF_REPORTED,
                actor_label=f"member {request.user.email}",
                redirect_url=_account_tab_url(), member_log=True)
        messages.error(request, "That payment already has that category.")
        return _safe_next(request, _account_tab_url())
    if payment.registration_id:
        messages.error(
            request,
            "This payment settles an event registration. Contact the "
            "treasurer to correct the registration link.",
        )
        return _safe_next(request, _account_tab_url())
    if settle and new_type != Payment.Type.REGISTRATION:
        messages.error(
            request,
            "The settle option applies only when re-categorizing to "
            "Registration.",
        )
        return _safe_next(request, _account_tab_url())

    labels = dict(Payment.Type.choices)
    old_type = payment.payment_type
    with transaction.atomic():
        details, extra_flash = _apply_category_change(
            payment, new_type,
            treasurer_email=request.user.email,
            actor_label="member",
            dues_period_post=request.POST.get("dues_period"),
            tuition_period_post=request.POST.get("tuition_period"),
        )
        payment.source = Source.SELF_REPORTED
        audit = (f"[{timezone.now().date()}] Re-categorized "
                 f"{labels[old_type]} → {labels[new_type]} by member "
                 f"{request.user.email}."
                 + (f" ({'; '.join(details)})" if details else ""))
        payment.notes = (
            (payment.notes + "\n" + audit) if payment.notes else audit)
        payment.save()
        _log_member_action(
            payment, request.user, PaymentMemberAction.Action.RETYPE,
            f"{labels[old_type]} → {labels[new_type]}")

        flash = f"Re-categorized as {labels[new_type]}."
        if settle:
            # Honor-system era: the event fee this payment settled was never
            # recorded as a charge. Insert the matching charge dated with the
            # payment so the pair nets to zero exactly where it sits in the
            # statement — no phantom credit, no invented debt.
            when = (payment.paid_at or payment.created_at).date()
            _mint_settlement_charge(
                payment, payment.amount, when,
                source=Source.SELF_REPORTED,
                actor_label=f"member {request.user.email}",
                cause=f"re-categorization of payment #{payment.pk}",
            )
            flash += (" Inserted a matching Registration charge dated "
                      "with the payment.")
        flash += extra_flash
    messages.success(request, flash)
    return _safe_next(request, _account_tab_url())


@login_required
@require_POST
def my_payment_split(request, payment_id: int):
    """Member statement action: split one of the member's OWN payments into
    sibling rows with different categories (task #439, member Account v2 —
    full treasurer parity).

    Mirrors ``treasurer_payment_split`` mechanically, scoped to
    ``request.user``. Donation parts are allowed (full parity). Every
    minted row (siblings + any settlement charge) carries
    ``source=SELF_REPORTED``; the audit/settlement notes are attributed to
    the member. Registration-settling payments and already-split rows
    still refuse — same system invariants as the treasurer version."""
    from accounts.models import Source

    payment = get_object_or_404(Payment, pk=payment_id, user=request.user)
    if payment.status != Payment.Status.SUCCEEDED:
        messages.error(request, "Only succeeded payments can be split.")
        return _safe_next(request, _account_tab_url())
    if payment.registration_id:
        messages.error(
            request,
            "This payment settles an event registration and cannot be split.")
        return _safe_next(request, _account_tab_url())
    if payment.split_from_id or payment.split_parts.exists():
        messages.error(request, "This payment is already part of a split.")
        return _safe_next(request, _account_tab_url())

    types = request.POST.getlist("part_type")
    amounts = request.POST.getlist("part_amount")
    settle_rows = set(request.POST.getlist("part_settle"))
    parts = []
    for i, (t, raw) in enumerate(zip(types, amounts)):
        if not (raw or "").strip():
            continue  # empty extra row in the form
        amount = _parse_amount(raw)
        if t not in Payment.Type.values or amount is None:
            messages.error(
                request, "Each part needs a valid category and amount.")
            return _safe_next(request, _account_tab_url())
        settle = str(i) in settle_rows and t == Payment.Type.REGISTRATION
        parts.append((t, amount, settle))
    if len(parts) < 2:
        messages.error(request, "A split needs at least two parts.")
        return _safe_next(request, _account_tab_url())
    if sum((a for _, a, _ in parts), Decimal("0")) != payment.amount:
        messages.error(
            request, f"The parts must add up to exactly ${payment.amount}.")
        return _safe_next(request, _account_tab_url())

    labels = dict(Payment.Type.choices)
    old_type, old_amount = payment.payment_type, payment.amount
    when = (payment.paid_at or payment.created_at).date()
    today = timezone.now().date()
    breakdown = ", ".join(f"${a} {labels[t]}" for t, a, _ in parts)
    extra_flash = ""
    with transaction.atomic():
        first_type, first_amount, first_settle = parts[0]
        details = []
        # A split always unlinks a tuition installment — the single-installment
        # linkage no longer describes the (now divided) money — and unwinds it
        # if nothing else backs it. This runs regardless of the first part's
        # category (a same-category first part would otherwise keep the full
        # installment marked paid against a reduced amount).
        if payment.tuition_installment_id:
            details.append(
                f"unlinked installment #{payment.tuition_installment_id}")
            _installment = payment.tuition_installment
            payment.tuition_installment = None
            extra_flash += _unwind_installment(
                payment, _installment, treasurer_email=request.user.email,
                actor_label="member", cause="split across categories")
        if first_type != old_type:
            _details, _extra = _apply_category_change(
                payment, first_type, treasurer_email=request.user.email,
                actor_label="member")
            details += _details
            extra_flash += _extra
        payment.amount = first_amount
        payment.source = Source.SELF_REPORTED
        audit = (f"[{today}] Split ${old_amount} {labels[old_type]} into "
                 f"{breakdown} by member {request.user.email}."
                 + (f" ({'; '.join(details)})" if details else ""))
        payment.notes = (
            (payment.notes + "\n" + audit) if payment.notes else audit)
        payment.save()
        _log_member_action(
            payment, request.user, PaymentMemberAction.Action.SPLIT,
            f"${old_amount} {labels[old_type]} → {breakdown}")

        settle_targets = [(payment, first_amount)] if first_settle else []
        for t, a, settle in parts[1:]:
            child = _create_split_child(
                payment, t, a, when,
                source=Source.SELF_REPORTED,
                actor_label=f"member {request.user.email}",
                original=f"${old_amount} {labels[old_type]}",
            )
            if settle:
                settle_targets.append((child, a))
        for target, amount in settle_targets:
            _mint_settlement_charge(
                payment, amount, when,
                source=Source.SELF_REPORTED,
                actor_label=f"member {request.user.email}",
                cause=(f"the split of payment #{payment.pk} "
                       f"(part: payment #{target.pk})"),
            )
    flash = f"Split into {breakdown}."
    if settle_targets:
        flash += " Inserted matching Registration charge(s)."
    flash += extra_flash
    messages.success(request, flash)
    return _safe_next(request, _account_tab_url())


@login_required
@require_POST
def my_payment_note(request, payment_id: int):
    """Member statement action: write/replace the member's own note on one
    of their payments (task #439, member Account v2). Replaces
    ``member_note`` in full (not append — this is the member's own
    editable field, matching the retired ``my_payments_update`` table's
    note column); an empty submission clears it."""
    payment = get_object_or_404(Payment, pk=payment_id, user=request.user)
    note = (request.POST.get("note") or "").strip()[:1000]
    if payment.member_note != note:
        payment.member_note = note
        payment.save(update_fields=("member_note",))
        _log_member_action(
            payment, request.user, PaymentMemberAction.Action.NOTE,
            "Added a note" if note else "Cleared the note")
        messages.success(request, "Note saved." if note else "Note cleared.")
    return _safe_next(request, _account_tab_url())


@login_required
@require_POST
def my_ledger_submission_create(request):
    """Member endpoint: report a missing historical payment or charge (task
    #439, member Account v2 §3). Crucial for students who started before
    the site's records begin — this only files the claim as PENDING; a
    treasurer approves (minting the matching Payment/Charge) or declines it
    from the Reconcile tab's Member submissions queue. Capped at 10
    outstanding PENDING submissions per member — a guardrail against
    accidental repeat-submission flooding the treasurer's queue (review
    finding #4b), not a hard limit on legitimate history (declined/approved
    rows don't count)."""
    if LedgerSubmission.objects.filter(
            user=request.user, status=LedgerSubmission.Status.PENDING,
    ).count() >= 10:
        messages.error(
            request,
            "You have several reports awaiting review, please wait for "
            "the treasurer.")
        return redirect(_account_tab_url())

    kind = request.POST.get("kind")
    if kind not in LedgerSubmission.Kind.values:
        messages.error(request, "Choose whether this was a payment or a charge.")
        return redirect(_account_tab_url())
    category = request.POST.get("category")
    if category not in Payment.Type.values:
        messages.error(request, "Choose a valid category.")
        return redirect(_account_tab_url())
    if (kind == LedgerSubmission.Kind.CHARGE
            and category not in Charge.Category.values):
        messages.error(
            request,
            "Donations can only be reported as payments. Choose the "
            "payment option, or a dues, tuition, or registration category.")
        return redirect(_account_tab_url())
    amount = _parse_amount(request.POST.get("amount", ""))
    if amount is None:
        messages.error(request, "Enter a positive amount.")
        return redirect(_account_tab_url())
    try:
        claimed_date = date.fromisoformat(request.POST.get("claimed_date", ""))
    except ValueError:
        messages.error(request, "Enter a valid date.")
        return redirect(_account_tab_url())
    if claimed_date > timezone.now().date():
        messages.error(request, "The date can't be in the future.")
        return redirect(_account_tab_url())
    details = (request.POST.get("details") or "").strip()[:2000]
    if not details:
        messages.error(request, "Describe what this was.")
        return redirect(_account_tab_url())

    LedgerSubmission.objects.create(
        user=request.user, kind=kind, category=category, amount=amount,
        claimed_date=claimed_date, details=details,
    )
    messages.success(
        request,
        "Thanks, the treasurer will review your report and follow up.")
    return redirect(_account_tab_url())
