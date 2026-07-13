"""Tests for advisor selection (advisorship)."""

from __future__ import annotations

import pytest
from django.core import mail
from django.urls import reverse

from accounts.advisor import (
    advisor_roles_for,
    current_advisor,
    eligible_advisors,
    set_advisor,
)
from accounts.models import Advisorship, Profile, User

pytestmark = pytest.mark.django_db


def _u(email, role=Profile.Role.EXTERNAL, standing=Profile.Standing.ACTIVE):
    u = User.objects.create_user(email=email, password="x")
    u.profile.role = role
    u.profile.standing = standing
    u.profile.save()
    return u


def test_advisor_roles_by_track():
    assert advisor_roles_for(Profile.Role.PRE_CANDIDATE) == {Profile.Role.ANALYST}
    assert advisor_roles_for(Profile.Role.CANDIDATE) == {Profile.Role.ANALYST}
    assert advisor_roles_for(Profile.Role.PRE_CANDIDATE_SCHOLAR) == {
        Profile.Role.SCHOLAR, Profile.Role.ANALYST,
    }


def test_eligible_advisors_pool():
    advisee = _u("ac@x.test", role=Profile.Role.PRE_CANDIDATE)
    analyst = _u("an@x.test", role=Profile.Role.ANALYST)
    scholar = _u("sc@x.test", role=Profile.Role.SCHOLAR)
    on_leave = _u("ol@x.test", role=Profile.Role.ANALYST, standing=Profile.Standing.ON_LEAVE)
    pool = set(eligible_advisors(advisee))
    assert analyst in pool
    assert scholar not in pool  # analyst track → analyst advisors only
    assert on_leave not in pool  # non-active excluded
    assert advisee not in pool

    scholar_advisee = _u("sa@x.test", role=Profile.Role.PRE_CANDIDATE_SCHOLAR)
    spool = set(eligible_advisors(scholar_advisee))
    assert analyst in spool and scholar in spool


def test_eligible_advisors_excludes_only_advisor_unavailable():
    """Analysts who declared they're NOT available as an Advisor are hidden;
    Yes and Unknown (never reported) both remain (see availability app)."""
    from availability.models import AnalystFunction, AvailabilitySpan
    from availability.services import set_availability

    advisor_fn = AnalystFunction.objects.get(slug="advisor")
    control_fn = AnalystFunction.objects.get(slug="control-analysis")

    advisee = _u("ac2@x.test", role=Profile.Role.PRE_CANDIDATE)
    says_yes = _u("yes@x.test", role=Profile.Role.ANALYST)
    says_no = _u("no@x.test", role=Profile.Role.ANALYST)
    unknown = _u("unk@x.test", role=Profile.Role.ANALYST)  # never reported
    no_for_control = _u("noc@x.test", role=Profile.Role.ANALYST)

    set_availability(says_yes.profile, advisor_fn, AvailabilitySpan.Status.YES)
    set_availability(says_no.profile, advisor_fn, AvailabilitySpan.Status.NO)
    # "No" for a *different* function must not hide them from the advisor pool.
    set_availability(no_for_control.profile, control_fn, AvailabilitySpan.Status.NO)

    pool = set(eligible_advisors(advisee))
    assert says_yes in pool
    assert unknown in pool  # unreported availability still eligible
    assert no_for_control in pool
    assert says_no not in pool  # explicit "not available as Advisor" → hidden


def test_advisor_availability_split_groups_unknown():
    from availability.models import AnalystFunction, AvailabilitySpan
    from availability.services import set_availability

    from accounts.advisor import advisor_availability_split

    advisor_fn = AnalystFunction.objects.get(slug="advisor")
    advisee = _u("ac3@x.test", role=Profile.Role.PRE_CANDIDATE)
    says_yes = _u("y2@x.test", role=Profile.Role.ANALYST)
    unknown = _u("u2@x.test", role=Profile.Role.ANALYST)
    set_availability(says_yes.profile, advisor_fn, AvailabilitySpan.Status.YES)

    available, unk = advisor_availability_split(advisee)
    assert says_yes in available and says_yes not in unk
    assert unknown in unk and unknown not in available


