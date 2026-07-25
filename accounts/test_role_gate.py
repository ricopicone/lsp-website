"""Tuition clearance gate at the record_membership_change chokepoint (task #439)."""

from datetime import date, datetime
from datetime import timezone as tz
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict

from accounts.forms import MembershipChangeForm
from accounts.membership import current_academic_year_start, record_membership_change
from accounts.models import Profile, User
from payments.models import DuesPeriod, Payment, TuitionEnrollment, TuitionPeriod

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_periods():
    TuitionPeriod.objects.all().delete()
    DuesPeriod.objects.all().delete()


def _candidate_owing(email):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.save()
    tp = TuitionPeriod.objects.create(
        name="AY 2025-2026", slug="t-2025", start_date=date(2025, 9, 1),
        end_date=date(2026, 8, 31), decision_due_date=date(2025, 8, 31),
        tuition_amount=Decimal("2000"))
    TuitionEnrollment.objects.create(
        user=u, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
        source="staff")
    return u


def _candidate_settled(email):
    """A candidate with four fully-paid tuition years — clears the gate."""
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = "candidate"
    u.profile.save()
    for i in range(4):
        start = 2021 + i
        tp = TuitionPeriod.objects.create(
            name=f"AY {start}-{start + 1}", slug=f"t-{start}",
            start_date=date(start, 9, 1), end_date=date(start + 1, 8, 31),
            decision_due_date=date(start, 8, 31), tuition_amount=Decimal("2000"))
        TuitionEnrollment.objects.create(
            user=u, tuition_period=tp, status=TuitionEnrollment.Status.COMMITTED,
            source="staff")
    p = Payment.objects.create(
        user=u, payment_type=Payment.Type.TUITION, amount=Decimal("8000"),
        status=Payment.Status.SUCCEEDED, method=Payment.Method.OFFLINE)
    Payment.objects.filter(pk=p.pk).update(paid_at=datetime(2025, 10, 1, tzinfo=tz.utc))
    return u


def _promote(u, role="analyst"):
    return record_membership_change(
        u, role=role, standing=Profile.Standing.ACTIVE,
        effective_ay=current_academic_year_start())


def test_owing_candidate_cannot_become_analyst():
    u = _candidate_owing("rg1@x.test")
    with pytest.raises(ValidationError) as exc:
        _promote(u)
    assert any("uncovered" in m for m in exc.value.messages)
    assert any("treasurer account page" in m for m in exc.value.messages)
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"          # nothing changed
    assert u.tenures.count() <= 1                 # no tenure written


def test_external_to_analyst_passes_freely():
    u = User.objects.create_user(email="rg2@x.test", password="x")  # external
    _promote(u)
    u.profile.refresh_from_db()
    assert u.profile.role == "analyst"


def test_non_analyst_targets_unaffected():
    u = _candidate_owing("rg3@x.test")
    _promote(u, role="candidate")                 # lateral: no gate
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"


def test_voided_charges_do_not_create_covered_years():
    u = _candidate_owing("rg4@x.test")
    from payments.models import Charge
    for c in Charge.objects.filter(user=u):       # treasurer voids the charge
        c.status = Charge.Status.VOID
        c.staff_adjusted = True
        c.save()
    # …but 0 of 4 years covered still blocks:
    with pytest.raises(ValidationError):
        _promote(u)


def test_settled_candidate_promotes():
    u = _candidate_settled("rg4b@x.test")
    tenure = _promote(u)
    u.profile.refresh_from_db()
    assert u.profile.role == "analyst"
    assert tenure.role == "analyst"


# ---- MembershipChangeForm (Board membership admin) -------------------


def test_membership_form_blocks_owing_promotion():
    u = _candidate_owing("rg5@x.test")
    form = MembershipChangeForm(
        data={
            "role": "analyst", "standing": Profile.Standing.ACTIVE,
            "effective_ay": current_academic_year_start(),
        },
        member=u,
    )
    assert not form.is_valid()
    errors = form.errors.get("__all__") or form.errors.get("role") or []
    assert any("uncovered" in m for m in errors)


def test_membership_form_allows_settled():
    u = _candidate_settled("rg6@x.test")
    form = MembershipChangeForm(
        data={
            "role": "analyst", "standing": Profile.Standing.ACTIVE,
            "effective_ay": current_academic_year_start(),
        },
        member=u,
    )
    assert form.is_valid(), form.errors


# ---- ProfileAdminForm (Django admin) ----------------------------------


def test_profile_admin_form_blocks_role_edit():
    from accounts.admin import ProfileAdminForm

    u = _candidate_owing("rg7@x.test")
    data = model_to_dict(u.profile) | {"role": "analyst"}
    form = ProfileAdminForm(data=data, instance=u.profile)
    assert not form.is_valid()
    assert any("uncovered" in m for m in form.errors["role"])


def test_profile_admin_form_allows_non_gated_edits():
    from accounts.admin import ProfileAdminForm

    u = _candidate_owing("rg8@x.test")
    data = model_to_dict(u.profile) | {"bio": "Updated bio."}
    form = ProfileAdminForm(data=data, instance=u.profile)
    assert form.is_valid(), form.errors


def test_user_admin_inline_formset_blocks_role_edit(client):
    """The real surface a treasurer/admin uses is the Profile *inline* on the
    User change page, not the bare form — the gate has to survive the
    formset (task #443)."""
    from django.contrib.admin.sites import site

    from accounts.admin import ProfileInline, UserAdmin

    u = _candidate_owing("rg9@x.test")
    inline = ProfileInline(User, site)
    FormSet = inline.get_formset(_admin_request(), obj=u)
    prefix = FormSet.get_default_prefix()
    data = {
        f"{prefix}-TOTAL_FORMS": "1",
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1",
        f"{prefix}-0-id": str(u.profile.pk),
        f"{prefix}-0-user": str(u.pk),
        f"{prefix}-0-role": "analyst",
    }
    for field in ("default_billing_mode", "bio", "notes"):
        data[f"{prefix}-0-{field}"] = getattr(u.profile, field) or ""

    formset = FormSet(data=data, instance=u)
    assert not formset.is_valid()
    assert any("uncovered" in m
               for form in formset.forms
               for m in form.errors.get("role", []))
    u.profile.refresh_from_db()
    assert u.profile.role == "candidate"
    assert UserAdmin.inlines == [ProfileInline]  # the gate is actually wired


def test_user_admin_inline_formset_allows_a_clear_promotion(client):
    from django.contrib.admin.sites import site

    from accounts.admin import ProfileInline

    u = _candidate_settled("rg10@x.test")
    inline = ProfileInline(User, site)
    FormSet = inline.get_formset(_admin_request(), obj=u)
    prefix = FormSet.get_default_prefix()
    data = {
        f"{prefix}-TOTAL_FORMS": "1",
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1",
        f"{prefix}-0-id": str(u.profile.pk),
        f"{prefix}-0-user": str(u.pk),
        f"{prefix}-0-role": "analyst",
    }
    for field in ("default_billing_mode", "bio", "notes"):
        data[f"{prefix}-0-{field}"] = getattr(u.profile, field) or ""

    formset = FormSet(data=data, instance=u)
    assert formset.is_valid(), formset.errors


def _admin_request():
    from django.test import RequestFactory

    request = RequestFactory().request()
    request.user = User.objects.create_superuser(
        email=f"rg-admin-{User.objects.count()}@x.test", password="x")
    return request
