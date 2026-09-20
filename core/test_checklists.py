"""The data-driven walkthrough registry (core.checklists)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.checklists import CHECKLISTS, get_checklist


def test_registry_has_a_walkthrough_per_guide():
    assert set(CHECKLISTS) == {
        "profile", "seminars", "parletre", "cartels", "my_formation", "tuition_dues",
        "faculty", "proposals",
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


def _resolved(user, rf, task_id, wid="faculty"):
    request = rf.get("/")
    request.user = user
    task = next(t for t in get_checklist(wid).tasks if t.id == task_id)
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

    assert _resolved(faculty_user, rf, "fac_workspace")["url"] == (
        f"/groups/{ev.workgroup.slug}/"
    )
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


def test_faculty_walkthrough_starts_on_the_workspace_overview_then_walks_the_tabs():
    ids = [t.id for t in get_checklist("faculty").tasks]
    assert ids[:7] == ["fac_workspace", "fac_discuss", "fac_chat", "fac_meet",
                       "fac_files", "fac_roster", "fac_settings"]


def test_faculty_open_steps_tick_on_visit_but_close_and_reopen_does_not():
    """Landing on a step's page is doing it (Rico, 2026-09-20) — except for
    the one step whose page proves nothing on its own."""
    tasks = {t.id: t for t in get_checklist("faculty").tasks}
    assert tasks["fac_workspace"].visit_ticks is True
    assert tasks["fac_roster"].visit_ticks is True
    assert tasks["fac_edit"].visit_ticks is True
    assert tasks["fac_joining"].visit_ticks is True
    assert tasks["fac_status"].visit_ticks is False
    assert tasks["fac_code"].visit_ticks is False   # auto step; ticks from data


@pytest.mark.django_db
def test_resolved_task_carries_visit_ticks(rf, faculty_user):
    assert _resolved(faculty_user, rf, "fac_workspace")["visit_ticks"] is True
    assert _resolved(faculty_user, rf, "fac_status")["visit_ticks"] is False


@pytest.mark.django_db
def test_faculty_code_step_unticks_when_the_only_code_is_revoked(rf, faculty_user):
    """Rico minted a code for the demo, revoked it, and the step stayed ticked:
    a revoked code is not a code they can hand to anyone."""
    from django.utils import timezone

    from events.models import Event, PricingCode
    from workgroups.models import WorkgroupMembership

    ev = _offering("revoked-seminar", Event.Type.SEMINAR, (2026, 9, 1), (2999, 5, 1))
    _lead(ev, faculty_user, WorkgroupMembership.Role.FACULTY)
    code = PricingCode.objects.create(
        event=ev, code="GONE", issued_by=faculty_user,
        pricing_mode=PricingCode.Mode.FULL_PRICE, amount_or_percent=0,
    )
    assert _resolved(faculty_user, rf, "fac_code")["done"] is True
    code.valid_until = timezone.now()
    code.save()
    assert _resolved(faculty_user, rf, "fac_code")["done"] is False


# --- Route hints (task #749, route-hints spec) ------------------------------

def _rf_request(rf, user, path):
    request = rf.get(path)
    request.user = user
    return request


def test_hop_matches_path_only_or_path_and_query(rf, db):
    from core.checklists import Hop

    user = get_user_model().objects.create_user(email="h@example.com", password="x")
    path_only = Hop(page="/groups/x/", selector="[data-tour=a]", text="A")
    with_query = Hop(page="/groups/x/?tab=roster", selector="[data-tour=b]", text="B")
    assert path_only.matches(_rf_request(rf, user, "/groups/x/?tab=meet")) is True
    assert with_query.matches(_rf_request(rf, user, "/groups/x/?tab=meet")) is False
    assert with_query.matches(_rf_request(rf, user, "/groups/x/?tab=roster")) is True
    assert Hop(page="*", selector="[data-tour=c]", text="C").matches(
        _rf_request(rf, user, "/anything/")) is True


def test_task_hop_for_picks_the_first_matching_hop(rf, db):
    from core.checklists import ChecklistTask, Hop

    user = get_user_model().objects.create_user(email="h2@example.com", password="x")
    task = ChecklistTask(id="t", label="T", detail="", manual=True, route=(
        Hop(page="/groups/x/?tab=roster", selector="[data-tour=code]", text="Here."),
        Hop(page="/groups/x/", selector="[data-tour=ws-tab-roster]", text="Roster tab."),
        Hop(page="*", selector="[data-tour=avatar]", text="Open your menu."),
    ))
    roster = _rf_request(rf, user, "/groups/x/?tab=roster")
    assert task.hop_for(roster)["selector"] == "[data-tour=code]"
    meet = _rf_request(rf, user, "/groups/x/?tab=meet")
    assert task.hop_for(meet)["selector"] == "[data-tour=ws-tab-roster]"
    assert task.hop_for(_rf_request(rf, user, "/"))["index"] == 2
    assert task.resolved(user, _rf_request(rf, user, "/"))["hop"]["text"] == "Open your menu."


def test_hop_page_and_selector_may_be_callables(rf, db):
    from core.checklists import ChecklistTask, Hop

    user = get_user_model().objects.create_user(email="h3@example.com", password="x")
    task = ChecklistTask(id="t2", label="T", detail="", manual=True, route=(
        Hop(page=lambda r: "/groups/mine/", selector=lambda r: "[data-tour-slug=mine]",
            text="Yours."),
    ))
    mine = _rf_request(rf, user, "/groups/mine/")
    assert task.hop_for(mine)["selector"] == "[data-tour-slug=mine]"
    assert task.hop_for(_rf_request(rf, user, "/groups/other/")) is None


def test_hop_with_unresolvable_page_never_matches(rf, db):
    from core.checklists import ChecklistTask, Hop

    user = get_user_model().objects.create_user(email="h4@example.com", password="x")
    task = ChecklistTask(id="t3", label="T", detail="", manual=True, route=(
        Hop(page=lambda r: None, selector="[data-tour=x]", text="X"),
    ))
    assert task.hop_for(_rf_request(rf, user, "/")) is None


def test_task_refuses_both_route_and_hint():
    from core.checklists import ChecklistTask, Hop

    with pytest.raises(ValueError):
        ChecklistTask(id="t4", label="T", detail="", hint_selector="#x",
                      route=(Hop(page="*", selector="#y", text="Y"),))


@pytest.mark.django_db
def test_faculty_routes_point_at_the_viewers_own_seminar(rf, faculty_user):
    from events.models import Event
    from workgroups.models import WorkgroupMembership

    ev = _offering("routed-seminar", Event.Type.SEMINAR, (2026, 9, 1), (2999, 5, 1))
    _lead(ev, faculty_user, WorkgroupMembership.Role.FACULTY)
    slug = ev.workgroup.slug
    tasks = {t.id: t for t in get_checklist("faculty").tasks}

    # Off the route: every step points at the avatar menu.
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, "/guides/faculty/"))
    assert hop["selector"] == "[data-tour=avatar]"
    # On My LSP → Groups: the viewer's own card.
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, "/formation/?tab=groups"))
    assert hop["selector"] == f'[data-tour=group-card][data-tour-slug="{slug}"]'
    # On the Workspace (any tab): the Roster tab.
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, f"/groups/{slug}/?tab=meet"))
    assert hop["selector"] == "[data-tour=ws-tab-roster]"
    # On the Roster tab: the code form and the joining button.
    roster = _rf_request(rf, faculty_user, f"/groups/{slug}/?tab=roster")
    assert tasks["fac_code"].hop_for(roster)["selector"] == "[data-tour=generate-code]"
    assert tasks["fac_joining"].hop_for(roster)["selector"] == "[data-tour=joining-instructions]"
    # Edit event: from the Workspace, the button; on the edit page, the panel.
    assert tasks["fac_edit"].hop_for(roster)["selector"] == "[data-tour=edit-event]"
    edit = _rf_request(rf, faculty_user, f"/events/{ev.slug}/edit/")
    assert tasks["fac_status"].hop_for(edit)["selector"] == "[data-tour=registration-status]"
    # Video: the Meet tab, then its test link.
    assert tasks["fac_video"].hop_for(roster)["selector"] == "[data-tour=ws-tab-meet]"
    meet = _rf_request(rf, faculty_user, f"/groups/{slug}/?tab=meet")
    assert tasks["fac_video"].hop_for(meet)["selector"] == "[data-tour=meet-system-check]"
    # The private room is reached from My LSP.
    hub = _rf_request(rf, faculty_user, "/formation/?tab=groups")
    assert tasks["fac_room"].hop_for(hub)["selector"] == "[data-tour=my-lsp-room]"


@pytest.mark.django_db
def test_faculty_routes_without_an_offering_only_point_at_the_menu(rf, faculty_user):
    tasks = {t.id: t for t in get_checklist("faculty").tasks}
    hop = tasks["fac_roster"].hop_for(_rf_request(rf, faculty_user, "/formation/?tab=groups"))
    assert hop["selector"] == "[data-tour=avatar]"


def test_every_faculty_step_has_a_fallback_hop():
    for task in get_checklist("faculty").tasks:
        assert task.route, task.id
        assert task.route[-1].page == "*", task.id


@pytest.mark.django_db
def test_faculty_tab_steps_link_to_each_tab_and_route_through_it(rf, faculty_user):
    from events.models import Event
    from workgroups.models import WorkgroupMembership

    ev = _offering("tabbed-seminar", Event.Type.SEMINAR, (2026, 9, 1), (2999, 5, 1))
    _lead(ev, faculty_user, WorkgroupMembership.Role.FACULTY)
    slug = ev.workgroup.slug
    tasks = {t.id: t for t in get_checklist("faculty").tasks}
    for key in ("discuss", "chat", "meet", "files", "settings"):
        task = tasks[f"fac_{key}"]
        assert task.visit_ticks is True
        url = _resolved(faculty_user, rf, f"fac_{key}")["url"]
        assert url == f"/groups/{slug}/?tab={key}"
        on_workspace = _rf_request(rf, faculty_user, f"/groups/{slug}/")
        assert task.hop_for(on_workspace)["selector"] == f"[data-tour=ws-tab-{key}]"


# --- Proposals walkthrough --------------------------------------------------

def _proposal(user, status, **kw):
    from events.models import Event, EventProposal

    kw.setdefault("event_type", Event.Type.SEMINAR)
    kw.setdefault("title", "A proposal")
    return EventProposal.objects.create(proposed_by=user, status=status, **kw)


@pytest.mark.django_db
def test_proposals_walkthrough_links_and_routes(rf, faculty_user):
    tasks = {t.id: t for t in get_checklist("proposals").tasks}
    assert [t.id for t in get_checklist("proposals").tasks] == [
        "prop_tab", "prop_new", "prop_describe", "prop_when_where", "prop_fee",
        "prop_save", "prop_submit", "prop_track",
    ]
    tab_url = _resolved(faculty_user, rf, "prop_tab", "proposals")["url"]
    assert tab_url == "/formation/?tab=proposals"
    assert _resolved(faculty_user, rf, "prop_new", "proposals")["url"] == "/propose/"
    assert tasks["prop_tab"].visit_ticks is True
    assert tasks["prop_new"].visit_ticks is True
    # Routes: from anywhere the avatar; on the hub the Proposals tab; on the
    # tab the New proposal button; on the form the section, then the buttons.
    hub = _rf_request(rf, faculty_user, "/formation/?tab=groups")
    assert tasks["prop_tab"].hop_for(hub)["selector"] == "[data-tour=my-lsp-proposals]"
    tab = _rf_request(rf, faculty_user, "/formation/?tab=proposals")
    assert tasks["prop_new"].hop_for(tab)["selector"] == "[data-tour=new-proposal]"
    form = _rf_request(rf, faculty_user, "/propose/")
    assert tasks["prop_describe"].hop_for(form)["selector"] == "[data-tour=proposal-type]"
    assert tasks["prop_save"].hop_for(form)["selector"] == "[data-tour=proposal-save]"
    assert tasks["prop_submit"].hop_for(form)["selector"] == "[data-tour=proposal-submit]"
    # On the hub the Proposals tab is the next hop; anywhere else, the menu.
    assert tasks["prop_submit"].hop_for(hub)["selector"] == "[data-tour=my-lsp-proposals]"
    assert tasks["prop_submit"].hop_for(_rf_request(rf, faculty_user, "/"))["selector"] == (
        "[data-tour=avatar]")


@pytest.mark.django_db
def test_proposals_save_and_submit_steps_tick_from_the_viewers_proposals(rf, faculty_user):
    from events.models import EventProposal

    assert _resolved(faculty_user, rf, "prop_save", "proposals")["done"] is False
    assert _resolved(faculty_user, rf, "prop_submit", "proposals")["done"] is False
    p = _proposal(faculty_user, EventProposal.Status.SAVED)
    assert _resolved(faculty_user, rf, "prop_save", "proposals")["done"] is True
    assert _resolved(faculty_user, rf, "prop_submit", "proposals")["done"] is False
    p.status = EventProposal.Status.PROPOSED
    p.save()
    assert _resolved(faculty_user, rf, "prop_submit", "proposals")["done"] is True
    # A submitted proposal counts as "saved" too (it had to be).
    assert _resolved(faculty_user, rf, "prop_save", "proposals")["done"] is True
