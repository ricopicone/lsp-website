"""Public-facing auth views (architecture § 6.1) + member directory."""

from __future__ import annotations

import json
import logging
import os

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import StaffRole
from workgroups.models import Workgroup, WorkgroupMembership

from . import emails, twofactor
from .forms import (
    EmailChangeForm,
    LightSignupForm,
    MagicLinkRequestForm,
    ProfileEditForm,
    ReferralRequestForm,
    TOTPCodeForm,
    UserNameForm,
)
from .geocoding import geocode_after_edit
from .images import MAX_UPLOAD_BYTES, InvalidImage, render_headshot_square
from .models import EmailChangeRequest, MagicLoginLink, Profile, TOTPDevice, User

logger = logging.getLogger(__name__)

# Order in which role sections appear on /directory/. Roles not listed here
# (external, student, prospective_applicant) are not shown.
DIRECTORY_SECTIONS = [
    (Profile.Role.ANALYST,               "Analysts of the School"),
    (Profile.Role.CANDIDATE,             "Candidate Analysts"),
    (Profile.Role.PRE_CANDIDATE,         "Pre-Candidate Analysts"),
    (Profile.Role.SCHOLAR,               "Scholars"),
    (Profile.Role.CANDIDATE_SCHOLAR,     "Candidate Scholars"),
    (Profile.Role.PRE_CANDIDATE_SCHOLAR, "Pre-Candidate Scholars"),
    (Profile.Role.MEMBER,                "Members"),
]


def _directory_qs():
    """All directory-eligible profiles, with active public committee
    memberships prefetched onto ``user.active_public_memberships``.

    Committee rosters now live on the committee's workgroup, so this reads
    committee-kind workgroup memberships whose committee is public.
    """
    membership_qs = (
        WorkgroupMembership.objects.serving()
        .filter(
            workgroup__kind=Workgroup.Kind.COMMITTEE,
            workgroup__committee__public=True,
        )
        .select_related("workgroup__committee")
        .order_by("workgroup__committee__name")
    )
    return (
        Profile.objects
        .filter(role__in=Profile.DIRECTORY_ROLES, public=True)
        .exclude(standing__in=Profile.NON_MEMBER_STANDINGS)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__workgroup_memberships",
                queryset=membership_qs,
                to_attr="active_public_memberships",
            ),
            # Board-appointed operational roles (Treasurer, Cartel Coordinator,
            # …) badge the directory. LSP Staff is an internal access
            # designation, not a public position — exclude it. StaffRole.Meta
            # orders by name.
            Prefetch(
                "user__staff_roles",
                queryset=StaffRole.objects.exclude(key=StaffRole.LSP_STAFF),
                to_attr="public_staff_roles",
            ),
        )
        .order_by("user__last_name", "user__first_name")
    )


def _badge_staff_roles(user):
    """The user's board-appointee StaffRole badges, minus any whose position is
    already shown by a committee officer badge.

    A Treasurer who is the Board's Treasurer would otherwise get both a
    standalone "Treasurer" badge and a "Board of Directors · Treasurer" badge —
    the committee one is more informative, so drop the redundant standalone.
    StaffRole keys and ``WorkgroupMembership.Role`` values share strings for the
    overlapping positions (treasurer, web_coordinator, referral_coordinator,
    admin_assistant), so a key match is a position match.

    The President / Vice-President StaffRoles are the exception where the
    position keys differ: the Board's Chair / Co-chair membership *is* the
    school President / Vice-President (shown relabeled on the committee badge —
    tasks #368, #428), so map those to drop the redundant standalone badge too.

    Relies on the ``public_staff_roles`` / ``active_public_memberships``
    prefetches set by ``_directory_qs``.
    """
    from core.models import StaffRole

    # The Board's stored Chair / Co-chair are the President / Vice-President.
    BOARD_OFFICER_STAFFROLE = {
        "chair": StaffRole.PRESIDENT,
        "co_chair": StaffRole.VICE_PRESIDENT,
    }
    officer_keys = set()
    for m in getattr(user, "active_public_memberships", []):
        officer_keys.add(m.role)
        if m.workgroup.committee.slug == "board":
            officer_keys.add(BOARD_OFFICER_STAFFROLE.get(m.role, m.role))
    return [
        role for role in getattr(user, "public_staff_roles", [])
        if role.key not in officer_keys
    ]


