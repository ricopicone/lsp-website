"""The faculty pricing-code panel, driven the way a browser drives it (task #820).

The panel posts and redirects back to the Roster tab, so a refused code used to
lose what was typed and report its error at the top of the page, far from the
form. And a per-class seminar offered a payment plan the server then refused.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from core.browser_forms import browser_form
from events.models import PricingCode
from events.per_class_fixtures import make_event, make_tier, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(client):
    event = make_event("Clinical Cases", per_class=False, event_type="seminar")
    make_tier(event, "500.00")
    event.ensure_workgroup()
    faculty = make_user("fac@example.com")
    event.add_faculty(faculty)
    client.force_login(faculty)
    return event


def _roster(client, event):
    url = event.workgroup.get_absolute_url() + "?tab=roster"
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


def test_a_refused_code_comes_back_with_its_values_and_errors(client, setup):
    event = setup
    data = browser_form(_roster(client, event), action="/codes/")
    data["pricing_mode"] = [PricingCode.Mode.PERCENT_OFF]
    data["amount_or_percent"] = ["150"]
    data["max_uses"] = ["3"]

    response = client.post(reverse("events:generate_code", args=[event.slug]), data)

    assert response.status_code == 302
    assert response["Location"].endswith("#generate-code")
    assert not PricingCode.objects.exists()
    html = _roster(client, event)
    assert "The code wasn&#x27;t created" in html or "The code wasn't created" in html
    assert "A percent off must be between 0 and 100." in html
    again = browser_form(html, action="/codes/")
    assert again["amount_or_percent"] == ["150"]
    assert again["max_uses"] == ["3"]
    # One render only: the next visit is a clean form.
    assert "The code wasn" not in _roster(client, event)


def test_a_minted_code_says_so_and_lands_on_the_list(client, setup):
    event = setup
    data = browser_form(_roster(client, event), action="/codes/")
    data["pricing_mode"] = [PricingCode.Mode.FIXED_AMOUNT]
    data["amount_or_percent"] = ["100"]

    response = client.post(
        reverse("events:generate_code", args=[event.slug]), data, follow=True,
    )

    code = PricingCode.objects.get()
    assert response.redirect_chain[0][0].endswith("#existing-codes")
    assert f"Code {code.code} created" in response.content.decode()


def test_a_per_class_seminar_offers_no_payment_plan(client):
    event = make_event("Beyond Principle", per_class=True, event_type="seminar")
    make_tier(event, "25.00")
    event.ensure_workgroup()
    faculty = make_user("fac@example.com")
    event.add_faculty(faculty)
    client.force_login(faculty)

    html = _roster(client, event)
    data = browser_form(html, action="/codes/")
    assert "installments" not in data
    assert "Full price" not in html.split('id="generate-code"')[1].split("</form>")[0]

    data["pricing_mode"] = [PricingCode.Mode.FIXED_AMOUNT]
    data["amount_or_percent"] = ["15"]
    data["valid_until"] = [""]
    client.post(reverse("events:generate_code", args=[event.slug]), data)

    code = PricingCode.objects.get()
    assert code.per_class and code.installments == 1
    assert code.valid_until is None


def test_faculty_can_give_a_reason_when_declining(client, setup):
    """The decline view took a reason the roster form never asked for (#820)."""
    from decimal import Decimal

    from registrations.models import Registration

    event = setup
    member = make_user("waiting@example.com")
    reg = Registration.objects.create(
        user=member, event=event, price_tier=event.price_tiers.get(),
        quoted_amount=Decimal("500.00"),
        status=Registration.Status.PENDING_APPROVAL,
    )
    data = browser_form(_roster(client, event), action=f"/registrations/{reg.pk}/decline/")
    data["reason"] = ["The seminar is full this term."]

    client.post(reverse("registrations:decline", args=[reg.pk]), data)

    reg.refresh_from_db()
    assert reg.status == Registration.Status.DECLINED
    assert reg.decline_reason == "The seminar is full this term."
