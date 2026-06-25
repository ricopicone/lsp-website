"""The Analyst page (/admin-tools/analyst/) — an Analyst of the School's own
interview workspace.

Two things: interview requests they can agree to (open invitations they're
eligible for), and the interviews they've agreed to — where they record the
report when done. The agree/report page is also where the invitation email's
"I can interview" button lands.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import InterviewReportForm
from .models import Application, ApplicationInterview
from .permissions import analyst_required, is_analyst


@analyst_required
def dashboard(request):
    user = request.user
    mine = list(
        ApplicationInterview.objects.filter(interviewer=user)
        .select_related("application__applicant")
        .order_by("completed_at", "-agreed_at")
    )
    mine_app_ids = {iv.application_id for iv in mine}

    # Open requests: invited, still short of interviewers, this analyst eligible
    # and not already on it.
    requests = []
    invited = (
        Application.objects.filter(
            status=Application.Status.INTERVIEWING,
            interviewers_invited_at__isnull=False,
        )
        .select_related("applicant")
        .prefetch_related("interviews")
    )
    for app in invited:
        if app.pk in mine_app_ids:
            continue
        if services.slots_remaining(app) <= 0:
            continue
        if user in services.eligible_interviewers(app):
            requests.append(app)

    return render(request, "admissions/analyst/dashboard.html", {
        "requests": requests,
        "mine": mine,
    })


@analyst_required
def interview(request, pk):
    """Per-application page: agree to interview (if a slot is open and you
    haven't yet), or — once you're the interviewer — record your report. This
    is where the invitation and reminder emails land."""
    application = get_object_or_404(
        Application.objects.select_related("applicant").prefetch_related("interviews"),
        pk=pk,
    )
    mine = application.interviews.filter(interviewer=request.user).first()
    report_form = (
        InterviewReportForm(instance=mine) if mine and not mine.is_complete else None
    )
    is_sandbox = application.applicant.profile.is_persona

    # Sandbox helper: a superuser trialing the flow agrees by impersonating the
    # persona analysts (the email's link lands them here as themselves, not the
    # persona). Offer one-click "act as" links that return to this page.
    sandbox_actors = []
    if is_sandbox and request.user.is_superuser:
        from urllib.parse import urlencode
        here = reverse("admissions:analyst_interview", args=[application.pk])
        agreed_ids = set(application.interviews.values_list("interviewer_id", flat=True))
        for analyst in services.eligible_interviewers(application):
            if analyst.pk in agreed_ids:
                continue
            impersonate = reverse("core:impersonate_start", args=[analyst.pk])
            sandbox_actors.append({
                "name": analyst.get_full_name() or analyst.email,
                "url": f"{impersonate}?{urlencode({'next': here})}",
            })

    return render(request, "admissions/analyst/interview.html", {
        "application": application,
        "mine": mine,
        "slots_remaining": services.slots_remaining(application),
        "eligible": request.user in services.eligible_interviewers(application),
        "report_form": report_form,
        "is_sandbox": is_sandbox,
        "sandbox_actors": sandbox_actors,
    })


@analyst_required
@require_POST
def agree(request, pk):
    application = get_object_or_404(Application, pk=pk)
    _interview, outcome = services.agree_to_interview(application, request.user)
    if outcome == "agreed":
        messages.success(
            request,
            "Thank you — you're connected with the applicant by email to arrange "
            "a time.",
        )
    elif outcome == "already":
        messages.info(request, "You're already set to interview this applicant.")
    else:  # full
        messages.info(
            request,
            "Thank you — the interviews for this applicant are already covered.",
        )
    return redirect("admissions:analyst_interview", pk=pk)


@analyst_required
@require_POST
def report(request, pk):
    application = get_object_or_404(Application, pk=pk)
    iv = get_object_or_404(
        ApplicationInterview, application=application, interviewer=request.user
    )
    form = InterviewReportForm(request.POST, instance=iv)
    if form.is_valid():
        form.save()
        messages.success(request, "Your interview report has been recorded. Thank you.")
        return redirect("admissions:analyst_dashboard")
    return render(request, "admissions/analyst/interview.html", {
        "application": application,
        "mine": iv,
        "slots_remaining": services.slots_remaining(application),
        "eligible": is_analyst(request.user),
        "report_form": form,
    })
