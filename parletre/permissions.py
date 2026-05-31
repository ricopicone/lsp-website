"""Access control for Parlêtre (the members-only discussion board).

Two layers:

* :func:`is_member` — the board-wide gate (MEM-1). Decides whether a user
  may enter Parlêtre at all. A "member" is anyone holding one of the LSP
  member roles, anyone on an active committee (Board / Programming
  Committee / LSP Staff), or any Django staff user.
* Per-channel access — :func:`channel_visible`, :func:`channel_can_post`,
  and :func:`channel_can_moderate` — layered on top, keyed off the
  channel's ``access`` and ``post_policy`` fields. ``Channel`` exposes
  thin method wrappers (``visible_to`` / ``can_post`` / ``can_moderate``)
  that delegate here.

``is_staff`` is god-mode for *open*, *role*, and *committee* channels —
matching the rest of the site, where staff need reach for moderation and
support. **Private channels are the exception:** they are genuinely private,
visible and moderable only to their named members / moderators, with no staff
bypass. This is application-level privacy, not cryptographic — a database
administrator can still read the rows — but the product never surfaces a
private channel to someone who isn't in it.

Every channel, of every access mode, still sits behind :func:`is_member`:
Parlêtre as a whole is members-only and never public.
"""

from __future__ import annotations

from accounts.models import Profile
from committees.models import CommitteeMembership
from workgroups.models import Workgroup, WorkgroupMembership

#: Workgroup kinds whose channels allow the staff read/moderate bypass.
#: Cartels and working groups are intimate — genuinely private, no bypass
#: (like a PRIVATE channel). Committees and seminars keep staff oversight,
#: matching the legacy COMMITTEE access mode.
_WORKGROUP_STAFF_BYPASS_KINDS = (Workgroup.Kind.COMMITTEE, Workgroup.Kind.SEMINAR)

#: The LSP roles that, on their own, grant entry to the members-only board.
#: Mirrors the public-directory membership set — the people the school
#: considers actual members (analysts, candidates, pre-candidates across both
#: tracks, scholars, and plain members). Prospective applicants, students,
#: and guests (external) are excluded.
MEMBER_ROLES = Profile.DIRECTORY_ROLES


def _authenticated(user) -> bool:
    return bool(getattr(user, "is_authenticated", False))


def is_member(user) -> bool:
    """Whether ``user`` may enter Parlêtre at all (the MEM-1 gate)."""
    if not _authenticated(user):
        return False
    if user.is_staff:
        return True
    profile = getattr(user, "profile", None)
    if profile is not None and profile.role in MEMBER_ROLES:
        return True
    # Board / PC / Staff members may sit outside the member-role set (e.g. an
    # admin assistant carried as a guest role) but still belong on the board.
    return CommitteeMembership.objects.filter(
        user=user, end_date__isnull=True
    ).exists()


def _workgroup_lead(workgroup, user) -> bool:
    """Whether ``user`` holds a leading role (chair / co-chair / plus-one) in
    ``workgroup`` — the roles that moderate its channel."""
    return WorkgroupMembership.objects.filter(
        workgroup=workgroup,
        user=user,
        end_date__isnull=True,
        role__in=WorkgroupMembership.LEAD_ROLES,
    ).exists()


def _can_moderate_workgroup_channel(channel, user) -> bool:
    if channel.moderators.filter(pk=user.pk).exists():
        return True
    wg = channel.workgroup
    if wg is None:
        return False
    if _workgroup_lead(wg, user):
        return True
    return user.is_staff and wg.kind in _WORKGROUP_STAFF_BYPASS_KINDS


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
    # Chairs of a channel's gating committee moderate it by default.
    if channel.committee_id is not None:
        return CommitteeMembership.objects.filter(
            user=user,
            committee_id=channel.committee_id,
            end_date__isnull=True,
            role_in_committee__in=(
                CommitteeMembership.Role.CHAIR,
                CommitteeMembership.Role.CO_CHAIR,
            ),
        ).exists()
    return False


def channel_visible(channel, user) -> bool:
    """Whether ``user`` may see and read ``channel``."""
    if not is_member(user):
        return False
    # Archived channels linger for moderators/staff only.
    if channel.archived and not channel_can_moderate(channel, user):
        return False

    access = channel.access
    Access = channel.Access
    if access == Access.OPEN:
        return True
    if access == Access.PRIVATE:
        # Genuinely private: named members or moderators only. Checked before
        # the staff bypass, so staff cannot read a private channel they aren't
        # part of.
        return (
            channel.members.filter(pk=user.pk).exists()
            or channel.moderators.filter(pk=user.pk).exists()
        )
    if access == Access.WORKGROUP:
        # Gated by workgroup membership. Intimate kinds (cartel / working group)
        # get no staff bypass — checked before the staff shortcut below.
        wg = channel.workgroup
        if wg is None:
            return False
        if wg.is_member(user):
            return True
        return user.is_staff and wg.kind in _WORKGROUP_STAFF_BYPASS_KINDS
    # Role- and committee-gated channels: staff may always read (moderation,
    # support) — privacy is not the point for those.
    if user.is_staff:
        return True
    if access == Access.ROLE:
        profile = getattr(user, "profile", None)
        return profile is not None and profile.role in (channel.allowed_roles or [])
    if access == Access.COMMITTEE:
        return channel.committee_id is not None and CommitteeMembership.objects.filter(
            user=user, committee_id=channel.committee_id, end_date__isnull=True
        ).exists()
    return False


def channel_can_post(channel, user) -> bool:
    """Whether ``user`` may start threads / post in ``channel``."""
    if not channel_visible(channel, user):
        return False
    if channel.post_policy == channel.PostPolicy.STAFF_ONLY:
        return channel_can_moderate(channel, user)
    return True
