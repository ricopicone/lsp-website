"""Views for ongoing formation — the member's "My LSP" hub, and the advancement
(palimpsest / passage) demande pipeline: member side, Advisor side, and the
Meeting-of-the-Analysts review side.

The intake side (apply / status / cv_download / review_*) stays in
``admissions.views`` — this module only covers what happens *after* someone is
already a member.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.membership import GATED_ROLES, current_academic_year_start
from accounts.models import Profile
from admissions.views import _can_review, _require_review

from .advancement import (
    can_open_advancement,
    decide_advancement,
    open_advancement,
    present_advancement,
    step_label_for_member,
    withdraw_advancement,
)
from .control import control_progress
from .forms import (
    AdvancementForm,
    ControlAnalysisForm,
    ExternalActivityForm,
    ExternalControlAnalystForm,
    RecommendationForm,
)
from .models import (
    Advancement,
    ControlAnalysis,
    ExternalActivity,
    ExternalControlAnalyst,
    FormationSettings,
)
from .tabs import available_tabs

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
    return reverse("formation:formation") + "?" + urlencode(query)


@login_required
def formation(request):
    """The member's personal formation hub — a tabbed surface that gathers
    everything about their place in the School: their Advisor and advancement
    demandes (Formation), their tuition decision + payments (Tuition), and the
    groups they belong to now and in the past (Groups)."""
    return render(request, "formation/formation.html", _formation_context(request))


def _formation_doc_for(user, formation_settings):
    """The track-appropriate formation guidelines Document for an in-training
    member, or None. In-training only (Precandidates/Candidates); respects the
    document's listing visibility."""
    profile = getattr(user, "profile", None)
    if profile is None or profile.role not in Profile.IN_TRAINING_ROLES:
        return None
    if profile.role in Profile.ANALYST_TRACK_ROLES:
        doc = formation_settings.analyst_formation_doc
    elif profile.role in Profile.SCHOLAR_TRACK_ROLES:
        doc = formation_settings.scholar_formation_doc
    else:  # defensive: IN_TRAINING_ROLES is a subset of the two tracks
        doc = None
    if doc is not None and doc.listing_visible_to(user):
        return doc
    return None


def _formation_context(request, *, advisor_form=None, demande_form=None) -> dict:
    """Assemble the full context for the formation hub. Bound forms may be
    passed in so a failed POST can re-render with errors on the right tab."""
    from accounts.advisor import current_advisor
    from accounts.forms import AdvisorSelectForm
    from payments.dues import is_dues_obligated

    user = request.user
    profile = user.profile

    advisor = current_advisor(user)
    if advisor_form is None and profile.needs_advisor:
        advisor_form = AdvisorSelectForm(advisee=user)

    formation_settings = FormationSettings.load()

    ctx = {
        "formation_doc": _formation_doc_for(user, formation_settings),
        "advisor": advisor,
        "needs_advisor": profile.needs_advisor,
        "advisor_form": advisor_form,
        "can_open": can_open_advancement(user),
        "step_label": step_label_for_member(user),
        # The trace of formation steps (Palimpsest, then Passage/Traversée) —
        # derived from the member's role history so steps completed before this
        # system (or via import) still show, with any Advancement overlaid.
        "formation_steps": _formation_steps(user),
        "demande_form": demande_form if demande_form is not None else AdvancementForm(),
        "is_in_training": profile.role in Profile.IN_TRAINING_ROLES,
        "control_entries": ControlAnalysis.objects.filter(member=user),
        "control_progress": control_progress(user),
        "external_entries": ExternalActivity.objects.filter(member=user)
        .order_by("kind", "-start_date"),
        "external_requests": ExternalControlAnalyst.objects.filter(member=user),
    }

    # The page tab bar shows Tuition/Dues on obligation OR payment history; the
    # global avatar menu (available_tabs default) uses obligation only (cheap).
    show_money_tab = (
        profile.owes_tuition
        or is_dues_obligated(user)
        or _has_money_history(user)
    )
    ctx["show_money_tab"] = show_money_tab

    tabs = available_tabs(user, tuition=show_money_tab, account=show_money_tab)
    keys = {k for k, _ in tabs}
    active = request.GET.get("tab") or "formation"
    if active not in keys:
        active = "formation"
    ctx["formation_tabs"] = tabs
    ctx["active_tab"] = active

    # Lazy per-tab context — only the active tab pays for its queries. (The
    # Formation tab's advisor/steps above are always built: it's the default.)
    if active in ("groups", "events"):
        ctx.update(_formation_groups_events_context(request))
    elif active in ("tuition", "account"):
        ctx.update(_formation_money_context(request))
    elif active == "works":
        from works.queries import my_works_qs
        ctx["works"] = my_works_qs(user)
    elif active == "proposals":
        from events.models import EventProposal
        ctx["proposals"] = (
            EventProposal.objects.filter(proposed_by=user)
            .select_related("minted_event")
        )
    elif active == "suggestions":
        from suggestions.models import Suggestion
        ctx["suggestions"] = Suggestion.objects.filter(submitted_by=user)
    elif active == "profile":
        from accounts.views import _profile_edit_context
        ctx.update(_profile_edit_context(request))
        ctx["profile_next"] = _formation_url("profile")

    return ctx


