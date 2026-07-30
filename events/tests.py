"""Tests for the events app data model (Milestone 2)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from events.models import (
    Audience,
    Event,
    EventMemberSpeaker,
    PriceTier,
    PricingCode,
    Session,
    generate_pricing_code,
)


def _utc(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


# --- Event --------------------------------------------------------------


@pytest.mark.django_db
def test_event_create_minimal():
    e = Event.objects.create(
        title="Lacan Seminar XI",
        slug="lacan-seminar-xi",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15),
    )
    assert str(e) == "Lacan Seminar XI"
    assert e.event_type == Event.Type.SEMINAR
    assert e.status == Event.Status.DRAFT
    assert e.published is False


@pytest.mark.django_db
def test_event_clean_rejects_inverted_dates():
    e = Event(
        title="X",
        slug="x",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 9, 1),
    )
    with pytest.raises(ValidationError):
        e.full_clean()


@pytest.mark.django_db
def test_event_open_to_guests_defaults_true():
    e = Event.objects.create(
        title="Special Evening",
        slug="special-evening",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
    )
    assert e.open_to_guests is True


# --- Session ------------------------------------------------------------


@pytest.mark.django_db
def test_session_str_and_ordering():
    e = Event.objects.create(
        title="Seminar", slug="seminar",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    s2 = Session.objects.create(
        event=e, start_at=_utc(2026, 9, 15), end_at=_utc(2026, 9, 15, 12), sequence=2
    )
    s1 = Session.objects.create(
        event=e, start_at=_utc(2026, 9, 1), end_at=_utc(2026, 9, 1, 12), sequence=1
    )
    assert list(Session.objects.all()) == [s1, s2]
    assert "Seminar" in str(s2)


@pytest.mark.django_db
def test_session_clean_rejects_end_before_start():
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    s = Session(event=e, start_at=_utc(2026, 9, 1, 12), end_at=_utc(2026, 9, 1, 10))
    with pytest.raises(ValidationError):
        s.full_clean()


# --- PriceTier ----------------------------------------------------------


@pytest.mark.django_db
def test_price_tier_sliding_scale_requires_minimum():
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pt = PriceTier(
        event=e,
        audience=Audience.STUDENT,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        # minimum_amount missing
    )
    with pytest.raises(ValidationError):
        pt.full_clean()


@pytest.mark.django_db
def test_price_tier_minimum_cannot_exceed_base():
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pt = PriceTier(
        event=e,
        audience=Audience.ALL,
        base_amount=Decimal("50.00"),
        sliding_scale=True,
        minimum_amount=Decimal("100.00"),
    )
    with pytest.raises(ValidationError):
        pt.full_clean()


@pytest.mark.django_db
def test_price_tier_minimum_zero_is_valid_for_none_turned_away():
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pt = PriceTier(
        event=e,
        audience=Audience.ALL,
        base_amount=Decimal("100.00"),
        sliding_scale=True,
        minimum_amount=Decimal("0.00"),
    )
    pt.full_clean()  # no raise


# --- PricingCode --------------------------------------------------------


def test_generate_pricing_code_alphabet_and_length():
    code = generate_pricing_code()
    assert len(code) == 8
    assert set(code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")


@pytest.mark.django_db
def test_pricing_code_auto_generates_code_and_uses_remaining():
    faculty = User.objects.create_user(email="fac@example.com")
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pc = PricingCode.objects.create(
        event=e,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("25"),
        max_uses=3,
    )
    assert pc.code
    assert len(pc.code) == 8
    assert pc.uses_remaining == 3


@pytest.mark.django_db
def test_pricing_code_clean_rejects_invalid_percent():
    faculty = User.objects.create_user(email="fac@example.com")
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pc = PricingCode(
        event=e,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("150"),
    )
    with pytest.raises(ValidationError):
        pc.full_clean()


@pytest.mark.django_db
def test_pricing_code_is_redeemable_default():
    faculty = User.objects.create_user(email="fac@example.com")
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pc = PricingCode.objects.create(
        event=e,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("50"),
    )
    assert pc.is_redeemable() is True


@pytest.mark.django_db
def test_pricing_code_expired_not_redeemable():
    faculty = User.objects.create_user(email="fac@example.com")
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pc = PricingCode.objects.create(
        event=e,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("50"),
        valid_until=timezone.now() - timedelta(days=1),
    )
    assert pc.is_redeemable() is False


@pytest.mark.django_db
def test_pricing_code_exhausted_not_redeemable():
    faculty = User.objects.create_user(email="fac@example.com")
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pc = PricingCode.objects.create(
        event=e,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.PERCENT_OFF,
        amount_or_percent=Decimal("10"),
        max_uses=1,
    )
    pc.uses_remaining = 0
    pc.save()
    assert pc.is_redeemable() is False


@pytest.mark.django_db
def test_pricing_code_restricted_to_user():
    faculty = User.objects.create_user(email="fac@example.com")
    sally = User.objects.create_user(email="sally@example.com")
    other = User.objects.create_user(email="other@example.com")
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    pc = PricingCode.objects.create(
        event=e,
        issued_by=faculty,
        pricing_mode=PricingCode.Mode.FIXED_AMOUNT,
        amount_or_percent=Decimal("0"),
        restricted_to_user=sally,
    )
    assert pc.is_redeemable(user=sally) is True
    assert pc.is_redeemable(user=other) is False


# --- Faculty (a role on the event's workgroup) --------------------------


@pytest.mark.django_db
def test_event_faculty_is_a_workgroup_role():
    faculty = User.objects.create_user(email="fac@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )  # event_type defaults to SEMINAR → gets an offering workgroup
    e.add_faculty(faculty)
    assert e.faculty_members() == [faculty]
    assert e.is_faculty(faculty)
    # Faculty is stored as a FACULTY role on the generated workgroup.
    from workgroups.models import WorkgroupMembership
    assert WorkgroupMembership.objects.filter(
        workgroup=e.workgroup, user=faculty, role=WorkgroupMembership.Role.FACULTY,
        end_date__isnull=True,
    ).exists()
    # ...and the workgroup roster reflects them.
    assert e.workgroup.is_member(faculty)

    # set_faculty([]) ends the membership.
    e.set_faculty([])
    assert e.faculty_members() == [] and not e.is_faculty(faculty)


@pytest.mark.django_db
def test_profile_display_event_bio_falls_back_to_bio():
    u = User.objects.create_user(email="m@example.com", first_name="Stephanie", last_name="Swales")
    u.profile.bio = "General directory bio."
    u.profile.save()
    assert u.profile.display_event_bio == "General directory bio."
    u.profile.event_bio = "Speaker-only bio."
    u.profile.save()
    assert u.profile.display_event_bio == "Speaker-only bio."


@pytest.mark.django_db
def test_member_speaker_unique_per_event_and_user():
    u = User.objects.create_user(email="m@example.com")
    e = Event.objects.create(
        title="Y", slug="y",
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
    )
    EventMemberSpeaker.objects.create(event=e, user=u)
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        EventMemberSpeaker.objects.create(event=e, user=u)


@pytest.mark.django_db
def test_event_detail_renders_someone_in_both_faculty_and_member_speakers_once(client):
    u = User.objects.create_user(email="m@example.com", first_name="Stephanie", last_name="Swales")
    u.profile.is_faculty = True
    u.profile.bio = "Just one bio."
    u.profile.save()
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
        published=True, status=Event.Status.OPEN,
    )
    e.add_faculty(u)
    e.member_speakers.add(u)
    # The seminar page is the Workspace now; the event URL redirects there.
    resp = client.get(f"/events/{e.slug}/", follow=True)
    assert resp.status_code == 200
    assert resp.content.count(b"Stephanie Swales") == 1   # deduped in the shared summary


@pytest.mark.django_db
def test_event_detail_renders_member_speaker_with_event_bio(client):
    u = User.objects.create_user(email="m@example.com", first_name="Stephanie", last_name="Swales")
    u.profile.bio = "Generic directory bio."
    u.profile.event_bio = "Speaker-specific bio for talks."
    u.profile.save()
    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
        published=True, status=Event.Status.OPEN,
        event_type=Event.Type.SPECIAL_EVENT,
    )
    e.member_speakers.add(u)
    resp = client.get(f"/events/{e.slug}/")
    assert resp.status_code == 200
    body = resp.content
    assert b"Stephanie Swales" in body
    assert b"Speaker-specific bio for talks." in body
    assert b"Generic directory bio." not in body


@pytest.mark.django_db
def test_speaker_can_link_a_login_user():
    from events.models import Speaker
    u = User.objects.create_user(email="derek@example.com")
    s = Speaker.objects.create(name="Derek Hook", slug="derek-hook", email="derek@example.com")
    s.user = u
    s.save()
    s.refresh_from_db()
    assert s.user == u
    assert u.external_speaker == s


@pytest.mark.django_db
def test_speaker_spotlight_defaults_off():
    e = Event.objects.create(
        title="Talk", slug="spotlight-default",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2030, 9, 1), end_date=date(2030, 9, 1),
    )
    assert e.speaker_spotlight is False


def test_open_to_guests_is_on_edit_forms_and_not_reviewable():
    from events.forms import EventEditForm, ProgramEventForm
    from events.review import REVIEWABLE_FIELDS

    assert "open_to_guests" in EventEditForm.Meta.fields
    assert "open_to_guests" in ProgramEventForm.Meta.fields
    # Non-reviewable: applies immediately, skips the change-review dialog.
    assert "open_to_guests" not in REVIEWABLE_FIELDS


@pytest.mark.django_db
def test_staff_edit_toggles_open_to_guests_immediately(client):
    staff = User.objects.create_user(
        email="staff@example.org", password="pw", is_staff=True
    )
    e = Event.objects.create(
        title="Special Evening", slug="special-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    client.force_login(staff)
    resp = client.post(f"/events/{e.slug}/edit/", {
        "title": e.title,
        "description": "",
        "readings": "",
        "schedule_note": "",
        "contact": "",
        "fee_note": "",
        # record_video / speaker_spotlight / open_to_guests are checkboxes;
        # omitting open_to_guests unchecks it.
    })
    assert resp.status_code == 302
    e.refresh_from_db()
    assert e.open_to_guests is False


def _special_event(**kwargs):
    defaults = dict(
        title="Special Evening", slug="special-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
    )
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


@pytest.mark.django_db
def test_event_page_shows_guest_note_when_open_to_guests(client):
    e = _special_event()
    resp = client.get(f"/events/{e.slug}/")
    content = resp.content.decode()
    assert "Guests are welcome" in content
    # Anonymous viewers also get the account hint.
    assert "create a free account" in content


@pytest.mark.django_db
def test_event_page_hides_guest_note_when_flag_off(client):
    e = _special_event(open_to_guests=False)
    resp = client.get(f"/events/{e.slug}/")
    assert "Guests are welcome" not in resp.content.decode()


@pytest.mark.django_db
def test_signed_in_viewer_gets_note_without_account_hint(client):
    member = User.objects.create_user(email="m@example.org", password="pw")
    client.force_login(member)
    e = _special_event()
    resp = client.get(f"/events/{e.slug}/")
    content = resp.content.decode()
    assert "Guests are welcome" in content
    assert "create a free account" not in content


@pytest.mark.django_db
def test_members_only_event_hides_guest_note(client):
    e = _special_event(visibility=Event.Visibility.MEMBERS_ONLY)
    resp = client.get(f"/events/{e.slug}/")
    assert "Guests are welcome" not in resp.content.decode()
