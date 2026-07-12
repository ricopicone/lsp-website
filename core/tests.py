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


# ---- Payment deadlines on the calendar (#355) --------------------------


@pytest.fixture
def payment_periods(db):
    from payments.models import DuesPeriod, TuitionPeriod

    DuesPeriod.objects.create(
        name="AY 2026-2027 dues", start_date=date(2026, 9, 1),
        due_date=date(2026, 9, 30), end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=50, dues_amount_candidate=100,
        dues_amount_analyst=150,
    )
    TuitionPeriod.objects.create(
        name="AY 2026-2027 tuition", start_date=date(2026, 9, 1),
        decision_due_date=date(2026, 9, 15), end_date=date(2027, 8, 31),
        tuition_amount=2500,
    )


def test_calendar_shows_payment_deadlines_to_members(client, regular_user, payment_periods):
    client.force_login(regular_user)
    resp = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-01", "end": "2026-10-01"},
    )
    events = {e["title"]: e for e in resp.json()}
    assert "Membership dues due" in events
    assert "Tuition decision due" in events
    dues = events["Membership dues due"]
    assert dues["allDay"] is True
    assert dues["start"].startswith("2026-09-30")
    assert dues["url"] == reverse("payments:index")


def test_calendar_hides_payment_deadlines_from_anonymous(client, payment_periods):
    resp = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-09-01", "end": "2026-10-01"},
    )
    titles = [e["title"] for e in resp.json()]
    assert "Membership dues due" not in titles
    assert "Tuition decision due" not in titles


def test_calendar_payment_deadlines_respect_window(client, regular_user, payment_periods):
    client.force_login(regular_user)
    resp = client.get(
        reverse("core:calendar_events"),
        {"start": "2026-11-01", "end": "2026-11-30"},
    )
    titles = [e["title"] for e in resp.json()]
    assert "Membership dues due" not in titles  # Sept deadline, outside Nov window


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
    assert client.get(reverse("admin_tools")).status_code == 302


def test_coordinator_forbidden_for_plain_member(client, regular_user):
    client.force_login(regular_user)
    assert client.get(reverse("admin_tools")).status_code == 403


def test_coordinator_ok_for_holder(client, web_coordinator):
    client.force_login(web_coordinator)
    response = client.get(reverse("admin_tools"))
    assert response.status_code == 200
    assert b"Web Coordinator Admin" in response.content


def test_coordinator_ok_for_superuser(client, superuser):
    client.force_login(superuser)
    assert client.get(reverse("admin_tools")).status_code == 200


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
    assert b"Admin Tools" in client.get(reverse("core:landing")).content
    client.force_login(regular_user)
    assert b"Admin Tools" not in client.get(reverse("core:landing")).content


def test_account_menu_shows_donation_link(client, regular_user):
    client.force_login(regular_user)
    response = client.get(reverse("core:landing"))
    assert response.status_code == 200
    assert b"Donate to LSP" in response.content
    assert b'href="/donate/"' in response.content


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
    hub = client.get(reverse("admin_tools"))
    assert hub.status_code == 200
    assert b"Treasurer" in hub.content
    assert b"Aphorisms" not in hub.content  # not a web coordinator
    assert client.get(reverse("treasurer")).status_code == 200


def test_cartel_coordinator_sees_review_card(client, web_coordinator):
    """Granting the cartel-coordinator role surfaces the Cartel Coordinator Admin card."""
    from core.models import StaffRole

    StaffRole.objects.get(key=StaffRole.CARTEL_COORDINATOR).holders.add(web_coordinator)
    client.force_login(web_coordinator)
    body = client.get(reverse("admin_tools")).content
    assert b"Cartel Coordinator Admin" in body


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
    hub = client.get(reverse("admin_tools"))
    assert hub.status_code == 200
    assert b"Program Committee" in hub.content
    assert b"Aphorisms" not in hub.content  # not a web coordinator
    assert client.get(reverse("program_admin_programs")).status_code == 200


