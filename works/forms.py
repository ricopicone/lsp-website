"""Submission form for member-contributed works.

Two tricky bits beyond a plain ModelForm:

* **Authors**: members type LSP co-authors as comma-separated names or
  emails; ``clean_lsp_authors`` resolves each entry to a User. Free-text
  co-authors who aren't in our system go in ``external_authors``.

* **Files**: a Work has zero or more attached PDFs (``WorkFile`` rows).
  The form takes one new file + label at a time and, on edit, exposes
  every existing file with relabel + remove. When the final file count
  is two or more, every file must have a non-empty label.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Max, Q
from django.utils.text import slugify

from .models import Work, WorkFile

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
    """ModelForm with author resolution + per-file relabel/remove/add."""

    lsp_authors = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "textarea textarea-bordered w-full"}),
        help_text=(
            "Comma-separated LSP co-authors. Use email addresses or "
            "'First Last' names. You are added automatically — list "
            "co-authors here, in byline order."
        ),
    )
    new_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "file-input file-input-bordered w-full"}),
        help_text="Upload a PDF. To add more files, save and edit again.",
    )
    new_file_label = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "input input-bordered w-full",
            "placeholder": "Optional when this is the only file",
        }),
        help_text="Required when the work has multiple files.",
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
            "cover_image",
            "external_authors",
            "workgroup",
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
            "workgroup": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "listing_visibility": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "pdf_visibility": forms.Select(attrs={"class": "select select-bordered w-full"}),
        }

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

        # Workgroup picker: a member may attach a work to a group they belong
        # to (which unlocks the "Workgroup members only" visibility). Limit the
        # choices to the user's active groups, keeping any group already set on
        # the instance (so staff editing doesn't silently drop it).
        if "workgroup" in self.fields:
            from workgroups.models import Workgroup, WorkgroupMembership

            ids = set()
            if current_user is not None and getattr(current_user, "is_authenticated", False):
                ids.update(
                    WorkgroupMembership.objects.filter(
                        user=current_user, end_date__isnull=True
                    ).values_list("workgroup_id", flat=True)
                )
            if self.instance and self.instance.workgroup_id:
                ids.add(self.instance.workgroup_id)
            self.fields["workgroup"].queryset = Workgroup.objects.filter(pk__in=ids)
            self.fields["workgroup"].required = False
            self.fields["workgroup"].help_text = (
                "Attach this to one of your groups. Required if you set a "
                "visibility of 'Workgroup members only'."
            )
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
        # Inject one label + remove field per existing WorkFile so the edit
        # form can relabel or remove each file inline.
        self._existing_file_ids: list[int] = []
        if self.instance and self.instance.pk:
            for f in self.instance.files.all().order_by("display_order"):
                self._existing_file_ids.append(f.pk)
                self.fields[f"file_{f.pk}_label"] = forms.CharField(
                    required=False,
                    initial=f.label,
                    widget=forms.TextInput(attrs={"class": "input input-bordered input-sm w-full"}),
                )
                self.fields[f"file_{f.pk}_remove"] = forms.BooleanField(
                    required=False,
                    widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
                )

    # ---- Convenience for the template ----

    def existing_files(self):
        """Yield (WorkFile, label_field, remove_field) tuples for the template."""
        if not (self.instance and self.instance.pk):
            return
        files = {f.pk: f for f in self.instance.files.all().order_by("display_order")}
        for pk in self._existing_file_ids:
            yield files[pk], self[f"file_{pk}_label"], self[f"file_{pk}_remove"]

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

        # Visibility constraint (delegate to Model.clean for error placement).
        instance = self.instance
        for field, value in cleaned.items():
            if field in self.Meta.fields:
                setattr(instance, field, value)
        try:
            instance.clean()
        except forms.ValidationError as e:
            for field, errors in (e.error_dict.items() if hasattr(e, "error_dict") else []):
                for err in errors:
                    self.add_error(field, err)

        # File label rule: if the post-save state has >= 2 files, every
        # file (existing kept + the new one) must carry a non-empty label.
        existing_kept_pks = [
            pk for pk in self._existing_file_ids
            if not cleaned.get(f"file_{pk}_remove")
        ]
        new_file = cleaned.get("new_file")
        new_label = (cleaned.get("new_file_label") or "").strip()
        total = len(existing_kept_pks) + (1 if new_file else 0)

        if total >= 2:
            # Check every kept existing file has a label.
            for pk in existing_kept_pks:
                label_val = (cleaned.get(f"file_{pk}_label") or "").strip()
                if not label_val:
                    self.add_error(
                        f"file_{pk}_label",
                        "Label required when the work has multiple files.",
                    )
            if new_file and not new_label:
                self.add_error(
                    "new_file_label",
                    "Label required when the work has multiple files.",
                )

        return cleaned

    # ---- Save: write authors + slug + submitted_by + file ops ----

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

            # Authorships: replace to match byline order.
            WorkAuthor.objects.filter(work=instance).delete()
            for i, user in enumerate(byline):
                WorkAuthor.objects.create(work=instance, user=user, display_order=i)

            # Existing files: relabel and remove.
            for pk in self._existing_file_ids:
                wf = WorkFile.objects.filter(pk=pk, work=instance).first()
                if wf is None:
                    continue
                if self.cleaned_data.get(f"file_{pk}_remove"):
                    wf.delete()
                else:
                    new_label = (self.cleaned_data.get(f"file_{pk}_label") or "").strip()
                    if wf.label != new_label:
                        wf.label = new_label
                        wf.save(update_fields=["label"])

            # New file: append at the end of display_order.
            new_file = self.cleaned_data.get("new_file")
            if new_file:
                last = (
                    WorkFile.objects.filter(work=instance).aggregate(m=Max("display_order"))["m"]
                    or 0
                )
                WorkFile.objects.create(
                    work=instance,
                    file=new_file,
                    label=(self.cleaned_data.get("new_file_label") or "").strip(),
                    display_order=last + 1,
                )

        return instance
