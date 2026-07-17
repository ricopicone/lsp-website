"""The My LSP 'My account' tab (task #439) — the member-facing view onto the
unified ledger. Replaces the old 'Dues' tab: one running balance, a
member-safe statement (no treasurer notes/provenance), the tuition-years
tile, and the existing 'Pay dues' flow reused verbatim.

See payments/test_member_account_actions.py for the treasurer-side
equivalent this mirrors, and payments/ledger.py for the account math."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, User
from formation.tabs import available_tabs
from payments.models import Charge, DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


def _user(email, role=Profile.Role.CANDIDATE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.save()
    return u


def _staff(email="staffacct@x.test"):
    return User.objects.create_user(email=email, password="x", is_staff=True)


# ---- 1. Renders with balance + statement -----------------------------------

def test_account_tab_shows_balance_and_statement(client):
    member = _user("acct@x.test")
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("100.00"),
        effective_date=date(2026, 9, 1),
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("40.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()

    assert "$60.00 owed" in body            # balance tile: 100 - 40
    assert "Sep 1, 2026" in body            # statement line date
    assert "$100.00" in body                # charge running balance
    assert "$60.00" in body                 # payment running balance


# ---- 2. Member-safety: treasurer notes never leak ---------------------------

def test_member_safety_hides_treasurer_notes(client):
    member = _user("safety@x.test")
    charge = Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("50.00"),
        effective_date=date(2026, 9, 1), notes="TREASURER-EYES-ONLY-MARKER",
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("10.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        notes="TREASURER-EYES-ONLY-MARKER", paid_at=timezone.now(),
    )

    client.force_login(member)
    member_body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "TREASURER-EYES-ONLY-MARKER" not in member_body

    client.force_login(_staff())
    treasurer_body = client.get(
        reverse("treasurer_member_detail", args=[member.id])).content.decode()
    assert "TREASURER-EYES-ONLY-MARKER" in treasurer_body
    assert charge.notes == "TREASURER-EYES-ONLY-MARKER"  # sanity: same row


def test_member_safety_hides_treasurer_notes_with_statement_actions_rendered(client):
    """Same leakage guard, extended to the statement-action modals (task
    #439): a retype/split/note-eligible row (no registration, succeeded,
    not split) exercises the real render path — the modals must render
    (sanity the assertion below isn't vacuous) without ever leaking
    Payment.notes/Charge.notes or the provenance ``source`` label."""
    from accounts.models import Source

    member = _user("safety2@x.test")
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, amount=Decimal("50.00"),
        effective_date=date(2026, 9, 1), notes="TREASURER-EYES-ONLY-MARKER-2",
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, amount=Decimal("10.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        notes="TREASURER-EYES-ONLY-MARKER-2", source=Source.VERIFIED,
        paid_at=timezone.now(),
    )

    client.force_login(member)
    body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    # Sanity: the statement actions actually rendered for this row.
    assert 'title="Re-categorize"' in body
    assert 'title="Split across categories"' in body
    assert 'title="Note"' in body
    # The leakage guard itself.
    assert "TREASURER-EYES-ONLY-MARKER-2" not in body
    assert "Verified against records" not in body


# ---- 3. Dues pay button gating ----------------------------------------------

def test_account_tab_pay_dues_button_present_when_unpaid(client):
    member = _user("duesunpaid@x.test")
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Pay $" in body
    assert "dues" in body.lower()


def test_account_tab_pay_dues_button_absent_when_paid(client):
    member = _user("duespaid@x.test")
    period = DuesPeriod.current()
    assert period is not None
    amount = period.amount_for_role(member.profile.role)
    Charge.objects.create(
        user=member, category=Charge.Category.DUES, dues_period=period,
        amount=amount, effective_date=period.start_date,
    )
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DUES, dues_period=period,
        amount=amount, status=Payment.Status.SUCCEEDED,
        method=Payment.Method.OFFLINE, paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Pay $" not in body
    assert "Dues paid" in body


# ---- 4. Decision-exemption vs payment-based "requirement met" --------------
#
# task #439: `payments.ledger.tuition_decision_exempt` (>=4 non-skipping
# enrollments) is the right rule for skipping the annual-decision nag but the
# WRONG rule for the "Requirement met" badge, which must mean PAID
# (`tuition_years_covered >= tuition_years_required`). A member can be
# decision-exempt with money still owed on those four years — see Rico's
# case below.

def _mint_four_tuition_years(member, paid_years=0):
    """Mint 4 non-skipping $800 tuition enrollments; optionally pay the
    oldest `paid_years` of them off in full."""
    for y in (2020, 2021, 2022, 2023):
        tp = TuitionPeriod.objects.create(
            name=f"AY {y}–{y + 1}", slug=f"ay-{y}-{y + 1}-reqmet-test",
            start_date=date(y, 9, 1), decision_due_date=date(y, 10, 1),
            end_date=date(y + 1, 8, 31), tuition_amount=Decimal("800.00"),
        )
        TuitionEnrollment.objects.create(
            user=member, tuition_period=tp,
            status=TuitionEnrollment.Status.COMMITTED,
        )
    if paid_years:
        Payment.objects.create(
            user=member, payment_type=Payment.Type.TUITION,
            amount=Decimal("800.00") * paid_years,
            status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
            paid_at=timezone.now(),
        )


def test_decision_exempt_hides_decision_form_on_account_tab(client):
    """4 non-skipping years, none paid: exempt from a fifth-year decision —
    but NOT "requirement met" (that's payment-based), so the quiet
    exemption note shows, not the paid-in-full notice."""
    member = _user("decexempt@x.test")
    _mint_four_tuition_years(member)
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "No annual tuition decision is needed, four years are on record." in body
    assert "Record decision" not in body
    assert "Requirement met" not in body


def test_requirement_met_badge_on_account_tile_when_paid(client):
    """The badge is payment-based: all four years fully paid off."""
    member = _user("reqmet2@x.test")
    _mint_four_tuition_years(member, paid_years=4)
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Requirement met" in body


def test_partial_coverage_rico_case_no_badge_but_decision_exempt(client):
    """Rico's case: 4 non-skipping enrollments, only 3 years' worth paid.
    Account tile shows progress (3 of 4) with NO "Requirement met" badge;
    the tuition-tab decision form stays hidden (still decision-exempt);
    Gate 1 (registrations._tuition_block_reason) does not block."""
    member = _user("rico@x.test")
    _mint_four_tuition_years(member, paid_years=3)
    client.force_login(member)

    account_body = client.get(
        reverse("formation:formation") + "?tab=account").content.decode()
    assert "3 of 4" in account_body
    assert "Requirement met" not in account_body
    assert "Record decision" not in account_body
    assert ("No annual tuition decision is needed, four years are on record."
            in account_body)

    from registrations.views import _tuition_block_reason
    assert _tuition_block_reason(member, event=None) is None


def test_paid_charges_no_enrollments_shows_met_banner_without_decision_form(client):
    """task #439 review finding #2: a member whose four tuition years are
    fully paid off via CHARGES with no TuitionEnrollment rows at all (e.g.
    minted entirely from approved pre-records history submissions) must be
    decision-exempt too — showing the "Requirement met" badge and no
    decision form, never both a "paid" badge and a contradictory 'record
    your decision' form."""
    member = _user("paidnoenroll@x.test")
    for y in (2016, 2017, 2018, 2019):
        Charge.objects.create(
            user=member, category=Charge.Category.TUITION,
            amount=Decimal("800.00"), effective_date=date(y, 9, 1))
    Payment.objects.create(
        user=member, payment_type=Payment.Type.TUITION, amount=Decimal("3200.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        paid_at=timezone.now(),
    )
    assert TuitionEnrollment.objects.filter(user=member).count() == 0
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Requirement met" in body
    assert "Record decision" not in body


def test_not_decision_exempt_still_shows_decision_form(client, db):
    member = _user("notreqmet@x.test")
    if TuitionPeriod.current() is None:
        TuitionPeriod.objects.create(
            name="Test AY", slug="test-ay-notreqmet",
            start_date=timezone.now().date(), decision_due_date=timezone.now().date(),
            end_date=timezone.now().date(), tuition_amount=Decimal("800.00"),
        )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Record decision" in body
    assert "No annual tuition decision is needed" not in body


# ---- 5. Tab list -------------------------------------------------------------

def test_available_tabs_shows_account_not_dues_or_tuition():
    u = _user("tablist@x.test")
    tabs = available_tabs(u, account=True)
    assert ("account", "Account") in tabs
    assert not any(key == "dues" for key, _ in tabs)
    assert not any(key == "tuition" for key, _ in tabs)


def test_formation_page_tab_bar_shows_account(client):
    member = _user("tabbar@x.test")
    client.force_login(member)
    body = client.get(reverse("formation:formation")).content
    assert b'href="?tab=account"' in body
    assert b">Account<" in body
    assert b'href="?tab=dues"' not in body
    assert b'href="?tab=tuition"' not in body


def test_old_tab_tuition_link_falls_back_to_account(client):
    """An old bookmarked/emailed ?tab=tuition link (the Tuition tab is
    retired, task #439) lands on the Account tab rather than 404ing or
    silently falling through to the Formation tab."""
    member = _user("oldlink@x.test")
    client.force_login(member)
    resp = client.get(reverse("formation:formation") + "?tab=tuition")
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "account"


def test_old_tab_tuition_link_falls_back_to_formation_when_no_money_tab(client):
    """If the member doesn't have the Account tab at all (no obligation, no
    history), the ?tab=tuition fallback still degrades gracefully to the
    default Formation tab rather than landing on an unavailable tab."""
    member = _user("oldlink2@x.test", role=Profile.Role.MEMBER)
    client.force_login(member)
    resp = client.get(reverse("formation:formation") + "?tab=tuition")
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "formation"


# ---- 6. Decision form lives inside the Account tab ---------------------------

def test_decision_form_posts_from_within_account_tab(client, db):
    """The tuition decision form (moved verbatim from the retired Tuition
    tab) still works when it's POSTed from inside the Account tab."""
    from payments.models import TuitionPeriod

    member = _user("decideacct@x.test")
    if TuitionPeriod.current() is None:
        TuitionPeriod.objects.create(
            name="Test AY", slug="test-ay-decideacct",
            start_date=timezone.now().date(), decision_due_date=timezone.now().date(),
            end_date=timezone.now().date(), tuition_amount=Decimal("800.00"),
        )
    client.force_login(member)
    resp = client.post(reverse("tuition"), {"status": "committed"})
    assert resp.status_code == 302
    assert "tab=account" in resp.url

    enr = TuitionEnrollment.objects.get(user=member)
    assert enr.status == TuitionEnrollment.Status.COMMITTED

    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert "Committed" in body


# ---- 7. Statement actions — retype/split/note buttons on own rows ----------

def test_statement_actions_render_on_own_payment_rows(client):
    member = _user("actions@x.test")
    Payment.objects.create(
        user=member, payment_type=Payment.Type.DONATION, amount=Decimal("40.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert 'title="Re-categorize"' in body
    assert 'title="Split across categories"' in body
    assert 'title="Note"' in body
    assert reverse("my_payment_note", args=[Payment.objects.get(user=member).id]) in body


def test_statement_actions_hidden_on_registration_settling_payment(client):
    """Retype and split are refused for registration-settling payments (the
    registration owns that link) — the buttons don't even render."""
    from events.models import Audience, Event, PriceTier
    from registrations.models import Registration

    member = _user("actionsreg@x.test")
    event = Event.objects.create(
        title="Gated Seminar", slug="gated-seminar-acct",
        start_date=date(2026, 9, 1), end_date=date(2026, 12, 15),
    )
    tier = PriceTier.objects.create(
        event=event, audience=Audience.ALL, base_amount=Decimal("50"))
    registration = Registration.objects.create(
        user=member, event=event, price_tier=tier,
        quoted_amount=Decimal("50"), status=Registration.Status.PAID)
    payment = Payment.objects.create(
        user=member, payment_type=Payment.Type.REGISTRATION, amount=Decimal("50"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        registration=registration, paid_at=timezone.now(),
    )
    client.force_login(member)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert 'title="Re-categorize"' not in body
    assert 'title="Split across categories"' not in body
    # The note action is still available (it's payment-only, not
    # registration-gated).
    assert reverse("my_payment_note", args=[payment.id]) in body


def test_split_action_hidden_when_already_split(client):
    """A split row's Split button is hidden (a split row can't be
    re-split); its Re-categorize button stays available (full parity —
    task #439 deliberately allows a member to re-categorize their own
    split children)."""
    parent = Payment.objects.create(
        user=_user("actionssplit@x.test"), payment_type=Payment.Type.TUITION,
        amount=Decimal("400.00"), status=Payment.Status.SUCCEEDED,
        method=Payment.Method.OFFLINE, paid_at=timezone.now(),
    )
    child = Payment.objects.create(
        user=parent.user, payment_type=Payment.Type.DUES, amount=Decimal("150.00"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE,
        split_from=parent, paid_at=parent.paid_at,
    )
    client.force_login(parent.user)
    body = client.get(reverse("formation:formation") + "?tab=account").content.decode()
    assert body.count('title="Re-categorize"') == 2   # parent + child
    assert body.count('title="Split across categories"') == 0
    assert reverse("my_payment_note", args=[child.id]) in body