def test_board_member_sees_board_card(db, client):
    """A Board member (no role, not Django staff) reaches the hub, sees the
    Board Admin card, and can open the Board Admin page."""
    from committees.models import Committee

    user = User.objects.create_user(email="board@example.com", password="x")
    board = Committee.objects.get(slug="board")
    board.add_member(user, start_date=date(2026, 1, 1))
    client.force_login(user)
    body = client.get(reverse("admin_tools")).content
    assert b"Board Admin" in body
    assert reverse("board_admin").encode() in body
    assert client.get(reverse("board_admin")).status_code == 200


def test_meeting_of_analysts_committee_seeded(db):
    """The Meeting of Analysts committee exists with a backing workgroup."""
    from committees.models import Committee

    c = Committee.objects.get(slug="meeting-of-analysts")
    assert c.workgroup_id is not None


# --- Impersonation ("View as") -----------------------------------------------

@pytest.mark.django_db
def test_superuser_impersonates_persona_and_exits(client):
    from core.models import ImpersonationLog

    su = User.objects.create_superuser(email="su@x.test", password="x")
    persona = User.objects.create_user(email="persona@x.test",
                                       first_name="Test", last_name="Persona")
    persona.profile.is_persona = True
    persona.profile.role = Profile.Role.ANALYST
    persona.profile.save()

    client.force_login(su)
    resp = client.post(reverse("core:impersonate_start", args=[persona.id]))
    assert resp.status_code == 302
    home = client.get("/")
    assert b"Viewing as" in home.content and b"Test Persona" in home.content
    assert ImpersonationLog.objects.filter(impersonator=su, target=persona).exists()

    client.post(reverse("core:impersonate_stop"))
    assert b"Viewing as" not in client.get("/").content


@pytest.mark.django_db
def test_exit_impersonation_returns_to_current_page(client):
    su = User.objects.create_superuser(email="su@x.test", password="x")
    persona = User.objects.create_user(email="persona@x.test",
                                       first_name="Test", last_name="Persona")
    persona.profile.is_persona = True
    persona.profile.role = Profile.Role.ANALYST
    persona.profile.save()

    client.force_login(su)
    client.post(reverse("core:impersonate_start", args=[persona.id]))

    # Exiting with a next= carries the user back to the page they were on.
    resp = client.post(reverse("core:impersonate_stop"), {"next": "/directory/"})
    assert resp.status_code == 302
    assert resp.url == "/directory/"


@pytest.mark.django_db
def test_exit_impersonation_ignores_unsafe_next(client):
    su = User.objects.create_superuser(email="su@x.test", password="x")
    persona = User.objects.create_user(email="persona@x.test", first_name="P")
    persona.profile.is_persona = True
    persona.profile.save()

    client.force_login(su)
    client.post(reverse("core:impersonate_start", args=[persona.id]))

    resp = client.post(reverse("core:impersonate_stop"),
                       {"next": "https://evil.example/"})
    assert resp.status_code == 302
    assert resp.url == "/"


@pytest.mark.django_db
def test_non_superuser_cannot_impersonate(client):
    u = User.objects.create_user(email="u@x.test", password="x")
    other = User.objects.create_user(email="o@x.test")
    client.force_login(u)
    assert client.get(reverse("core:impersonate_picker")).status_code == 404
    assert client.post(reverse("core:impersonate_start", args=[other.id])).status_code == 404


@pytest.mark.django_db
def test_cannot_impersonate_a_superuser(client):
    su = User.objects.create_superuser(email="su@x.test", password="x")
    su2 = User.objects.create_superuser(email="su2@x.test", password="x")
    client.force_login(su)
    client.post(reverse("core:impersonate_start", args=[su2.id]))
    assert b"Viewing as" not in client.get("/").content   # refused


