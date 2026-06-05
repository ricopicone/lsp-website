"""Tests for the shared Workgroup layer — visibility, roster, toggles."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import Profile, User
from cartels.models import Cartel
from committees.models import Committee
from workgroups.models import Visibility, Workgroup, WorkgroupMembership

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.MEMBER, is_staff=False, first="", last=""):
    u = User.objects.create_user(
        email=email, password="x", is_staff=is_staff, first_name=first, last_name=last
    )
    u.profile.role = role
    u.profile.save()
    return u


def _wg(**kwargs):
    kwargs.setdefault("kind", Workgroup.Kind.CARTEL)
    kwargs.setdefault("name", "Test Group")
    return Workgroup.objects.create(**kwargs)


# ---- Roster / is_member ------------------------------------------------

def test_is_member_only_for_active_membership():
    wg = _wg()
    insider = _user("in@x.test")
    outsider = _user("out@x.test")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    assert wg.is_member(insider) is True
    assert wg.is_member(outsider) is False


def test_ended_membership_is_not_current():
    wg = _wg()
    u = _user("u@x.test")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u,
        start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2025, 1, 1),
    )
    assert wg.is_member(u) is False
    assert wg.active_members().count() == 0


def test_one_active_membership_per_user_group():
    wg = _wg()
    u = _user("u@x.test")
    d1, d2 = datetime.date(2026, 1, 1), datetime.date(2026, 2, 1)
    WorkgroupMembership.objects.create(workgroup=wg, user=u, start_date=d1)
    with pytest.raises(Exception):  # IntegrityError from the partial-unique constraint
        WorkgroupMembership.objects.create(workgroup=wg, user=u, start_date=d2)


# ---- Visibility --------------------------------------------------------

def test_public_landing_visible_to_anonymous():
    wg = _wg(landing_visibility=Visibility.PUBLIC, content_visibility=Visibility.PRIVATE)
    assert wg.landing_visible_to(None) is True
    assert wg.content_visible_to(None) is False


def test_members_visibility_requires_lsp_member():
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.MEMBERS)
    member = _user("m@x.test", role=Profile.Role.ANALYST)
    guest = _user("g@x.test", role=Profile.Role.EXTERNAL)
    assert wg.content_visible_to(member) is True
    assert wg.content_visible_to(guest) is False


def test_private_content_visible_only_to_group_members():
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.PRIVATE)
    member = _user("m@x.test", role=Profile.Role.ANALYST)        # LSP member, not in group
    insider = _user("i@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    assert wg.landing_visible_to(member) is True       # MEMBERS landing
    assert wg.content_visible_to(member) is False       # PRIVATE content, not in group
    assert wg.content_visible_to(insider) is True


def test_content_not_more_public_than_landing():
    wg = _wg(landing_visibility=Visibility.PRIVATE, content_visibility=Visibility.PUBLIC)
    with pytest.raises(ValidationError) as exc:
        wg.clean()
    assert "content_visibility" in exc.value.error_dict


def test_committee_member_counts_as_lsp_member_for_members_visibility():
    """A committee member with a non-directory role still passes MEMBERS."""
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.MEMBERS)
    staffer = _user("s@x.test", role=Profile.Role.EXTERNAL)
    committee = Committee.objects.create(name="Ethics", slug="ethics")
    committee.add_member(staffer, start_date=datetime.date(2026, 1, 1))
    assert wg.content_visible_to(staffer) is True


# ---- Toggle seed + Cartel helper --------------------------------------

def test_kind_toggle_defaults_seed():
    assert Workgroup.kind_toggle_defaults(Workgroup.Kind.SEMINAR)["has_works"] is False
    assert Workgroup.kind_toggle_defaults(Workgroup.Kind.WORKING_GROUP)["has_decisions"] is True


def test_cartel_create_with_workgroup_applies_seed():
    cartel = Cartel.objects.create_with_workgroup(name="Speech & Writing")
    assert cartel.workgroup.kind == Workgroup.Kind.CARTEL
    assert cartel.workgroup.slug == "speech-writing"
    assert cartel.workgroup.has_works is True
    assert cartel.workgroup.has_tasks is True       # cartel seed
    assert cartel.workgroup.has_minutes is False     # not in cartel seed
    assert str(cartel) == "Speech & Writing"


def test_slug_autopopulated_from_name():
    wg = _wg(name="The Purloined Letter", slug="")
    assert wg.slug == "the-purloined-letter"


# ---- Workspace surface (views) ----------------------------------------

def test_detail_404_when_landing_not_visible(client):
    wg = _wg(landing_visibility=Visibility.PRIVATE, content_visibility=Visibility.PRIVATE)
    # anonymous user: a private-landing group must not even reveal it exists
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 404


def test_detail_hides_roster_from_non_members_for_members_only_kind(client):
    # A cartel's roster is open to LSP members, not the public.
    wg = _wg(landing_visibility=Visibility.PUBLIC, content_visibility=Visibility.PRIVATE)
    secret = _user("secret@x.test", role=Profile.Role.ANALYST, first="Verena")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=secret, start_date=datetime.date(2026, 1, 1)
    )
    resp = client.get(wg.get_absolute_url())   # anonymous: not an LSP member
    assert resp.status_code == 200
    assert b"visible to LSP members" in resp.content
    assert b"Verena" not in resp.content


def test_detail_shows_roster_to_group_member(client):
    wg = _wg(landing_visibility=Visibility.MEMBERS, content_visibility=Visibility.PRIVATE)
    insider = _user("insider@x.test", first="Vera", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=insider, start_date=datetime.date(2026, 1, 1)
    )
    client.force_login(insider)
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert b"Vera" in resp.content


@pytest.mark.parametrize("kind,public,members_only", [
    (Workgroup.Kind.COMMITTEE, True, True),
    (Workgroup.Kind.WORKING_GROUP, True, True),
    (Workgroup.Kind.CARTEL, False, True),
    (Workgroup.Kind.READING_GROUP, False, True),
    (Workgroup.Kind.SEMINAR, False, False),
])
def test_roster_visibility_policy_by_kind(kind, public, members_only):
    """Committees / working groups: roster public. Cartels / reading groups:
    LSP members. Seminars: never."""
    from django.contrib.auth.models import AnonymousUser

    wg = _wg(kind=kind, landing_visibility=Visibility.PUBLIC)
    lsp_member = _user("analyst@x.test", role=Profile.Role.ANALYST)
    assert wg.roster_visible_to(AnonymousUser()) is public
    assert wg.roster_visible_to(lsp_member) is members_only


def test_auto_member_role_derives_membership():
    """A workgroup with auto_member_role makes every user of that Profile role
    a member — derived, with no stored roster row."""
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, auto_member_role="analyst")
    analyst = _user("a@x.test", role=Profile.Role.ANALYST)
    other = _user("m@x.test", role=Profile.Role.MEMBER)

    assert wg.is_member(analyst) is True
    assert wg.is_member(other) is False
    users = [p.user for p in wg.participants()]
    assert analyst in users and other not in users
    assert not WorkgroupMembership.objects.filter(workgroup=wg, user=analyst).exists()


def test_reading_group_open_join_and_leave(client):
    """A reading group is standing + open-join: any LSP member joins directly
    (stored membership), and can leave."""
    wg = _wg(kind=Workgroup.Kind.READING_GROUP,
             landing_visibility=Visibility.MEMBERS, open_join=True)
    assert wg.open_join is True            # seeded by kind default too
    member = _user("rg@x.test", role=Profile.Role.ANALYST)   # an LSP member
    client.force_login(member)

    resp = client.get(wg.get_absolute_url())
    assert b"Join this group" in resp.content

    client.post(reverse("workgroups:join", args=[wg.slug]))
    assert wg.is_member(member)
    assert wg.memberships.filter(user=member, end_date__isnull=True).exists()

    resp = client.get(wg.get_absolute_url())
    assert b"Leave group" in resp.content

    client.post(reverse("workgroups:leave", args=[wg.slug]))
    assert not wg.memberships.filter(user=member, end_date__isnull=True).exists()


def test_reading_group_public_landing_roster_members_only(client):
    """Reading group page is public (like seminars), but the roster is hidden
    from the public and shown to LSP members; anon sees a login-to-join prompt."""
    from workgroups.models import build_workgroup

    wg = build_workgroup(Workgroup.Kind.READING_GROUP, name="Freud RG", slug="freud-rg")
    assert wg.landing_visibility == Visibility.PUBLIC
    assert wg.content_visibility == Visibility.MEMBERS
    organizer = _user("org@x.test", role=Profile.Role.ANALYST, first="Sabina")
    WorkgroupMembership.objects.create(
        workgroup=wg, user=organizer, role=WorkgroupMembership.Role.ORGANIZER,
        start_date=datetime.date(2026, 1, 1),
    )

    # Anonymous: page visible, no roster, prompted to log in to join.
    resp = client.get(wg.get_absolute_url())
    assert resp.status_code == 200
    assert b"Freud RG" in resp.content
    assert b"Log in to join" in resp.content
    assert b"Sabina" not in resp.content          # roster hidden from the public
    from django.contrib.auth.models import AnonymousUser
    assert wg.roster_visible_to(AnonymousUser()) is False

    # An LSP member sees the roster (membership visible to logged-in members).
    viewer = _user("viewer@x.test", role=Profile.Role.ANALYST)
    client.force_login(viewer)
    resp = client.get(wg.get_absolute_url())
    assert b"Sabina" in resp.content
    assert b"Join this group" in resp.content


def _paid_reading_group(slug="freud-rg", term_start=datetime.date(2099, 9, 1),
                        term_end=datetime.date(2100, 5, 1)):
    """A standing paid reading group with one current term (Event)."""
    from decimal import Decimal

    from events.models import Audience, Event, PriceTier

    wg = _wg(kind=Workgroup.Kind.READING_GROUP, name="Freud RG", slug=slug,
             open_join=False, landing_visibility=Visibility.PUBLIC)
    term = Event.objects.create(
        title="Freud RG term", slug=f"{slug}-term",
        event_type=Event.Type.READING_GROUP, start_date=term_start, end_date=term_end,
        published=True, status=Event.Status.OPEN, workgroup=wg,
    )
    PriceTier.objects.create(event=term, audience=Audience.ALL, base_amount=Decimal("100"))
    return wg, term


def _paid_for(term, user):
    from decimal import Decimal

    from registrations.models import Registration

    return Registration.objects.create(
        user=user, event=term, price_tier=term.price_tiers.first(),
        quoted_amount=Decimal("100"), status=Registration.Status.PAID,
    )


def test_paid_reading_group_membership_from_current_term(client):
    wg, term = _paid_reading_group()
    assert wg.current_term() == term

    payer = _user("payer@x.test", role=Profile.Role.ANALYST)
    _paid_for(term, payer)
    assert wg.is_member(payer) is True
    assert payer in [p.user for p in wg.participants()]

    stranger = _user("stranger@x.test", role=Profile.Role.ANALYST)
    assert wg.is_member(stranger) is False

    # Overview offers the term's register CTA (pay to join), not a free Join.
    resp = client.get(wg.get_absolute_url())
    assert reverse("registrations:register", args=[term.slug]).encode() in resp.content
    assert b"Join this group" not in resp.content


def test_reading_group_membership_lapses_when_term_ends(client):
    # A term that already ended → no current term → registrant lapses.
    wg, term = _paid_reading_group(
        slug="freud-old", term_start=datetime.date(2020, 9, 1),
        term_end=datetime.date(2021, 5, 1),
    )
    payer = _user("payer@x.test", role=Profile.Role.ANALYST)
    _paid_for(term, payer)
    assert wg.current_term() is None
    assert wg.is_member(payer) is False


def test_organizer_opens_reading_group_term(client):
    """An organizer opens a new annual paid term in one click → a published,
    open Event attached to the standing group, with a fee tier."""
    wg = _wg(kind=Workgroup.Kind.READING_GROUP, name="Freud RG", slug="freud-rg",
             open_join=False, landing_visibility=Visibility.PUBLIC)
    organizer = _user("org@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=organizer, role=WorkgroupMembership.Role.ORGANIZER,
        start_date=datetime.date(2026, 1, 1),
    )
    client.force_login(organizer)
    client.post(reverse("workgroups:open_term", args=[wg.slug]), {
        "start_date": "2099-09-01", "end_date": "2100-05-01", "fee": "120.00",
    })

    term = wg.current_term()
    assert term is not None
    assert term.published and term.status == "open"
    assert term.workgroup_id == wg.id
    assert str(term.price_tiers.first().base_amount) == "120.00"


def test_open_term_blocked_for_non_managers(client):
    wg = _wg(kind=Workgroup.Kind.READING_GROUP, slug="rg2", open_join=False)
    plain = _user("plain@x.test", role=Profile.Role.ANALYST)  # not an organizer
    client.force_login(plain)
    resp = client.post(reverse("workgroups:open_term", args=[wg.slug]),
                       {"start_date": "2099-09-01", "end_date": "2100-05-01", "fee": "0"})
    assert resp.status_code == 404
    assert wg.current_term() is None


def test_reading_group_kind_default_open_join():
    from workgroups.models import build_workgroup

    built = build_workgroup(Workgroup.Kind.READING_GROUP, name="RG", slug="rg-x")
    assert built.open_join is True
    cartel_wg = build_workgroup(Workgroup.Kind.CARTEL, name="C", slug="c-x")
    assert cartel_wg.open_join is False


def test_join_blocked_when_not_open_join(client):
    wg = _wg(kind=Workgroup.Kind.CARTEL)   # open_join False
    member = _user("a@x.test", role=Profile.Role.ANALYST)
    client.force_login(member)
    assert client.post(reverse("workgroups:join", args=[wg.slug])).status_code == 404


def test_standing_reading_group_listed_on_program_by_overlap(client):
    from events.models import Program, academic_year_date_range, current_academic_year

    year = current_academic_year()
    Program.objects.create(academic_year=year, published=True)
    ay_start, _ = academic_year_date_range(year)
    wg = _wg(kind=Workgroup.Kind.READING_GROUP, name="Freud Reading Group",
             start_date=ay_start)   # ongoing (no end date)
    assert wg.overlaps_academic_year(year)

    body = client.get(f"/program/?year={year}").content
    assert b"Reading Groups" in body and b"Freud Reading Group" in body


def test_reading_group_workspace_links_to_program(client):
    from events.models import Program, academic_year_date_range, current_academic_year

    year = current_academic_year()
    Program.objects.create(academic_year=year, published=True)
    ay_start, _ = academic_year_date_range(year)
    wg = _wg(kind=Workgroup.Kind.READING_GROUP, name="Freud RG",
             start_date=ay_start, landing_visibility=Visibility.MEMBERS)
    member = _user("m@x.test", role=Profile.Role.ANALYST)
    client.force_login(member)
    resp = client.get(wg.get_absolute_url())
    assert f"/program/?year={year}".encode() in resp.content   # ← Program <year>


def test_personas_have_membership_but_are_hidden_from_roster():
    wg = _wg(kind=Workgroup.Kind.COMMITTEE)
    persona = _user("persona@x.test", role=Profile.Role.ANALYST)
    persona.profile.is_persona = True
    persona.profile.save()
    WorkgroupMembership.objects.create(
        workgroup=wg, user=persona, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2026, 1, 1),
    )
    assert wg.is_member(persona) is True            # real membership (for impersonation)
    assert persona not in [p.user for p in wg.participants()]   # hidden from roster


def test_groups_overview_shows_a_card_per_kind(client):
    """The /groups/ overview lists the kinds, not individual groups."""
    resp = client.get("/groups/")
    assert resp.status_code == 200
    for label in (b"Seminars", b"Cartels", b"Committees",
                  b"Working Groups", b"Reading Groups"):
        assert label in resp.content


def test_kind_list_shows_visible_groups_of_that_kind(client):
    Workgroup.objects.create(
        kind=Workgroup.Kind.WORKING_GROUP, name="Ethics WG",
        landing_visibility=Visibility.PUBLIC,
    )
    Cartel.objects.create_with_workgroup(
        name="Letter Cartel", landing_visibility=Visibility.PUBLIC
    )
    resp = client.get("/groups/working-groups/")
    assert resp.status_code == 200
    assert b"Ethics WG" in resp.content
    assert b"Letter Cartel" not in resp.content   # other kind excluded


def test_reading_groups_kind_page_renders(client):
    resp = client.get("/groups/reading-groups/")
    assert resp.status_code == 200


def test_cartels_listed_under_unified_groups_kind_page(client):
    Cartel.objects.create_with_workgroup(
        name="Speech and Writing", landing_visibility=Visibility.PUBLIC
    )
    # /cartels/ now redirects into the unified Groups section.
    assert client.get("/cartels/").status_code == 302
    resp = client.get("/groups/cartels/")
    assert resp.status_code == 200
    assert b"Speech and Writing" in resp.content


# ---- Phase B: lifecycle (leave / archive / roster management) ----------

def _chair(wg, email="chair@x.test"):
    u = _user(email, role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2026, 1, 1),
    )
    return u


def _plain_member(wg, email):
    u = _user(email, role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, role=WorkgroupMembership.Role.MEMBER,
        start_date=datetime.date(2026, 1, 1),
    )
    return u


def test_archive_freezes_membership_keeps_archive_access():
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Archive")
    chair = _chair(wg)
    member = _plain_member(wg, "m@x.test")
    assert wg.is_member(member) is True
    wg.archive(by=chair)
    wg.refresh_from_db()
    assert wg.is_archived is True
    assert wg.is_member(member) is False           # frozen — can't post
    assert wg.has_archive_access(member) is True    # read-only retained
    assert wg.has_archive_access(_user("out@x.test", role=Profile.Role.ANALYST)) is False
    wg.unarchive()
    wg.refresh_from_db()
    assert wg.is_member(member) is True


def test_can_leave_but_sole_lead_cannot():
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Leave")
    chair = _chair(wg)
    member = _plain_member(wg, "m@x.test")
    assert wg.can_leave(member) is True
    assert wg.can_leave(chair) is False             # sole remaining lead
    assert wg.leave(member) is True
    assert wg.is_member(member) is False
    assert wg.leave(chair) is False                 # refused
    assert wg.is_member(chair) is True


def test_remove_member_and_sole_lead_protected():
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Remove")
    chair = _chair(wg)
    member = _plain_member(wg, "m@x.test")
    assert wg.remove_member(member) is True
    assert wg.is_member(member) is False
    assert wg.remove_member(chair) is False         # would orphan the group
    assert wg.is_member(chair) is True


def test_set_role_protects_last_lead():
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Roles")
    chair = _chair(wg)
    assert wg.set_role(chair, WorkgroupMembership.Role.MEMBER) is False  # sole lead
    member = _plain_member(wg, "m@x.test")
    assert wg.set_role(member, WorkgroupMembership.Role.CO_CHAIR) is True
    assert wg.set_role(chair, WorkgroupMembership.Role.MEMBER) is True   # now ok


def test_roster_add_gated_to_manager(client):
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Gate",
             landing_visibility=Visibility.PUBLIC)
    chair = _chair(wg)
    client.force_login(_user("plain@x.test", role=Profile.Role.ANALYST))
    assert client.post(reverse("workgroups:roster_add", args=[wg.slug]),
                       {"member": "new@x.test"}).status_code == 404
    newbie = _user("new@x.test", role=Profile.Role.ANALYST, first="New", last="Person")
    client.force_login(chair)
    assert client.post(reverse("workgroups:roster_add", args=[wg.slug]),
                       {"member": "new@x.test"}).status_code == 302
    assert wg.is_member(newbie) is True


def test_archive_view_gated_and_settings_reachable_after_archive(client):
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Lifecycle",
             landing_visibility=Visibility.PUBLIC)
    chair = _chair(wg)
    client.force_login(_user("plain@x.test", role=Profile.Role.ANALYST))
    assert client.post(reverse("workgroups:archive", args=[wg.slug])).status_code == 404
    client.force_login(chair)
    assert client.post(reverse("workgroups:archive", args=[wg.slug])).status_code == 302
    wg.refresh_from_db()
    assert wg.is_archived is True
    # The chair is frozen out of active membership but can still manage.
    resp = client.get(f"{wg.get_absolute_url()}?tab=settings")
    assert resp.status_code == 200
    assert b"Reactivate group" in resp.content


def test_working_group_overview_editable_by_member(client):
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="WG Overview",
             landing_visibility=Visibility.PUBLIC)
    member = _plain_member(wg, "wg-mem@x.test")
    client.force_login(member)
    # The editor is offered on the Settings tab...
    resp = client.get(f"{wg.get_absolute_url()}?tab=settings")
    assert resp.status_code == 200
    assert b"Save overview" in resp.content
    # ...and saving updates the name + description.
    resp = client.post(reverse("workgroups:update_overview", args=[wg.slug]), {
        "name": "Renamed WG", "description": "A fresh overview.",
    })
    assert resp.status_code == 302
    wg.refresh_from_db()
    assert wg.name == "Renamed WG"
    assert wg.description == "A fresh overview."
    # Slug is stable across a rename.
    assert Workgroup.objects.filter(slug=wg.slug).exists()


def test_overview_editor_absent_for_committee_and_non_member(client):
    # Committees edit their description via the charter form, so the generic
    # overview editor must not also appear for them.
    from committees.models import Committee

    committee = Committee.objects.create(name="Ethics", slug="ethics")
    wg = committee.workgroup
    wg.landing_visibility = Visibility.PUBLIC
    wg.save(update_fields=["landing_visibility"])
    chair = _chair(wg)
    client.force_login(chair)
    resp = client.get(f"{wg.get_absolute_url()}?tab=settings")
    assert resp.status_code == 200
    assert b"Save overview" not in resp.content
    # And a non-member can't post the overview endpoint.
    client.force_login(_user("nope@x.test", role=Profile.Role.ANALYST))
    assert client.post(
        reverse("workgroups:update_overview", args=[wg.slug]),
        {"name": "Hijack", "description": ""},
    ).status_code == 404


def test_reading_group_schedule_is_organizer_only(client):
    """Open-join reading-group members can't manage the calendar — only
    organizers (leads) / staff do."""
    wg = _wg(kind=Workgroup.Kind.READING_GROUP, name="RG Schedule",
             open_join=True, landing_visibility=Visibility.PUBLIC)
    organizer = _user("rg-org@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=organizer, role=WorkgroupMembership.Role.ORGANIZER,
        start_date=datetime.date(2026, 1, 1),
    )
    member = _user("rg-member@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=member, role=WorkgroupMembership.Role.MEMBER,
        start_date=datetime.date(2026, 1, 1),
    )
    client.force_login(member)
    assert client.post(reverse("workgroups:meeting_add", args=[wg.slug]),
                       {"starts_at": "2099-01-15T18:00"}).status_code == 404
    client.force_login(organizer)
    assert client.post(reverse("workgroups:meeting_add", args=[wg.slug]),
                       {"starts_at": "2099-01-15T18:00"}).status_code == 302


# --- Meeting scheduler -------------------------------------------------------

def _scheduler_wg_and_lead():
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Sched WG", slug="sched-wg")
    wg.has_calendar = True
    wg.save()
    lead = _user("lead@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=lead, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2026, 1, 1),
    )
    return wg, lead


def test_series_materializes_weekly_occurrences(client):
    from workgroups.models import MeetingSeries, WorkgroupMeeting

    wg, lead = _scheduler_wg_and_lead()
    client.force_login(lead)
    client.post(reverse("workgroups:series_add", args=[wg.slug]), {
        "title": "Weekly seminar", "frequency": "weekly", "weekdays": ["TH"],
        "week_position": "1", "start_date": "2099-01-01", "end_date": "2099-01-31",
        "start_time": "18:00", "end_time": "19:30",
        "location": "Online", "online_url": "https://zoom.example/x",
        "access_info": "", "description": "",
    })
    series = MeetingSeries.objects.get(workgroup=wg)
    occ = WorkgroupMeeting.objects.filter(series=series)
    assert occ.count() >= 4                       # the Thursdays of Jan 2099
    assert all(m.online_url == "https://zoom.example/x" for m in occ)


def test_meeting_cancel_reschedule_minutes(client):
    from workgroups.models import WorkgroupMeeting

    wg, lead = _scheduler_wg_and_lead()
    m = WorkgroupMeeting.objects.create(
        workgroup=wg, starts_at=datetime.datetime(2099, 3, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )
    client.force_login(lead)

    client.post(reverse("workgroups:meeting_cancel", args=[wg.slug, m.pk]), {"reason": "Holiday"})
    m.refresh_from_db()
    assert m.cancelled and m.cancellation_reason == "Holiday" and m.is_override

    client.post(reverse("workgroups:meeting_reschedule", args=[wg.slug, m.pk]),
                {"starts_at": "2099-03-08T18:00", "ends_at": "2099-03-08T19:30"})
    m.refresh_from_db()
    from django.utils import timezone as _tz
    assert _tz.localtime(m.starts_at).date() == datetime.date(2099, 3, 8)

    client.post(reverse("workgroups:meeting_minutes", args=[wg.slug, m.pk]),
                {"minutes": "We discussed the Sinthome."})
    m.refresh_from_db()
    assert "Sinthome" in m.minutes


def test_series_delete_keeps_past_and_minuted(client):
    from workgroups.models import MeetingSeries, WorkgroupMeeting

    wg, lead = _scheduler_wg_and_lead()
    series = MeetingSeries.objects.create(
        workgroup=wg, frequency="weekly", weekdays="TH",
        start_date=datetime.date(2099, 1, 1), end_date=datetime.date(2099, 1, 31),
        start_time=datetime.time(18), end_time=datetime.time(19),
    )
    past = WorkgroupMeeting.objects.create(
        workgroup=wg, series=series,
        starts_at=datetime.datetime(2020, 1, 1, 18, tzinfo=datetime.timezone.utc),
    )
    future = WorkgroupMeeting.objects.create(
        workgroup=wg, series=series,
        starts_at=datetime.datetime(2099, 6, 1, 18, tzinfo=datetime.timezone.utc),
    )
    client.force_login(lead)
    client.post(reverse("workgroups:series_delete", args=[wg.slug, series.pk]))

    assert not MeetingSeries.objects.filter(pk=series.pk).exists()
    past.refresh_from_db()
    assert past.series_id is None                 # kept (record), detached
    assert not WorkgroupMeeting.objects.filter(pk=future.pk).exists()   # future removed


def test_ical_feeds(client):
    from workgroups.models import Visibility, WorkgroupMeeting, build_workgroup

    # Public reading group → open feed.
    pub = build_workgroup(Workgroup.Kind.READING_GROUP, name="Freud RG", slug="freud-ical")
    assert pub.landing_visibility == Visibility.PUBLIC
    WorkgroupMeeting.objects.create(
        workgroup=pub, title="Session",
        starts_at=datetime.datetime(2099, 2, 1, 18, tzinfo=datetime.timezone.utc),
    )
    resp = client.get(reverse("workgroups:calendar_ics", args=[pub.slug]))
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/calendar")
    assert b"BEGIN:VCALENDAR" in resp.content and b"Session" in resp.content

    # Members-only group → needs a member's token.
    wg, lead = _scheduler_wg_and_lead()
    WorkgroupMeeting.objects.create(
        workgroup=wg, starts_at=datetime.datetime(2099, 2, 2, 18, tzinfo=datetime.timezone.utc),
    )
    assert client.get(reverse("workgroups:calendar_ics", args=[wg.slug])).status_code == 404
    lead.profile.calendar_token = "tok-abc"
    lead.profile.save()
    ok = client.get(reverse("workgroups:calendar_ics", args=[wg.slug]) + "?token=tok-abc")
    assert ok.status_code == 200

    # Personal feed via token → the member's group meetings.
    mine = client.get(reverse("workgroups:my_calendar_ics", args=["tok-abc"]))
    assert mine.status_code == 200 and b"BEGIN:VCALENDAR" in mine.content
    assert client.get(reverse("workgroups:my_calendar_ics", args=["bogus"])).status_code == 404


# ---- Collaborative working documents (Work tab) ------------------------

def _member_of(wg, email="docmember@x.test"):
    u = _user(email)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, start_date=datetime.date(2000, 1, 1)
    )
    return u


def test_draft_create_redirects_to_editor(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    u = _member_of(wg)
    client.force_login(u)
    resp = client.post(reverse("workgroups:draft_create", args=[wg.slug]),
                       {"title": "My Draft"})
    from works.models import WorkDraft
    draft = WorkDraft.objects.get(workgroup=wg)
    assert draft.title == "My Draft"
    assert resp.status_code == 302
    assert resp.url == reverse("workgroups:draft_edit", args=[wg.slug, draft.pk])


def test_draft_create_linked_google_doc(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    u = _member_of(wg)
    client.force_login(u)
    resp = client.post(reverse("workgroups:draft_create", args=[wg.slug]),
                       {"title": "Linked", "google_doc_url": "https://docs.google.com/x"})
    from works.models import WorkDraft
    draft = WorkDraft.objects.get(workgroup=wg)
    assert draft.is_linked
    assert "tab=work" in resp.url


def test_non_member_cannot_create_draft(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    outsider = _user("outsider@x.test")
    client.force_login(outsider)
    resp = client.post(reverse("workgroups:draft_create", args=[wg.slug]),
                       {"title": "Nope"})
    assert resp.status_code == 404


def test_draft_autosave_saves_content(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    u = _member_of(wg)
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D", created_by=u)
    client.force_login(u)
    resp = client.post(
        reverse("workgroups:draft_autosave", args=[wg.slug, draft.pk]),
        {"content": "<p>hello</p>"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    draft.refresh_from_db()
    assert draft.content_html == "<p>hello</p>"


def test_draft_autosave_blocked_when_locked_by_other(client):
    from django.utils import timezone
    wg = _wg(name="Doc Group", slug="doc-group")
    holder = _member_of(wg, "holder@x.test")
    other = _member_of(wg, "other@x.test")
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(
        workgroup=wg, title="D", locked_by=holder, locked_at=timezone.now()
    )
    client.force_login(other)
    resp = client.post(
        reverse("workgroups:draft_autosave", args=[wg.slug, draft.pk]),
        {"content": "<p>stomp</p>"},
    )
    assert resp.status_code == 409
    draft.refresh_from_db()
    assert draft.content_html == ""


def test_draft_publish_creates_work_with_pdf(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    manager = _member_of(wg, "mgr@x.test")
    manager.is_superuser = True
    manager.save()
    from works.models import Work, WorkDraft
    draft = WorkDraft.objects.create(
        workgroup=wg, title="Findings",
        content_html="<h1>Title</h1><p>Body</p><script>alert(1)</script>",
    )
    client.force_login(manager)
    resp = client.post(
        reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
        {"visibility": "members"},
    )
    assert resp.status_code == 302
    work = Work.objects.get(workgroup=wg, kind=Work.Kind.DOCUMENT)
    assert work.title == "Findings"
    assert "<script>" not in work.body_html       # sanitized
    assert "alert(1)" not in work.body_html
    assert work.files.filter(label="Published PDF").count() == 1
    draft.refresh_from_db()
    assert draft.published_work_id == work.pk


def test_draft_publish_blocked_for_plain_member(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    plain = _member_of(wg, "plain@x.test")
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D")
    client.force_login(plain)
    resp = client.post(
        reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
        {"visibility": "members"},
    )
    assert resp.status_code == 404


def test_draft_republish_updates_same_work(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    manager = _member_of(wg, "mgr@x.test")
    manager.is_superuser = True
    manager.save()
    from works.models import Work, WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="V1", content_html="<p>one</p>")
    client.force_login(manager)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    draft.refresh_from_db()
    draft.title = "V2"
    draft.content_html = "<p>two</p>"
    draft.save()
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    assert Work.objects.filter(workgroup=wg, kind=Work.Kind.DOCUMENT).count() == 1
    work = Work.objects.get(workgroup=wg, kind=Work.Kind.DOCUMENT)
    assert work.title == "V2"
    assert "two" in work.body_html
    assert work.files.filter(label="Published PDF").count() == 1   # not duplicated
    assert work.publication_date is not None                       # stamped on publish
    # Two publishes → two "Published" snapshots (revision history).
    assert draft.versions.filter(label="Published").count() == 2


def test_published_work_page_shows_provenance_and_revisions(client):
    wg = _wg(name="The Letter", slug="the-letter")
    manager = _member_of(wg, "mgr@x.test")
    manager.is_superuser = True
    manager.save()
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="Findings",
                                     content_html="<p>body</p>")
    client.force_login(manager)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "public"})
    draft.refresh_from_db()
    resp = client.get(draft.published_work.get_absolute_url())
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Published by" in body
    assert "The Letter" in body              # group name (provenance)
    assert "Revision history" in body
    assert "Revision 1" in body


def test_draft_delete(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    u = _member_of(wg)
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D")
    client.force_login(u)
    resp = client.post(reverse("workgroups:draft_delete", args=[wg.slug, draft.pk]))
    assert resp.status_code == 302
    assert not WorkDraft.objects.filter(pk=draft.pk).exists()


def test_draft_edit_page_renders_and_acquires_lock(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    u = _member_of(wg)
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D", content_html="<p>hi</p>")
    client.force_login(u)
    resp = client.get(reverse("workgroups:draft_edit", args=[wg.slug, draft.pk]))
    assert resp.status_code == 200
    assert b"js/vendor/doc-editor.js" in resp.content   # vendored bundle, no CDN
    assert b"LSPDocEditor.init" in resp.content
    draft.refresh_from_db()
    assert draft.locked_by_id == u.pk


def test_work_tab_lists_drafts_for_member(client):
    wg = _wg(name="Doc Group", slug="doc-group", has_works=True,
             content_visibility=Visibility.MEMBERS)
    u = _member_of(wg)
    from works.models import WorkDraft
    WorkDraft.objects.create(workgroup=wg, title="Shared notes")
    client.force_login(u)
    resp = client.get(f"{wg.get_absolute_url()}?tab=work")
    assert resp.status_code == 200
    assert b"Shared notes" in resp.content
    assert b"Working documents" in resp.content


def test_unpublish_removes_work_keeps_draft(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    manager = _member_of(wg, "mgr@x.test")
    manager.is_superuser = True
    manager.save()
    from works.models import Work, WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D", content_html="<p>x</p>")
    client.force_login(manager)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    draft.refresh_from_db()
    work_pk = draft.published_work_id
    assert work_pk is not None
    resp = client.post(reverse("workgroups:draft_unpublish", args=[wg.slug, draft.pk]))
    assert resp.status_code == 302
    assert resp.url == reverse("workgroups:draft_edit", args=[wg.slug, draft.pk])
    draft.refresh_from_db()
    assert draft.published_work_id is None              # back to editable draft
    assert not Work.objects.filter(pk=work_pk).exists()  # work removed
    assert WorkDraft.objects.filter(pk=draft.pk).exists()  # draft kept


def test_unpublish_blocked_for_non_manager(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    manager = _member_of(wg, "mgr@x.test")
    manager.is_superuser = True
    manager.save()
    plain = _member_of(wg, "plain@x.test")
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D")
    client.force_login(manager)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    client.force_login(plain)
    resp = client.post(reverse("workgroups:draft_unpublish", args=[wg.slug, draft.pk]))
    assert resp.status_code == 404
    draft.refresh_from_db()
    assert draft.published_work_id is not None          # untouched


def test_delete_document_work_keeps_source_draft(client):
    wg = _wg(name="Doc Group", slug="doc-group")
    manager = _member_of(wg, "mgr@x.test")
    manager.is_superuser = True
    manager.save()
    from works.models import Work, WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="D", content_html="<p>x</p>")
    client.force_login(manager)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    draft.refresh_from_db()
    work = draft.published_work
    resp = client.post(reverse("works:delete", args=[work.slug]))
    assert resp.status_code == 302
    assert f"{wg.get_absolute_url()}?tab=work" in resp.url
    assert not Work.objects.filter(pk=work.pk).exists()
    draft.refresh_from_db()
    assert WorkDraft.objects.filter(pk=draft.pk).exists()
    assert draft.published_work_id is None


# ---- Committee terms (has_terms) ---------------------------------------


def test_committee_kind_default_enables_terms():
    from workgroups.models import build_workgroup
    committee = build_workgroup(Workgroup.Kind.COMMITTEE, name="Board X", slug="board-x")
    cartel = build_workgroup(Workgroup.Kind.CARTEL, name="Cartel X", slug="cartel-x")
    assert committee.has_terms is True
    assert cartel.has_terms is False


@pytest.mark.django_db
def test_set_member_term_model():
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Term WG", has_terms=True)
    u = _user("m@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2026, 1, 1),
    )
    # Valid: set a new start and an end.
    assert wg.set_member_term(
        u, start_date=datetime.date(2024, 9, 1), end_date=datetime.date(2026, 8, 31)
    ) is True
    m = wg.memberships.get(user=u)
    assert m.start_date == datetime.date(2024, 9, 1)
    assert m.end_date == datetime.date(2026, 8, 31)
    # Reject end before start.
    assert wg.set_member_term(
        u, start_date=datetime.date(2024, 9, 1), end_date=datetime.date(2024, 1, 1)
    ) is False


def test_roster_set_term_view(client):
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Term View WG",
             landing_visibility=Visibility.PUBLIC, has_terms=True)
    chair = _chair(wg)
    member = _user("member@x.test", role=Profile.Role.ANALYST)
    wg.add_member(member)
    client.force_login(chair)
    resp = client.post(
        reverse("workgroups:roster_set_term", args=[wg.slug]),
        {"user": member.pk, "start_date": "2024-09-01", "end_date": ""},
    )
    assert resp.status_code == 302
    m = wg.memberships.get(user=member, end_date__isnull=True)
    assert m.start_date == datetime.date(2024, 9, 1)


def test_roster_set_term_404_without_has_terms(client):
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="No Terms WG",
             landing_visibility=Visibility.PUBLIC, has_terms=False)
    chair = _chair(wg)
    client.force_login(chair)
    resp = client.post(
        reverse("workgroups:roster_set_term", args=[wg.slug]),
        {"user": chair.pk, "start_date": "2024-09-01"},
    )
    assert resp.status_code == 404


def test_publish_attributes_work_to_all_group_members(client):
    """A document published by a cartel is bylined with every member, not just
    the publisher (regression: two-person cartel showed one author)."""
    wg = _wg(name="Two Person", slug="two-person")
    pub = _member_of(wg, "pub@x.test")
    pub.is_superuser = True
    pub.save()
    pub.first_name, pub.last_name = "Pub", "Lisher"
    pub.save()
    other = _member_of(wg, "other@x.test")
    other.first_name, other.last_name = "Co", "Author"
    other.save()
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="Attest", content_html="<p>x</p>")
    client.force_login(pub)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    draft.refresh_from_db()
    work = draft.published_work
    author_ids = set(work.authorships.values_list("user_id", flat=True))
    assert author_ids == {pub.pk, other.pk}        # both members bylined


def test_publish_authors_exclude_personas(client):
    wg = _wg(name="With Persona", slug="with-persona")
    pub = _member_of(wg, "real@x.test")
    pub.is_superuser = True
    pub.save()
    persona = _member_of(wg, "persona@x.test")
    persona.profile.is_persona = True
    persona.profile.save()
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(workgroup=wg, title="Doc", content_html="<p>x</p>")
    client.force_login(pub)
    client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                {"visibility": "members"})
    draft.refresh_from_db()
    ids = set(draft.published_work.authorships.values_list("user_id", flat=True))
    assert ids == {pub.pk}                          # persona not credited


# ---- Serving membership (future-dated term ends) -----------------------


@pytest.mark.django_db
def test_future_term_end_still_serving():
    """A member whose term ends in the future is still an active member;
    a past end is not."""
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Serving WG", has_terms=True)
    future = _user("future@x.test", role=Profile.Role.ANALYST)
    past = _user("past@x.test", role=Profile.Role.ANALYST)
    today = datetime.date.today()
    WorkgroupMembership.objects.create(
        workgroup=wg, user=future, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2024, 1, 1),
        end_date=today + datetime.timedelta(days=400),
    )
    WorkgroupMembership.objects.create(
        workgroup=wg, user=past, role=WorkgroupMembership.Role.MEMBER,
        start_date=datetime.date(2020, 1, 1),
        end_date=today - datetime.timedelta(days=1),
    )
    assert wg.is_member(future) is True
    assert wg.is_member(past) is False
    member_ids = {m.user_id for m in wg.active_members()}
    assert future.pk in member_ids
    assert past.pk not in member_ids


@pytest.mark.django_db
def test_remove_member_takes_effect_today_not_tomorrow():
    """Removing a member (end_date=today) drops them from serving immediately —
    end_date is exclusive (end > today)."""
    wg = _wg(kind=Workgroup.Kind.WORKING_GROUP, name="Remove WG")
    chair = _chair(wg)
    m = _user("m@x.test", role=Profile.Role.ANALYST)
    wg.add_member(m)
    assert wg.is_member(m) is True
    assert wg.remove_member(m) is True
    assert wg.is_member(m) is False  # not "serving through today"
    # chair untouched
    assert wg.is_member(chair) is True


@pytest.mark.django_db
def test_set_member_term_future_end_editable_again():
    """A member with a future-dated end can still be found + edited (the lookup
    uses serving semantics, not end_date IS NULL)."""
    wg = _wg(kind=Workgroup.Kind.COMMITTEE, name="Edit WG", has_terms=True)
    u = _user("u@x.test", role=Profile.Role.ANALYST)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2024, 1, 1),
    )
    fut = datetime.date.today() + datetime.timedelta(days=300)
    assert wg.set_member_term(u, start_date=datetime.date(2024, 1, 1), end_date=fut) is True
    # Now they have a future end; we can still edit them (find via serving).
    later = datetime.date.today() + datetime.timedelta(days=600)
    assert wg.set_member_term(u, start_date=datetime.date(2024, 1, 1), end_date=later) is True
    assert wg.memberships.get(user=u).end_date == later


def test_create_file_draft_redirects_to_work_tab(client):
    from django.core.files.uploadedfile import SimpleUploadedFile
    wg = _wg(name="Filey", slug="filey")
    u = _member_of(wg)
    client.force_login(u)
    pdf = SimpleUploadedFile("paper.pdf", b"%PDF-1.4\n%data\n", content_type="application/pdf")
    resp = client.post(reverse("workgroups:draft_create", args=[wg.slug]),
                       {"title": "Static Paper", "file": pdf})
    from works.models import WorkDraft
    draft = WorkDraft.objects.get(workgroup=wg)
    assert draft.is_file
    assert not draft.is_native
    assert "tab=work" in resp.url          # not the editor


def test_publish_file_draft_attaches_pdf_no_body(client):
    from django.core.files.uploadedfile import SimpleUploadedFile
    wg = _wg(name="Filey", slug="filey")
    mgr = _member_of(wg, "mgr@x.test")
    mgr.is_superuser = True
    mgr.save()
    from works.models import Work, WorkDraft
    draft = WorkDraft.objects.create(
        workgroup=wg, title="Static Paper",
        file=SimpleUploadedFile("paper.pdf", b"%PDF-1.4\n%uploaded\n",
                                content_type="application/pdf"),
    )
    client.force_login(mgr)
    resp = client.post(reverse("workgroups:draft_publish", args=[wg.slug, draft.pk]),
                       {"visibility": "members"})
    assert resp.status_code == 302
    work = Work.objects.get(workgroup=wg, kind=Work.Kind.DOCUMENT)
    assert work.body_html == ""                          # static PDF, no web body
    pf = work.files.get(label="Published PDF")
    assert pf.file.read() == b"%PDF-1.4\n%uploaded\n"     # the uploaded bytes
    draft.refresh_from_db()
    assert draft.published_work_id == work.pk
    assert work.authorships.filter(user=mgr).exists()    # bylined to members


def test_work_tab_renders_file_draft_row(client):
    from django.core.files.uploadedfile import SimpleUploadedFile
    wg = _wg(name="Filey", slug="filey", has_works=True,
             content_visibility=Visibility.MEMBERS)
    u = _member_of(wg)
    from works.models import WorkDraft
    WorkDraft.objects.create(
        workgroup=wg, title="Static Paper",
        file=SimpleUploadedFile("paper.pdf", b"%PDF-1.4\n", content_type="application/pdf"),
    )
    client.force_login(u)
    resp = client.get(f"{wg.get_absolute_url()}?tab=work")
    assert resp.status_code == 200
    assert b"Static Paper" in resp.content
    assert b"Upload a PDF" in resp.content       # the new create option
    assert b"PDF \xe2\x86\x97" in resp.content   # "PDF ↗" badge


def test_draft_file_download_gated_by_membership(client):
    from django.core.files.uploadedfile import SimpleUploadedFile
    wg = _wg(name="Filey", slug="filey")
    member = _member_of(wg, "m@x.test")
    outsider = _user("out@x.test")
    from works.models import WorkDraft
    draft = WorkDraft.objects.create(
        workgroup=wg, title="Static",
        file=SimpleUploadedFile("p.pdf", b"%PDF-1.4\nbytes\n", content_type="application/pdf"),
    )
    url = reverse("workgroups:draft_file", args=[wg.slug, draft.pk])
    # member: streams the bytes
    client.force_login(member)
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content) == b"%PDF-1.4\nbytes\n"
    # outsider: 404 (not a member)
    client.force_login(outsider)
    assert client.get(url).status_code == 404


def test_private_storage_used_for_gated_fields():
    """Gated FileFields resolve to the private storage (local fallback in dev)."""
    from core.storage import private_storage
    from documents.models import Document
    from works.models import WorkDraft, WorkFile
    expected = type(private_storage())
    assert isinstance(WorkFile._meta.get_field("file").storage, expected)
    assert isinstance(WorkDraft._meta.get_field("file").storage, expected)
    assert isinstance(Document._meta.get_field("file").storage, expected)


# ---- Shared files (Files tab) ------------------------------------------

def _pdf_upload(name="f.pdf", size=1000):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, b"x" * size, content_type="application/pdf")


def test_file_upload_creates_versioned_file(client):
    wg = _wg(name="Files WG", slug="files-wg", has_files=True)
    u = _member_of(wg)
    client.force_login(u)
    resp = client.post(reverse("workgroups:file_upload", args=[wg.slug]),
                       {"name": "Budget", "file": _pdf_upload(size=2048)})
    assert resp.status_code == 302
    from workgroups.models import WorkgroupFile
    wf = WorkgroupFile.objects.get(workgroup=wg)
    assert wf.name == "Budget"
    assert wf.version_count == 1
    assert wf.size == 2048
    assert wg.files_used_bytes() == 2048


def test_file_new_version_increments_and_counts_quota(client):
    wg = _wg(name="Files WG", slug="files-wg", has_files=True)
    u = _member_of(wg)
    from workgroups.models import WorkgroupFile
    wf = WorkgroupFile.objects.create(workgroup=wg, name="Doc", created_by=u)
    wf.add_version(blob=_pdf_upload(size=1000), original_name="a.pdf", size=1000, user=u)
    client.force_login(u)
    client.post(reverse("workgroups:file_version_add", args=[wg.slug, wf.pk]),
                {"file": _pdf_upload(size=3000)})
    wf.refresh_from_db()
    assert wf.version_count == 2
    assert wf.current_version().number == 2
    assert wf.size == 3000                      # current = latest
    assert wg.files_used_bytes() == 4000        # both versions count


def test_file_upload_rejects_oversize(client):
    from workgroups.models import MAX_WORKGROUP_FILE_BYTES, WorkgroupFile
    wg = _wg(name="Files WG", slug="files-wg", has_files=True)
    u = _member_of(wg)
    client.force_login(u)
    client.post(reverse("workgroups:file_upload", args=[wg.slug]),
                {"file": _pdf_upload(size=MAX_WORKGROUP_FILE_BYTES + 1)})
    assert not WorkgroupFile.objects.filter(workgroup=wg).exists()


def test_file_upload_rejects_over_quota(client):
    from workgroups.models import WorkgroupFile
    wg = _wg(name="Files WG", slug="files-wg", has_files=True, file_quota_bytes=5000)
    u = _member_of(wg)
    wf = WorkgroupFile.objects.create(workgroup=wg, name="Big", created_by=u)
    wf.add_version(blob=_pdf_upload(size=4000), original_name="a.pdf", size=4000, user=u)
    client.force_login(u)
    client.post(reverse("workgroups:file_upload", args=[wg.slug]),
                {"file": _pdf_upload(size=2000)})       # 4000+2000 > 5000
    assert WorkgroupFile.objects.filter(workgroup=wg).count() == 1   # not added


def test_file_download_gated_and_streams(client):
    from workgroups.models import WorkgroupFile
    wg = _wg(name="Files WG", slug="files-wg", has_files=True,
             content_visibility=Visibility.PRIVATE)
    member = _member_of(wg, "m@x.test")
    outsider = _user("out@x.test")
    wf = WorkgroupFile.objects.create(workgroup=wg, name="Doc", created_by=member)
    wf.add_version(blob=_pdf_upload(size=12), original_name="a.pdf", size=12, user=member)
    url = reverse("workgroups:file_download", args=[wg.slug, wf.pk])
    client.force_login(member)
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content) == b"x" * 12
    client.force_login(outsider)
    assert client.get(url).status_code == 404


def test_file_delete_by_creator_reclaims_quota(client):
    from workgroups.models import WorkgroupFile
    wg = _wg(name="Files WG", slug="files-wg", has_files=True)
    u = _member_of(wg)
    wf = WorkgroupFile.objects.create(workgroup=wg, name="Doc", created_by=u)
    wf.add_version(blob=_pdf_upload(size=5000), original_name="a.pdf", size=5000, user=u)
    assert wg.files_used_bytes() == 5000
    client.force_login(u)
    client.post(reverse("workgroups:file_delete", args=[wg.slug, wf.pk]))
    assert not WorkgroupFile.objects.filter(pk=wf.pk).exists()
    assert wg.files_used_bytes() == 0


def test_files_tab_renders_with_quota(client):
    wg = _wg(name="Files WG", slug="files-wg", has_files=True,
             content_visibility=Visibility.MEMBERS)
    u = _member_of(wg)
    from workgroups.models import WorkgroupFile
    wf = WorkgroupFile.objects.create(workgroup=wg, name="Shared Notes", created_by=u)
    wf.add_version(blob=_pdf_upload(size=1024), original_name="a.pdf", size=1024, user=u)
    client.force_login(u)
    resp = client.get(f"{wg.get_absolute_url()}?tab=files")
    assert resp.status_code == 200
    assert b"Shared Notes" in resp.content
    assert b"Upload a file" in resp.content
    assert b"the web coordinator" in resp.content


def test_deleting_version_removes_blob_from_storage(client):
    from workgroups.models import WorkgroupFile
    wg = _wg(name="Files WG", slug="files-wg", has_files=True)
    u = _member_of(wg)
    wf = WorkgroupFile.objects.create(workgroup=wg, name="Doc", created_by=u)
    v = wf.add_version(blob=_pdf_upload(size=100), original_name="a.pdf", size=100, user=u)
    storage, name = v.blob.storage, v.blob.name
    assert storage.exists(name)
    wf.delete()                                 # cascade → version → post_delete
    assert not storage.exists(name)             # blob cleaned up, no orphan


# ---- Decisions register (Decisions tab) --------------------------------

def _chair_of(wg, email="chair@x.test"):
    u = _user(email)
    WorkgroupMembership.objects.create(
        workgroup=wg, user=u, role=WorkgroupMembership.Role.CHAIR,
        start_date=datetime.date(2000, 1, 1),
    )
    return u


def test_decision_leaderless_any_member_can_register():
    from workgroups.permissions import can_register_decision, workgroup_has_leads
    wg = _wg(name="Cartel D", slug="cartel-d", has_decisions=True)        # cartel, members only
    m = _member_of(wg, "m@x.test")
    assert workgroup_has_leads(wg) is False
    assert can_register_decision(m, wg) is True


def test_decision_leaderled_only_leads_register():
    from workgroups.permissions import can_register_decision, workgroup_has_leads
    wg = _wg(name="Cmte D", slug="cmte-d", kind=Workgroup.Kind.COMMITTEE, has_decisions=True)
    chair = _chair_of(wg)
    plain = _member_of(wg, "plain@x.test")
    assert workgroup_has_leads(wg) is True
    assert can_register_decision(chair, wg) is True
    assert can_register_decision(plain, wg) is False    # member, not a lead


def test_decision_add_links_meeting_and_records_author(client):
    from workgroups.models import WorkgroupDecision, WorkgroupMeeting
    wg = _wg(name="Cartel D", slug="cartel-d", has_decisions=True)
    m = _member_of(wg, "m@x.test")
    mt = WorkgroupMeeting.objects.create(
        workgroup=wg,
        starts_at=datetime.datetime(2026, 3, 1, 18, 0, tzinfo=datetime.timezone.utc),
    )
    client.force_login(m)
    resp = client.post(reverse("workgroups:decision_add", args=[wg.slug]), {
        "title": "Adopt the budget", "status": "adopted",
        "decided_on": "2026-03-01", "meeting": mt.pk, "detail": "**ratified**",
    })
    assert resp.status_code == 302
    d = WorkgroupDecision.objects.get(workgroup=wg)
    assert d.title == "Adopt the budget"
    assert d.meeting_id == mt.pk and d.status == "adopted" and d.created_by == m


def test_decision_add_blocked_for_non_lead_in_led_group(client):
    from workgroups.models import WorkgroupDecision
    wg = _wg(name="Cmte D", slug="cmte-d", kind=Workgroup.Kind.COMMITTEE, has_decisions=True)
    _chair_of(wg)
    plain = _member_of(wg, "plain@x.test")
    client.force_login(plain)
    resp = client.post(reverse("workgroups:decision_add", args=[wg.slug]),
                       {"title": "Nope"})
    assert resp.status_code == 404
    assert not WorkgroupDecision.objects.filter(workgroup=wg).exists()


def test_decision_edit_delete_restricted_to_creator_or_manager(client):
    from workgroups.models import WorkgroupDecision
    wg = _wg(name="Cartel D", slug="cartel-d", has_decisions=True)
    creator = _member_of(wg, "c@x.test")
    other = _member_of(wg, "o@x.test")
    d = WorkgroupDecision.objects.create(workgroup=wg, title="X", created_by=creator)
    # another member (can register, but not this decision's author/manager): 404
    client.force_login(other)
    assert client.post(
        reverse("workgroups:decision_delete", args=[wg.slug, d.pk])).status_code == 404
    # creator edits + deletes
    client.force_login(creator)
    client.post(reverse("workgroups:decision_edit", args=[wg.slug, d.pk]),
                {"title": "Y", "status": "tabled"})
    d.refresh_from_db()
    assert d.title == "Y" and d.status == "tabled"
    client.post(reverse("workgroups:decision_delete", args=[wg.slug, d.pk]))
    assert not WorkgroupDecision.objects.filter(pk=d.pk).exists()


def test_decisions_tab_renders(client):
    from workgroups.models import WorkgroupDecision
    wg = _wg(name="Cartel D", slug="cartel-d", has_decisions=True,
             content_visibility=Visibility.MEMBERS)
    m = _member_of(wg, "m@x.test")
    WorkgroupDecision.objects.create(workgroup=wg, title="Adopt the charter",
                                     created_by=m, status="adopted")
    client.force_login(m)
    resp = client.get(f"{wg.get_absolute_url()}?tab=decisions")
    assert resp.status_code == 200
    assert b"Adopt the charter" in resp.content
    assert b"Record a decision" in resp.content


# ---- Minutes (meeting record) tab --------------------------------------

def test_minutes_tab_shows_record_and_decisions(client):
    from workgroups.models import WorkgroupDecision, WorkgroupMeeting
    wg = _wg(name="Cmte M", slug="cmte-m", kind=Workgroup.Kind.COMMITTEE,
             has_minutes=True, has_decisions=True,
             content_visibility=Visibility.MEMBERS)
    m = _member_of(wg, "m@x.test")
    past = WorkgroupMeeting.objects.create(
        workgroup=wg, title="March meeting",
        starts_at=datetime.datetime(2020, 3, 1, 18, 0, tzinfo=datetime.timezone.utc),
        minutes="Discussed the budget.")
    WorkgroupDecision.objects.create(workgroup=wg, title="Adopt the budget",
                                     meeting=past, status="adopted", created_by=m)
    WorkgroupMeeting.objects.create(            # future, no minutes → excluded
        workgroup=wg, title="Future planning",
        starts_at=datetime.datetime(2099, 1, 1, 18, 0, tzinfo=datetime.timezone.utc))
    client.force_login(m)
    resp = client.get(f"{wg.get_absolute_url()}?tab=minutes")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "March meeting" in body
    assert "Discussed the budget." in body
    assert "Adopt the budget" in body          # the decision that came out of it
    assert "Future planning" not in body       # upcoming with no minutes


def test_minutes_save_returns_to_minutes_tab(client):
    from workgroups.models import WorkgroupMeeting
    wg = _wg(name="Cmte M", slug="cmte-m", kind=Workgroup.Kind.COMMITTEE,
             has_minutes=True)
    lead = _chair_of(wg)                        # a chair can schedule/record
    mt = WorkgroupMeeting.objects.create(
        workgroup=wg,
        starts_at=datetime.datetime(2020, 3, 1, 18, 0, tzinfo=datetime.timezone.utc))
    client.force_login(lead)
    resp = client.post(reverse("workgroups:meeting_minutes", args=[wg.slug, mt.pk]),
                       {"minutes": "Recorded here.", "tab": "minutes"})
    assert resp.status_code == 302
    assert "tab=minutes" in resp.url            # returns to the record, not Schedule
    mt.refresh_from_db()
    assert mt.minutes == "Recorded here."
