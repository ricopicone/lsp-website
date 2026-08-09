"""Forms for the Referral Coordinator surface and the clinician respond page."""

from __future__ import annotations

from django import forms

from accounts.models import User

from .models import (
    MessageTemplate,
    ReferralAddendum,
    ReferralListMember,
    ReferralResponse,
    ReferralSettings,
)

_TEXT_INPUT = forms.TextInput(attrs={"class": "input input-bordered w-full"})
_SELECT = forms.Select(attrs={"class": "select select-bordered w-full"})


def _textarea(rows: int) -> forms.Textarea:
    return forms.Textarea(attrs={
        "rows": rows,
        "class": (
            "textarea textarea-bordered w-full font-sans text-sm leading-relaxed"
        ),
    })


class ReferralSettingsForm(forms.ModelForm):
    class Meta:
        model = ReferralSettings
        fields = [
            "ack_mode", "distribution_mode", "followup_mode",
            "onboarding_mode", "response_window_days", "retention_months",
        ]
        widgets = {
            "ack_mode": _SELECT,
            "distribution_mode": _SELECT,
            "followup_mode": _SELECT,
            "onboarding_mode": _SELECT,
            "response_window_days": forms.NumberInput(
                attrs={"class": "input input-bordered w-24", "min": 1},
            ),
            "retention_months": forms.NumberInput(
                attrs={"class": "input input-bordered w-24", "min": 1},
            ),
        }


class MessageTemplateForm(forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["subject", "body"]
        widgets = {
            "subject": _TEXT_INPUT,
            "body": _textarea(18),
        }


class AddClinicianForm(forms.Form):
    """Pick a member to add to the referral list."""

    user = forms.ModelChoiceField(
        queryset=User.objects.none(), label="Member", widget=_SELECT,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        listed = ReferralListMember.objects.filter(
            is_active=True,
        ).values_list("user_id", flat=True)
        self.fields["user"].queryset = (
            User.objects.filter(is_active=True, profile__is_persona=False)
            .exclude(pk__in=listed)
            .order_by("last_name", "first_name", "email")
        )
        self.fields["user"].label_from_instance = (
            lambda u: u.get_full_name() or u.email
        )


class ClinicianEditForm(forms.ModelForm):
    class Meta:
        model = ReferralListMember
        fields = ["details_override", "notes"]
        widgets = {
            "details_override": _textarea(6),
            "notes": _textarea(3),
        }


class RespondForm(forms.ModelForm):
    """The clinician's step-4 response.

    One checkbox, never a choice (task #531): a clinician who is not
    available lets the request pass. Submitting it unchecked withdraws a
    response rather than recording "unavailable".
    """

    available = forms.BooleanField(
        required=False,
        label="I'm available to work with this person",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )

    class Meta:
        model = ReferralResponse
        fields = ["available", "message"]
        widgets = {"message": _textarea(4)}


class RecordResponseForm(forms.Form):
    """Coordinator escape hatch: record a clinician's response by hand
    (e.g. one received by email or in conversation). Recorded responses are
    always available ones, there is no unavailable answer (task #531)."""

    member = forms.ModelChoiceField(
        queryset=ReferralListMember.objects.filter(is_active=True),
        label="Clinician", widget=_SELECT,
    )
    message = forms.CharField(
        required=False, widget=_textarea(2), label="Note",
    )


class AddendumForm(forms.Form):
    """Something to tell the clinicians after distribution (task #531)."""

    text = forms.CharField(
        label="What's changed", widget=_textarea(5),
        help_text="Sent to the clinicians and shown on their respond page.",
    )
    audience = forms.ChoiceField(
        label="Send to", choices=ReferralAddendum.Audience.choices,
        widget=_SELECT,
    )
    responses_due_at = forms.DateTimeField(
        required=False, label="Response deadline",
        widget=forms.DateTimeInput(
            attrs={"type": "date", "class": "input input-bordered w-full"},
            format="%Y-%m-%d",
        ),
    )

    def __init__(self, *args, request_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_obj = request_obj
        if request_obj is None:
            return
        reached = request_obj.distributed_to.filter(is_active=True).count()
        everyone = ReferralListMember.objects.filter(is_active=True).count()
        self.fields["audience"].choices = [
            (
                ReferralAddendum.Audience.DISTRIBUTED,
                f"Only the clinicians this request went to ({reached})"
                if reached
                else "Only the clinicians this request went to "
                     "(not recorded for this request)",
            ),
            (
                ReferralAddendum.Audience.ALL,
                f"Everyone on the referral list ({everyone})",
            ),
        ]
        self.fields["audience"].initial = (
            ReferralAddendum.Audience.DISTRIBUTED if reached
            else ReferralAddendum.Audience.ALL
        )
        self.fields["responses_due_at"].initial = request_obj.responses_due_at

    def clean_audience(self):
        """An unrecorded audience cannot be targeted, whatever the POST says.

        Requests distributed before the recipient log existed have nobody on
        it, and guessing who they reached would be a fiction.
        """
        audience = self.cleaned_data["audience"]
        if (
            audience == ReferralAddendum.Audience.DISTRIBUTED
            and self.request_obj is not None
            and not self.request_obj.distributed_to.filter(
                is_active=True,
            ).exists()
        ):
            raise forms.ValidationError(
                "This request has no recorded recipients, so an addendum can "
                "only go to everyone on the referral list.",
            )
        return audience


class FollowupForm(forms.Form):
    """The step-5 draft, editable before sending."""

    subject = forms.CharField(max_length=200, widget=_TEXT_INPUT)
    body = forms.CharField(widget=_textarea(20))


class NotesForm(forms.Form):
    coordinator_notes = forms.CharField(
        required=False, widget=_textarea(4), label="Coordinator notes",
    )