def _has_money_history(user) -> bool:
    """Whether the member has any payment or (non-skipping) tuition enrollment —
    so the Tuition/Dues tabs stay reachable after the obligation lapses."""
    from payments.models import Payment, TuitionEnrollment

    return (
        Payment.objects.filter(user=user).exists()
        or TuitionEnrollment.objects.filter(user=user)
        .exclude(status=TuitionEnrollment.Status.SKIPPING)
        .exists()
    )


#: Each formation track's role ladder. The step *into* index 1 is the
#: Palimpsest; the step into index 2 is the Passage (Analyst) / Traversée
#: (Scholar).
_FORMATION_TRACKS = {
    "analyst": ["pre_candidate", "candidate", "analyst"],
    "scholar": ["pre_candidate_scholar", "candidate_scholar", "scholar"],
}


def _formation_track_for(roles_held):
    """Which ladder the member is on, from any analyst/scholar-track role they
    hold now or have held. Returns ``(name, ladder)`` or ``(None, None)``."""
    for name, ladder in _FORMATION_TRACKS.items():
        if roles_held & set(ladder):
            return name, ladder
    return None, None


def _formation_steps(user):
    """The member's formation steps as a display trace.

    Derived from the **role history** (``MembershipTenure``) so a Palimpsest or
    Passage/Traversée completed before this system — or set by import — still
    shows, dated to the academic year the member entered the target role. Any
    actual ``Advancement`` demande is overlaid for its status/dates and the Work
    file. Only completed steps (or steps with a demande on file) are listed; the
    *next* available step is offered by the demande form, not here."""
    from accounts.models import MembershipTenure

    from .models import Advancement, step_label_for

    tenures = list(MembershipTenure.objects.filter(user=user))
    roles_held = {t.role for t in tenures} | {user.profile.role}
    track, ladder = _formation_track_for(roles_held)
    if ladder is None:
        return []

    # Earliest AY the member entered each role (the step's "when").
    entered_ay: dict[str, int] = {}
    for t in tenures:
        if t.role not in entered_ay or t.start_ay < entered_ay[t.role]:
            entered_ay[t.role] = t.start_ay

    max_rank = max(
        (ladder.index(r) for r in roles_held if r in ladder), default=-1
    )

    advs = {
        a.kind: a
        for a in Advancement.objects.filter(member=user)
        .select_related("advisor").order_by("requested_at")
    }

    # The artifact for each step is a real Work (works app), of the matching
    # Kind, authored by the member — not a file on the demande. Map the step to
    # the Work.Kind, distinguishing the Analyst Passage from the Scholar
    # Traversée.
    from works.models import Work

    scholar = track == "scholar"
    work_kind_for = {
        1: Work.Kind.PALIMPSEST,
        2: Work.Kind.TRAVERSEE if scholar else Work.Kind.PASSAGE,
    }
    my_works = (
        Work.objects.filter(authors=user, kind__in=work_kind_for.values())
        .order_by("-created_at")
    )
    works_by_kind: dict[str, list] = {}
    for w in my_works:
        works_by_kind.setdefault(w.kind, []).append(w)

    steps = []
    for i, kind in ((1, Advancement.Kind.PALIMPSEST), (2, Advancement.Kind.PASSAGE)):
        from_role, target_role = ladder[i - 1], ladder[i]
        adv = advs.get(kind)
        completed = max_rank >= i
        if not completed and adv is None:
            continue  # not reached and no demande on file — the form covers it
        work_kind = work_kind_for[i]
        steps.append({
            "kind": kind,
            "label": step_label_for(kind, from_role),
            "completed": completed,
            "when_ay": entered_ay.get(target_role) if completed else None,
            "advancement": adv,
            "work_kind": work_kind,
            "works": works_by_kind.get(work_kind, []),
        })
    return steps


