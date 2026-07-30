"""Public-facing event views (PROG-1, PROG-7, PROG-8, REG-10)."""

from __future__ import annotations

import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import is_lsp_member
from core.access import gate_or_login

from .forms import EventEditForm, PricingCodeForm
from .models import (
    ArchivedProgram,
    Event,
    PricingCode,
    academic_year_date_range,
    current_academic_year,
)
from .permissions import can_edit_event


def _faculty_view_url(event: Event) -> str:
    """Where the faculty tools (roster + pricing codes) live for an event.

    Offering events (seminar / reading group) now host these on their
    Workspace Roster tab; everything else keeps the event page's faculty view.
    """
    if event.event_type in Event.ANNUAL_PROGRAM_TYPES and event.workgroup_id:
        return event.workgroup.get_absolute_url() + "?tab=roster"
    return reverse("events:detail", args=[event.slug]) + "?view=faculty"


def event_summary_context(event, user) -> dict:
    """Context for the shared ``events/_event_summary.html`` partial (faculty,
    about, sessions, pricing, register/your-status CTA). Used by the standalone
    event page *and* the seminar Workspace Overview so they never drift."""
    from registrations.models import Registration

    user_registration = None
    if getattr(user, "is_authenticated", False):
        user_registration = (
            Registration.objects.filter(user=user, event=event)
            .exclude(status__in=(
                Registration.Status.CANCELLED,
                Registration.Status.REFUNDED,
            ))
            .order_by("-created_at")
            .first()
        )
    # PAID and COMPED both grant access — comp means the fee was waived.
    has_paid_registration = bool(
        user_registration
        and user_registration.status in (
            Registration.Status.PAID,
            Registration.Status.COMPED,
        )
    )
    from events.permissions import can_edit_event
    from video.services import daily_enabled, presence_names, room_participant_count

    # Whoever runs the event — faculty, a PC-organized event's presenters, the
    # PC, staff — sees the access details (venue / meeting link) without a
    # registration. They never pay for their own event, so the payment gate
    # would withhold the meeting details from the people leading the meeting.
    can_host = can_edit_event(user, event)
    daily_on = daily_enabled()
    # Real Daily presence in the event's room (people actually meeting now).
    # No provisioning: counts only an already-created room, else 0 (no API call).
    # Offering events meet in their workgroup's room; one-off events own theirs.
    from video.services import room_owner_for_event

    owner = room_owner_for_event(event)  # read-only: never provisions
    room = getattr(owner, "video_room", None) if owner is not None else None
    room_participants = room_participant_count(room) if daily_on else 0
    room_participant_names = presence_names(room) if daily_on else []
    from video.models import Recording

    recordings = [
        r for r in Recording.objects.filter(event=event, status=Recording.Status.READY)
        if r.listing_visible_to(user)
    ]
    next_session = event.next_session()
    from django.utils import timezone as _tz

    sessions = list(event.sessions.order_by("start_at"))
    # Above-the-fold preview for long session lists: the next few meetings
    # (the full table collapses behind a <details>).
    sessions_upcoming = [s for s in sessions if s.start_at >= _tz.now()][:3]
    return {
        "event": event,
        "sessions": sessions,
        "sessions_upcoming": sessions_upcoming,
        "price_tiers": event.price_tiers.select_related("session").order_by(
            "session", "audience"
        ),
        "user_registration": user_registration,
        "has_paid_registration": has_paid_registration,
        "daily_enabled": daily_on,
        "event_is_live": event.is_live(),
        "event_next_session_at": next_session.start_at if next_session else None,
        "can_host": can_host,
        "show_access_info": bool(event.access_info) and (
            has_paid_registration or can_host
        ),
        "event_room_live": bool(room_participants),
        "event_room_participants": room_participants,
        "event_room_participant_names": room_participant_names,
        "recordings": recordings,
    }


def event_list(request):
    """Public chronological list of upcoming standalone events (PROG-1).

    Excludes annual-program types (seminars, reading groups, cartels) —
    those have a dedicated home at /program/, gated by Program visibility.
    Members-only events are hidden from non-members — anonymous visitors and
    authenticated outside registrants (auditors) alike.
    """
    today = timezone.now().date()
    events = (
        Event.objects.filter(published=True, end_date__gte=today)
        .exclude(event_type__in=Event.ANNUAL_PROGRAM_TYPES)
        .order_by("start_date", "title")
    )
    if not is_lsp_member(request.user):
        events = events.filter(visibility=Event.Visibility.PUBLIC)
    return render(request, "events/event_list.html", {"events": events})


