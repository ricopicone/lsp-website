"""The Scholarly Seminar Series has a coordinator and a page (task #851).

The coordinator proposes the series' talks through the usual Program Committee
queue, and hosts them: the same rights a presenter has on their own event.
"""

from __future__ import annotations

import datetime as dt
import io

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

def test_the_series_page_lists_its_talks(client):
    _event(title="Coming Talk", slug="coming-talk")
    _event(title="Ended Talk", slug="ended-talk", days=-30)
    _event(Event.Type.SPECIAL_EVENT, title="Not The Series", slug="not-series")
    page = client.get(reverse("events:scholarly_series")).content.decode()
    assert "<s>Scholarly</s> Seminar Series" in page
    assert "&lt;s&gt;" not in page  # the heading's strike isn't escaped
    assert "Coming Talk" in page and "Ended Talk" in page
    assert "Not The Series" not in page
    assert page.index("Coming Talk") < page.index("Ended Talk")
    assert reverse("events:detail", args=["ended-talk"]) in page


# --- The talks before the site -----------------------------------------------

def _import(**opts):
    from django.core.management import call_command

    call_command("import_scholarly_series_history", stdout=io.StringIO(), **opts)


def _dream():
    return Event.objects.get(title="The Perpetual Writing of the Dream")


def test_the_import_makes_the_earlier_talks_events():
    _import()
    talks = Event.objects.filter(event_type=Event.Type.SCHOLARLY_SEMINAR)
    assert talks.count() == 7
    dream = _dream()
    assert dream.start_date == dream.end_date == dt.date(2026, 3, 7)
    assert dream.published and dream.status == Event.Status.CLOSED
    assert dream.visibility == Event.Visibility.PUBLIC


def test_the_import_links_a_member_presenter(client):
    diana = _member("diana@x.test", "Diana", "Cuello")
    _import()
    dream = _dream()
    assert list(dream.member_speakers.all()) == [diana]
    assert not dream.speakers.exists()


def test_without_the_member_the_presenter_is_named():
    _import()
    assert [s.name for s in _dream().speakers.all()] == ["Diana Cuello"]


def test_the_import_runs_once_and_keeps_later_edits():
    _import()
    dream = _dream()
    dream.description = "An abstract Sheila added."
    dream.save(update_fields=["description"])
    _import()
    assert Event.objects.filter(event_type=Event.Type.SCHOLARLY_SEMINAR).count() == 7
    assert _dream().description == "An abstract Sheila added."


def test_a_dry_run_writes_nothing():
    _import(dry_run=True)
    assert not Event.objects.filter(event_type=Event.Type.SCHOLARLY_SEMINAR).exists()


def test_the_earlier_talks_are_listed_as_events(client):
    _import()
    dream = _dream()
    detail = reverse("events:detail", args=[dream.slug])
    assert client.get(detail).status_code == 200
    series = client.get(reverse("events:scholarly_series")).content.decode()
    assert f'href="{detail}"' in series
    assert "Femininity and the Spirit of Decision" in series
    assert detail in client.get(reverse("events:past")).content.decode()


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


def test_the_coordinator_introduces_the_description_with_their_bio(client, coordinator):
    coordinator.profile.bio = "Practice bio."
    coordinator.profile.event_bio = "Professor of sociology."
    coordinator.profile.save()
    page = client.get(reverse("events:scholarly_series")).content.decode()
    assert (
        "A word from the Scholarly Seminar Series Coordinator Sheila Coordinator"
        in page
    )
    # The event bio, as on an event page, not the practice bio.
    assert "Professor of sociology." in page
    assert "Practice bio." not in page
    # Proposals are sent to the coordinator by way of their profile.
    profile = reverse("directory_detail", args=["sheila-coordinator"])
    assert f'href="{profile}"' in page
    assert "mailto:sheila@x.test" not in page


def test_with_no_coordinator_the_page_names_no_one(client):
    page = client.get(reverse("events:scholarly_series")).content.decode()
    assert "A word from" not in page
    assert "the Program Committee" in page


# --- The coordinator's admin -------------------------------------------------

def test_the_admin_is_the_coordinators(client, coordinator):
    url = reverse("scholarly_series_admin")
    assert client.get(url).status_code == 302  # anonymous → sign in
    client.force_login(_member("plain@x.test"))
    assert client.get(url).status_code == 403
    client.force_login(coordinator)
    assert client.get(url).status_code == 200


def test_the_admin_hub_lists_the_coordinators_admin(client, coordinator):
    client.force_login(coordinator)
    page = client.get(reverse("admin_tools")).content.decode()
    assert reverse("scholarly_series_admin") in page


def test_the_admin_lists_talks_with_their_recordings(client, coordinator):
    from video.models import Recording

    talk = _event(title="Recorded Talk", slug="recorded-talk", days=-5)
    rec = Recording.objects.create(
        event=talk, daily_recording_id="r1", status=Recording.Status.READY,
        listing_visibility=Recording.Visibility.MEMBERS,
        content_visibility=Recording.Visibility.MEMBERS,
    )
    _event(Event.Type.SPECIAL_EVENT, title="Not The Series", slug="not-series")
    client.force_login(coordinator)
    page = client.get(reverse("scholarly_series_admin")).content.decode()
    assert "Recorded Talk" in page
    assert "Not The Series" not in page
    assert reverse("video:recording_play", args=[rec.pk]) in page


