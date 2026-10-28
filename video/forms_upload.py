"""The form for uploading a recording made elsewhere to an event (task #851)."""
from __future__ import annotations

from django import forms

from . import uploads
from .models import Recording


class RecordingUploadForm(forms.Form):
    """A video posted to the site, or the key of one the browser already put
    in the bucket (``video_key``), plus what the recording page would otherwise
    ask. The presenter's agreement is a condition of the upload."""

    video = forms.FileField(
        required=False, label="Video file",
        help_text=f"MP4, WebM or MOV, up to {uploads.MAX_LABEL}.",
        widget=forms.ClearableFileInput(attrs={
            "accept": ",".join(uploads.VIDEO_EXTS),
            "class": "file-input file-input-bordered w-full",
        }),
    )
    video_key = forms.CharField(required=False, widget=forms.HiddenInput)
    recorded_on = forms.DateField(
        label="Recorded on",
        widget=forms.DateInput(attrs={"type": "date", "class": "input input-bordered"}),
    )
    visibility = forms.ChoiceField(
        label="Who can watch it", choices=Recording.Visibility.choices,
        initial=Recording.Visibility.MEMBERS,
        help_text="You can change this later on the recording's page.",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    consent = forms.BooleanField(
        label="The presenter agreed to this recording being shared on the site.",
        error_messages={"required": "Upload a recording only with the presenter's agreement."},
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )

    def __init__(self, *args, event, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)
        self.fields["recorded_on"].initial = event.start_date

    def clean(self):
        cleaned = super().clean()
        key, video = cleaned.get("video_key"), cleaned.get("video")
        try:
            if key:
                cleaned["video_key"] = uploads.verify_key(self.event, key)
            elif video:
                uploads.check_filename(video.name)
                if video.size > uploads.MAX_BYTES:
                    raise uploads.UploadError(
                        f"That file is over the {uploads.MAX_LABEL} limit."
                    )
            else:
                self.add_error("video", "Choose the recording's video file.")
        except uploads.UploadError as exc:
            self.add_error("video", str(exc))
        return cleaned

    def save(self, *, by) -> Recording:
        key = self.cleaned_data.get("video_key") or uploads.store_file(
            self.event, self.cleaned_data["video"],
        )
        return uploads.attach(
            self.event, key=key, by=by,
            recorded_on=self.cleaned_data["recorded_on"],
            visibility=self.cleaned_data["visibility"],
        )
