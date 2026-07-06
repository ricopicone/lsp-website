"""Data-driven onboarding walkthroughs.

A :class:`Checklist` is a named, ordered list of :class:`ChecklistTask`. Each
task is either **auto** (``is_done`` checks real data, so it ticks itself) or
**manual** (the member checks it off; the tick is remembered client-side). The
floating card in ``base.html`` appears only when a walkthrough is *active* for
the viewer — one they started from a guide page (tracked by the
``lsp_walkthrough`` session cookie). There is no always-on default; closing the
card or ending the session removes it, and it's re-summoned from the guide.

Adding a walkthrough is a single entry in ``CHECKLISTS`` here plus a
``checklist:`` line in the matching guide's frontmatter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings
from django.urls import NoReverseMatch, reverse


def _rev(name: str, *args, query: str = "") -> str | None:
    try:
        url = reverse(name, args=args)
    except NoReverseMatch:
        return None
    return f"{url}?{query}" if query else url


def _never(user, request) -> bool:  # manual tasks: completion is client-side
    return False


def _no_url(request) -> str | None:  # default for tasks with no link
    return None


@dataclass(frozen=True)
class ChecklistTask:
    id: str
    label: str
    detail: str
    resolve_url: Callable[[object], str | None] = _no_url
    is_done: Callable[[object, object], bool] = _never
    manual: bool = False
    # Optional contextual hint (a pulsing anchor + popover) on the task's page.
    hint_selector: str = ""
    hint_text: str = ""
    hint_placement: str = "below"
    hint_key: str = ""

    def key(self) -> str:
        return self.hint_key or f"lsp-tour-{self.id}-hint"

    def resolved(self, user, request) -> dict:
        try:
            url = self.resolve_url(request)
        except NoReverseMatch:
            url = None
        # Manual tasks are never "done" server-side; the card applies the
        # remembered client-side state after render.
        done = False if self.manual else bool(self.is_done(user, request))
        return {
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "url": url,
            "done": done,
            "manual": self.manual,
            "hint_selector": self.hint_selector,
            "hint_text": self.hint_text,
            "hint_placement": self.hint_placement,
            "hint_key": self.key(),
            "show_hint": (not self.manual) and (not done) and bool(self.hint_selector),
        }


@dataclass(frozen=True)
class Checklist:
    id: str
    title: str
    tasks: list[ChecklistTask] = field(default_factory=list)


# --- Completion checks + link resolvers ------------------------------------

def _profile(user):
    return getattr(user, "profile", None)


def _photo_done(user, request):
    p = _profile(user)
    return bool(p and p.headshot)


def _bio_done(user, request):
    p = _profile(user)
    return bool(p and (p.bio or "").strip())


def _profile_done(user, request):
    return _photo_done(user, request) and _bio_done(user, request)


def _preview_event():
    from events.models import Event

    slug = getattr(settings, "PREVIEW_TOUR_SEMINAR_SLUG", "")
    return Event.objects.filter(slug=slug).first() if slug else None


def _seminar_url(request):
    event = _preview_event()
    return _rev("events:detail", event.slug) if event else None


def _register_done(user, request):
    from registrations.models import Registration

    event = _preview_event()
    if event is None:
        return False
    return (
        Registration.objects.filter(user=user, event=event)
        .exclude(status__in=(Registration.Status.CANCELLED, Registration.Status.REFUNDED))
        .exists()
    )


def _preview_channel():
    from parletre.models import Channel

    slug = getattr(settings, "PREVIEW_TOUR_CHANNEL_SLUG", "")
    return Channel.objects.filter(slug=slug).first() if slug else None


def _channel_url(request):
    channel = _preview_channel()
    return _rev("parletre:channel", channel.slug) if channel else None


def _channel_done(user, request):
    from parletre.models import Post

    channel = _preview_channel()
    if channel is None:
        return False
    return Post.objects.filter(author=user, channel=channel).exists()


def _profile_anchor(anchor: str) -> str | None:
    # Same-page anchor: clicking from the profile page scrolls to the section
    # (no reload, so unsaved input survives); from elsewhere it navigates there.
    url = _rev("profile_edit")
    return f"{url}#{anchor}" if url else None


def _pe_photo_url(request):
    return _profile_anchor("photo")


def _pe_about_url(request):
    return _profile_anchor("about")


def _pe_public_url(request):
    return _profile_anchor("public-profile")


def _formation_url(request):
    return _rev("formation:formation")


def _formation_advisor_url(request):
    url = _rev("formation:formation")
    return f"{url}#advisor" if url else None


def _formation_steps_url(request):
    url = _rev("formation:formation")
    return f"{url}#steps" if url else None


def _tuition_tab_url(request):
    return _rev("formation:formation", query="tab=tuition")


def _tuition_decision_url(request):
    url = _rev("formation:formation", query="tab=tuition")
    return f"{url}#decision" if url else None


def _ac_dashboard_url(request):
    return _rev("admissions:coordinator_dashboard")


def _ac_messages_url(request):
    return _rev("admissions:coordinator_messages")


def _ac_settings_url(request):
    return _rev("admissions:coordinator_settings")


def _analyst_dashboard_url(request):
    return _rev("admissions:analyst_dashboard")


# --- The walkthroughs ------------------------------------------------------
# One per guide. There's no always-on default: the floating card appears only
# once a member starts a walkthrough from a guide (see core.views.set_walkthrough)
# and disappears when they close it or the browser session ends.

def _profile_walkthrough() -> Checklist:
    return Checklist("profile", "Set up your profile", [
        ChecklistTask(id="pf_photo", label="Add a photo",
                      detail="Crop it to the circle; it appears across the site.",
                      resolve_url=_pe_photo_url, is_done=_photo_done,
                      hint_selector="#choose-photo",
                      hint_text=("<strong>Start here.</strong> Add your photo — "
                                 "you'll crop it to a circle."),
                      hint_key="lsp-wt-hint-pf-photo"),
        ChecklistTask(id="pf_bio", label="Write a short bio",
                      detail="A few sentences in the first person.",
                      resolve_url=_pe_about_url, is_done=_bio_done),
        ChecklistTask(id="pf_visibility", label="Choose who sees each field",
                      detail="Public, members only, or private.",
                      resolve_url=_pe_about_url, manual=True),
        ChecklistTask(id="pf_listed", label="Confirm your directory listing",
                      detail="Stay listed so colleagues can find you.",
                      resolve_url=_pe_public_url, manual=True),
    ])


def _seminars_walkthrough() -> Checklist:
    return Checklist("seminars", "Register for a seminar", [
        ChecklistTask(id="sem_browse", label="Browse the program & events",
                      detail="See what's on this year.",
                      resolve_url=lambda r: _rev("program"), manual=True),
        ChecklistTask(id="sem_register", label="Register for the preview seminar",
                      detail="Free and instant — feel the whole flow.",
                      resolve_url=_seminar_url, is_done=_register_done,
                      hint_selector="#register-cta",
                      hint_text=("<strong>Try it.</strong> This sandbox seminar is free — "
                                 "register to see the whole flow."),
                      hint_key="lsp-wt-hint-sem-register"),
        ChecklistTask(id="sem_access", label="View your registration & access",
                      detail="Your access details appear once you're registered.",
                      resolve_url=_seminar_url, manual=True),
    ])


def _parletre_walkthrough() -> Checklist:
    return Checklist("parletre", "Join the conversation", [
        ChecklistTask(id="par_open", label="Open Parlêtre",
                      detail="The members' commons.",
                      resolve_url=lambda r: _rev("parletre:index"), manual=True),
        ChecklistTask(id="par_post", label="Post a hello",
                      detail="Say hi in the welcome channel.",
                      resolve_url=_channel_url, is_done=_channel_done,
                      hint_selector=".parletre-composer", hint_placement="above",
                      hint_text=("<strong>Say hi 👋</strong> Type a quick hello here "
                                 "and press Enter."),
                      hint_key="lsp-wt-hint-par-post"),
        ChecklistTask(id="par_subscribe", label="Subscribe to a channel",
                      detail="Get updates and email digests.",
                      resolve_url=lambda r: _rev("parletre:index"), manual=True),
    ])


def _cartels_walkthrough() -> Checklist:
    return Checklist("cartels", "Explore cartels", [
        ChecklistTask(id="car_browse", label="Browse the cartels",
                      detail="See which have formed and what they're working.",
                      resolve_url=lambda r: _rev("workgroups:kind_cartels"), manual=True),
        ChecklistTask(id="car_plusone", label="Understand the plus-one",
                      detail="The function distinct from the working members.",
                      manual=True),
        ChecklistTask(id="car_propose", label="Propose or join a cartel",
                      detail="Start one around a guiding question, any time.",
                      resolve_url=lambda r: _rev("cartels:propose"), manual=True),
    ])


def _formation_walkthrough() -> Checklist:
    return Checklist("my_formation", "Find your way", [
        ChecklistTask(id="form_open", label="Open My Formation",
                      detail="Your personal hub.", resolve_url=_formation_url, manual=True),
        ChecklistTask(id="form_advisor", label="Choose your advisor",
                      detail="They present your demandes to the Meeting of the Analysts.",
                      resolve_url=_formation_advisor_url, manual=True),
        ChecklistTask(id="form_steps", label="Review your formation steps",
                      detail="Your path so far, and the next step.",
                      resolve_url=_formation_steps_url, manual=True),
    ])


def _tuition_dues_walkthrough() -> Checklist:
    return Checklist("tuition_dues", "Sort tuition & dues", [
        ChecklistTask(id="td_tab", label="Open the Tuition & Dues tab",
                      detail="Everything in one place.", resolve_url=_tuition_tab_url, manual=True),
        ChecklistTask(id="td_decision", label="Record your tuition decision",
                      detail="Committed, payment plan, paid in full, or skipping.",
                      resolve_url=_tuition_decision_url, manual=True),
        ChecklistTask(id="td_dues", label="Pay your dues",
                      detail="If your role and standing owe them this year.",
                      resolve_url=lambda r: _rev("dues"), manual=True),
    ])


def _applications_coordinator_walkthrough() -> Checklist:
    return Checklist("applications_coordinator", "Run the admissions workflow", [
        ChecklistTask(id="ac_open", label="Open the Applications console",
                      detail="Your admissions home — every application and its progress.",
                      resolve_url=_ac_dashboard_url, manual=True),
        ChecklistTask(id="ac_ack", label="Acknowledge a new applicant",
                      detail="Send the acknowledgment from the Ack. column "
                             "(or make it automatic in Settings).",
                      resolve_url=_ac_dashboard_url, manual=True),
        ChecklistTask(id="ac_invite", label="Invite interviewers",
                      detail="Click the applicant's name to open them, then press "
                             "'Invite interviewers' to email available analysts. "
                             "On a sandbox applicant (marked 🧪) every email is "
                             "redirected to you.",
                      resolve_url=_ac_dashboard_url, manual=True),
        ChecklistTask(id="ac_connect", label="Watch the introductions",
                      detail="When an analyst agrees, the applicant and "
                             "interviewer are connected by email to set a time. "
                             "In the sandbox, use “Simulate analyst "
                             "responses” on the application to fast-forward "
                             "this — no impersonation needed.",
                      resolve_url=_ac_dashboard_url, manual=True),
        ChecklistTask(id="ac_decide", label="Record the decision",
                      detail="Open the applicant from your console and record the "
                             "Meeting's accept/reject decision.",
                      resolve_url=_ac_dashboard_url, manual=True),
        ChecklistTask(id="ac_messages", label="Tailor the messages",
                      detail="Edit the wording of any outgoing email — tokens like "
                             "{name} are filled in automatically.",
                      resolve_url=_ac_messages_url, manual=True),
        ChecklistTask(id="ac_settings", label="Choose auto vs review",
                      detail="Set whether acknowledgment and invitations send on "
                             "their own or wait for you.",
                      resolve_url=_ac_settings_url, manual=True),
    ])


def _analyst_interviews_walkthrough() -> Checklist:
    return Checklist("analyst_interviews", "Conduct an interview", [
        ChecklistTask(id="ai_open", label="Open your interviews",
                      detail="Requests you can take, and interviews you've agreed to.",
                      resolve_url=_analyst_dashboard_url, manual=True),
        ChecklistTask(id="ai_agree", label="Agree to a request",
                      detail="Open a request; if a slot is open and you can "
                             "interview, agree — you'll be connected with the "
                             "applicant by email.",
                      resolve_url=_analyst_dashboard_url, manual=True),
        ChecklistTask(id="ai_report", label="Submit your report",
                      detail="After the interview, record your report (the date "
                             "defaults to today).",
                      resolve_url=_analyst_dashboard_url, manual=True),
    ])


# Registry: walkthrough id -> factory (so URLs/checks resolve at request time).
CHECKLISTS: dict[str, Callable[[], Checklist]] = {
    "profile": _profile_walkthrough,
    "seminars": _seminars_walkthrough,
    "parletre": _parletre_walkthrough,
    "cartels": _cartels_walkthrough,
    "my_formation": _formation_walkthrough,
    "tuition_dues": _tuition_dues_walkthrough,
    "applications_coordinator": _applications_coordinator_walkthrough,
    "analyst_interviews": _analyst_interviews_walkthrough,
}


def get_checklist(checklist_id: str) -> Checklist | None:
    factory = CHECKLISTS.get(checklist_id)
    return factory() if factory else None


def active_checklist(request) -> Checklist | None:
    """The walkthrough the viewer has started (from the ``lsp_walkthrough``
    cookie), or None — there is no always-on default, so None means no card."""
    return get_checklist(request.COOKIES.get("lsp_walkthrough", ""))


def first_step_url(checklist_id: str, request=None) -> str | None:
    """The URL of the first task that has one — used as the 'start' landing."""
    checklist = get_checklist(checklist_id)
    if checklist is None:
        return None
    for task in checklist.tasks:
        try:
            url = task.resolve_url(request)
        except NoReverseMatch:
            url = None
        if url:
            return url
    return None
