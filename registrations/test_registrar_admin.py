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
