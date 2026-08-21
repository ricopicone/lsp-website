"""Breakout rooms (task #624).

Gardner asked whether a seminar could break into smaller groups. Daily supports
it as a room property, Prebuilt-only (which is what we run), and it needs an
owner in the call to create the rooms. Our owners are faculty and group leads,
which is exactly who should be splitting a class up.
"""

from video import services


class _Owner:
    recording_mode = "on_demand"


def test_rooms_enable_breakout_rooms():
    """_desired_properties is the single source of truth that ensure_room
    reconciles against the live room (task #475), so existing rooms pick this
    up at the next join with no backfill."""
    assert services._desired_properties(_Owner())["enable_breakout_rooms"] is True


def test_breakout_rooms_survive_a_recording_off_group():
    """Turning the Record button off is orthogonal to splitting into groups."""

    class _NoRecording:
        recording_mode = "off"

    props = services._desired_properties(_NoRecording())
    assert props["enable_recording"] is False
    assert props["enable_breakout_rooms"] is True
