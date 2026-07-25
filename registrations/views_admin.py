"""The Registration Admin console (/admin-tools/registrations/) — task #470.

Cross-event registration management for the (future) Registrar, the Web
Coordinator, and the Programming Committee. Follows the referrals-console
tab pattern; the denied-user convention is Http404 (like the PC admin).
"""

from __future__ import annotations

import datetime as _dt
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from .models import Registration
from .permissions import can_administer_registrations

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
    ("help",          "Help"),
]


def _tab_links() -> list[tuple[str, str, str]]:
    """[(key, label, url), ...] for core/_admin_tab_nav.html."""
    name_to_url = {
        "registrations": reverse("registrations:registrar"),
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
    return _render(request, "registrations",
                   "registrations/registrar/registrations.html", {
        "page": page,
        "pending": pending,
        "filters": filters,
        "querystring": querydict.urlencode(),
        "status_choices": Registration.Status.choices,
        "event_choices": Event.objects.filter(
            registrations__isnull=False
        ).distinct().order_by("-start_date", "title"),
    })


@registrar_required
def registrar_help(request):
    from core.docs import render_doc
    return _render(request, "help", "registrations/registrar/help.html", {
        "doc_html": render_doc("registrar-guide"),
    })
