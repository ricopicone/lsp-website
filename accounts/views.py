"""Public-facing auth views (architecture § 6.1) + member directory."""

from __future__ import annotations

from django.contrib.auth import login
from django.db.models import Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render

from committees.models import CommitteeMembership

from . import emails
from .forms import LightSignupForm, ReferralRequestForm
from .models import Profile

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
    for profile in _directory_qs():
        if profile.directory_slug == slug:
            return render(
                request,
                "accounts/directory_detail.html",
                {"profile": profile, "section_label": dict(DIRECTORY_SECTIONS)[profile.role]},
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
            data = dict(form.cleaned_data)
            # Convert the modality machine value to its display label for the email.
            data["modality"] = dict(form.fields["modality"].choices).get(
                data["modality"], data["modality"]
            )
            data.pop("website", None)
            emails.send_referral_inquiry(data)
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