def program(request):
    """Annual program: seminars + other offerings for an academic year (PROG-2).

    Visibility is gated by ``Program.is_public_now`` for the requested
    academic year. If the Program isn't public yet (and the user isn't
    staff / on the Program Committee), 404. Program Committee members
    and Django staff see all programs (any AY) for preview.
    """
    from .models import Program
    from .permissions import is_program_committee
    year = request.GET.get("year")
    if not year:
        # Default to the newest publicly-visible program (e.g. a fall program
        # published in July, before its academic year begins), falling back
        # to the calendar's current AY when nothing is published yet.
        year = next(
            (p.academic_year for p in Program.objects.all() if p.is_public_now),
            None,
        ) or current_academic_year()
    try:
        academic_year_date_range(year)
    except (ValueError, IndexError):
        raise Http404("Unknown academic year") from None

    program_obj = Program.for_year(year)
    can_preview = request.user.is_authenticated and (
        request.user.is_staff or is_program_committee(request.user)
    )
    if program_obj is None or (not program_obj.is_public_now and not can_preview):
        raise Http404("Program not available for this academic year.")

    events_qs = (
        program_obj.events.all()
        .order_by("start_date", "title")
    )
    seminars = list(events_qs.filter(event_type=Event.Type.SEMINAR))
    # Reading groups are listed below as standing workgroups (their term events
    # aren't shown here); cartels likewise have their own section.
    offerings = list(events_qs.filter(event_type=Event.Type.CARTEL))

    # Year-picker options: every Program that's publicly visible right
    # now, plus all programs if the viewer can preview. Always include the
    # current AY label so an empty-program year doesn't vanish.
    all_programs = Program.objects.all()
    if not can_preview:
        all_programs = [p for p in all_programs if p.is_public_now]
    distinct_years = sorted({p.academic_year for p in all_programs}, reverse=True)
    current = current_academic_year()
    if current not in distinct_years:
        distinct_years.insert(0, current)

    # Self-formed cartels that existed at any point during this AY are part of
    # the program too (publicly — name + guiding question; their roster/content
    # stay members-only). Cartels aren't program-owned Events, so they're found
    # by date overlap rather than the Program FK.
    from cartels.models import Cartel
    from workgroups.models import Workgroup

    cartels = Cartel.objects.in_academic_year(year)
    # Standing reading groups that span this academic year (by date overlap —
    # they're continuous workgroups now, not per-year events).
    reading_groups = [
        wg for wg in Workgroup.objects.filter(kind=Workgroup.Kind.READING_GROUP)
        if wg.overlaps_academic_year(year)
    ]

    return render(request, "events/program.html", {
        "year":            year,
        "program":         program_obj,
        "seminars":        seminars,
        "offerings":       offerings,
        "cartels":         cartels,
        "reading_groups":  reading_groups,
        "available_years": distinct_years,
        "is_current_year": year == current,
        "is_preview":      not program_obj.is_public_now,
        "can_propose_seminar": is_lsp_member(request.user),
        "has_archive":     ArchivedProgram.objects.exists(),
    })


def program_archive(request):
    """A list of past program PDFs (years predating the live Program model).

    The list is public so anyone can see which years exist; the PDFs
    themselves download only for members via ``program_archive_download``."""
    programs = list(ArchivedProgram.objects.all())  # ordered -academic_year
    return render(request, "events/program_archive.html", {
        "programs": programs,
        "is_member": is_lsp_member(request.user),
    })


def program_archive_download(request, pk: int):
    """Serve an archived program PDF — members only (for now)."""
    if not is_lsp_member(request.user):
        # Anonymous → login (return here after sign-in); signed-in non-member → 404.
        return gate_or_login(request)
    archived = get_object_or_404(ArchivedProgram, pk=pk)
    if not archived.file:
        raise Http404()
    filename = archived.file.name.rsplit("/", 1)[-1]
    return FileResponse(archived.file.open("rb"), as_attachment=False, filename=filename)


def event_detail(request, slug: str):
    """Render the public event page for a published event (PROG-1).

    Unpublished events 404 for anonymous and non-staff users; staff and
    faculty-editors see them so they can preview before flipping
    ``published``. If the current user has a *paid* Registration for the
    event, the page additionally shows the ``access_info`` block (REG-8).
    """
    event = get_object_or_404(
        Event.objects
        .prefetch_related("sessions", "price_tiers")
        .select_related("program", "workgroup"),
        slug=slug,
    )
    can_edit = can_edit_event(request.user, event)
    if not event.is_public_now and not can_edit:
        raise Http404("Event not found.")

    # Offering events (seminar / reading group) live in their Workspace now —
    # that's the canonical page (faculty tooling moved to its Roster tab).
    if event.event_type in Event.ANNUAL_PROGRAM_TYPES and event.workgroup_id:
        return redirect(event.workgroup.get_absolute_url())

    show_faculty_view = (
        can_edit and request.GET.get("view") == "faculty"
    )

    # Cross-link to the Workspace for offering events (seminar / reading group)
    # that the viewer may see — the durable collaborative home.
    workspace_url = None
    wg = event.workgroup
    if (wg and event.event_type in Event.ANNUAL_PROGRAM_TYPES
            and wg.landing_visible_to(request.user)):
        workspace_url = wg.get_absolute_url()

    context = {
        "can_edit": can_edit,
        "show_faculty_view": show_faculty_view,
        "workspace_url": workspace_url,
        **event_summary_context(event, request.user),
    }
    if show_faculty_view:
        from registrations.models import Registration

        context["registrations"] = event.registrations.select_related(
            "user", "price_tier"
        ).order_by("created_at")
        context["pending_registrations"] = event.registrations.filter(
            status=Registration.Status.PENDING_APPROVAL
        ).select_related("user")
        context["pricing_code_form"] = PricingCodeForm()
        context["existing_codes"] = event.pricing_codes.order_by("-created_at")

    return render(request, "events/event_detail.html", context)


