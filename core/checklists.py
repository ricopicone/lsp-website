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


def _call_or_value(value, request):
    return value(request) if callable(value) else value


@dataclass(frozen=True)
class Hop:
    """One leg of a route: on ``page``, pulse ``selector`` and say ``text``.

    ``page`` / ``selector`` may be callables of the request so a route can
    name the viewer's own seminar. ``page == "*"`` matches everywhere and is
    the fallback that points back at the menu from any page off the route.
    A page string with a query must match path+query; without, path only.
    """

    page: object          # str | Callable[[request], str | None]
    selector: object      # str | Callable[[request], str | None]
    text: str
    placement: str = "below"

    def matches(self, request) -> bool:
        try:
            page = _call_or_value(self.page, request)
        except NoReverseMatch:
            return False
        if not page:
            return False
        if page == "*":
            return True
        if "?" in page:
            query = request.META.get("QUERY_STRING", "")
            here = request.path + ("?" + query if query else "")
            return here == page
        return request.path == page

    def resolved(self, request, index: int) -> dict | None:
        try:
            selector = _call_or_value(self.selector, request)
        except NoReverseMatch:
            return None
        if not selector:
            return None
        return {"selector": selector, "text": self.text,
                "placement": self.placement, "index": index}


@dataclass(frozen=True)
class ChecklistTask:
    id: str
    label: str
    detail: str
    resolve_url: Callable[[object], str | None] = _no_url
    is_done: Callable[[object, object], bool] = _never
    manual: bool = False
    # A manual step whose whole content is "open this page": the card ticks it
    # when the member lands on its URL (task #749). Off for a step whose page
    # proves nothing on its own (close-and-reopen registration lives on the
    # same page as "open Edit event").
    visit_ticks: bool = False
    # Optional contextual hint (a pulsing anchor + popover) on the task's page.
    hint_selector: str = ""
    hint_text: str = ""
    hint_placement: str = "below"
    hint_key: str = ""
    # A route: ordered hops, the last usually ``page="*"`` (the fallback). The
    # card shows the first matching hop of the first unfinished step.
    route: tuple = ()

    def __post_init__(self):
        if self.route and self.hint_selector:
            raise ValueError(f"task {self.id}: a route or a hint, not both")

    def hop_for(self, request) -> dict | None:
        """The first hop of this task's route that matches the current page."""
        if request is None:
            return None
        for index, hop in enumerate(self.route):
            if not hop.matches(request):
                continue
            resolved = hop.resolved(request, index)
            # A hop whose selector can't resolve (no offering to name) falls
            # through to the next, so the fallback still points at the menu.
            if resolved is not None:
                return resolved
        return None

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
            "visit_ticks": self.manual and self.visit_ticks,
            "hop": self.hop_for(request),
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
    return _rev("formation:formation", query="tab=account")


def _tuition_decision_url(request):
    url = _rev("formation:formation", query="tab=account")
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
        ChecklistTask(id="sem_event", label="Open a seminar page",
                      detail="Readings, schedule, fees, and the Register "
                             "button live on each event page.",
                      resolve_url=lambda r: _rev("program"), manual=True),
        ChecklistTask(id="sem_access", label="Know where access details live",
                      detail="After you register, the Zoom link or room "
                             "appears on the event page and in your "
                             "confirmation email.",
                      resolve_url=lambda r: _rev("program"), manual=True),
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
        ChecklistTask(id="td_tab", label="Open the Account tab",
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


# --- Faculty: run your own seminar or reading group (task #749) --------------
# Every step links to the OFFERING THE VIEWER RUNS, so the walkthrough that
# frames the faculty training is the same one a faculty member runs afterwards
# on their real seminar. No step sends anything: the joining-instructions step
# stops at that page's preview, and the pricing-code step mints a code that
# goes nowhere until they hand it to someone.

def _my_offering(request):
    """The seminar or reading group the viewer runs — a serving lead-role
    membership (faculty on a seminar, organizer on a reading group) on an
    offering workgroup, resolved to that group's featured event. Prefers a
    current offering (soonest start), else the most recently ended. None if
    they run nothing."""
    from django.utils import timezone

    from workgroups.models import Workgroup, WorkgroupMembership, serving_membership_q

    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return None
    workgroups = (
        Workgroup.objects
        .filter(
            serving_membership_q("memberships__"),
            kind__in=Workgroup.OFFERING_KINDS,
            memberships__user=user,
            memberships__role__in=WorkgroupMembership.LEAD_ROLES,
        )
        .distinct()
        .prefetch_related("events")
    )
    events = [e for e in (wg.primary_event() for wg in workgroups) if e is not None]
    if not events:
        return None
    today = timezone.localdate()
    current = [e for e in events if e.end_date and e.end_date >= today]
    if current:
        return min(current, key=lambda e: e.start_date)
    return max(events, key=lambda e: e.end_date or e.start_date)


def _my_groups_url(request):
    return _rev("formation:formation", query="tab=groups")


def _fac_workspace_url(request):
    event = _my_offering(request)
    if event is None or event.workgroup_id is None:
        return _my_groups_url(request)
    return _rev("workgroups:detail", event.workgroup.slug)


def _fac_roster_url(request):
    event = _my_offering(request)
    if event is None or event.workgroup_id is None:
        return _my_groups_url(request)
    return _rev("workgroups:detail", event.workgroup.slug, query="tab=roster")


def _fac_edit_url(request):
    event = _my_offering(request)
    return _rev("events:edit", event.slug) if event else _my_groups_url(request)


def _fac_joining_url(request):
    event = _my_offering(request)
    if event is None:
        return _my_groups_url(request)
    return _rev("events:joining_instructions", event.slug)


def _fac_code_done(user, request):
    """A live code the viewer minted. A revoked (expired) one doesn't count:
    the step is "have a code you could hand to someone", and revoking it is
    how the demo resets."""
    from django.db.models import Q
    from django.utils import timezone

    event = _my_offering(request)
    if event is None:
        return False
    return event.pricing_codes.filter(
        Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now()),
        issued_by=user,
    ).exists()


