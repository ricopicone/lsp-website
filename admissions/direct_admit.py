"""Admitting a member who never applied on the site (task #476).

Deliberately in the **Web Coordinator's** admin rather than the Applications
Coordinator's console. That console is the application process; a second
admission button inside it would invite reaching for the shortcut instead of
deciding the application in front of you. Different role, different surface,
and :class:`admissions.forms.DirectAdmitForm` refuses anyone who has an
application row at all.

The admission itself is not reimplemented here: it goes through
``services.admit_member``, the same chokepoint ``accept_application`` uses.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.emails import send_account_ready
from accounts.models import Profile, User, WelcomeEmail
from core.access import staff_role_required
from core.models import StaffRole

from .emails import send_direct_acceptance
from .forms import DirectAdmitForm
from .services import admit_member


@login_required
@staff_role_required(StaffRole.WEB_COORDINATOR)
def direct_admit(request):
    form = DirectAdmitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member = _admit(form, by=request.user)
        messages.success(
            request,
            f"Admitted {member.get_full_name()} ({member.email}). "
            "Dues charges are minted by the treasurer's Sync charges.",
        )
        return redirect("admissions:direct_admit")
    return render(request, "admissions/direct_admit.html", {"form": form})


@transaction.atomic
def _admit(form, *, by) -> User:
    data = form.cleaned_data
    member = form.existing_user
    if member is None:
        member = User.objects.create_user(
            email=data["email"],
            password=None,  # unusable: they set one from the invitation
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
    else:
        member.first_name = data["first_name"]
        member.last_name = data["last_name"]
        member.save(update_fields=["first_name", "last_name"])

    profile = member.profile
    profile.year_joined = data["effective_ay"]
    # Staff-vouched, so this account is not an unconfirmed self-signup —
    # a null email_verified_at is what marks those for purging (#471).
    if profile.email_verified_at is None:
        profile.email_verified_at = timezone.now()
    profile.save(update_fields=["year_joined", "email_verified_at"])

    admit_member(
        member,
        track=data["track"],
        formation_background=data["formation_background"],
        effective_ay=data["effective_ay"],
        by=by,
        tenure_note=(
            "Admitted directly by the Web Coordinator, no site application. "
            f"{data['note']}"
        ).strip(),
        background_note="Set at direct admission.",
    )

    send = data["send"]
    if send == DirectAdmitForm.SEND_LETTER:
        send_direct_acceptance(
            member, track=data["track"],
            background=_application_background(data["formation_background"]),
            note=data["note"],
        )
    elif send == DirectAdmitForm.SEND_ACCOUNT:
        send_account_ready(member, track=data["track"])

    # Whatever we sent (including nothing), keep the launch welcome sweep off
    # them: send_welcome_emails picks up any active account without this row,
    # and a second "here's how to sign in" letter would only confuse.
    WelcomeEmail.objects.get_or_create(user=member)
    return member


def _application_background(formation_background: str) -> str:
    """Map a ``Profile.FormationBackground`` to the ``Application.Background``
    value the letter's formation label is built from."""
    from .models import Application

    return {
        Profile.FormationBackground.CLINICAL: Application.Background.CLINICAL,
        Profile.FormationBackground.ACADEMIC: Application.Background.ACADEMIC,
    }.get(formation_background, "")