def signup(request):
    """Lightweight account creation. Logs the user in on success."""
    if request.user.is_authenticated:
        return redirect(_safe_next(request) or "/")
    if request.method == "POST":
        form = LightSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(_safe_next(request) or "/")
    else:
        form = LightSignupForm()
    return render(
        request,
        "registration/signup.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def directory(request):
    """Grid of all members grouped by role section."""
    by_role: dict[str, list[dict]] = {}
    for profile in _directory_qs():
        profile.badge_staff_roles = _badge_staff_roles(profile.user)
        by_role.setdefault(profile.role, []).append({
            "profile": profile,
            "slug": profile.directory_slug,
            "show_location": profile.visible_to("location", request.user),
        })
    sections = [
        {"role": role, "label": label, "members": by_role.get(role, [])}
        for role, label in DIRECTORY_SECTIONS
        if by_role.get(role)
    ]
    return render(request, "accounts/directory.html", {"sections": sections})


def directory_detail(request, slug: str):
    """Full bio page for one member."""
    from works.models import Work, WorkAuthor
    for profile in _directory_qs():
        if profile.directory_slug == slug:
            profile.badge_staff_roles = _badge_staff_roles(profile.user)
            works = (
                Work.listing_for(request.user)
                .filter(authors=profile.user)
                .prefetch_related(
                    Prefetch(
                        "authorships",
                        queryset=(
                            WorkAuthor.objects
                            .select_related("user")
                            .order_by("display_order")
                        ),
                    ),
                )
                .order_by("-publication_date", "-created_at")
            )
            return render(
                request,
                "accounts/directory_detail.html",
                {
                    "profile": profile,
                    "section_label": dict(DIRECTORY_SECTIONS)[profile.role],
                    "works": works,
                    "vis": profile.visible_fields(request.user),
                    # Members-only: which LSP functions this analyst is open for.
                    "availability": _availability_rows(profile, request.user),
                    "availability_note": _availability_note(profile, request.user),
                },
            )
    raise Http404("Member not found")


def _availability_rows(profile, user):
    """For an authenticated member viewing an analyst, the analyst's status for
    each active LSP function (Yes / No / Unknown), with any note. Returns None
    for anonymous viewers or non-analysts — the data is members-only and only
    applies to Analysts of the School (see availability.services)."""
    if not getattr(user, "is_authenticated", False):
        return None
    from availability import services
    from availability.models import AnalystFunction, AvailabilitySpan
    if not services.is_eligible(profile):
        return None
    spans = {
        s.function_id: s
        for s in profile.availability_spans.filter(end_date__isnull=True)
    }
    rows = []
    for fn in AnalystFunction.objects.filter(is_active=True):
        span = spans.get(fn.pk)
        rows.append({
            "function": fn,
            "status": span.status if span else AvailabilitySpan.Status.UNKNOWN,
        })
    return rows


def _availability_note(profile, user):
    """The analyst's current availability note for an authenticated viewer
    (members-only); None otherwise."""
    if not getattr(user, "is_authenticated", False):
        return None
    from availability import services
    if not services.is_eligible(profile):
        return None
    return services.current_note(profile)


@login_required
def directory_availability(request):
    """Members-only table of which Analysts of the School are available for each
    LSP function. Lists every analyst (new ones appear automatically); sortable
    and filterable by column, with the sort/filter state in the URL
    (?sort=<slug>, ?only=<slug>) so any view is linkable."""
    from availability import services
    from availability.models import AnalystFunction, AvailabilityNote, AvailabilitySpan

    Status = AvailabilitySpan.Status
    functions = list(AnalystFunction.objects.filter(is_active=True))
    fn_by_slug = {f.slug: f for f in functions}

    profiles = list(
        services.eligible_profiles()
        .filter(is_persona=False, user__is_active=True)
        .select_related("user")
        .order_by("user__last_name", "user__first_name")
    )
    spans = AvailabilitySpan.objects.filter(
        profile__in=profiles, function__in=functions, end_date__isnull=True
    )
    smap = {(s.profile_id, s.function_id): s for s in spans}
    # Current note per analyst (latest row), in one pass.
    notes = {}
    for n in AvailabilityNote.objects.filter(profile__in=profiles).order_by("created_at"):
        notes[n.profile_id] = n.text  # later rows overwrite → ends on the latest

    rows = []
    for p in profiles:
        by_fn = {}
        for f in functions:
            span = smap.get((p.pk, f.pk))
            by_fn[f.pk] = {
                "function": f,
                "status": span.status if span else Status.UNKNOWN,
            }
        rows.append({
            "profile": p,
            "slug": p.directory_slug,
            "linkable": p.is_listed,  # only public profiles have a detail page
            "note": notes.get(p.pk, ""),
            "by_fn": by_fn,
            "cells": [by_fn[f.pk] for f in functions],
        })

    only_fn = fn_by_slug.get(request.GET.get("only") or "")
    if only_fn:
        rows = [r for r in rows if r["by_fn"][only_fn.pk]["status"] == Status.YES]

    sort_fn = fn_by_slug.get(request.GET.get("sort") or "")
    if sort_fn:
        rows.sort(key=lambda r: (
            0 if r["by_fn"][sort_fn.pk]["status"] == Status.YES else 1,
            r["profile"].user.last_name.lower(),
            r["profile"].user.first_name.lower(),
        ))

    return render(request, "accounts/directory_availability.html", {
        "functions": functions,
        "rows": rows,
        "only": only_fn,
        "sort": sort_fn,
        "total": len(rows),
    })


def find_an_analyst(request):
    """Public Find-an-Analyst page: referral form + interactive map of members.

    Handles form GET (display) and POST. A valid submission becomes a tracked
    ``referrals.ReferralRequest`` (the coordinator inquiry email and, in auto
    mode, the acknowledgment are sent by ``referrals.services.intake``).
    """
    submitted = request.GET.get("submitted") == "1"
    if request.method == "POST":
        form = ReferralRequestForm(request.POST)
        if form.is_valid():
            from referrals.services import intake

            modality_labels = dict(form.fields["modality"].choices)
            intake({
                "name":      form.cleaned_data["name"],
                "pronouns":  form.pronouns_display(),
                "email":     form.cleaned_data["email"],
                "location":  form.cleaned_data["location"],
                "language":  form.cleaned_data["language"],
                "modality":  ", ".join(
                    modality_labels.get(v, v) for v in form.cleaned_data["modality"]
                ),
                "additional_information": form.cleaned_data["additional_information"],
            })
            return redirect(f"{request.path}?submitted=1#submitted")
    else:
        form = ReferralRequestForm()
    return render(request, "accounts/find_an_analyst.html", {
        "form": form,
        "submitted": submitted,
    })


def find_an_analyst_pins(request):
    """JSON feed of geocoded public directory members for the Leaflet map.

    Returns a flat ``pins`` array — one entry per geocoded *location*, not
    per profile, so members who list two places (e.g. "San Francisco &
    Palo Alto, CA") render as two markers.
    """
    qs = (
        Profile.objects
        .filter(role__in=Profile.DIRECTORY_ROLES, public=True)
        .exclude(standing__in=Profile.NON_MEMBER_STANDINGS)
        .exclude(location_lat__isnull=True)
        .exclude(location_lng__isnull=True)
        .select_related("user")
    )
    pins = []
    for p in qs:
        # Respect the member's location visibility — no public pin if they've
        # restricted their location to members-only / private (vs this viewer).
        if not p.visible_to("location", request.user):
            continue
        # location_pins is the canonical store (one entry per geocoded
        # sub-place). Fall back to (location_lat, location_lng) as a single
        # synthetic pin for profiles geocoded before multi-pin landed.
        raw_pins = p.location_pins or [{
            "lat": p.location_lat, "lng": p.location_lng, "label": p.location,
        }]
        for pin in raw_pins:
            pins.append({
                "name":      f"{p.user.first_name} {p.user.last_name}".strip(),
                "slug":      p.directory_slug,
                "role":      p.get_role_display(),
                "location":  pin.get("label") or p.location,
                "lat":       pin["lat"],
                "lng":       pin["lng"],
                "headshot":  p.headshot.url if p.headshot else "",
                "accepting": p.accepting_patients,
            })
    return JsonResponse({"pins": pins})


def _safe_next(request) -> str | None:
    """Only allow ``next`` redirects to relative URLs we control."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return None


@login_required
def timezone_settings(request):
    """Legacy redirect — the timezone picker is now folded into the unified
    profile editor (its own section + anchor). Kept so old bookmarks and the
    ``set_timezone_from_browser`` flow still resolve."""
    return redirect(reverse("profile_edit") + "#timezone")


_CROP_KEYS = ("x", "y", "width", "height", "rotate", "scaleX", "scaleY")


def _parse_crop(raw: str | None) -> dict:
    """Parse the cropper's JSON payload into a clean numeric dict."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in _CROP_KEYS:
        if key in data:
            try:
                out[key] = float(data[key])
            except (TypeError, ValueError):
                pass
    return out


def _apply_headshot(profile, new_file, crop, remove):
    """Mutate ``profile``'s headshot fields in place (caller saves).

    Three paths: remove, upload-a-new-photo, or re-crop the existing
    original. Raises :class:`InvalidImage` on a bad upload; leaves the
    profile untouched when there's nothing to do.
    """
    if remove:
        if profile.headshot:
            profile.headshot.delete(save=False)
        if profile.headshot_original:
            profile.headshot_original.delete(save=False)
        profile.headshot_crop = {}
        return

    if new_file is not None:
        if new_file.size and new_file.size > MAX_UPLOAD_BYTES:
            raise InvalidImage("That image is too large (12 MB max).")
        square = render_headshot_square(new_file, crop)
        new_file.seek(0)  # render consumed the stream; rewind to store original
        ext = os.path.splitext(new_file.name)[1].lower() or ".img"
        if profile.headshot_original:
            profile.headshot_original.delete(save=False)
        profile.headshot_original.save(f"{profile.user.pk}{ext}", new_file, save=False)
    elif crop and profile.headshot_original:
        profile.headshot_original.open("rb")
        square = render_headshot_square(profile.headshot_original, crop)
    else:
        return  # no photo change in this submission

    if profile.headshot:
        profile.headshot.delete(save=False)
    profile.headshot.save(f"{profile.user.pk}.webp", square, save=False)
    profile.headshot_crop = crop or {}


def _profile_edit_context(request, *, uform=None, pform=None, image_error=None):
    """Context for the profile editor — shared by the standalone page and the
    embedded My LSP Profile tab. Bound forms may be passed in to re-render a
    failed POST with errors.

    Field-group flags: only show listing/practice sections to members who
    actually appear on public pages, and billing only to faculty. The public
    directory lists everyone in a directory role (Profile.public is not a gate
    anywhere — see _directory_qs), and faculty show on event pages.
    """
    user = request.user
    profile = user.profile
    if uform is None:
        uform = UserNameForm(instance=user)
    if pform is None:
        pform = ProfileEditForm(instance=profile)
    show_practice = profile.role in {
        Profile.Role.ANALYST,
        Profile.Role.CANDIDATE,
        Profile.Role.PRE_CANDIDATE,
    }
    availability_rows = _availability_rows(profile, user)
    return {
        "uform":         uform,
        "pform":         pform,
        "profile":       profile,
        "saved":         request.GET.get("saved") == "1",
        "image_error":   image_error,
        "show_listing":  profile.is_in_directory or profile.is_faculty,
        "show_practice": show_practice,
        "show_billing":  profile.is_faculty,
        "show_availability": availability_rows is not None,
        "availability_rows": availability_rows or [],
        "can_change_email": can_change_email(user),
    }


def _profile_saved_redirect(request) -> str:
    """Where to land after a successful save: a validated posted ``next`` (the
    My LSP Profile tab, when embedded), else the standalone editor."""
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        sep = "&" if "?" in next_url else "?"
        return f"{next_url}{sep}saved=1#saved"
    return reverse("profile_edit") + "?saved=1#saved"


@login_required
def profile_edit(request):
    """Self-service profile editor (USR-6+): name, headshot, bio, listing.

    Edits ``User`` name fields and the member-editable ``Profile`` fields in
    one page. ``role`` / ``is_faculty`` stay staff-only and render read-only.
    The headshot is processed through the Pillow square-crop pipeline so it
    renders correctly in every circle/square frame across the site. The same
    editor is embedded as the My LSP Profile tab; a posted ``next`` (validated)
    sends a successful save back there.
    """
    user = request.user
    profile = user.profile

    if request.method == "POST":
        uform = UserNameForm(request.POST, instance=user)
        pform = ProfileEditForm(request.POST, instance=profile)
        if uform.is_valid() and pform.is_valid():
            crop = _parse_crop(request.POST.get("headshot_crop"))
            new_file = request.FILES.get("headshot_file")
            remove = request.POST.get("remove_headshot") == "1"
            try:
                prof = pform.save(commit=False)
                _apply_headshot(prof, new_file, crop, remove)
            except InvalidImage as exc:
                return render(
                    request, "accounts/profile_edit.html",
                    _profile_edit_context(request, uform=uform, pform=pform,
                                          image_error=str(exc)),
                )
            uform.save()
            prof.save()
            geocode_after_edit(prof)
            return redirect(_profile_saved_redirect(request))
        return render(
            request, "accounts/profile_edit.html",
            _profile_edit_context(request, uform=uform, pform=pform),
        )
    return render(request, "accounts/profile_edit.html",
                  _profile_edit_context(request))


@require_POST
@login_required
def profile_autosave(request):
    """Debounced background save of the profile's *text* fields, so a member's
    typing survives leaving the page. The headshot is NOT handled here — it's
    saved only via the explicit Save (the cropper pipeline). Returns JSON; an
    invalid round just doesn't save (the explicit Save surfaces field errors)."""
    uform = UserNameForm(request.POST, instance=request.user)
    pform = ProfileEditForm(request.POST, instance=request.user.profile)
    if uform.is_valid() and pform.is_valid():
        uform.save()
        prof = pform.save()
        geocode_after_edit(prof)
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False})


