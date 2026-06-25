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
    return render(request, "admissions/analyst/interview.html", {
        "application": application,
        "mine": mine,
        "slots_remaining": services.slots_remaining(application),
        "eligible": request.user in services.eligible_interviewers(application),
        "report_form": report_form,
        "is_sandbox": application.applicant.profile.is_persona,
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
