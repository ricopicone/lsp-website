"""Admin Tools — one hub linking each governance body / staff role to its own
admin page.

``home`` lists the admin pages the current user can reach, one card each:
the **Board** and **Program Committee** (governance bodies), and the staff
roles (**Treasurer**, **Cartel Coordinator**, **Administrative Assistant**,
**Web Coordinator**, **Web Developer**). Each card is gated to its body/role,
so a user sees only their own. Some pages live here (web-coordinator,
web-developer, admin-assistant, board); others link to existing dashboards
(treasurer, program-committee, cartel review). Built to grow: gate a card in
``_panels_for`` by the relevant body/role.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .access import has_staff_role, staff_role_required
from .forms import AphorismForm
from .models import Aphorism, StaffRole

#: Staff roles that map to their own admin page in the hub (NB: lsp_staff has no
#: page of its own — it's a general designation, not an admin area).
PANEL_ROLES = (
    StaffRole.WEB_COORDINATOR,
    StaffRole.TREASURER,
    StaffRole.CARTEL_COORDINATOR,
    StaffRole.ADMIN_ASSISTANT,
    StaffRole.WEB_DEVELOPER,
    StaffRole.REFERRAL_COORDINATOR,
    StaffRole.REGISTRAR,
)


def _can_treasurer(user) -> bool:
    return user.is_superuser or user.is_staff or has_staff_role(user, StaffRole.TREASURER)


def _can_board(user) -> bool:
    from committees.permissions import is_on_committee
    return user.is_superuser or user.is_staff or is_on_committee(user, "board")


def _can_program_committee(user) -> bool:
    from events.permissions import is_program_committee
    return user.is_superuser or user.is_staff or is_program_committee(user)


def _can_meeting_of_analysts(user) -> bool:
    from workgroups.permissions import is_meeting_of_analysts
    return user.is_superuser or user.is_staff or is_meeting_of_analysts(user)


def _can_cartel_coordinator(user) -> bool:
    from cartels.permissions import is_cartel_coordinator
    return user.is_superuser or user.is_staff or is_cartel_coordinator(user)


def _can_registrar(user) -> bool:
    from registrations.permissions import can_administer_registrations
    return can_administer_registrations(user)


def _can_applications_coordinator(user) -> bool:
    from workgroups.permissions import is_applications_coordinator
    return is_applications_coordinator(user)


def can_access_admin_tools(user) -> bool:
    """Entry gate to /admin-tools/: staff-role holders, Board members, and
    Program Committee members (plus Django staff / superusers). Members of
    *other* committees reach their workspace via Groups, not here. Kept cheap
    for the nav link."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    if has_staff_role(user, *PANEL_ROLES):
        return True
    return (
        _can_board(user)
        or _can_program_committee(user)
        or _can_meeting_of_analysts(user)
        or _can_applications_coordinator(user)
    )