@pytest.mark.django_db
def test_real_member_impersonation_is_read_only_persona_is_writable(client):
    from workgroups.models import Visibility, Workgroup, build_workgroup

    su = User.objects.create_superuser(email="su@x.test", password="x")
    wg = build_workgroup(
        Workgroup.Kind.READING_GROUP, name="RG", slug="rg-imp",
        landing_visibility=Visibility.PUBLIC,
    )

    def _analyst(email, persona):
        u = User.objects.create_user(email=email)
        u.profile.role = Profile.Role.ANALYST
        u.profile.is_persona = persona
        u.profile.save()
        return u

    real = _analyst("real@x.test", persona=False)
    persona = _analyst("persona@x.test", persona=True)

    client.force_login(su)

    # Real member → read-only: the join write is blocked.
    client.post(reverse("core:impersonate_start", args=[real.id]))
    r = client.post(reverse("workgroups:join", args=[wg.slug]))
    assert r.status_code == 302
    assert not wg.memberships.filter(user=real).exists()
    client.post(reverse("core:impersonate_stop"))

    # Persona → writable: the join goes through.
    client.post(reverse("core:impersonate_start", args=[persona.id]))
    client.post(reverse("workgroups:join", args=[wg.slug]))
    assert wg.memberships.filter(user=persona, end_date__isnull=True).exists()


# ---- Staff hub Documentation section ----------------------------------

@pytest.mark.django_db
def test_staff_docs_section_and_groups_guide(client):
    from accounts.models import User

    admin = User.objects.create_user(
        email="admin-docs@x.test", password="x", is_staff=True, is_superuser=True
    )
    client.force_login(admin)
    home = client.get("/admin-tools/")
    assert home.status_code == 200
    assert b"Documentation" in home.content
    assert b"/admin-tools/docs/groups-guide/" in home.content

    guide = client.get("/admin-tools/docs/groups-guide/")
    assert guide.status_code == 200
    assert b"Groups at the LSP" in guide.content        # the doc's H1, rendered

    assert client.get("/admin-tools/docs/does-not-exist/").status_code == 404


@pytest.mark.django_db
def test_staff_doc_denied_without_hub_access(client):
    from accounts.models import User

    nobody = User.objects.create_user(email="nobody-docs@x.test", password="x")
    client.force_login(nobody)
    assert client.get("/admin-tools/docs/groups-guide/").status_code == 403


# --- Persona exemptions: treasurer/financial + email -------------------------

@pytest.mark.django_db
def test_personas_are_not_financially_obligated():
    from payments.dues import is_dues_obligated

    persona = User.objects.create_user(email="persona+analyst@x.test")
    persona.profile.role = Profile.Role.ANALYST       # dues-obligated role
    persona.profile.is_persona = True
    persona.profile.save()
    assert is_dues_obligated(persona) is False

    cand = User.objects.create_user(email="persona+cand@x.test")
    cand.profile.role = Profile.Role.CANDIDATE        # tuition (in-training) role
    cand.profile.is_persona = True
    cand.profile.save()
    assert cand.profile.owes_tuition is False


@pytest.mark.django_db
def test_persona_safe_email_backend_drops_persona_recipients(settings):
    from django.core import mail
    from django.core.mail import EmailMessage

    from core.email import PersonaSafeEmailBackend

    settings.PERSONA_SAFE_INNER_EMAIL_BACKEND = (
        "django.core.mail.backends.locmem.EmailBackend"
    )
    persona = User.objects.create_user(email="persona+x@lacanschool.org")
    persona.profile.is_persona = True
    persona.profile.save()

    mail.outbox = []
    backend = PersonaSafeEmailBackend()
    backend.send_messages([
        EmailMessage("s", "b", "from@x.test", ["persona+x@lacanschool.org"]),
        EmailMessage("s", "b", "from@x.test", ["real@x.test"]),
    ])
    delivered = [addr for m in mail.outbox for addr in m.to]
    assert "real@x.test" in delivered
    assert "persona+x@lacanschool.org" not in delivered


def _grant_role(user, key):
    from core.models import StaffRole
    StaffRole.objects.get(key=key).holders.add(user)


