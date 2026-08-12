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


@pytest.mark.django_db
def test_offering_leads_includes_reading_group_conveners():
    """A reading group's conveners hold ORGANIZER, not FACULTY (task #495), so
    ``faculty_members()`` can't see them — but they run the offering and must
    hear about anything that asks them to act (task #564)."""
    from events.permissions import offering_leads
    from workgroups.models import WorkgroupMembership

    event = Event.objects.create(
        title="Reading Freud", slug="rg-freud",
        event_type=Event.Type.READING_GROUP,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )
    event.ensure_workgroup()
    convener = User.objects.create_user(email="conv@x.test", password="x")
    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=convener,
        role=WorkgroupMembership.Role.ORGANIZER,
        start_date=date(2026, 9, 1),
    )

    assert convener in offering_leads(event)
    # faculty_members() answers "who teaches this" and is deliberately unchanged.
    assert convener not in event.faculty_members()


@pytest.mark.django_db
def test_offering_leads_includes_faculty_without_duplicating_them():
    from events.permissions import offering_leads

    event = Event.objects.create(
        title="Seminar", slug="sem-leads", event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
    )
    event.ensure_workgroup()
    fac = User.objects.create_user(email="fac-leads@x.test", password="x")
    event.add_faculty(fac)

    leads = offering_leads(event)
    assert leads.count(fac) == 1


def test_approval_toggle_is_on_the_faculty_form_and_not_reviewable():
    from events.forms import EventEditForm, ProgramEventForm
    from events.review import REVIEWABLE_FIELDS

    assert "requires_faculty_approval" in EventEditForm.Meta.fields
    assert "requires_faculty_approval" in ProgramEventForm.Meta.fields
    # Review protects content the PC approved; who may enrol is not that.
    assert "requires_faculty_approval" not in REVIEWABLE_FIELDS


def test_confirm_dialog_reposts_the_approval_checkbox():
    """The change-review dialog re-posts every field as a hidden <textarea>,
    which silently drops a checkbox — it has to follow the record_video
    precedent or the toggle is eaten on exactly the events that route through
    review (tasks #504, #532, #564)."""
    from pathlib import Path

    src = Path(__file__).resolve().parent / "templates/events/event_edit_confirm.html"
    assert "requires_faculty_approval" in src.read_text()


def _approval_seminar(**kwargs):
    """A published seminar requiring approval, with a tier and a workgroup."""
    defaults = dict(
        title="Gated Seminar", slug="gated-seminar",
        event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        status=Event.Status.OPEN, published=True,
        requires_faculty_approval=True,
    )
    e = Event.objects.create(**{**defaults, **kwargs})
    PriceTier.objects.create(event=e, audience=Audience.ALL,
                             base_amount=Decimal("50.00"))
    e.ensure_workgroup()
    return e


def _pending_reg(event, email, amount="50.00"):
    from registrations.models import Registration

    return Registration.objects.create(
        user=User.objects.create_user(email=email, password="pw"),
        event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal(amount),
        status=Registration.Status.PENDING_APPROVAL,
    )


@pytest.mark.django_db
def test_faculty_unticking_approval_releases_the_queue(
    client, django_capture_on_commit_callbacks
):
    from registrations.models import Registration

    staff = User.objects.create_user(
        email="staff-rel@example.org", password="pw", is_staff=True
    )
    event = _approval_seminar()
    pending = _pending_reg(event, "waiting@example.org")

    client.force_login(staff)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/events/{event.slug}/edit/", {
            "title": event.title, "description": "", "readings": "",
            "schedule_note": "", "contact": "", "fee_note": "",
            "fee_type": "fixed", "fee_amount": "50.00",
            # requires_faculty_approval omitted → unticked.
        })

    event.refresh_from_db()
    pending.refresh_from_db()
    assert event.requires_faculty_approval is False
    assert pending.status == Registration.Status.AWAITING_PAYMENT


@pytest.mark.django_db
def test_ticking_approval_on_releases_nothing(client):
    from registrations.models import Registration

    staff = User.objects.create_user(
        email="staff-on@example.org", password="pw", is_staff=True
    )
    event = _approval_seminar(requires_faculty_approval=False)
    pending = _pending_reg(event, "still-waiting@example.org")

    client.force_login(staff)
    client.post(f"/events/{event.slug}/edit/", {
        "title": event.title, "description": "", "readings": "",
        "schedule_note": "", "contact": "", "fee_note": "",
        "fee_type": "fixed", "fee_amount": "50.00",
        "requires_faculty_approval": "on",
    })

    event.refresh_from_db()
    pending.refresh_from_db()
    assert event.requires_faculty_approval is True
    assert pending.status == Registration.Status.PENDING_APPROVAL


@pytest.mark.django_db
def test_django_admin_save_does_not_release_the_queue():
    """Staff paths don't fire the automation (#485's rule) — the raw admin is
    the escape hatch, and a signal would let any script mail members."""
    from registrations.models import Registration

    event = _approval_seminar()
    pending = _pending_reg(event, "admin-path@example.org")

    event.requires_faculty_approval = False
    event.save(update_fields=("requires_faculty_approval",))

    pending.refresh_from_db()
    assert pending.status == Registration.Status.PENDING_APPROVAL


@pytest.mark.django_db
def test_pc_form_unticking_approval_releases_the_queue(
    client, django_capture_on_commit_callbacks
):
    """The PC's own form is the surface the chair actually uses (task #564)."""
    from events.models import Program
    from registrations.models import Registration

    program = Program.objects.create(academic_year="2026-2027")
    event = _approval_seminar(program=program)
    pending = _pending_reg(event, "pc-waiting@example.org")
    staff = User.objects.create_user(
        email="pc-staff@example.org", password="pw", is_staff=True
    )

    client.force_login(staff)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            f"/program-admin/{program.academic_year}/events/{event.slug}/edit/", {
                "title": event.title, "slug": event.slug,
                "event_type": event.event_type,
                "start_date": "2026-09-01", "end_date": "2027-05-01",
                "format": event.format, "status": event.status,
                "description": "", "readings": "", "schedule_note": "",
                "contact": "", "fee_note": "", "access_info": "",
                "fee_type": "fixed", "fee_amount": "50.00",
                # requires_faculty_approval omitted → unticked.
            },
        )

    assert resp.status_code == 302, resp.context["form"].errors if resp.context else resp
    event.refresh_from_db()
    pending.refresh_from_db()
    assert event.requires_faculty_approval is False
    assert pending.status == Registration.Status.AWAITING_PAYMENT
