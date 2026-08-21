"""An online event says *where* online: the in-site room, or somewhere else.

Task #624. ``Event.format`` says whether people gather in a room; it never said
which online room, so an event meeting on Zoom still offered the site's own
video room beside the Zoom link. ``online_venue`` is that missing axis and
``uses_insite_room`` is the one predicate every surface asks.
"""

import datetime as dt
from decimal import Decimal

import pytest

from accounts.models import User
from events.models import Event

# ---- The predicate ------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "venue", "expected"),
    [
        (Event.Format.ONLINE, Event.OnlineVenue.INSITE, True),
        (Event.Format.ONLINE, Event.OnlineVenue.EXTERNAL, False),
        (Event.Format.HYBRID, Event.OnlineVenue.INSITE, True),
        (Event.Format.HYBRID, Event.OnlineVenue.EXTERNAL, False),
        # In person never meets online, whatever the venue field happens to say.
        (Event.Format.IN_PERSON, Event.OnlineVenue.INSITE, False),
        (Event.Format.IN_PERSON, Event.OnlineVenue.EXTERNAL, False),
    ],
)
def test_uses_insite_room_truth_table(fmt, venue, expected):
    assert Event(format=fmt, online_venue=venue).uses_insite_room is expected


def test_online_venue_defaults_to_the_insite_room():
    """The default must stay in-site: it is what every existing event means."""
    assert Event().online_venue == Event.OnlineVenue.INSITE
    assert Event(format=Event.Format.ONLINE).uses_insite_room is True


# ---- The proposal's fourth location kind --------------------------------


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(email="pc@example.test", password="x")


@pytest.mark.django_db
def test_proposal_external_online_mints_an_external_event(reviewer):
    """A seminar proposed as "online, external link" mints as one, and the
    proposed link flows into access_info the way a venue address already does."""
    from events.models import EventProposal

    proposal = EventProposal.objects.create(
        title="A Seminar on Zoom",
        event_type=Event.Type.SEMINAR,
        location_kind=EventProposal.LocationKind.ONLINE_EXTERNAL,
        location="https://zoom.example.com/j/424242",
        start_date=dt.date(2026, 9, 1),
        end_date=dt.date(2027, 5, 1),
        proposed_by=reviewer,
        fee_amount=Decimal("0.00"),
    )
    event = proposal.approve(reviewer)

    assert event.format == Event.Format.ONLINE
    assert event.online_venue == Event.OnlineVenue.EXTERNAL
    assert event.access_info == "https://zoom.example.com/j/424242"
    assert event.uses_insite_room is False


@pytest.mark.django_db
def test_proposal_insite_online_still_mints_the_insite_room(reviewer):
    """The default path is untouched: no access_info, the site's own room."""
    from events.models import EventProposal

    proposal = EventProposal.objects.create(
        title="A Seminar in the Site's Room",
        event_type=Event.Type.SEMINAR,
        location_kind=EventProposal.LocationKind.ONLINE_INSITE,
        start_date=dt.date(2026, 9, 1),
        end_date=dt.date(2027, 5, 1),
        proposed_by=reviewer,
        fee_amount=Decimal("0.00"),
    )
    event = proposal.approve(reviewer)

    assert event.format == Event.Format.ONLINE
    assert event.online_venue == Event.OnlineVenue.INSITE
    assert event.access_info == ""
    assert event.uses_insite_room is True


# ---- Not reviewable -----------------------------------------------------


def test_venue_and_link_are_not_reviewable_fields():
    """Change review protects the content the PC approved (title, description,
    readings, fee). A meeting link was never approved content."""
    from events.review import REVIEWABLE_FIELDS

    assert "online_venue" not in REVIEWABLE_FIELDS
    assert "access_info" not in REVIEWABLE_FIELDS


# ---- The migration's one-time carry-across ------------------------------
#
# The heuristic is unsafe as a live predicate and safe run once over today's
# data, so it is tested as what it is: a function over rows.


def _carry_across():
    """The migration's data function, imported past its numeric module name."""
    import importlib

    mod = importlib.import_module("events.migrations.0050_event_online_venue")
    from django.apps import apps as django_apps

    return lambda: mod.carry_external_venue_across(django_apps, None)


def _event(**kw):
    kw.setdefault("title", "T")
    kw.setdefault("event_type", Event.Type.SPECIAL_EVENT)
    kw.setdefault("start_date", dt.date(2026, 9, 1))
    kw.setdefault("end_date", dt.date(2026, 9, 1))
    return Event.objects.create(**kw)


