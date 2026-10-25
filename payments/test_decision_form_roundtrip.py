"""The tuition decision form, driven the way a browser drives it (task #820).

A plan request with no reasons used to redirect with "Please choose one of
the listed options", which was wrong, and drop what the member chose.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from core.browser_forms import browser_form
from payments.models import TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(client):
    user = User.objects.create_user(email="cand@example.com", password="x")
    user.profile.role = Profile.Role.CANDIDATE
    user.profile.save()
    client.force_login(user)
    return user


def test_a_plan_request_without_reasons_comes_back_to_its_field(client, candidate):
    period = TuitionPeriod.current()
    account = reverse("formation:formation") + "?tab=account"
    html = client.get(account).content.decode()
    data = browser_form(html, field="reasons")
    data["status"] = ["payment_plan"]
    data["reasons"] = [""]

    response = client.post(reverse("tuition"), data)

    assert response.status_code == 302
    assert response["Location"].endswith(f"#decision-{period.slug}")
    assert not TuitionEnrollment.objects.filter(user=candidate).exists()
    html = client.get(account).content.decode()
    assert "Please choose one of the listed options" not in html
    again = browser_form(html, field="reasons")
    assert again["status"] == ["payment_plan"]
    # The error sits with the reasons field, and only for one render.
    def reasons_block(page):
        return page.split('name="reasons"')[1].split("</div>")[0]

    assert "text-error text-sm" in reasons_block(html)
    assert "text-error text-sm" not in reasons_block(client.get(account).content.decode())
