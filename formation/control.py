"""Structured control-analysis accounting: per-slot progress toward the
background-dependent requirement (one 4-year + one/two 2-year analyses)."""

from __future__ import annotations

from django.utils import timezone

from .models import ControlAnalysis, FormationSettings


def _slot(entry, target):
    years = entry.duration_years if entry else 0.0
    return {"entry": entry, "years": round(years, 2), "target": target,
            "met": bool(entry and years >= target)}


def control_progress(user) -> dict:
    """Sub-bar data for a member's control analyses.

    Each requirement slot is filled by the *longest single* entry with the
    matching tag (per-relationship, not cumulative); leftover entries still
    count toward the Total bar. Slot counts come from
    ``Profile.control_requirement()``.
    """
    settings_ = FormationSettings.load()
    req = user.profile.control_requirement()
    entries = list(ControlAnalysis.objects.filter(member=user))

    four = sorted(
        (c for c in entries if c.requirement == ControlAnalysis.Requirement.FOUR_YEAR),
        key=lambda c: c.duration_years, reverse=True,
    )
    twos = sorted(
        (c for c in entries if c.requirement == ControlAnalysis.Requirement.TWO_YEAR),
        key=lambda c: c.duration_years, reverse=True,
    )

    n_two = req["two_year"]
    two_slots = [
        _slot(twos[i] if i < len(twos) else None, settings_.two_year_threshold)
        for i in range(n_two)
    ]
    total_years = round(sum(c.duration_years for c in entries), 2)
    total_target = settings_.four_year_threshold + settings_.two_year_threshold * n_two
    return {
        "total_years": total_years,
        "total_target": total_target,
        "four_year": _slot(four[0] if four else None, settings_.four_year_threshold),
        "two_year": two_slots,
    }


def decide_external(obj, *, approve, by, note=""):
    """Approve or decline an external-control-analyst request and notify the
    requesting member."""
    from . import notifications as notify_formation
    from .models import ExternalControlAnalyst

    obj.status = (ExternalControlAnalyst.Status.APPROVED if approve
                  else ExternalControlAnalyst.Status.DECLINED)
    obj.decided_at = timezone.now()
    obj.decided_by = by
    obj.decision_note = note
    obj.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])
    notify_formation.external_analyst_decision(obj)
    return obj
