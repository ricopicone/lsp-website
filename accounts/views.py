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
from django.views.decorators.http import require_POST

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
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__workgroup_memberships",
                queryset=membership_qs,
                to_attr="active_public_memberships",
            )
        )
        .order_by("user__last_name", "user__first_name")
    )


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
                },
            )
    raise Http404("Member not found")


def find_an_analyst(request):
    """Public Find-an-Analyst page: referral form + interactive map of members.

    Handles form GET (display) and POST (validate, email coordinator,
    redirect to ``?submitted=1``).
    """
    submitted = request.GET.get("submitted") == "1"
    if request.method == "POST":
        form = ReferralRequestForm(request.POST)
        if form.is_valid():
            modality_labels = dict(form.fields["modality"].choices)
            data = {
                "name":      form.cleaned_data["name"],
                "pronouns":  form.pronouns_display(),
                "email":     form.cleaned_data["email"],
                "location":  form.cleaned_data["location"],
                "language":  form.cleaned_data["language"],
                "modality":  ", ".join(
                    modality_labels.get(v, v) for v in form.cleaned_data["modality"]
                ),
                "additional_information": form.cleaned_data["additional_information"],
            }
            emails.send_referral_inquiry(data)
            # Acknowledgment to the inquirer — failure here shouldn't
            # mask the success of the coordinator email above.
            try:
                emails.send_referral_acknowledgment(data)
            except Exception:
                logger.exception("Failed to send referral acknowledgment to %s", data["email"])
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


@login_required
def profile_edit(request):
    """Self-service profile editor (USR-6+): name, headshot, bio, listing.

    Edits ``User`` name fields and the member-editable ``Profile`` fields in
    one page. ``role`` / ``is_faculty`` stay staff-only and render read-only.
    The headshot is processed through the Pillow square-crop pipeline so it
    renders correctly in every circle/square frame across the site.
    """
    user = request.user
    profile = user.profile
    image_error = None

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
                image_error = str(exc)
            else:
                uform.save()
                prof.save()
                return redirect(reverse("profile_edit") + "?saved=1#saved")
    else:
        uform = UserNameForm(instance=user)
        pform = ProfileEditForm(instance=profile)

    # Field-group flags: only show listing/practice sections to members who
    # actually appear on public pages, and billing only to faculty. The
    # public directory lists everyone in a directory role (Profile.public is
    # not a gate anywhere — see _directory_qs), and faculty show on event pages.
    show_listing = profile.is_in_directory or profile.is_faculty
    show_practice = profile.role in {
        Profile.Role.ANALYST,
        Profile.Role.CANDIDATE,
        Profile.Role.PRE_CANDIDATE,
    }
    return render(request, "accounts/profile_edit.html", {
        "uform":         uform,
        "pform":         pform,
        "profile":       profile,
        "saved":         request.GET.get("saved") == "1",
        "image_error":   image_error,
        "show_listing":  show_listing,
        "show_practice": show_practice,
        "show_billing":  profile.is_faculty,
        "can_change_email": can_change_email(user),
    })


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
    (``admissions:formation``); this endpoint handles its POST and otherwise
    redirects there — there's no standalone Advisor page anymore."""
    from django.contrib import messages

    from .advisor import set_advisor
    from .forms import AdvisorSelectForm

    formation_url = reverse("admissions:formation") + "?tab=formation"
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
    if request.user.is_authenticated:
        return redirect(_safe_next(request) or "/")
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
                    emails.send_magic_link(link)
                except Exception:  # delivery failure must not leak existence
                    logger.exception("magic-link email to %s failed", user.email)
            sent = True
            form = None
    else:
        form = MagicLinkRequestForm()
    return render(request, "accounts/magic_link_request.html", {
        "form": form, "sent": sent,
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
    return redirect(settings.LOGIN_REDIRECT_URL)


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
    """The launch intake survey — a friendly single page. Confirms a few fields
    and one year-grid (which years you paid tuition/dues); on submit it
    reconciles into structured records (see ``accounts.survey``)."""
    from django.contrib import messages

    from .forms import IntakeSurveyForm
    from .models import MemberIntakeSurvey
    from .survey import apply_survey, parse_grid, survey_year_rows

    survey = MemberIntakeSurvey.objects.filter(user=request.user).first()
    profile = request.user.profile

    if request.method == "POST":
        form = IntakeSurveyForm(request.POST)
        if form.is_valid():
            apply_survey(
                request.user,
                year_joined=form.cleaned_data["year_joined"],
                pronouns=(form.cleaned_data["pronouns"] or None),
                payment_names=form.cleaned_data["payment_names"],
                payment_emails=form.cleaned_data["payment_emails"],
                grid=parse_grid(request.POST),
            )
            messages.success(request, "Thanks — your answers are saved.")
            return redirect(reverse("intake_survey") + "?done=1")
    else:
        form = IntakeSurveyForm(initial={
            "year_joined": (survey.year_joined if survey else None) or profile.year_joined,
            "pronouns": profile.pronouns,
            "payment_names": survey.payment_names if survey else "",
            "payment_emails": survey.payment_emails if survey else "",
        })

    rows = survey_year_rows(request.user)
    return render(request, "accounts/survey.html", {
        "form": form,
        "rows": rows,
        "survey": survey,
        "done": request.GET.get("done") == "1",
        "tuition_prechecked": sum(1 for r in rows if r["tuition_checked"]),
    })
