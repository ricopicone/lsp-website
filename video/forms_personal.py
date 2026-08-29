"""Forms for a member's private meeting room (task #687)."""
from __future__ import annotations

from django import forms

from .models import PersonalRoom, RoomInvitation

_INPUT = "input input-bordered w-full"
_SELECT = "select select-bordered w-full"


class PersonalRoomSettingsForm(forms.ModelForm):
    """Recording and office hours, the two things the member controls."""

    class Meta:
        model = PersonalRoom
        fields = ("recording_mode", "office_hours", "hours_note")
        widgets = {
            "recording_mode": forms.Select(attrs={"class": _SELECT}),
            "office_hours": forms.Select(attrs={"class": _SELECT}),
            "hours_note": forms.TextInput(attrs={
                "class": _INPUT,
                "placeholder": "Thursdays 3-4pm Pacific",
            }),
        }
        labels = {
            "recording_mode": "Recording",
            "office_hours": "Office hours",
            "hours_note": "When (or how to arrange it)",
        }
        help_texts = {
            "hours_note": (
                "Shown to members on your directory page, and to the students of "
                "any seminar or reading group you lead."
            ),
        }

    def clean(self):
        data = super().clean()
        # Advertising nothing is the same as not advertising: rather than reject
        # the pair, say what is missing, since the member plainly meant to post.
        if data.get("office_hours") != PersonalRoom.OfficeHours.OFF and not (
            data.get("hours_note") or ""
        ).strip():
            self.add_error("hours_note", "Add a line saying when, or how to arrange a time.")
        return data


class InvitationForm(forms.Form):
    """Invite one person.

    Two ways to name them, resolved in :meth:`clean`:

    * pick an **LSP member** from the list — already public in the directory, so
      the list discloses nothing new; or
    * give an **email address** for anyone else. If it matches an account (an
      applicant, an auditor, an outside speaker) the invitation binds to that
      account and they sign in as themselves; otherwise it becomes a guest
      invitation with a secret link.

    There is deliberately no picker listing every account on the site: that
    would hand any member a roster of everyone who has ever signed up.
    """

    member = forms.ModelChoiceField(
        queryset=None, required=False, label="An LSP member",
        empty_label="Choose a member…",
        widget=forms.Select(attrs={"class": _SELECT}),
    )
    email = forms.EmailField(
        required=False, label="Or an email address",
        widget=forms.EmailInput(attrs={"class": _INPUT, "placeholder": "name@example.com"}),
    )
    name = forms.CharField(
        required=False, max_length=120, label="Their name",
        widget=forms.TextInput(attrs={"class": _INPUT, "placeholder": "Jane Doe"}),
    )
    note = forms.CharField(
        required=False, max_length=200, label="A note for them (optional)",
        widget=forms.TextInput(attrs={
            "class": _INPUT, "placeholder": "Our interview, Thursday at 2",
        }),
    )
    send_email = forms.BooleanField(
        required=False, initial=True, label="Email them the link",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )

    def __init__(self, *args, room=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.room = room
        self.fields["member"].queryset = self._member_queryset()

    def _member_queryset(self):
        from accounts.models import Profile, User

        qs = User.objects.filter(
            is_active=True,
            profile__role__in=Profile.DIRECTORY_ROLES,
        ).exclude(profile__standing__in=Profile.NON_MEMBER_STANDINGS)
        if self.room is not None:
            qs = qs.exclude(pk=self.room.user_id)
        return qs.order_by("last_name", "first_name")

    def clean(self):
        data = super().clean()
        member, email = data.get("member"), (data.get("email") or "").strip()
        if member and email:
            raise forms.ValidationError(
                "Choose a member or give an email address, not both."
            )
        if not member and not email:
            raise forms.ValidationError("Choose a member, or give an email address.")

        if member:
            data["invited_user"] = member
            return data

        from accounts.models import User

        data["invited_user"] = User.objects.filter(email__iexact=email).first()
        if data["invited_user"] is None and not (data.get("name") or "").strip():
            self.add_error("name", "Give a name, so you can see who is at the door.")
        return data

    def already_invited(self) -> bool:
        user = self.cleaned_data.get("invited_user")
        if user is None or self.room is None:
            return False
        return self.room.invitations.live().filter(invited_user=user).exists()

    def build(self) -> RoomInvitation:
        """Create the invitation this form describes (internal or guest)."""
        data = self.cleaned_data
        user = data.get("invited_user")
        common = {
            "room": self.room,
            "note": (data.get("note") or "").strip(),
            "expires_at": RoomInvitation.default_expiry(),
        }
        if user is not None:
            return RoomInvitation.objects.create(invited_user=user, **common)
        return RoomInvitation.objects.create(
            token=RoomInvitation.new_token(),
            guest_name=(data.get("name") or "").strip(),
            guest_email=(data.get("email") or "").strip(),
            **common,
        )


class GuestJoinForm(forms.Form):
    """The name a guest will appear under in the People panel."""

    display_name = forms.CharField(
        max_length=120, label="Your name",
        widget=forms.TextInput(attrs={"class": _INPUT, "autofocus": "autofocus"}),
    )
