"""Works app views — catalog, detail, submission, gated PDF."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import F, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.http import (
    FileResponse,
    Http404,
    HttpResponseForbidden,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.access import gate_or_login

from .forms import WorkForm
from .models import Work, WorkAuthor, WorkFile


def _prefetched(qs):
    """Add authors + files prefetches (in display order) to a Work queryset."""
    return qs.prefetch_related(
        Prefetch(
            "authorships",
            queryset=WorkAuthor.objects.select_related("user").order_by("display_order"),
        ),
        Prefetch(
            "files",
            queryset=WorkFile.objects.order_by("display_order"),
        ),
    )


def _annotated_qs(user):
    """Listing queryset with authors + files prefetched in order."""
    return _prefetched(Work.listing_for(user))


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

    sort = request.GET.get("sort") or "random"
    if sort not in ("random", "year", "added", "author"):
        sort = "random"
    if sort == "year":
        qs = qs.order_by(F("publication_date").desc(nulls_last=True), "-created_at")
    elif sort == "added":
        qs = qs.order_by("-created_at")
    elif sort == "author":
        # First LSP author's last name, else the free-text external authors;
        # works with neither sort last.
        first_author = Subquery(
            WorkAuthor.objects.filter(work=OuterRef("pk"))
            .order_by("display_order")
            .values("user__last_name")[:1]
        )
        qs = qs.annotate(
            _author_key=Coalesce(
                NullIf(Lower(first_author), Value("")),
                NullIf(Lower("external_authors"), Value("")),
            )
        ).order_by(F("_author_key").asc(nulls_last=True), "title")
    else:
        qs = qs.order_by("?")

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
        "selected_sort": sort,
        "sort_choices": [
            ("random", "Random"),
            ("year", "Publication year"),
            ("added", "Recently added"),
            ("author", "Author A–Z"),
        ],
    })


def detail(request, slug):
    # Fetch unfiltered so a members-only work still resolves — then gate, so an
    # anonymous visitor following a shared link is sent to login (and returned
    # here after sign-in) rather than dead-ended at a 404.
    work = get_object_or_404(_prefetched(Work.objects.all()), slug=slug)
    if not work.listing_visible_to(request.user):
        return gate_or_login(request)
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
    # Unpublish (back to an editable draft) is offered for document works whose
    # source draft still exists and whose group the user manages.
    can_unpublish = False
    if draft is not None:
        from workgroups.permissions import can_manage_workgroup

        can_unpublish = can_manage_workgroup(request.user, draft.workgroup)
    # Streamed video (gated like the PDFs): a direct presigned S3 URL in prod
    # so the browser streams/seeks straight from S3; the local streaming view
    # as a dev fallback.
    video_url = None
    if work.video and work.content_visible_to(request.user):
        from core.storage import presigned_private_url

        video_url = presigned_private_url(work.video.name) or reverse(
            "works:video", args=[work.slug]
        )
    # Chicago citation, external publications only. The Cite block needs at
    # least a year or some structured data — title-only citations are noise.
    from .citation import citation_html, citation_text, source_html

    has_citation = work.kind == Work.Kind.EXTERNAL and (
        work.has_structured_citation or work.publication_date
    )
    return render(request, "works/detail.html", {
        "work": work,
        "citation": citation_html(work) if has_citation else "",
        "citation_txt": citation_text(work) if has_citation else "",
        "source_line": source_html(work) if work.kind == Work.Kind.EXTERNAL else "",
        "can_edit": work.editable_by(request.user),
        "content_visible": work.content_visible_to(request.user),
        "video_url": video_url,
        "revisions": revisions,
        "source_draft": draft,
        "can_unpublish": can_unpublish,
    })


VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v")
_INCOMING_PREFIX = "works/videos/incoming/"


@login_required
@require_POST
def video_presign(request):
    """Hand the browser a one-time ticket to upload a video straight to S3,
    bypassing the app server. Gated like the upload itself (member + the
    web-developer enable switch); the size cap is enforced by S3 via the
    presigned POST conditions. Returns ``{fallback: true}`` when there's no
    private bucket (dev), so the form falls back to a server-side upload."""
    import json
    import uuid

    from django.http import JsonResponse

    from accounts.permissions import is_lsp_member
    from core.storage import presigned_upload_post

    from .models import VideoUploadSettings

    if not is_lsp_member(request.user):
        raise Http404()
    cfg = VideoUploadSettings.load()
    if not cfg.enabled:
        return JsonResponse({"error": "Video uploads are turned off."}, status=403)

    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"error": "Bad request."}, status=400)
    filename = (payload.get("filename") or "").strip()
    content_type = (payload.get("content_type") or "").strip()
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in VIDEO_EXTS or not content_type.startswith("video/"):
        return JsonResponse({"error": "Please choose an MP4, WebM, or MOV file."}, status=400)

    # A locked, unique key under the temporary incoming/ prefix (an S3 lifecycle
    # rule expires anything left here; attach promotes it to a permanent key).
    key = f"{_INCOMING_PREFIX}{uuid.uuid4().hex}{ext}"
    post = presigned_upload_post(key, max_bytes=cfg.max_file_bytes, content_type=content_type)
    if post is None:
        return JsonResponse({"fallback": True})  # dev: no bucket → server-side upload
    return JsonResponse({"key": key, "url": post["url"], "fields": post["fields"]})


def video(request, slug):
    """Stream a work's video, gated by content visibility. Redirects to a
    presigned S3 URL in prod (range-capable), or streams the local file in dev."""
    work = get_object_or_404(Work, slug=slug)
    if not work.content_visible_to(request.user):
        return gate_or_login(request)
    if not work.video:
        raise Http404()
    from core.storage import presigned_private_url

    url = presigned_private_url(work.video.name)
    if url:
        return HttpResponseRedirect(url)
    filename = work.video.name.rsplit("/", 1)[-1]
    return FileResponse(work.video.open("rb"), filename=filename)


def download(request, slug, file_id):
    work = get_object_or_404(Work, slug=slug)
    if not work.content_visible_to(request.user):
        return gate_or_login(request)
    wf = get_object_or_404(WorkFile, pk=file_id, work=work)
    filename = wf.file.name.rsplit("/", 1)[-1]
    return FileResponse(wf.file.open("rb"), as_attachment=False, filename=filename)


@login_required
def add(request):
    # A caller (e.g. the My Formation hub) can pre-pick the kind and ask to be
    # returned to its page via ?kind=&next=.
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ""
    if request.method == "POST":
        form = WorkForm(request.POST, request.FILES, current_user=request.user)
        if form.is_valid():
            work = form.save()
            return redirect(next_url or work.get_absolute_url())
    else:
        initial = {}
        kind = request.GET.get("kind")
        if kind in Work.Kind.values:
            initial["kind"] = kind
        form = WorkForm(current_user=request.user, initial=initial)
    return render(request, "works/form.html", {
        "form": form,
        "is_new": True,
        "next": next_url,
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
@require_POST
def delete(request, slug):
    """Remove a work entirely (and its attached files). If it was published
    from a draft, the draft survives — its ``published_work`` link just nulls,
    so the document can be re-published or further edited."""
    work = get_object_or_404(Work, slug=slug)
    if not work.editable_by(request.user):
        return HttpResponseForbidden("You don't have permission to delete this work.")
    wg = work.workgroup
    work.delete()
    if wg is not None:
        return redirect(f"{wg.get_absolute_url()}?tab=work")
    return redirect("works:index")


@login_required
def my_works(request):
    """Legacy ``/works/mine/`` — now the My LSP hub's Works tab."""
    from django.urls import reverse

    return redirect(reverse("formation:formation") + "?tab=works")
