"""Forms for the Web Coordinator's document management surface (task #592)."""

from __future__ import annotations

from django import forms

from .models import Document

_INPUT = "input input-bordered w-full"
_TEXTAREA = "textarea textarea-bordered w-full"
_SELECT = "select select-bordered w-full"


class DocumentEditForm(forms.ModelForm):
    """Content and presentation only.

    Identity fields — slug (the URL, with no redirect if changed), category,
    owning workgroup, authors, superseded_by — stay in the Django admin.
    """

    note = forms.CharField(
        required=False, max_length=255,
        label="What changed?",
        help_text="Optional. Recorded against the previous version.",
        widget=forms.TextInput(attrs={"class": _INPUT}),
    )

    class Meta:
        model = Document
        fields = (
            "title", "summary", "description", "notice", "file", "body",
            "effective_date", "listing_visibility", "content_visibility",
            "display_order",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": _INPUT}),
            "summary": forms.TextInput(attrs={"class": _INPUT}),
            "notice": forms.TextInput(attrs={"class": _INPUT}),
            "description": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 4}),
            "body": forms.Textarea(attrs={"class": _TEXTAREA, "rows": 12}),
            "effective_date": forms.DateInput(
                attrs={"class": _INPUT, "type": "date"}, format="%Y-%m-%d",
            ),
            "listing_visibility": forms.Select(attrs={"class": _SELECT}),
            "content_visibility": forms.Select(attrs={"class": _SELECT}),
            "display_order": forms.NumberInput(attrs={"class": _INPUT}),
            "file": forms.ClearableFileInput(
                attrs={"class": "file-input file-input-bordered w-full",
                       "accept": "application/pdf"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A model field with a default but no blank=True arrives required.
        self.fields["display_order"].required = False
        self.fields["file"].required = False

    def clean_display_order(self):
        value = self.cleaned_data.get("display_order")
        return 0 if value in (None, "") else value
