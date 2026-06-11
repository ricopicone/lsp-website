"""Public-facing event views (PROG-1, PROG-7, PROG-8, REG-10)."""

from __future__ import annotations

import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
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

from .forms import EventDescriptionForm, PricingCodeForm
from .models import (
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

    daily_on = daily_enabled()
    # Real Daily presence in the event's room (people actually meeting now).
    # No provisioning: counts only an already-created room, else 0 (no API call).
    # Offering events meet in their workgroup's room; one-off events own theirs.
    wg = getattr(event, "workgroup", None)
    if event.event_type in event.ANNUAL_PROGRAM_TYPES:
        room = getattr(wg, "video_room", None) if wg else None
    else:
        room = getattr(event, "video_room", None)
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
        "can_host": can_edit_event(user, event),
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
    year = request.GET.get("year") or current_academic_year()
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
    })


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


@login_required
def event_edit(request, slug: str):
    """Faculty-facing edit form for the event description (PROG-7)."""
    event = get_object_or_404(Event, slug=slug)
    if not can_edit_event(request.user, event):
        return HttpResponseForbidden(
            "You don't have permission to edit this event."
        )

    if request.method == "POST":
        form = EventDescriptionForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            return redirect("events:detail", slug=event.slug)
    else:
        form = EventDescriptionForm(instance=event)

    return render(request, "events/event_edit.html", {"event": event, "form": form})


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

    return redirect(reverse("admissions:formation") + "?tab=proposals")


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
    return _pc_admin_render(request, "proposals", "events/program_admin/proposals.html", {
        "pending": pending,
        "decided": decided,
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