def _fac_workspace_path(request):
    event = _my_offering(request)
    if event is None or event.workgroup_id is None:
        return None
    return _rev("workgroups:detail", event.workgroup.slug)


def _fac_card_selector(request):
    event = _my_offering(request)
    if event is None or event.workgroup_id is None:
        return None
    return f'[data-tour=group-card][data-tour-slug="{event.workgroup.slug}"]'


def _fac_meet_url(request):
    path = _fac_workspace_path(request)
    return f"{path}?tab=meet" if path else None


def _formation_path(request):
    return _rev("formation:formation")


# Shared hops. The route reads back to front: the most specific page first,
# the avatar menu last as the fallback from any page off the route.
MENU_TEXT = "Open your menu, then <strong>My LSP</strong>, then <strong>Groups</strong>."
AVATAR_HOP = Hop(page="*", selector="[data-tour=avatar]", text=MENU_TEXT)
CARD_HOP = Hop(page=_my_groups_url, selector=_fac_card_selector,
               text="<strong>This is your seminar.</strong> Open it.")
ROSTER_TAB_HOP = Hop(page=_fac_workspace_path, selector="[data-tour=ws-tab-roster]",
                     text="Your roster, approvals, and codes live on the "
                          "<strong>Roster</strong> tab.")
EDIT_BUTTON_HOP = Hop(page=_fac_workspace_path, selector="[data-tour=edit-event]",
                      text="<strong>Edit event</strong> opens the page's content.")


def _fac_tab_url(key: str):
    def resolve(request):
        path = _fac_workspace_path(request)
        return f"{path}?tab={key}" if path else _my_groups_url(request)
    return resolve


def _tab_hop(key: str, text: str) -> Hop:
    return Hop(page=_fac_workspace_path, selector=f"[data-tour=ws-tab-{key}]", text=text)


