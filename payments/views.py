"""Public payment views: webhook, dues, donations, thanks, exports, dashboard."""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.membership import current_academic_year_start as ay_of
from registrations.models import Registration

from .forms import DonationForm, TuitionDecisionForm
from .models import (
    DuesPeriod,
    Payment,
    TuitionEnrollment,
    TuitionInstallment,
    TuitionPeriod,
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
    ("tuition",  "Tuition"),
    ("dues",     "Dues"),
    ("members",  "Members"),
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
        "tuition":  reverse("treasurer_tuition"),
        "dues":     reverse("treasurer_dues"),
        "members":  reverse("treasurer_members"),
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
    """Overview tab — compact highlights for both tuition and dues (M7.5)."""
    tuition_ctx = _treasurer_tuition_context()
    dues_ctx = _treasurer_dues_context()

    return _treasurer_render(request, "overview", "payments/treasurer/overview.html", {
        **dues_ctx,
        **tuition_ctx,
    })


@login_required
@user_passes_test(_is_staff)
def treasurer_tuition(request):
    """Tuition tab — per-year drill-down detail + longitudinal table/charts."""
    selected = TuitionPeriod.objects.filter(slug=request.GET.get("year")).first()
    ctx = _treasurer_tuition_context(selected)
    ctx.update(_treasurer_tuition_longitudinal())
    ctx["tuition_all_periods"] = list(TuitionPeriod.objects.order_by("-start_date"))
    return _treasurer_render(request, "tuition", "payments/treasurer/tuition.html", ctx)


@login_required
@user_passes_test(_is_staff)
def treasurer_dues(request):
    """Dues tab — per-year drill-down detail + longitudinal table/charts."""
    selected = DuesPeriod.objects.filter(slug=request.GET.get("year")).first()
    ctx = _treasurer_dues_context(selected)
    ctx["dues_all_periods"] = list(DuesPeriod.objects.order_by("-start_date"))
    return _treasurer_render(request, "dues", "payments/treasurer/dues.html", ctx)


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
    return _treasurer_render(request, "reconcile", "payments/treasurer/reconcile.html", {
        "groups": group_list,
        "assumed_count": len(assumed),
        "assumed_total": sum((p.amount for p in assumed), Decimal("0")),
        "no_payer_groups": no_payer_groups,
        "no_payer_count": len(no_payer),
        "no_payer_total": sum((p.amount for p in no_payer), Decimal("0")),
        "type_choices": Payment.Type.choices,
        "member_options": _reconcile_member_options() if need_members else [],
    })


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


def _treasurer_dues_context(selected_period=None) -> dict:
    """Build the dues-section context.

    The detailed sections (role breakdown, unpaid list, outstanding $, the
    paid-members list) describe the *selected* period — the current period by
    default, or any past year via the year selector. Forward-looking pieces
    (unpaid members, outstanding owed) only apply to the current period; past
    years show the retrospective paid-members list instead. ``period_stats``
    and the charts are always all-years (longitudinal).
    """
    from payments.dues import obligated_users_qs
    obligated_roles = list(settings.DUES_OBLIGATED_ROLES)
    obligated_count = obligated_users_qs().count()

    current = DuesPeriod.current()
    selected = selected_period or current

    periods = list(DuesPeriod.objects.order_by("-start_date"))
    period_stats = []
    for p in periods:
        paid_payments = p.payments.filter(status=Payment.Status.SUCCEEDED)
        paid_count = paid_payments.values("user").distinct().count()
        total = paid_payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        is_cur = current is not None and p.id == current.id
        period_stats.append({
            "period": p,
            "paid_count": paid_count,
            # Unpaid is only meaningful for the current year — it's measured
            # against today's roster. Templates show it only when is_current.
            "unpaid_count": max(obligated_count - paid_count, 0) if is_cur else None,
            "total_collected": total,
            "is_current": is_cur,
        })

    current_dues_stats = next(
        (s for s in period_stats if current and s["period"].id == current.id), None
    )
    selected_dues_stats = next(
        (s for s in period_stats if selected and s["period"].id == selected.id), None
    )
    is_current = current is not None and selected is not None and selected.id == current.id

    role_breakdown = []
    unpaid_users = []
    paid_members = []
    dues_collected = selected_dues_stats["total_collected"] if selected_dues_stats else Decimal("0")
    dues_outstanding = Decimal("0")
    if selected is not None:
        paid_user_ids = set(
            selected.payments
            .filter(status=Payment.Status.SUCCEEDED)
            .values_list("user_id", flat=True)
        )
        # Retrospective: who paid this year (accurate regardless of roster churn).
        paid_members = list(
            selected.payments
            .filter(status=Payment.Status.SUCCEEDED)
            .select_related("user", "user__profile")
            .order_by("user__last_name", "user__first_name", "-paid_at")
        )
        # Forward-looking role breakdown + unpaid list + outstanding: current only.
        if is_current:
            for role in obligated_roles:
                users_in_role = obligated_users_qs().filter(profile__role=role)
                total_in_role = users_in_role.count()
                paid_in_role = users_in_role.filter(id__in=paid_user_ids).count()
                unpaid_in_role = total_in_role - paid_in_role
                role_breakdown.append({
                    "role": role,
                    "total": total_in_role,
                    "paid": paid_in_role,
                    "unpaid": unpaid_in_role,
                })
                rate = selected.amount_for_role(role) or Decimal("0")
                dues_outstanding += rate * unpaid_in_role
            unpaid_users = list(
                obligated_users_qs()
                .exclude(id__in=paid_user_ids)
                .select_related("profile")
                .order_by("last_name", "first_name", "email")
            )

    chron = list(reversed(period_stats))
    chart_periods = {
        "labels": [s["period"].name for s in chron],
        "totals": [float(s["total_collected"]) for s in chron],
    }
    chart_participation = {
        "labels": [s["period"].name for s in chron],
        "counts": [s["paid_count"] for s in chron],
    }
    chart_roles = {
        "labels": [r["role"] for r in role_breakdown],
        "paid": [r["paid"] for r in role_breakdown],
        "unpaid": [r["unpaid"] for r in role_breakdown],
    }
    chart_dues_money = {
        "collected": float(dues_collected),
        "outstanding": float(dues_outstanding),
    }
    return {
        "period_stats":   period_stats,
        "current_period": current,
        "dues_selected_period": selected,
        "dues_is_current": is_current,
        "current_dues_stats": current_dues_stats,
        "selected_dues_stats": selected_dues_stats,
        "role_breakdown": role_breakdown,
        "unpaid_users":   unpaid_users,
        "paid_members":   paid_members,
        "dues_confirmed_pct": _confirmed_pct(p.source for p in paid_members),
        "obligated_count": obligated_count,
        "dues_collected": dues_collected,
        "dues_outstanding": dues_outstanding,
        "dues_expected": dues_collected + dues_outstanding,
        "chart_periods_json": json.dumps(chart_periods),
        "chart_participation_json": json.dumps(chart_participation),
        "chart_roles_json": json.dumps(chart_roles),
        "chart_dues_money_json": json.dumps(chart_dues_money),
    }


@login_required
@user_passes_test(_is_staff)
def treasurer_members(request):
    """Members tab — search for a member, view their full payment history."""
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        from django.db.models import Q
        results = list(
            User.objects.filter(
                Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q),
            )
            .exclude(profile__is_persona=True)   # personas aren't real members
            .select_related("profile")
            .order_by("last_name", "first_name", "email")[:50]
        )
    return _treasurer_render(request, "members", "payments/treasurer/members.html", {
        "q":       q,
        "results": results,
    })


