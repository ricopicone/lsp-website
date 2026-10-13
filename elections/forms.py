"""Forms for the elections app (task #813)."""

from __future__ import annotations

from django import forms

from .models import Election


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


DATE_FIELDS = (
    "nominations_open_at", "nominations_close_at", "voting_open_at", "voting_close_at",
)
_DT_FORMAT = "%Y-%m-%dT%H:%M"


def _minute(dt):
    return dt.replace(second=0, microsecond=0) if dt else dt


def _style(form) -> None:
    """DaisyUI classes on every widget (the class strings also appear in
    templates, so Tailwind keeps them in the production build)."""
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, forms.Select):
            css = "select select-bordered w-full"
        elif isinstance(w, forms.Textarea):
            css = "textarea textarea-bordered w-full"
        else:
            css = "input input-bordered w-full"
        w.attrs.setdefault("class", css)


class ElectionSettingsForm(forms.ModelForm):
    """An election's settings. The administrator sets every date; the rules
    keep a closed window closed: a date that has passed can't be changed,
    and a changed date must be in the future. Extending an open window is
    just moving its (future) close date later."""

    class Meta:
        model = Election
        fields = [
            "title", "seats", *DATE_FIELDS, "results_due",
            "count_method", "show_during_voting", "show_results",
        ]
        labels = {
            "nominations_open_at": "Nominations open",
            "nominations_close_at": "Nominations close",
            "voting_open_at": "Voting opens",
            "voting_close_at": "Voting closes",
            "results_due": "Results due",
            "seats": "Seats to fill",
            "count_method": "Counting rule",
            "show_during_voting": "While voting is open, members see",
            "show_results": "After the count, members see",
        }
        help_texts = {
            "results_due": "The bylaws ask for results within a week of voting closing. "
                           "Left blank, it is set to a week after voting closes.",
            "voting_open_at": "Voting opens at this time or when the slate is "
                              "published, whichever is later.",
        }
        widgets = {
            **{f: forms.DateTimeInput(attrs={"type": "datetime-local"}, format=_DT_FORMAT)
               for f in DATE_FIELDS},
            "results_due": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, now=None, **kwargs):
        from django.utils import timezone

        super().__init__(*args, **kwargs)
        self.now = now or timezone.now()
        self.is_new = self.instance.pk is None
        self.original = {f: getattr(self.instance, f) for f in self.Meta.fields}
        for f in DATE_FIELDS:
            self.fields[f].input_formats = [_DT_FORMAT, "%Y-%m-%d %H:%M"]
        _style(self)
        self.fields["results_due"].required = False
        if self.is_new:
            return
        P = Election.Phase
        phase = self.instance.phase_at(self.now)
        locked: set[str] = set()
        if phase in (P.VOTING, P.CLOSED, P.COUNTED, P.PUBLISHED, P.ACCLAIMED):
            locked.add("seats")
        if phase in (P.COUNTED, P.PUBLISHED, P.ACCLAIMED):
            locked |= {"title", *DATE_FIELDS, "results_due", "count_method"}
        if phase in (P.PUBLISHED, P.ACCLAIMED):
            locked |= {"show_during_voting", "show_results"}
        for f in locked:
            self.fields[f].disabled = True

    def clean(self):
        from datetime import timedelta

        from django.utils import timezone

        data = super().clean()
        grace = self.now - timedelta(minutes=1)
        for f in DATE_FIELDS:
            new = data.get(f)
            if new is None or self.fields[f].disabled:
                continue
            old = self.original.get(f)
            if not self.is_new and old is not None and _minute(new) == _minute(old):
                data[f] = old  # untouched: keep the stored value, seconds and all
                continue
            if not self.is_new and old is not None and old <= self.now:
                self.add_error(f, "This date has already passed, so it can't be changed.")
            elif new < grace:
                self.add_error(f, "Choose a time in the future.")
        dates = [data.get(f) for f in DATE_FIELDS]
        if all(dates):
            no, nc, vo, vc = dates
            if not no < nc:
                self.add_error("nominations_close_at", "Nominations must close after they open.")
            if not nc <= vo:
                self.add_error("voting_open_at", "Voting can't open before nominations close.")
            if not vo < vc:
                self.add_error("voting_close_at", "Voting must close after it opens.")
            if not data.get("results_due"):
                data["results_due"] = timezone.localdate(vc) + timedelta(days=7)
        return data

    def changed_summary(self) -> list[str]:
        from django.utils import timezone

        def show(v):
            if hasattr(v, "hour"):
                return f"{timezone.localtime(v):%Y-%m-%d %H:%M}"
            return str(v)

        lines = []
        for f in self.Meta.fields:
            old, new = self.original.get(f), self.cleaned_data.get(f)
            if f in DATE_FIELDS and old and new and _minute(old) == _minute(new):
                continue
            if old != new:
                lines.append(f"{self.fields[f].label}: {show(old)} → {show(new)}")
        return lines


class OverrideForm(forms.Form):
    email = forms.EmailField(label="Member's email")
    override = forms.ChoiceField(choices=[("add", "Add to the roll"),
                                          ("remove", "Remove from the roll")])
    reason = forms.CharField(max_length=300)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def clean_email(self):
        from accounts.models import User

        email = self.cleaned_data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise forms.ValidationError("No account has that email address.")
        self.user = user
        return email


class NominationForm(forms.Form):
    letter = forms.CharField(
        label="Motivation letter",
        widget=forms.Textarea(attrs={"rows": 10, "class": "textarea textarea-bordered w-full"}),
        help_text="Your motivation, your interests, and what you can bring to "
                  "the Board and the School.",
    )