def _formation_money_context(request) -> dict:
    """Tuition + the unified account (statement/balance/dues) + the member's
    own payment history — all on one tab (task #439: the member-facing view
    onto the unified ledger, ``payments.ledger.member_account``).

    Tuition: the four-year progress, this year's decision/installments,
    ledger-derived years-covered count. Account: the running-balance
    statement + this year's dues status. Payments: full history (editable
    type/note, and academic year for tuition) from the My Payments table."""
    from payments import ledger
    from payments.dues import is_dues_obligated
    from payments.forms import TuitionDecisionForm
    from payments.models import (
        DuesPeriod,
        Payment,
        TuitionEnrollment,
        TuitionPeriod,
    )

    user = request.user
    profile = user.profile

    # --- The unified account — computed once, everything below derives from it. ---
    acct = ledger.member_account(user)
    requirement_met = ledger.tuition_requirement_met(user)

    # --- Tuition (current year) ---
    period = TuitionPeriod.current()
    enrollment = None
    installments = []
    if period is not None:
        enrollment = TuitionEnrollment.objects.filter(
            user=user, tuition_period=period,
        ).first()
        if enrollment is not None:
            installments = list(enrollment.installments.order_by("sequence"))
    progress = _tuition_progress(user)

    # --- Dues (current year) ---
    dues_period = DuesPeriod.current()
    dues_obligated = is_dues_obligated(user)
    dues_amount = (
        dues_period.amount_for_role(profile.role) if dues_period is not None else None
    )
    dues_paid = acct["dues_state"] in ("paid", "waived")

    # --- Payments (all) — one editable table (type + note + tuition AY) ---
    # Order by the same date the table shows (paid_at, falling back to
    # created_at), newest first — not by created_at alone, which diverges for
    # backfilled/offline charges entered long after they were paid.
    from django.db.models.functions import Coalesce

    payments = list(
        Payment.objects.filter(user=user)
        .select_related("registration__event", "dues_period", "tuition_period")
        .annotate(when=Coalesce("paid_at", "created_at"))
        .order_by("-when", "-id")
    )

    # For tuition rows, pre-select the assigned AY, else the AY the payment date
    # falls in (so the "For" column's year picker starts on the right guess).
    from accounts.membership import current_academic_year_start as ay_of
    tuition_periods = list(TuitionPeriod.objects.order_by("-start_date"))
    period_id_by_ay = {ay_of(tp.start_date): tp.id for tp in tuition_periods}
    for p in payments:
        if p.payment_type != Payment.Type.TUITION:
            continue
        when = p.paid_at or p.created_at
        p.selected_period_id = p.tuition_period_id or (
            period_id_by_ay.get(ay_of(when.date())) if when else None
        )

    show_money_tab = (
        profile.owes_tuition or dues_obligated or bool(payments)
        or progress["tuition_years_started"] > 0
    )

    return {
        "show_money_tab": show_money_tab,
        # unified account (task #439) — statement/balance/tuition-years tile
        "acct": acct,
        "requirement_met": requirement_met,
        # tuition
        "owes_tuition": profile.owes_tuition,
        "tuition_period": period,
        "tuition_enrollment": enrollment,
        # A fully covered year reads as its outcome, not the recorded
        # decision ("Committed" that is actually paid shows "Paid").
        "tuition_decision_label": next(
            (r["decision_label"] for r in acct["tuition_rows"]
             if enrollment and r["enrollment"].pk == enrollment.pk), None),
        "tuition_installments": installments,
        "tuition_form": TuitionDecisionForm(
            initial={"status": enrollment.status} if enrollment else {}
        ),
        "tuition_stripe_status": request.GET.get("stripe"),
        **progress,
        # dues
        "dues_period": dues_period,
        "dues_obligated": dues_obligated,
        "dues_amount": dues_amount,
        "dues_paid": dues_paid,
        # payments
        "my_payments": payments,
        "tuition_periods": tuition_periods,
        "payment_type_choices": Payment.Type.choices,
    }


