"""Forms for the events app (PROG-7, PROG-8, Program Committee admin)."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .ce import CECreditBasis
from .models import Event, EventProposal, PricingCode, Program, Session


class EventEditForm(forms.ModelForm):
    """Faculty-facing edit form for an event's public content (PROG-7).

    Named for the whole page, not just the description: it has carried title,
    readings, schedule, contact, fee, and now CE for some time.
    """

    class Meta:
        model = Event
        fields = (
            "title", "description", "readings", "schedule_note", "contact",
            "fee_note", "record_video", "speaker_spotlight", "open_to_guests",
            "offers_ce", "ce_credits", "ce_credits_basis", "ce_note",
            "ce_organizations",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "description": forms.Textarea(attrs={"rows": 12, "cols": 80}),
            "readings": forms.Textarea(attrs={"rows": 8, "cols": 80}),
            "schedule_note": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            "fee_note": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            "ce_note": forms.Textarea(attrs={"rows": 2, "cols": 80}),
            # Rendered by hand in the template so each option carries its logo.
            "ce_organizations": forms.CheckboxSelectMultiple,
            "ce_credits": forms.NumberInput(
                attrs={"class": "input input-bordered input-sm", "step": "0.5", "min": "0"},
            ),
            "ce_credits_basis": forms.Select(
                attrs={"class": "select select-bordered select-sm"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The basis is meaningless without a count and always has a default, so
        # a POST that omits it (the change-review dialog's re-post, a partial
        # form) must not fail validation.
        self.fields["ce_credits_basis"].required = False

    def clean_ce_credits_basis(self):
        return self.cleaned_data.get("ce_credits_basis") or CECreditBasis.TOTAL


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


class EventProposalForm(forms.ModelForm):
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
        help_text=(
            "One citation per line, following the style guide below. Wrap book "
            "and journal titles in *asterisks* to italicize them."
        ),
    )

    #: Drives which fee inputs apply (the model stores the resolved amounts).
    fee_type = forms.ChoiceField(
        required=False, label="Fee",
        choices=[("free", "Free"), ("fixed", "Fixed amount"),
                 ("sliding", "Sliding scale")],
        widget=forms.RadioSelect, initial="free",
    )

    #: Seminars / reading groups: schedule the recurring meetings now, or leave TBD.
    schedule_choice = forms.ChoiceField(
        required=False, label="Meeting schedule",
        choices=[("tbd", "Schedule TBD"), ("set", "Schedule the meetings")],
        widget=forms.RadioSelect, initial="tbd",
    )
    sched_weekdays = forms.MultipleChoiceField(
        required=False, label="On",
        choices=[("MO", "Mon"), ("TU", "Tue"), ("WE", "Wed"), ("TH", "Thu"),
                 ("FR", "Fri"), ("SA", "Sat"), ("SU", "Sun")],
        widget=forms.CheckboxSelectMultiple,
    )
    sched_week_positions = forms.MultipleChoiceField(
        required=False, label="Weekday occurrence(s)",
        choices=[("1", "First"), ("2", "Second"), ("3", "Third"),
                 ("4", "Fourth"), ("-1", "Last")],
        widget=forms.CheckboxSelectMultiple,
        help_text="e.g. First + Third = the 1st and 3rd of each month.",
    )

    class Meta:
        model = EventProposal
        fields = (
            "event_type", "title", "description",
            "start_date", "end_date",
            "date_tbd", "proposed_datetime",
            "location_kind", "location", "contact",
            "continues_seminar", "faculty",
            "fee_amount", "fee_sliding_min", "fee_sliding_max", "tuition_covers",
            "offers_ce",
            "sched_frequency", "sched_start_time", "sched_end_time",
            "speaker_arrangement", "honoraria_estimate",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "proposed_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
            "description": forms.Textarea(attrs={"rows": 8}),
            "speaker_arrangement": forms.RadioSelect,
            "sched_frequency": forms.Select,
            "sched_start_time": forms.TimeInput(attrs={"type": "time"}),
            "sched_end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import User
        from workgroups.models import Workgroup

        self.fields["event_type"].label = "Type of event"
        # datetime-local needs the value in this exact format to prefill on edit.
        self.fields["proposed_datetime"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["proposed_datetime"].label = "Proposed date & time"
        from django.utils import timezone as _tz
        self.fields["proposed_datetime"].help_text = (
            f"In your timezone ({_tz.get_current_timezone()})."
        )

        self.fields["description"].help_text = ""  # guidance shown above the field

        self.fields["faculty"].required = False
        self.fields["faculty"].queryset = User.objects.filter(
            profile__is_faculty=True, is_active=True,
        ).order_by("last_name", "first_name")
        self.fields["faculty"].label_from_instance = _member_name
        self.fields["faculty"].label = "Additional conveners / internal speakers"
        self.fields["faculty"].help_text = (
            "You're counted as a convener. Add any co-conveners (seminars / reading "
            "groups) or internal LSP speakers (special events) — their bios come from "
            "their profiles. Teaching a seminar confers faculty standing."
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
        self.fields["start_date"].label = "Start date"
        self.fields["end_date"].label = "End date"
        self.fields["location_kind"].label = "Location"
        self.fields["offers_ce"].label = "Offer CE credits"

        # Recurring-schedule fields (offerings). Frequency optional at field level
        # — required only when the member chooses to schedule now (in clean()).
        self.fields["sched_frequency"].required = False
        self.fields["sched_frequency"].label = "Frequency"
        self.fields["sched_frequency"].choices = (
            [("", "—")] + list(EventProposal.ScheduleFrequency.choices)
        )
        self.fields["sched_start_time"].label = "Start time"
        self.fields["sched_end_time"].label = "End time"
        self.fields["contact"].label = "Contact email"
        self.fields["contact"].help_text = (
            "An additional contact for this proposal, besides your own account email."
        )

        # Speaker arrangement: a real first option (no blank "---------").
        self.fields["speaker_arrangement"].required = False
        self.fields["speaker_arrangement"].choices = (
            EventProposal.SpeakerArrangement.choices
        )
        if not self.initial.get("speaker_arrangement") and not self.instance.pk:
            self.initial["speaker_arrangement"] = (
                EventProposal.SpeakerArrangement.PROPOSER
            )

        # Derive the fee type from stored amounts when editing.
        if self.instance and self.instance.pk and not self.is_bound:
            inst = self.instance
            if inst.fee_sliding_min is not None or inst.fee_sliding_max is not None:
                self.initial["fee_type"] = "sliding"
            elif inst.fee_amount is not None:
                self.initial["fee_type"] = "fixed"
            else:
                self.initial["fee_type"] = "free"

        # Prefill the readings textarea from existing rows when editing.
        if self.instance and self.instance.pk:
            existing = self.instance.readings.all()
            if existing:
                self.fields["readings_text"].initial = "\n".join(
                    r.citation for r in existing
                )
            if self.instance.proposed_datetime:
                from django.utils import timezone
                # Prefill in the editor's own timezone (localtime uses the
                # request's active tz), matching how the input is interpreted.
                self.initial["proposed_datetime"] = timezone.localtime(
                    self.instance.proposed_datetime
                ).strftime("%Y-%m-%dT%H:%M")
            if not self.is_bound:
                self.initial["schedule_choice"] = (
                    "tbd" if self.instance.schedule_tbd else "set"
                )
                if self.instance.sched_weekdays:
                    self.initial["sched_weekdays"] = self.instance.sched_weekdays.split(",")
                if self.instance.sched_week_positions:
                    self.initial["sched_week_positions"] = (
                        self.instance.sched_week_positions.split(",")
                    )

    def clean_proposed_datetime(self):
        """Interpret the naive datetime-local input in the editor's own timezone
        (the request's active tz = their Profile.timezone), like the rest of the
        app. Django usually localizes this already; the guard is defensive."""
        from django.utils import timezone
        dt = self.cleaned_data.get("proposed_datetime")
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    def clean(self):
        data = super().clean()
        import datetime as _dt

        # A saved (not-yet-submitted) proposal may be incomplete; only enforce the
        # full requirements when the member is actually submitting for review.
        require = getattr(self, "require_complete", True)

        etype = data.get("event_type")
        start, end = data.get("start_date"), data.get("end_date")
        is_offering = etype in (Event.Type.SEMINAR, Event.Type.READING_GROUP)

        if is_offering:
            # Tuition always covers seminars & reading groups (REG-4).
            data["tuition_covers"] = True
            if require and not start:
                self.add_error("start_date", "Required for seminars and reading groups.")
            if require and not end:
                self.add_error("end_date", "Required for seminars and reading groups.")
            if start and end:
                if end <= start:
                    self.add_error("end_date", "End date must be after the start date.")
                elif require and end < _dt.date.today():
                    self.add_error(
                        "end_date",
                        "End date can't be in the past — the term wouldn't be active.",
                    )
        else:
            # Special event: a concrete date/time is required unless it's TBD.
            if require and not data.get("date_tbd") and not data.get("proposed_datetime"):
                self.add_error(
                    "proposed_datetime",
                    "Give a proposed date & time, or check “date/time TBD”.",
                )
        # Fee: keep only the inputs that match the chosen fee type.
        fee_type = data.get("fee_type") or "free"
        smin, smax = data.get("fee_sliding_min"), data.get("fee_sliding_max")
        if fee_type == "free":
            data["fee_amount"] = data["fee_sliding_min"] = data["fee_sliding_max"] = None
        elif fee_type == "fixed":
            data["fee_sliding_min"] = data["fee_sliding_max"] = None
            if require and data.get("fee_amount") is None:
                self.add_error("fee_amount", "Enter a fixed fee, or choose Free / Sliding scale.")
        else:  # sliding
            data["fee_amount"] = None
            if require and smin is None and smax is None:
                self.add_error("fee_sliding_max", "Enter a sliding-scale range.")
            elif smin is not None and smax is not None and smin > smax:
                self.add_error("fee_sliding_min", "Minimum can't exceed the maximum.")

        # Recurring meeting schedule (offerings only). sched_weekdays + schedule_tbd
        # aren't ModelForm fields, so write them onto the instance directly.
        weekdays = ",".join(data.get("sched_weekdays") or [])
        positions = ",".join(data.get("sched_week_positions") or [])
        scheduled = is_offering and data.get("schedule_choice") == "set"
        self.instance.schedule_tbd = not scheduled
        self.instance.sched_weekdays = weekdays if scheduled else ""
        self.instance.sched_week_positions = positions if scheduled else ""
        data["sched_weekdays"] = weekdays  # keep cleaned_data consistent for errors
        if not scheduled:
            # Clear any partial schedule so a flip back to TBD leaves no stray data.
            data["sched_frequency"] = ""
        elif require:
            if not data.get("sched_frequency"):
                self.add_error("sched_frequency", "Pick how often it meets.")
            if not data.get("sched_weekdays"):
                self.add_error("sched_weekdays", "Pick at least one weekday.")
            if not data.get("sched_start_time") or not data.get("sched_end_time"):
                self.add_error("sched_end_time", "Give the meeting start and end times.")
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


def _build_speaker_formset():
    from .models import EventProposal, ProposalSpeaker
    return forms.inlineformset_factory(
        EventProposal, ProposalSpeaker,
        fields=("name", "email", "affiliation", "bio"),
        widgets={
            "bio": forms.Textarea(attrs={"rows": 2}),
            "name": forms.TextInput(attrs={"placeholder": "Full name"}),
            "email": forms.EmailInput(attrs={"placeholder": "Contact email"}),
            "affiliation": forms.TextInput(attrs={"placeholder": "Affiliation"}),
        },
        extra=1, can_delete=True,
    )


#: External-speaker formset for special-event proposals (name/email/affiliation/bio).
ProposalSpeakerFormSet = _build_speaker_formset()


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
        widget=forms.CheckboxSelectMultiple(attrs={"class": "checkbox checkbox-sm"}),
        help_text="LSP-affiliated instructors (can edit the event and mint pricing codes).",
    )

    #: Opt-in continuity: attach this (seminar) event as another term of an
    #: existing seminar's standing workgroup instead of spawning a new group —
    #: members of past terms retain workspace/archive access and renew here.
    continues_seminar = forms.ModelChoiceField(
        queryset=None, required=False,
        label="Continue an existing seminar",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
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
            "description", "readings", "schedule_note", "contact", "fee_note",
            "access_info",
            "requires_faculty_approval", "record_video", "open_to_guests",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "slug": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "event_type": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "input input-bordered w-full"},
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "input input-bordered w-full"},
            ),
            "format": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "status": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "description": forms.Textarea(
                attrs={"rows": 10, "class": "textarea textarea-bordered w-full"},
            ),
            "readings": forms.Textarea(
                attrs={"rows": 8, "class": "textarea textarea-bordered w-full"},
            ),
            "schedule_note": forms.Textarea(
                attrs={"rows": 2, "class": "textarea textarea-bordered w-full"},
            ),
            "contact": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "fee_note": forms.Textarea(
                attrs={"rows": 2, "class": "textarea textarea-bordered w-full"},
            ),
            "access_info": forms.Textarea(
                attrs={"rows": 3, "class": "textarea textarea-bordered w-full"},
            ),
            "requires_faculty_approval": forms.CheckboxInput(attrs={"class": "checkbox"}),
            "record_video": forms.CheckboxInput(attrs={"class": "checkbox"}),
            "open_to_guests": forms.CheckboxInput(attrs={"class": "checkbox"}),
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


# --- Standalone-event schedule (session) editor -------------------------

_DT_ATTRS = {"type": "datetime-local", "class": "input input-bordered w-full"}


class SessionScheduleForm(forms.ModelForm):
    """One session in the standalone-event schedule editor.

    Start and end are independent ``datetime-local`` inputs (not a shared date +
    two times) — in the editor's own timezone, a session's start and end can
    fall on different calendar dates, so each carries its own date. Django
    localizes the naive input to the request's active timezone (the user's
    ``Profile.timezone``), matching the workgroup meeting forms and the rest of
    the app's per-user display.
    """

    class Meta:
        model = Session
        fields = ("start_at", "end_at", "location")
        widgets = {
            "start_at": forms.DateTimeInput(attrs=_DT_ATTRS, format="%Y-%m-%dT%H:%M"),
            "end_at": forms.DateTimeInput(attrs=_DT_ATTRS, format="%Y-%m-%dT%H:%M"),
            "location": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in ("start_at", "end_at"):
            self.fields[f].input_formats = ["%Y-%m-%dT%H:%M"]
            self.fields[f].required = False
        self.fields["location"].required = False

    def clean(self):
        cd = super().clean()
        start, end = cd.get("start_at"), cd.get("end_at")
        # A blank extra row is dropped by the formset; a partial one is an error.
        if not start and not end and not cd.get("location"):
            return cd
        if not start or not end:
            raise forms.ValidationError("Give both a start and an end date/time.")
        if end <= start:
            self.add_error("end_at", "The end must be after the start.")
        return cd


def _build_schedule_formset():
    return forms.inlineformset_factory(
        Event, Session, form=SessionScheduleForm, extra=1, can_delete=True,
    )


#: Session formset for the standalone-event schedule editor (start/end datetimes + location).
SessionScheduleFormSet = _build_schedule_formset()
