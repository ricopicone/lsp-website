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


# --- Faculty M2M --------------------------------------------------------


@pytest.mark.django_db
def test_event_faculty_m2m_attaches_users():
    faculty = User.objects.create_user(email="fac@example.com")
    faculty.profile.is_faculty = True
    faculty.profile.save()
    e = Event.objects.create(
        title="X", slug="x",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    e.faculty.add(faculty)
    assert list(e.faculty.all()) == [faculty]
    assert list(faculty.events_taught.all()) == [e]


@pytest.mark.django_db
def test_member_speaker_display_bio_falls_back_to_profile():
    u = User.objects.create_user(email="m@example.com", first_name="Stephanie", last_name="Swales")
    u.profile.bio = "Profile-level bio."
    u.profile.save()
    e = Event.objects.create(
        title="Y", slug="y",
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
    )
    link = EventMemberSpeaker.objects.create(event=e, user=u)
    assert link.display_bio == "Profile-level bio."
    link.bio_override = "Bio just for this event."
    link.save()
    assert link.display_bio == "Bio just for this event."


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
def test_event_detail_renders_member_speaker_with_overridden_bio(client):
    u = User.objects.create_user(email="m@example.com", first_name="Stephanie", last_name="Swales")
    u.profile.bio = "Generic profile bio."
    u.profile.save()
    e = Event.objects.create(
        title="Working with Masochism", slug="working-with-masochism",
        start_date=date(2026, 9, 6), end_date=date(2026, 9, 6),
        published=True, status=Event.Status.OPEN,
        event_type=Event.Type.SPECIAL_EVENT,
    )
    EventMemberSpeaker.objects.create(
        event=e, user=u,
        bio_override="Per-event introduction tailored to the talk.",
    )
    resp = client.get(f"/events/{e.slug}/")
    assert resp.status_code == 200
    body = resp.content
    assert b"Stephanie Swales" in body
    assert b"Per-event introduction tailored to the talk." in body
    assert b"Generic profile bio." not in body
