"""Views for the Workspace surface — the shared landing/detail page every
group kind renders through."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from works.models import Work

from .models import Workgroup, WorkgroupMembership


def _attached(workgroup, accessor):
    """The concrete object attached to ``workgroup`` via a reverse OneToOne
    (e.g. its Cartel), or None — without importing the owning app."""
    try:
        return getattr(workgroup, accessor)
    except ObjectDoesNotExist:
        return None

#: The Groups overview / dropdown order: kind, url-name suffix, label, blurb.
#: Drives both the overview cards and the per-kind routes in ``urls.py``.
KIND_META = [
    (Workgroup.Kind.SEMINAR, "seminars", "Seminars",
     "Year-long teaching seminars led by faculty."),
    (Workgroup.Kind.CARTEL, "cartels", "Cartels",
     "Small groups — several members and a “plus-one” — formed around a "
     "shared question."),
    (Workgroup.Kind.COMMITTEE, "committees", "Committees",
     "Standing committees that carry the work of the school."),
    (Workgroup.Kind.WORKING_GROUP, "working_groups", "Working Groups",
     "Task- and project-oriented groups organized around an aim."),
    (Workgroup.Kind.READING_GROUP, "reading_groups", "Reading Groups",
     "Groups reading a shared text or body of work together."),
]


def workgroup_list(request):
    """The Groups overview: one card per kind (always all of them)."""
    visible = [
        g for g in Workgroup.objects.all()
        if g.landing_visible_to(request.user)
    ]
    counts: dict[str, int] = {}
    for g in visible:
        counts[g.kind] = counts.get(g.kind, 0) + 1

    kinds = [
        {
            "label": label,
            "blurb": blurb,
            "url": reverse(f"workgroups:kind_{name}"),
            "count": counts.get(kind, 0),
        }
        for kind, name, label, blurb in KIND_META
    ]
    return render(request, "workgroups/list.html", {"kinds": kinds})


def workgroup_kind_list(request, kind):
    """The per-kind directory — visible workgroups of a single kind."""
    label = Workgroup.Kind(kind).label
    groups = [
        g for g in Workgroup.objects.filter(kind=kind)
        if g.landing_visible_to(request.user)
    ]
    context = {
        "kind_label": label,
        "kind_label_plural": f"{label}s",
        "groups": groups,
    }
    # Cartels get formation entry points + a "My cartels" section here
    # (the unified Cartels home).
    if kind == Workgroup.Kind.CARTEL:
        from accounts.permissions import is_lsp_member
        from cartels.permissions import is_cartel_coordinator

        context["can_propose_cartel"] = is_lsp_member(request.user)
        context["is_cartel_coordinator"] = is_cartel_coordinator(request.user)
        if request.user.is_authenticated:
            mine_ids = set(
                WorkgroupMembership.objects
                .filter(user=request.user, workgroup__kind=Workgroup.Kind.CARTEL)
                .values_list("workgroup_id", flat=True)
            )
            context["my_cartels"] = [g for g in groups if g.id in mine_ids] + [
                g for g in Workgroup.objects.filter(id__in=mine_ids)
                if g not in groups  # include ones not in the visible list (e.g. proposed)
            ]
    return render(request, "workgroups/kind_list.html", context)


def workgroup_detail(request, slug):
    """The Workspace — a tabbed surface (Overview / Work / Settings / …),
    gated by visibility + membership. Tabs follow the capability toggles."""
    wg = get_object_or_404(Workgroup, slug=slug)
    if not wg.landing_visible_to(request.user):
        raise Http404  # don't reveal that a hidden group exists

    can_view = wg.content_visible_to(request.user)
    is_member = wg.is_member(request.user)

    # Discuss (forum) + Chat channels, for members. (Files → W2; Schedule →
    # W3; Tasks → W4.)
    discuss_channel = chat_channel = None
    if is_member and wg.has_channel:
        discuss_channel = wg.channels.filter(kind="forum").first()
        chat_channel = wg.channels.filter(kind="chat").first()

    # Offering Workspaces (seminar / reading group) feature their generated
    # event; faculty/editors get its PROG-8 tooling on a Roster tab.
    primary_event = wg.primary_event()
    can_edit_offering = False
    if primary_event is not None:
        from events.permissions import can_edit_event

        can_edit_offering = can_edit_event(request.user, primary_event)

    tabs = [("overview", "Overview")]
    if discuss_channel:
        tabs.append(("discuss", "Discuss"))
    if chat_channel:
        tabs.append(("chat", "Chat"))
    if wg.has_works and can_view:
        tabs.append(("work", "Work"))
    if wg.has_calendar and is_member:
        tabs.append(("schedule", "Schedule"))
    if wg.has_tasks and is_member:
        tabs.append(("tasks", "Tasks"))
    if can_edit_offering:
        tabs.append(("roster", "Roster"))
    if is_member:
        tabs.append(("settings", "Settings"))
    tab_keys = [k for k, _ in tabs]
    active = request.GET.get("tab", "overview")
    if active not in tab_keys:
        active = "overview"

    # Breadcrumb back to this kind's directory (e.g. "Cartels").
    kind_url_suffix = next(
        (name for k, name, *_ in KIND_META if k == wg.kind), None
    )
    kind_index_url = (
        reverse(f"workgroups:kind_{kind_url_suffix}") if kind_url_suffix else None
    )

    # A seminar also lives in its annual Program — show that as a second,
    # stable context link (not referrer-based) when the program is visible.
    program_url = program_label = None
    if primary_event is not None and primary_event.program_id:
        prog = primary_event.program
        if prog.is_public_now or can_edit_offering:
            program_url = reverse("program") + f"?year={prog.academic_year}"
            program_label = str(prog)

    members = wg.participants() if can_view else []

    context = {
        "workgroup": wg,
        "can_view_content": can_view,
        "is_member": is_member,
        "members": members,
        "member_count": len(members),
        "kind_index_url": kind_index_url,
        "program_url": program_url,
        "program_label": program_label,
        "tabs": tabs,
        "active_tab": active,
        "primary_event": primary_event,
        "can_edit_offering": can_edit_offering,
    }
    # Compose kind-specific UI without importing the concrete app: reach the
    # attached object via its reverse accessor and ask it for its viewer state.
    cartel = _attached(wg, "cartel")
    if cartel is not None:
        from cartels.permissions import is_cartel_coordinator

        context["cartel"] = cartel
        context["is_coordinator"] = is_cartel_coordinator(request.user)
        context.update(cartel.viewer_state(request.user))

    if active == "overview" and primary_event is not None:
        # A seminar / reading-group Workspace shows the generated event's public
        # summary (faculty, sessions, pricing, Register) inline — the shared
        # partial keeps it identical to the standalone event page.
        from events.views import event_summary_context

        context.update(event_summary_context(primary_event, request.user))
    elif active == "roster" and can_edit_offering:
        # PROG-8 faculty tooling: registrant roster + pricing-code minting.
        context["event"] = primary_event
        context["registrations"] = primary_event.registrations.select_related(
            "user", "price_tier"
        ).order_by("created_at")
        from events.forms import PricingCodeForm

        context["pricing_code_form"] = PricingCodeForm()
        context["existing_codes"] = primary_event.pricing_codes.order_by("-created_at")
    elif active in ("discuss", "chat"):
        from parletre.views import channel_inline_context

        ch = discuss_channel if active == "discuss" else chat_channel
        context.update(channel_inline_context(request, ch))
        # After posting in the embedded composer, return to this tab (not the
        # standalone Parlêtre channel page).
        context["channel_next"] = f"{wg.get_absolute_url()}?tab={active}"
    elif active == "work" and wg.has_works and can_view:
        works = (
            Work.listing_for(request.user).filter(workgroup=wg).prefetch_related("files")
        )
        context["works_released"] = [w for w in works if not w.in_progress]
        context["works_in_progress"] = [w for w in works if w.in_progress]
    elif active == "schedule" and wg.has_calendar and is_member:
        from django.utils import timezone as _tz

        from .forms import WorkgroupMeetingForm

        now = _tz.now()
        context["upcoming_meetings"] = list(wg.meetings.filter(starts_at__gte=now))
        context["past_meetings"] = list(
            wg.meetings.filter(starts_at__lt=now).order_by("-starts_at")
        )
        context["meeting_form"] = WorkgroupMeetingForm()
    elif active == "tasks" and wg.has_tasks and is_member:
        qs = wg.tasks.prefetch_related("assignees")
        q = (request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(title__icontains=q)
        sort = request.GET.get("sort", "created")
        open_qs = qs.filter(done=False)
        if sort == "due":
            # Soonest due first; tasks with no due date sort to the end.
            open_qs = open_qs.order_by(F("due_date").asc(nulls_last=True), "-created_at")
        elif sort == "title":
            open_qs = open_qs.order_by("title")
        else:
            open_qs = open_qs.order_by("-created_at")
        context["open_tasks"] = list(open_qs)
        context["done_tasks"] = list(qs.filter(done=True).order_by("-completed_at"))
        context["task_q"] = q
        context["task_sort"] = sort
    elif active == "settings" and is_member:
        from .forms import WorkgroupDatesForm

        context["dates_form"] = WorkgroupDatesForm(instance=wg)

    return render(request, "workgroups/detail.html", context)


@login_required
@require_POST
def workgroup_update_dates(request, slug):
    """Members set the group's start/end dates (Settings tab)."""
    wg = get_object_or_404(Workgroup, slug=slug)
    if not wg.is_member(request.user):
        raise Http404
    from .forms import WorkgroupDatesForm

    form = WorkgroupDatesForm(request.POST, instance=wg)
    if form.is_valid():
        form.save()
    return redirect(f"{wg.get_absolute_url()}?tab=settings")