def _ce_edit_context(form):
    """Organization checkboxes for the edit form.

    Rendered by hand rather than through the widget so each option can show its
    logo. ``BoundField.value()`` gives the *submitted* selection when the form
    is bound, so a failed POST re-renders with the user's ticks intact.
    """
    from .models import CEOrganization

    return {
        "ce_organizations": CEOrganization.objects.all(),
        "selected_ce_values": [str(v) for v in (form["ce_organizations"].value() or [])],
    }


@login_required
def event_edit(request, slug: str):
    """Faculty-facing edit form for the event description (PROG-7).

    Approved events (published + minted from a PC proposal) route reviewable
    content changes through a certify-or-submit dialog (#295): non-reviewable
    fields apply immediately, but a change to the title / description / readings
    / fee note prompts the editor to either certify it as minor (adopted now) or
    submit it to the Programming Committee queue. Reviewers (PC/staff) get a
    third "administrative change" option, recorded for the audit trail.
    """
    from .permissions import is_change_reviewer
    from .review import REVIEWABLE_FIELDS, change_ratio

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden(
            "You don't have permission to edit this event."
        )

    if request.method != "POST":
        form = EventEditForm(instance=event)
        return render(request, "events/event_edit.html", {
            "event": event, "form": form,
            "speaker_invites": _speaker_invite_rows(event),
            **_ce_edit_context(form),
            **_schedule_editor_context(event),
        })

    # Snapshot the live reviewable values *before* binding — ModelForm validation
    # mutates ``event`` in place (construct_instance), so reading them afterwards
    # would compare the new value against itself.
    original = {f: (getattr(event, f) or "") for f in REVIEWABLE_FIELDS}

    form = EventEditForm(request.POST, instance=event)
    if not form.is_valid():
        return render(request, "events/event_edit.html", {
            "event": event, "form": form,
            "speaker_invites": _speaker_invite_rows(event),
            **_ce_edit_context(form),
            **_schedule_editor_context(event),
        })

    cd = form.cleaned_data
    changed = [f for f in REVIEWABLE_FIELDS if (cd[f] or "") != original[f]]

    # Events that don't carry the review expectation, or edits that touch no
    # reviewable field, save straight through as before.
    if not changed or not event.requires_change_review():
        form.save()
        messages.success(request, "Changes saved.")
        return redirect("events:detail", slug=event.slug)

    decision = request.POST.get("decision")
    if not decision:
        # First submission of a reviewable change → show the dialog. Carry the
        # submitted values forward as hidden inputs so the choice POST re-binds.
        desc_ratio = change_ratio(original["description"], cd["description"]) \
            if "description" in changed else 0.0
        return render(request, "events/event_edit_confirm.html", {
            "event": event,
            "form": form,
            "changed_labels": [_field_label(f) for f in changed],
            "description_ratio_pct": round(desc_ratio * 100),
            "description_changed": "description" in changed,
            "is_reviewer": is_change_reviewer(request.user),
        })

    # The editor made a choice. Apply non-reviewable changes immediately either
    # way, then route the reviewable ones per the decision.
    from . import notifications as event_notifications
    from .models import EventChangeRequest

    # Apply non-reviewable changes immediately either way. ManyToMany fields
    # (ce_organizations) can go through neither setattr() nor update_fields, so
    # they're set separately.
    m2m_names = {f.name for f in Event._meta.many_to_many}
    nonreviewable = [
        f for f in form.changed_data if f not in REVIEWABLE_FIELDS
    ]
    concrete = [f for f in nonreviewable if f not in m2m_names]
    if concrete:
        for f in concrete:
            setattr(event, f, cd[f])
        event.save(update_fields=concrete)
    for f in nonreviewable:
        if f in m2m_names:
            getattr(event, f).set(cd[f])

    reviewer = is_change_reviewer(request.user)
    desc_ratio = change_ratio(original["description"], cd["description"]) \
        if "description" in changed else 0.0

    def _make_request(status):
        return EventChangeRequest(
            event=event, proposed_by=request.user, status=status,
            changed_fields=changed, description_change_ratio=desc_ratio,
            **{f"proposed_{f}": cd[f] for f in changed},
            **{f"original_{f}": original[f] for f in changed},
        )

    if decision == "review":
        cr = _make_request(EventChangeRequest.Status.PENDING)
        cr.save()
        event_notifications.notify_change_submitted(cr)
        messages.success(
            request,
            "Submitted to the Programming Committee — the event stays as it is "
            "until they review your change.",
        )
        return redirect("events:detail", slug=event.slug)

    if decision == "admin" and reviewer:
        cr = _make_request(EventChangeRequest.Status.ADMINISTRATIVE)
        cr.apply()                 # writes the proposed values onto the event
        cr.reviewed_by = request.user
        cr.reviewed_at = timezone.now()
        cr.save()
        messages.success(request, "Administrative change applied and logged.")
        return redirect("events:detail", slug=event.slug)

    # Default / "minor": faculty self-certifies; the change is adopted now.
    cr = _make_request(EventChangeRequest.Status.SELF_CERTIFIED)
    cr.apply()
    cr.save()
    messages.success(request, "Change adopted.")
    return redirect("events:detail", slug=event.slug)


