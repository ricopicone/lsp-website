"""Forms for posting in Parlêtre."""

from __future__ import annotations

from django import forms
from django.template.defaultfilters import filesizeformat

from .models import MAX_ATTACHMENT_BYTES

_TEXTAREA = forms.Textarea(
    attrs={
        "class": "textarea textarea-bordered w-full",
        "rows": 5,
        "placeholder": "Write in Markdown…",
    }
)


class _MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A FileField that accepts several files at once (Django's documented
    multi-upload recipe), each capped at ``MAX_ATTACHMENT_BYTES``."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            _MultipleFileInput(
                attrs={
                    "class": "file-input file-input-bordered file-input-sm w-full",
                    "multiple": True,
                }
            ),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        items = data if isinstance(data, (list, tuple)) else [data]
        cleaned = []
        for item in items:
            if item in (None, "", False):
                continue
            value = single(item, initial)
            if value.size > MAX_ATTACHMENT_BYTES:
                raise forms.ValidationError(
                    f"“{value.name}” is too large (max {filesizeformat(MAX_ATTACHMENT_BYTES)})."
                )
            cleaned.append(value)
        return cleaned


class NewThreadForm(forms.Form):
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": "input input-bordered w-full", "placeholder": "Thread title"}
        ),
    )
    body = forms.CharField(widget=_TEXTAREA)
    attachments = MultipleFileField(required=False)

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Say something.")
        return body


class PostForm(forms.Form):
    """A single message — a forum reply or a chat post."""

    body = forms.CharField(widget=_TEXTAREA, label="")
    attachments = MultipleFileField(required=False)
    reply_to = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Say something.")
        return body


class EditPostForm(forms.Form):
    """Edit an existing post's body."""

    body = forms.CharField(widget=_TEXTAREA, label="")

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Say something.")
        return body
