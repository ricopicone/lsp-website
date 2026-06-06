"""Forms for the events app (PROG-7, PROG-8, Program Committee admin)."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .models import Event, PricingCode, Program, SeminarProposal


class EventDescriptionForm(forms.ModelForm):
    """Faculty-facing edit form for the event description (PROG-7)."""

    class Meta:
        model = Event
        fields = ("description", "record_video")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 12, "cols": 80}),
        }


class PricingCodeForm(forms.ModelForm):
    """Faculty-issued pricing code (PROG-8 / REG-17)."""

    class Meta:
        model = PricingCode
        fields = (
            "pricing_mode",
            "amount_or_percent",
            "valid_until",
            "max_uses",
            "restricted_to_user",
        )
        widgets = {
            "valid_until": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
        }

    def clean(self):
        data = super().clean()
        mode = data.get("pricing_mode")
        amount = data.get("amount_or_percent")
        if mode == PricingCode.Mode.PERCENT_OFF and amount is not None and not (
            Decimal("0") <= amount <= Decimal("100")
        ):
            self.add_error("amount_or_percent", "percent_off requires a value between 0 and 100.")
        if amount is not None and amount < 0:
            self.add_error("amount_or_percent", "Cannot be negative.")
        return data


class ProgramPublishForm(forms.ModelForm):
    """PC-facing publish-control form for a Program (publish toggle + schedule)."""

    class Meta:
        model = Program
        fields = ("published", "publish_date")
        widgets = {
            "publish_date": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
        }


def _member_name(user):
    return user.get_full_name() or user.email


class SeminarProposalForm(forms.ModelForm):
    """Member-facing event proposal (M12.5) — seminar, reading group, or special
    event. Fields are grouped per type in the template (toggled by ``event_type``);
    validation enforces the per-type requirements here. The Programming Committee
    reviews it and, on approval, mints the Event."""

    #: Readings entered one MLA-style citation per line; parsed into individual
    #: ProposalReading rows on save (so they display/format nicely).
    readings_text = forms.CharField(
        required=False,
        label="Readings",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="One citation per line, following the style guide below.",
    )

    class Meta:
        model = SeminarProposal
        fields = (
            "event_type", "title", "description",
            "date_tbd", "start_date", "end_date", "proposed_time",
            "format", "location", "contact",
            "continues_seminar", "faculty",
            "offers_ce", "fee_note", "biography",
            "speaker_arrangement", "external_speakers", "honoraria_estimate",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 8}),
            "fee_note": forms.Textarea(attrs={"rows": 2}),
            "biography": forms.Textarea(attrs={"rows": 4}),
            "external_speakers": forms.Textarea(attrs={"rows": 4}),
            "speaker_arrangement": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import User
        from workgroups.models import Workgroup

        self.fields["event_type"].label = "Type of event"

        self.fields["description"].help_text = (
            "≈250 words. Introduce the central focus and topics, with a clear "
            "rationale for how you engage Freudian and Lacanian clinical technique "
            "and theory, plus the format (discussion, lecture, presentations, …)."
        )

        self.fields["faculty"].required = False
        self.fields["faculty"].queryset = User.objects.filter(
            profile__is_faculty=True, is_active=True,
        ).order_by("last_name", "first_name")
        self.fields["faculty"].label_from_instance = _member_name
        self.fields["faculty"].label = "Additional conveners / speakers"
        self.fields["faculty"].help_text = (
            "You're counted as a convener — add any co-conveners (seminars / reading "
            "groups) or internal LSP speakers (special events). Teaching a seminar "
            "confers faculty standing."
        )

        self.fields["continues_seminar"].required = False
        self.fields["continues_seminar"].label = "Continue an existing seminar"
        self.fields["continues_seminar"].help_text = (
            "Seminars only: pick the seminar to run another year of, or leave "
            "blank for a brand-new one."
        )
        self.fields["continues_seminar"].queryset = (
            Workgroup.objects.filter(kind=Workgroup.Kind.SEMINAR).order_by("name")
        )
        self.fields["start_date"].label = "Start / event date"
        self.fields["end_date"].label = "End date"
        self.fields["speaker_arrangement"].required = False

        # Prefill the readings textarea from existing rows when editing.
        if self.instance and self.instance.pk:
            existing = self.instance.readings.all()
            if existing:
                self.fields["readings_text"].initial = "\n".join(
                    r.citation for r in existing
                )

    def clean(self):
        data = super().clean()
        import datetime as _dt

        etype = data.get("event_type")
        start, end = data.get("start_date"), data.get("end_date")
        is_offering = etype in (Event.Type.SEMINAR, Event.Type.READING_GROUP)

        if is_offering:
            if not start:
                self.add_error("start_date", "Required for seminars and reading groups.")
            if not end:
                self.add_error("end_date", "Required for seminars and reading groups.")
            if start and end:
                if end <= start:
                    self.add_error("end_date", "End date must be after the start date.")
                elif end < _dt.date.today():
                    self.add_error(
                        "end_date",
                        "End date can't be in the past — the term wouldn't be active.",
                    )
        else:
            # Special event: a concrete date is required unless it's TBD.
            if not data.get("date_tbd") and not start:
                self.add_error(
                    "start_date",
                    "Give a proposed date, or check “date/time TBD”.",
                )
        return data

    def save_readings(self, proposal):
        """Replace the proposal's readings from the textarea (one per line)."""
        from .models import ProposalReading

        lines = [
            ln.strip() for ln in (self.cleaned_data.get("readings_text") or "").splitlines()
            if ln.strip()
        ]
        proposal.readings.all().delete()
        ProposalReading.objects.bulk_create([
            ProposalReading(proposal=proposal, sort_order=i, citation=line)
            for i, line in enumerate(lines)
        ])


