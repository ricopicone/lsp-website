"""The Referral Coordinator surface (/admin-tools/referrals/) and the
clinician respond page (/referrals/<reference>/respond/).

Coordinator views are gated to the Referral Coordinator staff role +
superusers only — requests carry sensitive disclosures, so unlike most
admin-tools panels, generic ``is_staff`` does not get in. The respond page
is gated to active referral-list members.
"""

from __future__ import annotations

from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    AddClinicianForm,
    ClinicianEditForm,
    FollowupForm,
    MessageTemplateForm,
    NotesForm,
    RecordResponseForm,
    ReferralSettingsForm,
    RespondForm,
)
from .models import (
    BlockedSubmission,
    MessageTemplate,
    ReferralListMember,
    ReferralRequest,
    ReferralResponse,
    ReferralSettings,
)
from .permissions import can_coordinate_referrals


def coordinator_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_coordinate_referrals(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def _get_request(reference: str) -> ReferralRequest:
    return get_object_or_404(ReferralRequest, reference=reference)


#: (key, label) for the coordinator surface's tabs, in display order.
TABS = [
    ("requests",   "Requests"),
    ("clinicians", "Referral list"),
    ("templates",  "Templates"),
    ("settings",   "Settings"),
    ("help",       "Help"),
]


def _tab_links() -> list[tuple[str, str, str]]:
    """[(key, label, url), ...] for core/_admin_tab_nav.html."""
    from django.urls import reverse
    name_to_url = {
        "requests":   reverse("referrals:dashboard"),
        "clinicians": reverse("referrals:clinicians"),
        "templates":  reverse("referrals:templates"),
        "settings":   reverse("referrals:settings"),
        "help":       reverse("referrals:help"),
    }
    return [(key, label, name_to_url[key]) for key, label in TABS]


def _render(request, tab_key: str, template: str, ctx: dict):
    """Common render helper: injects the tab nav into every coordinator page.
    Sub-pages (request detail, compose, edits) pass their parent tab's key."""
    return render(request, template, {
        **ctx, "tab_key": tab_key, "tabs": _tab_links(),
    })


# ---- Coordinator: requests ---------------------------------------------


@coordinator_required
def dashboard(request):
    status = request.GET.get("status", "open")
    qs = ReferralRequest.objects.all().prefetch_related("responses")
    if status == "open":
        qs = qs.filter(status__in=ReferralRequest.OPEN_STATUSES)
    elif status in ReferralRequest.Status.values:
        qs = qs.filter(status=status)
    else:
        status = "all"
    return _render(request, "requests", "referrals/dashboard.html", {
        "requests": qs,
        "status_filter": status,
        "status_choices": ReferralRequest.Status.choices,
        "open_count": ReferralRequest.objects.filter(
            status__in=ReferralRequest.OPEN_STATUSES
        ).count(),
        "held_count": ReferralRequest.objects.filter(
            status=ReferralRequest.Status.HELD,
        ).count(),
        "blocked_30d": BlockedSubmission.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=30),
        ).count(),
        "config": ReferralSettings.load(),
    })


@coordinator_required
def detail(request, reference):
    req = _get_request(reference)
    return _render(request, "requests", "referrals/detail.html", {
        "req": req,
        "responses": req.responses.select_related(
            "member__user__profile", "recorded_by",
        ),
        "interested_count": req.interested_responses().count(),
        "record_form": RecordResponseForm(),
        "notes_form": NotesForm(
            initial={"coordinator_notes": req.coordinator_notes},
        ),
        "config": ReferralSettings.load(),
    })


