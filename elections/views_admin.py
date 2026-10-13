"""The Election Administrator console, /admin-tools/elections/ (task #813).

Follows the registrar console's tab pattern. Gate: the Election
Administrator role or a superuser; anonymous visitors go to login and
anyone else gets a 404. Every state change goes through ``services``.
"""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import ballots, eligibility, services
from .forms import ElectionSettingsForm, OverrideForm
from .models import Election, Nomination, VoterRollEntry
from .permissions import is_election_administrator

P = Election.Phase


def administrator_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_election_administrator(request.user):
            raise Http404
        return view(request, *args, **kwargs)
    return wrapper


TABS = [
    ("overview", "Overview"),
    ("settings", "Settings"),
    ("nominations", "Nominations"),
    ("roll", "Voter roll"),
    ("count", "Count"),
]

#: What the administrator should do next, by phase.
NEXT_STEP = {
    P.DRAFT: "Nothing yet. The call for nominations goes to every voter when "
             "nominations open.",
    P.NOMINATING: "Members are nominating themselves. Nominations close on the "
                  "date in Settings, or press Close now.",
    P.REVIEW: "The Board is reviewing the nominations. Once every nomination is "
              "decided, publish the slate.",
    P.SLATE: "The slate is published. Voting opens on the date in Settings, or "
             "press Open now.",
    P.VOTING: "Voting is open. Check the voter roll, and send a reminder to those "
              "who haven't voted if needed.",
    P.CLOSED: "Voting has closed. Run the count.",
    P.COUNTED: "Check the count, then publish the results.",
    P.PUBLISHED: "The results are published.",
    P.ACCLAIMED: "The election closed without a vote.",
}


def _tab_links(election):
    links = [(key, label, reverse(f"elections:admin_{key}", args=[election.slug]))
             for key, label in TABS]
    return links + [("help", "Help", reverse("elections:admin_help"))]


def _render(request, election, tab_key, template, ctx=None):
    return render(request, template, {
        **(ctx or {}),
        "election": election,
        "phase": election.phase if election else None,
        "tab_key": tab_key,
        "tabs": _tab_links(election) if election else [],
    })


def _election(slug):
    return get_object_or_404(Election, slug=slug)


def _unique_slug(title):
    base = slugify(title)[:50] or "election"
    slug, n = base, 2
    while Election.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


@administrator_required
def admin_index(request):
    current = services.current_election()
    if current is not None and current.phase not in Election.FINAL_PHASES:
        return redirect("elections:admin_overview", current.slug)
    return render(request, "elections/admin/list.html", {
        "elections": Election.objects.all(),
    })


@administrator_required
def admin_new(request):
    form = ElectionSettingsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        election = form.save(commit=False)
        election.slug = _unique_slug(election.title)
        election.append_audit(request.user, "Created the election.")
        election.save()
        messages.success(request, "Election created.")
        return redirect("elections:admin_overview", election.slug)
    return render(request, "elections/admin/new.html", {"form": form})


@administrator_required
def admin_overview(request, slug):
    e = _election(slug)
    live = e.nominations.filter(withdrawn_at__isnull=True)
    candidates = ballots.candidates(e)
    return _render(request, e, "overview", "elections/admin/overview.html", {
        "next_step": NEXT_STEP[e.phase],
        "nomination_count": live.count(),
        "accepted_count": len(candidates),
        "roll_size": len(services.roll_ids(e)),
        "turnout": ballots.turnout(e),
        "no_contest": e.phase == P.SLATE and len(candidates) <= e.seats,
        "past": Election.objects.exclude(pk=e.pk),
    })


@administrator_required
def admin_settings(request, slug):
    e = _election(slug)
    form = ElectionSettingsForm(request.POST or None, instance=e)
    if request.method == "POST" and form.is_valid():
        changes = form.changed_summary()
        election = form.save(commit=False)
        if changes:
            election.append_audit(request.user, "Changed settings: " + "; ".join(changes))
        election.save()
        messages.success(request, "Settings saved." if changes else "Nothing changed.")
        return redirect("elections:admin_settings", e.slug)
    return _render(request, e, "settings", "elections/admin/settings.html", {"form": form})


@administrator_required
def admin_nominations(request, slug):
    e = _election(slug)
    return _render(request, e, "nominations", "elections/admin/nominations.html", {
        "nominations": e.nominations.select_related("user", "reviewed_by"),
        "pending": e.nominations.filter(
            withdrawn_at__isnull=True, status=Nomination.Status.PENDING).count(),
    })


