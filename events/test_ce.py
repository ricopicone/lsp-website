"""CE credits + accreditor organizations (task #486)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import User
from events.ce import CECreditBasis, credits_label
from events.models import CEOrganization, CEOrganizationLogo, Event, EventProposal

# ---- Credit-line phrasing ----------------------------------------------


def test_label_is_empty_when_ce_is_off():
    assert credits_label(False, Decimal("2"), CECreditBasis.TOTAL) == ""


def test_label_without_a_count_says_credits_are_available():
    assert credits_label(True, None, CECreditBasis.TOTAL) == "CE credits available."


def test_label_for_a_total():
    assert credits_label(True, Decimal("6.00"), CECreditBasis.TOTAL) == (
        "Approved for 6 CE credits."
    )


def test_label_per_meeting():
    assert credits_label(True, Decimal("2.00"), CECreditBasis.PER_MEETING) == (
        "Approved for 2 CE credits per meeting."
    )


def test_label_keeps_a_half_credit():
    assert credits_label(True, Decimal("1.50"), CECreditBasis.TOTAL) == (
        "Approved for 1.5 CE credits."
    )


def test_label_singular_for_one_credit():
    assert credits_label(True, Decimal("1.00"), CECreditBasis.PER_MEETING) == (
        "Approved for 1 CE credit per meeting."
    )


def test_label_does_not_go_scientific_on_round_tens():
    assert credits_label(True, Decimal("20.00"), CECreditBasis.TOTAL) == (
        "Approved for 20 CE credits."
    )


# ---- CEOrganization -----------------------------------------------------


@pytest.mark.django_db
def test_organization_names_are_unique_case_insensitively():
    CEOrganization.objects.create(name="American Psychological Association")
    with pytest.raises(IntegrityError), transaction.atomic():
        CEOrganization.objects.create(name="american psychological association")


def test_negative_credits_are_rejected():
    """Checked on the field's validators rather than through full_clean(), so
    the test can't fail for unrelated missing-field reasons."""
    field = Event._meta.get_field("ce_credits")
    with pytest.raises(ValidationError):
        field.run_validators(Decimal("-1"))


# ---- Proposal → Event carry --------------------------------------------


@pytest.mark.django_db
def test_approve_carries_ce_intent_onto_the_minted_event():
    proposer = User.objects.create_user(email="proposer@x.test")
    reviewer = User.objects.create_user(email="pc@x.test")
    proposal = EventProposal.objects.create(
        proposed_by=proposer,
        event_type=Event.Type.SEMINAR,
        title="Seminar on the Sinthome",
        description="A year with Seminar XXIII.",
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        offers_ce=True,
        ce_credits=Decimal("2.00"),
        ce_credits_basis=CECreditBasis.PER_MEETING,
    )
    event = proposal.approve(reviewer)
    assert event.offers_ce is True
    assert event.ce_credits == Decimal("2.00")
    assert event.ce_credits_basis == CECreditBasis.PER_MEETING
    assert event.ce_credits_label == "Approved for 2 CE credits per meeting."


# ---- Logo set ----------------------------------------------------------


def _webp_blob():
    """A tiny real WebP, the shape normalize_logo() returns."""
    import io

    from django.core.files.base import ContentFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(buf, format="WEBP")
    return ContentFile(buf.getvalue())


@pytest.mark.django_db
def test_add_logos_appends_in_order(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="APA")

    org.add_logos([_webp_blob(), _webp_blob()])
    org.add_logos([_webp_blob()])

    logos = list(org.logos.all())
    assert len(logos) == 3
    assert [logo.sort_order for logo in logos] == [1, 2, 3]
    assert all(logo.image.name.endswith(".webp") for logo in logos)


@pytest.mark.django_db
def test_deleting_an_organization_takes_its_logos(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    org = CEOrganization.objects.create(name="GPPA")
    org.add_logos([_webp_blob()])
    org.delete()
    assert CEOrganizationLogo.objects.count() == 0


@pytest.mark.django_db
def test_the_single_logo_field_is_gone():
    """Its replacement is the related set; a stray `logo` attribute would mean
    the migration left the old column behind."""
    field_names = {f.name for f in CEOrganization._meta.get_fields()}
    assert "logo" not in field_names
    assert "logos" in field_names
