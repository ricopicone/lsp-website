"""The web-developer API's bearer tokens.

The dev API (``/devapi/``) is the surface a Claude Code session — acting as the
site's web developer — uses to read and triage the work the site generates
(member suggestions today, more later). Rather than mint a parallel permission
system, a token is **bound to a real user**: every request is authorized as that
user through the same ``core.StaffRole`` checks the web UI uses, so the API can
never do anything its holder couldn't do by hand.

The raw token is shown **once**, at creation; only its SHA-256 hash is stored, so
a database leak can't reconstruct it. A short non-secret ``prefix`` is kept for
display ("which token is this?") and lookups stay O(1) on the indexed hash.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

#: Human-recognisable, greppable token prefix (the part before the secret).
TOKEN_PREFIX = "lspdev_"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DevApiToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="devapi_tokens",
        help_text="The token acts as this user; the API can do only what they can.",
    )
    label = models.CharField(
        max_length=120,
        help_text="Where this token lives, e.g. 'rico laptop — Claude Code'.",
    )
    #: SHA-256 hex of the full raw token. The raw token itself is never stored.
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    #: First few non-secret characters of the raw token, for identification.
    prefix = models.CharField(max_length=16, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked = models.BooleanField(
        default=False, help_text="Revoked tokens are rejected without being deleted."
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "dev API token"

    def __str__(self) -> str:
        state = " (revoked)" if self.revoked else ""
        return f"{self.label} · {self.prefix}…{state}"

    @classmethod
    def issue(cls, user, label: str) -> tuple[DevApiToken, str]:
        """Create a token for ``user`` and return ``(instance, raw_token)``.

        The raw token is returned only here — it is not recoverable afterwards.
        """
        raw = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        token = cls.objects.create(
            user=user,
            label=label,
            token_hash=_hash(raw),
            prefix=raw[: len(TOKEN_PREFIX) + 4],
        )
        return token, raw

    @classmethod
    def authenticate(cls, raw: str) -> DevApiToken | None:
        """Return the active token matching ``raw``, stamping ``last_used_at``.

        Returns ``None`` for an empty, unknown, or revoked token. Comparison is a
        single indexed hash lookup — no per-row secret comparison.
        """
        if not raw or not raw.startswith(TOKEN_PREFIX):
            return None
        try:
            token = cls.objects.select_related("user").get(token_hash=_hash(raw))
        except cls.DoesNotExist:
            return None
        if token.revoked:
            return None
        # Avoid auto_now side-effects / signals: a targeted UPDATE.
        now = timezone.now()
        cls.objects.filter(pk=token.pk).update(last_used_at=now)
        token.last_used_at = now
        return token