@login_required
@require_POST
def ce_organization_add(request, slug: str):
    """Add an accrediting body to the shared library and apply it to this event.

    Reaching this from an event can only mean "this event is approved by it", so
    the new organization is ticked on straight away. Gated by can_edit_event: the
    library is shared, so only someone who can edit *some* event may seed it.
    """
    from .forms import CEOrganizationForm

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to edit this event.")

    org_form = CEOrganizationForm(request.POST, request.FILES)
    if org_form.is_valid():
        org = org_form.save(added_by=request.user)
        event.ce_organizations.add(org)
        messages.success(request, f"Added {org.name} and applied it to this event.")
        return redirect("events:edit", slug=event.slug)

    form = EventEditForm(instance=event)
    return render(request, "events/event_edit.html", {
        "event": event, "form": form, "ce_org_form": org_form,
        "speaker_invites": _speaker_invite_rows(event),
        **_ce_edit_context(form),
        **_schedule_editor_context(event),
    })


def _schedule_editor_context(event, formset=None):
    """Context for the standalone-event schedule editor on the edit page.

    The editor is shown only for standalone one-off types (special events, Days
    of Assembly, Working Days, Scholarly Seminars); annual-program events derive
    their sessions from a recurring meeting series managed elsewhere.
    """
    from .forms import SessionScheduleFormSet

    show = event.event_type in Event.PC_OWNED_TYPES
    if not show:
        return {"show_schedule_editor": False}
    if formset is None:
        formset = SessionScheduleFormSet(instance=event, prefix="sessions")
    return {"show_schedule_editor": True, "schedule_formset": formset}


def _resequence_and_sync_dates(event):
    """Renumber an event's sessions by start time and pull the event's
    start/end date onto the earliest start and latest end.

    The coarse ``start_date`` / ``end_date`` labels are derived in a *fixed*
    canonical timezone (the project TIME_ZONE, Pacific) rather than the editor's
    own tz, so an event's calendar "day" doesn't shift depending on who edited
    it. Session wall-clock times are still entered/shown in each user's tz.
    """
    from zoneinfo import ZoneInfo

    sessions = list(event.sessions.order_by("start_at"))
    for i, s in enumerate(sessions, start=1):
        if s.sequence != i:
            s.sequence = i
            s.save(update_fields=["sequence"])
    if sessions:
        tz = ZoneInfo("America/Los_Angeles")
        event.start_date = timezone.localtime(sessions[0].start_at, tz).date()
        latest_end = max(s.end_at for s in sessions)
        event.end_date = timezone.localtime(latest_end, tz).date()
        event.save(update_fields=["start_date", "end_date"])


@login_required
@require_POST
def event_edit_schedule(request, slug: str):
    """Faculty/PC/staff edit the sessions (date + start/end + location) of a
    standalone one-off event. Isolated from the content edit form + review loop
    (sessions are a different model). Applies immediately."""
    from django.db import transaction

    from .forms import SessionScheduleFormSet

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to edit this event.")
    if event.event_type not in Event.PC_OWNED_TYPES:
        raise Http404()

    formset = SessionScheduleFormSet(request.POST, instance=event, prefix="sessions")
    if formset.is_valid():
        with transaction.atomic():
            formset.save()
            _resequence_and_sync_dates(event)
        messages.success(request, "Schedule updated.")
        return redirect("events:edit", slug=event.slug)

    form = EventEditForm(instance=event)
    return render(request, "events/event_edit.html", {
        "event": event, "form": form,
        **_schedule_editor_context(event, formset=formset),
    })


def _field_label(field: str) -> str:
    from .review import FIELD_LABELS
    return FIELD_LABELS.get(field, field)


@login_required
def check_pricing_code(request, slug: str):
    """JSON: look up a pricing code for this event and return its mode + value.

    Used by the register page to adapt the UI (slider vs fixed display) before
    submit. Returns ``ok=False`` for missing / invalid / unredeemable codes
    rather than HTTP errors — the front-end shows the message inline.
    """
    event = get_object_or_404(Event, slug=slug)
    raw = (request.GET.get("code") or "").strip().upper()
    if not raw:
        return JsonResponse({"ok": False, "error": "Empty code."})
    try:
        code = PricingCode.objects.get(code=raw, event=event)
    except PricingCode.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Code not recognized for this event."})
    if not code.is_redeemable(user=request.user):
        return JsonResponse({"ok": False, "error": "Code is not redeemable for you right now."})
    return JsonResponse({
        "ok": True,
        "mode": code.pricing_mode,
        "value": str(code.amount_or_percent),
    })


@login_required
def event_roster_csv(request, slug: str):
    """CSV export of an event's roster (REG-10).

    Active registrations only (awaiting_payment, paid, comped); cancelled
    and refunded rows are excluded. Permission mirrors event editing: event
    faculty, Programming Committee, LSP Staff, or Django is_staff.
    """
    from registrations.models import Registration

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to view this roster.")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{event.slug}-roster.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        "first_name", "last_name", "email", "role",
        "tier", "amount", "status", "pricing_code", "registered_at",
    ])

    qs = (
        Registration.objects.filter(event=event)
        .exclude(status__in=(
            Registration.Status.CANCELLED,
            Registration.Status.REFUNDED,
        ))
        .select_related("user", "user__profile", "price_tier", "pricing_code")
        .order_by("created_at")
    )
    for r in qs:
        writer.writerow([
            r.user.first_name,
            r.user.last_name,
            r.user.email,
            getattr(getattr(r.user, "profile", None), "role", ""),
            r.price_tier.get_audience_display(),
            r.quoted_amount,
            r.get_status_display(),
            r.pricing_code.code if r.pricing_code else "",
            r.created_at.isoformat(),
        ])
    return response


