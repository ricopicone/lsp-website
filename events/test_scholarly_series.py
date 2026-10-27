"""The Scholarly Seminar Series has a coordinator and a page (task #851).

The coordinator proposes the series' talks through the usual Program Committee
queue, and hosts them: the same rights a presenter has on their own event.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from events.models import Event, EventProposal

pytestmark = pytest.mark.django_db

_SUBMIT = {
    "action": "submit", "location_kind": "online_insite", "fee_type": "free",
    "speakers-TOTAL_FORMS": "0", "speakers-INITIAL_FORMS": "0",
    "speakers-MIN_NUM_FORMS": "0", "speakers-MAX_NUM_FORMS": "1000",
}


def _member(email, first="Mem", last="Ber"):
    u = User.objects.create_user(
        email=email, password="x", first_name=first, last_name=last,
    )
    u.profile.role = Profile.Role.ANALYST
    u.profile.save()
    return u


@pytest.fixture
def coordinator():
    u = _member("sheila@x.test", "Sheila", "Coordinator")
    StaffRole.objects.get(key=StaffRole.SCHOLARLY_SEMINAR_COORDINATOR).holders.add(u)
    return u


def _event(event_type=Event.Type.SCHOLARLY_SEMINAR, days=10, **extra):
    day = dt.date.today() + dt.timedelta(days=days)
    return Event.objects.create(
        title=extra.pop("title", "A Talk"), slug=extra.pop("slug", "a-talk"),
        event_type=event_type, start_date=day, end_date=day, published=True,
        **extra,
    )


# --- The role ----------------------------------------------------------------

def test_the_coordinator_role_is_seeded():
    role = StaffRole.objects.get(key=StaffRole.SCHOLARLY_SEMINAR_COORDINATOR)
    assert role.name == "Scholarly Seminar Series Coordinator"


def test_the_coordinator_hosts_series_events_and_only_those(coordinator):
    from events.permissions import can_edit_event
    from video.services import is_owner

    talk = _event()
    other = _event(Event.Type.SPECIAL_EVENT, title="Other", slug="other")
    assert can_edit_event(coordinator, talk)
    assert is_owner(talk, coordinator)  # moderator in the room, Record button
    assert not can_edit_event(coordinator, other)
    assert not can_edit_event(_member("plain@x.test"), talk)


def test_the_coordinator_is_badged_in_the_directory(client, coordinator):
    detail = client.get("/directory/sheila-coordinator/").content
    assert b"Scholarly Seminar Series Coordinator" in detail


# --- Proposing a talk --------------------------------------------------------

def test_only_the_coordinator_is_offered_the_series_type(client, coordinator):
    client.force_login(_member("plain@x.test"))
    assert b'value="scholarly_seminar"' not in client.get("/propose/").content
    client.force_login(coordinator)
    assert b'value="scholarly_seminar"' in client.get("/propose/").content


def test_the_propose_link_can_preselect_the_series(client, coordinator):
    client.force_login(coordinator)
    page = client.get("/propose/?type=scholarly_seminar").content.decode()
    assert '<option value="scholarly_seminar" selected>' in page


def test_a_coordinator_proposal_goes_to_the_pc_queue(client, coordinator):
    client.force_login(coordinator)
    resp = client.post("/propose/", {
        **_SUBMIT, "event_type": Event.Type.SCHOLARLY_SEMINAR,
        "title": "A Paper in Progress", "description": "An abstract.",
        "proposed_datetime": "2030-11-05T11:00",
    })
    assert resp.status_code == 302
    p = EventProposal.objects.get(title="A Paper in Progress")
    assert p.status == EventProposal.Status.PROPOSED
    assert p.minted_event is None  # nothing on the site until the PC approves


def test_a_non_coordinator_cannot_post_the_series_type(client):
    client.force_login(_member("plain@x.test"))
    resp = client.post("/propose/", {
        **_SUBMIT, "event_type": Event.Type.SCHOLARLY_SEMINAR,
        "title": "Sneaky Talk", "description": "x",
        "proposed_datetime": "2030-11-05T11:00",
    })
    assert resp.status_code == 200  # invalid choice → re-render
    assert not EventProposal.objects.filter(title="Sneaky Talk").exists()


def test_approval_publishes_the_talk_without_making_the_coordinator_a_speaker(
    coordinator,
):
    presenter = _member("presenter@x.test", "Pre", "Senter")
    p = EventProposal.objects.create(
        proposed_by=coordinator, event_type=Event.Type.SCHOLARLY_SEMINAR,
        title="Approved Talk", description="x", status=EventProposal.Status.PROPOSED,
        proposed_datetime=dt.datetime(2030, 11, 5, 19, tzinfo=dt.timezone.utc),
    )
    p.faculty.add(presenter)
    event = p.approve(_member("pc@x.test"))
    assert event.event_type == Event.Type.SCHOLARLY_SEMINAR
    assert event.published
    assert list(event.member_speakers.all()) == [presenter]


def test_an_approved_talk_routes_content_edits_through_review(coordinator):
    p = EventProposal.objects.create(
        proposed_by=coordinator, event_type=Event.Type.SCHOLARLY_SEMINAR,
        title="Reviewed Talk", description="x", status=EventProposal.Status.PROPOSED,
        proposed_datetime=dt.datetime(2030, 11, 5, 19, tzinfo=dt.timezone.utc),
    )
    event = p.approve(_member("pc@x.test"))
    assert event.requires_change_review()


# --- The series page ---------------------------------------------------------

def test_the_series_page_lists_its_talks_and_history(client):
    _event(title="Coming Talk", slug="coming-talk")
    _event(title="Ended Talk", slug="ended-talk", days=-30)
    _event(Event.Type.SPECIAL_EVENT, title="Not The Series", slug="not-series")
    page = client.get(reverse("events:scholarly_series")).content.decode()
    assert "<s>Scholarly</s> Seminar Series" in page
    assert "&lt;s&gt;" not in page  # the heading's strike isn't escaped
    assert "Coming Talk" in page and "Ended Talk" in page
    assert "Not The Series" not in page
    # Talks given before the site existed.
    assert "The Perpetual Writing of the Dream" in page
    assert page.index("Coming Talk") < page.index("Ended Talk")


def test_the_series_page_hides_members_only_talks_from_visitors(client):
    _event(title="Members Talk", slug="members-talk",
           visibility=Event.Visibility.MEMBERS_ONLY)
    assert "Members Talk" not in client.get(
        reverse("events:scholarly_series")
    ).content.decode()


def test_the_coordinator_gets_a_propose_link_on_the_series_page(client, coordinator):
    url = reverse("events:scholarly_series")
    propose = reverse("propose_event") + "?type=scholarly_seminar"
    client.force_login(_member("plain@x.test"))
    assert propose not in client.get(url).content.decode()
    client.force_login(coordinator)
    assert propose in client.get(url).content.decode()


def test_a_series_event_page_links_the_series(client):
    talk = _event()
    page = client.get(reverse("events:detail", args=[talk.slug])).content.decode()
    assert reverse("events:scholarly_series") in page