@pytest.mark.django_db
def test_carry_across_marks_an_online_event_with_a_link_external():
    """Saying "Zoom" the only way the site allowed — a link in access_info on
    an online event — meant EXTERNAL all along."""
    e = _event(slug="zoomed", format=Event.Format.ONLINE,
               access_info="https://zoom.example.com/j/1")
    _carry_across()()
    e.refresh_from_db()
    assert e.online_venue == Event.OnlineVenue.EXTERNAL
    assert e.uses_insite_room is False


@pytest.mark.django_db
def test_carry_across_leaves_hybrid_events_alone():
    """A hybrid event's access_info is its *venue address* (the proposal mint
    writes it there) and it still wants the in-site room. This is exactly why
    the predicate is a stored field rather than a guess."""
    e = _event(slug="hybrid", format=Event.Format.HYBRID,
               access_info="220 Montgomery St, San Francisco")
    _carry_across()()
    e.refresh_from_db()
    assert e.online_venue == Event.OnlineVenue.INSITE
    assert e.uses_insite_room is True


@pytest.mark.django_db
def test_carry_across_leaves_the_insite_default_alone():
    """An online event with no access_info is the in-site room, unchanged."""
    e = _event(slug="insite", format=Event.Format.ONLINE, access_info="")
    _carry_across()()
    e.refresh_from_db()
    assert e.online_venue == Event.OnlineVenue.INSITE


# ---- The confirmation email ---------------------------------------------
#
# payments/emails.py offered the in-site room on `has_access and
# daily_enabled()` with no format check at all, so it mailed "Join the meeting
# room (in your browser, no app to install)" to *in-person* registrants too.


@pytest.fixture
def _daily_on():
    from django.test import override_settings

    with override_settings(
        DAILY_ENABLED=True, DAILY_API_KEY="k", DAILY_DOMAIN="lsp.daily.co"
    ):
        yield


def _paid_registration(event):
    from events.models import Audience, PriceTier
    from registrations.models import Registration

    user = User.objects.create_user(email="student@example.test", password="x")
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("0.00")
    )
    return Registration.objects.create(
        user=user, event=event, price_tier=tier,
        quoted_amount=Decimal("0.00"), status=Registration.Status.PAID,
    )


def _confirmation_body(event, mailoutbox):
    from payments.emails import send_registration_confirmation

    send_registration_confirmation(_paid_registration(event))
    return mailoutbox[-1].body


@pytest.mark.django_db
def test_confirmation_email_offers_the_room_for_an_insite_event(
    mailoutbox, _daily_on,
):
    body = _confirmation_body(
        _event(slug="insite-mail", format=Event.Format.ONLINE), mailoutbox
    )
    assert "Join the meeting room" in body


@pytest.mark.django_db
def test_confirmation_email_omits_the_room_for_an_external_event(
    mailoutbox, _daily_on,
):
    """A Zoom seminar's registrant gets the Zoom link, not two doors."""
    event = _event(
        slug="external-mail", format=Event.Format.ONLINE,
        online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example.com/j/424242",
    )
    body = _confirmation_body(event, mailoutbox)
    assert "Join the meeting room" not in body
    assert "https://zoom.example.com/j/424242" in body


@pytest.mark.django_db
def test_confirmation_email_omits_the_room_for_an_in_person_event(
    mailoutbox, _daily_on,
):
    """Regression (task #624): the room paragraph had no format check, so
    in-person registrants were told to join in their browser."""
    event = _event(
        slug="in-person-mail", format=Event.Format.IN_PERSON,
        access_info="220 Montgomery St, San Francisco",
    )
    body = _confirmation_body(event, mailoutbox)
    assert "Join the meeting room" not in body
    assert "no app to install" not in body


# ---- Faculty own their own meeting link ---------------------------------
#
# Neither access_info nor format was on EventEditForm, so the person teaching
# the seminar had to ask the Program Committee to set their Zoom link. Format
# stays the PC's (whether people gather in a room is a program fact); *which*
# online venue is a teaching decision.


def test_venue_and_link_are_on_the_faculty_form_but_format_is_not():
    from events.forms import EventEditForm

    assert "online_venue" in EventEditForm.Meta.fields
    assert "access_info" in EventEditForm.Meta.fields
    assert "format" not in EventEditForm.Meta.fields


