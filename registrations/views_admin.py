"""The Registration Admin console (/admin-tools/registrations/) — task #470.

Cross-event registration management for the (future) Registrar, the Web
Coordinator, and the Programming Committee. Follows the referrals-console
tab pattern; the denied-user convention is Http404 (like the PC admin).
"""

from __future__ import annotations

import csv
import datetime as _dt
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from payments import notifications as notify_payments

from .models import Registration
from .permissions import can_administer_registrations
from .services import comp_registration

PAGE_SIZE = 50


def registrar_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_administer_registrations(request.user):
            raise Http404()
        return view(request, *args, **kwargs)
    return wrapper


#: (key, label) for the console's tabs, in display order.
TABS = [
    ("registrations", "Registrations"),
    ("events",        "Events"),
    ("help",          "Help"),
]


def _tab_links() -> list[tuple[str, str, str]]:
    """[(key, label, url), ...] for core/_admin_tab_nav.html."""
    name_to_url = {
        "registrations": reverse("registrations:registrar"),
        "events":        reverse("registrations:registrar_events"),
        "help":          reverse("registrations:registrar_help"),
    }
    return [(key, label, name_to_url[key]) for key, label in TABS]


def _render(request, tab_key: str, template: str, ctx: dict):
    return render(request, template, {
        **ctx, "tab_key": tab_key, "tabs": _tab_links(),
    })


#: Statuses shown under the default "active" filter.
ACTIVE_STATUSES = (
    Registration.Status.PENDING_APPROVAL,
    Registration.Status.AWAITING_PAYMENT,
    Registration.Status.PAID,
    Registration.Status.COMPED,
)


def _parse_date(raw: str) -> str:
    """Echo back a valid ISO date, or '' for anything malformed."""
    try:
        _dt.date.fromisoformat(raw)
    except ValueError:
        return ""
    return raw


def _filtered_registrations(request):
    """The Registrations-tab queryset for the current GET filters.

    Returns ``(qs, filters)`` where ``filters`` echoes the applied values
    back to the template (and the CSV export reuses both).
    """
    qs = Registration.objects.select_related(
        "user", "user__profile", "event", "price_tier", "pricing_code",
    ).order_by("-created_at")

    status = request.GET.get("status", "active")
    if status == "active":
        qs = qs.filter(status__in=ACTIVE_STATUSES)
    elif status in Registration.Status.values:
        qs = qs.filter(status=status)
    else:
        status = "all"

    event_id = request.GET.get("event") or ""
    if event_id.isdigit():
        qs = qs.filter(event_id=int(event_id))
    else:
        event_id = ""

    since = _parse_date(request.GET.get("since") or "")
    until = _parse_date(request.GET.get("until") or "")
    if since:
        qs = qs.filter(created_at__date__gte=since)
    if until:
        qs = qs.filter(created_at__date__lte=until)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(user__email__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
        )
    return qs, {"status": status, "event": event_id, "since": since,
                "until": until, "q": q}


@registrar_required
def registrar_registrations(request):
    from events.models import Event

    qs, filters = _filtered_registrations(request)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    pending = (
        Registration.objects.filter(status=Registration.Status.PENDING_APPROVAL)
        .select_related("user", "event")
        .order_by("created_at")
    )
    querydict = request.GET.copy()
    querydict.pop("page", None)
    unfiltered = filters == {"status": "active", "event": "", "since": "",
                             "until": "", "q": ""}
    return _render(request, "registrations",
                   "registrations/registrar/registrations.html", {
        "page": page,
        # The needs-attention strip is a landing-view alert; filtered views
        # are targeted work, so it hides rather than leak unmatched rows.
        "pending": pending if unfiltered else [],
        "filters": filters,
        "querystring": querydict.urlencode(),
        "status_choices": Registration.Status.choices,
        "event_choices": Event.objects.filter(
            registrations__isnull=False
        ).distinct().order_by("-start_date", "title"),
    })


@registrar_required
def registrar_registrations_csv(request):
    """CSV of the Registrations tab under the current filters (REG-15 sibling)."""
    qs, _filters = _filtered_registrations(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="registrations.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "event", "first_name", "last_name", "email", "role",
        "tier", "amount", "status", "pricing_code", "registered_at",
    ])
    for r in qs:
        writer.writerow([
            r.event.title,
            r.user.first_name,
            r.user.last_name,
            r.user.email,
            getattr(getattr(r.user, "profile", None), "role", ""),
            r.price_tier.get_audience_display(),
            r.quoted_amount,
            r.status,
            r.pricing_code.code if r.pricing_code else "",
            r.created_at.isoformat(),
        ])
    return response


