"""The member-facing suggestion form.

Member-visible fields (kind, title, body, screenshot) plus two hidden inputs the
floating widget fills from the current page (``page_url``/``page_title``). The
``context`` blob is read straight from POST in the view, not modelled here.
"""

from __future__ import annotations

from django import forms

from .models import Suggestion


class SuggestionForm(forms.ModelForm):
    class Meta:
        model = Suggestion
        fields = ("kind", "title", "body", "page_url", "page_title", "screenshot")
        widgets = {
            "kind": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "title": forms.TextInput(attrs={
                "class": "input input-bordered w-full",
                "placeholder": "A short summary",
                "maxlength": 200,
            }),
            "body": forms.Textarea(attrs={
                "rows": 4, "class": "textarea textarea-bordered w-full",
                "placeholder": "What would you change? For a bug, what did you "
                               "expect to happen instead?",
            }),
            "screenshot": forms.ClearableFileInput(attrs={
                "class": "file-input file-input-bordered w-full",
                "accept": "image/*",
            }),
            "page_url": forms.HiddenInput(),
            "page_title": forms.HiddenInput(),
        }

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Please describe the change you have in mind.")
        return body
