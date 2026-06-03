"""TOTP two-factor helpers (bespoke, built on ``pyotp``).

The codebase rolls its own light token flows rather than pulling in
django-otp / django-two-factor-auth; this mirrors that style. The pieces:

- :func:`requires_2fa` — *who* must use a second factor. Reuses the existing
  admin predicate (:func:`core.staff.can_access_admin_tools`) so "admin role"
  has one definition site.
- :data:`SESSION_VERIFIED_KEY` — the per-session flag set once the member
  passes the challenge; the enforcement middleware reads it.
- enrollment / verification primitives over a :class:`accounts.TOTPDevice`.

Enforcement itself (forcing enrollment + the challenge) lives in
``accounts.middleware.TwoFactorEnforcementMiddleware`` and is gated by the
``TWO_FACTOR_ENFORCED`` setting (default off) so it can ship dark.
"""

from __future__ import annotations

import secrets

import pyotp
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

#: Session flag set to True once the user clears the 2FA challenge this session.
SESSION_VERIFIED_KEY = "2fa_verified"

#: How many one-time backup codes to mint at enrollment.
RECOVERY_CODE_COUNT = 10

#: Issuer label shown in the authenticator app.
ISSUER = "Lacanian School"


def requires_2fa(user) -> bool:
    """Whether ``user`` is in a role for which 2FA applies.

    This is the *eligibility* test, independent of whether enforcement is
    switched on. We tie it to the admin-tools gate: anyone who can reach a
    staff/governance control panel handles a second factor.
    """
    from core.staff import can_access_admin_tools

    return can_access_admin_tools(user)


def confirmed_device(user):
    """The user's confirmed :class:`TOTPDevice`, or ``None``."""
    if not getattr(user, "is_authenticated", False):
        return None
    device = getattr(user, "totp_device", None)
    return device if (device is not None and device.confirmed) else None


def has_confirmed_device(user) -> bool:
    return confirmed_device(user) is not None


def provisioning_uri(device) -> str:
    """The ``otpauth://`` URI to encode in the enrollment QR code."""
    return pyotp.TOTP(device.secret).provisioning_uri(
        name=device.user.email, issuer_name=ISSUER
    )


def qr_svg(uri: str) -> str:
    """An inline SVG QR code for ``uri`` (no Pillow dependency)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    return img.to_string(encoding="unicode")


def verify_code(device, code: str) -> bool:
    """True if ``code`` is a valid current TOTP for ``device``.

    ``valid_window=1`` tolerates one step of clock drift either side.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(device.secret).verify(code, valid_window=1)


def _normalize_recovery(code: str) -> str:
    return (code or "").strip().replace("-", "").replace(" ", "").lower()


def generate_recovery_codes(device) -> list[str]:
    """Replace ``device``'s recovery codes with a fresh batch.

    Returns the plaintext codes (shown to the member once); only hashes are
    stored. Formatted ``xxxx-xxxx`` for legibility.
    """
    from .models import RecoveryCode

    device.recovery_codes.all().delete()
    plaintext: list[str] = []
    rows = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(4)  # 8 hex chars
        pretty = f"{raw[:4]}-{raw[4:]}"
        plaintext.append(pretty)
        rows.append(RecoveryCode(device=device, code_hash=make_password(raw)))
    RecoveryCode.objects.bulk_create(rows)
    return plaintext


def verify_recovery_code(device, code: str) -> bool:
    """Consume a matching unused recovery code; True on success."""
    raw = _normalize_recovery(code)
    if not raw:
        return False
    from django.utils import timezone

    for rc in device.recovery_codes.filter(used_at__isnull=True):
        if check_password(raw, rc.code_hash):
            rc.used_at = timezone.now()
            rc.save(update_fields=["used_at"])
            return True
    return False


def new_secret() -> str:
    return pyotp.random_base32()


def enforcement_on() -> bool:
    """Whether the requirement (forced enrollment + challenge) is switched on.

    Off by default so the enrollment/verify flows can ship and be opted into
    without blocking current testers. Flip ``DJANGO_TWO_FACTOR_ENFORCED=true``
    at launch.
    """
    return bool(getattr(settings, "TWO_FACTOR_ENFORCED", False))