@login_required
@user_passes_test(_is_staff)
def treasurer_member_detail(request, user_id: int):
    """Per-member detail page: payments, tuition enrollments, registrations."""
    from registrations.models import Registration
    target = get_object_or_404(
        User.objects.select_related("profile"), pk=user_id,
    )
    payments = list(
        Payment.objects.filter(user=target)
        .select_related("registration__event")
        # Sort by the real transaction date (paid_at), not the import date
        # (created_at). See Payment.transaction_date. (Task #437.)
        .order_by(Coalesce("paid_at", "created_at").desc())
    )
    tuition = _member_tuition_summary(target)
    registrations = list(
        Registration.objects.filter(user=target)
        .select_related("event", "price_tier")
        .order_by("-created_at")
    )
    return _treasurer_render(
        request, "members", "payments/treasurer/member_detail.html",
        {
            "target":         target,
            "payments":       payments,
            "tuition_rows":   tuition["rows"],
            "tuition_orphan": tuition["unattributed"],
            "registrations":  registrations,
        },
    )


def _member_tuition_summary(user) -> dict:
    """Per-academic-year tuition picture for the treasurer member page.

    Attributes every succeeded tuition payment to a year — an explicit
    installment or period link wins; otherwise the year whose window contains
    the payment date — then reports **paid vs owed** per year and flags
    over-payment and "marked paid in full but short." Payments that fall in no
    period at all are returned separately. Reveals payments the old
    installment-only view hid (e.g. a lump payment not wired to the plan).
    (Task #435.)"""
    periods = list(TuitionPeriod.objects.all())
    period_by_id = {tp.id: tp for tp in periods}

    def period_for_date(d):
        for tp in periods:
            if tp.start_date <= d <= tp.end_date:
                return tp
        return None

    payments = (
        Payment.objects.filter(
            user=user, payment_type=Payment.Type.TUITION,
            status=Payment.Status.SUCCEEDED,
        )
        .select_related(
            "tuition_installment__enrollment__tuition_period", "tuition_period")
    )
    by_period = defaultdict(list)
    unattributed = []
    for p in payments:
        tp = None
        if p.tuition_installment_id and p.tuition_installment.enrollment_id:
            tp = p.tuition_installment.enrollment.tuition_period
        elif p.tuition_period_id:
            tp = p.tuition_period
        elif p.paid_at:
            tp = period_for_date(p.paid_at.date())
        if tp:
            by_period[tp.id].append(p)
        else:
            unattributed.append(p)

    enrollments = {
        e.tuition_period_id: e
        for e in TuitionEnrollment.objects.filter(user=user)
        .select_related("tuition_period").prefetch_related("installments")
    }

    rows = []
    for pid in set(by_period) | set(enrollments):
        tp = period_by_id[pid]
        enr = enrollments.get(pid)
        pays = sorted(by_period.get(pid, []),
                      key=lambda p: p.paid_at or p.created_at)
        paid = sum((p.amount for p in pays), Decimal("0"))
        owed = tp.tuition_amount or Decimal("0")
        skipping = bool(enr and enr.status == TuitionEnrollment.Status.SKIPPING)
        rows.append({
            "period": tp, "enrollment": enr, "owed": owed, "paid": paid,
            "payments": pays,
            "overpaid": paid > owed and not skipping,
            "short": bool(enr and enr.status == TuitionEnrollment.Status.PAID_IN_FULL
                          and paid < owed),
        })
    rows.sort(key=lambda r: r["period"].start_date, reverse=True)
    return {"rows": rows, "unattributed": unattributed}


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
    })


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
        return redirect("treasurer_payments")

    if payment.method == Payment.Method.STRIPE:
        try:
            refund_payment(payment)
        except RefundError as exc:
            logger.exception("Refund failed for payment %s: %s", payment.id, exc)
            return redirect("treasurer_payments")
    else:
        _record_offline_refund(payment, treasurer=request.user)
        # Cascade to Registration (the Stripe path gets this via webhook).
        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id,
                status=Registration.Status.PAID,
            ).update(status=Registration.Status.REFUNDED)
    return redirect("treasurer_payments")


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
    if not hasattr(payment, "receipt"):
        return redirect("treasurer_payments")
    try:
        send_receipt(payment)
    except Exception:
        logger.exception("Failed to resend receipt for payment %s", payment.id)
    return redirect("treasurer_payments")


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
    return redirect("treasurer_payments")


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
        return redirect("treasurer_tuition")
    target = get_object_or_404(User, pk=user_id)
    period = TuitionPeriod.current()
    if period is None:
        return redirect("treasurer_tuition")
    with transaction.atomic():
        enr, _ = TuitionEnrollment.objects.update_or_create(
            user=target, tuition_period=period,
            defaults={"status": status},
        )
        enr.notes = (
            (enr.notes + "\n" if enr.notes else "")
            + f"[{timezone.now().date()}] Treasurer ({request.user.email}) "
            f"set status to {_INLINE_TUITION_STATUSES[status]}."
        )
        enr.save(update_fields=("notes",))
    return redirect("treasurer_tuition")


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_dues_record_offline_payment(request, user_id: int):
    """Record an offline dues payment for the user's role-tier amount.

    Creates an OFFLINE Payment for the current DuesPeriod's per-role
    amount and runs ``complete_payment`` — which marks SUCCEEDED, issues
    a Receipt, and emails the member.
    """
    target = get_object_or_404(User, pk=user_id)
    period = DuesPeriod.current()
    if period is None:
        return redirect("treasurer_dues")
    amount = period.amount_for_role(target.profile.role)
    if amount is None:
        # User's role isn't dues-obligated under the current tier table.
        return redirect("treasurer_dues")
    with transaction.atomic():
        payment = Payment.objects.create(
            payment_type=Payment.Type.DUES,
            user=target,
            amount=amount,
            method=Payment.Method.OFFLINE,
            status=Payment.Status.PENDING,
            dues_period=period,
            notes=(
                f"Offline dues payment recorded by treasurer "
                f"{request.user.email} on {timezone.now().date()}."
            ),
        )
    complete_payment(payment)
    return redirect("treasurer_dues")