def _back(request):
    """Redirect target preserving the list's filters (posted as ``next``)."""
    nxt = request.POST.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts=None):
        return redirect(nxt)
    return redirect("registrations:registrar")


@registrar_required
@require_POST
def registrar_approve(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    if reg.approve(request.user):
        if reg.needs_payment:
            notify_payments.registration_approved(reg)
        else:
            notify_payments.registration_confirmed(reg)
        messages.success(request, f"Approved {reg.user.email} for {reg.event.title}.")
    else:
        messages.warning(request, "That registration wasn't pending approval.")
    return _back(request)


@registrar_required
@require_POST
def registrar_decline(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    if reg.decline(request.user, (request.POST.get("reason") or "").strip()):
        notify_payments.registration_declined(reg)
        messages.success(request, f"Declined {reg.user.email} for {reg.event.title}.")
    else:
        messages.warning(request, "That registration wasn't pending approval.")
    return _back(request)


@registrar_required
@require_POST
def registrar_comp(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    comped, email_ok = comp_registration(
        reg, request.user, via="registration admin",
    )
    if comped and email_ok:
        messages.success(request, f"Comped {reg.user.email} for {reg.event.title}.")
    elif comped:
        messages.warning(request, "Comped, but the confirmation email failed.")
    else:
        messages.warning(request, "Only awaiting-payment registrations can be comped.")
    return _back(request)


@registrar_required
@require_POST
def registrar_note(request, reg_id: int):
    reg = get_object_or_404(Registration, pk=reg_id)
    note = (request.POST.get("note") or "").strip()
    if note:
        reg.staff_notes = (reg.staff_notes or "") + (
            f"\n[{timezone.localdate().isoformat()}] {note} "
            f"— {request.user.email} via registration admin."
        )
        reg.save(update_fields=("staff_notes",))
        messages.success(request, "Note added.")
    return _back(request)


@registrar_required
def registrar_events(request):
    """One row per current/upcoming-AY event: status + registration counts +
    the open/close toggle. 'Current' = events whose start_date falls on or
    after the start of the current academic year."""
    from django.db.models import Count

    from events.models import (
        Event,
        academic_year_date_range,
        current_academic_year,
    )

    ay_start, _ = academic_year_date_range(current_academic_year())
    events = (
        Event.objects.filter(start_date__gte=ay_start)
        .annotate(
            n_pending=Count("registrations", filter=Q(
                registrations__status=Registration.Status.PENDING_APPROVAL)),
            n_awaiting=Count("registrations", filter=Q(
                registrations__status=Registration.Status.AWAITING_PAYMENT)),
            n_paid=Count("registrations", filter=Q(
                registrations__status=Registration.Status.PAID)),
            n_comped=Count("registrations", filter=Q(
                registrations__status=Registration.Status.COMPED)),
        )
        .order_by("start_date", "title")
    )
    return _render(request, "events", "registrations/registrar/events.html", {
        "events": events,
    })


@registrar_required
@require_POST
def registrar_event_toggle(request, pk: int):
    """Open or close registration for one event. Mirrors the PC bulk view's
    convention (events/views.py program_admin_registration_bulk): open flips
    DRAFT or CLOSED → OPEN; close flips OPEN → CLOSED. Publishing
    (Event.published) is a separate decision made elsewhere."""
    from events.models import Event

    event = get_object_or_404(Event, pk=pk)
    action = request.POST.get("action")
    if action == "open" and event.status in (
        Event.Status.DRAFT, Event.Status.CLOSED,
    ):
        event.status = Event.Status.OPEN
        event.save(update_fields=("status",))
        messages.success(request, f"Registration opened for {event.title}.")
    elif action == "close" and event.status == Event.Status.OPEN:
        event.status = Event.Status.CLOSED
        event.save(update_fields=("status",))
        messages.success(request, f"Registration closed for {event.title}.")
    else:
        messages.warning(
            request,
            f"No change — {event.title} is "
            f"{event.get_status_display().lower()}.",
        )
    return redirect("registrations:registrar_events")


@registrar_required
def registrar_help(request):
    from core.docs import render_doc
    return _render(request, "help", "registrations/registrar/help.html", {
        "doc_html": render_doc("registrar-guide"),
    })