def _tuition_progress(user) -> dict:
    """The member's progress toward the four years of tuition required for full
    standing.

    A year is "started" if the member has a non-skipping enrollment *or* any
    successful tuition payment dated to it. Progress is driven by **actual
    SUCCEEDED tuition payments** — not installment flags — so ledger-imported,
    Stripe-imported, reconciled, and offline payments all count, even when no
    ``TuitionInstallment`` was ever created. Each started year is one of the
    four slots (goal = that year's amount; a partially-paid year counts its
    remainder as still owed); years not yet started are projected at the
    current rate so there's always a four-slot goal to fill."""
    from payments.models import Payment, TuitionEnrollment, TuitionPeriod

    required = 4

    def ay_of(d):
        """Academic-year start year for a date (the AY begins in September)."""
        return d.year if d.month >= 9 else d.year - 1

    # Goal + name per academic year, and which years count as started.
    period_by_ay: dict[int, object] = {}
    paid_by_ay: dict[int, Decimal] = {}

    # 1) Successful tuition payments → paid, bucketed by academic year (via the
    #    linked period when present, else the payment date).
    payments = (
        Payment.objects
        .filter(user=user, payment_type=Payment.Type.TUITION,
                status=Payment.Status.SUCCEEDED)
        .select_related(
            "tuition_period", "tuition_installment__enrollment__tuition_period",
        )
    )
    for p in payments:
        # Prefer the member's explicit AY assignment, then the installment's
        # period, then the payment date.
        period = p.tuition_period
        if period is None:
            inst = p.tuition_installment
            if inst is not None and inst.enrollment_id:
                period = inst.enrollment.tuition_period
        ay = ay_of(period.start_date) if period else ay_of(p.paid_at or p.created_at)
        if period is not None:
            period_by_ay.setdefault(ay, period)
        paid_by_ay[ay] = paid_by_ay.get(ay, Decimal("0")) + p.amount

    # 2) Non-skipping enrollments mark a year started (even if nothing paid yet).
    for enr in (
        TuitionEnrollment.objects.filter(user=user)
        .exclude(status=TuitionEnrollment.Status.SKIPPING)
        .select_related("tuition_period")
    ):
        ay = ay_of(enr.tuition_period.start_date)
        period_by_ay.setdefault(ay, enr.tuition_period)
        paid_by_ay.setdefault(ay, Decimal("0"))

    current = (
        TuitionPeriod.current()
        or TuitionPeriod.objects.order_by("-start_date").first()
    )
    rate = (current.tuition_amount if current else None) or Decimal("0")

    slots = []
    total_paid = Decimal("0")
    total_goal = Decimal("0")
    for ay in sorted(paid_by_ay)[:required]:
        period = period_by_ay.get(ay)
        goal = (period.tuition_amount if period else rate) or Decimal("0")
        paid = min(paid_by_ay[ay], goal) if goal else paid_by_ay[ay]
        pct = int(paid / goal * 100) if goal else 0
        slots.append({
            "label": period.name if period else f"{ay}–{ay + 1}",
            "goal": goal, "paid": paid, "remaining": max(goal - paid, Decimal("0")),
            "pct": pct, "projected": False,
        })
        total_paid += paid
        total_goal += goal

    started = len(slots)
    for _ in range(started, required):
        slots.append({
            "label": "Future year", "goal": rate, "paid": Decimal("0"),
            "remaining": rate, "pct": 0, "projected": True,
        })
        total_goal += rate

    return {
        "tuition_slots": slots,
        "tuition_years_started": started,
    }