@login_required
def event_generate_code(request, slug: str):
    """Mint a pricing code for the event (PROG-8 / REG-17).

    Permission is the same as event editing. On success, redirects back to
    the faculty view of the event detail page where the new code is listed.
    """
    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden(
            "You don't have permission to issue codes for this event."
        )
    if request.method != "POST":
        return redirect(_faculty_view_url(event))

    form = PricingCodeForm(request.POST)
    if form.is_valid():
        code = form.save(commit=False)
        code.event = event
        code.issued_by = request.user
        code.save()

    return redirect(_faculty_view_url(event))


# --- Program Committee admin --------------------------------------------


PC_ADMIN_TABS = [
    ("programs",  "Programs"),
    ("proposals", "Proposals"),
    ("changes",   "Changes"),
    ("help",      "Help"),
]


def _pc_admin_tab_links():
    """Tab nav for the PC admin."""
    return [(key, label, reverse(f"program_admin_{key}"))
            for key, label in PC_ADMIN_TABS]


def _pc_admin_render(request, tab_key, template, ctx):
    ctx = {**ctx, "tab_key": tab_key, "tabs": _pc_admin_tab_links()}
    return render(request, template, ctx)


def _is_pc_or_staff(user) -> bool:
    """Gate for PC admin views — Programming Committee members + Django staff."""
    from .permissions import is_program_committee
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_staff or is_program_committee(user)


@login_required
def program_admin_help(request):
    """Help tab — renders the PC admin guide markdown doc."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from core.docs import render_doc
    return _pc_admin_render(request, "help", "events/program_admin/help.html", {
        "rendered_html": render_doc("pc-admin-guide"),
    })


@login_required
def program_admin_programs(request):
    """PC admin: list every Program with status + event counts."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .models import Program
    rows = []
    for p in Program.objects.all().order_by("-academic_year"):
        rows.append({
            "program":         p,
            "event_count":     p.events.count(),
            "published_count": p.events.filter(published=True).count(),
            "is_public_now":   p.is_public_now,
        })
    return _pc_admin_render(request, "programs", "events/program_admin/index.html", {
        "rows": rows,
    })


@login_required
def program_admin_detail(request, academic_year: str):
    """PC admin: view + edit a single program (publish toggle, list events)."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .forms import ProgramPublishForm
    from .models import Program
    program = get_object_or_404(Program, academic_year=academic_year)

    if request.method == "POST":
        form = ProgramPublishForm(request.POST, instance=program)
        if form.is_valid():
            form.save()
            return redirect(
                reverse("program_admin_detail", args=[academic_year]) + "?saved=1#saved"
            )
    else:
        form = ProgramPublishForm(instance=program)

    events = list(
        program.events.all()
        .order_by("event_type", "start_date", "title")
    )
    seminars = [e for e in events if e.event_type == Event.Type.SEMINAR]
    offerings = [e for e in events if e.event_type in (
        Event.Type.READING_GROUP, Event.Type.CARTEL,
    )]

    return _pc_admin_render(request, "programs", "events/program_admin/detail.html", {
        "program":   program,
        "form":      form,
        "events":    events,
        "seminars":  seminars,
        "offerings": offerings,
        "saved":     request.GET.get("saved") == "1",
    })


@login_required
def program_admin_registration_bulk(request, academic_year: str):
    """PC admin: open or close registration for a whole program at once.

    ``action=open`` flips every DRAFT event to OPEN; ``action=close`` flips
    every OPEN event to CLOSED. Distinct from *publishing* the program, which
    only controls public visibility — this controls whether members can
    register (and pay).
    """
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .models import Program
    program = get_object_or_404(Program, academic_year=academic_year)
    if request.method != "POST":
        return redirect(reverse("program_admin_detail", args=[academic_year]))

    action = request.POST.get("action")
    if action == "open":
        n = program.events.filter(status=Event.Status.DRAFT).update(
            status=Event.Status.OPEN
        )
        flag = f"opened={n}"
    elif action == "close":
        n = program.events.filter(status=Event.Status.OPEN).update(
            status=Event.Status.CLOSED
        )
        flag = f"closed={n}"
    else:
        raise Http404()
    return redirect(
        reverse("program_admin_detail", args=[academic_year]) + f"?{flag}"
    )


@login_required
def program_admin_event_new(request, academic_year: str):
    """PC admin: create a new event attached to this program."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .forms import ProgramEventForm
    from .models import Program
    program = get_object_or_404(Program, academic_year=academic_year)

    if request.method == "POST":
        form = ProgramEventForm(request.POST, program=program)
        if form.is_valid():
            event = form.save()
            # Workgroup-primary: every PC-created event gets its generating
            # workgroup (offering → own group; PC-organized → the PC's group).
            event.ensure_workgroup()
            return redirect(
                reverse("program_admin_event_edit", args=[academic_year, event.slug])
            )
    else:
        form = ProgramEventForm(program=program)

    return _pc_admin_render(request, "programs", "events/program_admin/event_form.html", {
        "program":  program,
        "form":     form,
        "creating": True,
    })