def test_the_coordinator_turns_recording_on_and_off(client, coordinator):
    talk = _event(online_venue=Event.OnlineVenue.INSITE, format=Event.Format.ONLINE)
    url = reverse("scholarly_series_record", args=[talk.slug])
    client.force_login(coordinator)
    assert client.post(url, {"record": "on"}).status_code == 302
    talk.refresh_from_db()
    assert talk.record_video
    client.post(url, {"record": "off"})
    talk.refresh_from_db()
    assert not talk.record_video


def test_the_record_switch_is_only_for_series_talks(client, coordinator):
    other = _event(Event.Type.SPECIAL_EVENT, title="Other", slug="other")
    client.force_login(coordinator)
    resp = client.post(
        reverse("scholarly_series_record", args=[other.slug]), {"record": "on"},
    )
    assert resp.status_code == 404
    other.refresh_from_db()
    assert not other.record_video


# --- Uploading a recording made elsewhere ------------------------------------

@pytest.fixture
def private_media(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path)


def _upload_form(**extra):
    from django.core.files.uploadedfile import SimpleUploadedFile

    data = {
        "video": SimpleUploadedFile("zoom.mp4", b"\0" * 32, content_type="video/mp4"),
        "recorded_on": "2026-10-01", "visibility": "members", "consent": "on",
    }
    data.update(extra)
    return {k: v for k, v in data.items() if v is not None}


def test_the_coordinator_uploads_a_talks_recording(client, coordinator, private_media):
    from video.models import Recording

    talk = _event(title="Zoom Talk", slug="zoom-talk", days=-3)
    client.force_login(coordinator)
    url = reverse("scholarly_series_upload", args=[talk.slug])
    assert client.get(url).status_code == 200
    resp = client.post(url, _upload_form())
    rec = Recording.objects.get(event=talk)
    assert resp.status_code == 302
    assert resp["Location"] == reverse("video:recording_play", args=[rec.pk])
    assert rec.source == Recording.Source.UPLOAD and rec.started_by == coordinator
    # Listed where any recording of the talk is.
    client.force_login(_member("watcher@x.test"))
    series = client.get(reverse("events:scholarly_series")).content.decode()
    assert "Recording</a>" in series
    detail = client.get(reverse("events:detail", args=[talk.slug])).content.decode()
    assert reverse("video:recording_play", args=[rec.pk]) in detail


def test_an_upload_needs_the_presenters_agreement(client, coordinator, private_media):
    from video.models import Recording

    talk = _event(days=-3)
    client.force_login(coordinator)
    resp = client.post(
        reverse("scholarly_series_upload", args=[talk.slug]), _upload_form(consent=None),
    )
    assert resp.status_code == 200
    assert not Recording.objects.exists()


def test_a_direct_upload_attaches_by_its_key(client, coordinator, monkeypatch):
    import core.storage as storage
    from video.models import Recording

    monkeypatch.setattr(storage, "head_private_object",
                        lambda key: {"size": 10, "content_type": "video/mp4"})
    talk = _event(days=-3)
    key = f"recordings/uploads/{talk.pk}/abc.mp4"
    client.force_login(coordinator)
    client.post(reverse("scholarly_series_upload", args=[talk.slug]),
                _upload_form(video=None, video_key=key))
    assert Recording.objects.get(event=talk).s3_key == key


def test_only_the_coordinator_uploads(client, private_media):
    talk = _event(days=-3)
    client.force_login(_member("plain@x.test"))
    url = reverse("scholarly_series_upload", args=[talk.slug])
    assert client.get(url).status_code == 403
    assert client.post(url, _upload_form()).status_code == 403


def test_a_talk_still_to_come_takes_no_upload(client, coordinator, private_media):
    from video.models import Recording

    talk = _event(days=5)
    client.force_login(coordinator)
    resp = client.post(reverse("scholarly_series_upload", args=[talk.slug]), _upload_form())
    assert resp.status_code == 302
    assert resp["Location"] == reverse("scholarly_series_admin")
    assert not Recording.objects.exists()


def test_without_a_bucket_the_browser_posts_the_file(client, coordinator):
    import json

    talk = _event(days=-3)
    client.force_login(coordinator)
    resp = client.post(
        reverse("scholarly_series_upload_presign", args=[talk.slug]),
        data=json.dumps({"filename": "zoom.mp4", "content_type": "video/mp4"}),
        content_type="application/json",
    )
    assert resp.json() == {"fallback": True}


def test_the_admin_offers_an_upload_once_a_talk_has_happened(client, coordinator):
    given = _event(title="Given", slug="given", days=-3)
    coming = _event(title="Coming", slug="coming", days=5)
    client.force_login(coordinator)
    page = client.get(reverse("scholarly_series_admin")).content.decode()
    assert reverse("scholarly_series_upload", args=[given.slug]) in page
    assert reverse("scholarly_series_upload", args=[coming.slug]) not in page
