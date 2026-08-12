"""Faculty-approval registration flow (approve-first, then pay)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import Profile, User
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def _approval_event(amount="50.00", *, requires_approval=True,
                    event_type=Event.Type.SEMINAR):
    e = Event.objects.create(
        title="Approval Seminar", slug="appr", event_type=event_type,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=Event.Status.OPEN,
        requires_faculty_approval=requires_approval,
    )
    PriceTier.objects.create(event=e, audience=Audience.ALL, base_amount=Decimal(amount))
    e.ensure_workgroup()
    return e


def _faculty(event, email="fac@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="Fa", last_name="Culty")
    u.profile.is_faculty = True
    u.profile.save()
    event.add_faculty(u)
    return u


def _student(email="stu@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="Stu", last_name="Dent")
    u.profile.role = Profile.Role.MEMBER
    u.profile.save()
    return u


def test_turning_approval_on_grandfathers_existing_registrations(client):
    """Flipping the flag on a running seminar is inert for everyone already in.

    The flag is read only when a registration is *created*, so this holds by
    construction — which is exactly why it's pinned here rather than left as an
    emergent property of where the read happens to live (task #564).
    """
    event = _approval_event(requires_approval=False)
    tier = event.price_tiers.first()
    early = Registration.objects.create(
        user=_student("early@x.test"), event=event, price_tier=tier,
        quoted_amount=Decimal("50.00"), status=Registration.Status.AWAITING_PAYMENT,
    )
    paid = Registration.objects.create(
        user=_student("paid@x.test"), event=event, price_tier=tier,
        quoted_amount=Decimal("50.00"), status=Registration.Status.PAID,
    )

    event.requires_faculty_approval = True
    event.save(update_fields=("requires_faculty_approval",))

    early.refresh_from_db()
    paid.refresh_from_db()
    assert early.status == Registration.Status.AWAITING_PAYMENT
    assert paid.status == Registration.Status.PAID

    # ...but the next one through the door queues.
    later = _student("later@x.test")
    client.force_login(later)
    client.post(reverse("registrations:register", args=[event.slug]),
                {"price_tier": tier.pk})
    assert (Registration.objects.get(user=later, event=event).status
            == Registration.Status.PENDING_APPROVAL)


def test_register_requires_approval_creates_pending_and_notifies_faculty(client):
    event = _approval_event()
    fac = _faculty(event)
    student = _student()
    client.force_login(student)

    tier = event.price_tiers.first()
    mail.outbox.clear()
    resp = client.post(reverse("registrations:register", args=[event.slug]),
                       {"price_tier": tier.pk})

    reg = Registration.objects.get(user=student, event=event)
    assert reg.status == Registration.Status.PENDING_APPROVAL
    assert resp.status_code == 302 and "confirmation" in resp.url   # not Stripe
    # Faculty got the approval-needed email.
    assert any(fac.email in m.to for m in mail.outbox)


def test_approve_nonzero_moves_to_awaiting_payment_and_emails_student(
    client, django_capture_on_commit_callbacks
):
    event = _approval_event("50.00")
    fac = _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(fac)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("registrations:approve", args=[reg.id]))

    reg.refresh_from_db()
    assert reg.status == Registration.Status.AWAITING_PAYMENT
    assert reg.approved_by == fac and reg.decided_at is not None
    assert reg.needs_payment
    assert any(student.email in m.to for m in mail.outbox)   # "approved — pay" email


def test_approve_zero_amount_moves_to_paid(client):
    event = _approval_event("0.00")
    fac = _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("0.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(fac)
    client.post(reverse("registrations:approve", args=[reg.id]))

    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID


def test_decline_sets_declined_and_emails_student(
    client, django_capture_on_commit_callbacks
):
    event = _approval_event()
    fac = _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(fac)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("registrations:decline", args=[reg.id]), {"reason": "Full this year"})

    reg.refresh_from_db()
    assert reg.status == Registration.Status.DECLINED
    assert reg.decline_reason == "Full this year"
    assert any(student.email in m.to for m in mail.outbox)


def test_non_faculty_cannot_approve(client):
    event = _approval_event()
    _faculty(event)
    student = _student()
    reg = Registration.objects.create(
        user=student, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    client.force_login(_student("outsider@x.test"))
    resp = client.post(reverse("registrations:approve", args=[reg.id]))
    assert resp.status_code == 403
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PENDING_APPROVAL


def test_reminders_command_notifies_and_throttles(client):
    from django.core.management import call_command
    from django.utils import timezone

    event = _approval_event("50.00")
    fac = _faculty(event)
    pending = Registration.objects.create(
        user=_student("p@x.test"), event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    approved = Registration.objects.create(
        user=_student("a@x.test"), event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.AWAITING_PAYMENT,
        decided_at=timezone.now(),
    )

    mail.outbox.clear()
    call_command("send_registration_reminders")
    # Faculty reminder (to fac) + student payment reminder (to approved.user).
    assert any(fac.email in m.to for m in mail.outbox)
    assert any(approved.user.email in m.to for m in mail.outbox)
    pending.refresh_from_db()
    approved.refresh_from_db()
    assert pending.reminded_at is not None and approved.reminded_at is not None

    # Running again immediately: throttled, nothing sent.
    mail.outbox.clear()
    call_command("send_registration_reminders")
    assert mail.outbox == []


def test_pending_notice_reaches_conveners_and_links_to_the_roster():
    """The convener could always approve; nothing told them there was anything
    to approve, and the bell's ?view=faculty URL redirected to the Workspace
    Overview tab, which has no approve buttons (task #564)."""
    from notifications.models import Notification
    from payments import notifications as notify_payments
    from workgroups.models import WorkgroupMembership

    event = _approval_event(event_type=Event.Type.READING_GROUP)
    convener = _student("conv@x.test")
    WorkgroupMembership.objects.create(
        workgroup=event.workgroup, user=convener,
        role=WorkgroupMembership.Role.ORGANIZER, start_date=date(2026, 9, 1),
    )
    reg = Registration.objects.create(
        user=_student(), event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )

    mail.outbox.clear()
    notify_payments.registration_pending(reg)

    assert any(convener.email in m.to for m in mail.outbox)
    bell = Notification.objects.get(recipient=convener)
    assert bell.url.endswith("?tab=roster"), bell.url


def test_release_pending_approvals_routes_on_amount_and_is_idempotent(
    django_capture_on_commit_callbacks,
):
    """Off has to be the inverse of on (task #564)."""
    from registrations.services import release_pending_approvals

    event = _approval_event()
    staff = _faculty(event)
    free = Registration.objects.create(
        user=_student("free@x.test"), event=event,
        price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("0.00"), status=Registration.Status.PENDING_APPROVAL,
    )
    owing = Registration.objects.create(
        user=_student("owing@x.test"), event=event,
        price_tier=event.price_tiers.first(),
        quoted_amount=Decimal("50.00"), status=Registration.Status.PENDING_APPROVAL,
    )

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        released = release_pending_approvals(event, staff)

    assert {r.pk for r in released} == {free.pk, owing.pk}
    free.refresh_from_db()
    owing.refresh_from_db()
    assert free.status == Registration.Status.PAID
    assert owing.status == Registration.Status.AWAITING_PAYMENT
    assert owing.approved_by == staff and owing.decided_at is not None
    assert any(free.user.email in m.to for m in mail.outbox)
    assert any(owing.user.email in m.to for m in mail.outbox)

    # A second pass finds nothing pending and so sends nothing.
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        assert release_pending_approvals(event, staff) == []
    assert mail.outbox == []


# Literal template text isn't auto-escaped, so the apostrophe stays raw.
NOTICE = "reviewed before it's confirmed"


def test_register_page_discloses_approval(client):
    """Nothing told a member their registration would be reviewed — they found
    out on the confirmation page, after committing (task #564)."""
    event = _approval_event()
    client.force_login(_student())
    body = client.get(
        reverse("registrations:register", args=[event.slug])
    ).content.decode()
    assert NOTICE in body


def test_register_page_silent_without_approval(client):
    event = _approval_event(requires_approval=False)
    client.force_login(_student())
    body = client.get(
        reverse("registrations:register", args=[event.slug])
    ).content.decode()
    assert NOTICE not in body
