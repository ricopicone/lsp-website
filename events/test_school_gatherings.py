"""Days of Assembly and Working Days are the School's own gatherings (task #756,
John K's Sept 28 requests): every member joins without registering, the
forms ask only for what a gathering needs, and the calendar marks them out."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from committees.models import Committee
from events.models import Audience, Event, PriceTier, Session

pytestmark = pytest.mark.django_db


def _member(email="m@x.test", role=Profile.Role.ANALYST):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _pc_member(email="pc@x.test"):
    u = _member(email)
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee", defaults={"name": "Program Committee"},
    )
    committee.add_member(u, start_date=date(2026, 1, 1))
    return u


def _gathering(etype=Event.Type.DAY_OF_ASSEMBLY, slug="doa", **kw):
    e = Event.objects.create(
        title="Virtual Days of Assembly", slug=slug, event_type=etype,
        start_date=date(2030, 11, 14), end_date=date(2030, 11, 15),
        published=True, status=Event.Status.OPEN,
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY,
        **kw,
    )
    start = datetime(2030, 11, 14, 17, 0, tzinfo=dt_timezone.utc)
    Session.objects.create(
        event=e, start_at=start, end_at=start + timedelta(hours=8), sequence=1,
    )
    return e


# --- Who is admitted -------------------------------------------------------


def test_every_member_is_admitted_to_a_gathering_without_registering():
    e = _gathering()
    assert e.is_school_gathering
    assert e.admits_member(_member()) is True
    assert e.admits_member(_member("st@x.test", Profile.Role.STUDENT)) is False


def test_a_special_event_still_needs_a_registration():
    e = _gathering(etype=Event.Type.SPECIAL_EVENT, slug="talk")
    assert e.is_school_gathering is False
    assert e.admits_member(_member()) is False


def test_room_entry_admits_members_to_a_gathering():
    from video.services import can_enter_event

    e = _gathering()
    assert can_enter_event(e, _member()) is True
    assert can_enter_event(e, _member("g@x.test", Profile.Role.EXTERNAL)) is False


def test_event_page_offers_members_the_room_and_no_register_button(client):
    e = _gathering()
    client.force_login(_member())
    body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert "Open to all members" in body
    assert "no registration needed" in body
    assert 'id="register-cta"' not in body
    assert "Register for details" not in body


def test_event_page_shows_members_the_external_link(client):
    e = _gathering(online_venue=Event.OnlineVenue.EXTERNAL,
                   access_info="https://zoom.us/j/1")
    client.force_login(_member())
    body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert "https://zoom.us/j/1" in body


def test_event_page_withholds_the_link_from_a_non_member(client):
    e = _gathering(online_venue=Event.OnlineVenue.EXTERNAL,
                   access_info="https://zoom.us/j/1")
    client.force_login(_member("x@x.test", Profile.Role.EXTERNAL))
    body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert "https://zoom.us/j/1" not in body


def test_anonymous_visitor_is_told_to_sign_in(client):
    e = _gathering()
    body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert "Open to all members" in body
    assert 'id="register-cta"' not in body


# --- The PC's create form --------------------------------------------------


def _payload(**overrides):
    data = {
        "event_type": "day_of_assembly",
        "title": "Assembly",
        "description": "9:00 Opening\n10:00 Passes",
        "proposed_datetime": "2030-11-14T09:00",
        "location_kind": "online_insite",
        "fee_type": "free",
        "speakers-TOTAL_FORMS": "0",
        "speakers-INITIAL_FORMS": "0",
        "speakers-MIN_NUM_FORMS": "0",
        "speakers-MAX_NUM_FORMS": "1000",
        "action": "publish",
    }
    data.update(overrides)
    return data


def test_create_form_labels_the_description_as_the_proceedings(client):
    client.force_login(_pc_member())
    body = client.get(reverse("program_admin_special_event_new")).content.decode()
    assert "Schedule of proceedings" in body


def test_create_form_discards_fields_a_gathering_does_not_use(client):
    """Hidden in the browser, but a type switch can leave values posted."""
    client.force_login(_pc_member())
    client.post(reverse("program_admin_special_event_new"), _payload(
        fee_type="fixed", fee_amount="40", readings_text="Freud, S. One.",
        offers_ce="on", ce_credits="3",
    ))
    e = Event.objects.get(title="Assembly")
    assert not e.price_tiers.exists()
    assert e.readings == ""
    assert e.offers_ce is False
    assert e.description.startswith("9:00 Opening")


# --- The edit page ----------------------------------------------------------


def test_edit_page_hides_fee_readings_and_ce_for_a_gathering(client):
    e = _gathering()
    client.force_login(_pc_member())
    body = client.get(reverse("events:edit", args=[e.slug])).content.decode()
    assert "Schedule of proceedings" in body
    assert 'name="readings"' not in body
    assert 'name="fee_note"' not in body
    assert 'name="fee_type"' not in body
    assert 'name="offers_ce"' not in body


def test_editing_a_gathering_keeps_its_hidden_values(client):
    """A trimmed page must not wipe what it no longer shows — the January
    Working Day on prod carries a $0 tier."""
    e = _gathering(etype=Event.Type.WORKING_DAY, slug="wd", readings="Kept.")
    PriceTier.objects.create(event=e, audience=Audience.ALL,
                             base_amount=Decimal("0.00"), covered_by_tuition=True)
    client.force_login(_pc_member())
    resp = client.post(reverse("events:edit", args=[e.slug]), {
        "title": "Working Day", "description": "Program",
        "schedule_note": "", "contact": "",
        "registration_eligibility": "members_only",
        "online_venue": "insite", "access_info": "",
    })
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.title == "Working Day"
    assert e.readings == "Kept."
    assert e.price_tiers.count() == 1


# --- Calendar ----------------------------------------------------------------


def test_calendar_shows_a_gathering_as_one_all_day_item(client):
    e = _gathering()
    Session.objects.create(
        event=e, sequence=2,
        start_at=datetime(2030, 11, 15, 17, 0, tzinfo=dt_timezone.utc),
        end_at=datetime(2030, 11, 15, 22, 0, tzinfo=dt_timezone.utc),
    )
    items = client.get(
        reverse("core:calendar_events"),
        {"start": "2030-11-01", "end": "2030-12-01"},
    ).json()
    mine = [i for i in items if i.get("url") == reverse("events:detail", args=[e.slug])]
    assert len(mine) == 1                      # not one per session
    item = mine[0]
    assert item["allDay"] is True
    assert item["start"] == "2030-11-14"
    assert item["end"] == "2030-11-16"         # exclusive end, spans both days
    assert "lsp-cal-gathering" in item["className"]


def test_calendar_keeps_timed_sessions_for_other_events(client):
    e = _gathering(etype=Event.Type.SPECIAL_EVENT, slug="talk")
    items = client.get(
        reverse("core:calendar_events"),
        {"start": "2030-11-01", "end": "2030-12-01"},
    ).json()
    mine = [i for i in items if i.get("url") == reverse("events:detail", args=[e.slug])]
    assert len(mine) == 1
    assert "allDay" not in mine[0]


def test_calendar_hides_an_unpublished_gathering(client):
    e = _gathering()
    e.published = False
    e.save(update_fields=["published"])
    items = client.get(
        reverse("core:calendar_events"),
        {"start": "2030-11-01", "end": "2030-12-01"},
    ).json()
    assert not [i for i in items if i.get("url") == reverse("events:detail", args=[e.slug])]


def test_event_page_names_the_description_as_the_proceedings(client):
    e = _gathering(description="9:00 Opening")
    body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert "Schedule of proceedings" in body


def test_member_gets_the_join_button_once_the_gathering_is_live(client):
    """With video on, an unregistered member reaches the room like a registrant."""
    from django.test import override_settings
    from django.utils import timezone

    e = _gathering()
    now = timezone.now()
    s = e.sessions.get()
    s.start_at, s.end_at = now - timedelta(minutes=10), now + timedelta(hours=2)
    s.save()
    client.force_login(_member())
    with override_settings(DAILY_ENABLED=True, DAILY_API_KEY="k",
                           DAILY_DOMAIN="lsp.daily.co"):
        body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert reverse("video:event_room", args=[e.slug]) in body
    assert "Join the meeting room" in body


def test_a_members_only_gathering_shows_no_fee(client):
    """The January Working Day on prod carries a $0 tier; members pay nothing,
    so a fee block would only mislead."""
    e = _gathering(etype=Event.Type.WORKING_DAY, slug="wd-fee")
    PriceTier.objects.create(event=e, audience=Audience.ALL, base_amount=Decimal("0.00"))
    body = client.get(reverse("events:detail", args=[e.slug])).content.decode()
    assert ">Fee</h2>" not in body