def test_admin_assistant_role_page_and_card(db, client):
    from core.models import StaffRole
    user = User.objects.create_user(email="aa@example.com", password="x")
    _grant_role(user, StaffRole.ADMIN_ASSISTANT)
    client.force_login(user)
    body = client.get(reverse("admin_tools")).content
    assert b"Administrative Assistant Admin" in body
    assert b"Web Coordinator Admin" not in body  # only their own card
    assert client.get(reverse("admin_assistant_admin")).status_code == 200


def test_web_developer_role_page_and_card(db, client):
    from core.models import StaffRole
    user = User.objects.create_user(email="wd@example.com", password="x")
    _grant_role(user, StaffRole.WEB_DEVELOPER)
    client.force_login(user)
    body = client.get(reverse("admin_tools")).content
    assert b"Web Developer Admin" in body
    assert client.get(reverse("web_developer_admin")).status_code == 200


def test_web_coordinator_landing_shows_aphorisms(client, web_coordinator):
    client.force_login(web_coordinator)
    resp = client.get(reverse("web_coordinator_admin"))
    assert resp.status_code == 200
    assert b"Aphorisms" in resp.content


def test_role_pages_forbidden_without_role(client, regular_user):
    client.force_login(regular_user)
    for name in ("admin_assistant_admin", "web_developer_admin",
                 "web_coordinator_admin", "board_admin"):
        assert client.get(reverse(name)).status_code == 403


def test_other_committee_member_no_longer_reaches_hub(db, client):
    """Narrowed access: a member of a committee other than Board / Programming
    Committee / Meeting of the Analysts no longer gets the Admin Tools hub."""
    from committees.models import Committee
    user = User.objects.create_user(email="outreach@example.com", password="x")
    Committee.objects.create(name="Outreach", slug="outreach").add_member(
        user, start_date=date(2026, 1, 1)
    )
    client.force_login(user)
    assert client.get(reverse("admin_tools")).status_code == 403


def test_meeting_of_analysts_member_reaches_hub(db, client):
    """The Meeting of the Analysts now has its own admin surface, so its members
    reach the hub (and see only their own panel)."""
    from accounts.models import Profile
    user = User.objects.create_user(email="analyst-hub@example.com", password="x")
    user.profile.role = Profile.Role.ANALYST  # auto-member of the Meeting
    user.profile.save()
    client.force_login(user)
    resp = client.get(reverse("admin_tools"))
    assert resp.status_code == 200
    assert b"Meeting of Analysts Admin" in resp.content


def test_staff_url_redirects_to_admin_tools(client, superuser):
    client.force_login(superuser)
    resp = client.get("/staff/")
    assert resp.status_code == 302
    assert resp.url == reverse("admin_tools")


# ---- Board Admin: appointments / committees / governance ----------------

def _board_member(email="boardm@example.com"):
    from committees.models import Committee
    u = User.objects.create_user(email=email, password="x")
    Committee.objects.get(slug="board").add_member(u, start_date=date(2026, 1, 1))
    return u


@pytest.mark.parametrize("name", ["board_appointments", "board_committees", "board_governance"])
def test_board_pages_gated(db, client, name):
    client.force_login(User.objects.create_user(email="no@example.com", password="x"))
    assert client.get(reverse(name)).status_code == 403


@pytest.mark.parametrize("name", ["board_appointments", "board_committees", "board_governance"])
def test_board_pages_render_for_board(db, client, name):
    client.force_login(_board_member(f"{name}@example.com"))
    assert client.get(reverse(name)).status_code == 200


def test_appoint_and_remove_staff_role(db, client):
    from core.access import has_staff_role
    from core.models import StaffRole
    board = _board_member("appt@example.com")
    target = User.objects.create_user(email="newtreas@example.com", password="x")
    client.force_login(board)
    resp = client.post(reverse("board_appointments"), {
        "action": "appoint", "role": StaffRole.TREASURER, "user": target.pk,
    })
    assert resp.status_code == 302
    target.refresh_from_db()
    assert has_staff_role(target, StaffRole.TREASURER)
    # Remove
    client.post(reverse("board_appointments"), {
        "action": "remove", "role": StaffRole.TREASURER, "user": target.pk,
    })
    assert not has_staff_role(target, StaffRole.TREASURER)


