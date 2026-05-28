"""Public-facing auth views (architecture § 6.1) + member directory."""

from __future__ import annotations

from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.text import slugify

from .forms import LightSignupForm
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


def _member_slug(profile: Profile) -> str:
    """Slug derived from the user's name: "andre-patsalides"."""
    return (
        slugify(f"{profile.user.first_name} {profile.user.last_name}".strip())
        or str(profile.user.pk)
    )


def _directory_qs():
    return (
        Profile.objects
        .filter(role__in=[r for r, _ in DIRECTORY_SECTIONS])
        .select_related("user")
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
            "slug": _member_slug(profile),
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
        if _member_slug(profile) == slug:
            return render(
                request,
                "accounts/directory_detail.html",
                {"profile": profile, "section_label": dict(DIRECTORY_SECTIONS)[profile.role]},
            )
    raise Http404("Member not found")


def _safe_next(request) -> str | None:
    """Only allow ``next`` redirects to relative URLs we control."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return None
