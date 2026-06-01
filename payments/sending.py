"""Rate-limited, retry-on-throttle sending for the batch reminder jobs.

SES enforces a maximum send rate (1 msg/s in the sandbox, higher once
production access is granted). The reminder management commands
(`send_dues_reminders`, `send_tuition_reminders`,
`send_registration_reminders`) loop over many recipients; without pacing
they burst past that cap and SES returns a transient ``454 Throttling
failure`` for the tail of the batch, which the loops would otherwise count
as an error and silently skip until the next run.

:class:`ThrottledSender` spaces calls to stay under ``EMAIL_MAX_SEND_RATE``
and retries transient SMTP errors (4xx — chiefly the 454 throttle) with
exponential backoff. Permanent failures (5xx — e.g. an unverified identity
in the sandbox) are not retried; retrying them would only waste the rate
budget. The clock and sleep are injectable so tests don't actually wait.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from django.conf import settings


def _is_transient(exc: Exception) -> bool:
    """True for retryable SMTP failures (4xx), False for permanent ones.

    smtplib's response exceptions (``SMTPDataError``, ``SMTPSenderRefused``,
    …) carry an integer ``smtp_code``. A 5xx (e.g. 554 "Email address is not
    verified" in the SES sandbox) is permanent; a 4xx (454 throttling) is
    worth retrying. Exceptions without an ``smtp_code`` are treated as
    permanent.
    """
    code = getattr(exc, "smtp_code", None)
    return isinstance(code, int) and 400 <= code < 500


class ThrottledSender:
    """Pace calls to a send function and retry transient throttling.

    Usage::

        sender = ThrottledSender()
        sender.send(send_dues_reminder, user, period)

    ``send`` re-raises the underlying exception on a permanent failure or
    once retries are exhausted, so callers keep their existing per-recipient
    error handling.
    """

    def __init__(
        self,
        *,
        rate_per_sec: float | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if rate_per_sec is None:
            rate_per_sec = getattr(settings, "EMAIL_MAX_SEND_RATE", 1.0)
        self.min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self.max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_sent: float | None = None

    def _pace(self) -> None:
        """Sleep just long enough to keep successive sends ``min_interval`` apart."""
        if self.min_interval <= 0:
            return
        if self._last_sent is not None:
            wait = self.min_interval - (self._monotonic() - self._last_sent)
            if wait > 0:
                self._sleep(wait)
        self._last_sent = self._monotonic()

    def send(self, fn: Callable, *args, **kwargs):
        """Pace, call ``fn(*args, **kwargs)``, and retry transient throttling."""
        attempt = 0
        while True:
            self._pace()
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if _is_transient(exc) and attempt < self.max_retries:
                    attempt += 1
                    # Exponential backoff, at least one rate interval so we
                    # actually fall back under the cap before retrying.
                    self._sleep(max(self.min_interval * (2 ** attempt), self.min_interval))
                    continue
                raise