def _faculty_walkthrough() -> Checklist:
    return Checklist("faculty", "Run your seminar", [
        ChecklistTask(id="fac_workspace", label="Open your seminar's Workspace",
                      detail="Your avatar menu (top right), then My LSP, then "
                             "Groups, then your seminar. It opens on Overview; "
                             "look along the tab menu.",
                      resolve_url=_fac_workspace_url, manual=True, visit_ticks=True,
                      route=(CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_discuss", label="Open the Discuss tab",
                      detail="The seminar's own discussion board, for questions and "
                             "readings between sessions. Only your group sees it.",
                      resolve_url=_fac_tab_url("discuss"), manual=True, visit_ticks=True,
                      route=(_tab_hop("discuss", "<strong>Discuss</strong> is the group's "
                                      "message board."), CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_chat", label="Open the Chat tab",
                      detail="A live chat for the group, in the browser.",
                      resolve_url=_fac_tab_url("chat"), manual=True, visit_ticks=True,
                      route=(_tab_hop("chat", "<strong>Chat</strong> is the group's live "
                                      "chat."), CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_meet", label="Open the Meet tab",
                      detail="The seminar's video room: open it any time, see who is in "
                             "it, and find recordings.",
                      resolve_url=_fac_tab_url("meet"), manual=True, visit_ticks=True,
                      route=(_tab_hop("meet", "<strong>Meet</strong> is the seminar's "
                                      "video room."), CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_files", label="Open the Files tab",
                      detail="Shared files for the group, kept in versions. Members only.",
                      resolve_url=_fac_tab_url("files"), manual=True, visit_ticks=True,
                      route=(_tab_hop("files", "<strong>Files</strong> holds what the "
                                      "group shares."), CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_roster", label="Open the Roster tab",
                      detail="On your Workspace, the Roster tab: who has "
                             "registered, pending approvals, and your codes.",
                      resolve_url=_fac_roster_url, manual=True, visit_ticks=True,
                      route=(ROSTER_TAB_HOP, CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_settings", label="Open the Settings tab",
                      detail="Meeting reminders, video recording, the annual term, and "
                             "who holds which role.",
                      resolve_url=_fac_tab_url("settings"), manual=True, visit_ticks=True,
                      route=(_tab_hop("settings", "<strong>Settings</strong>: reminders, "
                                      "recording, and roles."), CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_edit", label="Open Edit event",
                      detail="Roster tab, then the Edit event button: description, "
                             "readings, CE credits, who can register, where it meets.",
                      resolve_url=_fac_edit_url, manual=True, visit_ticks=True,
                      route=(EDIT_BUTTON_HOP, CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_status", label="Close and reopen registration",
                      detail="Edit event, then the Registration panel at the "
                             "bottom. The same button sits at the top of the Roster tab.",
                      resolve_url=_fac_edit_url, manual=True,
                      route=(
                          Hop(page=_fac_edit_url, selector="[data-tour=registration-status]",
                              text="Close registration here. The button then reads "
                                   "<strong>Open registration</strong>, so you can reopen."),
                          Hop(page=_fac_workspace_path, selector="[data-tour=edit-event]",
                              text="<strong>Edit event</strong>, then the Registration "
                                   "panel at the bottom."),
                          CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_code", label="Mint a pricing code",
                      detail="Roster tab, then Generate a pricing code. Pin it to "
                             "one person, or leave it open with one use. Revoke "
                             "it under Existing codes.",
                      resolve_url=_fac_roster_url, is_done=_fac_code_done,
                      route=(
                          Hop(page=_fac_roster_url, selector="[data-tour=generate-code]",
                              text="Mint a code here. It appears under "
                                   "<strong>Existing codes</strong>."),
                          ROSTER_TAB_HOP, CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_joining", label="Preview the joining instructions",
                      detail="Roster tab, then Email joining instructions at the "
                             "top. You see the whole email before anything goes.",
                      resolve_url=_fac_joining_url, manual=True, visit_ticks=True,
                      route=(
                          Hop(page=_fac_roster_url, selector="[data-tour=joining-instructions]",
                              text="<strong>Email joining instructions</strong> shows the "
                                   "whole email before anything goes."),
                          ROSTER_TAB_HOP, CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_video", label="Test your video & audio",
                      detail="Your Workspace, Meet tab, then Test your video & "
                             "audio: a throwaway room for camera and microphone.",
                      resolve_url=lambda r: _rev("video:system_check"),
                      manual=True, visit_ticks=True,
                      route=(
                          Hop(page=_fac_meet_url, selector="[data-tour=meet-system-check]",
                              text="<strong>Test your setup</strong> opens a throwaway room "
                                   "for camera and microphone."),
                          Hop(page=_fac_workspace_path, selector="[data-tour=ws-tab-meet]",
                              text="The <strong>Meet</strong> tab has the test link."),
                          CARD_HOP, AVATAR_HOP)),
        ChecklistTask(id="fac_room", label="Find your private meeting room",
                      detail="Avatar menu, then My LSP, then Meeting room. For "
                             "office hours and one-to-one conversations.",
                      resolve_url=lambda r: _rev("video:my_room"),
                      manual=True, visit_ticks=True,
                      route=(
                          Hop(page=_formation_path, selector="[data-tour=my-lsp-room]",
                              text="Your private room is the <strong>Meeting room</strong> tab."),
                          Hop(page="*", selector="[data-tour=avatar]",
                              text="Open your menu, then <strong>My LSP</strong>, then "
                                   "<strong>Meeting room</strong>."))),
    ])


# --- Proposals: propose a seminar, reading group, or special event ----------
# Any LSP member may propose. The form saves incomplete work; Submit needs
# the dates (or a TBD date for a special event) and sends it to the Program
# Committee's queue. The two auto steps read the viewer's own proposals.

def _proposals_tab_url(request):
    return _rev("formation:formation", query="tab=proposals")


def _propose_url(request):
    return _rev("propose_event")


def _my_proposals(user):
    from events.models import EventProposal

    return EventProposal.objects.filter(proposed_by=user)


def _prop_saved_done(user, request):
    return _my_proposals(user).exists()


def _prop_submitted_done(user, request):
    from events.models import EventProposal

    return _my_proposals(user).exclude(status=EventProposal.Status.SAVED).exists()


PROPOSALS_MENU_TEXT = ("Open your menu, then <strong>My LSP</strong>, then "
                       "<strong>Proposals</strong>.")
PROP_AVATAR_HOP = Hop(page="*", selector="[data-tour=avatar]", text=PROPOSALS_MENU_TEXT)
PROP_TAB_HOP = Hop(page=_formation_path, selector="[data-tour=my-lsp-proposals]",
                   text="Your proposals live on the <strong>Proposals</strong> tab.")
PROP_NEW_HOP = Hop(page=_proposals_tab_url, selector="[data-tour=new-proposal]",
                   text="<strong>New proposal</strong> opens the form.")


def _form_hop(anchor: str, text: str) -> Hop:
    return Hop(page=_propose_url, selector=f"[data-tour={anchor}]", text=text)


def _proposals_walkthrough() -> Checklist:
    return Checklist("proposals", "Propose an event", [
        ChecklistTask(id="prop_tab", label="Open your Proposals tab",
                      detail="Avatar menu, then My LSP, then Proposals: everything you "
                             "have saved or submitted, with its status.",
                      resolve_url=_proposals_tab_url, manual=True, visit_ticks=True,
                      route=(PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_new", label="Start a new proposal",
                      detail="The New proposal button. The form adapts to the type "
                             "you pick.",
                      resolve_url=_propose_url, manual=True, visit_ticks=True,
                      route=(PROP_NEW_HOP, PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_describe", label="Pick the type and describe it",
                      detail="Seminar, reading group, or special event; a title; about "
                             "250 words on the focus, the rationale, and the format.",
                      resolve_url=_propose_url, manual=True,
                      route=(_form_hop("proposal-type", "Start with the "
                                       "<strong>type</strong>; the form adapts to it."),
                             PROP_NEW_HOP, PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_when_where", label="Say when and where",
                      detail="Start and end dates and a meeting schedule (or TBD), and "
                             "whether it meets in the site's room, on Zoom, or in person.",
                      resolve_url=_propose_url, manual=True,
                      route=(_form_hop("proposal-dates", "The <strong>dates</strong> are "
                                       "what a submission needs; the schedule can wait."),
                             PROP_NEW_HOP, PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_fee", label="Set the fee, CE, and readings",
                      detail="Free, a fixed amount, or a sliding scale; whether tuition "
                             "covers it; CE credits; and one citation per line.",
                      resolve_url=_propose_url, manual=True,
                      route=(_form_hop("proposal-fee", "The <strong>fee</strong> you propose "
                                       "becomes the listed price if approved."),
                             PROP_NEW_HOP, PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_save", label="Save it for later",
                      detail="A saved proposal can be incomplete. Nobody sees it but you.",
                      resolve_url=_propose_url, is_done=_prop_saved_done,
                      route=(_form_hop("proposal-save", "<strong>Save for later</strong> "
                                       "keeps a draft only you can see."),
                             PROP_NEW_HOP, PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_submit", label="Submit it for review",
                      detail="Sends it to the Program Committee. You can still edit "
                             "until they decide.",
                      resolve_url=_proposals_tab_url, is_done=_prop_submitted_done,
                      route=(_form_hop("proposal-submit", "<strong>Submit for review</strong> "
                                       "sends it to the Program Committee."),
                             PROP_TAB_HOP, PROP_AVATAR_HOP)),
        ChecklistTask(id="prop_track", label="Track it on your Proposals tab",
                      detail="Under review, approved with a link to the event, or "
                             "declined with a note so you can revise and resubmit.",
                      resolve_url=_proposals_tab_url, manual=True, visit_ticks=True,
                      route=(PROP_TAB_HOP, PROP_AVATAR_HOP)),
    ])


# Registry: walkthrough id -> factory (so URLs/checks resolve at request time).
CHECKLISTS: dict[str, Callable[[], Checklist]] = {
    "profile": _profile_walkthrough,
    "seminars": _seminars_walkthrough,
    "parletre": _parletre_walkthrough,
    "cartels": _cartels_walkthrough,
    "my_formation": _formation_walkthrough,
    "tuition_dues": _tuition_dues_walkthrough,
    "faculty": _faculty_walkthrough,
    "proposals": _proposals_walkthrough,
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
