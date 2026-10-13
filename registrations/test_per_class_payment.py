"""Paying for classes, and the pages that show them (task #811)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.urls import reverse

from events import per_class
from events.models import ClassAttendance
from events.per_class_fixtures import (
    enroll,
    make_event,
    make_session,
    make_tier,
    make_user,
)
from payments.ledger import member_account
from payments.models import Charge, Payment
from payments.operations import complete_payment
from registrations.models import Registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def billed():
    event = make_event()
    tier = make_tier(event)
    user = make_user()
    reg = enroll(user, event, tier)
    for days in (5, 12):
        session = make_session(event, ends_ago=timedelta(days=days))
        per_class.run(now=session.end_at + timedelta(hours=1))
    per_class.run()
    assert Charge.objects.count() == 2
    return event, user, reg


@pytest.fixture
def fake_stripe():
    session = SimpleNamespace(id="cs_test_pc", url="https://stripe.test/pc", livemode=False)
    with patch("payments.stripe_checkout.stripe.checkout.Session.create",
               return_value=session) as create:
        yield create


def test_pay_classes_checks_out_the_open_balance(client, billed, fake_stripe):
    event, user, reg = billed
    client.force_login(user)
    resp = client.post(reverse("registrations:pay_classes", args=[reg.id]))
    assert resp.status_code == 302 and resp.url == "https://stripe.test/pc"
    payment = Payment.objects.get(status=Payment.Status.PENDING)
    assert payment.per_class_registration == reg
    assert payment.registration is None
    assert payment.amount == Decimal("50.00")
    item = fake_stripe.call_args.kwargs["line_items"][0]
    desc = item["price_data"]["product_data"]["description"]
    assert desc.startswith("2 classes")


def test_completing_the_payment_settles_the_classes_and_nothing_else(billed):
    event, user, reg = billed
    payment = Payment.objects.create(
        payment_type=Payment.Type.REGISTRATION, per_class_registration=reg,
        user=user, amount=Decimal("50.00"), method=Payment.Method.STRIPE,
    )
    complete_payment(payment)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.PAID
    assert not Charge.objects.filter(registration=reg).exists()
    assert per_class.open_balance(reg) == Decimal("0")
    assert member_account(user)["balance"] == Decimal("0")


def test_nothing_to_pay_bounces_back(client, fake_stripe):
    event = make_event()
    user = make_user()
    reg = enroll(user, event, make_tier(event))
    client.force_login(user)
    resp = client.post(reverse("registrations:pay_classes", args=[reg.id]))
    assert resp.status_code == 302
    fake_stripe.assert_not_called()


def test_someone_else_cannot_pay_your_classes(client, billed):
    event, user, reg = billed
    client.force_login(make_user("other@example.com"))
    resp = client.post(reverse("registrations:pay_classes", args=[reg.id]))
    assert resp.status_code == 404


# ---- pages -------------------------------------------------------------------


def test_confirm_page_shows_classes_and_balance(client, billed):
    event, user, reg = billed
    client.force_login(user)
    body = client.get(reverse("registrations:confirm", args=[reg.id])).content.decode()
    assert "Your classes" in body
    assert "$25.00 for each class you attend" in body
    assert "Pay $50.00" in body
    assert "(full refund)" not in body


def test_statement_labels_class_charges(client, billed):
    event, user, reg = billed
    staff = make_user("treasurer@example.com")
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    resp = client.get(reverse("treasurer_member_detail", args=[user.pk]))
    assert resp.status_code == 200
    assert f"{event.title}, class of" in resp.content.decode()


def test_faculty_see_attendance_on_the_event_page(client, billed):
    event, user, reg = billed
    staff = make_user("pc@example.com")
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    body = client.get(
        reverse("events:detail", args=[event.slug]) + "?view=faculty", follow=True,
    ).content.decode()
    assert 'id="attendance"' in body
    assert "$25.00/class" in body


# ---- the mark view ------------------------------------------------------------


def _fresh_row():
    event = make_event()
    user = make_user()
    reg = enroll(user, event, make_tier(event))
    session = make_session(event)
    per_class.run(now=session.end_at + timedelta(hours=1))
    return user, ClassAttendance.objects.get(registration=reg)


def test_member_marks_own_row(client):
    user, att = _fresh_row()
    client.force_login(user)
    client.post(reverse("events:attendance_mark", args=[att.pk]), {"present": "0"})
    att.refresh_from_db()
    assert not att.present and att.source == "student"


def test_another_member_cannot_mark_it(client):
    user, att = _fresh_row()
    client.force_login(make_user("nosy@example.com"))
    resp = client.post(reverse("events:attendance_mark", args=[att.pk]), {"present": "0"})
    assert resp.status_code == 403
    att.refresh_from_db()
    assert att.present


def test_staff_marks_as_faculty_and_locks(client):
    user, att = _fresh_row()
    staff = make_user("pc@example.com")
    staff.is_staff = True
    staff.save()
    client.force_login(staff)
    client.post(reverse("events:attendance_mark", args=[att.pk]), {"present": "0"})
    att.refresh_from_db()
    assert att.faculty_locked and att.source == "faculty"


def test_mark_view_is_post_only(client):
    user, att = _fresh_row()
    client.force_login(user)
    assert client.get(reverse("events:attendance_mark", args=[att.pk])).status_code == 405


def test_event_page_strip_says_billed_per_class(client):
    event = make_event()
    user = make_user()
    enroll(user, event, make_tier(event))
    client.force_login(user)
    body = client.get(reverse("events:detail", args=[event.slug]), follow=True).content.decode()
    assert "billed per class" in body