@login_required
def program_admin_event_edit(request, academic_year: str, slug: str):
    """PC admin: edit an existing event in this program."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .forms import ProgramEventForm
    from .models import Program
    program = get_object_or_404(Program, academic_year=academic_year)
    event = get_object_or_404(Event, slug=slug, program=program)

    if request.method == "POST":
        form = ProgramEventForm(request.POST, instance=event, program=program)
        if form.is_valid():
            form.save()
            return redirect(
                reverse("program_admin_event_edit", args=[academic_year, event.slug])
                + "?saved=1#saved"
            )
    else:
        form = ProgramEventForm(instance=event, program=program)

    return _pc_admin_render(request, "programs", "events/program_admin/event_form.html", {
        "program":  program,
        "event":    event,
        "form":     form,
        "creating": False,
        "saved":    request.GET.get("saved") == "1",
    })


# ---- Seminar proposals (M12.5) ----------------------------------------

def _save_proposal_form(request, form, speakers, proposal, *, is_submit):
    """Persist a valid proposal form + its readings/speakers; set status by intent
    (Save → SAVED, Submit → PROPOSED, resetting any prior review)."""
    from .models import EventProposal

    proposal = form.save(commit=False)
    if proposal.proposed_by_id is None:
        proposal.proposed_by = request.user
    if is_submit:
        proposal.status = EventProposal.Status.PROPOSED
        proposal.reviewed_by = None
        proposal.reviewed_at = None
        proposal.review_note = ""
    else:
        proposal.status = EventProposal.Status.SAVED
    proposal.save()
    form.save_m2m()
    form.save_readings(proposal)
    speakers.instance = proposal
    speakers.save()
    return proposal


@login_required
def propose_event(request):
    """Any LSP member proposes a seminar, reading group, or special event. They
    can Save a work-in-progress (incomplete OK) or Submit it for PC review.
    Teaching a seminar confers faculty standing, granted on approval."""
    if not is_lsp_member(request.user):
        raise Http404()
    from .forms import EventProposalForm, ProposalSpeakerFormSet

    if request.method == "POST":
        is_submit = request.POST.get("action") == "submit"
        form = EventProposalForm(request.POST)
        form.require_complete = is_submit
        speakers = ProposalSpeakerFormSet(request.POST, prefix="speakers")
        if form.is_valid() and speakers.is_valid():
            proposal = _save_proposal_form(
                request, form, speakers, None, is_submit=is_submit
            )
            messages.success(
                request,
                f"{proposal.get_event_type_display()} submitted — the Programming "
                "Committee will review it." if is_submit
                else f"{proposal.get_event_type_display()} saved. Submit it when ready.",
            )
            return redirect("my_proposals")
    else:
        form = EventProposalForm()
        speakers = ProposalSpeakerFormSet(prefix="speakers")
    return render(request, "events/propose_event.html", {
        "form": form, "speakers": speakers,
    })


@login_required
def proposal_edit(request, pk: int):
    """The proposer edits a saved / pending / declined proposal; Save keeps it a
    draft, Submit (re)sends it for review."""
    from .forms import EventProposalForm, ProposalSpeakerFormSet
    from .models import EventProposal

    proposal = get_object_or_404(EventProposal, pk=pk)
    editable = proposal.status in (
        EventProposal.Status.SAVED, EventProposal.Status.PROPOSED,
        EventProposal.Status.DECLINED,
    )
    if proposal.proposed_by_id != request.user.id or not editable:
        raise Http404()
    if request.method == "POST":
        is_submit = request.POST.get("action") == "submit"
        form = EventProposalForm(request.POST, instance=proposal)
        form.require_complete = is_submit
        speakers = ProposalSpeakerFormSet(
            request.POST, instance=proposal, prefix="speakers"
        )
        if form.is_valid() and speakers.is_valid():
            _save_proposal_form(request, form, speakers, proposal, is_submit=is_submit)
            messages.success(
                request,
                "Submitted for review." if is_submit else "Proposal saved.",
            )
            return redirect("my_proposals")
    else:
        form = EventProposalForm(instance=proposal)
        speakers = ProposalSpeakerFormSet(instance=proposal, prefix="speakers")
    return render(request, "events/propose_event.html", {
        "form": form, "speakers": speakers, "editing": proposal,
    })


@login_required
def my_proposals(request):
    """Legacy ``/propose/mine/`` — now the My LSP hub's Proposals tab."""
    from django.urls import reverse

    return redirect(reverse("formation:formation") + "?tab=proposals")


@login_required
@require_POST
def proposal_submit(request, pk: int):
    """Submit a saved (or declined) proposal for PC review, if it's complete."""
    from .models import EventProposal

    p = get_object_or_404(EventProposal, pk=pk, proposed_by=request.user)
    if p.status not in (EventProposal.Status.SAVED, EventProposal.Status.DECLINED):
        return redirect("my_proposals")
    missing = p.missing_for_submission()
    if missing:
        messages.error(request, f"Add {missing} before submitting.")
        return redirect("proposal_edit", pk=p.pk)
    p.status = EventProposal.Status.PROPOSED
    p.reviewed_by = p.reviewed_at = None
    p.review_note = ""
    p.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    messages.success(request, "Submitted for review.")
    return redirect("my_proposals")