def _formation_groups_events_context(request) -> dict:
    """The Groups and Events tabs: the member's current/former groups of every
    kind (the improved ``workgroups.membership`` selectors) and the standalone
    events they're registered for, plus the personal calendar-subscribe URLs.

    One pass over ``my_groups`` feeds both tabs — Events excludes anything
    already shown as a group. A calendar token is *not* minted while
    impersonating (we're only viewing as the member)."""
    import re

    from django.urls import reverse

    from workgroups.membership import (
        ensure_calendar_token,
        my_events,
        my_groups,
        my_groups_by_kind,
    )

    user = request.user
    rows = my_groups(user)
    events = my_events(user, {r.workgroup.id for r in rows})
    current = [r for r in rows if r.is_current]
    past = [r for r in rows if not r.is_current]

    calendar_feed_url = webcal_url = None
    if not getattr(request, "impersonator", None):
        token = ensure_calendar_token(user)
        calendar_feed_url = request.build_absolute_uri(
            reverse("workgroups:my_calendar_ics", args=[token])
        )
        webcal_url = re.sub(r"^https?://", "webcal://", calendar_feed_url)

    return {
        "current_by_kind": my_groups_by_kind(current),
        "past_by_kind": my_groups_by_kind(past),
        "groups_has_any": bool(rows),
        "upcoming_events": [e for e in events if e.is_upcoming],
        "past_events": [e for e in events if not e.is_upcoming],
        "calendar_has_any": bool(rows) or bool(events),
        "calendar_feed_url": calendar_feed_url,
        "webcal_url": webcal_url,
    }


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
    return render(request, "formation/formation.html",
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


@login_required
def control_add(request):
    """Add a control (supervisory) analysis entry — a self-reported record, no
    approval required."""
    if request.method == "POST":
        form = ControlAnalysisForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.member = request.user
            obj.save()
            messages.success(request, "Control analysis added.")
            return redirect(_formation_url("formation"))
    else:
        form = ControlAnalysisForm(user=request.user)
    return render(request, "formation/_control_form.html", {"form": form, "mode": "add"})


@login_required
def control_edit(request, pk):
    """Edit one of the member's own control-analysis entries. A non-owner gets
    a 404 (no signal that the entry exists at all)."""
    obj = get_object_or_404(ControlAnalysis, pk=pk, member=request.user)
    if request.method == "POST":
        form = ControlAnalysisForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Control analysis updated.")
            return redirect(_formation_url("formation"))
    else:
        form = ControlAnalysisForm(instance=obj, user=request.user)
    return render(request, "formation/_control_form.html",
                  {"form": form, "mode": "edit", "entry": obj})


@login_required
@require_POST
def control_delete(request, pk):
    """Delete one of the member's own control-analysis entries."""
    obj = get_object_or_404(ControlAnalysis, pk=pk, member=request.user)
    obj.delete()
    messages.success(request, "Control analysis removed.")
    return redirect(_formation_url("formation"))


@login_required
def external_add(request):
    """Add an external-activity entry, a self-reported record, no approval
    required."""
    if request.method == "POST":
        form = ExternalActivityForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.member = request.user
            obj.save()
            messages.success(request, "External activity added.")
            return redirect(_formation_url("formation"))
    else:
        form = ExternalActivityForm()
    return render(request, "formation/_external_form.html", {"form": form, "mode": "add"})


@login_required
def external_edit(request, pk):
    """Edit one of the member's own external-activity entries. A non-owner
    gets a 404 (no signal that the entry exists at all)."""
    obj = get_object_or_404(ExternalActivity, pk=pk, member=request.user)
    if request.method == "POST":
        form = ExternalActivityForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "External activity updated.")
            return redirect(_formation_url("formation"))
    else:
        form = ExternalActivityForm(instance=obj)
    return render(request, "formation/_external_form.html",
                  {"form": form, "mode": "edit", "entry": obj})