@administrator_required
def admin_roll(request, slug):
    from payments.ledger import accounts_overview

    e = _election(slug)
    if e.phase in (P.VOTING, P.CLOSED):
        services.ensure_roll_frozen(e)
    users = list(eligibility.roll_users(e))
    overrides = {r.user_id: r for r in VoterRollEntry.objects.filter(election=e)
                 .exclude(override="").select_related("user")}
    dues = {row["user"].id: row["dues_state"] for row in accounts_overview()}
    show_voted = e.phase in (P.VOTING, P.CLOSED, P.COUNTED, P.PUBLISHED)
    voted = ballots.voted_user_ids(e) if show_voted else set()
    rows = [{
        "user": u,
        "dues": dues.get(u.id),
        "override": overrides.get(u.id),
        "voted": u.id in voted,
    } for u in users]
    on_roll = {u.id for u in users}
    removed = [r for uid, r in overrides.items()
               if r.override == VoterRollEntry.Override.REMOVE and uid not in on_roll]
    return _render(request, e, "roll", "elections/admin/roll.html", {
        "rows": rows,
        "removed": removed,
        "show_voted": show_voted,
        "voted_count": len(voted),
        "frozen": bool(e.roll_frozen_at),
        "roll_open": e.phase not in (P.CLOSED, P.COUNTED, P.PUBLISHED, P.ACCLAIMED),
        "form": OverrideForm(),
    })


@administrator_required
def admin_count(request, slug):
    e = _election(slug)
    result = e.count_result or {}
    names = result.get("names", {})
    stages = []
    for s in result.get("stages", []):
        stages.append({
            **s,
            "subject_name": names.get(str(s["subject"]), "") if s.get("subject") else "",
            "rows": [(names.get(cid, cid), v) for cid, v in s["totals"].items()],
        })
    return _render(request, e, "count", "elections/admin/count.html", {
        "result": result,
        "elected": [names.get(str(i), i) for i in result.get("elected", [])],
        "stages": stages,
        "lots": [{**lot, "tied_names": [names.get(str(c), c) for c in lot["tied"]]}
                 for lot in result.get("lots", [])],
    })


@administrator_required
def admin_help(request):
    from core.docs import render_doc

    e = services.current_election()
    return _render(request, e, "help", "elections/admin/help.html", {
        "doc_html": render_doc("election-guide"),
    })


_ACTIONS = {
    "open_nominations_now": (lambda e, u: services.open_now(e, "nominations", u),
                             "Nominations are open."),
    "close_nominations_now": (lambda e, u: services.close_now(e, "nominations", u),
                              "Nominations are closed."),
    "open_voting_now": (lambda e, u: services.open_now(e, "voting", u),
                        "Voting opens now, or as soon as the slate is published."),
    "close_voting_now": (lambda e, u: services.close_now(e, "voting", u),
                         "Voting is closed."),
    "publish_slate": (services.publish_slate,
                      "The slate is published and the candidates have been told."),
    "acclaim": (services.acclaim, "The election is closed without a vote."),
    "run_count": (services.run_count, "The votes are counted."),
    "publish_results": (services.publish_results, "The results are published."),
    "remind": (services.remind_nonvoters, "Reminder sent to those who haven't voted."),
}


def _back(request, election):
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()},
                                               require_https=request.is_secure()):
        return redirect(nxt)
    return redirect("elections:admin_overview", election.slug)


@require_POST
@administrator_required
def admin_action(request, slug):
    e = _election(slug)
    action = _ACTIONS.get(request.POST.get("action", ""))
    if action is None:
        messages.error(request, "Unknown action.")
        return _back(request, e)
    fn, done = action
    try:
        fn(e, request.user)
    except services.ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, done)
    return _back(request, e)


@require_POST
@administrator_required
def admin_override(request, slug):
    e = _election(slug)
    form = OverrideForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for err in errors:
                messages.error(request, err)
        return redirect("elections:admin_roll", e.slug)
    try:
        services.set_override(e, form.user, form.cleaned_data["override"],
                              form.cleaned_data["reason"], request.user)
    except services.ElectionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "The voter roll is updated.")
    return redirect("elections:admin_roll", e.slug)