def can_change_email(user) -> bool:
    """Whether ``user`` may use the self-service login-email change.

    Gated until launch: everyone once ``EMAIL_CHANGE_PUBLIC`` is on, else
    only addresses in ``EMAIL_CHANGE_ALLOWLIST`` (case-insensitive)."""
    if getattr(settings, "EMAIL_CHANGE_PUBLIC", False):
        return True
    allow = {e.strip().lower() for e in getattr(settings, "EMAIL_CHANGE_ALLOWLIST", [])}
    return bool(user.is_authenticated and user.email.lower() in allow)


@login_required
def email_change(request):
    """Initiate a login-email change (gated; password re-auth required).

    On success creates an :class:`EmailChangeRequest`, supersedes any prior
    pending one, and emails a verification link to the new address. The
    login email does not change until that link is confirmed.
    """
    if not can_change_email(request.user):
        raise Http404

    sent_to = None
    if request.method == "POST":
        form = EmailChangeForm(request.POST, user=request.user)
        if form.is_valid():
            new_email = form.cleaned_data["new_email"]
            # Supersede prior unconfirmed requests so old links stop working.
            EmailChangeRequest.objects.filter(
                user=request.user, confirmed_at__isnull=True
            ).delete()
            req = EmailChangeRequest.objects.create(
                user=request.user, new_email=new_email
            )
            emails.send_email_change_verification(req)
            sent_to = new_email
            form = None  # fall through to the "check your inbox" state
    else:
        form = EmailChangeForm(user=request.user)

    return render(request, "accounts/email_change.html", {
        "form":    form,
        "sent_to": sent_to,
    })


