"""Tests for payments.sending.ThrottledSender (rate-limit + retry-on-throttle)."""

from __future__ import annotations

from smtplib import SMTPDataError

import pytest

from payments.sending import ThrottledSender, _is_transient


class FakeClock:
    """Monotonic clock that only advances when something sleeps."""

    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _sender(clock: FakeClock, *, rate_per_sec=1.0, max_retries=3) -> ThrottledSender:
    return ThrottledSender(
        rate_per_sec=rate_per_sec,
        max_retries=max_retries,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_first_send_does_not_sleep():
    clock = FakeClock()
    sender = _sender(clock)
    sender.send(lambda: "ok")
    assert clock.sleeps == []


def test_subsequent_sends_are_paced_to_the_rate():
    clock = FakeClock()
    sender = _sender(clock, rate_per_sec=2.0)  # min_interval = 0.5s
    sender.send(lambda: None)   # t=0, no sleep, last=0
    sender.send(lambda: None)   # no time elapsed -> must wait 0.5s
    sender.send(lambda: None)   # again 0.5s
    assert clock.sleeps == [0.5, 0.5]


def test_rate_zero_disables_pacing():
    clock = FakeClock()
    sender = _sender(clock, rate_per_sec=0)
    for _ in range(5):
        sender.send(lambda: None)
    assert clock.sleeps == []


def test_transient_454_is_retried_then_succeeds():
    clock = FakeClock()
    sender = _sender(clock, rate_per_sec=1.0, max_retries=3)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise SMTPDataError(454, b"Throttling failure: Maximum sending rate exceeded.")
        return "sent"

    assert sender.send(flaky) == "sent"
    assert calls["n"] == 2
    # One backoff sleep happened (>= the rate interval); pacing on the first
    # call did not (it was the first send).
    assert any(s >= 1.0 for s in clock.sleeps)


def test_transient_error_reraised_after_exhausting_retries():
    clock = FakeClock()
    sender = _sender(clock, rate_per_sec=1.0, max_retries=2)

    def always_throttled():
        raise SMTPDataError(454, b"Throttling failure")

    with pytest.raises(SMTPDataError):
        sender.send(always_throttled)


def test_permanent_5xx_is_not_retried():
    clock = FakeClock()
    sender = _sender(clock)
    calls = {"n": 0}

    def unverified():
        calls["n"] += 1
        raise SMTPDataError(554, b"Message rejected: Email address is not verified.")

    with pytest.raises(SMTPDataError):
        sender.send(unverified)
    assert calls["n"] == 1  # tried exactly once, no retry


def test_is_transient_classifies_by_code():
    assert _is_transient(SMTPDataError(454, b"throttle")) is True
    assert _is_transient(SMTPDataError(421, b"service unavailable")) is True
    assert _is_transient(SMTPDataError(554, b"rejected")) is False
    assert _is_transient(ValueError("no smtp_code")) is False
