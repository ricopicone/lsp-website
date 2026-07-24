"""Tests for the faculty-facing event surfaces (PROG-7, PROG-8)."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from committees.models import Committee
from events.models import Audience, Event, PriceTier, PricingCode
from registrations.models import Registration


def _utc(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


# ---- Fixtures ----------------------------------------------------------


@pytest.fixture
def event(db):
    return Event.objects.create(
        title="Seminar XI", slug="seminar-xi",
        description="initial body",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def other_event(db):
    return Event.objects.create(
        title="Other", slug="other",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
        published=True, status=Event.Status.OPEN,
    )


@pytest.fixture
def faculty_member(db, event):
    u = User.objects.create_user(email="fac@example.com", first_name="Jane", last_name="Doe")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


@pytest.fixture
def other_faculty(db, other_event):
    u = User.objects.create_user(email="otherfac@example.com")
    u.profile.is_faculty = True
    u.profile.save()
    other_event.add_faculty(u)
    return u


@pytest.fixture
def pc_member(db):
    u = User.objects.create_user(email="pc@example.com")
    Committee.objects.get(slug="programming-committee").add_member(
        u, start_date=date(2026, 1, 1)
    )
    return u


@pytest.fixture
def staff_member(db):
    u = User.objects.create_user(email="staff@example.com")
    from core.models import StaffRole
    StaffRole.objects.get(key=StaffRole.LSP_STAFF).holders.add(u)
    return u


@pytest.fixture
def random_user(db):
    return User.objects.create_user(email="rando@example.com")


# ---- Permissions: event_edit (PROG-7) ----------------------------------


def test_edit_redirects_anonymous(client, event):
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_edit_forbidden_for_random_user(client, event, random_user):
    client.force_login(random_user)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 403


def test_edit_forbidden_for_faculty_of_other_event(
    client, event, other_event, other_faculty,
):
    client.force_login(other_faculty)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 403


def test_edit_allowed_for_this_events_faculty(client, event, faculty_member):
    client.force_login(faculty_member)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 200
    assert b"Edit Seminar XI" in response.content


def test_edit_allowed_for_programming_committee(client, event, pc_member):
    client.force_login(pc_member)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 200


def test_edit_allowed_for_lsp_staff(client, event, staff_member):
    client.force_login(staff_member)
    response = client.get(reverse("events:edit", args=[event.slug]))
    assert response.status_code == 200


def test_edit_post_updates_description(client, event, faculty_member):
    client.force_login(faculty_member)
    response = client.post(
        reverse("events:edit", args=[event.slug]),
        {"title": event.title, "description": "Updated body"},
    )
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.description == "Updated body"


# ---- Faculty toggle view (PROG-8) --------------------------------------


def test_public_event_shows_no_faculty_link_to_random_user(client, event, random_user):
    client.force_login(random_user)
    response = client.get(reverse("events:detail", args=[event.slug]))
    assert b"Faculty view" not in response.content
    assert b"Edit description" not in response.content


def test_workspace_offers_roster_tab_to_faculty(client, event, faculty_member):
    """Faculty see a Roster tab on the seminar Workspace (PROG-8 tooling moved
    here from the event page's ?view=faculty)."""
    client.force_login(faculty_member)
    response = client.get(event.workgroup.get_absolute_url())
    assert response.status_code == 200
    assert b"tab=roster" in response.content
    assert b"Edit description" in response.content   # edit affordance on the masthead


def test_roster_tab_renders_roster_for_faculty(
    client, event, faculty_member, random_user,
):
    tier = PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("100.00")
    )
    Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    client.force_login(faculty_member)
    response = client.get(event.workgroup.get_absolute_url() + "?tab=roster")
    assert response.status_code == 200
    assert b"Roster" in response.content
    assert b"rando@example.com" in response.content


def test_faculty_view_param_ignored_for_random_user(
    client, event, random_user,
):
    """Toggle param is ignored without permission — random user just sees public page."""
    tier = PriceTier.objects.create(
        event=event, audience=Audience.STUDENT, base_amount=Decimal("100.00")
    )
    Registration.objects.create(
        user=random_user, event=event, price_tier=tier,
        quoted_amount=Decimal("100.00"),
    )
    client.force_login(random_user)
    response = client.get(reverse("events:detail", args=[event.slug]) + "?view=faculty")
    assert response.status_code == 200
    # Roster section not rendered (no leak of registration data)
    assert b"Roster" not in response.content


# ---- Special-event presenters (task #463) ------------------------------
#
# A PC-organized event (special event, assembly, work day, scholarly) shares
# the Programming Committee's workgroup, so its presenters can't be stored as
# a FACULTY role there — they're listed as ``member_speakers`` instead. They
# still get the event's faculty surfaces, scoped to that one event.


@pytest.fixture
def special_event(db):
    return Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        description="initial body",
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
        published=True, status=Event.Status.OPEN,
        event_type=Event.Type.SPECIAL_EVENT,
    )