def _panels_for(user) -> list[dict]:
    """The admin pages ``user`` may reach, in display order. One card per
    governance body / staff role the user belongs to."""
    panels = []

    # --- Governance bodies ---
    if _can_board(user):
        panels.append({
            "title": "Board Admin",
            "blurb": "Board membership, documents, and meeting records.",
            "url": reverse("board_admin"),
        })
    if _can_program_committee(user):
        panels.append({
            "title": "Program Committee Admin",
            "blurb": "Solicit and review proposals; mint events into a program.",
            "url": reverse("program_admin_programs"),
        })
    if _can_registrar(user):
        from registrations.models import Registration
        panels.append({
            "title": "Registration Admin",
            "blurb": "Registrations across all events: approve, comp, and "
                     "open or close registration.",
            "url": reverse("registrations:registrar"),
            "count": Registration.objects.filter(
                status=Registration.Status.PENDING_APPROVAL
            ).count(),
            "count_label": "pending",
        })
    if _can_meeting_of_analysts(user):
        from admissions.models import Application
        from formation.models import Advancement
        open_count = (
            Application.objects.filter(status__in=Application.OPEN_STATUSES).count()
            + Advancement.objects.filter(
                status__in=Advancement.OPEN_STATUSES
            ).count()
        )
        panels.append({
            "title": "Meeting of Analysts Admin",
            "blurb": "Admissions and formation: review applications, decide "
                     "palimpsest and passage demandes.",
            "url": reverse("meeting_of_analysts_admin"),
            "count": open_count,
            "count_label": "open",
        })

    # --- Staff roles ---
    if _can_treasurer(user):
        panels.append({
            "title": "Treasurer Admin",
            "blurb": "Dues and tuition dashboards, member ledgers, and exports.",
            "url": reverse("treasurer"),
        })
    if _can_cartel_coordinator(user):
        from cartels.models import Cartel
        panels.append({
            "title": "Cartel Coordinator Admin",
            "blurb": "Review proposed cartels (the PC approves; the Coordinator advises).",
            "url": reverse("cartels:review_queue"),
            "count": Cartel.objects.filter(
                workgroup__proposal__status=Cartel.Status.PROPOSED
            ).count(),
            "count_label": "pending",
        })
    if user.is_superuser or has_staff_role(user, StaffRole.ADMIN_ASSISTANT):
        panels.append({
            "title": "Administrative Assistant Admin",
            "blurb": "Board support: membership records, communications, scheduling.",
            "url": reverse("admin_assistant_admin"),
        })
    if user.is_superuser or has_staff_role(user, StaffRole.WEB_COORDINATOR):
        panels.append({
            "title": "Web Coordinator Admin",
            "blurb": "Editable site content — aphorisms and more.",
            "url": reverse("web_coordinator_admin"),
        })
    if user.is_superuser or has_staff_role(user, StaffRole.WEB_DEVELOPER):
        panels.append({
            "title": "Web Developer Admin",
            "blurb": "Technical operations: the Django back office, deploys, internals.",
            "url": reverse("web_developer_admin"),
        })
    # Referral Coordinator — deliberately NOT opened to generic is_staff:
    # requests carry sensitive personal disclosures.
    if user.is_superuser or has_staff_role(user, StaffRole.REFERRAL_COORDINATOR):
        from referrals.models import ReferralRequest
        panels.append({
            "title": "Referral Coordinator Admin",
            "blurb": "Find-an-Analyst requests: distribute to the referral "
                     "list, collect responses, reply to requesters.",
            "url": reverse("referrals:dashboard"),
            "count": ReferralRequest.objects.filter(
                status__in=ReferralRequest.OPEN_STATUSES
            ).count(),
            "count_label": "open",
        })
    # Applications Coordinator — an officer of the Meeting of Analysts who
    # facilitates admissions; deliberately NOT generic is_staff.
    if _can_applications_coordinator(user):
        from admissions.models import Application
        panels.append({
            "title": "Applications Coordinator Admin",
            "blurb": "Facilitate admissions for the Meeting of Analysts: triage "
                     "applications, staff interviewers, chase reports. Plus the "
                     "analyst-availability table.",
            "url": reverse("admissions:coordinator_dashboard"),
            "count": Application.objects.filter(
                status__in=Application.OPEN_STATUSES
            ).count(),
            "count_label": "open",
        })
    if user.is_superuser or has_staff_role(
        user, StaffRole.WEB_COORDINATOR, StaffRole.WEB_DEVELOPER
    ):
        from suggestions.models import Suggestion
        panels.append({
            "title": "Suggestions",
            "blurb": "Member suggestions for the site — triage and export as "
                     "Claude Code briefs.",
            "url": reverse("suggestions_triage"),
            "count": Suggestion.objects.filter(
                status__in=Suggestion.ACTIONABLE_STATUSES
            ).count(),
            "count_label": "open",
        })

    # Every active Analyst gets their interview workspace (agree to interview
    # applicants; submit reports).
    from admissions.permissions import is_analyst
    if is_analyst(user):
        from admissions.models import ApplicationInterview
        panels.append({
            "title": "Analyst — Interviews",
            "blurb": "Applicants who need an interviewer, and the interviews "
                     "you've agreed to — set up a time and submit your report.",
            "url": reverse("admissions:analyst_dashboard"),
            "count": ApplicationInterview.objects.filter(
                interviewer=user, completed_at__isnull=True,
            ).count(),
            "count_label": "to report",
        })

    if user.is_staff:
        panels.append({
            "title": "Django admin",
            "blurb": "The full back office for every model.",
            "url": "/admin/",
        })
    return panels


