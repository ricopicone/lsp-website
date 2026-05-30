"""Forms for posting in Parlêtre."""

from __future__ import annotations

from django import forms

_TEXTAREA = forms.Textarea(
    attrs={
        "class": "textarea textarea-bordered w-full",
        "rows": 5,
        "placeholder": "Write in Markdown…",
    }
)


class NewThreadForm(forms.Form):
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": "input input-bordered w-full", "placeholder": "Thread title"}
        ),
    )
    body = forms.CharField(widget=_TEXTAREA)

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Say something.")
        return body


class PostForm(forms.Form):
    """A single message — a forum reply or a chat post."""

    body = forms.CharField(widget=_TEXTAREA, label="")

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Say something.")
        return body