def test_gate_or_login_redirects_anonymous(db):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from core.access import gate_or_login
    req = RequestFactory().get("/groups/secret/")
    req.user = AnonymousUser()
    resp = gate_or_login(req)
    assert resp.status_code == 302
    assert resp.url == "/accounts/login/?next=/groups/secret/"


def test_gate_or_login_404s_signed_in_non_member(db):
    from django.http import Http404
    from django.test import RequestFactory

    from core.access import gate_or_login
    req = RequestFactory().get("/groups/secret/")
    req.user = User.objects.create_user(email="gate@example.com", password="x")
    with pytest.raises(Http404):
        gate_or_login(req)


def test_create_committee_provisions_workgroup(db, client):
    from committees.models import Committee
    client.force_login(_board_member("cmt@example.com"))
    resp = client.post(reverse("board_committees"), {
        "name": "Ethics Committee", "description": "Ethics oversight",
        "charter": "Reviews ethics matters.", "public": "",
    })
    assert resp.status_code == 302
    c = Committee.objects.get(name="Ethics Committee")
    assert c.slug == "ethics-committee"
    assert c.workgroup_id is not None  # auto-provisioned


def test_edit_committee(db, client):
    from committees.models import Committee
    client.force_login(_board_member("cmt2@example.com"))
    c = Committee.objects.create(name="Outreach C", slug="outreach-c")
    client.post(reverse("board_committees"), {
        "committee": c.pk, "name": "Outreach C", "description": "Updated desc",
        "charter": "", "public": "on",
    })
    c.refresh_from_db()
    assert c.description == "Updated desc" and c.public is True


# ---- Persona-safe email backend: drop vs sandbox-redirect (task #272) ------

import pytest as _pytest  # noqa: E402
from django.core import mail as _mail  # noqa: E402
from django.core.mail import EmailMessage  # noqa: E402
from django.test import override_settings  # noqa: E402

from accounts.models import User as _User  # noqa: E402


@_pytest.mark.django_db
@override_settings(
    PERSONA_SAFE_INNER_EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
def test_persona_safe_backend_redirects_owned_drops_orphan_keeps_real():
    from core.email import PersonaSafeEmailBackend

    owner = _User.objects.create_user(email="owner@x.test", password="x")
    owned = _User.objects.create_user(email="s-owned@lacanschool.invalid", password="x")
    owned.profile.is_persona = True
    owned.profile.persona_owner = owner
    owned.profile.save()
    orphan = _User.objects.create_user(email="s-orphan@lacanschool.invalid", password="x")
    orphan.profile.is_persona = True
    orphan.profile.save()

    _mail.outbox.clear()
    PersonaSafeEmailBackend().send_messages([
        EmailMessage("Owned", "b", "f@x.test", ["s-owned@lacanschool.invalid"]),
        EmailMessage("Orphan", "b", "f@x.test", ["s-orphan@lacanschool.invalid"]),
        EmailMessage("Real", "b", "f@x.test", ["real@x.test"]),
    ])

    subjects = [m.subject for m in _mail.outbox]
    # owned persona → redirected to owner, tagged
    owned_msg = next(m for m in _mail.outbox if "owner@x.test" in m.to)
    assert owned_msg.subject.startswith("[SANDBOX → s-owned@lacanschool.invalid]")
    # orphan persona → dropped entirely
    assert all("s-orphan@lacanschool.invalid" not in m.to for m in _mail.outbox)
    assert not any(s.startswith("[SANDBOX") and "Orphan" in s for s in subjects)
    # real recipient → kept untouched
    assert any(m.to == ["real@x.test"] and m.subject == "Real" for m in _mail.outbox)