#: Reference guides surfaced in the staff hub's Documentation section. Each is
#: a Markdown file under ``core/docs/`` rendered by :func:`core.docs.render_doc`.
STAFF_DOCS = [
    {
        "slug": "groups-guide",
        "title": "Groups — a guide",
        "blurb": (
            "How cartels, working groups, committees, seminars, reading groups, "
            "and the Meeting of Analysts work — who creates, approves, joins, "
            "runs, and ends each, with step-by-step recipes."
        ),
    },
    {
        "slug": "registrar-guide",
        "title": "Registration Admin — a guide",
        "blurb": (
            "Managing registrations across all events: approvals, comps, "
            "notes, CSV export, and opening or closing registration."
        ),
    },
]
_STAFF_DOCS_BY_SLUG = {d["slug"]: d for d in STAFF_DOCS}


@login_required
def home(request):
    # Authoritative gate: you reach the hub iff you have at least one tool.
    panels = _panels_for(request.user)
    if not panels:
        raise PermissionDenied
    docs = [
        {**d, "url": reverse("staff_doc", args=[d["slug"]])} for d in STAFF_DOCS
    ]
    return render(request, "core/staff/home.html", {"panels": panels, "docs": docs})


@login_required
def doc(request, slug):
    """Render a staff documentation guide (Documentation section of the hub)."""
    if not _panels_for(request.user):
        raise PermissionDenied
    meta = _STAFF_DOCS_BY_SLUG.get(slug)
    if meta is None:
        raise Http404
    from core.docs import render_doc

    return render(request, "core/staff/doc.html", {
        "title": meta["title"],
        "rendered_html": render_doc(slug),
    })


# ---- Per-body / per-role admin landing pages --------------------------------


def school_officers():
    """The President + Vice-President roles with their current holders, for
    display on the bodies they govern (the Board and the Meeting of Analysts).
    One appointment (Board → Appointments) surfaces on both."""
    roles = (
        StaffRole.objects
        .filter(key__in=[StaffRole.PRESIDENT, StaffRole.VICE_PRESIDENT])
        .prefetch_related("holders")
        .order_by("key")  # "president" sorts before "vice_president"
    )
    return [{"name": r.name, "holders": list(r.holders.all())} for r in roles]


@login_required
def board_admin(request):
    """Board's admin landing. Gated to Board members (+ staff/superuser).

    School-governance actions only — the Board's own roster, documents, minutes,
    decisions, and discussion live in its workspace, linked from the page.
    """
    if not _can_board(request.user):
        raise PermissionDenied
    from committees.models import Committee
    from payments.models import TuitionPlanApplication
    board = (
        Committee.objects.filter(slug="board").select_related("workgroup").first()
    )
    workspace_url = (
        reverse("workgroups:detail", args=[board.workgroup.slug])
        if board and board.workgroup_id
        else None
    )
    return render(request, "core/staff/admin/board.html", {
        "workspace_url": workspace_url,
        "officers": school_officers(),
        "pending_plan_count": TuitionPlanApplication.objects.filter(
            status=TuitionPlanApplication.Status.PENDING
        ).count(),
    })


