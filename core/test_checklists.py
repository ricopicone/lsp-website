"""The data-driven walkthrough registry (core.checklists)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.checklists import CHECKLISTS, get_checklist


def test_registry_has_a_walkthrough_per_guide():
    assert set(CHECKLISTS) == {
        "profile", "seminars", "parletre", "cartels", "my_formation", "tuition_dues",
        "faculty",
        # Admin walkthroughs — started from the console, not a guide page.
        "applications_coordinator", "analyst_interviews",
    }
    # No always-on default walkthrough.
    assert "getting_started" not in CHECKLISTS


def test_get_checklist_returns_titled_tasks():
    profile = get_checklist("profile")
    assert profile.title == "Set up your profile"
    assert [t.id for t in profile.tasks][:2] == ["pf_photo", "pf_bio"]
    assert get_checklist("nope") is None


def test_manual_and_auto_task_mix():
    tasks = {t.id: t for t in get_checklist("profile").tasks}
    assert tasks["pf_photo"].manual is False   # auto: ticks from real data
    assert tasks["pf_visibility"].manual is True  # member checks it off


@pytest.mark.django_db
def test_auto_task_resolves_done_from_data(rf):
    user = get_user_model().objects.create_user(email="t@example.com", password="x")
    request = rf.get("/")
    request.user = user
    photo = next(t for t in get_checklist("profile").tasks if t.id == "pf_photo")
    d = photo.resolved(user, request)
    assert d["done"] is False           # no headshot yet
    assert d["url"]                     # profile_edit reverses
    assert d["show_hint"] is True       # not done + has anchor


@pytest.mark.django_db
def test_manual_task_never_done_serverside(rf):
    user = get_user_model().objects.create_user(email="m@example.com", password="x")
    request = rf.get("/")
    request.user = user
    vis = next(t for t in get_checklist("profile").tasks if t.id == "pf_visibility")
    d = vis.resolved(user, request)
    assert d["manual"] is True
    assert d["done"] is False
    assert d["show_hint"] is False      # manual steps never pulse


def test_admin_walkthroughs_registered_and_resolve():
    from core.checklists import CHECKLISTS, get_checklist

    for wid in ("applications_coordinator", "analyst_interviews"):
        assert wid in CHECKLISTS
        cl = get_checklist(wid)
        assert cl and cl.tasks
        for task in cl.tasks:
            task.resolve_url(None)  # resolver runs without error


# --- Faculty walkthrough (task #749) ---------------------------------------
# Each step links to the viewer's OWN offering, so a faculty member can run the
# walkthrough on their real seminar after the training.

def _offering(slug, event_type, start, end):
    from datetime import date

    from events.models import Event

    ev = Event.objects.create(
        title=slug, slug=slug, event_type=event_type,
        start_date=date(*start), end_date=date(*end), published=True,
        status=Event.Status.OPEN,
    )
    ev.ensure_workgroup()
    return ev


def _lead(event, user, role):
    from workgroups.models import WorkgroupMembership

    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=user, role=role,
        start_date=event.start_date,
    )


def _resolved(user, rf, task_id):
    request = rf.get("/")
    request.user = user
    task = next(t for t in get_checklist("faculty").tasks if t.id == task_id)
    return task.resolved(user, request)


@pytest.fixture
def faculty_user(db):
    return get_user_model().objects.create_user(email="fac@example.com", password="x")


@pytest.mark.django_db
def test_faculty_walkthrough_links_to_the_viewers_own_seminar(rf, faculty_user):
    from events.models import Event
    from workgroups.models import WorkgroupMembership

    ev = _offering("my-seminar-2026-27", Event.Type.SEMINAR, (2026, 9, 1), (2027, 5, 1))
    _lead(ev, faculty_user, WorkgroupMembership.Role.FACULTY)

    assert _resolved(faculty_user, rf, "fac_roster")["url"] == (
        f"/groups/{ev.workgroup.slug}/?tab=roster"
    )
    assert _resolved(faculty_user, rf, "fac_edit")["url"] == f"/events/{ev.slug}/edit/"
    assert _resolved(faculty_user, rf, "fac_joining")["url"] == (
        f"/events/{ev.slug}/joining-instructions/"
    )


@pytest.mark.django_db
def test_faculty_walkthrough_reaches_a_reading_group_convener(rf, faculty_user):
    from events.models import Event
    from workgroups.models import WorkgroupMembership

    rg = _offering("freud-rg-2026-27", Event.Type.READING_GROUP, (2026, 9, 1), (2027, 5, 1))
    _lead(rg, faculty_user, WorkgroupMembership.Role.ORGANIZER)

    assert _resolved(faculty_user, rf, "fac_roster")["url"] == (
        f"/groups/{rg.workgroup.slug}/?tab=roster"
    )


@pytest.mark.django_db
def test_faculty_walkthrough_prefers_the_current_offering_over_a_past_one(rf, faculty_user):
    from events.models import Event
    from workgroups.models import WorkgroupMembership

    past = _offering("old-seminar-2019-20", Event.Type.SEMINAR, (2019, 9, 1), (2020, 5, 1))
    current = _offering("new-seminar", Event.Type.SEMINAR, (2026, 9, 1), (2999, 5, 1))
    _lead(past, faculty_user, WorkgroupMembership.Role.FACULTY)
    _lead(current, faculty_user, WorkgroupMembership.Role.FACULTY)

    assert _resolved(faculty_user, rf, "fac_edit")["url"] == f"/events/{current.slug}/edit/"


@pytest.mark.django_db
def test_faculty_walkthrough_falls_back_to_my_groups_without_an_offering(rf, faculty_user):
    d = _resolved(faculty_user, rf, "fac_roster")
    assert d["url"] == "/formation/?tab=groups"
    assert _resolved(faculty_user, rf, "fac_edit")["url"] == "/formation/?tab=groups"


@pytest.mark.django_db
def test_faculty_code_step_ticks_once_they_have_minted_a_code(rf, faculty_user):
    from events.models import Event, PricingCode
    from workgroups.models import WorkgroupMembership

    ev = _offering("coded-seminar", Event.Type.SEMINAR, (2026, 9, 1), (2999, 5, 1))
    _lead(ev, faculty_user, WorkgroupMembership.Role.FACULTY)
    assert _resolved(faculty_user, rf, "fac_code")["done"] is False

    PricingCode.objects.create(
        event=ev, code="TRY-ME", issued_by=faculty_user,
        pricing_mode=PricingCode.Mode.FULL_PRICE, amount_or_percent=0,
    )
    assert _resolved(faculty_user, rf, "fac_code")["done"] is True


@pytest.mark.django_db
def test_faculty_walkthrough_sends_nothing(rf, faculty_user):
    """Every step is safe to take on a real seminar: none is an email send.
    The joining-instructions step stops at the preview page."""
    for task in get_checklist("faculty").tasks:
        assert "send" not in task.label.lower()
