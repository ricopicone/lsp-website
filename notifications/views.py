"""The notification feed and the per-category preferences page."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .categories import (
    CATEGORY_META,
    SECTION_ORDER,
    DigestCadence,
    EmailDelivery,
    meta_for,
)
from .models import Notification, NotificationPreference
from .preferences import resolve


@login_required
def feed(request):
    """The member's notification list. Unlike the old Parlêtre page, viewing
    does *not* silently mark everything read — the member marks items read by
    clicking through or with the explicit button (POST to ``mark_all_read``)."""
    items = list(
        Notification.objects.filter(recipient=request.user)
        .select_related("actor")[:100]
    )
    unread = sum(1 for n in items if n.is_unread)
    return render(
        request,
        "notifications/feed.html",
        {"items": items, "unread": unread},
    )


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(
        recipient=request.user, read_at__isnull=True
    ).update(read_at=timezone.now())
    return redirect("notifications:feed")


@login_required
@require_POST
def open(request, pk):
    """Mark one notification read and redirect to its target."""
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if n.is_unread:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return redirect(n.url or "notifications:feed")


@login_required
def recent(request):
    """The dropdown panel's contents: the most recent notifications + count.
    Loaded lazily when the bell opens."""
    items = list(
        Notification.objects.filter(recipient=request.user)
        .select_related("actor")[:8]
    )
    unread = Notification.objects.filter(
        recipient=request.user, read_at__isnull=True
    ).count()
    return render(
        request,
        "notifications/_dropdown.html",
        {"items": items, "unread": unread},
    )


@login_required
@require_POST
def mark_read(request, pk):
    """Mark one notification read without navigating (used by the dropdown
    before the browser follows the link). Returns 204."""
    Notification.objects.filter(
        pk=pk, recipient=request.user, read_at__isnull=True
    ).update(read_at=timezone.now())
    return HttpResponse(status=204)


@login_required
def settings_page(request):
    """Per-category delivery preferences, grouped into sections."""
    pref, _ = NotificationPreference.objects.get_or_create(user=request.user)

    if request.method == "POST":
        for category in CATEGORY_META:
            meta = meta_for(category)
            in_app = (
                request.POST.get(f"{category}__in_app") == "on"
                if meta.in_app_capable
                else meta.default_in_app
            )
            if meta.email_locked or not meta.email_capable:
                email = meta.default_email
            else:
                email = request.POST.get(f"{category}__email", EmailDelivery.OFF)
                if email not in EmailDelivery.values:
                    email = EmailDelivery.OFF
            pref.set(category, in_app=in_app, email=email)
        cadence = request.POST.get("digest_cadence", "")
        if cadence in DigestCadence.values:
            pref.digest_cadence = cadence
        pref.save(update_fields=["overrides", "digest_cadence", "updated_at"])
        messages.success(request, "Notification preferences saved.")
        return redirect("notifications:settings")

    # Build the grouped view model.
    sections: dict[str, list] = {s: [] for s in SECTION_ORDER}
    for category, meta in CATEGORY_META.items():
        res = resolve(request.user, category)
        sections[meta.section].append(
            {
                "key": category,
                "label": meta.label,
                "help_text": meta.help_text,
                "in_app": res.in_app,
                "email_mode": res.email_mode,
                "in_app_editable": res.in_app_editable,
                "email_editable": res.email_editable,
                "email_locked": meta.email_locked,
            }
        )
    grouped = [
        {"title": s, "rows": sections[s]} for s in SECTION_ORDER if sections[s]
    ]
    return render(
        request,
        "notifications/settings.html",
        {
            "sections": grouped,
            "cadence": pref.digest_cadence,
            "cadence_choices": DigestCadence.choices,
            "email_choices": EmailDelivery.choices,
        },
    )