@login_required
@user_passes_test(_is_staff)
@require_POST
def treasurer_tuition_record_offline_payment(request, user_id: int):
    """Record an offline tuition payment for the full annual amount.

    Creates (or reuses) a COMMITTED enrollment for the current period,
    mints a single full-amount TuitionInstallment, creates an OFFLINE
    Payment, and runs the standard ``complete_payment`` side-effects —
    which marks the installment paid and flips the enrollment to
    PAID_IN_FULL. The Payment.notes carries a short audit trail.
    """
    target = get_object_or_404(User, pk=user_id)
    period = TuitionPeriod.current()
    if period is None:
        return redirect("treasurer_tuition")
    with transaction.atomic():
        enr, _ = TuitionEnrollment.objects.update_or_create(
            user=target, tuition_period=period,
            defaults={"status": TuitionEnrollment.Status.COMMITTED},
        )
        installment = TuitionInstallment.objects.create(
            enrollment=enr, sequence=enr.installments.count() + 1,
            due_date=period.decision_due_date,
            amount=period.tuition_amount,
        )
        payment = Payment.objects.create(
            payment_type=Payment.Type.TUITION,
            user=target,
            amount=period.tuition_amount,
            method=Payment.Method.OFFLINE,
            status=Payment.Status.PENDING,
            tuition_installment=installment,
            notes=(
                f"Offline tuition payment recorded by treasurer "
                f"{request.user.email} on {timezone.now().date()}."
            ),
        )
    complete_payment(payment)
    return redirect("treasurer_tuition")


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


