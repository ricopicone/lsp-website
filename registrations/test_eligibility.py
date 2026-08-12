"""Who may register: members only, or members and guests (task #566)."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from events.models import Event, PricingCode
from registrations.permissions import eligibility_block_reason


def _event(**kwargs):
    defaults = dict(
        title="Special Evening", slug="special-evening",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
        status=Event.Status.OPEN, published=True,
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY,
    )
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _user(email, role=Profile.Role.EXTERNAL, **profile_kwargs):
    user = User.objects.create_user(email=email, password="pw")
    Profile.objects.filter(pk=user.profile.pk).update(role=role, **profile_kwargs)
    user.profile.refresh_from_db()
    return user


def _code(event, issued_by, code, **kwargs):
    defaults = dict(
        pricing_mode=PricingCode.Mode.PERCENT_OFF, amount_or_percent=100,
        max_uses=1, uses_remaining=1,
    )
    defaults.update(kwargs)
    return PricingCode.objects.create(
        event=event, code=code, issued_by=issued_by, **defaults
    )


@pytest.mark.django_db
def test_open_event_admits_anyone():
    event = _event(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_AND_GUESTS
    )
    assert eligibility_block_reason(_user("guest@example.org"), event) is None


@pytest.mark.django_db
def test_member_is_admitted():
    event = _event()
    member = _user("a@example.org", Profile.Role.ANALYST)
    assert eligibility_block_reason(member, event) is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["external", "student", "prospective_applicant"])
def test_every_non_member_role_is_blocked(role):
    event = _event()
    reason = eligibility_block_reason(_user(f"{role}@example.org", role), event)
    assert reason is not None
    assert "members of the Lacanian School" in reason


@pytest.mark.django_db
def test_resigned_member_is_blocked():
    event = _event()
    user = _user(
        "gone@example.org", Profile.Role.ANALYST,
        standing=Profile.Standing.RESIGNED,
    )
    assert eligibility_block_reason(user, event) is not None


@pytest.mark.django_db
def test_guest_with_a_code_addressed_to_them_is_admitted():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    _code(event, faculty, "GUEST1", restricted_to_user=guest)
    assert eligibility_block_reason(guest, event) is None


@pytest.mark.django_db
def test_an_unrestricted_code_does_not_open_the_door():
    """A code that can be forwarded is not a decision about a person."""
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    _code(event, faculty, "ANYONE")
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_a_spent_code_does_not_open_the_door():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    _code(event, faculty, "SPENT", restricted_to_user=guest, uses_remaining=0)
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_an_expired_code_does_not_open_the_door():
    event = _event()
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    _code(
        event, faculty, "STALE", restricted_to_user=guest,
        valid_until=timezone.now() - timedelta(days=1),
    )
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_a_code_for_another_event_does_not_open_the_door():
    event = _event()
    other = _event(title="Other", slug="other-evening")
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    _code(other, faculty, "ELSEWHERE", restricted_to_user=guest)
    assert eligibility_block_reason(guest, event) is not None


@pytest.mark.django_db
def test_an_outside_speaker_is_never_told_members_only():
    """A PC event's presenter with a linked login (task #463) presents at it."""
    event = _event()
    speaker_user = _user("speaker@example.org")
    event.member_speakers.add(speaker_user)
    assert eligibility_block_reason(speaker_user, event) is None


@pytest.mark.django_db
def test_anonymous_is_blocked():
    from django.contrib.auth.models import AnonymousUser

    assert eligibility_block_reason(AnonymousUser(), _event()) is not None


# --- The register view --------------------------------------------------


@pytest.mark.django_db
def test_guest_gets_403_at_the_register_url(client):
    event = _event()
    client.force_login(_user("guest@example.org"))
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 403
    assert "limited to members" in resp.content.decode()


@pytest.mark.django_db
def test_member_reaches_the_register_page(client):
    from events.models import Audience, PriceTier

    event = _event()
    PriceTier.objects.create(event=event, audience=Audience.ALL, base_amount=0)
    client.force_login(_user("a@example.org", Profile.Role.ANALYST))
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_guest_with_a_code_reaches_the_register_page(client):
    from events.models import Audience, PriceTier

    event = _event()
    PriceTier.objects.create(event=event, audience=Audience.ALL, base_amount=0)
    guest = _user("guest@example.org")
    faculty = _user("f@example.org", Profile.Role.ANALYST)
    _code(event, faculty, "GUEST1", restricted_to_user=guest)
    client.force_login(guest)
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_a_guest_who_already_registered_keeps_their_registration(client):
    """Restricting an event later must not strand someone already enrolled."""
    from events.models import Audience, PriceTier
    from registrations.models import Registration

    event = _event(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_AND_GUESTS
    )
    tier = PriceTier.objects.create(event=event, audience=Audience.ALL, base_amount=0)
    guest = _user("guest@example.org")
    reg = Registration.objects.create(
        user=guest, event=event, price_tier=tier, quoted_amount=0,
        status=Registration.Status.PAID,
    )
    Event.objects.filter(pk=event.pk).update(
        registration_eligibility=Event.RegistrationEligibility.MEMBERS_ONLY
    )
    client.force_login(guest)
    resp = client.get(f"/events/{event.slug}/register/")
    assert resp.status_code == 302
    assert str(reg.id) in resp.url


# --- The event page -----------------------------------------------------


@pytest.mark.django_db
def test_event_page_drops_the_register_button_for_a_blocked_guest(client):
    event = _event()
    client.force_login(_user("guest@example.org"))
    content = client.get(f"/events/{event.slug}/").content.decode()
    assert 'id="register-cta"' not in content
    assert "limited to members" in content


@pytest.mark.django_db
def test_event_page_keeps_the_register_button_for_a_member(client):
    event = _event()
    client.force_login(_user("a@example.org", Profile.Role.ANALYST))
    content = client.get(f"/events/{event.slug}/").content.decode()
    assert 'id="register-cta"' in content


@pytest.mark.django_db
def test_anonymous_visitor_keeps_the_button_with_a_note(client):
    """The site can't tell a signed-out member from a stranger, so it must not
    turn one away at the door."""
    event = _event()
    content = client.get(f"/events/{event.slug}/").content.decode()
    assert 'id="register-cta"' in content
    assert "limited to members" in content