class ProgramEventForm(forms.ModelForm):
    """PC-facing event create/edit form for events belonging to a Program.

    Restricts event_type to the annual-program types and auto-attaches the
    target program on save.
    """

    #: Faculty is no longer a model field — it's a role on the event's
    #: generated workgroup. Edit it here as a plain multi-select and reconcile
    #: via ``Event.set_faculty`` on save.
    faculty = forms.ModelMultipleChoiceField(
        queryset=None, required=False,
        help_text="LSP-affiliated instructors (can edit the event and mint pricing codes).",
    )

    #: Opt-in continuity: attach this (seminar) event as another term of an
    #: existing seminar's standing workgroup instead of spawning a new group —
    #: members of past terms retain workspace/archive access and renew here.
    continues_seminar = forms.ModelChoiceField(
        queryset=None, required=False,
        label="Continue an existing seminar",
        help_text=(
            "Optional. Make this a new yearly term of an existing seminar — its "
            "workspace, channel, and past members carry over (they renew by "
            "registering for this term). Leave blank for a brand-new seminar."
        ),
    )

    class Meta:
        model = Event
        fields = (
            "title", "slug", "event_type",
            "start_date", "end_date",
            "format", "status",
            "description", "access_info",
            "requires_faculty_approval", "record_video",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date":   forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 8}),
            "access_info": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, program=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.program = program
        # Narrow event_type choices to the annual-program-type set.
        self.fields["event_type"].choices = [
            (Event.Type.SEMINAR.value,       Event.Type.SEMINAR.label),
            (Event.Type.READING_GROUP.value, Event.Type.READING_GROUP.label),
            (Event.Type.CARTEL.value,        Event.Type.CARTEL.label),
        ]
        # Restrict faculty choices to users with is_faculty=True (USR-6).
        from accounts.models import User
        self.fields["faculty"].queryset = User.objects.filter(
            profile__is_faculty=True, is_active=True,
        ).order_by("last_name", "first_name")
        self.fields["faculty"].label_from_instance = _member_name
        if self.instance.pk:
            self.fields["faculty"].initial = self.instance.faculty_members()

        from workgroups.models import Workgroup
        self.fields["continues_seminar"].queryset = (
            Workgroup.objects.filter(kind=Workgroup.Kind.SEMINAR).order_by("name")
        )
        # Continuity is a create-time choice; an existing event already has its
        # workgroup, so hide it when editing.
        if self.instance.pk:
            del self.fields["continues_seminar"]

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.program is not None:
            instance.program = self.program
        # New term of an existing seminar → attach to its standing workgroup so
        # ensure_workgroup() won't spawn a fresh one.
        continues = self.cleaned_data.get("continues_seminar")
        if continues is not None and instance.workgroup_id is None:
            instance.workgroup = continues
        if commit:
            instance.save()
            self.save_m2m()
            instance.set_faculty(self.cleaned_data.get("faculty", []))
        return instance