_TUITION_STATUS_ORDER = [
    ("paid_in_full",  "Paid in full"),
    ("payment_plan",  "On payment plan"),
    ("committed",     "Committed (unpaid)"),
    ("skipping",      "Skipping"),
]


def _confirmed_pct(sources) -> int | None:
    """Percent of rows whose provenance is confirmed (verified/imported/staff)
    vs. estimated (self-reported/assumed). None when there are no rows."""
    from accounts.models import Source
    sources = list(sources)
    if not sources:
        return None
    confirmed = sum(
        1 for s in sources
        if s in (Source.VERIFIED, Source.IMPORTED, Source.STAFF)
    )
    return round(100 * confirmed / len(sources))


def _backfilled_tuition_collected(period) -> Decimal:
    """Succeeded tuition payments with no installment link (historical Stripe /
    treasurer-ledger imports), summed for ``period`` by payment date. The
    payment-plan flow links tuition via ``tuition_installment``; backfilled lump
    payments don't, so they'd otherwise be invisible on the tuition dashboard."""
    base = Payment.objects.filter(
        payment_type=Payment.Type.TUITION,
        status=Payment.Status.SUCCEEDED,
        tuition_installment__isnull=True,
    )
    # Payments the member assigned to this AY win outright; the rest fall back
    # to the AY their payment date lands in.
    assigned = base.filter(tuition_period=period).aggregate(s=Sum("amount"))["s"]
    dated = base.filter(
        tuition_period__isnull=True,
        paid_at__date__gte=period.start_date,
        paid_at__date__lte=period.end_date,
    ).aggregate(s=Sum("amount"))["s"]
    return (assigned or Decimal("0")) + (dated or Decimal("0"))