@login_required
@require_POST
def proposal_delete(request, pk: int):
    """Withdraw/delete one of your proposals (not an approved one)."""
    from .models import EventProposal

    p = get_object_or_404(EventProposal, pk=pk, proposed_by=request.user)
    if p.status != EventProposal.Status.APPROVED:
        p.delete()
        messages.success(request, "Proposal deleted.")
    return redirect("my_proposals")


@login_required
def program_admin_proposals(request):
    """PC admin: review queue for seminar proposals."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .models import EventProposal

    # Saved (not-yet-submitted) proposals never reach the PC queue.
    proposals = list(
        EventProposal.objects
        .exclude(status=EventProposal.Status.SAVED)
        .select_related("proposed_by", "minted_event", "continues_seminar")
        .prefetch_related("faculty")
    )
    pending = [p for p in proposals if p.status == EventProposal.Status.PROPOSED]
    decided = [p for p in proposals if p.status != EventProposal.Status.PROPOSED]
    # Standalone special events get their management home here — the PC creates,
    # edits, and publishes them from this tab (they aren't part of any program).
    special_events = list(
        Event.objects.filter(event_type=Event.Type.SPECIAL_EVENT)
        .order_by("-start_date", "title")
    )
    return _pc_admin_render(request, "proposals", "events/program_admin/proposals.html", {
        "pending": pending,
        "decided": decided,
        "special_events": special_events,
    })


@login_required
@require_POST
def proposal_decide(request, pk: int):
    """PC approves (mints the Event) or declines a seminar proposal."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .models import EventProposal

    proposal = get_object_or_404(EventProposal, pk=pk)
    if proposal.status != EventProposal.Status.PROPOSED:
        return redirect("program_admin_proposals")
    if request.POST.get("decision") == "approve":
        event = proposal.approve(request.user)
        messages.success(request, f"Approved — minted “{event.title}”.")
    else:
        proposal.decline(request.user, note=request.POST.get("note", ""))
        messages.success(request, "Proposal declined.")
    return redirect("program_admin_proposals")


@login_required
def program_admin_special_event_new(request):
    """PC direct-create a special event.

    Reuses the member proposal form + ``EventProposal.approve()`` pipeline so the
    minting (price tier, first session, speakers, workgroup provenance) is never
    duplicated. The auto-approve is a property of *this action*, not of the
    proposer's PC membership — a PC member using the normal propose form still
    goes through the review queue. The PC chooses to publish now or save a draft.
    """
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from django.db import transaction

    from .forms import EventProposalForm, ProposalSpeakerFormSet

    special = Event.Type.SPECIAL_EVENT

    def _lock_to_special(form):
        # Constrain the choices so only special events can be created here (both
        # the template's type-adaptive display and POST validation honor this).
        form.fields["event_type"].choices = [(special.value, special.label)]

    if request.method == "POST":
        publish = request.POST.get("action") == "publish"
        form = EventProposalForm(request.POST)
        _lock_to_special(form)
        form.require_complete = True
        speakers = ProposalSpeakerFormSet(request.POST, prefix="speakers")
        if form.is_valid() and speakers.is_valid():
            with transaction.atomic():
                proposal = _save_proposal_form(
                    request, form, speakers, None, is_submit=True,
                )
                event = proposal.approve(request.user)
                has_real_date = bool(proposal.proposed_datetime) and not proposal.date_tbd
                want_published = publish and has_real_date
                if event.published != want_published:
                    event.published = want_published
                    event.save(update_fields=["published"])
            if publish and not has_real_date:
                messages.warning(
                    request,
                    f"“{event.title}” was created as a draft — it needs a date "
                    "before it can be published.",
                )
            elif event.published:
                messages.success(request, f"Created and published “{event.title}”.")
            else:
                messages.success(
                    request,
                    f"Saved “{event.title}” as a draft. Publish it from the "
                    "Proposals tab when it's ready.",
                )
            return redirect("events:edit", slug=event.slug)
    else:
        form = EventProposalForm(initial={"event_type": special.value})
        _lock_to_special(form)
        speakers = ProposalSpeakerFormSet(prefix="speakers")
    return render(request, "events/propose_event.html", {
        "form": form, "speakers": speakers, "direct_create": True,
    })


