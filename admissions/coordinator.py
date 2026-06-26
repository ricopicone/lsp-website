"""The Applications Coordinator console (/admin-tools/applications/).

Facilitation for the Meeting of Analysts' admissions: an at-a-glance triage of
applications with interview progress, one-tap reminders to interviewers whose
reports are outstanding, and the editable reminder wording. Interviewer
assignment and the accept/reject decision stay on the Meeting's review surface
(this console links there) — the Meeting keeps the decision.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import notifications as notify_admissions
from . import services
from .forms import AdmissionsSettingsForm, MessageTemplateForm
from .models import AdmissionsSettings, Application, MessageTemplate
from .permissions import coordinator_required

#: (key, label) for the console tabs, in display order. Availability is the
#: coordinator's other surface (the analyst-availability table) — same role.
#: The one workspace tab bar, shared by BOTH the admissions and availability
#: consoles so it's identical wherever you are. (key, label, url-name).
_WORKSPACE_TABS = [
    ("applications", "Applications", "admissions:coordinator_dashboard"),
    ("availability", "Analyst availability", "availability:grid"),
    ("overview", "Overview", "availability:overview"),
    ("messages", "Messages", "admissions:coordinator_messages"),
    ("reminder", "Reminder message", "availability:templates"),
    ("settings", "Settings", "admissions:coordinator_settings"),
]


def workspace_tabs() -> list[tuple[str, str, str]]:
    """(key, label, url) for the coordinator workspace tab bar — the single
    source used by both consoles."""
    return [(key, label, reverse(name)) for key, label, name in _WORKSPACE_TABS]


def _render(request, tab_key, template, ctx):
    return render(request, template, {**ctx, "tab_key": tab_key, "tabs": workspace_tabs()})


@coordinator_required
def dashboard(request):
    status = request.GET.get("status", "open")
    qs = (
        Application.objects.select_related("applicant__profile")
        .prefetch_related("interviews__interviewer")
        .order_by("status", "-submitted_at")
    )
    if status == "open":
        qs = qs.filter(status__in=Application.OPEN_STATUSES)
    elif status in Application.Status.values:
        qs = qs.filter(status=status)
    else:
        status = "all"

    rows = []
    for app in qs:
        interviews = list(app.interviews.all())
        pending = [iv for iv in interviews if not iv.is_complete]
        rows.append({
            "application": app,
            "assigned": len(interviews),
            "reports_in": len(interviews) - len(pending),
            "pending": pending,
            "acknowledged": app.acknowledged_at is not None,
            "invited": app.interviewers_invited_at is not None,
            "slots_remaining": max(0, Application.INTERVIEWS_NEEDED - len(interviews)),
            "is_sandbox": app.applicant.profile.is_persona,
        })

    return _render(request, "applications", "admissions/coordinator/dashboard.html", {
        "rows": rows,
        "status_filter": status,
        "status_choices": Application.Status.choices,
        "open_count": Application.objects.filter(
            status__in=Application.OPEN_STATUSES
        ).count(),
        "has_sandbox": request.user.owned_personas.exists(),
    })


@coordinator_required
@require_POST
def invite(request, pk):
    """Send the call for interviewers to available analysts."""
    application = get_object_or_404(Application, pk=pk)
    n = services.invite_interviewers(application)
    messages.success(
        request,
        f"Invited {n} analyst{'s' if n != 1 else ''} to interview "
        f"{application.applicant.get_full_name() or application.applicant.email}.",
    )
    return redirect("admissions:coordinator_dashboard")


@coordinator_required
@require_POST
def reset_sandbox(request):
    """Reset (or create) this coordinator's training sandbox to its starting
    state — Applicant One back to Submitted, Applicant Two interviewing with
    reports in — so the walkthrough can be run again from scratch."""
    import io

    from django.core.management import call_command

    call_command("seed_sandbox", owner=request.user.email, reset=True,
                stdout=io.StringIO())
    messages.success(request, "Sandbox reset to its starting state.")
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("admissions:coordinator_dashboard")


@coordinator_required
@require_POST
def simulate(request, pk):
    """Sandbox-only: fast-forward the interview stage (analysts agree + report)
    so the coordinator can reach the decision without impersonating each one."""
    application = get_object_or_404(Application, pk=pk)
    try:
        n = services.simulate_interviews(application)
    except ValueError:
        messages.error(request, "Simulation is only available for sandbox applications.")
    else:
        messages.success(
            request,
            f"Simulated {n} interview{'s' if n != 1 else ''} — agreed and reported. "
            "The introductions came to your inbox; the application is ready to decide.",
        )
    return redirect("admissions:review_detail", pk=pk)


@coordinator_required
@require_POST
def nudge(request, pk):
    """Remind every interviewer on this application whose report is outstanding
    (the same weekly reminder, sent by hand)."""
    application = get_object_or_404(
        Application.objects.prefetch_related("interviews__interviewer"), pk=pk
    )
    sent = 0
    for interview in application.interviews.all():
        if interview.is_complete:
            continue
        notify_admissions.interview_reminder(interview)
        sent += 1

    if sent:
        messages.success(request, f"Reminded {sent} interviewer{'s' if sent != 1 else ''}.")
    else:
        messages.info(request, "No outstanding interview reports to remind about.")
    return redirect("admissions:coordinator_dashboard")


@coordinator_required
@require_POST
def send_acknowledgment(request, pk):
    """Send the applicant acknowledgment by hand (review-first mode, or to
    re-send). Idempotent enough — stamps acknowledged_at."""
    application = get_object_or_404(Application, pk=pk)
    services.acknowledge(application)
    messages.success(request, "Acknowledgment sent to the applicant.")
    return redirect("admissions:coordinator_dashboard")


@coordinator_required
def settings_view(request):
    """One Settings page for the whole workspace — admissions (acknowledgment,
    invitations) and the availability reminder cadence."""
    from availability.forms import AvailabilitySettingsForm
    from availability.models import AvailabilitySettings

    form = AdmissionsSettingsForm(
        request.POST or None, instance=AdmissionsSettings.load(), prefix="adm",
    )
    avail_form = AvailabilitySettingsForm(
        request.POST or None, instance=AvailabilitySettings.load(), prefix="avl",
    )
    if request.method == "POST" and form.is_valid() and avail_form.is_valid():
        form.save()
        avail_form.save()
        messages.success(request, "Settings saved.")
        return redirect("admissions:coordinator_settings")
    return _render(request, "settings", "admissions/coordinator/settings.html", {
        "form": form,
        "avail_form": avail_form,
    })


@coordinator_required
def messages_list(request):
    items = [MessageTemplate.get(key) for key in MessageTemplate.Key.values]
    return _render(request, "messages", "admissions/coordinator/messages.html", {
        "templates": items,
    })


#: The tokens each message supports, for the editor's hint.
_TOKENS = {
    MessageTemplate.Key.ACKNOWLEDGMENT: (
        "{name}, {track}, {formation}, {status_url}, {applications_coordinator}"
    ),
    MessageTemplate.Key.INVITATION: (
        "{interviewer}, {applicant}, {formation}, {agree_url}, {applications_coordinator}"
    ),
    MessageTemplate.Key.INTRODUCTION: (
        "{applicant}, {interviewer}, {applicant_email}, {interviewer_email}, "
        "{applications_coordinator}"
    ),
    MessageTemplate.Key.INTERVIEW_REMINDER: (
        "{interviewer}, {applicant}, {url}, {applications_coordinator}"
    ),
    MessageTemplate.Key.DECISION_ACCEPT: (
        "{name}, {formation}, {note}, {guidelines_url}, {availability_url}, "
        "{documents_url}, {profile_url}, {mylsp_url}, {applications_coordinator}"
    ),
    MessageTemplate.Key.DECISION_REJECT: (
        "{name}, {track}, {note}, {applications_coordinator}"
    ),
}


@coordinator_required
def message_edit(request, key):
    if key not in MessageTemplate.Key.values:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    template = MessageTemplate.get(key)
    form = MessageTemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Message saved.")
        return redirect("admissions:coordinator_messages")
    return _render(request, "messages", "admissions/coordinator/message_edit.html", {
        "template": template, "form": form, "tokens": _TOKENS.get(key, ""),
    })