def email_change_confirm(request, token):
    """Confirm an email change from the link sent to the new address.

    Token-only (clickable from the new inbox without being logged in). Idempotent
    against reuse and re-checks uniqueness to close the request→confirm race.
    """
    req = EmailChangeRequest.objects.filter(token=token).select_related("user").first()
    status = None
    if req is None or req.confirmed_at is not None:
        status = "invalid"
    elif req.is_expired():
        status = "expired"
    elif User.objects.filter(email__iexact=req.new_email).exclude(pk=req.user_id).exists():
        # Someone else claimed the address between request and confirmation.
        status = "taken"
    else:
        with transaction.atomic():
            user = req.user
            old_email = user.email
            user.email = req.new_email
            user.save(update_fields=["email"])
            req.confirmed_at = timezone.now()
            req.save(update_fields=["confirmed_at"])
        try:
            emails.send_email_change_notice(user, old_email, req.new_email)
        except Exception:  # a failed courtesy notice must not undo the change
            logger.exception("email-change notice to %s failed", old_email)
        status = "ok"

    return render(request, "accounts/email_change_confirm.html", {
        "status":    status,
        "new_email": req.new_email if req else None,
    })


@require_POST
@login_required
def set_timezone_from_browser(request):
    """Save a browser-detected IANA TZ to Profile.timezone.

    Called via a small JS POST on signup / first dropdown-open. Idempotent
    — no-op if Profile.timezone is already set. Validates against the
    curated list before saving.
    """
    if request.user.profile.timezone:
        return JsonResponse({"ok": True, "saved": False, "reason": "already-set"})
    from .timezones import IS_VALID
    tz_name = (request.POST.get("tz") or "").strip()
    if tz_name not in IS_VALID:
        return JsonResponse({"ok": False, "reason": "not-in-curated-list"})
    request.user.profile.timezone = tz_name
    request.user.profile.save(update_fields=("timezone",))
    return JsonResponse({"ok": True, "saved": True, "tz": tz_name})


