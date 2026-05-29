"""Geocode ``Profile.location`` strings into lat/lng for the M11 map.

Uses Nominatim (OpenStreetMap) — no key, no cost, polite rate-limited use
required by their TOS. The user-agent string identifies our app.

``split_location`` lets a single ``Profile.location`` field carry several
geocodable places — e.g. "San Francisco & Palo Alto, CA" becomes two
queries, ["San Francisco, CA", "Palo Alto, CA"], each rendering its own
pin on the map.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from geopy.exc import GeocoderUnavailable, GeopyError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

NOMINATIM_USER_AGENT = "lsp-website/1.0 (https://app.lacanschool.org)"

#: Splits on " & ", " and ", or " / " — but NOT comma (commas separate
#: city/state/country within a single place).
_SPLIT_RE = re.compile(r"\s*(?:&| and | / )\s*", flags=re.IGNORECASE)


def split_location(text: str) -> list[str]:
    """Split a free-form location string into one or more place queries.

    If the original ends with a regional suffix (", CA" or ", USA") and an
    earlier sub-piece doesn't carry its own comma, the suffix propagates so
    that "San Francisco & Palo Alto, CA" geocodes both halves to California
    rather than risking a "Palo Alto" in another country.
    """
    text = text.strip()
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        return parts
    last = parts[-1]
    if "," in last:
        suffix = last[last.find(","):]
        out: list[str] = []
        for p in parts[:-1]:
            out.append(p if "," in p else p + suffix)
        out.append(last)
        return out
    return parts


class GeocodeResult(NamedTuple):
    lat: float
    lng: float
    formatted: str  # what the geocoder normalized the query to


def _geocoder():
    return Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=10)


def geocode(location: str) -> GeocodeResult | None:
    """Geocode a single free-form location string.

    Returns None on miss or transient error. Caller decides whether to retry.
    """
    if not location.strip():
        return None
    try:
        result = _geocoder().geocode(location, exactly_one=True, language="en")
    except (GeocoderUnavailable, GeopyError):
        return None
    if result is None:
        return None
    return GeocodeResult(
        lat=result.latitude,
        lng=result.longitude,
        formatted=str(result.address),
    )


def make_batch_geocoder(per_request_delay: float = 1.0):
    """A geopy RateLimiter-wrapped callable for batch geocoding.

    Nominatim's TOS requires ≤ 1 request/second. Returns a function with
    the same signature as ``geocode`` above.
    """
    inner = _geocoder().geocode
    limited = RateLimiter(inner, min_delay_seconds=per_request_delay)

    def _call(location: str) -> GeocodeResult | None:
        if not location.strip():
            return None
        try:
            r = limited(location, exactly_one=True, language="en")
        except (GeocoderUnavailable, GeopyError):
            return None
        if r is None:
            return None
        return GeocodeResult(lat=r.latitude, lng=r.longitude, formatted=str(r.address))

    return _call
