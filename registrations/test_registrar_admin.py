"""Registration Admin console (/admin-tools/registrations/) — task #470."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def test_registrar_staff_role_seeded():
    role = StaffRole.objects.get(key=StaffRole.REGISTRAR)
    assert role.name == "Registrar"


def test_registrar_role_never_badges_directory():
    from accounts.views import _badge_staff_roles

    u = User.objects.create_user(email="reg@x.test", password="x")
    StaffRole.objects.get(key=StaffRole.REGISTRAR).holders.add(u)
    # Simulate the _directory_qs prefetch attributes.
    u.public_staff_roles = list(
        StaffRole.objects.filter(holders=u).exclude(
            key__in=(StaffRole.LSP_STAFF, StaffRole.REGISTRAR)
        )
    )
    u.active_public_memberships = []
    assert _badge_staff_roles(u) == []


# ---- shared fixtures -----------------------------------------------------


def _event(slug="ev", status=Event.Status.OPEN, **kw):
    e = Event.objects.create(
        title=f"Event {slug}", slug=slug, event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=status, **kw,
    )
    PriceTier.objects.create(event=e, audience=Audience.ALL, base_amount=Decimal("50.00"))
    return e


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="M", last_name="Ember")
    u.profile.role = Profile.Role.MEMBER
    u.profile.save()
    return u


def _reg(event, user, status=Registration.Status.AWAITING_PAYMENT, amount="50.00"):
    return Registration.objects.create(
        user=user, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal(amount), status=status,
    )


# ---- comp service --------------------------------------------------------


def test_comp_registration_service_flips_notes_mints_and_notifies():
    from payments.models import Charge
    from registrations.services import comp_registration

    staff = User.objects.create_user(email="s@x.test", password="x", is_staff=True)
    reg = _reg(_event("comp-ev"), _member("c@x.test"))
    comped, email_ok = comp_registration(reg, staff, via="registration admin")

    reg.refresh_from_db()
    assert comped and email_ok
    assert reg.status == Registration.Status.COMPED
    assert "Comped by s@x.test via registration admin." in reg.staff_notes
    assert Charge.objects.filter(registration=reg).exists()


def test_comp_registration_service_refuses_non_awaiting():
    from registrations.services import comp_registration

    staff = User.objects.create_user(email="s2@x.test", password="x", is_staff=True)
    reg = _reg(_event("comp-ev2"), _member("c2@x.test"),
               status=Registration.Status.PAID)
    comped, _ = comp_registration(reg, staff)
    reg.refresh_from_db()
    assert not comped and reg.status == Registration.Status.PAID
