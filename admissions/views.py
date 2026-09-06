"""Views for the application process.

Applicant side: choose a track, submit a letter of intent + CV, and watch the
status. Reviewer side (Board-gated): a queue, then per-application assignment of
two interviewers, their reports, and the accept/reject decision.

The ongoing-formation side (the member hub + advancement/advisor views) lives
in ``formation.views``; ``_can_review``/``_require_review`` stay here since
both the application review queue and the advancement review queue are gated
by the same Meeting-of-the-Analysts permission, and ``formation.views``
imports them from this module.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.membership import current_academic_year_start
from accounts.models import Profile

from .forms import (
    ApplicationForm,
    AssignInterviewerForm,
    InterviewReportForm,
)
from .models import Application, ApplicationInterview
from .permissions import applications_open
from .services import accept_application, reject_application

# Eligibility copy shown on each track's page (from the formation guidelines).
TRACK_ELIGIBILITY = {
    Application.Track.ANALYST: [
        "Academic background — engaged in or holding a PhD (or the most advanced "
        "degree in your field) and eligible to practice psychoanalysis under your "
        "state/country law; or",
        "Clinical background — an advanced degree in psychology, psychiatry, "
        "counseling, or social work, and licensed, working toward licensure, or "
        "practicing in a mental health profession.",
    ],
    Application.Track.SCHOLAR: [
        "At least one full year of personal Lacanian analysis.",
        "A demonstrated interest in Freudian and Lacanian psychoanalysis.",
    ],
}


# --------------------------------------------------------------------------
# Applicant side
# --------------------------------------------------------------------------

def apply_start(request):
    """Choose a track (or jump to your existing application).

    Public on purpose: an anonymous visitor can read the tracks and eligibility
    here, then sign in when they click through to a track (``apply`` is
    login-required and carries ``?next=`` back). This is the public on-ramp the
    apply flow previously lacked."""
    if request.user.is_authenticated and Application.objects.filter(
        applicant=request.user
    ).exists():
        return redirect("admissions:status")
    return render(request, "admissions/apply_start.html", {
        "tracks": [
            {"key": k, "label": Application.Track(k).label, "eligibility": v}
            for k, v in TRACK_ELIGIBILITY.items()
        ],
        "applications_open": applications_open(),
        "applications_email": settings.APPLICATIONS_EMAIL,
    })


def apply(request, track):
    """Submit an application for ``track``.

    Login-gated by hand rather than by decorator: the closed-door check has to
    run *first*, so a stale bookmark doesn't ask a stranger to make an account
    for a form that is no longer there.
    """
    if track not in Application.Track.values:
        raise PermissionDenied
    # The front door is shut: the buttons are gone, but this URL is guessable
    # and sits in browser histories, so guard the POST as well as the GET.
    if not applications_open():
        return redirect("admissions:apply_start")
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if Application.objects.filter(applicant=request.user).exists():
        return redirect("admissions:status")

    form = ApplicationForm(request.POST or None, request.FILES or None, track=track)
    if request.method == "POST" and form.is_valid():
        application = form.save(commit=False)
        application.applicant = request.user
        application.track = track
        application.status = Application.Status.SUBMITTED
        application.submitted_at = timezone.now()
        application.save()
        # A guest who applies becomes a prospective applicant (no tenure yet —
        # admission writes that). Don't touch an existing member's role.
        profile = request.user.profile
        if profile.role in (Profile.Role.EXTERNAL, Profile.Role.PROSPECTIVE_APPLICANT):
            profile.role = Profile.Role.PROSPECTIVE_APPLICANT
            profile.save(update_fields=["role"])
        try:
            from . import services
            services.acknowledge_on_submit(application)
            services.invite_on_submit(application)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("application-submitted email failed")
        messages.success(request, "Your application has been submitted.")
        return redirect("admissions:status")

    return render(request, "admissions/apply.html", {
        "form": form, "track": track,
        "track_label": Application.Track(track).label,
        "eligibility": TRACK_ELIGIBILITY[track],
    })


@login_required
def status(request):
    """The applicant's own application status."""
    application = get_object_or_404(
        Application.objects.prefetch_related("interviews__interviewer"),
        applicant=request.user,
    )
    return render(request, "admissions/status.html", {"application": application})


@login_required
def cv_download(request, pk):
    """Serve an applicant's CV — to the applicant themselves or a Board reviewer
    only. CVs are private (never a public media URL)."""
    from django.http import FileResponse, Http404

    application = get_object_or_404(Application, pk=pk)
    if not (request.user.pk == application.applicant_id or _can_review(request.user)):
        raise Http404
    if not application.cv:
        raise Http404
    name = application.cv.name.rsplit("/", 1)[-1].replace('"', "")
    response = FileResponse(application.cv.open("rb"))
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# --------------------------------------------------------------------------
# Reviewer side (Board-gated)
# --------------------------------------------------------------------------

