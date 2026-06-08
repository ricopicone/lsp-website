"""Reusable Work querysets — shared by the works views and the My LSP hub's
Works tab so the two never drift."""

from __future__ import annotations

from django.db.models import Prefetch, Q

from .models import Work, WorkAuthor, WorkFile


def my_works_qs(user):
    """The works ``user`` authored or submitted, newest first, with authors and
    files prefetched for listing."""
    return (
        Work.objects.filter(
            Q(authorships__user=user) | Q(submitted_by=user)
        )
        .prefetch_related(
            Prefetch(
                "authorships",
                queryset=WorkAuthor.objects.select_related("user").order_by("display_order"),
            ),
            Prefetch(
                "files",
                queryset=WorkFile.objects.order_by("display_order"),
            ),
        )
        .distinct()
        .order_by("-publication_date", "-created_at")
    )
