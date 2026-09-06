"""Helpers for tests that build academic-year periods by hand.

The data migrations ``payments/0004`` and ``payments/0006`` seed a dues period
and a tuition period named for *today's* academic year, so the test database
holds a row whose name and slug change on September 1. Tests that create
"AY 2026–2027" themselves were fine until that day, then collided on the
unique name or slug (23 tests turned red overnight, nothing in the code having
changed). The seeded rows are wanted — the treasurer surfaces and the
``current_period`` fixtures read them — so a test that wants a period the seed
may already have created adopts that row rather than racing it.
"""

from __future__ import annotations

from django.db.models import Q


def make_period(model, **fields):
    """Create a ``DuesPeriod`` / ``TuitionPeriod`` with ``fields``, or, when
    the clock-seeded row already carries that name or slug, overwrite it with
    ``fields`` and return it. Either way the caller gets exactly the period it
    described, and there is one row for that year, not two."""
    existing = model.objects.filter(
        Q(name=fields["name"]) | Q(slug=fields["slug"])
    ).first()
    if existing is None:
        return model.objects.create(**fields)
    for key, value in fields.items():
        setattr(existing, key, value)
    existing.save()
    return existing
