"""Access control for Parlêtre (the members-only discussion board).

Two layers:

* :func:`can_enter_parletre` — the board-entry gate (MEM-1). Decides whether
  a user may open Parlêtre at all: full members (:func:`is_member`) plus
  *auditors* (outside registrants with a paid/comped seminar/reading-group
  registration, confined by the per-channel checks to that offering's own
  workgroup channel).
* :func:`is_member` — full LSP membership. A "member" is anyone holding one
  of the LSP member roles, anyone on an active committee (Board / Programming
  Committee / LSP Staff), or any Django staff user. OPEN ("every member") and
  ROLE channels gate on this, so auditors never reach them.
* Per-channel access — :func:`channel_visible`, :func:`channel_can_post`,
  and :func:`channel_can_moderate` — layered on top, keyed off the
  channel's ``access`` and ``post_policy`` fields. ``Channel`` exposes
  thin method wrappers (``visible_to`` / ``can_post`` / ``can_moderate``)
  that delegate here.

``is_staff`` is god-mode for *open*, *role*, and *committee* channels —
matching the rest of the site, where staff need reach for moderation and
support. **Private and workgroup channels are the exception:** they are
genuinely private, visible and moderable only to their members / moderators,
with no staff bypass. A workgroup's forum and chat belong to that group
(cartel, seminar, committee, working group, reading group) and no outsider —
staff included — may read or moderate them; only its members, leads (chair /
co-chair / plus-one / faculty), and named moderators can. This is
application-level privacy, not cryptographic — a database administrator can
still read the rows — but the product never surfaces such a channel to someone
who isn't in it.

Every channel, of every access mode, still sits behind
:func:`can_enter_parletre`: Parlêtre as a whole is gated and never public.
"""

from __future__ import annotations

from django.conf import settings

from accounts.permissions import is_lsp_member as _is_lsp_member
from workgroups.models import Workgroup, WorkgroupMembership


def _is_schoolwide_social(channel) -> bool:
    """The school-wide social channels retired in task #360: any disappearing
    channel (Purloined Letters), or any OPEN channel other than Announcements.
    Excludes LSP Staff (access=lsp_staff), workgroup channels, and Announcements."""
    if channel.message_ttl_seconds:
        return True
    return channel.access == channel.Access.OPEN and channel.slug != "announcements"


def _authenticated(user) -> bool:
    return bool(getattr(user, "is_authenticated", False))


def is_member(user) -> bool:
    """Whether ``user`` counts as a full LSP member (the MEM-1 gate).

    Consolidated onto :func:`accounts.permissions.is_lsp_member` (Stage-4
    fold-in): Django staff, a directory/member role, the LSP Staff
    designation, or active membership in a committee-kind workgroup
    (Board / PC) all qualify. This is *membership*, not mere board entry —
    OPEN ("every member") and ROLE channels gate on it. For "may this user
    open Parlêtre at all" use :func:`can_enter_parletre`, which also admits
    auditors.
    """
    return _is_lsp_member(user)


def _is_offering_registrant(user) -> bool:
    """Whether ``user`` holds a paid/comped registration on a seminar or
    reading group — an *auditor* who belongs to at least one offering's
    workspace even though they are not an LSP member."""
    if not _authenticated(user):
        return False
    from registrations.models import Registration

    return Registration.objects.filter(
        user=user,
        status__in=(Registration.Status.PAID, Registration.Status.COMPED),
        event__workgroup__kind__in=Workgroup.OFFERING_KINDS,
    ).exists()


def can_enter_parletre(user) -> bool:
    """Whether ``user`` may open Parlêtre at all (the board-entry gate).

    Full members (:func:`is_member`) reach the whole board. *Auditors* —
    outside registrants (``role=external``) with a paid/comped registration on
    a seminar or reading group — may enter too, but :func:`channel_visible`
    confines them to that offering's own workgroup channel: OPEN and ROLE
    channels re-check real membership, so an auditor sees only the seminar(s)
    they're enrolled in and nothing the wider membership can see.
    """
    return is_member(user) or _is_offering_registrant(user)


def _workgroup_lead(workgroup, user) -> bool:
    """Whether ``user`` holds a leading role (chair / co-chair / plus-one) in
    ``workgroup`` — the roles that moderate its channel."""
    return WorkgroupMembership.objects.serving().filter(
        workgroup=workgroup,
        user=user,
        role__in=WorkgroupMembership.LEAD_ROLES,
    ).exists()