@login_required
def advisor_select(request):
    """Self-service Advisor choice. The Advisor form lives on the Formation hub
    (``formation:formation``); this endpoint handles its POST and otherwise
    redirects there — there's no standalone Advisor page anymore."""
    from django.contrib import messages

    from .advisor import set_advisor
    from .forms import AdvisorSelectForm

    formation_url = reverse("formation:formation") + "?tab=formation"
    profile = request.user.profile
    if request.method == "POST" and profile.needs_advisor:
        form = AdvisorSelectForm(request.POST, advisee=request.user)
        if form.is_valid():
            set_advisor(request.user, form.cleaned_data["advisor"], by=request.user)
            messages.success(request, "Your Advisor has been recorded.")
        else:
            messages.error(request, "Please choose an eligible Advisor.")
    return redirect(formation_url)


# --- Passwordless sign-in (magic link) ----------------------------------

def magic_link_request(request):
    """Request a single-use sign-in link by email (no password).

    Never reveals whether an account exists — the same confirmation renders
    either way. Repeat submits reuse the most recent unexpired link rather
    than minting a pile of them.
    """
    # Where to land after sign-in (e.g. a meeting deep link that bounced the
    # user through login). Carried into the emailed link and honored on consume.
    nxt = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(nxt or "/")
    sent = False
    if request.method == "POST":
        form = MagicLinkRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user is not None:
                link = (
                    MagicLoginLink.objects
                    .filter(user=user, used_at__isnull=True)
                    .order_by("-created_at")
                    .first()
                )
                if link is None or link.is_expired():
                    link = MagicLoginLink.objects.create(user=user)
                try:
                    emails.send_magic_link(link, next_url=nxt or "")
                except Exception:  # delivery failure must not leak existence
                    logger.exception("magic-link email to %s failed", user.email)
            sent = True
            form = None
    else:
        form = MagicLinkRequestForm()
    return render(request, "accounts/magic_link_request.html", {
        "form": form, "sent": sent, "next": nxt or "",
    })