def _treasurer_tuition_context(selected_period=None) -> dict:
    """Build the tuition-section context for a selected TuitionPeriod.

    For the *current* period this includes the forward-looking sections — the
    live in-training roster, undecided students, the reconciliation queue, and
    the 'owed by undecided' money bucket. For a selected *past* period those
    roster-relative concepts don't apply, so it returns retrospective facts
    only: enrollments by status, collected, and committed-but-unpaid.
    """
    from accounts.models import Profile
    current = TuitionPeriod.current()
    period = selected_period or current
    if period is None:
        return {
            "tuition_period": None,
            "tuition_selected_period": None,
            "tuition_is_current": False,
            "tuition_status_counts": [],
            "tuition_role_breakdown": [],
            "tuition_reconciliation_users": [],
            "tuition_enrollment_rows": [],
            "tuition_in_training_count": 0,
            "tuition_total_collected": Decimal("0"),
            "tuition_committed_remaining": Decimal("0"),
            "tuition_undecided_owed": Decimal("0"),
            "tuition_outstanding": Decimal("0"),
            "chart_tuition_money_json": json.dumps({"collected": 0, "planned": 0, "owed": 0}),
        }

    is_current = current is not None and period.id == current.id

    enrollments = list(
        TuitionEnrollment.objects.filter(tuition_period=period)
        .select_related("user", "user__profile")
    )
    decided_user_ids = {e.user_id for e in enrollments}
    status_counter: dict[str, int] = {}
    for e in enrollments:
        status_counter[e.status] = status_counter.get(e.status, 0) + 1

    # Per-enrollment paid-so-far for the period (drives collected + remaining).
    paid_by_enrollment: dict[int, Decimal] = {}
    for row in (
        Payment.objects.filter(
            payment_type=Payment.Type.TUITION,
            status=Payment.Status.SUCCEEDED,
            tuition_installment__enrollment__tuition_period=period,
        )
        .values("tuition_installment__enrollment")
        .annotate(s=Sum("amount"))
    ):
        paid_by_enrollment[row["tuition_installment__enrollment"]] = row["s"] or Decimal("0")
    total_collected = sum(paid_by_enrollment.values(), Decimal("0"))
    # Plus historical backfill: tuition payments with no installment link
    # (imported from Stripe / the treasurer ledger), attributed to the period
    # whose academic year contains the payment date.
    total_collected += _backfilled_tuition_collected(period)

    full = period.tuition_amount or Decimal("0")
    # Remaining balance for students who committed / are on a plan but haven't
    # fully paid. Meaningful for any year (uncollected-from-committed).
    committed_remaining = Decimal("0")
    for e in enrollments:
        if e.status in (
            TuitionEnrollment.Status.COMMITTED,
            TuitionEnrollment.Status.PAYMENT_PLAN,
        ):
            paid = paid_by_enrollment.get(e.id, Decimal("0"))
            committed_remaining += max(full - paid, Decimal("0"))

    # Per-student rows for the selected year (retrospective record).
    status_labels = dict(TuitionEnrollment.Status.choices)
    enrollment_rows = []
    for e in sorted(
        enrollments,
        key=lambda e: (e.user.last_name or "", e.user.first_name or "", e.user.email),
    ):
        paid = paid_by_enrollment.get(e.id, Decimal("0"))
        remaining = (
            Decimal("0") if e.status == TuitionEnrollment.Status.SKIPPING
            else max(full - paid, Decimal("0"))
        )
        enrollment_rows.append({
            "user": e.user, "status": e.status,
            "status_label": status_labels.get(e.status, e.status),
            "source": e.source, "source_label": e.get_source_display(),
            "notes": e.notes,
            "paid": paid, "remaining": remaining,
        })

    # Forward-looking sections — current period only (live in-training roster).
    in_training_count = 0
    undecided_users = []
    role_breakdown_tuition = []
    reconciliation_users = []
    undecided_owed = Decimal("0")
    if is_current:
        in_training_qs = User.objects.filter(
            is_active=True, profile__is_persona=False,
            profile__standing=Profile.Standing.ACTIVE,
            profile__role__in=Profile.IN_TRAINING_ROLES,
        )
        in_training_count = in_training_qs.count()
        undecided_users = list(in_training_qs.exclude(id__in=decided_user_ids))
        undecided_owed = full * len(undecided_users)
        enrollment_by_user = {e.user_id: e for e in enrollments}
        role_labels = dict(Profile.Role.choices)
        for role in sorted(Profile.IN_TRAINING_ROLES):
            users_in_role = in_training_qs.filter(profile__role=role)
            total_in_role = users_in_role.count()
            in_role_user_ids = set(users_in_role.values_list("id", flat=True))
            decided_in_role = len(in_role_user_ids & decided_user_ids)
            committed_in_role = sum(
                1 for uid in in_role_user_ids
                if enrollment_by_user.get(uid)
                and enrollment_by_user[uid].status == TuitionEnrollment.Status.COMMITTED
            )
            role_breakdown_tuition.append({
                "role":           role,
                "role_label":     role_labels.get(role, role),
                "total":          total_in_role,
                "decided":        decided_in_role,
                "undecided":      total_in_role - decided_in_role,
                "committed_only": committed_in_role,
            })
        for u in undecided_users:
            reconciliation_users.append({"user": u, "reason": "Undecided", "status": None})
        for e in enrollments:
            if e.status == TuitionEnrollment.Status.COMMITTED:
                reconciliation_users.append({
                    "user": e.user, "reason": "Committed, no payment received",
                    "status": e.status,
                })
        reconciliation_users.sort(
            key=lambda r: (r["user"].last_name or "", r["user"].first_name or "", r["user"].email)
        )

    tuition_status_counts = [
        {"key": k, "label": label, "count": status_counter.get(k, 0)}
        for k, label in _TUITION_STATUS_ORDER
    ]
    if is_current:
        tuition_status_counts.append(
            {"key": "undecided", "label": "Undecided", "count": len(undecided_users)}
        )

    chart_tuition_money = {
        "collected": float(total_collected),
        "planned": float(committed_remaining),
        "owed": float(undecided_owed),
    }

    return {
        "tuition_period":              period,
        "tuition_selected_period":     period,
        "tuition_is_current":          is_current,
        "tuition_status_counts":       tuition_status_counts,
        "tuition_role_breakdown":      role_breakdown_tuition,
        "tuition_reconciliation_users": reconciliation_users,
        "tuition_enrollment_rows":     enrollment_rows,
        "tuition_confirmed_pct":       _confirmed_pct(e.source for e in enrollments),
        "tuition_in_training_count":   in_training_count,
        "tuition_total_collected":     total_collected,
        "tuition_committed_remaining": committed_remaining,
        "tuition_undecided_owed":      undecided_owed,
        "tuition_outstanding":         committed_remaining + undecided_owed,
        "chart_tuition_money_json":    json.dumps(chart_tuition_money),
    }


