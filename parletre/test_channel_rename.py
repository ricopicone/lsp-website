"""A renamed workgroup renames its auto-provisioned channels (task #568).

The three channels (Discuss / Chat / Video) take their name *and* description
from ``Workgroup.name`` at provisioning time. Nothing re-derived them, so a
retitled seminar left three stale copies in the Parlêtre sidebar.

Only channels still carrying the derived name are rewritten: ``Channel.name``
is editable in Django admin, and a deliberate rename must not be clobbered.
"""

from __future__ import annotations

import pytest

from parletre.models import Channel
from workgroups.models import Workgroup

pytestmark = pytest.mark.django_db


def _wg(name="Speech and Writing", kind=Workgroup.Kind.SEMINAR):
    return Workgroup.objects.create(kind=kind, name=name)


def test_renaming_a_workgroup_renames_all_three_channels():
    wg = _wg()

    wg.rename("Speech and Writing, Revisited")

    forum = wg.channels.get(kind=Channel.Kind.FORUM)
    chat = wg.channels.get(kind=Channel.Kind.CHAT)
    video = wg.channels.get(kind=Channel.Kind.VIDEO)
    assert forum.name == "Speech and Writing, Revisited"
    assert chat.name == "Speech and Writing, Revisited chat"
    assert video.name == "Speech and Writing, Revisited video"


def test_renaming_rewrites_the_channel_descriptions():
    wg = _wg()

    wg.rename("A New Name")

    forum = wg.channels.get(kind=Channel.Kind.FORUM)
    chat = wg.channels.get(kind=Channel.Kind.CHAT)
    video = wg.channels.get(kind=Channel.Kind.VIDEO)
    assert forum.description == "Discussion for A New Name."
    assert chat.description == "Chat for A New Name."
    assert video.description == "Video room for A New Name."


def test_channel_slugs_are_untouched_by_a_rename():
    """Slugs are the channel URLs and are unique — a rename must not move them."""
    wg = _wg()
    before = dict(wg.channels.values_list("kind", "slug"))

    wg.rename("Something Else Entirely")

    assert dict(wg.channels.values_list("kind", "slug")) == before


def test_a_hand_edited_channel_name_is_left_alone():
    wg = _wg()
    forum = wg.channels.get(kind=Channel.Kind.FORUM)
    forum.name = "The Letter (main room)"
    forum.save(update_fields=["name"])

    wg.rename("Speech and Writing, Revisited")

    forum.refresh_from_db()
    assert forum.name == "The Letter (main room)"
    # ...but its siblings, still on the derived name, do follow.
    assert wg.channels.get(kind=Channel.Kind.CHAT).name == (
        "Speech and Writing, Revisited chat"
    )


def test_a_plain_name_assignment_cascades_too():
    """The cartel details form and the Workspace Overview form both write
    ``name`` directly. The cascade hangs off ``save()`` rather than off the
    callers, so no edit surface has to remember to use ``rename``."""
    wg = _wg(kind=Workgroup.Kind.CARTEL)
    wg.name = "The Cartel, Renamed"
    wg.description = "new blurb"
    wg.save(update_fields=["name", "description"])

    assert wg.channels.get(kind=Channel.Kind.CHAT).name == "The Cartel, Renamed chat"


def test_an_unsaved_name_change_does_not_cascade():
    """A save that doesn't write ``name`` leaves the channels alone, even if the
    in-memory instance was mutated."""
    wg = _wg()
    wg.name = "Never Saved"
    wg.save(update_fields=["description"])

    assert wg.channels.get(kind=Channel.Kind.FORUM).name == "Speech and Writing"


def test_creating_a_workgroup_does_not_send_a_rename():
    """Provisioning already names the channels; a create must not also fire the
    cascade with no previous name to compare against."""
    seen = []
    from workgroups.models import renamed

    def _listen(sender, **kw):
        seen.append(kw["new_name"])

    renamed.connect(_listen, dispatch_uid="test_rename_listener")
    try:
        _wg(name="Brand New")
    finally:
        renamed.disconnect(dispatch_uid="test_rename_listener")
    assert seen == []


def test_rename_to_the_same_name_is_a_no_op():
    wg = _wg()

    assert wg.rename("Speech and Writing") is False


def test_rename_returns_true_when_it_changed():
    wg = _wg()

    assert wg.rename("Another Name") is True
    wg.refresh_from_db()
    assert wg.name == "Another Name"
