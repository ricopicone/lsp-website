"""The notification feed and the per-category preferences page."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .categories import CATEGORY_META, SECTION_ORDER, EmailDelivery, meta_for
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
                email = (
                    EmailDelivery.IMMEDIATE
                    if request.POST.get(f"{category}__email") == "on"
                    else EmailDelivery.OFF
                )
            pref.set(category, in_app=in_app, email=email)
        pref.save(update_fields=["overrides", "updated_at"])
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
                "email": res.email,
                "in_app_editable": res.in_app_editable,
                "email_editable": res.email_editable,
                "email_locked": meta.email_locked,
            }
        )
    grouped = [
        {"title": s, "rows": sections[s]} for s in SECTION_ORDER if sections[s]
    ]
    return render(request, "notifications/settings.html", {"sections": grouped})
