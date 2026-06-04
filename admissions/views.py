"""Views for the application process.

Applicant side: choose a track, submit a letter of intent + CV, and watch the
status. Reviewer side (Board-gated): a queue, then per-application assignment of
two interviewers, their reports, and the accept/reject decision.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.membership import current_academic_year_start
from accounts.models import Profile

from .advancement import (
    can_open_advancement,
    decide_advancement,
    open_advancement,
    open_advancement_for,
    present_advancement,
    step_label_for_member,
    withdraw_advancement,
)
from .emails import send_application_submitted
from .forms import (
    AdvancementForm,
    ApplicationForm,
    AssignInterviewerForm,
    InterviewReportForm,
    RecommendationForm,
)
from .models import Advancement, Application, ApplicationInterview
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

@login_required
def apply_start(request):
    """Choose a track (or jump to your existing application)."""
    if Application.objects.filter(applicant=request.user).exists():
        return redirect("admissions:status")
    return render(request, "admissions/apply_start.html", {
        "tracks": [
            {"key": k, "label": Application.Track(k).label, "eligibility": v}
            for k, v in TRACK_ELIGIBILITY.items()
        ],
    })


@login_required
def apply(request, track):
    """Submit an application for ``track``."""
    if track not in Application.Track.values:
        raise PermissionDenied
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
            send_application_submitted(application)
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


@login_required
def review_queue(request):
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
    _require_review(request)
    application = get_object_or_404(
        Application.objects.select_related("applicant", "applicant__profile")
        .prefetch_related("interviews__interviewer"),
        pk=pk,
    )
    interviews = list(application.interviews.all())
    report_forms = [
        (iv, InterviewReportForm(instance=iv, prefix=f"iv{iv.pk}")) for iv in interviews
    ]
    return render(request, "admissions/review_detail.html", {
        "application": application,
        "assign_form": AssignInterviewerForm(application=application),
        "report_forms": report_forms,
        "default_ay": current_academic_year_start(),
    })


@login_required
@require_POST
def review_assign(request, pk):
    _require_review(request)
    application = get_object_or_404(Application, pk=pk)
    form = AssignInterviewerForm(request.POST, application=application)
    if form.is_valid():
        ApplicationInterview.objects.get_or_create(
            application=application, interviewer=form.cleaned_data["interviewer"],
        )
        if application.status == Application.Status.SUBMITTED:
            application.status = Application.Status.INTERVIEWING
            application.save(update_fields=["status"])
        messages.success(request, "Interviewer added.")
    else:
        messages.error(request, "Couldn't add that interviewer.")
    return redirect("admissions:review_detail", pk=pk)


@login_required
@require_POST
def review_report(request, interview_pk):
    _require_review(request)
    interview = get_object_or_404(ApplicationInterview, pk=interview_pk)
    form = InterviewReportForm(request.POST, instance=interview, prefix=f"iv{interview.pk}")
    if form.is_valid():
        form.save()
        messages.success(request, "Interview report saved.")
    else:
        messages.error(request, "Couldn't save the report — check the date.")
    return redirect("admissions:review_detail", pk=interview.application_id)


@login_required
@require_POST
def review_remove_interview(request, interview_pk):
    _require_review(request)
    interview = get_object_or_404(ApplicationInterview, pk=interview_pk)
    app_id = interview.application_id
    interview.delete()
    messages.success(request, "Interviewer removed.")
    return redirect("admissions:review_detail", pk=app_id)


@login_required
@require_POST
def review_decide(request, pk):
    _require_review(request)
    application = get_object_or_404(Application, pk=pk)
    if not application.is_open:
        messages.error(request, "This application has already been decided.")
        return redirect("admissions:review_detail", pk=pk)
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
    return redirect("admissions:review_detail", pk=pk)


# ==========================================================================
# Advancement — palimpsest (Precandidate → Candidate) / passage demandes
# ==========================================================================

# ---- Member side: the unified "Your Formation" hub ------------------------

def _formation_url(tab="formation", **params):
    """URL for the formation hub, landing on ``tab`` (and carrying any extra
    query params, e.g. ``stripe=success``) after a POST round-trip."""
    from urllib.parse import urlencode

    from django.urls import reverse

    query = {"tab": tab, **{k: v for k, v in params.items() if v}}
    return reverse("admissions:formation") + "?" + urlencode(query)


@login_required
def formation(request):
    """The member's personal formation hub — a tabbed surface that gathers
    everything about their place in the School: their Advisor and advancement
    demandes (Formation), their tuition decision + payments (Tuition), and the
    groups they belong to now and in the past (Groups)."""
    return render(request, "admissions/formation.html", _formation_context(request))


def _formation_context(request, *, advisor_form=None, demande_form=None) -> dict:
    """Assemble the full context for the formation hub. Bound forms may be
    passed in so a failed POST can re-render with errors on the right tab."""
    from accounts.advisor import current_advisor
    from accounts.forms import AdvisorSelectForm

    user = request.user
    profile = user.profile
    tab = request.GET.get("tab") or "formation"

    advisor = current_advisor(user)
    existing = (
        Advancement.objects.filter(member=user)
        .select_related("advisor")
        .order_by("-requested_at")
        .first()
    )
    if advisor_form is None and profile.needs_advisor:
        advisor_form = AdvisorSelectForm(advisee=user)

    ctx = {
        "active_tab": tab,
        "advisor": advisor,
        "needs_advisor": profile.needs_advisor,
        "advisor_form": advisor_form,
        "existing": existing,
        "open_one": open_advancement_for(user),
        "can_open": can_open_advancement(user),
        "step_label": step_label_for_member(user),
        "demande_form": demande_form if demande_form is not None else AdvancementForm(),
        "is_in_training": profile.role in Profile.IN_TRAINING_ROLES,
    }
    ctx.update(_formation_tuition_context(request))
    ctx.update(_formation_groups_context(user))
    return ctx


def _formation_tuition_context(request) -> dict:
    """Tuition decision + installments + the member's own payment history and
    the subset they can self-reconcile (provisional / ASSUMED charges)."""
    from accounts.models import Source
    from payments.forms import TuitionDecisionForm
    from payments.models import Payment, TuitionEnrollment, TuitionPeriod

    user = request.user
    profile = user.profile
    period = TuitionPeriod.current()
    enrollment = None
    installments = []
    if period is not None:
        enrollment = TuitionEnrollment.objects.filter(
            user=user, tuition_period=period,
        ).first()
        if enrollment is not None:
            installments = list(enrollment.installments.order_by("sequence"))

    payments = list(Payment.objects.filter(user=user).order_by("-created_at", "-id"))
    assumed = [p for p in payments if p.source == Source.ASSUMED]

    return {
        "owes_tuition": profile.owes_tuition,
        "show_tuition_tab": profile.owes_tuition or bool(payments),
        "tuition_period": period,
        "tuition_enrollment": enrollment,
        "tuition_installments": installments,
        "tuition_form": TuitionDecisionForm(
            initial={"status": enrollment.status} if enrollment else {}
        ),
        "tuition_stripe_status": request.GET.get("stripe"),
        "my_payments": payments,
        "my_assumed_payments": assumed,
        "payment_type_choices": Payment.Type.choices,
    }


def _formation_groups_context(user) -> dict:
    """The user's current and past groups: stored ``WorkgroupMembership`` rows
    plus seminars / reading groups they attended as a paid/comped registrant."""
    from registrations.models import Registration

    current, past = [], []
    seen: set[int] = set()

    memberships = (
        user.workgroup_memberships
        .select_related("workgroup")
        .order_by("workgroup__name", "-start_date")
    )
    for m in memberships:
        if m.workgroup_id in seen:
            continue
        seen.add(m.workgroup_id)
        entry = {
            "workgroup": m.workgroup,
            "kind": m.workgroup.get_kind_display(),
            "role": m.get_role_display(),
        }
        (current if m.is_active else past).append(entry)

    # Derived: seminars / reading groups joined via a paid or comped
    # registration (no stored membership row).
    regs = (
        Registration.objects
        .filter(user=user, status__in=(
            Registration.Status.PAID, Registration.Status.COMPED,
        ))
        .select_related("event", "event__workgroup")
    )
    for reg in regs:
        wg = reg.event.workgroup if reg.event_id else None
        if wg is None or wg.id in seen:
            continue
        seen.add(wg.id)
        entry = {"workgroup": wg, "kind": wg.get_kind_display(), "role": "Participant"}
        (current if wg.is_member(user) else past).append(entry)

    current.sort(key=lambda e: e["workgroup"].name.lower())
    past.sort(key=lambda e: e["workgroup"].name.lower())
    return {"current_groups": current, "past_groups": past}


@login_required
@require_POST
def advancement(request):
    """Open a Palimpsest / Passage / Traversée demande — the request to present
    at the next Days of Assembly. POSTed from the Formation tab."""
    from accounts.advisor import current_advisor

    if not can_open_advancement(request.user):
        raise PermissionDenied
    if current_advisor(request.user) is None:
        messages.error(request, "Choose your Advisor before opening a demande.")
        return redirect(_formation_url("formation"))
    form = AdvancementForm(request.POST)
    if form.is_valid():
        open_advancement(
            request.user,
            statement=form.cleaned_data.get("statement") or "",
        )
        messages.success(request, "Your request has been sent to your Advisor.")
        return redirect(_formation_url("formation"))
    return render(request, "admissions/formation.html",
                  _formation_context(request, demande_form=form))


@login_required
@require_POST
def advancement_withdraw(request, pk):
    adv = get_object_or_404(Advancement, pk=pk, member=request.user)
    if not adv.is_open:
        messages.error(request, "That demande can no longer be withdrawn.")
    else:
        withdraw_advancement(adv)
        messages.success(request, "Your demande has been withdrawn.")
    return redirect(_formation_url("formation"))


@login_required
def palimpsest_download(request, pk):
    """Serve an advancement's written palimpsest — to the member, their Advisor,
    or a Meeting-of-the-Analysts reviewer only (never a public media URL)."""
    from django.http import FileResponse, Http404

    adv = get_object_or_404(Advancement, pk=pk)
    allowed = (
        request.user.pk in (adv.member_id, adv.advisor_id)
        or _can_review(request.user)
    )
    if not allowed or not adv.palimpsest:
        raise Http404
    name = adv.palimpsest.name.rsplit("/", 1)[-1].replace('"', "")
    response = FileResponse(adv.palimpsest.open("rb"))
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


# ---- Advisor side ---------------------------------------------------------

@login_required
def advise_queue(request):
    """Demandes this Advisor is responsible for presenting to the Meeting."""
    advancements = list(
        Advancement.objects.filter(advisor=request.user)
        .select_related("member", "member__profile")
        .order_by("status", "-requested_at")
    )
    return render(request, "admissions/advise_queue.html", {
        "advancements": advancements,
    })


@login_required
@require_POST
def advise_present(request, pk):
    adv = get_object_or_404(Advancement, pk=pk, advisor=request.user)
    if not adv.is_open:
        messages.error(request, "That demande has already been decided.")
        return redirect("admissions:advise_queue")
    form = RecommendationForm(request.POST, instance=adv, prefix=f"a{adv.pk}")
    if form.is_valid():
        present_advancement(
            adv,
            recommendation=form.cleaned_data["recommendation"],
            presented_on=form.cleaned_data.get("presented_at"),
            by=request.user,
        )
        messages.success(
            request, "Recorded — thank you for presenting the demande."
        )
    else:
        messages.error(request, "Please add your recommendation.")
    return redirect("admissions:advise_queue")


# ---- Meeting of the Analysts review side ----------------------------------

@login_required
def advancement_queue(request):
    _require_review(request)
    advancements = list(
        Advancement.objects.select_related(
            "member", "member__profile", "advisor"
        ).order_by("status", "-requested_at")
    )
    return render(request, "admissions/advancement_queue.html", {
        "advancements": advancements,
        "open_statuses": Advancement.OPEN_STATUSES,
    })


@login_required
def advancement_detail(request, pk):
    _require_review(request)
    adv = get_object_or_404(
        Advancement.objects.select_related("member", "member__profile", "advisor"),
        pk=pk,
    )
    return render(request, "admissions/advancement_detail.html", {
        "adv": adv,
        "default_ay": current_academic_year_start(),
    })


@login_required
@require_POST
def advancement_decide(request, pk):
    _require_review(request)
    adv = get_object_or_404(Advancement, pk=pk)
    if not adv.is_open:
        messages.error(request, "This demande has already been decided.")
        return redirect("admissions:advancement_detail", pk=pk)
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()
    if decision == "approve":
        ay = request.POST.get("effective_ay")
        effective_ay = int(ay) if ay and ay.isdigit() else current_academic_year_start()
        decide_advancement(adv, approve=True, by=request.user,
                            effective_ay=effective_ay, note=note)
        name = adv.member.get_full_name() or adv.member.email
        role_label = dict(Profile.Role.choices).get(adv.advance_role, "the next step")
        messages.success(request, f"Approved — {name} advances to {role_label}.")
    elif decision == "decline":
        decide_advancement(adv, approve=False, by=request.user, note=note)
        messages.success(request, "Recorded as not approved; the member has been notified.")
    else:
        messages.error(request, "Choose approve or decline.")
    return redirect("admissions:advancement_detail", pk=pk)