def _can_moderate_workgroup_channel(channel, user) -> bool:
    if channel.moderators.filter(pk=user.pk).exists():
        return True
    wg = channel.workgroup
    if wg is None:
        return False
    # No staff bypass: a workgroup channel is moderated only from within the
    # group (its leads + named moderators).
    return _workgroup_lead(wg, user)


def channel_can_moderate(channel, user) -> bool:
    """Whether ``user`` may moderate ``channel`` (pin/lock/move/delete)."""
    if not _authenticated(user):
        return False
    # Private channels: only their named moderators — no staff god-mode, so a
    # private channel stays private even for moderation.
    if channel.access == channel.Access.PRIVATE:
        return channel.moderators.filter(pk=user.pk).exists()
    if channel.access == channel.Access.WORKGROUP:
        return _can_moderate_workgroup_channel(channel, user)
    if user.is_staff:
        return True
    if channel.moderators.filter(pk=user.pk).exists():
        return True
    # Legacy committee-access channels: chairs of the gating committee
    # moderate, read via the committee's workgroup roster.
    if channel.committee_id is not None:
        return WorkgroupMembership.objects.serving().filter(
            user=user,
            workgroup__committee__pk=channel.committee_id,
            role__in=WorkgroupMembership.LEAD_ROLES,
        ).exists()
    return False


def channel_visible(channel, user) -> bool:
    """Whether ``user`` may see and read ``channel``."""
    if not can_enter_parletre(user):
        return False
    # Reversible #360 hides (default off). Private chats vanish for everyone
    # (incl. their creators — this sits above the moderator/membership checks
    # below); school-wide social channels vanish for regular members, staff
    # retained. Flip DJANGO_PARLETRE_*_ENABLED to restore.
    if channel.access == channel.Access.PRIVATE and not settings.PARLETRE_PRIVATE_CHATS_ENABLED:
        return False
    if _is_schoolwide_social(channel) and not settings.PARLETRE_SCHOOLWIDE_SOCIAL_ENABLED:
        if not channel_can_moderate(channel, user):
            return False
    # Archived channels linger for moderators/staff only.
    if channel.archived and not channel_can_moderate(channel, user):
        return False

    access = channel.access
    Access = channel.Access
    if access == Access.OPEN:
        # "Every member" — auditors pass the board gate above but are not
        # members, so they don't get the open channels.
        return is_member(user)
    if access == Access.PRIVATE:
        # Genuinely private: named members or moderators only. Checked before
        # the staff bypass, so staff cannot read a private channel they aren't
        # part of.
        return (
            channel.members.filter(pk=user.pk).exists()
            or channel.moderators.filter(pk=user.pk).exists()
        )
    if access == Access.WORKGROUP:
        # Private to the group: members only, no staff bypass — checked before
        # the staff shortcut below, so a workgroup channel stays private even
        # to staff who aren't in the group. Past-term attendees of an offering
        # keep read-only archive access (they can see, not post — see
        # channel_can_post).
        wg = channel.workgroup
        if wg is None:
            return False
        return wg.is_member(user) or wg.has_archive_access(user)
    if access == Access.LSP_STAFF:
        # The LSP Staff channel: gated by the LSP Staff role (staff keep
        # oversight).
        from core.access import has_staff_role
        from core.models import StaffRole

        return has_staff_role(user, StaffRole.LSP_STAFF) or user.is_staff
    # Role- and committee-gated channels: staff may always read (moderation,
    # support) — privacy is not the point for those.
    if user.is_staff:
        return True
    if access == Access.ROLE:
        profile = getattr(user, "profile", None)
        return profile is not None and profile.role in (channel.allowed_roles or [])
    if access == Access.COMMITTEE:
        # Legacy committee-access channels, read via the committee's workgroup.
        return channel.committee_id is not None and WorkgroupMembership.objects.serving().filter(
            user=user, workgroup__committee__pk=channel.committee_id
        ).exists()
    return False


def channel_can_post(channel, user) -> bool:
    """Whether ``user`` may start threads / post in ``channel``."""
    if not channel_visible(channel, user):
        return False
    if channel.post_policy == channel.PostPolicy.STAFF_ONLY:
        return channel_can_moderate(channel, user)
    if channel.access == channel.Access.WORKGROUP:
        # Archive viewers (past-term attendees) can read but not post — posting
        # needs ACTIVE membership (current term / stored).
        wg = channel.workgroup
        return wg is not None and wg.is_member(user)
    return True