@login_required
@require_POST
def external_delete(request, pk):
    """Delete one of the member's own external-activity entries."""
    obj = get_object_or_404(ExternalActivity, pk=pk, member=request.user)
    obj.delete()
    messages.success(request, "External activity removed.")
    return redirect(_formation_url("formation"))


@login_required
def external_analyst_request(request):
    """A member requests authorization to use an external control analyst."""
    from . import notifications as notify_formation

    if request.method == "POST":
        form = ExternalControlAnalystForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.member = request.user
            obj.save()
            notify_formation.external_analyst_requested(obj)
            messages.success(
                request,
                "Request sent to the Meeting of the Analysts, you'll be "
                "notified when they decide.")
            return redirect(_formation_url("formation") + "#control")
    else:
        form = ExternalControlAnalystForm()
    return render(request, "formation/external_analyst_request.html", {"form": form})


# ---- Advisor side ---------------------------------------------------------

@login_required
def advise_queue(request):
    """Demandes this Advisor is responsible for presenting to the Meeting."""
    advancements = list(
        Advancement.objects.filter(advisor=request.user)
        .select_related("member", "member__profile")
        .order_by("status", "-requested_at")
    )
    return render(request, "formation/advise_queue.html", {
        "advancements": advancements,
    })


@login_required
@require_POST
def advise_present(request, pk):
    adv = get_object_or_404(Advancement, pk=pk, advisor=request.user)
    if not adv.is_open:
        messages.error(request, "That demande has already been decided.")
        return redirect("formation:advise_queue")
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
    return redirect("formation:advise_queue")


# ---- Advisor View: read-only advisee record + private notes ---------------

@login_required
def advisees(request):
    """The advisor's current advisees, each linking to their read-only record."""
    from .permissions import current_advisees

    rows = current_advisees(request.user)
    return render(request, "formation/advisees.html", {"advisorships": rows})


@login_required
def advisee_detail(request, pk):
    """An advisee's read-only formation record plus an advisor-only notes panel.
    Gated to the advisee's current advisor (and staff); everyone else is denied.
    The advisee never sees this page's notes, they only appear here."""
    from accounts.models import User

    from .models import AdvisorNote
    from .permissions import can_view_advisee

    advisee = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    ctx = {
        "advisee": advisee,
        "advancements": Advancement.objects.filter(member=advisee)
        .select_related("advisor").order_by("-requested_at"),
        "control_entries": ControlAnalysis.objects.filter(member=advisee),
        "control_progress": control_progress(advisee),
        "external_entries": ExternalActivity.objects.filter(member=advisee)
        .order_by("kind", "-start_date"),
        "notes": AdvisorNote.objects.filter(advisee=advisee).select_related("author"),
    }
    return render(request, "formation/advisee_detail.html", ctx)