@login_required
def board_membership_admin(request):
    """Membership administration (Board record-keeping): admit members and record
    role/standing transitions, writing each member's tenure timeline + the live
    Profile. Gated to Board members (+ staff/superuser)."""
    if not _can_board(request.user):
        raise PermissionDenied
    from django.contrib import messages
    from django.db.models import Q

    from accounts.forms import MembershipChangeForm
    from accounts.membership import (
        current_academic_year_start,
        record_membership_change,
    )
    from accounts.models import MembershipTenure, User

    member = None
    form = None
    if request.method == "POST":
        action = request.POST.get("action")
        member = get_object_or_404(User, pk=request.POST.get("member"))
        if action in {"set_deceased", "clear_deceased", "waive_charges"}:
            from accounts.lifecycle import clear_deceased, set_deceased
            from payments.charges import waive_open_charges

            if action == "set_deceased":
                from datetime import date as _date
                raw = request.POST.get("deceased_on") or ""
                try:
                    d = _date.fromisoformat(raw)
                except ValueError:
                    messages.error(request, "Enter a valid date (YYYY-MM-DD).")
                else:
                    set_deceased(member, d, by=request.user)
                    messages.success(
                        request,
                        f"Recorded {member.get_full_name() or member.email} "
                        "as deceased. The account is disabled and open charges "
                        "were waived.",
                    )
            elif action == "clear_deceased":
                clear_deceased(member, by=request.user)
                messages.success(
                    request, "Cleared the deceased mark; the account is re-enabled."
                )
            elif action == "waive_charges":
                n = waive_open_charges(
                    member, reason="Waived — member removed", by=request.user,
                )
                messages.success(request, f"Waived {n} open charge(s).")
            return redirect(f"{reverse('board_membership_admin')}?member={member.pk}")
        form = MembershipChangeForm(request.POST, member=member)
        if form.is_valid():
            from django.core.exceptions import ValidationError

            try:
                record_membership_change(
                    member,
                    role=form.cleaned_data["role"],
                    standing=form.cleaned_data["standing"],
                    effective_ay=form.cleaned_data["effective_ay"],
                    notes=form.cleaned_data["notes"],
                    by=request.user,
                )
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Recorded a membership change for "
                    f"{member.get_full_name() or member.email}.",
                )
                return redirect(
                    f"{reverse('board_membership_admin')}?member={member.pk}"
                )
    else:
        member_id = request.GET.get("member")
        if member_id:
            member = (
                User.objects.filter(pk=member_id).select_related("profile").first()
            )

    q = (request.GET.get("q") or "").strip()
    results = []
    if q and member is None:
        results = list(
            User.objects.filter(
                Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q),
            )
            .select_related("profile")
            .order_by("last_name", "first_name", "email")[:50]
        )

    timeline = []
    open_owes = None
    if member is not None:
        timeline = list(
            MembershipTenure.objects.filter(user=member).order_by("-start_ay")
        )
        if form is None:
            form = MembershipChangeForm(
                initial={
                    "role": member.profile.role,
                    "standing": member.profile.standing,
                    "effective_ay": current_academic_year_start(),
                },
                member=member,
            )
        from payments.ledger import member_account
        open_owes = member_account(member)["owes"]  # Decimal; 0 if nothing owed

    return render(request, "core/staff/admin/board_membership.html", {
        "q": q, "results": results, "member": member,
        "timeline": timeline, "form": form, "open_owes": open_owes,
    })


