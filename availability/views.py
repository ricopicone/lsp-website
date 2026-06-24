"""The Applications Coordinator console (/admin-tools/availability/).

Gated to the Applications Coordinator staff role + superusers (the data is
members-internal). Surfaces:

- **grid** — the editable table of every Analyst × every function; the
  coordinator sets each cell's status and saves.
- **analyst** — one analyst's current status + note per function, the full
  span history (the audit trail), and the academic-year coverage ("credit").
- **settings** / **templates** — the reminder automation toggle and the
  editable reminder wording.
- **send reminders** — emails every analyst the review request (bell + email).
"""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import notifications, services
from .forms import AvailabilitySettingsForm, ReminderTemplateForm
from .models import AnalystFunction, AvailabilitySettings, AvailabilitySpan, ReminderTemplate
from .permissions import can_manage_availability

Status = AvailabilitySpan.Status


def coordinator_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_manage_availability(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


#: (key, label) for the console tabs, in display order. "Applications" links to
#: the coordinator's admissions console — the same role's other surface.
TABS = [
    ("applications", "Applications"),
    ("grid", "Analyst availability"),
    ("overview", "Overview"),
    ("settings", "Settings"),
    ("templates", "Reminder message"),
]


def _tab_links() -> list[tuple[str, str, str]]:
    name_to_url = {
        "applications": reverse("admissions:coordinator_dashboard"),
        "grid": reverse("availability:grid"),
        "overview": reverse("availability:overview"),
        "settings": reverse("availability:settings"),
        "templates": reverse("availability:templates"),
    }
    return [(key, label, name_to_url[key]) for key, label in TABS]


def _render(request, tab_key: str, template: str, ctx: dict):
    return render(request, template, {**ctx, "tab_key": tab_key, "tabs": _tab_links()})


def _console_profiles():
    """Analysts the console manages — eligible role, real, active members,
    in directory order."""
    return (
        services.eligible_profiles()
        .filter(is_persona=False, user__is_active=True)
        .select_related("user")
        .order_by("user__last_name", "user__first_name", "user__email")
    )


def _open_spans_map(profiles, functions) -> dict[tuple[int, int], AvailabilitySpan]:
    """{(profile_id, function_id): open span} for the given profiles/functions."""
    spans = AvailabilitySpan.objects.filter(
        profile__in=profiles, function__in=functions, end_date__isnull=True
    )
    return {(s.profile_id, s.function_id): s for s in spans}


# ---- Grid ----------------------------------------------------------------


@coordinator_required
def grid(request):
    functions = list(AnalystFunction.objects.filter(is_active=True))
    profiles = list(_console_profiles())

    if request.method == "POST":
        return _save_grid(request, profiles, functions)

    open_map = _open_spans_map(profiles, functions)
    notes = {p.pk: services.current_note(p) for p in profiles}
    rows = []
    for profile in profiles:
        cells = []
        for fn in functions:
            span = open_map.get((profile.pk, fn.pk))
            cells.append({
                "function": fn,
                "status": span.status if span else Status.UNKNOWN,
                "field": f"cell_{profile.pk}_{fn.pk}",
            })
        rows.append({"profile": profile, "cells": cells, "note": notes[profile.pk]})

    return _render(request, "grid", "availability/grid.html", {
        "functions": functions,
        "rows": rows,
        "status_choices": Status.choices,
    })


def _save_grid(request, profiles, functions):
    open_map = _open_spans_map(profiles, functions)
    valid_status = set(Status.values)

    changed = 0
    for profile in profiles:
        for fn in functions:
            new_status = request.POST.get(f"cell_{profile.pk}_{fn.pk}")
            if new_status not in valid_status:
                continue
            span = open_map.get((profile.pk, fn.pk))
            if span and span.status == new_status:
                continue  # unchanged
            services.set_availability(
                profile, fn, new_status,
                source=AvailabilitySpan.Source.COORDINATOR,
                by=request.user,
            )
            changed += 1
        note = (request.POST.get(f"note_{profile.pk}") or "").strip()
        if services.set_note(profile, note, by=request.user) is not None:
            changed += 1

    if changed:
        messages.success(request, f"Saved {changed} change{'s' if changed != 1 else ''}.")
    else:
        messages.info(request, "No changes to save.")
    return redirect("availability:grid")


@coordinator_required
def overview(request):
    """At-a-glance coverage: how many analysts are available for each function
    now, plus a monthly history chart."""
    return _render(request, "overview", "availability/overview.html", {
        "coverage": services.current_coverage(),
        "series": services.coverage_series(months=12),
    })


# ---- Per-analyst (history + coverage) ------------------------------------


@coordinator_required
def analyst(request, pk):
    profile = get_object_or_404(_console_profiles(), pk=pk)
    functions = list(AnalystFunction.objects.filter(is_active=True))

    if request.method == "POST":
        if request.POST.get("action") == "note":
            return _save_analyst_note(request, profile)
        return _save_analyst_cell(request, profile)

    current_ay, upcoming_ay = services.current_and_upcoming_ay()
    open_map = _open_spans_map([profile], functions)
    all_spans = list(
        AvailabilitySpan.objects.filter(profile=profile)
        .select_related("function", "created_by")
        .order_by("function__display_order", "-start_date")
    )
    history_by_fn: dict[int, list] = {}
    for span in all_spans:
        history_by_fn.setdefault(span.function_id, []).append(span)

    fn_rows = []
    for fn in functions:
        span = open_map.get((profile.pk, fn.pk))
        fn_rows.append({
            "function": fn,
            "status": span.status if span else Status.UNKNOWN,
            "history": history_by_fn.get(fn.pk, []),
            "coverage_current": round(
                services.coverage_fraction(profile, fn, current_ay) * 100
            ),
            "coverage_upcoming": round(
                services.coverage_fraction(profile, fn, upcoming_ay) * 100
            ),
        })

    return _render(request, "grid", "availability/analyst.html", {
        "profile": profile,
        "fn_rows": fn_rows,
        "status_choices": Status.choices,
        "current_ay": current_ay,
        "upcoming_ay": upcoming_ay,
        "current_note": services.current_note(profile),
        "note_history": services.note_history(profile),
    })


def _save_analyst_cell(request, profile):
    fn = get_object_or_404(AnalystFunction, pk=request.POST.get("function"))
    status = request.POST.get("status")
    if status not in set(Status.values):
        raise PermissionDenied
    services.set_availability(
        profile, fn, status,
        source=AvailabilitySpan.Source.COORDINATOR,
        by=request.user,
    )
    messages.success(request, f"Updated {fn.name} for {profile.display_full_name}.")
    return redirect("availability:analyst", pk=profile.pk)


def _save_analyst_note(request, profile):
    note = (request.POST.get("note") or "").strip()
    if services.set_note(profile, note, by=request.user) is not None:
        messages.success(request, f"Saved a note for {profile.display_full_name}.")
    else:
        messages.info(request, "Note unchanged.")
    return redirect("availability:analyst", pk=profile.pk)


# ---- Settings, templates, reminders --------------------------------------


@coordinator_required
def settings_view(request):
    config = AvailabilitySettings.load()
    form = AvailabilitySettingsForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Availability settings saved.")
        return redirect("availability:settings")
    return _render(request, "settings", "availability/settings.html", {"form": form})


@coordinator_required
def template_edit(request):
    template = ReminderTemplate.get(ReminderTemplate.Key.REVIEW_REQUEST)
    form = ReminderTemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Reminder message saved.")
        return redirect("availability:templates")
    return _render(request, "templates", "availability/templates.html", {
        "template": template, "form": form,
    })


@login_required
@require_POST
def self_update(request):
    """An analyst sets their own availability from the profile editor.

    Self-service complement to the coordinator grid (source=self); the
    coordinator can always override. Gated to eligible analysts editing their
    own profile."""
    profile = request.user.profile
    if not services.is_eligible(profile):
        raise PermissionDenied
    valid_status = set(Status.values)
    changed = 0
    for fn in AnalystFunction.objects.filter(is_active=True):
        status = request.POST.get(f"fn_{fn.pk}")
        if status not in valid_status:
            continue
        if services.current_status(profile, fn) == status:
            continue
        services.set_availability(
            profile, fn, status,
            source=AvailabilitySpan.Source.SELF, by=request.user,
        )
        changed += 1
    if changed:
        messages.success(request, "Your availability has been updated.")
    else:
        messages.info(request, "No changes to your availability.")

    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(reverse("profile_edit") + "#availability")


@coordinator_required
@require_POST
def send_reminders(request):
    sent = 0
    for profile in _console_profiles():
        notifications.request_review(profile.user)
        sent += 1
    messages.success(
        request,
        f"Sent an availability review request to {sent} "
        f"analyst{'s' if sent != 1 else ''}.",
    )
    return redirect("availability:grid")
