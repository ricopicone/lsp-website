"""Works app views — catalog, detail, submission, gated PDF."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .forms import WorkForm
from .models import Work, WorkAuthor, WorkFile


def _annotated_qs(user):
    """Listing queryset with authors + files prefetched in order."""
    return (
        Work.listing_for(user)
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
    )


def index(request):
    qs = _annotated_qs(request.user)

    kind = request.GET.get("kind") or ""
    year = request.GET.get("year") or ""
    has_pdf = request.GET.get("has_pdf") == "1"
    q = (request.GET.get("q") or "").strip()

    if kind:
        qs = qs.filter(kind=kind)
    if year and year.isdigit():
        qs = qs.filter(publication_date__year=int(year))
    if has_pdf:
        qs = qs.filter(files__isnull=False).distinct()
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(abstract__icontains=q)
            | Q(external_authors__icontains=q)
            | Q(authors__first_name__icontains=q)
            | Q(authors__last_name__icontains=q)
        ).distinct()

    years_qs = (
        _annotated_qs(request.user)
        .exclude(publication_date__isnull=True)
        .values_list("publication_date__year", flat=True)
        .distinct()
        .order_by("-publication_date__year")
    )

    return render(request, "works/index.html", {
        "works": qs,
        "kind_choices": [(c.value, c.label) for c in Work.Kind if c != Work.Kind.CARTEL],
        "all_kind_choices": Work.Kind.choices,
        "years": list(years_qs),
        "selected_kind": kind,
        "selected_year": year,
        "has_pdf": has_pdf,
        "q": q,
    })


def detail(request, slug):
    work = get_object_or_404(_annotated_qs(request.user), slug=slug)
    if not work.listing_visible_to(request.user):
        raise Http404()
    # Publication revisions — the "Published" snapshots of the source draft,
    # oldest → newest, so each carries a stable revision number.
    revisions = []
    draft = getattr(work, "source_draft", None)
    if draft is not None:
        pubs = list(draft.versions.filter(label="Published")
                    .select_related("saved_by").order_by("saved_at"))
        revisions = [
            {"number": i + 1, "saved_at": v.saved_at, "saved_by": v.saved_by}
            for i, v in enumerate(pubs)
        ]
        revisions.reverse()  # newest first for display
    return render(request, "works/detail.html", {
        "work": work,
        "can_edit": work.editable_by(request.user),
        "pdf_visible": work.pdf_visible_to(request.user),
        "revisions": revisions,
    })


def download(request, slug, file_id):
    work = get_object_or_404(Work, slug=slug)
    if not work.pdf_visible_to(request.user):
        raise Http404()
    wf = get_object_or_404(WorkFile, pk=file_id, work=work)
    filename = wf.file.name.rsplit("/", 1)[-1]
    return FileResponse(wf.file.open("rb"), as_attachment=False, filename=filename)


@login_required
def add(request):
    if request.method == "POST":
        form = WorkForm(request.POST, request.FILES, current_user=request.user)
        if form.is_valid():
            work = form.save()
            return redirect(work.get_absolute_url())
    else:
        form = WorkForm(current_user=request.user)
    return render(request, "works/form.html", {
        "form": form,
        "is_new": True,
    })


@login_required
def edit(request, slug):
    work = get_object_or_404(Work, slug=slug)
    if not work.editable_by(request.user):
        return HttpResponseForbidden("You don't have permission to edit this work.")
    if request.method == "POST":
        form = WorkForm(
            request.POST, request.FILES, instance=work, current_user=request.user,
        )
        if form.is_valid():
            work = form.save()
            return redirect(work.get_absolute_url())
    else:
        form = WorkForm(instance=work, current_user=request.user)
    return render(request, "works/form.html", {
        "form": form,
        "work": work,
        "is_new": False,
    })


@login_required
def my_works(request):
    """List the works ``request.user`` authored or submitted."""
    qs = (
        Work.objects.filter(
            Q(authorships__user=request.user) | Q(submitted_by=request.user)
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
    return render(request, "works/my_works.html", {"works": qs})
