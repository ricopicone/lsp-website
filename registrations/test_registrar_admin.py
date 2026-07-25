"""Registration Admin console (/admin-tools/registrations/) — task #470."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Profile, User
from core.models import StaffRole
from events.models import Audience, Event, PriceTier
from registrations.models import Registration

pytestmark = pytest.mark.django_db


def test_registrar_staff_role_seeded():
    role = StaffRole.objects.get(key=StaffRole.REGISTRAR)
    assert role.name == "Registrar"


def test_registrar_role_never_badges_directory():
    from accounts.views import _badge_staff_roles

    u = User.objects.create_user(email="reg@x.test", password="x")
    StaffRole.objects.get(key=StaffRole.REGISTRAR).holders.add(u)
    # Simulate the _directory_qs prefetch attributes.
    u.public_staff_roles = list(
        StaffRole.objects.filter(holders=u).exclude(
            key__in=(StaffRole.LSP_STAFF, StaffRole.REGISTRAR)
        )
    )
    u.active_public_memberships = []
    assert _badge_staff_roles(u) == []


# ---- shared fixtures -----------------------------------------------------


def _event(slug="ev", status=Event.Status.OPEN, **kw):
    e = Event.objects.create(
        title=f"Event {slug}", slug=slug, event_type=Event.Type.SEMINAR,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=status, **kw,
    )
    PriceTier.objects.create(event=e, audience=Audience.ALL, base_amount=Decimal("50.00"))
    return e


def _member(email="m@x.test"):
    u = User.objects.create_user(email=email, password="x", first_name="M", last_name="Ember")
    u.profile.role = Profile.Role.MEMBER
    u.profile.save()
    return u


def _reg(event, user, status=Registration.Status.AWAITING_PAYMENT, amount="50.00"):
    return Registration.objects.create(
        user=user, event=event, price_tier=event.price_tiers.first(),
        quoted_amount=Decimal(amount), status=status,
    )


# ---- comp service --------------------------------------------------------


def test_comp_registration_service_flips_notes_mints_and_notifies():
    from payments.models import Charge
    from registrations.services import comp_registration

    staff = User.objects.create_user(email="s@x.test", password="x", is_staff=True)
    reg = _reg(_event("comp-ev"), _member("c@x.test"))
    comped, email_ok = comp_registration(reg, staff, via="registration admin")

    reg.refresh_from_db()
    assert comped and email_ok
    assert reg.status == Registration.Status.COMPED
    assert "Comped by s@x.test via registration admin." in reg.staff_notes
    assert Charge.objects.filter(registration=reg).exists()


def test_comp_registration_service_refuses_non_awaiting():
    from registrations.services import comp_registration

    staff = User.objects.create_user(email="s2@x.test", password="x", is_staff=True)
    reg = _reg(_event("comp-ev2"), _member("c2@x.test"),
               status=Registration.Status.PAID)
    comped, _ = comp_registration(reg, staff)
    reg.refresh_from_db()
    assert not comped and reg.status == Registration.Status.PAID


# ---- console gate --------------------------------------------------------

from committees.models import Committee  # noqa: E402


def _registrar(email="registrar@x.test"):
    u = User.objects.create_user(email=email, password="x")
    StaffRole.objects.get(key=StaffRole.REGISTRAR).holders.add(u)
    return u


def _web_coordinator(email="wc@x.test"):
    u = User.objects.create_user(email=email, password="x")
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(u)
    return u


def _pc_member(email="pc@x.test"):
    u = User.objects.create_user(email=email, password="x")
    committee, _ = Committee.objects.get_or_create(
        slug="programming-committee",
        defaults={"name": "Programming Committee"},
    )
    committee.add_member(u, start_date=date(2026, 1, 1))
    return u


class TestGate:
    URL = "/admin-tools/registrations/"

    @pytest.mark.parametrize("maker", [_registrar, _web_coordinator, _pc_member])
    def test_admitted_roles(self, client, maker):
        client.force_login(maker())
        assert client.get(self.URL).status_code == 200

    def test_django_staff_admitted(self, client):
        u = User.objects.create_user(email="st@x.test", password="x", is_staff=True)
        client.force_login(u)
        assert client.get(self.URL).status_code == 200

    def test_plain_member_404(self, client):
        client.force_login(_member("plain@x.test"))
        assert client.get(self.URL).status_code == 404

    def test_anonymous_redirects_to_login(self, client):
        resp = client.get(self.URL)
        assert resp.status_code == 302 and "login" in resp.url


def test_registrations_tab_lists_and_filters(client):
    e1, e2 = _event("list-a"), _event("list-b")
    m1, m2 = _member("a@x.test"), _member("b@x.test")
    _reg(e1, m1)
    _reg(e2, m2, status=Registration.Status.PENDING_APPROVAL)
    client.force_login(_registrar("r2@x.test"))

    resp = client.get(reverse("registrations:registrar"))
    body = resp.content.decode()
    assert "a@x.test" in body and "b@x.test" in body
    assert "Needs attention" in body  # pending strip

    resp = client.get(reverse("registrations:registrar"), {"event": e1.pk})
    body = resp.content.decode()
    assert "a@x.test" in body and "b@x.test" not in body

    resp = client.get(reverse("registrations:registrar"),
                      {"status": Registration.Status.PENDING_APPROVAL})
    body = resp.content.decode()
    assert "b@x.test" in body and "a@x.test" not in body

    resp = client.get(reverse("registrations:registrar"), {"q": "a@x.test"})
    body = resp.content.decode()
    assert "a@x.test" in body and "b@x.test" not in body


def test_bad_date_filter_does_not_500(client):
    _reg(_event("bad-date"), _member("bd@x.test"))
    client.force_login(_registrar("rbd@x.test"))
    resp = client.get(reverse("registrations:registrar"), {"since": "not-a-date"})
    assert resp.status_code == 200


class TestRowActions:
    def _login_registrar(self, client, email):
        u = _registrar(email)
        client.force_login(u)
        return u

    def test_approve(self, client, django_capture_on_commit_callbacks):
        reg = _reg(_event("act-a"), _member("aa@x.test"),
                   status=Registration.Status.PENDING_APPROVAL)
        u = self._login_registrar(client, "ra@x.test")
        with django_capture_on_commit_callbacks(execute=True):
            resp = client.post(
                reverse("registrations:registrar_approve", args=[reg.id]))
        reg.refresh_from_db()
        assert resp.status_code == 302
        assert reg.status == Registration.Status.AWAITING_PAYMENT
        assert reg.approved_by == u

    def test_decline_with_reason(self, client, django_capture_on_commit_callbacks):
        reg = _reg(_event("act-b"), _member("bb@x.test"),
                   status=Registration.Status.PENDING_APPROVAL)
        self._login_registrar(client, "rb@x.test")
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("registrations:registrar_decline", args=[reg.id]),
                        {"reason": "Full"})
        reg.refresh_from_db()
        assert reg.status == Registration.Status.DECLINED
        assert reg.decline_reason == "Full"

    def test_comp(self, client, django_capture_on_commit_callbacks):
        reg = _reg(_event("act-c"), _member("cc@x.test"))
        self._login_registrar(client, "rc@x.test")
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("registrations:registrar_comp", args=[reg.id]))
        reg.refresh_from_db()
        assert reg.status == Registration.Status.COMPED
        assert "via registration admin." in reg.staff_notes

    def test_comp_wrong_status_refused(self, client):
        reg = _reg(_event("act-d"), _member("dd@x.test"),
                   status=Registration.Status.PAID)
        self._login_registrar(client, "rd@x.test")
        client.post(reverse("registrations:registrar_comp", args=[reg.id]))
        reg.refresh_from_db()
        assert reg.status == Registration.Status.PAID

    def test_note_appends_dated_line(self, client):
        reg = _reg(_event("act-e"), _member("ee@x.test"))
        self._login_registrar(client, "re@x.test")
        client.post(reverse("registrations:registrar_note", args=[reg.id]),
                    {"note": "Spoke by phone; paying by check."})
        reg.refresh_from_db()
        assert "Spoke by phone; paying by check." in reg.staff_notes
        assert "re@x.test" in reg.staff_notes

    def test_actions_gated(self, client):
        reg = _reg(_event("act-f"), _member("ff@x.test"))
        client.force_login(_member("intruder@x.test"))
        resp = client.post(reverse("registrations:registrar_comp", args=[reg.id]))
        assert resp.status_code == 404
        reg.refresh_from_db()
        assert reg.status == Registration.Status.AWAITING_PAYMENT


def test_csv_export_honors_filters(client):
    e1, e2 = _event("csv-a"), _event("csv-b")
    _reg(e1, _member("csva@x.test"))
    _reg(e2, _member("csvb@x.test"))
    client.force_login(_registrar("rcsv@x.test"))

    resp = client.get(reverse("registrations:registrar_csv"), {"event": e1.pk})
    body = resp.content.decode()
    assert resp["Content-Type"].startswith("text/csv")
    assert "csva@x.test" in body and "csvb@x.test" not in body
    header = body.splitlines()[0]
    assert header == ("event,first_name,last_name,email,role,tier,amount,"
                      "status,pricing_code,registered_at")


class TestEventsTab:
    def test_lists_current_and_upcoming_events_with_counts(self, client):
        e = _event("tab-a")
        _reg(e, _member("ta@x.test"), status=Registration.Status.PAID)
        _reg(e, _member("tb@x.test"))
        client.force_login(_registrar("rev@x.test"))
        resp = client.get(reverse("registrations:registrar_events"))
        body = resp.content.decode()
        assert "Event tab-a" in body
        assert "Close registration" in body  # e is OPEN

    def test_toggle_open_close(self, client):
        e = _event("tab-b", status=Event.Status.DRAFT)
        client.force_login(_registrar("rev2@x.test"))
        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "open"})
        e.refresh_from_db()
        assert e.status == Event.Status.OPEN

        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "close"})
        e.refresh_from_db()
        assert e.status == Event.Status.CLOSED

        # Reopen after close.
        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "open"})
        e.refresh_from_db()
        assert e.status == Event.Status.OPEN

    def test_close_only_applies_to_open(self, client):
        e = _event("tab-c", status=Event.Status.DRAFT)
        client.force_login(_registrar("rev3@x.test"))
        client.post(reverse("registrations:registrar_event_toggle", args=[e.pk]),
                    {"action": "close"})
        e.refresh_from_db()
        assert e.status == Event.Status.DRAFT


def test_help_tab_renders(client):
    client.force_login(_registrar("r3@x.test"))
    resp = client.get(reverse("registrations:registrar_help"))
    assert resp.status_code == 200
    assert "Registration Admin" in resp.content.decode()
