"""Send a keyed batch announcement email to members.

Mirrors ``send_welcome_emails``: dry-run by default, ``--commit`` to send,
``--only`` for a test send, throttled, one ``AnnouncementEmail`` row per
(user, key) so re-runs skip everyone already sent. Campaigns live in
``accounts.emails.ANNOUNCEMENTS``.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.emails import ANNOUNCEMENTS, send_announcement
from accounts.models import AnnouncementEmail
from payments.sending import ThrottledSender

User = get_user_model()


class Command(BaseCommand):
    help = "Send a keyed announcement email to members (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--key", required=True,
            help=f"Campaign key: one of {', '.join(sorted(ANNOUNCEMENTS))}.",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually send. Without it, just report who would get it.",
        )
        parser.add_argument(
            "--only", default="",
            help="Comma-separated emails: restrict the run (for a test send).",
        )

    def handle(self, *args, **opts):
        key = opts["key"]
        if key not in ANNOUNCEMENTS:
            raise CommandError(
                f"Unknown key {key!r}; known: {', '.join(sorted(ANNOUNCEMENTS))}"
            )

        qs = (
            User.objects.filter(is_active=True)
            .exclude(profile__is_persona=True)
            .exclude(announcement_emails__key=key)
            .order_by("email")
        )
        if opts["only"]:
            q = Q()
            for email in [e.strip() for e in opts["only"].split(",") if e.strip()]:
                q |= Q(email__iexact=email)
            qs = qs.filter(q)

        users = list(qs)
        if not users:
            self.stdout.write("Nobody to send to (all sent, or no matches).")
            return

        if not opts["commit"]:
            for user in users:
                self.stdout.write(f"would send: {user.email}")
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(users)} announcement email(s) NOT sent "
                    f"({key}). Re-run with --commit to send."
                )
            )
            return

        sender = ThrottledSender()
        sent = failed = 0
        for user in users:
            try:
                sender.send(send_announcement, user, key)
            except Exception as exc:  # noqa: BLE001 — keep the batch going
                failed += 1
                self.stderr.write(f"FAILED {user.email}: {exc}")
                continue
            AnnouncementEmail.objects.create(user=user, key=key)
            sent += 1
            self.stdout.write(f"sent: {user.email}")
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} ({key}); {failed} failed."))
