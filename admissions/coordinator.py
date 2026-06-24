"""The Applications Coordinator console (/admin-tools/applications/).

Facilitation for the Meeting of Analysts' admissions: an at-a-glance triage of
applications with interview progress, one-tap reminders to interviewers whose
reports are outstanding, and the editable reminder wording. Interviewer
assignment and the accept/reject decision stay on the Meeting's review surface
(this console links there) — the Meeting keeps the decision.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import notifications as notify_admissions
from . import services
from .forms import AdmissionsSettingsForm, MessageTemplateForm
from .models import AdmissionsSettings, Application, MessageTemplate
from .permissions import coordinator_required

#: (key, label) for the console tabs, in display order. Availability is the
#: coordinator's other surface (the analyst-availability table) — same role.
TABS = [
    ("applications", "Applications"),
    ("availability", "Analyst availability"),
    ("messages", "Messages"),
    ("settings", "Settings"),
]


def _tab_links() -> list[tuple[str, str, str]]:
    name_to_url = {
        "applications": reverse("admissions:coordinator_dashboard"),
        "availability": reverse("availability:grid"),
        "messages": reverse("admissions:coordinator_messages"),
        "settings": reverse("admissions:coordinator_settings"),
    }
    return [(key, label, name_to_url[key]) for key, label in TABS]


def _render(request, tab_key, template, ctx):
    return render(request, template, {**ctx, "tab_key": tab_key, "tabs": _tab_links()})


def _absolute(path: str) -> str:
    return settings.SITE_BASE_URL.rstrip("/") + path


@coordinator_required
def dashboard(request):
    status = request.GET.get("status", "open")
    qs = (
        Application.objects.select_related("applicant")
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
        })

    return _render(request, "applications", "admissions/coordinator/dashboard.html", {
        "rows": rows,
        "status_filter": status,
        "status_choices": Application.Status.choices,
        "open_count": Application.objects.filter(
            status__in=Application.OPEN_STATUSES
        ).count(),
    })


@coordinator_required
@require_POST
def nudge(request, pk):
    """Remind every interviewer on this application whose report is outstanding."""
    application = get_object_or_404(
        Application.objects.prefetch_related("interviews__interviewer"), pk=pk
    )
    template = MessageTemplate.get(MessageTemplate.Key.INTERVIEWER_NUDGE)
    url = _absolute(reverse("admissions:review_detail", args=[application.pk]))
    applicant = application.applicant.get_full_name() or application.applicant.email

    sent = 0
    for interview in application.interviews.all():
        if interview.is_complete:
            continue
        ctx = {
            "interviewer": interview.interviewer.get_full_name()
            or interview.interviewer.email,
            "applicant": applicant,
            "url": url,
        }
        notify_admissions.interviewer_nudge(
            interview,
            services.render_template(template.subject, ctx),
            services.render_template(template.body, ctx),
        )
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
    config = AdmissionsSettings.load()
    form = AdmissionsSettingsForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Admissions settings saved.")
        return redirect("admissions:coordinator_settings")
    return _render(request, "settings", "admissions/coordinator/settings.html", {
        "form": form,
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
    MessageTemplate.Key.INTERVIEWER_NUDGE: "{interviewer}, {applicant}, {url}",
    MessageTemplate.Key.DECISION_ACCEPT: (
        "{name}, {formation}, {note}, {availability_url}, {documents_url}, "
        "{profile_url}, {applications_coordinator}"
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
