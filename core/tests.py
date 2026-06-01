"""Tests for the unified calendar (PROG-6)."""

from __future__ import annotations

from datetime import date, datetime
from datetime import timezone as dt_timezone

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Event, Session


def _utc(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="staff@example.com",
        password="not-a-real-password",
    )
    user.is_staff = True
    user.save()
    return user


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        email="member@example.com",
        password="not-a-real-password",
    )


@pytest.fixture
def event_with_sessions(db):
    e = Event.objects.create(
        title="Lacan Seminar XI",
        slug="lacan-seminar-xi",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        published=True,
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 3), end_at=_utc(2026, 9, 3, 12), sequence=1
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 10), end_at=_utc(2026, 9, 10, 12), sequence=2
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 17), end_at=_utc(2026, 9, 17, 12), sequence=3
    )
    return e


@pytest.fixture
def draft_event_with_sessions(db):
    e = Event.objects.create(
        title="Draft Event",
        slug="draft-event",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
        published=False,
    )
    Session.objects.create(
        event=e, start_at=_utc(2026, 9, 5), end_at=_utc(2026, 9, 5, 12), sequence=1
    )
    return e


@pytest.mark.django_db
def test_calendar_page_public_no_auth(client):
    """Calendar is publicly viewable post-M5; no login required."""
    response = client.get(reverse("core:calendar"))
    assert response.status_code == 200
    assert b"FullCalendar" in response.content


def test_calendar_events_json_anonymous_sees_only_published(
    client, event_with_sessions, draft_event_with_sessions,
):
    response = client.get(reverse("core:calendar_events"))
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()}
    assert "Lacan Seminar XI" in titles
    assert "Draft Event" not in titles


def test_calendar_events_json_staff_sees_drafts(
    client, staff_user, event_with_sessions, draft_event_with_sessions,
):
    client.force_login(staff_user)
    response = client.get(reverse("core:calendar_events"))
    titles = {item["title"] for item in response.json()}
    assert "Lacan Seminar XI" in titles
    assert "Draft Event" in titles


def test_calendar_events_json_url_public_for_staff(client, staff_user, event_with_sessions):
    """Calendar event links go to the public event page for everyone —
    including staff. Staff can edit from the event page directly."""
    client.force_login(staff_user)
    response = client.get(reverse("core:calendar_events"))
    first = response.json()[0]
    assert first["url"] == reverse("events:detail", args=["lacan-seminar-xi"])


def test_calendar_events_json_url_public_for_anonymous(client, event_with_sessions):
    response = client.get(reverse("core:calendar_events"))
    first = response.json()[0]
    assert first["url"] == reverse("events:detail", args=["lacan-seminar-xi"])


def test_events_json_filters_by_range(client, event_with_sessions):
    response = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-05T00:00:00Z", "end": "2026-09-15T00:00:00Z"},
    )
    data = response.json()
    assert len(data) == 1
    assert data[0]["start"].startswith("2026-09-10")


def test_events_json_accepts_bare_dates(client, event_with_sessions):
    response = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-05", "end": "2026-09-15"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


# ---- Landing page ------------------------------------------------------


@pytest.mark.django_db
def test_landing_page_renders(client):
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    assert b"Lacanian School" in response.content
    assert b"lacanschool.org" in response.content  # link to apex


def test_landing_page_lists_upcoming_events(client, event_with_sessions):
    response = client.get(reverse("core:landing"))
    assert b"Lacan Seminar XI" in response.content


def test_landing_page_skips_draft_events(client, draft_event_with_sessions):
    response = client.get(reverse("core:landing"))
    assert b"Draft Event" not in response.content


def test_landing_page_logged_in_shows_recent_registration_link(
    client, regular_user, event_with_sessions,
):
    from decimal import Decimal

    from events.models import Audience, PriceTier
    from registrations.models import Registration
    tier = PriceTier.objects.create(
        event=event_with_sessions, audience=Audience.ALL,
        base_amount=Decimal("100.00"),
    )
    Registration.objects.create(
        user=regular_user, event=event_with_sessions, price_tier=tier,
        quoted_amount=Decimal("100.00"),
        status=Registration.Status.AWAITING_PAYMENT,
    )
    client.force_login(regular_user)
    response = client.get(reverse("core:landing"))
    assert b"View your most recent registration" in response.content


# ---- Public events list -----------------------------------------------


@pytest.mark.django_db
def test_events_list_public(client):
    response = client.get(reverse("events:list"))
    assert response.status_code == 200


def test_events_list_shows_published_upcoming(
    client, event_with_sessions, draft_event_with_sessions,
):
    response = client.get(reverse("events:list"))
    assert b"Lacan Seminar XI" in response.content
    assert b"Draft Event" not in response.content


@pytest.mark.django_db
def test_events_list_excludes_past_events(client):
    """Events that ended before today shouldn't appear in the list."""
    Event.objects.create(
        title="Old Event", slug="old",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2020, 1, 1), end_date=date(2020, 12, 31),
        published=True,
    )
    response = client.get(reverse("events:list"))
    assert b"Old Event" not in response.content


