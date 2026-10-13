"""The Election Administrator console (task #813)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import StaffRole
from elections import services
from elections.models import Election
from elections.tests.factories import (
    make_administrator, make_director, make_election, make_member, make_nomination,
)

pytestmark = pytest.mark.django_db
FMT = "%Y-%m-%dT%H:%M"


def _local(dt):
    return timezone.localtime(dt).strftime(FMT)


def _settings_post(e, **changes):
    data = {
        "title": e.title, "seats": e.seats, "count_method": e.count_method,
        "show_during_voting": e.show_during_voting, "show_results": e.show_results,
        "nominations_open_at": _local(e.nominations_open_at),
        "nominations_close_at": _local(e.nominations_close_at),
        "voting_open_at": _local(e.voting_open_at),
        "voting_close_at": _local(e.voting_close_at),
        "results_due": e.results_due.isoformat() if e.results_due else "",
    }
    data.update(changes)
    return data


@pytest.fixture
def admin_user():
    return make_administrator()


def test_anonymous_redirected_to_login(client):
    e = make_election()
    r = client.get(reverse("elections:admin_overview", args=[e.slug]))
    assert r.status_code == 302 and "login" in r.url


def test_web_coordinator_not_admitted(client):
    e = make_election()
    wc = make_member()
    StaffRole.objects.get(key=StaffRole.WEB_COORDINATOR).holders.add(wc)
    client.force_login(wc)
    assert client.get(reverse("elections:admin_overview", args=[e.slug])).status_code == 404
    assert client.get(reverse("elections:admin")).status_code == 404


def test_index_with_no_elections_offers_new(client, admin_user):
    client.force_login(admin_user)
    r = client.get(reverse("elections:admin"))
    assert r.status_code == 200 and reverse("elections:admin_new").encode() in r.content


def test_index_redirects_to_current(client, admin_user):
    e = make_election("nominating")
    client.force_login(admin_user)
    r = client.get(reverse("elections:admin"))
    assert r.status_code == 302 and r.url == reverse("elections:admin_overview", args=[e.slug])


def test_create_election(client, admin_user):
    client.force_login(admin_user)
    start = timezone.now() + timedelta(days=1)
    r = client.post(reverse("elections:admin_new"), {
        "title": "Board election 2026", "seats": 3,
        "nominations_open_at": _local(start),
        "nominations_close_at": _local(start + timedelta(days=14)),
        "voting_open_at": _local(start + timedelta(days=21)),
        "voting_close_at": _local(start + timedelta(days=35)),
        "count_method": "stv", "show_during_voting": "status", "show_results": "winners",
    })
    e = Election.objects.get()
    assert r.status_code == 302
    assert e.slug == "board-election-2026"
    assert e.results_due == timezone.localdate(e.voting_close_at) + timedelta(days=7)
    assert "Created the election" in e.audit_notes


def test_create_refuses_out_of_order_dates(client, admin_user):
    client.force_login(admin_user)
    start = timezone.now() + timedelta(days=1)
    r = client.post(reverse("elections:admin_new"), {
        "title": "Bad", "seats": 3,
        "nominations_open_at": _local(start + timedelta(days=14)),
        "nominations_close_at": _local(start),
        "voting_open_at": _local(start + timedelta(days=21)),
        "voting_close_at": _local(start + timedelta(days=35)),
        "count_method": "stv", "show_during_voting": "status", "show_results": "winners",
    })
    assert r.status_code == 200 and not Election.objects.exists()


def test_unchanged_passed_dates_save(client, admin_user):
    # The form posts minutes; the stored dates carry seconds. An untouched
    # passed date must not read as "changed".
    e = make_election("nominating")
    client.force_login(admin_user)
    r = client.post(reverse("elections:admin_settings", args=[e.slug]),
                    _settings_post(e, title="Renamed"))
    assert r.status_code == 302
    e.refresh_from_db()
    assert e.title == "Renamed"


def test_extension_allowed_and_audited(client, admin_user):
    e = make_election("nominating")
    client.force_login(admin_user)
    later = e.nominations_close_at + timedelta(hours=12)
    r = client.post(reverse("elections:admin_settings", args=[e.slug]),
                    _settings_post(e, nominations_close_at=_local(later)))
    assert r.status_code == 302
    e.refresh_from_db()
    assert abs(e.nominations_close_at - later) < timedelta(minutes=1)
    assert "Nominations close" in e.audit_notes


def test_passed_date_cannot_move(client, admin_user):
    e = make_election("nominating")
    client.force_login(admin_user)
    r = client.post(reverse("elections:admin_settings", args=[e.slug]), _settings_post(
        e, nominations_open_at=_local(timezone.now() + timedelta(hours=1))))
    assert r.status_code == 200 and b"already passed" in r.content


def test_new_date_cannot_be_in_the_past(client, admin_user):
    e = make_election("nominating")
    client.force_login(admin_user)
    r = client.post(reverse("elections:admin_settings", args=[e.slug]), _settings_post(
        e, nominations_close_at=_local(timezone.now() - timedelta(hours=1))))
    assert r.status_code == 200 and b"in the future" in r.content


def test_seats_locked_once_voting(client, admin_user):
    e = make_election("voting", seats=2)
    client.force_login(admin_user)
    client.post(reverse("elections:admin_settings", args=[e.slug]), _settings_post(e, seats=5))
    e.refresh_from_db()
    assert e.seats == 2


@pytest.mark.parametrize("tab", ["overview", "settings", "nominations", "roll", "count"])
def test_tabs_render(client, admin_user, tab):
    e = make_election("voting")
    make_nomination(e)
    client.force_login(admin_user)
    assert client.get(reverse(f"elections:admin_{tab}", args=[e.slug])).status_code == 200


def test_help_renders(client, admin_user):
    client.force_login(admin_user)
    r = client.get(reverse("elections:admin_help"))
    assert r.status_code == 200 and b"database" in r.content


def test_roll_shows_voted_not_time(client, admin_user):
    e = make_election("voting")
    cand = make_nomination(e)
    v = make_member(first="Vera", last="Voterson")
    services.cast_ballot(e, v, [cand.id])
    client.force_login(admin_user)
    html = client.get(reverse("elections:admin_roll", args=[e.slug])).content.decode()
    assert "Voterson" in html and "Voted" in html and "Not yet" in html


def test_override_via_console(client, admin_user):
    e = make_election("nominating")
    outsider = make_member(role="external", email="out@x.test")
    client.force_login(admin_user)
    client.post(reverse("elections:admin_override", args=[e.slug]),
                {"email": "OUT@x.test", "override": "add", "reason": "foundation"})
    assert outsider.id in services.roll_ids(e)


def test_action_publish_slate(client, admin_user):
    e = make_election("review")
    make_nomination(e)
    client.force_login(admin_user)
    client.post(reverse("elections:admin_action", args=[e.slug]), {"action": "publish_slate"})
    e.refresh_from_db()
    assert e.slate_published_at


def test_action_refusal_is_a_message(client, admin_user):
    e = make_election("review")
    make_nomination(e, status="pending")
    client.force_login(admin_user)
    r = client.post(reverse("elections:admin_action", args=[e.slug]),
                    {"action": "publish_slate"}, follow=True)
    assert b"has not decided every nomination" in r.content


def test_count_tab_shows_analyst_warning(client, admin_user):
    e = make_election("closed", seats=1)
    a = make_nomination(e, user=make_member(role="candidate", last="Cando"))
    services.ensure_roll_frozen(e)
    from elections import ballots
    ballots.cast(e, make_member(), [a.id])
    services.run_count(e, admin_user)
    client.force_login(admin_user)
    html = client.get(reverse("elections:admin_count", args=[e.slug])).content.decode()
    assert "Cando" in html and "three analysts" in html


def test_hub_card_for_administrator_only(client, admin_user):
    client.force_login(admin_user)
    assert reverse("elections:admin").encode() in client.get(reverse("admin_tools")).content


def test_appointments_warns_for_director(client):
    director, chair = make_director(), make_director()
    client.force_login(chair)
    r = client.post(reverse("board_appointments"), {
        "action": "appoint", "role": StaffRole.ELECTION_ADMINISTRATOR, "user": director.pk,
    }, follow=True)
    assert b"sitting director" in r.content


def test_directory_does_not_badge_role():
    import inspect

    from accounts import views
    assert "ELECTION_ADMINISTRATOR" in inspect.getsource(views._directory_qs)