def _can_review(user) -> bool:
    """The formation pipeline (admissions + advancement) is decided by the
    Meeting of the Analysts — every active Analyst, plus staff/superuser."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    from workgroups.permissions import is_meeting_of_analysts
    return is_meeting_of_analysts(user)


def _require_review(request):
    if not _can_review(request.user):
        raise PermissionDenied


def _require_coordinator(request):
    """Acting on an application (assign, report, decide) is the Applications
    Coordinator's job; the Meeting of Analysts gets a read-only view."""
    from .permissions import can_coordinate_applications
    if not can_coordinate_applications(request.user):
        raise PermissionDenied


@login_required
def review_queue(request):
    """The Meeting of Analysts' read-only list of applications."""
    _require_review(request)
    applications = list(
        Application.objects.select_related("applicant", "applicant__profile")
        .prefetch_related("interviews")
        .order_by("status", "-submitted_at")
    )
    return render(request, "admissions/review_queue.html", {
        "applications": applications,
        "open_statuses": Application.OPEN_STATUSES,
    })


@login_required
def review_detail(request, pk):
    """The Meeting of Analysts' read-only view of one application. The actual
    admin (assign, report, decide) is the Applications Coordinator's, on
    ``coordinator_application_detail``."""
    _require_review(request)
    application = get_object_or_404(
        Application.objects.select_related("applicant", "applicant__profile")
        .prefetch_related("interviews__interviewer"),
        pk=pk,
    )
    from . import services
    return render(request, "admissions/review_detail.html", {
        "application": application,
        "report_forms": [(iv, None) for iv in application.interviews.all()],
        "can_act": False,
        "invited": application.interviewers_invited_at is not None,
        "slots_remaining": services.slots_remaining(application),
        "is_sandbox": application.applicant.profile.is_persona,
        "back_url": reverse("admissions:review_queue"),
        "back_label": "Applications",
    })


@login_required
@require_POST
def review_assign(request, pk):
    _require_coordinator(request)
    application = get_object_or_404(Application, pk=pk)
    form = AssignInterviewerForm(request.POST, application=application)
    if form.is_valid():
        # Same path as an analyst agreeing: records the interview and emails the
        # introduction connecting applicant + interviewer.
        from . import services
        try:
            _iv, created = services.add_interviewer(
                application, form.cleaned_data["interviewer"], by=request.user,
            )
        except ValueError:  # sandbox containment guard
            messages.error(request, "That interviewer can't be assigned here.")
        else:
            messages.success(
                request, "Interviewer added." if created else "Already an interviewer.",
            )
    else:
        messages.error(request, "Couldn't add that interviewer.")
    return redirect("admissions:coordinator_application_detail", pk=pk)


@login_required
@require_POST
def review_report(request, interview_pk):
    _require_coordinator(request)
    interview = get_object_or_404(ApplicationInterview, pk=interview_pk)
    form = InterviewReportForm(request.POST, instance=interview, prefix=f"iv{interview.pk}")
    if form.is_valid():
        form.save()
        messages.success(request, "Interview report saved.")
    else:
        messages.error(request, "Couldn't save the report — check the date.")
    return redirect("admissions:coordinator_application_detail", pk=interview.application_id)


@login_required
@require_POST
def review_remove_interview(request, interview_pk):
    _require_coordinator(request)
    interview = get_object_or_404(ApplicationInterview, pk=interview_pk)
    app_id = interview.application_id
    interview.delete()
    messages.success(request, "Interviewer removed.")
    return redirect("admissions:coordinator_application_detail", pk=app_id)


@login_required
@require_POST
def review_decide(request, pk):
    _require_coordinator(request)
    application = get_object_or_404(Application, pk=pk)
    if not application.is_open:
        messages.error(request, "This application has already been decided.")
        return redirect("admissions:coordinator_application_detail", pk=pk)
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()
    if decision == "accept":
        ay = request.POST.get("effective_ay")
        effective_ay = int(ay) if ay and ay.isdigit() else current_academic_year_start()
        accept_application(application, by=request.user, effective_ay=effective_ay, note=note)
        role_label = dict(Profile.Role.choices).get(application.admit_role, "a Precandidate")
        name = application.applicant.get_full_name() or application.applicant.email
        messages.success(request, f"Accepted — {name} is admitted as {role_label}.")
    elif decision == "reject":
        reject_application(application, by=request.user, note=note)
        messages.success(request, "Recorded as not accepted; the applicant has been notified.")
    else:
        messages.error(request, "Choose accept or decline.")
    return redirect("admissions:coordinator_application_detail", pk=pk)
