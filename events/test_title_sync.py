"""An offering's title is the one name; its workgroup follows it (task #568).

``ensure_workgroup`` snapshots ``Event.title`` into ``Workgroup.name`` at
creation, and nothing used to re-sync it. Because a seminar's event page
*redirects* to its Workspace, the stale copy was the page faculty actually
looked at — so an edited title read as an edit that hadn't held, while the
program listing (which renders ``Event.title``) showed the new one.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from committees.models import Committee
from events.models import Event
from workgroups.models import Workgroup

pytestmark = pytest.mark.django_db


def _seminar(title="Beyond Principle; or Put A Socket In It", slug="beyond", **kw):
    kw.setdefault("start_date", date(2026, 9, 1))
    kw.setdefault("end_date", date(2027, 5, 1))
    kw.setdefault("event_type", Event.Type.SEMINAR)
    return Event.objects.create(title=title, slug=slug, **kw)


def test_editing_the_title_renames_the_offering_workgroup():
    event = _seminar()
    wg = event.ensure_workgroup()
    assert wg.name == "Beyond Principle; or Put A Socket In It"

    event.title = "Beyond Principle; or, Put A Socket In It"
    event.save()

    wg.refresh_from_db()
    assert wg.name == "Beyond Principle; or, Put A Socket In It"


def test_rename_survives_a_targeted_update_fields_save():
    """The faculty edit form and EventChangeRequest.apply() both save with
    ``update_fields``; a title written that way must still cascade."""
    event = _seminar()
    wg = event.ensure_workgroup()

    event.title = "A Wholly New Title"
    event.save(update_fields=["title"])

    wg.refresh_from_db()
    assert wg.name == "A Wholly New Title"


def test_workgroup_slug_is_untouched_by_a_rename():
    """The slug is the URL — a retitled seminar keeps its Workspace address."""
    event = _seminar()
    wg = event.ensure_workgroup()
    slug = wg.slug

    event.title = "Renamed Entirely"
    event.save()

    wg.refresh_from_db()
    assert wg.slug == slug


def test_a_long_title_is_truncated_to_the_name_field():
    event = _seminar()
    wg = event.ensure_workgroup()

    event.title = "T" * 200
    event.save()

    wg.refresh_from_db()
    assert wg.name == "T" * 120


def test_a_title_edit_reaches_the_parletre_channels():
    """The whole chain, which is the bug as it was reported: the seminar page
    (the Workspace) and the Parlêtre sidebar both showed the pre-edit title
    while the program listing showed the new one."""
    from parletre.models import Channel

    event = _seminar()
    event.ensure_workgroup()

    event.title = "Beyond Principle; or, Put A Socket In It"
    event.save(update_fields=["title"])

    names = dict(event.workgroup.channels.values_list("kind", "name"))
    assert names[Channel.Kind.FORUM] == "Beyond Principle; or, Put A Socket In It"
    assert names[Channel.Kind.CHAT] == "Beyond Principle; or, Put A Socket In It chat"
    assert names[Channel.Kind.VIDEO] == "Beyond Principle; or, Put A Socket In It video"


def test_a_pc_owned_event_never_renames_the_committee_workgroup():
    """Special events share the Programming Committee's workgroup — renaming
    that to an event title would retitle the committee itself."""
    pc = Committee.objects.get(slug="programming-committee")
    pc_wg = pc.workgroup or Workgroup.objects.create(
        kind=Workgroup.Kind.COMMITTEE, name=pc.name
    )
    if pc.workgroup_id is None:
        pc.workgroup = pc_wg
        pc.save(update_fields=["workgroup"])
    original_name = pc_wg.name
    event = _seminar(
        title="Working with Masochism", slug="masochism",
        event_type=Event.Type.SPECIAL_EVENT,
    )
    assert event.ensure_workgroup() == pc_wg

    event.title = "Working with Masochism, Revisited"
    event.save()

    pc_wg.refresh_from_db()
    assert pc_wg.name == original_name


def test_editing_a_past_term_does_not_rename_a_continuing_seminar():
    """An offering workgroup can carry several years' events. The Workspace
    features the current term, so the name follows *that* one."""
    past = _seminar(title="Old Term", slug="old-term",
                    start_date=date(2024, 9, 1), end_date=date(2025, 5, 1))
    wg = past.ensure_workgroup()
    current = _seminar(
        title="Current Term", slug="current-term",
        start_date=date.today(), end_date=date.today() + timedelta(days=90),
        workgroup=wg,
    )
    assert wg.primary_event() == current
    wg.refresh_from_db()
    assert wg.name == "Current Term"

    past.title = "Old Term, Retitled"
    past.save()

    wg.refresh_from_db()
    assert wg.name == "Current Term"