@pytest.fixture
def presenter(db, special_event):
    u = User.objects.create_user(
        email="presenter@example.com", first_name="Stephanie", last_name="Swales",
    )
    special_event.member_speakers.add(u)
    return u


def test_special_event_presenter_sees_faculty_view_link(client, special_event, presenter):
    client.force_login(presenter)
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert response.status_code == 200
    assert b"Faculty view" in response.content
    assert b"Edit description" in response.content


def test_special_event_presenter_sees_roster(
    client, special_event, presenter, random_user,
):
    tier = PriceTier.objects.create(
        event=special_event, audience=Audience.STUDENT, base_amount=Decimal("50.00")
    )
    Registration.objects.create(
        user=random_user, event=special_event, price_tier=tier,
        quoted_amount=Decimal("50.00"),
    )
    client.force_login(presenter)
    response = client.get(
        reverse("events:detail", args=[special_event.slug]) + "?view=faculty"
    )
    assert response.status_code == 200
    assert b"Roster" in response.content
    assert b"rando@example.com" in response.content


def test_special_event_presenter_may_edit(client, special_event, presenter):
    client.force_login(presenter)
    response = client.get(reverse("events:edit", args=[special_event.slug]))
    assert response.status_code == 200


def test_special_event_presenter_may_mint_pricing_code(client, special_event, presenter):
    client.force_login(presenter)
    response = client.post(
        reverse("events:generate_code", args=[special_event.slug]),
        {"pricing_mode": "percent_off", "amount_or_percent": "25"},
    )
    assert response.status_code == 302
    assert PricingCode.objects.get(event=special_event).issued_by == presenter


def test_special_event_presenter_has_no_rights_on_another_special_event(
    client, special_event, presenter,
):
    """Presenting one PC event must not confer rights on every PC event —
    they all share the Programming Committee's workgroup."""
    other = Event.objects.create(
        title="Days of Assembly", slug="days-of-assembly",
        start_date=date(2026, 10, 3), end_date=date(2026, 10, 3),
        published=True, status=Event.Status.OPEN,
        event_type=Event.Type.SPECIAL_EVENT,
    )
    client.force_login(presenter)
    assert client.get(reverse("events:edit", args=[other.slug])).status_code == 403


def test_member_speaker_on_an_offering_is_a_guest_not_faculty(
    client, event, random_user,
):
    """Offerings have their own workgroup where real faculty live, so a member
    speaker there is a guest — no edit rights."""
    event.member_speakers.add(random_user)
    client.force_login(random_user)
    assert client.get(reverse("events:edit", args=[event.slug])).status_code == 403


# ---- Access details for whoever runs the event -------------------------
#
# Faculty and presenters never register (or pay) for their own event, so the
# venue / meeting link isn't behind the registration gate for them.

ZOOM = "https://zoom.example.com/j/123"


def test_access_details_shown_to_special_event_presenter(
    client, special_event, presenter,
):
    special_event.access_info = ZOOM
    special_event.save(update_fields=["access_info"])
    client.force_login(presenter)
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert ZOOM.encode() in response.content


def test_access_details_shown_to_offering_faculty(client, event, faculty_member):
    event.access_info = ZOOM
    event.save(update_fields=["access_info"])
    client.force_login(faculty_member)
    # The seminar page is the Workspace; both render the shared summary.
    response = client.get(reverse("events:detail", args=[event.slug]), follow=True)
    assert ZOOM.encode() in response.content


def test_access_details_hidden_from_unregistered_user(
    client, special_event, random_user,
):
    special_event.access_info = ZOOM
    special_event.save(update_fields=["access_info"])
    client.force_login(random_user)
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert ZOOM.encode() not in response.content


def test_access_details_shown_to_paid_registrant(client, special_event, random_user):
    special_event.access_info = ZOOM
    special_event.save(update_fields=["access_info"])
    tier = PriceTier.objects.create(
        event=special_event, audience=Audience.STUDENT, base_amount=Decimal("50.00")
    )
    Registration.objects.create(
        user=random_user, event=special_event, price_tier=tier,
        quoted_amount=Decimal("50.00"), status=Registration.Status.PAID,
    )
    client.force_login(random_user)
    response = client.get(reverse("events:detail", args=[special_event.slug]))
    assert ZOOM.encode() in response.content


# ---- Pricing-code generation (PROG-8 / REG-17) -------------------------


def test_generate_code_redirects_anonymous(client, event):
    response = client.post(reverse("events:generate_code", args=[event.slug]))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_generate_code_forbidden_for_random_user(client, event, random_user):
    client.force_login(random_user)
    response = client.post(
        reverse("events:generate_code", args=[event.slug]),
        {"pricing_mode": "percent_off", "amount_or_percent": "10"},
    )
    assert response.status_code == 403
    assert PricingCode.objects.filter(event=event).count() == 0


def test_generate_code_creates_for_faculty(client, event, faculty_member):
    client.force_login(faculty_member)
    response = client.post(
        reverse("events:generate_code", args=[event.slug]),
        {"pricing_mode": "percent_off", "amount_or_percent": "25"},
    )
    assert response.status_code == 302
    code = PricingCode.objects.get(event=event)
    assert code.issued_by == faculty_member
    assert code.amount_or_percent == Decimal("25")