def _treasurer_tuition_longitudinal() -> dict:
    """All-years tuition aggregation for the longitudinal table + charts.

    Two aggregate queries (status counts + collected) keyed by period, so this
    stays O(1) in query count regardless of how many academic years exist.
    """
    periods = list(TuitionPeriod.objects.order_by("-start_date"))

    status_by_period: dict[int, dict[str, int]] = {}
    for row in (
        TuitionEnrollment.objects.values("tuition_period_id", "status")
        .annotate(n=Count("id"))
    ):
        status_by_period.setdefault(row["tuition_period_id"], {})[row["status"]] = row["n"]

    collected_by_period: dict[int, Decimal] = {}
    for row in (
        Payment.objects.filter(
            payment_type=Payment.Type.TUITION,
            status=Payment.Status.SUCCEEDED,
        )
        .values("tuition_installment__enrollment__tuition_period")
        .annotate(s=Sum("amount"))
    ):
        pid = row["tuition_installment__enrollment__tuition_period"]
        if pid is not None:
            collected_by_period[pid] = row["s"] or Decimal("0")

    # Fold in installment-less backfill (Stripe/treasurer imports). Member-
    # assigned payments go to their chosen AY; the rest bucket by payment date.
    period_id_by_ay = {ay_of(p.start_date): p.id for p in periods}
    base = Payment.objects.filter(
        payment_type=Payment.Type.TUITION,
        status=Payment.Status.SUCCEEDED,
        tuition_installment__isnull=True,
    )
    for pid, amount in base.filter(
        tuition_period__isnull=False
    ).values_list("tuition_period_id", "amount"):
        collected_by_period[pid] = collected_by_period.get(pid, Decimal("0")) + amount
    for paid_at, amount in base.filter(
        tuition_period__isnull=True, paid_at__isnull=False
    ).values_list("paid_at", "amount"):
        pid = period_id_by_ay.get(ay_of(paid_at.date()))
        if pid is not None:
            collected_by_period[pid] = collected_by_period.get(pid, Decimal("0")) + amount

    rows = []
    for p in periods:
        sc = status_by_period.get(p.id, {})
        rows.append({
            "period":       p,
            "paid_in_full": sc.get("paid_in_full", 0),
            "payment_plan": sc.get("payment_plan", 0),
            "committed":    sc.get("committed", 0),
            "skipping":     sc.get("skipping", 0),
            "enrolled":     sum(sc.values()),
            "collected":    collected_by_period.get(p.id, Decimal("0")),
        })

    chron = list(reversed(rows))
    labels = [r["period"].name for r in chron]
    chart_collected = {"labels": labels, "totals": [float(r["collected"]) for r in chron]}
    chart_status = {
        "labels": labels,
        "paid_in_full": [r["paid_in_full"] for r in chron],
        "payment_plan": [r["payment_plan"] for r in chron],
        "committed":    [r["committed"] for r in chron],
        "skipping":     [r["skipping"] for r in chron],
    }
    return {
        "tuition_year_rows":             rows,
        "chart_tuition_collected_json":  json.dumps(chart_collected),
        "chart_tuition_status_json":     json.dumps(chart_status),
    }


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