def test_advisor_select_form_renders_unknown_optgroup():
    from availability.models import AnalystFunction, AvailabilitySpan
    from availability.services import set_availability

    from accounts.forms import AdvisorSelectForm

    advisor_fn = AnalystFunction.objects.get(slug="advisor")
    advisee = _u("ac4@x.test", role=Profile.Role.PRE_CANDIDATE)
    says_yes = _u("y3@x.test", role=Profile.Role.ANALYST)
    _u("u3@x.test", role=Profile.Role.ANALYST)  # unknown
    set_availability(says_yes.profile, advisor_fn, AvailabilitySpan.Status.YES)

    html = str(AdvisorSelectForm(advisee=advisee)["advisor"])
    assert "<optgroup" in html and "Unknown availability" in html
    # A validating POST still resolves an unknown-availability analyst.
    form = AdvisorSelectForm({"advisor": str(_u("u4@x.test", role=Profile.Role.ANALYST).pk)},
                             advisee=advisee)
    assert form.is_valid(), form.errors


def test_set_advisor_records_and_supersedes():
    advisee = _u("adv@x.test", role=Profile.Role.PRE_CANDIDATE)
    a1 = _u("a1@x.test", role=Profile.Role.ANALYST)
    a2 = _u("a2@x.test", role=Profile.Role.ANALYST)
    set_advisor(advisee, a1, by=advisee)
    assert current_advisor(advisee) == a1
    # Changing supersedes the prior (one current per advisee).
    set_advisor(advisee, a2, by=advisee)
    assert current_advisor(advisee) == a2
    assert Advisorship.objects.filter(advisee=advisee, end_date__isnull=True).count() == 1
    assert Advisorship.objects.filter(advisee=advisee).count() == 2


def test_set_advisor_idempotent():
    advisee = _u("idem@x.test", role=Profile.Role.PRE_CANDIDATE)
    a1 = _u("a1b@x.test", role=Profile.Role.ANALYST)
    set_advisor(advisee, a1, by=advisee)
    set_advisor(advisee, a1, by=advisee)  # same advisor again
    assert Advisorship.objects.filter(advisee=advisee).count() == 1


def test_set_advisor_notifies(django_capture_on_commit_callbacks):
    advisee = _u("notif@x.test", role=Profile.Role.PRE_CANDIDATE)
    a1 = _u("advisor-notif@x.test", role=Profile.Role.ANALYST)
    with django_capture_on_commit_callbacks(execute=True):
        set_advisor(advisee, a1, by=advisee)
    assert any("Advisor" in m.subject and a1.email in m.to for m in mail.outbox)


def test_needs_advisor_property():
    assert _u("p1@x.test", role=Profile.Role.PRE_CANDIDATE).profile.needs_advisor is True
    assert _u("p2@x.test", role=Profile.Role.ANALYST).profile.needs_advisor is False


# ---- View ----


def test_advisor_view_requires_login(client):
    assert client.get(reverse("advisor_select")).status_code == 302


def test_in_training_member_selects_advisor(client):
    advisee = _u("v1@x.test", role=Profile.Role.CANDIDATE)
    analyst = _u("v-an@x.test", role=Profile.Role.ANALYST)
    client.force_login(advisee)
    resp = client.post(reverse("advisor_select"), {"advisor": analyst.pk})
    assert resp.status_code == 302
    assert current_advisor(advisee) == analyst


def test_advisor_select_redirects_to_formation_hub(client):
    """The Advisor picker lives on the Formation hub now — bare GETs land there."""
    member = _u("v1b@x.test", role=Profile.Role.CANDIDATE)
    client.force_login(member)
    resp = client.get(reverse("advisor_select"))
    assert resp.status_code == 302
    assert reverse("formation:formation") in resp.url


def test_non_in_training_sees_notice(client):
    """An analyst on the Formation hub sees that Advisors are for members in
    formation — not an Advisor picker."""
    member = _u("v2@x.test", role=Profile.Role.ANALYST)
    client.force_login(member)
    resp = client.get(reverse("formation:formation"))
    assert resp.status_code == 200
    assert b"chosen by members in formation" in resp.content
