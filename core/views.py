"""Landing page and unified calendar (PROG-1, PROG-6)."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import connections, models
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.context_processors import SITE_THEME_COOKIE, SITE_THEMES
from events.models import Event, Session


def set_site_theme(request, theme):
    """Persist the site-theme skin choice (``modern`` | ``wix``) in a cookie and
    return to where the visitor was. Drives the footer switch and works as a
    shareable link (e.g. ``/site-theme/wix/?next=/about/``) so the Board can
    preview either look. See core.context_processors.site_theme."""
    if theme not in SITE_THEMES:
        theme = "modern"
    nxt = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = "/"
    response = redirect(nxt)
    response.set_cookie(
        SITE_THEME_COOKIE, theme, max_age=60 * 60 * 24 * 365, samesite="Lax"
    )
    return response


def healthz(request):
    """Readiness probe for the blue-green deploy flip (ops/deploy/deploy.sh).

    Returns 200 only when the app is serving *and* can reach the database — so a
    new container that can't talk to RDS (e.g. after a master-credential rotation)
    fails the check and the deploy aborts before flipping traffic to it, rather
    than swapping in a broken color. Cheap, unauthenticated, no template.
    """
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return HttpResponse("db unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def landing(request):
    """Public landing page for app.lacanschool.org — the school's front door."""
    from accounts.models import Profile
    from workgroups.models import Visibility, Workgroup

    today = timezone.now().date()
    # "Coming up" shows events that haven't started yet — with one exception:
    # seminars (year-long) that started within the last month and aren't over,
    # so a freshly-begun seminar still surfaces for late registration.
    a_month_ago = today - timedelta(days=31)
    seminar_types = [Event.Type.SEMINAR, Event.Type.SCHOLARLY_SEMINAR]
    upcoming = (
        Event.objects.filter(published=True)
        .filter(
            models.Q(start_date__gte=today)
            | models.Q(
                event_type__in=seminar_types,
                start_date__gte=a_month_ago,
                start_date__lt=today,
                end_date__gte=today,
            )
        )
        .order_by("start_date", "title")[:4]
    )

    # Grounded figures woven into the page (each rendered only when positive).
    directory_count = Profile.objects.filter(
        role__in=Profile.DIRECTORY_ROLES, public=True
    ).count()
    analyst_count = Profile.objects.filter(
        role=Profile.Role.ANALYST, public=True
    ).count()
    seminar_count = (
        Workgroup.objects.filter(
            kind=Workgroup.Kind.SEMINAR, landing_visibility=Visibility.PUBLIC
        )
        .filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))
        .count()
    )

    dues_period_unpaid = None
    dues_amount_owed = None
    if request.user.is_authenticated:
        from payments.dues import is_dues_obligated, user_paid_for_period
        from payments.models import DuesPeriod

        # Dues banner for obligated unpaid members.
        current_period = DuesPeriod.current()
        if (
            current_period is not None
            and is_dues_obligated(request.user)
            and not user_paid_for_period(request.user, current_period)
        ):
            dues_period_unpaid = current_period
            dues_amount_owed = current_period.amount_for_role(
                request.user.profile.role
            )

    return render(
        request,
        "core/landing.html",
        {
            "upcoming_events": upcoming,
            "directory_count": directory_count,
            "analyst_count": analyst_count,
            "seminar_count": seminar_count,
            "dues_period_unpaid": dues_period_unpaid,
            "dues_amount_owed": dues_amount_owed,
        },
    )


def _is_staff(user):
    return user.is_authenticated and user.is_staff


def set_walkthrough(request):
    """Start (or exit) a guide walkthrough: set the ``lsp_walkthrough`` cookie
    so the floating card follows the viewer through it, then return to the
    feature. An unknown id — or the default — clears the cookie."""
    from django.utils.http import url_has_allowed_host_and_scheme

    from core.checklists import CHECKLISTS

    wid = request.GET.get("id", "")
    nxt = request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = "/"
    response = redirect(nxt)
    if wid in CHECKLISTS:
        # Session cookie (no max_age): the walkthrough follows the member across
        # pages but ends with the browser session, so it never lingers.
        response.set_cookie("lsp_walkthrough", wid, samesite="Lax")
    else:
        response.delete_cookie("lsp_walkthrough")
    return response