@login_required
def dues_pay(request):
    """Membership dues entry point (REG-12) — tiered by role per DuesPeriod.

    Falls back to the per-tier defaults from settings if no period covers
    today (which shouldn't happen in production once the bootstrap data
    migration + auto-rollover command are running).
    """
    from .dues import user_paid_for_period
    from .models import DuesPeriod

    period = DuesPeriod.current()

    # Already paid for the current cycle — show a friendly status panel.
    if period is not None and user_paid_for_period(request.user, period):
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
        if payment.registration_id:
            Registration.objects.filter(
                pk=payment.registration_id,
                status=Registration.Status.PAID,
            ).update(status=Registration.Status.REFUNDED)


def _tuition_tab_url(**params) -> str:
    """The tuition tab of the member's Formation hub — where tuition lives now.
    Extra params (e.g. ``stripe='success'``) ride along."""
    from urllib.parse import urlencode

    from django.urls import reverse

    query = {"tab": "tuition", **{k: v for k, v in params.items() if v}}
    return reverse("formation:formation") + "?" + urlencode(query)


@login_required
def tuition_decision(request):
    """Record the annual tuition decision (M7.5).

    The tuition surface (decision form, installments, payment history) lives on
    the member's Formation hub. This endpoint only handles the decision form's
    POST; every other request just redirects there.
    """
    profile = request.user.profile
    period = TuitionPeriod.current()

    if request.method == "POST" and profile.owes_tuition and period is not None:
        form = TuitionDecisionForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                TuitionEnrollment.objects.update_or_create(
                    user=request.user, tuition_period=period,
                    defaults={"status": form.cleaned_data["status"]},
                )
            messages.success(request, "Your tuition decision has been recorded.")
        else:
            messages.error(request, "Please choose one of the listed options.")
    return redirect(_tuition_tab_url())


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
        return redirect(_tuition_tab_url())
    period = TuitionPeriod.current()
    if period is None:
        return redirect(_tuition_tab_url())
    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()
    if enrollment is None:
        return redirect(_tuition_tab_url())
    if enrollment.installments.exists():
        # Already on a payment plan / has installments — direct to pay one
        # rather than minting a parallel "full" installment.
        return redirect(_tuition_tab_url())
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
        return redirect(_tuition_tab_url())
    period = TuitionPeriod.current()
    if period is None:
        return redirect(_tuition_tab_url())
    enrollment = TuitionEnrollment.objects.filter(
        user=request.user, tuition_period=period,
    ).first()
    if enrollment is None or enrollment.status != TuitionEnrollment.Status.PAYMENT_PLAN:
        return redirect(_tuition_tab_url())
    if enrollment.installments.exists():
        return redirect(_tuition_tab_url())
    try:
        count = int(request.POST.get("installment_count", "0"))
    except (TypeError, ValueError):
        return redirect(_tuition_tab_url())
    if count not in (2, 9):
        return redirect(_tuition_tab_url())

    schedule = _build_installment_schedule(period, count)
    with transaction.atomic():
        for seq, (due_date, amount) in enumerate(schedule, start=1):
            TuitionInstallment.objects.create(
                enrollment=enrollment, sequence=seq,
                due_date=due_date, amount=amount,
            )
    return redirect(_tuition_tab_url())


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
        return redirect(_tuition_tab_url())
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


