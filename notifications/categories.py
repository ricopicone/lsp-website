"""The controlled vocabulary of notification categories and their delivery
defaults.

Every in-app/email notification belongs to exactly one :class:`Category`. A
category carries metadata (:class:`CategoryMeta`) describing which section of
the preferences page it appears under, its human label, and its *default*
delivery on each channel (in-app bell + email).

Two flags need care:

* ``email_locked`` — transactional/security mail the member may **not** silence
  (payment receipts, registration confirmations, email-change verification,
  magic-link and password-reset links). For these, email is always sent
  regardless of preference.
* ``in_app_capable`` / ``email_capable`` — some categories only make sense on
  one channel. Magic-link and password-reset are email-only (no bell row);
  workgroup activity is in-app-first.

Preferences are resolved against these defaults — see
:mod:`notifications.preferences`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.db import models
from django.utils.translation import gettext_lazy as _


class Category(models.TextChoices):
    # --- Discussion (Parlêtre) ------------------------------------------
    PARLETRE_MENTION = "parletre_mention", _("You're mentioned")
    PARLETRE_REPLY = "parletre_reply", _("Replies in your threads")
    PARLETRE_THREAD = "parletre_thread", _("New threads in channels you follow")

    # --- Registration & payments ----------------------------------------
    REGISTRATION_STATUS = "registration_status", _("Registration updates")
    REGISTRATION_CONFIRMED = "registration_confirmed", _("Registration confirmation")
    PAYMENT_RECEIPT = "payment_receipt", _("Payment receipts")
    DUES_REMINDER = "dues_reminder", _("Dues reminders")
    TUITION_REMINDER = "tuition_reminder", _("Tuition reminders")
    TUITION_PLAN_REVIEW = "tuition_plan_review", _("Tuition payment plans")
    TUITION_PLAN_DECISION = "tuition_plan_decision", _("Your payment plan application")
    BALANCE_REMINDER = "balance_reminder", _("Balance reminders")

    # --- Cartels ---------------------------------------------------------
    CARTEL_INVITE = "cartel_invite", _("Cartel invitations")
    CARTEL_APPLICATION = "cartel_application", _("Cartel applications")
    CARTEL_DECISION = "cartel_decision", _("Cartel decisions")
    CARTEL_PROPOSAL = "cartel_proposal", _("Cartel proposal review")

    # --- Admissions ------------------------------------------------------
    ADMISSIONS_APPLICATION = "admissions_application", _("Admissions applications")
    ADMISSIONS_DECISION = "admissions_decision", _("Admissions decisions")
    ADMISSIONS_ADVANCEMENT = "admissions_advancement", _("Advancement (demande)")
    EXTERNAL_CONTROL_ANALYST = "external_control_analyst", _("External control analyst review")
    FORMATION_BACKGROUND = "formation_background", _("Formation background")

    # --- Groups (workgroups / cartels / committees / seminars) ----------
    GROUP_MEMBERSHIP = "group_membership", _("Added to or removed from a group")
    GROUP_MEETING = "group_meeting", _("Group meetings scheduled")
    GROUP_MEETING_REMINDER = "group_meeting_reminder", _("Meeting starting soon")
    GROUP_DECISION = "group_decision", _("Group decisions & minutes")
    GROUP_RECORDING = "group_recording", _("Meeting recordings ready")
    EVENT_CHANGE_REVIEW = "event_change_review", _("Event content change reviews")

    # --- Referrals ---------------------------------------------------------
    REFERRAL_REQUEST = "referral_request", _("Referral requests")

    # --- Suggestions -----------------------------------------------------
    SUGGESTION_FILED = "suggestion_filed", _("Suggestion review")
    SUGGESTION_UPDATE = "suggestion_update", _("Updates on your suggestions")

    # --- Account ---------------------------------------------------------
    ACCOUNT_ADVISOR = "account_advisor", _("Advisor assignments")
    ACCOUNT_UPDATES = "account_updates", _("Account updates")
    ACCOUNT_SECURITY = "account_security", _("Account & security")
    AVAILABILITY_REVIEW = "availability_review", _("Availability review requests")


class EmailDelivery(models.TextChoices):
    IMMEDIATE = "immediate", _("Email me")
    DIGEST = "digest", _("In a digest")
    OFF = "off", _("No email")


class DigestCadence(models.TextChoices):
    OFF = "off", _("Off")
    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")


# Display sections, in the order they appear on the preferences page.
SECTION_DISCUSSION = _("Discussion (Parlêtre)")
SECTION_PAYMENTS = _("Registration & payments")
SECTION_CARTELS = _("Cartels")
SECTION_ADMISSIONS = _("Admissions")
SECTION_GROUPS = _("Groups")
SECTION_REFERRALS = _("Referrals")
SECTION_SUGGESTIONS = _("Suggestions")
SECTION_ACCOUNT = _("Account")

SECTION_ORDER = [
    SECTION_DISCUSSION,
    SECTION_PAYMENTS,
    SECTION_CARTELS,
    SECTION_ADMISSIONS,
    SECTION_GROUPS,
    SECTION_REFERRALS,
    SECTION_SUGGESTIONS,
    SECTION_ACCOUNT,
]


@dataclass(frozen=True)
class CategoryMeta:
    section: str
    label: str
    help_text: str = ""
    default_in_app: bool = True
    default_email: str = EmailDelivery.IMMEDIATE
    # Email the member may not turn off (transactional/security).
    email_locked: bool = False
    # Whether this category can appear on each channel at all.
    in_app_capable: bool = True
    email_capable: bool = True
    # Optional per-recipient email default, consulted only when the member
    # hasn't chosen for themselves. Lets a queue aim its email at the role that
    # owns it while the rest of the committee keeps the bell row; both sides
    # can still override on the settings page.
    default_email_for: Callable[[object], str] | None = None


_M = CategoryMeta
_C = Category
_E = EmailDelivery


def _tuition_plan_review_default(user) -> str:
    """Aim payment-plan application email at the Treasurer (task #491).

    The Board reviews and decides these applications, so everyone on it gets
    the bell row, but only the Treasurer needs an email per application. If
    nobody holds the role, fall back to emailing the Board — an unassigned
    role must never mean an application sits unseen.
    """
    from core.access import has_staff_role
    from core.models import StaffRole

    if has_staff_role(user, StaffRole.TREASURER):
        return EmailDelivery.IMMEDIATE
    held = StaffRole.objects.filter(
        key=StaffRole.TREASURER, holders__isnull=False,
    ).exists()
    return EmailDelivery.OFF if held else EmailDelivery.IMMEDIATE


CATEGORY_META: dict[str, CategoryMeta] = {
    # Discussion — email cadence is governed by Parlêtre's own per-channel
    # subscriptions; these flags drive the in-app bell and the master on/off.
    _C.PARLETRE_MENTION: _M(
        SECTION_DISCUSSION, _("You're mentioned"),
        _("When someone @mentions you on the board."),
    ),
    _C.PARLETRE_REPLY: _M(
        SECTION_DISCUSSION, _("Replies in your threads"),
        _("When someone replies in a thread you started."),
    ),
    _C.PARLETRE_THREAD: _M(
        SECTION_DISCUSSION, _("New threads"),
        _("New threads in channels you follow closely."),
        default_email=_E.OFF,
    ),
    # Registration & payments.
    _C.REGISTRATION_STATUS: _M(
        SECTION_PAYMENTS, _("Registration updates"),
        _("When a registration is approved, declined, or cancelled."),
    ),
    _C.REGISTRATION_CONFIRMED: _M(
        SECTION_PAYMENTS, _("Registration confirmation"),
        _("Your confirmation and access details. Always emailed."),
        email_locked=True,
    ),
    _C.PAYMENT_RECEIPT: _M(
        SECTION_PAYMENTS, _("Payment receipts"),
        _("Receipts for payments you make. Always emailed."),
        email_locked=True,
    ),
    _C.DUES_REMINDER: _M(
        SECTION_PAYMENTS, _("Dues reminders"),
        _("Periodic reminders when dues are owed."),
    ),
    _C.TUITION_REMINDER: _M(
        SECTION_PAYMENTS, _("Tuition reminders"),
        _("Periodic reminders about tuition for the year."),
    ),
    _C.TUITION_PLAN_REVIEW: _M(
        SECTION_PAYMENTS, _("Tuition payment plans"),
        _("For the Treasurer and Board: a payment plan application to review. "
          "The Treasurer is emailed each application; the rest of the Board "
          "sees it in the bell, unless you turn email on here."),
        default_email=_E.OFF,
        default_email_for=_tuition_plan_review_default,
    ),
    # Kept separate from the reviewer queue above: quieting the queue must
    # never stop an applicant hearing their own outcome.
    _C.TUITION_PLAN_DECISION: _M(
        SECTION_PAYMENTS, _("Your payment plan application"),
        _("The Board's decision on a tuition payment plan you applied for."),
    ),
    _C.BALANCE_REMINDER: _M(
        SECTION_PAYMENTS, _("Balance reminders"),
        _("Periodic reminders when your account has an outstanding balance "
          "(dues, tuition, or event fees)."),
    ),
    # Cartels.
    _C.CARTEL_INVITE: _M(SECTION_CARTELS, _("Cartel invitations")),
    _C.CARTEL_APPLICATION: _M(SECTION_CARTELS, _("Applications to your cartel")),
    _C.CARTEL_DECISION: _M(SECTION_CARTELS, _("Decisions on your cartel")),
    _C.CARTEL_PROPOSAL: _M(
        SECTION_CARTELS, _("Proposal review"),
        _("For coordinators and the Programming Committee."),
    ),
    # Admissions.
    _C.ADMISSIONS_APPLICATION: _M(
        SECTION_ADMISSIONS, _("Applications"),
        _("For reviewers: a new application or advancement to review."),
    ),
    _C.ADMISSIONS_DECISION: _M(
        SECTION_ADMISSIONS, _("Decisions"),
        _("Decisions on your application or advancement."),
    ),
    _C.ADMISSIONS_ADVANCEMENT: _M(
        SECTION_ADMISSIONS, _("Advancement (demande)"),
        _("Advancement demandes you advise or present."),
    ),
    _C.EXTERNAL_CONTROL_ANALYST: _M(
        SECTION_ADMISSIONS, _("External control analyst"),
        _("Requests to authorize an analyst outside the School for control "
          "analysis, for you to review."),
    ),
    # Groups — in-app first; email optional (default off to avoid noise).
    _C.GROUP_MEMBERSHIP: _M(
        SECTION_GROUPS, _("Membership changes"),
        _("When you're added to or removed from a group."),
        default_email=_E.OFF,
    ),
    _C.GROUP_MEETING: _M(
        SECTION_GROUPS, _("Meetings scheduled"),
        _("New meetings or series in your groups."),
        default_email=_E.OFF,
    ),
    # Reminder 15 min before a meeting, with a personal one-tap join link.
    # Email defaults ON (a reminder you only see in the bell is little use),
    # but it's not locked — members can turn it off here.
    _C.GROUP_MEETING_REMINDER: _M(
        SECTION_GROUPS, _("Meeting starting soon"),
        _("A reminder ~15 minutes before a meeting in your groups, with a "
          "link to join."),
    ),
    _C.GROUP_DECISION: _M(
        SECTION_GROUPS, _("Decisions & minutes"),
        _("Decisions recorded and minutes posted in your groups."),
        default_email=_E.OFF,
    ),
    _C.GROUP_RECORDING: _M(
        SECTION_GROUPS, _("Recordings ready"),
        _("When a meeting recording becomes available."),
        default_email=_E.OFF,
    ),
    _C.EVENT_CHANGE_REVIEW: _M(
        SECTION_GROUPS, _("Event content change reviews"),
        _("When a faculty content change is submitted for committee review, "
          "and when the committee decides on yours."),
    ),
    # Referrals — distribution to the referral list. Email defaults on (a
    # clinician who never checks the bell would otherwise miss requests).
    _C.REFERRAL_REQUEST: _M(
        SECTION_REFERRALS, _("Referral requests"),
        _("For clinicians on the referral list: an anonymized request "
          "seeking an analyst."),
    ),
    # Suggestions.
    _C.SUGGESTION_FILED: _M(
        SECTION_SUGGESTIONS, _("Suggestion review"),
        _("For site staff: a member filed a suggestion to triage."),
        default_email=_E.OFF,
    ),
    _C.SUGGESTION_UPDATE: _M(
        SECTION_SUGGESTIONS, _("Updates on your suggestions"),
        _("When staff respond to or change the status of a suggestion you filed."),
    ),
    # Account.
    _C.ACCOUNT_ADVISOR: _M(
        SECTION_ACCOUNT, _("Advisor assignments"),
        _("When you're chosen as, or assigned, an advisor."),
    ),
    _C.FORMATION_BACKGROUND: _M(
        SECTION_ACCOUNT, _("Formation background"),
        _("When the Meeting of Analysts or your advisor sets your "
          "control-analysis requirement (clinical or academic)."),
        default_email=_E.OFF,
    ),
    # Outcomes on the member's own financial account — currently the
    # treasurer's decision on a payment/fee the member reported from before
    # the website (task #439 §3).
    _C.ACCOUNT_UPDATES: _M(
        SECTION_ACCOUNT, _("Account updates"),
        _("Decisions on payments or fees you report for your account."),
    ),
    _C.ACCOUNT_SECURITY: _M(
        SECTION_ACCOUNT, _("Account & security"),
        _("Sign-in links, email changes, password resets. Always emailed."),
        default_in_app=False, in_app_capable=False, email_locked=True,
    ),
    # Applications Coordinator's periodic ask that an analyst review which LSP
    # functions they're available for. Email defaults on (a prompt seen only in
    # the bell is little use), but it's not locked — analysts can turn it off.
    _C.AVAILABILITY_REVIEW: _M(
        SECTION_ACCOUNT, _("Availability review requests"),
        _("For Analysts of the School: an occasional request to confirm which "
          "LSP functions you're available for."),
    ),
}


def meta_for(category: str) -> CategoryMeta:
    """Metadata for ``category``; falls back to a permissive default so an
    unknown/legacy value never crashes dispatch."""
    return CATEGORY_META.get(
        category,
        CategoryMeta(SECTION_ACCOUNT, str(category)),
    )