def _member_or_404(request, slug):
    wg = get_object_or_404(Workgroup, slug=slug)
    if not wg.is_member(request.user):
        raise Http404
    return wg


def _member_ids(wg, raw_ids):
    """Filter submitted user ids down to current participants of ``wg`` —
    stored members *and* derived seminar registrants (so a student in the
    roster can be assigned a task), matching what the picker offers."""
    submitted = {str(i) for i in raw_ids}
    if not submitted:
        return []
    return [p.user.pk for p in wg.participants() if str(p.user.pk) in submitted]


def _parse_due(raw):
    """Parse a yyyy-mm-dd date string; return None if blank/invalid."""
    from datetime import date

    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@login_required
@require_POST
def task_add(request, slug):
    """A member adds a task (Tasks tab)."""
    wg = _member_or_404(request, slug)
    from .models import WorkgroupTask

    title = (request.POST.get("title") or "").strip()[:255]
    if title:
        task = WorkgroupTask.objects.create(
            workgroup=wg, title=title, created_by=request.user,
            due_date=_parse_due(request.POST.get("due_date")),
        )
        ids = _member_ids(wg, request.POST.getlist("assignees"))
        if ids:
            task.assignees.set(ids)
    return redirect(f"{wg.get_absolute_url()}?tab=tasks")