@login_required
@require_POST
def my_payments_update(request):
    """A member edits their *own* payments from the My Payments table: the
    **type** (re-categorizing e.g. a provisional/ASSUMED charge — promoted to
    ``SELF_REPORTED``), a **note** the treasurer can see (``member_note``), and —
    for tuition payments — the **academic year** it counts toward
    (``tuition_period``, resolving an ambiguous August date). Per-row fields
    ``type_<id>`` / ``note_<id>`` / ``period_<id>``; constrained to the member's
    own payments so a stale/forged id can't touch anyone else's."""
    from accounts.models import Source

    periods = {str(tp.id): tp for tp in TuitionPeriod.objects.all()}
    changed = 0
    for p in Payment.objects.filter(user=request.user):
        fields = []

        new_type = request.POST.get(f"type_{p.id}")
        if new_type in Payment.Type.values and new_type != p.payment_type:
            p.payment_type = new_type
            p.source = Source.SELF_REPORTED
            fields += ["payment_type", "source"]

        note_key = f"note_{p.id}"
        if note_key in request.POST:
            note = (request.POST.get(note_key) or "").strip()[:1000]
            if p.member_note != note:
                p.member_note = note
                fields.append("member_note")

        period_key = f"period_{p.id}"
        if period_key in request.POST:
            new_period = periods.get(request.POST.get(period_key) or "")
            new_period_id = new_period.id if new_period else None
            if p.tuition_period_id != new_period_id:
                p.tuition_period_id = new_period_id
                fields.append("tuition_period")

        if fields:
            p.save(update_fields=fields)
            changed += 1

    messages.success(
        request,
        f"Saved {changed} payment update(s)." if changed else "No changes to save.",
    )
    return redirect(_tuition_tab_url())
