"""Pre-flight report for an online event's video meeting (task #475).

Read-only by default: it reports the room's **live** config, never the config we
intended, and never provisions the room. Creating a room freezes its property
set at whatever the code said that day (see the
``daily-room-config-freezes-at-first-open`` memory), so a *check* must not do it
as a side effect. Pass ``--provision`` when you deliberately want the room
minted and reconciled.

    manage.py event_video_preflight working-with-masochism
    manage.py event_video_preflight working-with-masochism --provision

Exits non-zero if any check FAILs, so it can gate a deploy or a cron.
"""
from __future__ import annotations

import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from events.models import Event
from video import daily, services

OK, WARN, FAIL = "ok", "warn", "fail"


class Command(BaseCommand):
    help = "Read-only pre-flight report for an online event's video meeting."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Event slug, e.g. working-with-masochism")
        parser.add_argument(
            "--provision",
            action="store_true",
            help="Also create/reconcile the Daily room (default is read-only).",
        )

    def handle(self, *args, **options):
        try:
            event = Event.objects.get(slug=options["slug"])
        except Event.DoesNotExist as exc:
            raise CommandError(f"No event with slug {options['slug']!r}") from exc

        rows: list[tuple[str, str, str]] = []
        rows.extend(self._check_feature())
        if services.daily_enabled():
            rows.extend(self._check_event(event))
            rows.extend(self._check_room(event, provision=options["provision"]))
            rows.extend(self._check_hosts(event))
            rows.extend(self._check_registrants(event))
            rows.extend(self._check_token_window(event))
            rows.extend(self._check_presence())

        styles = {
            OK: self.style.SUCCESS, WARN: self.style.WARNING, FAIL: self.style.ERROR
        }
        self.stdout.write(f"\nPre-flight — {event.title} ({event.slug})\n")
        for status, label, detail in rows:
            self.stdout.write(
                f"  {styles[status](status.upper().ljust(4))}  {label}: {detail}"
            )

        failures = [r for r in rows if r[0] == FAIL]
        warnings = [r for r in rows if r[0] == WARN]
        self.stdout.write(
            f"\n{len(rows)} checks, {len(failures)} failed, {len(warnings)} warnings\n"
        )
        if failures:
            sys.exit(1)

    # -- checks ---------------------------------------------------------

    def _check_feature(self):
        if not services.daily_enabled():
            return [(FAIL, "daily", "disabled, or the API key / domain is missing")]
        out = [(OK, "daily", f"enabled, domain {settings.DAILY_DOMAIN}")]
        out.append(
            (OK, "webhook", "secret set")
            if settings.DAILY_WEBHOOK_SECRET
            else (WARN, "webhook", "DAILY_WEBHOOK_SECRET unset, recordings won't ingest")
        )
        return out

    def _check_event(self, event):
        out = []
        if event.format == "in_person":
            out.append((WARN, "format", "in_person, no video room expected"))
        else:
            out.append((OK, "format", event.format))
        out.append(
            (OK, "published", f"published, status={event.status}")
            if event.published
            else (WARN, "published", f"unpublished, status={event.status}")
        )
        out.append(
            (OK, "spotlight", "on, attendees join muted and camera-off")
            if event.speaker_spotlight
            else (WARN, "spotlight", "OFF, attendees arrive unmuted")
        )
        mode = getattr(event, "recording_mode", "on_demand")
        out.append((
            OK, "recording",
            f"record_video={event.record_video}, recording_mode={mode}",
        ))
        if not event.sessions.exists():
            out.append(
                (WARN, "sessions", "none, the join window falls back to the date span")
            )
        else:
            out.append((OK, "sessions", f"{event.sessions.count()}"))
        return out

    def _check_room(self, event, *, provision: bool):
        owner = services.room_owner_for_event(event, create=provision)
        if owner is None:
            return [(
                FAIL, "room",
                "this offering has no workgroup, so no room (re-run --provision)",
            )]
        name = services._room_name(owner)
        if provision:
            if services.ensure_room(owner) is None:
                return [(FAIL, "room", f"{name}: provisioning failed")]
        try:
            data = daily.get_room(name)
        except daily.DailyError as exc:
            return [(FAIL, "room", f"{name}: {exc}")]
        if data is None:
            return [(
                WARN, "room",
                f"{name}: not provisioned yet (mints on first join; "
                f"--provision to do it now)",
            )]

        out = [(OK, "room", f"{name} exists")]
        config = data.get("config") or {}
        drift = {
            key: (config.get(key), value)
            for key, value in services._desired_properties(owner).items()
            if services._norm(config.get(key)) != services._norm(value)
        }
        if drift:
            detail = ", ".join(
                f"{k} is {actual!r}, want {want!r}" for k, (actual, want) in drift.items()
            )
            out.append((FAIL, "room config", detail))
        else:
            out.append((OK, "room config", "matches"))
        return out

    def _check_hosts(self, event):
        # Three ways to be a host: a member speaker, an external Speaker with a
        # linked login (task #463), or faculty on the event's workgroup. Event
        # has no `faculty` M2M — that one lives on EventProposal.
        owner = services.room_owner_for_event(event)
        hosts, seen = [], set()
        for u in (
            list(event.member_speakers.all())
            + [
                s.user
                for s in event.speakers.filter(user__isnull=False).select_related("user")
            ]
            + event.faculty_members()
        ):
            if u is not None and u.pk not in seen:
                seen.add(u.pk)
                hosts.append(u)
        if not hosts:
            return [(WARN, "hosts", "no speakers or faculty listed on the event")]

        out = []
        for u in hosts:
            problems = []
            if not u.is_active:
                problems.append("inactive account")
            if not getattr(getattr(u, "profile", None), "email_verified_at", None):
                problems.append("email unverified")
            if not u.has_usable_password():
                problems.append("no usable password (password reset silently skips them)")
            if owner is not None and not services.can_enter(owner, u):
                problems.append("CANNOT ENTER THE ROOM")
            elif owner is not None and not services.is_owner(owner, u):
                problems.append("not a moderator")
            out.append((
                FAIL if problems else OK,
                "host",
                f"{u.email}: " + (", ".join(problems) if problems
                                  else "active, can enter, moderator"),
            ))
        return out

    def _check_registrants(self, event):
        from registrations.models import Registration

        owner = services.room_owner_for_event(event) or event
        with_access = list(
            event.registrations.filter(
                status__in=(Registration.Status.PAID, Registration.Status.COMPED)
            ).select_related("user__profile")
        )
        pending = event.registrations.filter(
            status=Registration.Status.AWAITING_PAYMENT
        ).count()
        blocked = [
            r.user.email
            for r in with_access
            if r.user and not services.can_enter(owner, r.user)
        ]
        out = [(
            OK, "registrants",
            f"{len(with_access)} with access, {pending} awaiting payment",
        )]
        if blocked:
            out.append((
                FAIL, "registrants", f"paid but cannot enter: {', '.join(blocked)}"
            ))
        return out

    def _check_token_window(self, event):
        ttl = settings.DAILY_TOKEN_TTL_MINUTES
        session = event.sessions.order_by("start_at").last()
        if session is None:
            return [(OK, "token window", f"flat TTL {ttl} min (no sessions)")]
        window_minutes = (
            (session.end_at + Event.JOIN_GRACE)
            - (session.start_at - Event.JOIN_PREOPEN)
        ).total_seconds() / 60
        if window_minutes <= ttl:
            return [(
                OK, "token window",
                f"{window_minutes:.0f} min window fits the {ttl} min flat TTL",
            )]
        return [(
            OK, "token window",
            f"{window_minutes:.0f} min window exceeds the {ttl} min flat TTL, "
            f"extended by token_exp_for() while the event is live",
        )]

    def _check_presence(self):
        try:
            daily.get_presence()
        except daily.DailyError as exc:
            return [(FAIL, "presence", str(exc))]
        return [(OK, "presence", "API reachable")]