def magic_link_consume(request, token):
    """Log in from a magic link. Single-use; admins still hit 2FA after."""
    if request.user.is_authenticated:
        return redirect(_safe_next(request) or "/")
    link = MagicLoginLink.objects.filter(token=token).select_related("user").first()
    if link is None or not link.is_valid or not link.user.is_active:
        return render(request, "accounts/magic_link_invalid.html", status=410)
    link.consume()
    login(request, link.user)
    return redirect(_safe_next(request) or settings.LOGIN_REDIRECT_URL)


# --- Two-factor authentication (TOTP) -----------------------------------

@login_required
def twofactor_setup(request):
    """Enroll (or show the status of) an authenticator-app second factor.

    Available to anyone — enrollment is decoupled from whether the
    requirement is switched on (see ``TWO_FACTOR_ENFORCED``). On first
    confirmation we mint one-time recovery codes and show them once.
    """
    device, _ = TOTPDevice.objects.get_or_create(
        user=request.user, defaults={"secret": twofactor.new_secret()},
    )
    if device.confirmed:
        return render(request, "accounts/twofactor_status.html", {"device": device})

    error = None
    if request.method == "POST":
        form = TOTPCodeForm(request.POST)
        if form.is_valid() and twofactor.verify_code(device, form.cleaned_data["code"]):
            device.confirmed = True
            device.last_used_at = timezone.now()
            device.save(update_fields=["confirmed", "last_used_at"])
            request.session[twofactor.SESSION_VERIFIED_KEY] = True
            request.session["2fa_recovery_codes"] = twofactor.generate_recovery_codes(device)
            return redirect("twofactor_recovery")
        error = "That code didn't match. Check your authenticator app and try again."
    else:
        form = TOTPCodeForm()

    return render(request, "accounts/twofactor_setup.html", {
        "form": form,
        "secret": device.secret,
        "qr_svg": twofactor.qr_svg(twofactor.provisioning_uri(device)),
        "error": error,
    })


