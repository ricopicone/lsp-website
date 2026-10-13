"""Forms for the elections app (task #813)."""

from __future__ import annotations

from django import forms


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} choice"


class BallotForm(forms.Form):
    """One rank <select> per candidate, so the ballot works without
    JavaScript. Ranks may have gaps (``ranked_ids`` closes them up);
    duplicates are refused."""

    def __init__(self, candidates, *args, initial_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.candidates = list(candidates)
        n = len(self.candidates)
        choices = [("", "Not ranked")] + [(str(i), _ordinal(i)) for i in range(1, n + 1)]
        initial = {nid: i for i, nid in enumerate(initial_order or [], start=1)}
        for c in self.candidates:
            self.fields[f"rank_{c.id}"] = forms.ChoiceField(
                choices=choices, required=False, label=c.name,
                initial=str(initial[c.id]) if c.id in initial else "",
            )
        self._ranked: list[int] = []

    def clean(self):
        data = super().clean()
        ranks = {
            c.id: int(data[f"rank_{c.id}"]) for c in self.candidates
            if data.get(f"rank_{c.id}")
        }
        if not ranks:
            raise forms.ValidationError("Rank at least one candidate.")
        if len(set(ranks.values())) != len(ranks):
            raise forms.ValidationError("Give each candidate a different rank.")
        self._ranked = [cid for cid, _ in sorted(ranks.items(), key=lambda kv: kv[1])]
        return data

    def ranked_ids(self) -> list[int]:
        return self._ranked

    def rows(self):
        """(candidate, bound field) pairs for the template."""
        return [(c, self[f"rank_{c.id}"]) for c in self.candidates]