@coordinator_required
@require_POST
def send_ack(request, reference):
    req = _get_request(reference)
    services.send_acknowledgment(req)
    messages.success(request, f"Acknowledgment sent to {req.email}.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def distribute(request, reference):
    req = _get_request(reference)
    count = services.distribute(req)
    if count:
        messages.success(
            request,
            f"Distributed {req.reference} to {count} clinician"
            f"{'s' if count != 1 else ''} on the referral list.",
        )
    else:
        messages.warning(
            request,
            "The referral list has no active clinicians — nothing was sent. "
            "Add clinicians on the Referral list page first.",
        )
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def record_response(request, reference):
    req = _get_request(reference)
    form = RecordResponseForm(request.POST)
    if form.is_valid():
        response, created = ReferralResponse.objects.update_or_create(
            request=req,
            member=form.cleaned_data["member"],
            defaults={
                "available": form.cleaned_data["available"],
                "message": form.cleaned_data["message"],
                "recorded_by": request.user,
            },
        )
        messages.success(
            request,
            f"{'Recorded' if created else 'Updated'} a response from "
            f"{response.member}.",
        )
    else:
        messages.error(request, "Couldn't record that response.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
def followup(request, reference):
    req = _get_request(reference)
    if request.method == "POST":
        form = FollowupForm(request.POST)
        if form.is_valid():
            services.send_followup(
                req, form.cleaned_data["subject"], form.cleaned_data["body"],
            )
            messages.success(request, f"Follow-up sent to {req.email}.")
            return redirect("referrals:detail", reference=reference)
    else:
        subject, body = services.build_followup(req)
        form = FollowupForm(initial={"subject": subject, "body": body})
    return _render(request, "requests", "referrals/followup.html", {
        "req": req,
        "form": form,
        "interested_count": req.interested_responses().count(),
    })


@coordinator_required
@require_POST
def close(request, reference):
    req = _get_request(reference)
    req.status = ReferralRequest.Status.CLOSED
    req.closed_at = timezone.now()
    req.save(update_fields=["status", "closed_at"])
    messages.success(request, f"{req.reference} closed.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def reopen(request, reference):
    req = _get_request(reference)
    req.status = (
        ReferralRequest.Status.DISTRIBUTED if req.distributed_at
        else ReferralRequest.Status.ACKNOWLEDGED if req.acknowledged_at
        else ReferralRequest.Status.NEW
    )
    req.closed_at = None
    req.save(update_fields=["status", "closed_at"])
    messages.success(request, f"{req.reference} reopened.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def release(request, reference):
    """Clear a screening hold: the request resumes the normal chain."""
    req = _get_request(reference)
    services.release(req)
    messages.success(
        request,
        f"{req.reference} released. It now follows the normal workflow.",
    )
    return redirect("referrals:detail", reference=reference)


def _audit_note(req, request, text: str) -> None:
    """Append a stamped line to coordinator_notes (the override trail)."""
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{stamp}] {text} — {request.user.email}"
    req.coordinator_notes = (
        f"{req.coordinator_notes}\n{line}".strip()
        if req.coordinator_notes else line
    )


@coordinator_required
@require_POST
def mark_junk(request, reference):
    """Mark a request as junk. Available on any status — this is the escape
    hatch for the coherent-but-fake submission no heuristic will catch."""
    req = _get_request(reference)
    req.status = ReferralRequest.Status.JUNK
    _audit_note(req, request, "Marked as junk")
    req.save(update_fields=["status", "coordinator_notes"])
    messages.success(request, f"{req.reference} marked as junk.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def unmark_junk(request, reference):
    """Undo a junk marking; the request returns to the normal workflow."""
    req = _get_request(reference)
    req.status = ReferralRequest.Status.NEW
    req.held_reason = ""
    req.held_at = None
    _audit_note(req, request, "Unmarked as junk")
    req.save(update_fields=[
        "status", "held_reason", "held_at", "coordinator_notes",
    ])
    messages.success(request, f"{req.reference} restored.")
    return redirect("referrals:detail", reference=reference)


@coordinator_required
@require_POST
def save_notes(request, reference):
    req = _get_request(reference)
    form = NotesForm(request.POST)
    if form.is_valid():
        req.coordinator_notes = form.cleaned_data["coordinator_notes"]
        req.save(update_fields=["coordinator_notes"])
        messages.success(request, "Notes saved.")
    return redirect("referrals:detail", reference=reference)


# ---- Coordinator: the referral list -------------------------------------


@coordinator_required
def clinicians(request):
    if request.method == "POST":
        form = AddClinicianForm(request.POST)
        if form.is_valid():
            member = services.add_to_list(form.cleaned_data["user"])
            note = (
                " New Member Instructions sent."
                if member.onboarded_at else
                " Send their New Member Instructions when ready."
            )
            messages.success(
                request, f"Added {member} to the referral list.{note}",
            )
            return redirect("referrals:clinicians")
    else:
        form = AddClinicianForm()
    return _render(request, "clinicians", "referrals/clinicians.html", {
        "members": ReferralListMember.objects.select_related("user__profile"),
        "form": form,
        "config": ReferralSettings.load(),
    })


@coordinator_required
@require_POST
def clinician_toggle(request, pk):
    member = get_object_or_404(ReferralListMember, pk=pk)
    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])
    messages.success(
        request,
        f"{member} is now {'on' if member.is_active else 'off'} the list.",
    )
    return redirect("referrals:clinicians")


@coordinator_required
@require_POST
def clinician_onboard(request, pk):
    member = get_object_or_404(ReferralListMember, pk=pk)
    services.send_onboarding(member)
    messages.success(request, f"New Member Instructions sent to {member}.")
    return redirect("referrals:clinicians")


@coordinator_required
def clinician_edit(request, pk):
    member = get_object_or_404(
        ReferralListMember.objects.select_related("user__profile"), pk=pk,
    )
    form = ClinicianEditForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Updated {member}.")
        return redirect("referrals:clinicians")
    # What requesters would receive with no override in place.
    profile_block = ReferralListMember(user=member.user).details_block()
    return _render(request, "clinicians", "referrals/clinician_edit.html", {
        "member": member,
        "form": form,
        "profile_block": profile_block,
    })


# ---- Coordinator: templates + settings -----------------------------------


@coordinator_required
def templates_list(request):
    existing = {t.key: t for t in MessageTemplate.objects.all()}
    items = [
        existing.get(key) or MessageTemplate.get(key)
        for key in MessageTemplate.Key.values
    ]
    return _render(request, "templates", "referrals/templates.html", {"templates": items})


@coordinator_required
def template_edit(request, key):
    if key not in MessageTemplate.Key.values:
        raise PermissionDenied
    template = MessageTemplate.get(key)
    form = MessageTemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved “{template.get_key_display()}”.")
        return redirect("referrals:templates")
    return _render(request, "templates", "referrals/template_edit.html", {
        "template": template,
        "form": form,
    })


@coordinator_required
def help_view(request):
    """Help tab — renders the referral coordinator guide markdown doc."""
    from core.docs import render_doc
    return _render(request, "help", "referrals/help.html", {
        "rendered_html": render_doc("referrals-guide"),
    })


@coordinator_required
def settings_view(request):
    config = ReferralSettings.load()
    form = ReferralSettingsForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Referral settings saved.")
        return redirect("referrals:settings")
    return _render(request, "settings", "referrals/settings.html", {"form": form})


# ---- Clinicians: the respond page (step 4) -------------------------------


@login_required
def respond(request, reference):
    member = ReferralListMember.objects.filter(
        user=request.user, is_active=True,
    ).first()
    if member is None and not can_coordinate_referrals(request.user):
        raise PermissionDenied
    req = _get_request(reference)
    existing = (
        ReferralResponse.objects.filter(request=req, member=member).first()
        if member else None
    )
    closed = req.status == ReferralRequest.Status.CLOSED
    can_respond = member is not None and not closed and not req.is_purged
    if request.method == "POST":
        if not can_respond:
            raise PermissionDenied
        form = RespondForm(request.POST, instance=existing)
        if form.is_valid():
            response = form.save(commit=False)
            response.request = req
            response.member = member
            response.recorded_by = None
            response.save()
            messages.success(
                request,
                "Thank you — your response was recorded and connected to "
                f"referral {req.reference}.",
            )
            return redirect("referrals:respond", reference=reference)
    else:
        form = RespondForm(instance=existing) if can_respond else None
    return render(request, "referrals/respond.html", {
        "req": req,
        "form": form,
        "existing": existing,
        "closed": closed,
        "window_closed": req.window_closed,
    })