@login_required
def board_appointments(request):
    """Appoint and reassign the operational staff roles (Treasurer, Web
    Coordinator, Cartel Coordinator, Administrative Assistant, Web Developer,
    LSP Staff). Gated to Board members (+ staff/superuser).

    Committee chairs and officers are roster roles — set those in each
    committee's workspace (see Committees), not here.
    """
    if not _can_board(request.user):
        raise PermissionDenied
    from accounts.models import Profile, User

    if request.method == "POST":
        action = request.POST.get("action")
        role = StaffRole.objects.filter(key=request.POST.get("role")).first()
        member = User.objects.filter(pk=request.POST.get("user")).first()
        if role is not None and role.key in (
            StaffRole.PRESIDENT, StaffRole.VICE_PRESIDENT
        ):
            messages.error(
                request,
                "President and Vice President are set in the Board's Settings "
                "roster (Chair and Co-chair).",
            )
            return redirect("board_appointments")
        if role is None or member is None:
            messages.error(request, "Couldn't find that role or member.")
        elif action == "appoint":
            role.holders.add(member)
            messages.success(
                request,
                f"Appointed {member.get_full_name() or member.email} as {role.name}.",
            )
        elif action == "remove":
            role.holders.remove(member)
            messages.success(
                request,
                f"Removed {member.get_full_name() or member.email} from {role.name}.",
            )
        return redirect("board_appointments")

    roles = list(
        StaffRole.objects
        .exclude(key__in=[StaffRole.PRESIDENT, StaffRole.VICE_PRESIDENT])
        .prefetch_related("holders")
        .order_by("name")
    )
    appointable = list(
        User.objects.filter(is_active=True, profile__is_persona=False)
        .exclude(profile__standing__in=Profile.NON_MEMBER_STANDINGS)
        .select_related("profile")
        .order_by("last_name", "first_name", "email")
    )
    return render(request, "core/staff/admin/board_appointments.html", {
        "roles": roles, "appointable": appointable,
    })


@login_required
def board_committees(request):
    """Create and oversee committees. Saving a new committee auto-provisions its
    backing workgroup (roster, workspace, channel). Gated to Board members."""
    if not _can_board(request.user):
        raise PermissionDenied
    from committees.models import Committee

    from .forms import CommitteeForm

    editing = None
    edit_id = request.POST.get("committee") or request.GET.get("committee")
    if edit_id:
        editing = Committee.objects.filter(pk=edit_id).first()

    if request.method == "POST":
        form = CommitteeForm(request.POST, instance=editing)
        if form.is_valid():
            committee = form.save()
            messages.success(
                request,
                f"{'Updated' if editing else 'Created'} the {committee.name} committee.",
            )
            return redirect("board_committees")
    else:
        form = CommitteeForm(instance=editing)

    committees = list(
        Committee.objects.select_related("workgroup").order_by("name")
    )
    return render(request, "core/staff/admin/board_committees.html", {
        "committees": committees, "form": form, "editing": editing,
    })


@login_required
def board_governance(request):
    """The Board's at-a-glance dashboard: membership by standing and role,
    pending decisions across the school, and a link to finances."""
    if not _can_board(request.user):
        raise PermissionDenied
    from django.db.models import Count

    from accounts.models import Profile
    from admissions.models import Application
    from committees.models import Committee
    from formation.models import Advancement

    member_qs = Profile.objects.filter(
        role__in=Profile.DIRECTORY_ROLES, is_persona=False, user__is_active=True,
    ).exclude(standing__in=Profile.NON_MEMBER_STANDINGS)
    by_standing = {
        row["standing"]: row["n"]
        for row in member_qs.values("standing").annotate(n=Count("pk"))
    }
    standings = [
        {"label": label, "value": value, "n": by_standing.get(value, 0)}
        for value, label in Profile.Standing.choices
    ]
    by_role = {
        row["role"]: row["n"]
        for row in member_qs.values("role").annotate(n=Count("pk"))
    }
    roles = [
        {"label": label, "n": by_role.get(value, 0)}
        for value, label in Profile.Role.choices
        if value in Profile.DIRECTORY_ROLES and by_role.get(value, 0)
    ]

    pending = {
        "applications": Application.objects.filter(
            status__in=Application.OPEN_STATUSES
        ).count(),
        "advancements": Advancement.objects.filter(
            status__in=Advancement.OPEN_STATUSES
        ).count(),
    }
    try:
        from cartels.models import Cartel
        pending["cartels"] = Cartel.objects.filter(
            workgroup__proposal__status=Cartel.Status.PROPOSED
        ).count()
    except Exception:
        pending["cartels"] = 0

    return render(request, "core/staff/admin/board_governance.html", {
        "standings": standings,
        "roles": roles,
        "total_members": member_qs.count(),
        "pending": pending,
        "committee_count": Committee.objects.count(),
    })