@pytest.mark.django_db
def test_events_list_excludes_annual_program_types(client):
    """Seminars, reading groups, cartels live on /program/, not /events/."""
    future = date(2030, 9, 1)
    for slug, etype in [
        ("a-seminar", Event.Type.SEMINAR),
        ("a-rg", Event.Type.READING_GROUP),
        ("a-cartel", Event.Type.CARTEL),
        ("a-special", Event.Type.SPECIAL_EVENT),
    ]:
        Event.objects.create(
            title=f"Event {slug}", slug=slug, event_type=etype,
            start_date=future, end_date=future, published=True,
        )
    response = client.get(reverse("events:list"))
    assert b"Event a-special" in response.content
    assert b"Event a-seminar" not in response.content
    assert b"Event a-rg" not in response.content
    assert b"Event a-cartel" not in response.content


@pytest.mark.django_db
def test_events_list_hides_members_only_from_anonymous(client, django_user_model):
    """visibility=members_only events are hidden from anonymous visitors."""
    future = date(2030, 9, 1)
    Event.objects.create(
        title="Members Only Talk", slug="members-only-talk",
        event_type=Event.Type.SCHOLARLY_SEMINAR,
        visibility=Event.Visibility.MEMBERS_ONLY,
        start_date=future, end_date=future, published=True,
    )
    Event.objects.create(
        title="Public Talk", slug="public-talk",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=future, end_date=future, published=True,
    )

    # Anonymous: members-only hidden.
    response = client.get(reverse("events:list"))
    assert b"Public Talk" in response.content
    assert b"Members Only Talk" not in response.content

    # An authenticated auditor (outside registrant, default role=external) is
    # not a member — members-only events stay hidden.
    auditor = django_user_model.objects.create_user(email="ext@example.com", password="x")
    client.force_login(auditor)
    response = client.get(reverse("events:list"))
    assert b"Members Only Talk" not in response.content

    # A member sees it.
    member = django_user_model.objects.create_user(email="m@example.com", password="x")
    member.profile.role = Profile.Role.ANALYST
    member.profile.save(update_fields=["role"])
    client.force_login(member)
    response = client.get(reverse("events:list"))
    assert b"Members Only Talk" in response.content


@pytest.mark.django_db
def test_event_detail_back_link_seminar_goes_to_program(client):
    """A seminar's back link points to /program/ for its academic year."""
    e = Event.objects.create(
        title="A Seminar", slug="a-seminar-test",
        event_type=Event.Type.SEMINAR,
        start_date=date(2027, 9, 1), end_date=date(2028, 5, 1),
        published=True,
    )
    response = client.get(reverse("events:detail", args=[e.slug]))
    assert response.status_code == 200
    assert b"\xe2\x86\x90 Program" in response.content
    assert b"/program/?year=2027-2028" in response.content


@pytest.mark.django_db
def test_event_detail_back_link_special_goes_to_events(client):
    """A special event's back link points to /events/."""
    e = Event.objects.create(
        title="A Workshop", slug="a-workshop-test",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2027, 10, 1), end_date=date(2027, 10, 1),
        published=True,
    )
    response = client.get(reverse("events:detail", args=[e.slug]))
    assert response.status_code == 200
    assert b"\xe2\x86\x90 Events" in response.content


# ---- Footer aphorism (DB-backed, staff-editable) ----------------------


@pytest.mark.django_db
def test_aphorism_context_processor_excludes_inactive():
    from django.core.cache import cache

    from core.context_processors import _active_aphorisms
    from core.models import Aphorism

    Aphorism.objects.all().delete()  # post_delete clears the cache
    Aphorism.objects.create(quote="Active one", short_attribution="X", is_active=True)
    Aphorism.objects.create(quote="Hidden one", short_attribution="Y", is_active=False)

    quotes = {i["quote"] for i in _active_aphorisms()}
    assert "Active one" in quotes
    assert "Hidden one" not in quotes
    cache.clear()


@pytest.mark.django_db
def test_aphorism_edit_invalidates_cache():
    from core.context_processors import _active_aphorisms
    from core.models import Aphorism

    Aphorism.objects.all().delete()
    a = Aphorism.objects.create(quote="First", is_active=True)
    assert {i["quote"] for i in _active_aphorisms()} == {"First"}

    a.quote = "Edited"
    a.save()  # post_save must drop the cached list
    assert {i["quote"] for i in _active_aphorisms()} == {"Edited"}


@pytest.mark.django_db
def test_landing_footer_renders_aphorism(client):
    from core.models import Aphorism

    Aphorism.objects.all().delete()
    Aphorism.objects.create(
        quote="The unconscious is structured like a language.",
        short_attribution="Seminar XI",
        is_active=True,
    )
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    assert b"structured like a language" in response.content


# ---- Web Coordinator panel (StaffRole-gated) --------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        email="root@example.com", password="not-a-real-password",
    )


@pytest.fixture
def web_coordinator(db):
    from core.models import StaffRole

    user = User.objects.create_user(
        email="webcoord@example.com", password="not-a-real-password",
    )
    role, _ = StaffRole.objects.get_or_create(
        key=StaffRole.WEB_COORDINATOR, defaults={"name": "Web Coordinator"},
    )
    role.holders.add(user)
    return user