@login_required
@require_POST
def advisee_note_add(request, pk):
    """Record a private advisor note about an advisee."""
    from django.urls import reverse

    from accounts.models import User

    from .models import AdvisorNote
    from .permissions import can_view_advisee

    advisee = get_object_or_404(User, pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    body = (request.POST.get("body") or "").strip()
    if body:
        AdvisorNote.objects.create(advisee=advisee, author=request.user, body=body)
        messages.success(request, "Note added.")
    return redirect(reverse("formation:advisee_detail", args=[advisee.pk]))


@login_required
@require_POST
def advisee_set_background(request, pk):
    """Advisor (or staff) sets an advisee's clinical/academic background."""
    from accounts.models import User

    from .permissions import can_view_advisee
    advisee = get_object_or_404(User.objects.select_related("profile"), pk=pk)
    if not can_view_advisee(request.user, advisee):
        raise PermissionDenied
    advisee.profile.clinical_background = bool(request.POST.get("clinical_background"))
    advisee.profile.save(update_fields=["clinical_background"])
    messages.success(request, "Background updated.")
    return redirect("formation:advisee_detail", pk=advisee.pk)


# ---- Meeting of the Analysts review side ----------------------------------

@login_required
def advancement_queue(request):
    _require_review(request)
    from payments.ledger import tuition_clearance

    advancements = list(
        Advancement.objects.select_related(
            "member", "member__profile", "advisor"
        ).order_by("status", "-requested_at")
    )
    for a in advancements:
        a.tuition_blocked = bool(
            a.is_open and a.advance_role in GATED_ROLES
            and tuition_clearance(a.member)
        )
    return render(request, "formation/advancement_queue.html", {
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
    tuition_reasons = None
    if adv.advance_role in GATED_ROLES and adv.is_open:
        from payments.ledger import tuition_clearance
        tuition_reasons = tuition_clearance(adv.member)
    return render(request, "formation/advancement_detail.html", {
        "adv": adv,
        "default_ay": current_academic_year_start(),
        "tuition_reasons": tuition_reasons,
    })


@login_required
@require_POST
def advancement_decide(request, pk):
    _require_review(request)
    adv = get_object_or_404(Advancement, pk=pk)
    if not adv.is_open:
        messages.error(request, "This demande has already been decided.")
        return redirect("formation:advancement_detail", pk=pk)
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()
    if decision == "approve":
        from django.core.exceptions import ValidationError

        ay = request.POST.get("effective_ay")
        effective_ay = int(ay) if ay and ay.isdigit() else current_academic_year_start()
        try:
            decide_advancement(adv, approve=True, by=request.user,
                                effective_ay=effective_ay, note=note)
        except ValidationError as exc:
            messages.error(
                request, "Cannot approve — " + " ".join(exc.messages))
            return redirect("formation:advancement_detail", pk=pk)
        name = adv.member.get_full_name() or adv.member.email
        role_label = dict(Profile.Role.choices).get(adv.advance_role, "the next step")
        messages.success(request, f"Approved — {name} advances to {role_label}.")
    elif decision == "decline":
        decide_advancement(adv, approve=False, by=request.user, note=note)
        messages.success(request, "Recorded as not approved; the member has been notified.")
    else:
        messages.error(request, "Choose approve or decline.")
    return redirect("formation:advancement_detail", pk=pk)


# ---- External control analyst review (Meeting of the Analysts) -----------

@login_required
def external_analyst_queue(request):
    _require_review(request)
    requests_ = (ExternalControlAnalyst.objects
                 .select_related("member", "member__profile", "decided_by")
                 .annotate(_open=Case(
                     When(status=ExternalControlAnalyst.Status.REQUESTED, then=Value(0)),
                     default=Value(1), output_field=IntegerField(),
                 ))
                 .order_by("_open", "-requested_at"))
    return render(request, "formation/external_analyst_queue.html", {
        "requests": requests_,
        "open_statuses": ExternalControlAnalyst.OPEN_STATUSES,
    })


@login_required
def external_analyst_detail(request, pk):
    _require_review(request)
    obj = get_object_or_404(
        ExternalControlAnalyst.objects.select_related("member", "member__profile"),
        pk=pk)
    return render(request, "formation/external_analyst_detail.html", {"obj": obj})


@login_required
@require_POST
def external_analyst_decide(request, pk):
    _require_review(request)
    from .control import decide_external
    obj = get_object_or_404(ExternalControlAnalyst, pk=pk)
    if not obj.is_open:
        messages.error(request, "This request has already been decided.")
        return redirect("formation:external_analyst_detail", pk=pk)
    decision = request.POST.get("decision")
    note = (request.POST.get("note") or "").strip()
    if decision == "approve":
        decide_external(obj, approve=True, by=request.user, note=note)
        messages.success(request, f"Approved {obj.name}; the member has been notified.")
    elif decision == "decline":
        decide_external(obj, approve=False, by=request.user, note=note)
        messages.success(request, "Recorded as not approved; the member has been notified.")
    else:
        messages.error(request, "Choose approve or decline.")
    return redirect("formation:external_analyst_detail", pk=pk)
