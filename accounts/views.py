"""Public-facing auth views (architecture § 6.1) + member directory."""

from __future__ import annotations

import json
import logging
import os

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from committees.models import CommitteeMembership

from . import emails
from .forms import (
    LightSignupForm,
    ProfileEditForm,
    ReferralRequestForm,
    UserNameForm,
)
from .images import MAX_UPLOAD_BYTES, InvalidImage, render_headshot_square
from .models import Profile

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
    memberships prefetched onto ``user.active_public_memberships``."""
    membership_qs = (
        CommitteeMembership.objects
        .filter(end_date__isnull=True, committee__public=True)
        .select_related("committee")
        .order_by("committee__name")
    )
    return (
        Profile.objects
        .filter(role__in=Profile.DIRECTORY_ROLES)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__committee_memberships",
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
        .filter(role__in=Profile.DIRECTORY_ROLES)
        .exclude(location_lat__isnull=True)
        .exclude(location_lng__isnull=True)
        .select_related("user")
    )
    pins = []
    for p in qs:
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
    # actually appear on public pages, and billing only to faculty.
    show_listing = profile.is_in_directory or profile.is_faculty or profile.public
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