@login_required
def twofactor_recovery(request):
    """Show freshly-minted backup codes exactly once (right after setup)."""
    codes = request.session.pop("2fa_recovery_codes", None)
    if not codes:
        return redirect("twofactor_setup")
    return render(request, "accounts/twofactor_recovery.html", {"codes": codes})


@login_required
def twofactor_verify(request):
    """Per-session challenge: enter a TOTP (or a backup recovery code)."""
    device = twofactor.confirmed_device(request.user)
    if device is None:
        return redirect("twofactor_setup")
    if request.session.get(twofactor.SESSION_VERIFIED_KEY):
        return redirect(_safe_next(request) or "/")

    error = None
    if request.method == "POST":
        form = TOTPCodeForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"]
            if twofactor.verify_code(device, code) or twofactor.verify_recovery_code(device, code):
                device.last_used_at = timezone.now()
                device.save(update_fields=["last_used_at"])
                request.session[twofactor.SESSION_VERIFIED_KEY] = True
                return redirect(_safe_next(request) or "/")
            error = "That code didn't match. Try again, or use a backup code."
    else:
        form = TOTPCodeForm()

    return render(request, "accounts/twofactor_verify.html", {
        "form": form, "error": error, "next": request.GET.get("next", ""),
    })


@login_required
def twofactor_disable(request):
    """Turn off 2FA for the current account (password re-auth required).

    If the requirement is on for this user, the next request simply sends
    them back through enrollment — but disabling is still how you re-enroll
    a new authenticator.
    """
    from django.contrib import messages

    device = getattr(request.user, "totp_device", None)
    if device is None:
        return redirect("profile_edit")

    error = None
    if request.method == "POST":
        if request.user.check_password(request.POST.get("password", "")):
            device.delete()
            request.session.pop(twofactor.SESSION_VERIFIED_KEY, None)
            messages.success(request, "Two-factor authentication has been turned off.")
            return redirect("profile_edit")
        error = "That password is incorrect."

    return render(request, "accounts/twofactor_disable.html", {"error": error})


