"""Forms for a member's private meeting room (task #687)."""
from __future__ import annotations

import re
from typing import NamedTuple

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

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


#: One person per line, in the ordinary mail convention. Each line is a name, an
#: address, or both — ``Jane Doe <jane@example.com>``.
_RECIPIENT_LINE = re.compile(
    r"""^\s*
        (?P<name>[^<>]*?)?          # optional display name
        \s*
        (?:<\s*(?P<angled>[^<>\s]+)\s*>)?   # optional <address>
        \s*$""",
    re.VERBOSE,
)


class Recipient(NamedTuple):
    """One person to invite, after parsing. Exactly one of ``user`` / a guest
    name is what the invitation ends up carrying."""

    user: object | None
    name: str
    email: str

    @property
    def label(self) -> str:
        if self.user is not None:
            return self.user.get_full_name() or self.user.email
        return self.name or self.email


class MemberChoiceField(forms.ModelMultipleChoiceField):
    """A person picker labelled by name.

    ``ModelChoiceField`` falls back to ``str(user)``, which for this project's
    email-login ``User`` is the address. An address is how the site finds
    someone, not how a member thinks of them; the fallback below shows only for
    an account with no name recorded.
    """

    def label_from_instance(self, user):
        return user.get_full_name() or user.email


class InvitationForm(forms.Form):
    """Invite one or more people.

    Two ways to name them, and both may be used at once:

    * tick **LSP members** in the list — already public in the directory, so the
      list discloses nothing new; the box above it filters live, since eighty
      names is more than anyone wants to scroll;
    * type **anyone else**, one per line, as a name, an address, or
      ``Jane Doe <jane@example.com>``.

    The email is only ever for *sending* the invitation. It is not required and
    it gates nothing: a guest link admits whoever opens it, so asking for an
    address the member may not have would be asking for something the room does
    not use. Given one, we resolve it against existing accounts first — an
    applicant, an auditor, an outside speaker already has a login, and binding
    the invitation to it is better than a secret link — and mail the link
    otherwise.

    There is deliberately no picker listing every account on the site: that
    would hand any member a roster of everyone who has ever signed up.
    """

    members = MemberChoiceField(
        queryset=None, required=False, label="LSP members",
        widget=forms.CheckboxSelectMultiple,
    )
    others = forms.CharField(
        required=False, label="Or anyone else, one per line",
        widget=forms.Textarea(attrs={
            "class": "textarea textarea-bordered w-full font-mono text-sm",
            "rows": 3,
            "placeholder": "Jane Doe\njane@example.com\nJane Doe <jane@example.com>",
        }),
        help_text=(
            "A name, an email address, or both. The address is only so we can send "
            "them the link, leave it out and copy the link yourself."
        ),
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
        self.fields["members"].queryset = self._member_queryset()

    def _member_queryset(self):
        """Directory-listed members, minus the training-sandbox personas.

        Personas are disposable test accounts the Web Coordinator impersonates;
        they carry real memberships for fidelity but must never appear on a
        roster a member reads (``personas-off-public-rosters``), and inviting
        one to a meeting is meaningless.
        """
        from accounts.models import Profile, User

        qs = User.objects.filter(
            is_active=True,
            profile__role__in=Profile.DIRECTORY_ROLES,
        ).exclude(
            profile__standing__in=Profile.NON_MEMBER_STANDINGS,
        ).exclude(profile__is_persona=True)
        if self.room is not None:
            qs = qs.exclude(pk=self.room.user_id)
        return qs.order_by("last_name", "first_name")

    def clean(self):
        data = super().clean()
        recipients: list[Recipient] = []
        seen_users: set = set()
        seen_labels: set = set()

        for user in data.get("members") or []:
            recipients.append(Recipient(user=user, name="", email=""))
            seen_users.add(user.pk)

        for line in (data.get("others") or "").splitlines():
            recipient = self._parse_line(line)
            if recipient is None:
                continue
            # The same person named twice (ticked and typed) is one invitation.
            if recipient.user is not None:
                if recipient.user.pk in seen_users:
                    continue
                seen_users.add(recipient.user.pk)
            else:
                key = (recipient.name.lower(), recipient.email.lower())
                if key in seen_labels:
                    continue
                seen_labels.add(key)
            recipients.append(recipient)

        if not recipients and not self.errors:
            raise forms.ValidationError("Choose a member, or type someone's name.")
        data["recipients"] = recipients
        return data

    def _parse_line(self, line: str) -> Recipient | None:
        """One typed line into a recipient, or None for a blank one."""
        from accounts.models import User

        raw = line.strip()
        if not raw:
            return None
        match = _RECIPIENT_LINE.match(raw)
        name = (match.group("name") or "").strip() if match else raw
        email = (match.group("angled") or "").strip() if match else ""
        # A bare address with no angle brackets lands in the name group.
        if not email and "@" in name and " " not in name:
            name, email = "", name
        if email:
            try:
                EmailValidator()(email)
            except ValidationError:
                self.add_error("others", f"“{raw}” does not look like an email address.")
                return None
            existing = User.objects.filter(email__iexact=email).first()
            if existing is not None:
                return Recipient(user=existing, name="", email="")
        if not name and not email:
            return None
        if not name:
            self.add_error(
                "others", f"Give a name for {email}, so you can see who is at the door."
            )
            return None
        return Recipient(user=None, name=name[:120], email=email)

    def already_invited(self, recipient) -> bool:
        if recipient.user is None or self.room is None:
            return False
        return self.room.invitations.live().filter(invited_user=recipient.user).exists()

    def build(self, recipient) -> RoomInvitation:
        """Create the invitation for one recipient (internal or guest)."""
        common = {
            "room": self.room,
            "note": (self.cleaned_data.get("note") or "").strip(),
            "expires_at": RoomInvitation.default_expiry(),
        }
        if recipient.user is not None:
            return RoomInvitation.objects.create(invited_user=recipient.user, **common)
        return RoomInvitation.objects.create(
            token=RoomInvitation.new_token(),
            guest_name=recipient.name,
            guest_email=recipient.email,
            **common,
        )


class GuestJoinForm(forms.Form):
    """The name a guest will appear under in the People panel."""

    display_name = forms.CharField(
        max_length=120, label="Your name",
        widget=forms.TextInput(attrs={"class": _INPUT, "autofocus": "autofocus"}),
    )
