"""Accounts tab — the unified roster with linkable filters (task #439)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import User
from payments.models import Charge, DuesPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture
def treasurer(client):
    u = User.objects.create_user(email="tr@x.test", password="x", is_staff=True)
    client.force_login(u)
    return u


def _member(email, role="candidate"):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


@pytest.fixture
def roster(treasurer):
    DuesPeriod.objects.all().delete()
    p = DuesPeriod.objects.create(
        name="AY 2026-2027", slug="ay-2026-2027",
        start_date=date(2026, 9, 1), due_date=date(2026, 9, 30),
        end_date=date(2027, 8, 31),
        dues_amount_pre_candidate=Decimal("50"),
        dues_amount_candidate=Decimal("100"),
        dues_amount_analyst=Decimal("150"),
    )
    owing = _member("owing@x.test")
    square = _member("square@x.test", "analyst")
    Charge.objects.create(user=owing, category=Charge.Category.DUES,
                          amount=Decimal("100"), effective_date=p.start_date,
                          dues_period=p)
    return owing, square


def test_accounts_lists_members_with_balances(client, roster):
    resp = client.get(reverse("treasurer_accounts"))
    assert resp.status_code == 200
    assert b"owing@x.test" in resp.content


def test_balance_filter_is_linkable(client, roster):
    resp = client.get(reverse("treasurer_accounts") + "?balance=owing")
    assert b"owing@x.test" in resp.content
    resp = client.get(reverse("treasurer_accounts") + "?balance=credit")
    assert b"owing@x.test" not in resp.content


def test_clear_link_hidden_with_no_filters_active(client, roster):
    """The default sort ("balance") must not count as an active filter, or
    the Clear link (gated on filter_qs) shows even with nothing to clear
    (task #439 fix 4c)."""
    resp = client.get(reverse("treasurer_accounts"))
    assert resp.context["filter_qs"] == ""
    assert b">Clear<" not in resp.content


def test_clear_link_shown_with_a_real_filter_active(client, roster):
    resp = client.get(reverse("treasurer_accounts") + "?balance=owing")
    assert resp.context["filter_qs"]
    assert b">Clear<" in resp.content


def test_search_filters_by_name_or_email(client, roster):
    resp = client.get(reverse("treasurer_accounts") + "?q=owing")
    assert b"owing@x.test" in resp.content
    assert b"square@x.test" not in resp.content


def test_requires_staff(client, roster):
    client.logout()
    outsider = User.objects.create_user(email="o@x.test", password="x")
    client.force_login(outsider)
    resp = client.get(reverse("treasurer_accounts"))
    assert resp.status_code in (302, 403)


def test_sync_button_mints_current_dues(client, roster, treasurer):
    Charge.objects.all().delete()
    resp = client.post(reverse("treasurer_sync_charges"))
    assert resp.status_code == 302
    # current period is 2026-27 only if today falls inside it; the view must
    # no-op gracefully otherwise — both outcomes are acceptable here, the
    # sync's own behavior is covered in test_charges_sync.py.


def test_old_tab_urls_redirect_to_accounts(client, roster):
    for name in ("treasurer_tuition", "treasurer_dues", "treasurer_members"):
        resp = client.get(reverse(name))
        assert resp.status_code == 302
        assert resp["Location"] == reverse("treasurer_accounts")


def test_tab_bar_is_seven_tabs(client, roster):
    from payments.views import TREASURER_TABS
    assert [k for k, _ in TREASURER_TABS] == [
        "overview", "accounts", "payments", "reconcile",
        "settings", "exports", "help"]


def test_help_tab_renders_rewritten_guide(client, roster):
    resp = client.get(reverse("treasurer_help"))
    assert resp.status_code == 200
    assert b"one account per member" in resp.content.lower()


def test_empty_ledger_notice_shown_and_hidden(client, treasurer, roster):
    from payments.models import Charge
    # roster fixture minted a charge → notice hidden
    resp = client.get(reverse("treasurer_accounts"))
    assert b"No charges have been minted yet" not in resp.content
    Charge.objects.all().delete()
    resp = client.get(reverse("treasurer_accounts"))
    assert b"No charges have been minted yet" in resp.content