# ---------------------------------------------------------------------------
# Member intake survey (launch onboarding)
# ---------------------------------------------------------------------------

@login_required
def intake_survey(request):
    """The launch intake survey — a friendly single page. Confirms a few fields,
    a tuition/dues year-grid, formation-step years, and the member's advisor; on
    submit it reconciles into structured records (see ``accounts.survey``)."""
    from django.contrib import messages

    from .advisor import current_advisor, eligible_advisors, set_advisor
    from .forms import IntakeSurveyForm
    from .membership import academic_year_choices
    from .models import MemberIntakeSurvey, Profile
    from .survey import (
        apply_survey,
        milestone_questions,
        parse_grid,
        parse_milestones,
        survey_year_rows,
    )

    survey = MemberIntakeSurvey.objects.filter(user=request.user).first()
    profile = request.user.profile
    needs_advisor = profile.needs_advisor
    can_list = profile.is_in_directory
    on_tuition_track = profile.role in (
        Profile.IN_TRAINING_ROLES | {Profile.Role.ANALYST, Profile.Role.SCHOLAR}
    )
    ay_choices = academic_year_choices()

    if request.method == "POST":
        form = IntakeSurveyForm(request.POST, ay_choices=ay_choices)
        if form.is_valid():
            apply_survey(
                request.user,
                year_joined=form.cleaned_data["year_joined"],
                payment_names=form.cleaned_data["payment_names"],
                payment_emails=form.cleaned_data["payment_emails"],
                grid=parse_grid(request.POST),
                milestones=parse_milestones(request.POST),
                list_in_directory=(
                    form.cleaned_data["list_in_directory"] if can_list else None
                ),
                paid_all_tuition=(
                    form.cleaned_data["paid_all_tuition"] if on_tuition_track else None
                ),
            )
            if needs_advisor and request.POST.get("advisor"):
                advisor = eligible_advisors(request.user).filter(
                    pk=request.POST["advisor"]
                ).first()
                if advisor is not None:
                    set_advisor(request.user, advisor, by=request.user)
            messages.success(request, "Thanks — your answers are saved.")
            return redirect(reverse("intake_survey") + "?done=1")
    else:
        form = IntakeSurveyForm(ay_choices=ay_choices, initial={
            "year_joined": (survey.year_joined if survey else None) or profile.year_joined,
            "payment_names": survey.payment_names if survey else "",
            "payment_emails": survey.payment_emails if survey else "",
            "list_in_directory": profile.public,
        })

    rows = survey_year_rows(request.user)
    return render(request, "accounts/survey.html", {
        "form": form,
        "rows": rows,
        "survey": survey,
        "done": request.GET.get("done") == "1",
        "ay_choices": ay_choices,
        "show_paid_all": on_tuition_track,
        "tuition_prechecked": sum(1 for r in rows if r["tuition_state"] == "full"),
        "milestones": milestone_questions(request.user),
        "needs_advisor": needs_advisor,
        "advisors": eligible_advisors(request.user) if needs_advisor else [],
        "current_advisor": current_advisor(request.user) if needs_advisor else None,
        "can_list": can_list,
    })
