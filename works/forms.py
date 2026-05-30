"""Submission form for member-contributed works.

The author entry is the trickiest part: members type LSP co-authors as
a comma-separated list of names or emails, and the form's clean step
resolves each entry to a User. Free-text co-authors who aren't in our
system go in ``external_authors`` instead.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.text import slugify

from .models import Work

User = get_user_model()


def _resolve_user(token: str):
    """Look up a User by email (preferred), then by 'First Last' name.

    Returns the User or None. Case-insensitive on both axes.
    """
    token = token.strip()
    if not token:
        return None
    if "@" in token:
        return User.objects.filter(email__iexact=token).first()
    parts = token.split()
    if len(parts) >= 2:
        first, *_, last = parts
        return User.objects.filter(
            Q(first_name__iexact=first) & Q(last_name__iexact=last)
        ).first()
    return User.objects.filter(
        Q(first_name__iexact=token) | Q(last_name__iexact=token)
    ).first()


class WorkForm(forms.ModelForm):
    """ModelForm with a free-text author field that resolves to User M2M."""

    lsp_authors = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "textarea textarea-bordered w-full"}),
        help_text=(
            "Comma-separated LSP co-authors. Use email addresses or "
            "'First Last' names. You are added automatically — list "
            "co-authors here, in byline order."
        ),
    )

    class Meta:
        model = Work
        fields = (
            "title",
            "kind",
            "abstract",
            "publication_info",
            "url",
            "publication_date",
            "pdf",
            "cover_image",
            "external_authors",
            "listing_visibility",
            "pdf_visibility",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "kind": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "abstract": forms.Textarea(attrs={
                "rows": 5,
                "class": "textarea textarea-bordered w-full",
                "placeholder": "Short summary (markdown supported)",
            }),
            "publication_info": forms.TextInput(attrs={
                "class": "input input-bordered w-full",
                "placeholder": "Journal of X, Vol 12 (2024), pp. 33–58",
            }),
            "url": forms.URLInput(attrs={
                "class": "input input-bordered w-full",
                "placeholder": "https://…",
            }),
            "publication_date": forms.DateInput(attrs={
                "type": "date",
                "class": "input input-bordered w-full",
            }),
            "external_authors": forms.TextInput(attrs={
                "class": "input input-bordered w-full",
                "placeholder": "Co-authors not in our system (free text)",
            }),
            "listing_visibility": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "pdf_visibility": forms.Select(attrs={"class": "select select-bordered w-full"}),
        }

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        # CARTEL kind is in the data model but its cartel-FK + cartel-internal
        # visibility belong to M14. Hide it from the v1 submission form.
        if "kind" in self.fields:
            self.fields["kind"].choices = [
                (v, label) for v, label in self.fields["kind"].choices
                if v != Work.Kind.CARTEL
            ]
        # Seed lsp_authors with existing co-authors (minus the current user)
        # so editors don't lose the list on round-trip.
        if self.instance and self.instance.pk and not self.is_bound:
            others = [
                a for a in self.instance.authors.all().order_by("authorships__display_order")
                if not current_user or a.pk != current_user.pk
            ]
            self.fields["lsp_authors"].initial = ", ".join(
                f"{u.first_name} {u.last_name}".strip() or u.email for u in others
            )

    # ---- Field-level cleaning ----

    def clean_lsp_authors(self):
        raw = (self.cleaned_data.get("lsp_authors") or "").strip()
        if not raw:
            return []
        users = []
        unmatched = []
        for token in [t for t in (s.strip() for s in raw.split(",")) if t]:
            u = _resolve_user(token)
            if u is None:
                unmatched.append(token)
            elif u not in users:
                users.append(u)
        if unmatched:
            raise forms.ValidationError(
                "Couldn't find LSP members matching: "
                + ", ".join(repr(t) for t in unmatched)
                + ". Use the exact email address, or 'First Last' as it appears in the directory. "
                "For people not in our system, list them under 'External co-authors' instead."
            )
        return users

    def clean(self):
        cleaned = super().clean()
        # Cross-field check: model.clean enforces PDF/listing visibility,
        # but Django's ModelForm won't call full_clean automatically — we
        # invoke it here so the form sees the error in-line on the right
        # field instead of just a __all__ message.
        instance = self.instance
        for field, value in cleaned.items():
            setattr(instance, field, value)
        try:
            instance.clean()
        except forms.ValidationError as e:
            # Re-raise so ModelForm attaches errors to the right fields.
            for field, errors in e.error_dict.items() if hasattr(e, "error_dict") else []:
                for err in errors:
                    self.add_error(field, err)
        return cleaned

    # ---- Save: write authors + slug + submitted_by ----

    def save(self, commit=True):
        from django.db import transaction

        from .models import WorkAuthor

        instance: Work = super().save(commit=False)

        if not instance.slug:
            base = slugify(instance.title) or "work"
            slug = base
            n = 2
            while Work.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            instance.slug = slug

        if not instance.pk and self.current_user:
            instance.submitted_by = self.current_user

        co_authors = self.cleaned_data.get("lsp_authors") or []
        # Current user is author #1; co-authors follow in byline order.
        byline: list = []
        if self.current_user:
            byline.append(self.current_user)
        for u in co_authors:
            if u not in byline:
                byline.append(u)

        if not commit:
            return instance

        with transaction.atomic():
            instance.save()
            # Replace authorships to match the byline order.
            WorkAuthor.objects.filter(work=instance).delete()
            for i, user in enumerate(byline):
                WorkAuthor.objects.create(work=instance, user=user, display_order=i)

        return instance
