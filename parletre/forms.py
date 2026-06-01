"""Forms for posting in Parlêtre."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.template.defaultfilters import filesizeformat

from accounts.models import Profile

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


#: Disappearing-chat lifetimes. The empty value means a regular (permanent)
#: chat; the rest map to ``Channel.message_ttl_seconds``.
LIFETIME_CHOICES = [
    ("", "Keep messages (regular chat)"),
    ("3600", "Disappear after 1 hour"),
    ("86400", "Disappear after 24 hours"),
    ("604800", "Disappear after 7 days"),
]


def _participant_queryset(creator):
    """Members who may be added to a private chat — the directory population
    (matching ``mention_search``), minus the creator (always a member anyway)."""
    return (
        get_user_model()
        .objects.filter(profile__role__in=Profile.DIRECTORY_ROLES)
        .exclude(pk=creator.pk)
        .order_by("first_name", "last_name")
    )


class _ParticipantsMixin(forms.Form):
    """Shared participant picker — a multi-member field whose options are the
    addable members. Rendered by the people-picker JS, not the default
    multiselect, so the widget itself stays out of the way."""

    participants = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.none(),
        widget=forms.MultipleHiddenInput,
        error_messages={"required": "Add at least one other member."},
    )

    def __init__(self, *args, creator, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participants"].queryset = _participant_queryset(creator)


class NewPrivateChatForm(_ParticipantsMixin):
    """A member starts a private chat: name, regular-vs-disappearing, members."""

    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "input input-bordered w-full", "placeholder": "Chat name"}
        ),
    )
    lifetime = forms.ChoiceField(
        choices=LIFETIME_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    field_order = ["name", "lifetime", "participants"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Give the chat a name.")
        return name

    def clean_lifetime(self):
        raw = self.cleaned_data.get("lifetime")
        return int(raw) if raw else None


class ParticipantsForm(_ParticipantsMixin):
    """Edit a private chat's participant list after creation."""