def test_coordinator_requires_login(client):
    assert client.get(reverse("staff")).status_code == 302


def test_coordinator_forbidden_for_plain_member(client, regular_user):
    client.force_login(regular_user)
    assert client.get(reverse("staff")).status_code == 403


def test_coordinator_ok_for_holder(client, web_coordinator):
    client.force_login(web_coordinator)
    response = client.get(reverse("staff"))
    assert response.status_code == 200
    assert b"Aphorisms" in response.content


def test_coordinator_ok_for_superuser(client, superuser):
    client.force_login(superuser)
    assert client.get(reverse("staff")).status_code == 200


def test_aphorism_create_via_panel(client, web_coordinator):
    from core.models import Aphorism

    client.force_login(web_coordinator)
    before = Aphorism.objects.count()
    response = client.post(
        reverse("staff_aphorism_new"),
        {"quote": "A freshly typed aphorism.", "short_attribution": "Test",
         "full_attribution": "", "is_active": "on"},
    )
    assert response.status_code == 302
    assert Aphorism.objects.count() == before + 1
    assert Aphorism.objects.filter(quote="A freshly typed aphorism.").exists()


def test_aphorism_toggle_and_delete_via_panel(client, web_coordinator):
    from core.models import Aphorism

    client.force_login(web_coordinator)
    a = Aphorism.objects.create(quote="Toggle me", is_active=True)
    client.post(reverse("staff_aphorism_toggle", args=[a.pk]))
    a.refresh_from_db()
    assert a.is_active is False
    client.post(reverse("staff_aphorism_delete", args=[a.pk]))
    assert not Aphorism.objects.filter(pk=a.pk).exists()


def test_aphorism_edit_forbidden_for_member(client, regular_user):
    from core.models import Aphorism

    a = Aphorism.objects.create(quote="Members may not edit me.")
    client.force_login(regular_user)
    assert client.get(
        reverse("staff_aphorism_edit", args=[a.pk])
    ).status_code == 403


def test_nav_staff_tools_link_visibility(client, web_coordinator, regular_user):
    client.force_login(web_coordinator)
    assert b"Staff tools" in client.get(reverse("core:landing")).content
    client.force_login(regular_user)
    assert b"Staff tools" not in client.get(reverse("core:landing")).content


@pytest.fixture
def treasurer_member(db):
    from core.models import StaffRole

    user = User.objects.create_user(
        email="treasurer@example.com", password="not-a-real-password",
    )
    StaffRole.objects.get(key=StaffRole.TREASURER).holders.add(user)
    return user


def test_treasurer_role_reaches_hub_and_dashboard(client, treasurer_member):
    """A Treasurer-role holder (not Django staff) sees the hub + Treasurer tool
    and can open the dashboard."""
    client.force_login(treasurer_member)
    hub = client.get(reverse("staff"))
    assert hub.status_code == 200
    assert b"Treasurer" in hub.content
    assert b"Aphorisms" not in hub.content  # not a web coordinator
    assert client.get(reverse("treasurer")).status_code == 200


def test_cartel_coordinator_sees_review_card(client, web_coordinator):
    """Granting the cartel-coordinator role surfaces the Cartel review card."""
    from core.models import StaffRole

    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(web_coordinator)
    client.force_login(web_coordinator)
    body = client.get(reverse("staff")).content
    assert b"Cartel review" in body


@pytest.fixture
def pc_member(db):
    from committees.models import Committee

    user = User.objects.create_user(email="pc@example.com", password="not-a-real-password")
    Committee.objects.get(slug="programming-committee").add_member(
        user, start_date=date(2026, 1, 1)
    )
    return user


def test_committee_member_sees_committee_panel(client, pc_member):
    """A Programming Committee member (not Django staff, no StaffRole) reaches
    the hub, sees the Program Committee card, and can open the PC admin."""
    client.force_login(pc_member)
    hub = client.get(reverse("staff"))
    assert hub.status_code == 200
    assert b"Program Committee" in hub.content
    assert b"Aphorisms" not in hub.content  # not a web coordinator
    assert client.get(reverse("program_admin_programs")).status_code == 200


def test_board_member_sees_board_card(db, client):
    """A Board member (no role, not Django staff) sees the Board card, which
    links to the committee's workgroup page."""
    from committees.models import Committee

    user = User.objects.create_user(email="board@example.com", password="x")
    board = Committee.objects.get(slug="board")
    board.add_member(user, start_date=date(2026, 1, 1))
    client.force_login(user)
    body = client.get(reverse("staff")).content
    assert b"Board" in body
    assert reverse("workgroups:detail", args=[board.workgroup.slug]).encode() in body


def test_meeting_of_analysts_committee_seeded(db):
    """The Meeting of Analysts committee exists with a backing workgroup."""
    from committees.models import Committee

    c = Committee.objects.get(slug="meeting-of-analysts")
    assert c.workgroup_id is not None
