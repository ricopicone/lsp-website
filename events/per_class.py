"""Per-class billing (REG-6, task #811): record, correct, bill, notify.

A per-class registration is enrolled at $0 and carries ``per_class_rate``.
After each class this module records a :class:`~events.models.ClassAttendance`
row per registrant, leaves it open to correction for ``WINDOW``, then bills it:
a present row becomes one ordinary registration-category ``payments.Charge``
linked through ``Charge.class_attendance`` with ``registration`` left empty, so
none of the whole-registration paths (mint/void, refunds, removal, the
one-charge-per-registration constraint) can see it. Members are told what was
billed once a week. The ledger needs no change: these are registration
charges like any other, and a seminar's open balance is read from the
registration's own money (:func:`class_coverage`).

``run(now)`` is the whole pipeline, called every five minutes from
``send_meeting_reminders``. Every step is idempotent.

Design: ``docs/superpowers/specs/2026-10-12-per-class-billing-design.md``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import ClassAttendance, Event, Session

logger = logging.getLogger(__name__)

#: How long after a class ends its attendance can be corrected before billing.
WINDOW = timedelta(hours=72)
#: A row recorded late (the timer was down) still gets at least this long.
MIN_WINDOW = timedelta(hours=24)
#: How long after billing faculty may still un-bill a class by marking absent.
CORRECTION_DAYS = 14
#: Give Daily time to close the meeting before asking who was in it.
RECORD_DELAY = timedelta(minutes=15)
#: Keep retrying a failed room lookup this long, then presume present.
DETECT_RETRY = timedelta(hours=24)
#: Joins this close to the class count as attending it.
DETECT_MARGIN = timedelta(minutes=30)
#: How far back to ask Daily for meetings that may have spanned the class.
DETECT_LOOKBACK = timedelta(hours=12)
#: Weekly billing notice: Monday, from this school-local hour.
NOTICE_WEEKDAY = 0
NOTICE_HOUR = 9


class AttendanceError(Exception):
    """A mark the rules refuse; the message is member-facing."""


# ---- small predicates -------------------------------------------------------


def _enrolled_statuses():
    from registrations.models import Registration

    return (Registration.Status.PAID, Registration.Status.COMPED)


def window_closes(att: ClassAttendance):
    """When ``att`` stops being correctable and is billed."""
    return max(att.session.end_at + WINDOW, att.recorded_at + MIN_WINDOW)


def is_covered(registration) -> bool:
    """Whether tuition covers this registrant's classes: a covered tier, no
    code, and tuition-current for the **event's** academic year (the same
    anchor as ``events.pricing._is_tuition_paying``)."""
    tier = registration.price_tier
    if not tier.covered_by_tuition or registration.pricing_code_id:
        return False
    profile = getattr(registration.user, "profile", None)
    return bool(profile and profile.is_tuition_current(registration.event.start_date))


def detects(event: Event) -> bool:
    """Whether attendance can be read from the site's room: the event meets
    there and nowhere else (a hybrid class has an in-room half the site can't
    see)."""
    from video.services import daily_enabled

    return (
        event.format == Event.Format.ONLINE
        and event.uses_insite_room
        and daily_enabled()
    )


def detect_present(session: Session) -> set[int] | None:
    """User ids that joined the event's room around ``session``.

    ``None`` means the room could not be read (retry later). A room that was
    never created means nobody met in it, so nobody is detected.
    """
    from video import daily
    from video.models import DailyRoom
    from video.services import _room_name, room_owner_for_event

    owner = room_owner_for_event(session.event)
    if owner is None:
        return set()
    name = _room_name(owner)
    if not DailyRoom.objects.filter(name=name).exists():
        return set()
    start = int((session.start_at - DETECT_MARGIN).timestamp())
    end = int((session.end_at + DETECT_MARGIN).timestamp())
    try:
        # Daily filters meetings by when the *meeting* started, so a room
        # opened well before class, or still running from earlier, would be
        # missed by a tight window. Ask wide; judge each participant's own
        # time in the room against the class below.
        meetings = daily.list_meetings(
            name, start=start - int(DETECT_LOOKBACK.total_seconds()), end=end,
        )
    except Exception:
        logger.warning("Could not read Daily meetings for %s", name, exc_info=True)
        return None
    present: set[int] = set()
    for meeting in meetings:
        for p in meeting.get("participants") or []:
            uid = str(p.get("user_id") or "")
            if not uid.isdigit():
                continue
            joined = p.get("join_time")
            if joined is not None:
                left = joined + (p.get("duration") or 0)
                if left < start or joined > end:
                    continue        # in the room, but not during this class
            present.add(int(uid))
    return present


# ---- recording ----------------------------------------------------------------


@dataclass
class Recorded:
    session: Session
    rows: list
    detect_failed: bool = False


def _unrecorded_registrations(session: Session):
    from registrations.models import Registration

    return (
        Registration.objects
        .filter(
            event_id=session.event_id,
            per_class_rate__isnull=False,
            status__in=_enrolled_statuses(),
            created_at__lt=session.end_at,
        )
        .exclude(class_attendance__session=session)
        .select_related("user")
    )


def record_session(session: Session, *, now=None) -> Recorded | None:
    """Create the attendance rows for ``session``. ``None`` = try again later
    (the room could not be read and the retry period has not run out)."""
    now = now or timezone.now()
    regs = list(_unrecorded_registrations(session))
    if not regs:
        return Recorded(session, [])
    detect_failed = False
    present_ids = None
    if detects(session.event):
        present_ids = detect_present(session)
        if present_ids is None:
            if now - session.end_at < DETECT_RETRY:
                return None
            detect_failed = True
    rows = []
    for reg in regs:
        if present_ids is None:
            present, source = True, ClassAttendance.Source.PRESUMED
        else:
            present = reg.user_id in present_ids
            source = ClassAttendance.Source.DETECTED
        att, created = ClassAttendance.objects.get_or_create(
            registration=reg, session=session,
            defaults={"present": present, "source": source, "recorded_at": now},
        )
        if created:
            note = "Recorded " + ("present" if present else "absent")
            note += f" ({att.get_source_display().lower()})"
            if detect_failed:
                note += "; the room's attendance couldn't be read"
            att.add_note(note + ".")
            att.save(update_fields=("notes",))
            rows.append(att)
    return Recorded(session, rows, detect_failed)


def due_sessions(now):
    """Ended classes of per-class events, after the event became per-class."""
    return (
        Session.objects
        .filter(
            event__billing_mode=Event.BillingMode.PER_CLASS,
            event__per_class_since__isnull=False,
            end_at__lte=now - RECORD_DELAY,
        )
        .select_related("event")
        .order_by("end_at")
    )


# ---- billing --------------------------------------------------------------------


def bill(att: ClassAttendance, *, now=None):
    """Settle ``att``'s outcome, minting its charge when one is owed.

    Idempotent: a row already billed is returned as is. Returns the Charge or
    ``None``.
    """
    from accounts.models import Source
    from payments.models import Charge
    from registrations.models import Registration

    now = now or timezone.now()
    with transaction.atomic():
        att = (
            ClassAttendance.objects.select_for_update()
            .select_related("registration__price_tier", "registration__event",
                            "registration__user", "session")
            .get(pk=att.pk)
        )
        if att.billed_at is not None:
            return att.charges.exclude(status=Charge.Status.VOID).first()
        reg = att.registration
        rate = reg.per_class_rate or Decimal("0")
        charge = None
        if not att.present:
            outcome = ClassAttendance.Outcome.ABSENT
        elif reg.status == Registration.Status.COMPED:
            outcome = ClassAttendance.Outcome.COMPED
        elif is_covered(reg):
            outcome = ClassAttendance.Outcome.COVERED
        elif rate <= 0:
            outcome = ClassAttendance.Outcome.NO_CHARGE
        else:
            outcome = ClassAttendance.Outcome.CHARGED
            charge = _mint(att, rate, source=Source.STAFF)
        att.outcome = outcome
        att.billed_at = now
        att.save(update_fields=("outcome", "billed_at"))
        return charge


def _class_date(att: ClassAttendance):
    return timezone.localdate(att.session.start_at)


def _mint(att: ClassAttendance, amount: Decimal, *, source):
    from payments.models import Charge

    day = _class_date(att)
    return Charge.objects.create(
        user_id=att.registration.user_id,
        category=Charge.Category.REGISTRATION,
        amount=amount,
        effective_date=day,
        class_attendance=att,
        source=source,
        notes=(
            f"[{timezone.localdate()}] {att.registration.event.title}, class of "
            f"{day:%b} {day.day} ({att.get_source_display().lower()})."
        ),
    )


# ---- balances -------------------------------------------------------------------


def class_charges(registration):
    from payments.models import Charge

    return (
        Charge.objects
        .filter(class_attendance__registration=registration,
                status=Charge.Status.OPEN)
        .select_related("class_attendance__session")
        .order_by("effective_date", "id")
    )


def class_coverage(registration) -> dict[int, Decimal]:
    """How much of each open class charge this registration's own money
    covers, oldest class first.

    Scoped to the registration, deliberately, rather than read off the
    member-wide registration bucket the statement sweeps (#473): old
    registration credit (imported payments carry no charge) would otherwise
    silently "pay" classes, and a class payment would land on an older
    seminar's plan charge and leave these classes asking to be paid again.
    The money that counts is what was paid *for this registration*: its
    class payments, plus what it holds through ``registration`` (a converted
    registration's original whole-seminar payment), less any whole-seminar
    charge still open on it. The account balance is unaffected either way;
    this only decides what this seminar's panel and corrections read.
    """
    from django.db.models import Q

    from payments.ledger import _counts
    from payments.models import Charge, Payment

    pot = sum(
        (p.amount for p in Payment.objects.filter(
            Q(per_class_registration=registration) | Q(registration=registration),
        ) if _counts(p)),
        Decimal("0"),
    )
    pot -= sum(
        (c.amount for c in Charge.objects.filter(
            registration=registration, status=Charge.Status.OPEN,
        )),
        Decimal("0"),
    )
    covered: dict[int, Decimal] = {}
    for charge in class_charges(registration):
        take = max(min(charge.amount, pot), Decimal("0"))
        covered[charge.id] = take
        pot -= take
    return covered


def open_charges(registration) -> list[tuple]:
    """``(charge, remaining)`` for each billed class not yet fully paid."""
    covered = class_coverage(registration)
    out = []
    for c in class_charges(registration):
        remaining = c.amount - covered.get(c.id, Decimal("0"))
        if remaining > 0:
            out.append((c, remaining))
    return out


def open_balance(registration) -> Decimal:
    return sum((r for _c, r in open_charges(registration)), Decimal("0"))


def _unpaid_charge(att: ClassAttendance):
    """The row's open charge if no money at all has reached it, else None."""
    from payments.models import Charge

    charge = att.charges.filter(status=Charge.Status.OPEN).first()
    if charge is None:
        return None
    if class_coverage(att.registration).get(charge.id, Decimal("0")) > 0:
        return None
    return charge


def correction_open(att: ClassAttendance, *, now=None) -> bool:
    """Whether faculty may still change a billed row (14 days)."""
    now = now or timezone.now()
    return (
        att.billed_at is not None
        and now - att.billed_at <= timedelta(days=CORRECTION_DAYS)
    )


def can_unbill(att: ClassAttendance, *, now=None) -> bool:
    return (
        att.outcome == ClassAttendance.Outcome.CHARGED
        and correction_open(att, now=now)
        and _unpaid_charge(att) is not None
    )


# ---- corrections ------------------------------------------------------------------


def mark(att: ClassAttendance, *, present: bool, by, as_faculty: bool, now=None) -> str:
    """Change ``att`` under the rules. Returns a member-facing summary of what
    happened; raises :class:`AttendanceError` when the rules refuse.

    - in the window: faculty mark anyone (and lock the row); a member marks
      themselves unless faculty have;
    - after billing, faculty only, within ``CORRECTION_DAYS``: present →
      absent voids the charge while no money has reached it; absent → present
      bills the class now.
    """
    now = now or timezone.now()
    if att.present == present:
        return "No change."
    label = "present" if present else "absent"
    who = by.get_full_name() or by.email

    if att.billed_at is None:
        if not as_faculty:
            if att.faculty_locked:
                raise AttendanceError("Your faculty have already set this one.")
            if now > window_closes(att):
                raise AttendanceError("The time to correct this class has passed.")
        att.present = present
        att.source = (ClassAttendance.Source.FACULTY if as_faculty
                      else ClassAttendance.Source.STUDENT)
        att.faculty_locked = att.faculty_locked or as_faculty
        att.marked_by = by
        att.add_note(f"Marked {label} by {who}.")
        att.save(update_fields=("present", "source", "faculty_locked",
                                "marked_by", "notes"))
        return f"Marked {label}."

    if not as_faculty:
        raise AttendanceError("This class has already been billed.")
    if not correction_open(att, now=now):
        raise AttendanceError(
            "It's been more than two weeks since this class was billed. "
            "Ask the treasurer."
        )
    from payments.models import Charge

    with transaction.atomic():
        if not present:
            charge = _unpaid_charge(att)
            if att.outcome == ClassAttendance.Outcome.CHARGED and charge is None:
                raise AttendanceError(
                    "This class has already been paid for. Ask the treasurer."
                )
            if charge is not None:
                charge.status = Charge.Status.VOID
                charge.add_note(f"Marked absent by {who}; class charge voided.", save=False)
                charge.save(update_fields=("status", "notes"))
            att.outcome = ClassAttendance.Outcome.ABSENT
        else:
            att.billed_at = None
            att.outcome = ClassAttendance.Outcome.PENDING
            att.notified_at = None
        att.present = present
        att.source = ClassAttendance.Source.FACULTY
        att.faculty_locked = True
        att.marked_by = by
        att.add_note(f"Marked {label} by {who} after billing.")
        att.save(update_fields=("present", "source", "faculty_locked", "marked_by",
                                "notes", "outcome", "billed_at", "notified_at"))
    if present:
        bill(att, now=now)
    from payments import notifications as notify_payments

    att.refresh_from_db()
    notify_payments.class_rebilled(att, removed=not present)
    return f"Marked {label}."


# ---- tuition coverage hooks -----------------------------------------------------


def _in_period(att_or_reg_event, period) -> bool:
    from payments.ledger import period_for_event

    return period_for_event(att_or_reg_event) == period


def covered_classes(user, period) -> list[tuple]:
    """``(attendance, amount)`` for each class tuition covered in ``period``,
    what a SKIPPING decision would bill (the #485 interstitial lists them)."""
    rows = (
        ClassAttendance.objects
        .filter(registration__user=user,
                outcome=ClassAttendance.Outcome.COVERED)
        .select_related("registration__event", "session")
    )
    out = []
    for att in rows:
        rate = att.registration.per_class_rate or Decimal("0")
        if rate > 0 and _in_period(att.registration.event, period):
            out.append((att, rate))
    return out


def bill_covered_classes(user, period) -> list:
    """Recording SKIPPING (member path only): bill each class tuition had
    covered in ``period`` at the member's per-class rate (mirrors #485)."""
    from accounts.models import Source

    charges = []
    for att, rate in covered_classes(user, period):
        with transaction.atomic():
            att.outcome = ClassAttendance.Outcome.CHARGED
            att.notified_at = None
            att.add_note("Billed: tuition skipped for the year, so coverage "
                         "no longer applies.")
            att.save(update_fields=("outcome", "notified_at", "notes"))
            charges.append(_mint(att, rate, source=Source.STAFF))
    return charges


def void_covered_open(user, period) -> list:
    """Recording a covering decision (member or treasurer path): void each
    class charge in ``period`` that tuition now covers and no money has
    reached (mirrors #561). Paid classes are the treasurer's refund call."""
    from payments.models import Charge

    charges = list(
        Charge.objects
        .filter(class_attendance__registration__user=user,
                status=Charge.Status.OPEN)
        .select_related("class_attendance__registration__price_tier",
                        "class_attendance__registration__event")
    )
    if not charges:
        return []
    voided = []
    coverage_by_reg: dict = {}
    for charge in charges:
        att = charge.class_attendance
        reg = att.registration
        if not _in_period(reg.event, period) or not is_covered(reg):
            continue
        if reg.pk not in coverage_by_reg:
            coverage_by_reg[reg.pk] = class_coverage(reg)
        if coverage_by_reg[reg.pk].get(charge.id, Decimal("0")) > 0:
            continue
        with transaction.atomic():
            charge.status = Charge.Status.VOID
            charge.add_note("Tuition covers this class; charge voided.", save=False)
            charge.save(update_fields=("status", "notes"))
            att.outcome = ClassAttendance.Outcome.COVERED
            att.add_note("Covered by tuition after billing; charge voided.")
            att.save(update_fields=("outcome", "notes"))
        voided.append(charge)
    return voided


# ---- the pipeline -------------------------------------------------------------------


def _notify_recorded(recorded: Recorded) -> int:
    from payments import notifications as notify_payments

    if not recorded.rows:
        return 0
    notify_payments.class_attendance_recorded(
        recorded.session, recorded.rows, detect_failed=recorded.detect_failed,
    )
    return len(recorded.rows)


def _week_start(now):
    local = timezone.localtime(now)
    monday = local.date() - timedelta(days=local.weekday())
    return timezone.make_aware(datetime.combine(monday, time.min))


def _notice_due(now) -> bool:
    local = timezone.localtime(now)
    return local.weekday() == NOTICE_WEEKDAY and local.hour >= NOTICE_HOUR


def send_billing_notices(now) -> int:
    """One note per member per seminar, at most once a week, covering the
    classes billed since the last one. Returns how many notes went out."""
    from payments import notifications as notify_payments
    from payments.models import Charge

    week = _week_start(now)
    rows = (
        ClassAttendance.objects
        .filter(outcome=ClassAttendance.Outcome.CHARGED, notified_at__isnull=True)
        .select_related("registration__user", "registration__event", "session")
        .order_by("session__start_at")
    )
    groups = defaultdict(list)
    for att in rows:
        groups[att.registration_id].append(att)
    sent = 0
    for reg_id, atts in groups.items():
        if ClassAttendance.objects.filter(
            registration_id=reg_id, notified_at__gte=week,
        ).exists():
            continue                # already told this week; next Monday
        charges = list(
            Charge.objects.filter(class_attendance__in=atts)
            .exclude(status=Charge.Status.VOID)
            .select_related("class_attendance__session")
        )
        if charges:
            try:
                notify_payments.classes_billed(atts[0].registration, charges)
            except Exception:
                logger.exception("per-class billing note failed for reg %s", reg_id)
                continue
            sent += 1
        ClassAttendance.objects.filter(pk__in=[a.pk for a in atts]).update(notified_at=now)
    return sent


def run(now=None, *, dry: bool = False) -> dict:
    """Record ended classes, bill closed windows, and (Mondays) send the
    weekly billing notes. One bad session or row is logged and skipped, never
    allowed to stall everyone else's billing."""
    now = now or timezone.now()
    stats = {"recorded": 0, "retry": 0, "billed": 0, "notices": 0, "errors": 0}
    for session in due_sessions(now):
        if session.end_at <= session.event.per_class_since:
            continue
        if dry:
            stats["recorded"] += _unrecorded_registrations(session).count()
            continue
        try:
            recorded = record_session(session, now=now)
            if recorded is None:
                stats["retry"] += 1
                continue
            stats["recorded"] += _notify_recorded(recorded)
        except Exception:
            logger.exception("per-class recording failed for session %s", session.pk)
            stats["errors"] += 1
    unbilled = (
        ClassAttendance.objects
        .filter(billed_at__isnull=True)
        .select_related("session")
    )
    for att in unbilled:
        if now < window_closes(att):
            continue
        if dry:
            stats["billed"] += 1
            continue
        try:
            bill(att, now=now)
            stats["billed"] += 1
        except Exception:
            logger.exception("per-class billing failed for attendance %s", att.pk)
            stats["errors"] += 1
    if not dry and _notice_due(now):
        stats["notices"] = send_billing_notices(now)
    return stats


# ---- page context ----------------------------------------------------------------


def _row(att: ClassAttendance, now, *, as_faculty: bool) -> dict:
    billed = att.billed_at is not None
    if billed:
        editable = as_faculty and correction_open(att, now=now) and (
            not att.present or can_unbill(att, now=now)
        )
    elif as_faculty:
        editable = True
    else:
        editable = not att.faculty_locked and now <= window_closes(att)
    return {
        "att": att,
        "day": _class_date(att),
        "closes": window_closes(att),
        "billed": billed,
        "editable": editable,
    }


def member_context(registration, *, now=None) -> dict:
    """The member's "Your classes" panel: each class recorded for them, what
    it came to, and the open balance with its Pay button."""
    now = now or timezone.now()
    rows = [
        _row(att, now, as_faculty=False)
        for att in registration.class_attendance.select_related("session")
        .order_by("-session__start_at")
    ]
    return {"rows": rows, "balance": open_balance(registration)}


def faculty_context(event, *, now=None) -> list[dict]:
    """The faculty Attendance section: recorded classes, newest first."""
    now = now or timezone.now()
    atts = (
        ClassAttendance.objects
        .filter(session__event=event)
        .select_related("session", "registration__user")
        .order_by("-session__start_at", "registration__user__last_name",
                  "registration__user__first_name")
    )
    by_session: dict = {}
    for att in atts:
        by_session.setdefault(att.session, []).append(
            _row(att, now, as_faculty=True)
        )
    return [
        {"session": session, "day": timezone.localdate(session.start_at),
         "rows": rows,
         "present": sum(1 for r in rows if r["att"].present)}
        for session, rows in by_session.items()
    ]


# ---- converting an existing event (task #810) ------------------------------------


def converted_rate(registration) -> Decimal:
    """What a registration made under whole-seminar billing pays per class
    once its event becomes per-class.

    Its code keeps the terms it was given, read per class, without asking
    whether the code could still be redeemed today (a used-up code still
    describes what its holder was offered). Without a code: the tier's base,
    or its floor on a sliding tier, the figure a skipped year re-bills too.
    """
    from events.models import PricingCode
    from payments.coverage import retro_amount

    tier = registration.price_tier
    code = registration.pricing_code
    if code is None:
        return retro_amount(tier)
    value = code.amount_or_percent or Decimal("0")
    if code.pricing_mode == PricingCode.Mode.PERCENT_OFF:
        off = (tier.base_amount * value / Decimal("100")).quantize(Decimal("0.01"))
        return max(tier.base_amount - off, Decimal("0"))
    if code.pricing_mode in (PricingCode.Mode.FIXED_AMOUNT,
                             PricingCode.Mode.SLIDING_FLOOR):
        return value
    return tier.base_amount
