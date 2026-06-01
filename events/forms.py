"""Forms for the events app (PROG-7, PROG-8, Program Committee admin)."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from .models import Event, PricingCode, Program


class EventDescriptionForm(forms.ModelForm):
    """Faculty-facing edit form for the event description (PROG-7)."""

    class Meta:
        model = Event
        fields = ("description",)
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
            "requires_faculty_approval",
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