@login_required
@require_POST
def task_assign(request, slug, pk):
    """Reassign an existing task (set its full assignee list) and/or its due date."""
    wg = _member_or_404(request, slug)
    from .models import WorkgroupTask

    task = get_object_or_404(WorkgroupTask, pk=pk, workgroup=wg)
    task.assignees.set(_member_ids(wg, request.POST.getlist("assignees")))
    if "due_date" in request.POST:
        task.due_date = _parse_due(request.POST.get("due_date"))
        task.save(update_fields=["due_date"])
    return redirect(f"{wg.get_absolute_url()}?tab=tasks")


@login_required
@require_POST
def task_toggle(request, slug, pk):
    wg = _member_or_404(request, slug)
    from .models import WorkgroupTask

    task = get_object_or_404(WorkgroupTask, pk=pk, workgroup=wg)
    task.set_done(not task.done)
    return redirect(f"{wg.get_absolute_url()}?tab=tasks")


@login_required
@require_POST
def task_delete(request, slug, pk):
    wg = _member_or_404(request, slug)
    from .models import WorkgroupTask

    WorkgroupTask.objects.filter(pk=pk, workgroup=wg).delete()
    return redirect(f"{wg.get_absolute_url()}?tab=tasks")


@login_required
@require_POST
def meeting_add(request, slug):
    """A member schedules a meeting (Schedule tab)."""
    wg = _member_or_404(request, slug)
    from .forms import WorkgroupMeetingForm

    form = WorkgroupMeetingForm(request.POST)
    if form.is_valid():
        meeting = form.save(commit=False)
        meeting.workgroup = wg
        meeting.created_by = request.user
        meeting.save()
    return redirect(f"{wg.get_absolute_url()}?tab=schedule")


@login_required
@require_POST
def meeting_delete(request, slug, pk):
    wg = _member_or_404(request, slug)
    from .models import WorkgroupMeeting

    WorkgroupMeeting.objects.filter(pk=pk, workgroup=wg).delete()
    return redirect(f"{wg.get_absolute_url()}?tab=schedule")