@login_required
@require_POST
def program_admin_special_event_publish(request, slug: str):
    """PC publishes / unpublishes a standalone special event (its live/draft
    lever is ``Event.published``). Filtered to special events so a program event,
    whose visibility cascades from its Program, can't be toggled here."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    event = get_object_or_404(
        Event, slug=slug, event_type=Event.Type.SPECIAL_EVENT,
    )
    publish = request.POST.get("action") == "publish"
    if event.published != publish:
        event.published = publish
        event.save(update_fields=["published"])
    messages.success(
        request,
        f"{'Published' if publish else 'Unpublished'} “{event.title}”.",
    )
    return redirect("program_admin_proposals")


@login_required
@require_POST
def program_admin_special_event_registration(request, slug: str):
    """PC opens / closes registration on a standalone special event.

    ``Event.published`` (the Publish button) controls visibility; ``status``
    controls whether members can register and pay — a live page can carry
    closed registration. Program events get this lever from their program's
    bulk buttons; a standalone special event had nowhere to set it but the
    Django admin, so this is it.
    """
    if not _is_pc_or_staff(request.user):
        raise Http404()
    event = get_object_or_404(
        Event, slug=slug, event_type=Event.Type.SPECIAL_EVENT,
    )
    action = request.POST.get("action")
    if action == "open":
        event.status = Event.Status.OPEN
    elif action == "close":
        event.status = Event.Status.CLOSED
    else:
        raise Http404()
    event.save(update_fields=["status"])
    if action == "open":
        messages.success(request, f"Registration is open for “{event.title}”.")
        # Nothing to quote without a tier — flag it rather than refuse (the PC
        # may be mid-setup), so nobody discovers it from a broken register page.
        if not event.price_tiers.exists():
            messages.warning(
                request,
                f"“{event.title}” has no price tier yet, so members can't "
                "complete a registration. Add one on the event's edit page.",
            )
        if not event.published:
            messages.warning(
                request,
                f"“{event.title}” is still a draft — publish it for anyone to "
                "reach the registration page.",
            )
    else:
        messages.success(request, f"Registration is closed for “{event.title}”.")
    return redirect("program_admin_proposals")


@login_required
def program_admin_changes(request):
    """PC admin: review queue for faculty content changes to approved events
    (#295), plus a history of self-certified / administrative / decided ones."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from .models import EventChangeRequest

    requests = list(
        EventChangeRequest.objects
        .select_related("event", "proposed_by", "reviewed_by")
    )
    pending = [c for c in requests if c.status == EventChangeRequest.Status.PENDING]
    decided = [c for c in requests if c.status != EventChangeRequest.Status.PENDING]
    return _pc_admin_render(request, "changes", "events/program_admin/changes.html", {
        "pending": pending,
        "decided": decided,
    })


@login_required
@require_POST
def change_request_decide(request, pk: int):
    """PC approves (applies) or declines a pending faculty content change."""
    if not _is_pc_or_staff(request.user):
        raise Http404()
    from . import notifications as event_notifications
    from .models import EventChangeRequest

    cr = get_object_or_404(EventChangeRequest, pk=pk)
    if cr.status != EventChangeRequest.Status.PENDING:
        return redirect("program_admin_changes")
    if request.POST.get("decision") == "approve":
        cr.approve(request.user)
        messages.success(request, f"Approved — “{cr.event.title}” updated.")
    else:
        cr.decline(request.user, note=request.POST.get("note", ""))
        messages.success(request, "Change declined.")
    event_notifications.notify_change_decided(cr)
    return redirect("program_admin_changes")


@login_required
@require_POST
def speaker_invite(request, slug, speaker_id):
    """PC/staff confirm-and-send an external-speaker invitation (task #463)."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    from .models import Speaker
    from .speaker_invitations import send_invitation

    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden("You don't have permission to invite speakers.")
    speaker = get_object_or_404(Speaker, pk=speaker_id, events=event)
    # An external speaker added without an email shows an inline field to add one
    # here; set it before inviting.
    new_email = request.POST.get("email", "").strip()
    if new_email and not (speaker.email or "").strip():
        try:
            validate_email(new_email)
        except ValidationError:
            messages.error(request, "That doesn't look like a valid email address.")
            return redirect("events:edit", slug=event.slug)
        speaker.email = new_email
        speaker.save(update_fields=["email"])
    if not (speaker.email or "").strip():
        messages.error(
            request, f"Add an email address for {speaker.name} before inviting."
        )
        return redirect("events:edit", slug=event.slug)
    message = request.POST.get("message", "").strip()
    send_invitation(speaker, event, message)
    messages.success(request, f"Invitation sent to {speaker.name} ({speaker.email}).")
    return redirect("events:edit", slug=event.slug)


def _speaker_invite_rows(event):
    """Per-speaker invite state for the edit page."""
    from .speaker_invitations import default_invitation_message
    rows = []
    for s in event.speakers.all().select_related("user"):
        if not (s.email or "").strip():
            status = "needs_email"   # shown with an inline "add an email" field
        elif s.user_id and s.user.has_usable_password():
            status = "active"
        elif s.user_id:
            status = "invited"   # provisioned; awaiting activation
        else:
            status = "ready"
        rows.append({
            "speaker": s,
            "status": status,
            "default_message": default_invitation_message(s, event),
        })
    return rows


def speaker_invitation_accept(request, token):
    """Activate an invited external-speaker login: set a password, sign in, and
    land on the event page (task #463).

    Consumption happens only on the POST that sets the password, so email
    security scanners that GET-prefetch the link can't burn it
    (memory ``auth-email-scanner-and-reset-gotchas``).
    """
    from django.contrib.auth import login
    from django.contrib.auth.forms import SetPasswordForm

    from .models import SpeakerInvitation

    inv = (
        SpeakerInvitation.objects
        .filter(token=token)
        .select_related("user", "speaker")
        .first()
    )
    if inv is None or not inv.is_valid or not inv.user.is_active:
        return render(request, "events/speaker_invitation_invalid.html", status=410)

    event = inv.speaker.events.order_by("start_date").first()
    if request.method == "POST":
        form = SetPasswordForm(inv.user, request.POST)
        if form.is_valid():
            form.save()
            inv.consume()
            login(request, inv.user)
            if event is not None:
                return redirect("events:detail", slug=event.slug)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = SetPasswordForm(inv.user)
    return render(request, "events/speaker_invitation_accept.html", {
        "form": form, "invitation": inv, "event": event,
    })
