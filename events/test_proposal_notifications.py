"""A proposal tells the Program Committee it awaits review, and tells its
proposer when the Committee decides (task #820)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from events.models import Event, EventProposal
from events.test_event_proposal import _MGMT, _future, _member, _pc_member
from notifications.categories import Category
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def _rows(user):
    return list(Notification.objects.filter(
        recipient=user, category=Category.EVENT_PROPOSAL,
    ))


def _proposal(proposer, **kw):
    start, end = _future()
    kw.setdefault("status", EventProposal.Status.PROPOSED)
    return EventProposal.objects.create(
        proposed_by=proposer, title="Seminar XX", event_type=Event.Type.SEMINAR,
        start_date=start, end_date=end, **kw,
    )


def _submit_payload(title="Seminar XX"):
    start, end = _future()
    return {
        **_MGMT, "event_type": Event.Type.SEMINAR, "title": title,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    }


def test_submitting_a_new_proposal_notifies_the_committee(client):
    pc = _pc_member()
    member = _member()
    client.force_login(member)
    client.post("/propose/", _submit_payload())
    [row] = _rows(pc)
    assert "Seminar XX" in row.title
    assert row.url == reverse("program_admin_proposals")
    assert not _rows(member)


def test_saving_a_draft_notifies_nobody(client):
    pc = _pc_member()
    client.force_login(_member())
    client.post("/propose/", {**_submit_payload(), "action": "save"})
    assert not _rows(pc)


def test_resaving_a_pending_proposal_does_not_ring_again(client):
    pc = _pc_member()
    member = _member()
    p = _proposal(member)
    client.force_login(member)
    client.post(f"/propose/{p.pk}/edit/", _submit_payload("Seminar XX, revised"))
    assert not _rows(pc)


def test_resubmitting_a_declined_proposal_says_so(client):
    pc = _pc_member()
    member = _member()
    p = _proposal(member, status=EventProposal.Status.DECLINED)
    client.force_login(member)
    client.post(f"/propose/{p.pk}/edit/", _submit_payload())
    [row] = _rows(pc)
    assert "resubmitted" in row.body


def test_submit_button_on_a_saved_proposal_notifies(client):
    pc = _pc_member()
    member = _member()
    p = _proposal(member, status=EventProposal.Status.SAVED)
    client.force_login(member)
    client.post(f"/propose/{p.pk}/submit/")
    [row] = _rows(pc)
    assert "submitted" in row.body and "resubmitted" not in row.body


def test_approval_notifies_the_proposer_with_the_event_link(client):
    member = _member()
    p = _proposal(member)
    client.force_login(_pc_member())
    client.post(f"/program-admin/proposals/{p.pk}/decide/", {"decision": "approve"})
    p.refresh_from_db()
    [row] = _rows(member)
    assert "approved" in row.title
    assert row.url == reverse("events:detail", args=[p.minted_event.slug])


def test_decline_notifies_the_proposer_with_the_note(client):
    member = _member()
    p = _proposal(member)
    client.force_login(_pc_member())
    client.post(f"/program-admin/proposals/{p.pk}/decide/",
                {"decision": "decline", "note": "Sharpen the focus."})
    [row] = _rows(member)
    assert "declined" in row.title and "Sharpen the focus." in row.body
    assert row.url == reverse("formation:formation") + "?tab=proposals"


def test_the_pcs_own_direct_create_notifies_nobody(client):
    pc = _pc_member()
    other = _pc_member("pc2@x.test")
    client.force_login(pc)
    client.post(reverse("program_admin_special_event_new"), {
        "event_type": "day_of_assembly", "title": "Assembly",
        "description": "9:00 Opening", "proposed_datetime": "2030-11-14T09:00",
        "location_kind": "online_insite", "fee_type": "free",
        "speakers-TOTAL_FORMS": "0", "speakers-INITIAL_FORMS": "0",
        "speakers-MIN_NUM_FORMS": "0", "speakers-MAX_NUM_FORMS": "1000",
        "action": "publish",
    })
    assert Event.objects.filter(title="Assembly").exists()
    assert not _rows(pc) and not _rows(other)
