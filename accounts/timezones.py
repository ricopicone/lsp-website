"""Curated IANA timezone choices for Profile.timezone.

Picked from where LSP members actually live (per the directory) plus the
most commonly-needed adjacent zones. Free-text IANA names work too —
just append to the list if a member needs something not here.

The ``LSP_TIMEZONES`` list is the form-choice source; ``IS_VALID`` is a
set for fast validation in the middleware.
"""

from __future__ import annotations

#: (IANA name, display label) pairs.
LSP_TIMEZONES: list[tuple[str, str]] = [
    # The Americas
    ("America/Los_Angeles", "Pacific (Los Angeles)"),
    ("America/Denver",      "Mountain (Denver)"),
    ("America/Chicago",     "Central (Chicago)"),
    ("America/New_York",    "Eastern (New York)"),
    ("America/Halifax",     "Atlantic (Halifax)"),
    ("America/Mexico_City", "Mexico City"),
    ("America/Sao_Paulo",   "São Paulo"),
    ("America/Buenos_Aires", "Buenos Aires"),
    # Europe
    ("Europe/London",       "London"),
    ("Europe/Paris",        "Paris"),
    ("Europe/Berlin",       "Berlin"),
    ("Europe/Madrid",       "Madrid"),
    ("Europe/Rome",         "Rome"),
    ("Europe/Athens",       "Athens"),
    # Africa / Middle East
    ("Africa/Cairo",        "Cairo"),
    ("Africa/Johannesburg", "Johannesburg"),
    ("Asia/Jerusalem",      "Jerusalem"),
    ("Asia/Dubai",          "Dubai"),
    # Asia / Oceania
    ("Asia/Kolkata",        "India (Kolkata)"),
    ("Asia/Shanghai",       "China (Shanghai/Beijing)"),
    ("Asia/Tokyo",          "Tokyo"),
    ("Australia/Sydney",    "Sydney"),
]

IS_VALID: frozenset[str] = frozenset(name for name, _ in LSP_TIMEZONES)