def test_online_venue_is_not_required_on_the_form():
    """A choices-plus-default field on a ModelForm is required by default,
    which breaks every POST that omits it — including the change-review
    dialog's re-post (the standing trap from #486, #566)."""
    from events.forms import EventEditForm

    form = EventEditForm()
    assert form.fields["online_venue"].required is False


def test_blank_online_venue_coerces_to_the_insite_default():
    from events.forms import EventEditForm

    form = EventEditForm(
        data={"title": "T", "description": "d", "online_venue": ""},
        instance=_event_unsaved(),
    )
    form.is_valid()
    assert form.cleaned_data["online_venue"] == Event.OnlineVenue.INSITE


def _event_unsaved():
    return Event(
        title="T", slug="t", event_type=Event.Type.SEMINAR,
        start_date=dt.date(2026, 9, 1), end_date=dt.date(2027, 5, 1),
    )


def test_confirm_dialog_reposts_the_venue_and_the_link():
    """The dialog re-posts every field as a hidden <textarea>. A TextField and
    a <select> both survive that (only checkboxes need the exception list), but
    a silent revert would be invisible, so pin it (task #566's precedent)."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent / "templates/events/event_edit_confirm.html"
    ).read_text()
    # Not in the checkbox exception list — they must fall through to the textarea.
    exception_line = [ln for ln in src.splitlines() if 'field.name == "record_video"' in ln]
    assert exception_line, "the checkbox exception list moved"
    assert "online_venue" not in exception_line[0]
    assert "access_info" not in exception_line[0]


@pytest.mark.django_db
def test_faculty_can_set_their_own_zoom_link(client):
    """End to end: the person teaching the seminar sets the venue and the link
    without asking the Program Committee."""
    from django.urls import reverse

    event = Event.objects.create(
        title="Gardner's Seminar", slug="gardners-seminar",
        event_type=Event.Type.SEMINAR,
        start_date=dt.date(2026, 9, 1), end_date=dt.date(2027, 5, 1),
        published=True, status=Event.Status.OPEN,
    )
    event.ensure_workgroup()
    faculty = User.objects.create_user(email="gardner@example.test", password="x")
    event.add_faculty(faculty)
    client.force_login(faculty)

    response = client.post(reverse("events:edit", args=[event.slug]), {
        "title": event.title,
        "description": "",
        "online_venue": Event.OnlineVenue.EXTERNAL,
        "access_info": "https://zoom.example.com/j/424242 (passcode 1234)",
    })

    assert response.status_code == 302
    event.refresh_from_db()
    assert event.online_venue == Event.OnlineVenue.EXTERNAL
    assert "zoom.example.com" in event.access_info
    assert event.uses_insite_room is False


def test_online_venue_is_not_required_on_the_pc_form_either():
    """Both forms hit the same trap: a choices-plus-default field is required
    by default, and the PC's form is POSTed by tests and views that predate the
    field. This is the second half of the fix, and it broke six tests before it
    was added."""
    from events.forms import ProgramEventForm

    form = ProgramEventForm()
    assert "online_venue" in ProgramEventForm.Meta.fields
    assert form.fields["online_venue"].required is False


# ---- The speaker invitation ---------------------------------------------
#
# The same defect one surface out: the invitation told an outside speaker "the
# meeting room is right there, no separate link needed", which is wrong for an
# event meeting on Zoom.


@pytest.mark.django_db
def test_speaker_invitation_promises_the_room_only_for_an_insite_event(mailoutbox):
    from events.models import Speaker
    from events.speaker_invitations import send_invitation

    event = _event(slug="insite-talk", format=Event.Format.ONLINE)
    speaker = Speaker.objects.create(
        name="A Speaker", email="speaker-insite@example.test"
    )
    send_invitation(speaker, event, "Please come.")

    assert "no separate link needed" in mailoutbox[-1].body


@pytest.mark.django_db
def test_speaker_invitation_points_at_the_joining_details_when_external(mailoutbox):
    from events.models import Speaker
    from events.speaker_invitations import send_invitation

    event = _event(
        slug="external-talk", format=Event.Format.ONLINE,
        online_venue=Event.OnlineVenue.EXTERNAL,
        access_info="https://zoom.example.com/j/424242",
    )
    speaker = Speaker.objects.create(
        name="B Speaker", email="speaker-external@example.test"
    )
    send_invitation(speaker, event, "Please come.")

    body = mailoutbox[-1].body
    assert "no separate link needed" not in body
    assert "joining details" in body.lower()