def calendar_page(request):
    """Render the month-grid calendar shell.

    Public for everyone; the JSON feed filters by published status for
    non-staff users so drafts only appear to admins.
    """
    return render(request, "core/calendar.html")


def calendar_events_json(request):
    """JSON feed for FullCalendar.

    Accepts ``start`` / ``end`` query params (FullCalendar sends them
    automatically per view). Non-staff users only see Sessions for
    published events; staff see everything (including drafts).
    """
    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    qs = Session.objects.select_related("event")
    if not _is_staff(request.user):
        qs = qs.filter(event__published=True)

    start = _parse(start_param) if start_param else None
    end = _parse(end_param) if end_param else None
    if start:
        qs = qs.filter(end_at__gte=start)
    if end:
        qs = qs.filter(start_at__lte=end)

    payload = [
        {
            "id": s.id,
            "title": s.title or s.event.title,
            "start": s.start_at.isoformat(),
            "end": s.end_at.isoformat(),
            # Always link to the public event page — even for staff /
            # PC. The event page has its own edit affordances; the
            # calendar shouldn't bounce people into Django admin.
            "url": reverse("events:detail", args=[s.event.slug]),
            "extendedProps": {
                "event": s.event.title,
                "location": s.location,
                "sequence": s.sequence,
            },
        }
        for s in qs
    ]
    return JsonResponse(payload, safe=False)


def _parse(value: str) -> datetime | None:
    """Accept ISO datetime *or* a bare date (FullCalendar sends both).

    Always returns a timezone-aware datetime in the project's current TZ;
    Django warns on naive datetime queries against ``DateTimeField``.
    """
    dt = parse_datetime(value)  # Django ≥4 accepts bare dates here (returns naive).
    if dt is None:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


# --- Impersonation ("View as") — superuser-only -----------------------------

def _real_superuser(request):
    """The real acting superuser (the impersonator if already viewing-as, else
    the logged-in user), or None if not a superuser."""
    real = getattr(request, "impersonator", None) or request.user
    return real if (real.is_authenticated and real.is_superuser) else None


def impersonate_picker(request):
    """Pick a persona (or search a real member) to view the site as."""
    if _real_superuser(request) is None:
        raise Http404
    from accounts.models import Profile

    User = get_user_model()
    personas = (
        User.objects.filter(profile__is_persona=True, is_active=True)
        .select_related("profile").order_by("first_name", "last_name", "email")
    )
    q = (request.GET.get("q") or "").strip()
    matches = []
    if q:
        matches = list(
            User.objects.filter(is_active=True, is_superuser=False, profile__is_persona=False)
            .filter(
                models.Q(first_name__icontains=q) | models.Q(last_name__icontains=q)
                | models.Q(email__icontains=q)
            ).select_related("profile").order_by("last_name", "first_name")[:20]
        )
    return render(request, "core/impersonate.html", {
        "personas": personas, "matches": matches, "q": q,
        "directory_roles": Profile.DIRECTORY_ROLES,
    })


@require_POST
def impersonate_start(request, user_id: int):
    real = _real_superuser(request)
    if real is None:
        raise Http404
    target = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    if target.is_superuser or target.pk == real.pk:
        messages.error(request, "Can't view as that account.")
        return redirect("core:impersonate_picker")
    from core.models import ImpersonationLog

    read_only = not getattr(getattr(target, "profile", None), "is_persona", False)
    request.session["impersonate_user_id"] = target.pk
    ImpersonationLog.objects.create(
        impersonator=real, target=target, read_only=read_only
    )
    return redirect("/")


@require_POST
def impersonate_stop(request):
    request.session.pop("impersonate_user_id", None)
    impersonator = getattr(request, "impersonator", None)
    if impersonator is not None:
        from core.models import ImpersonationLog

        (ImpersonationLog.objects
         .filter(impersonator=impersonator, ended_at__isnull=True)
         .order_by("-started_at").update(ended_at=timezone.now()))
    return redirect("/")