@login_required
def meeting_of_analysts_admin(request):
    """The Meeting of the Analysts' admin landing — the formation pipeline.

    Per ``content/pages/about.md`` the Analysts "review admissions materials …
    and make admission decisions" and "this meeting considers demands for
    palimpsests and passages." Gated to the Meeting of Analysts (every active
    Analyst, via the workgroup's role-derived membership) + staff/superuser.
    """
    if not _can_meeting_of_analysts(request.user):
        raise PermissionDenied
    from accounts.models import Profile
    from admissions.models import Application
    from formation.models import Advancement, ExternalControlAnalyst
    return render(request, "core/staff/admin/meeting_of_analysts.html", {
        "open_applications": Application.objects.filter(
            status__in=Application.OPEN_STATUSES
        ).count(),
        "open_advancements": Advancement.objects.filter(
            status__in=Advancement.OPEN_STATUSES
        ).count(),
        "open_external_analysts": ExternalControlAnalyst.objects.filter(
            status__in=ExternalControlAnalyst.OPEN_STATUSES).count(),
        "open_backgrounds": Profile.objects.filter(
            role__in=Profile.IN_TRAINING_ROLES,
            formation_background=Profile.FormationBackground.UNREVIEWED,
        ).exclude(is_persona=True).count(),
        "officers": school_officers(),
    })


@login_required
@staff_role_required(StaffRole.ADMIN_ASSISTANT)
def admin_assistant_admin(request):
    """Administrative Assistant to the Board admin landing."""
    return render(request, "core/staff/admin/admin_assistant.html", {})


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def web_coordinator_admin(request):
    """Web Coordinator admin landing — site content tools (aphorisms + more)."""
    return render(request, "core/staff/admin/web_coordinator.html", {
        "active_aphorisms": Aphorism.objects.filter(is_active=True).count(),
        "total_aphorisms": Aphorism.objects.count(),
    })


@login_required
@staff_role_required(StaffRole.WEB_DEVELOPER)
def web_developer_admin(request):
    """Web Developer admin landing — technical operations."""
    return render(request, "core/staff/admin/web_developer.html", {})


@login_required
@staff_role_required(StaffRole.WEB_DEVELOPER)
def video_upload_settings(request):
    """Control surface for Works video uploads: on/off + per-file size cap
    (cost control), with a quick usage count."""
    from works.forms import VideoUploadSettingsForm
    from works.models import VideoUploadSettings, Work

    cfg = VideoUploadSettings.load()
    saved = False
    if request.method == "POST":
        form = VideoUploadSettingsForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            saved = True
    else:
        form = VideoUploadSettingsForm(instance=cfg)
    return render(request, "core/staff/admin/video_settings.html", {
        "form": form,
        "saved": saved,
        "video_count": Work.objects.exclude(video="").count(),
    })


# ---- Aphorisms panel --------------------------------------------------------


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_list(request):
    return render(
        request,
        "core/staff/aphorisms.html",
        {"aphorisms": Aphorism.objects.all()},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_create(request):
    form = AphorismForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, "Aphorism added.")
        return redirect("staff_aphorisms")
    return render(request, "core/staff/aphorism_form.html", {"form": form, "mode": "new"})


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def aphorism_edit(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    form = AphorismForm(request.POST or None, instance=aphorism)
    if form.is_valid():
        form.save()
        messages.success(request, "Aphorism updated.")
        return redirect("staff_aphorisms")
    return render(
        request,
        "core/staff/aphorism_form.html",
        {"form": form, "mode": "edit", "aphorism": aphorism},
    )


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
@require_POST
def aphorism_delete(request, pk):
    get_object_or_404(Aphorism, pk=pk).delete()
    messages.success(request, "Aphorism deleted.")
    return redirect("staff_aphorisms")


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
@require_POST
def aphorism_toggle(request, pk):
    aphorism = get_object_or_404(Aphorism, pk=pk)
    aphorism.is_active = not aphorism.is_active
    aphorism.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Aphorism {'shown' if aphorism.is_active else 'hidden'}.")
    return redirect("staff_aphorisms")