def test_generate_code_with_user_restriction(client, event, faculty_member, random_user):
    client.force_login(faculty_member)
    client.post(
        reverse("events:generate_code", args=[event.slug]),
        {
            "pricing_mode": "fixed_amount",
            "amount_or_percent": "0",
            "restricted_to_user": random_user.id,
            "max_uses": 1,
        },
    )
    code = PricingCode.objects.get(event=event)
    assert code.restricted_to_user == random_user
    assert code.max_uses == 1
    assert code.uses_remaining == 1


def test_generate_code_rejects_invalid_percent(client, event, faculty_member):
    client.force_login(faculty_member)
    client.post(
        reverse("events:generate_code", args=[event.slug]),
        {"pricing_mode": "percent_off", "amount_or_percent": "150"},
    )
    assert PricingCode.objects.filter(event=event).count() == 0


def test_get_to_generate_code_redirects_to_faculty_view(client, event, faculty_member):
    client.force_login(faculty_member)
    response = client.get(reverse("events:generate_code", args=[event.slug]))
    assert response.status_code == 302
    # Offering events host faculty tools on the Workspace Roster tab now.
    assert response.url == event.workgroup.get_absolute_url() + "?tab=roster"


# ---- /events/<slug>/check-code/ ----------------------------------------


@pytest.fixture
def some_codes(event, faculty_member, random_user):
    sf = PricingCode.objects.create(
        event=event, issued_by=faculty_member,
        pricing_mode=PricingCode.Mode.SLIDING_FLOOR,
        amount_or_percent=Decimal("20"),
    )
    fa = PricingCode.objects.create(
        event=event, issued_by=faculty_member,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("40.00"),
    )
    po = PricingCode.objects.create(
        event=event, issued_by=faculty_member,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("25"),
    )
    return {"sliding_floor": sf, "fixed_amount": fa, "percent_off": po}


def test_check_code_anonymous_requires_login(client, event):
    response = client.get(reverse("events:check_code", args=[event.slug]), {"code": "X"})
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_check_code_empty_returns_error(client, event, random_user):
    client.force_login(random_user)
    response = client.get(reverse("events:check_code", args=[event.slug]))
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "Empty code."}


def test_check_code_unknown_returns_error(client, event, random_user):
    client.force_login(random_user)
    response = client.get(reverse("events:check_code", args=[event.slug]), {"code": "ZZZZ"})
    assert response.json() == {"ok": False, "error": "Code not recognized for this event."}


def test_check_code_sliding_floor_returns_mode_and_value(
    client, event, some_codes, random_user,
):
    client.force_login(random_user)
    response = client.get(
        reverse("events:check_code", args=[event.slug]),
        {"code": some_codes["sliding_floor"].code},
    )
    data = response.json()
    assert data["ok"] is True
    assert data["mode"] == "sliding_floor"
    assert data["value"] == "20.00"


def test_check_code_fixed_amount_returns_mode_and_value(
    client, event, some_codes, random_user,
):
    client.force_login(random_user)
    response = client.get(
        reverse("events:check_code", args=[event.slug]),
        {"code": some_codes["fixed_amount"].code},
    )
    assert response.json() == {"ok": True, "mode": "fixed_amount", "value": "40.00"}


def test_check_code_percent_off_returns_mode_and_value(
    client, event, some_codes, random_user,
):
    client.force_login(random_user)
    response = client.get(
        reverse("events:check_code", args=[event.slug]),
        {"code": some_codes["percent_off"].code},
    )
    assert response.json() == {"ok": True, "mode": "percent_off", "value": "25.00"}


def test_check_code_lowercase_normalized(client, event, some_codes, random_user):
    client.force_login(random_user)
    response = client.get(
        reverse("events:check_code", args=[event.slug]),
        {"code": some_codes["fixed_amount"].code.lower()},
    )
    assert response.json()["ok"] is True


def test_check_code_restricted_to_other_user_not_redeemable(
    client, event, faculty_member, random_user,
):
    sally = User.objects.create_user(email="sally@example.com")
    code = PricingCode.objects.create(
        event=event, issued_by=faculty_member,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
        restricted_to_user=sally,
    )
    client.force_login(random_user)
    response = client.get(
        reverse("events:check_code", args=[event.slug]),
        {"code": code.code},
    )
    assert response.json()["ok"] is False
    assert "not redeemable" in response.json()["error"].lower()


def test_check_code_wrong_event_not_recognized(
    client, event, other_event, faculty_member, random_user,
):
    code = PricingCode.objects.create(
        event=other_event, issued_by=faculty_member,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
    )
    client.force_login(random_user)
    response = client.get(
        reverse("events:check_code", args=[event.slug]),
        {"code": code.code},
    )
    assert response.json()["ok"] is False
    assert "not recognized" in response.json()["error"].lower()
