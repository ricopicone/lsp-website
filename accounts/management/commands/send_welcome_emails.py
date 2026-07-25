"""Send the one-time launch welcome email to members.

Dry-run by default: lists who would be welcomed and sends nothing. Pass
``--commit`` to send. Each delivery records a ``WelcomeEmail`` row, so
re-runs skip everyone already welcomed (and pick up members added since).

Skips inactive accounts and training-sandbox personas. ``--only`` limits a
run to specific addresses, e.g. a test send to yourself before the batch.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from accounts.emails import send_welcome
from accounts.models import WelcomeEmail
from payments.sending import ThrottledSender

User = get_user_model()


class Command(BaseCommand):
    help = "Send the launch welcome email to members (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually send. Without it, just report who would be welcomed.",
        )
        parser.add_argument(
            "--only",
            default="",
            help="Comma-separated email addresses: restrict the run to these "
            "accounts (for a test send).",
        )

    def handle(self, *args, **opts):
        qs = (
            User.objects.filter(is_active=True, welcome_email__isnull=True)
            .exclude(profile__is_persona=True)
            .order_by("email")
        )
        if opts["only"]:
            wanted = [e.strip() for e in opts["only"].split(",") if e.strip()]
            q = Q()
            for email in wanted:
                q |= Q(email__iexact=email)
            qs = qs.filter(q)

        users = list(qs)
        if not users:
            self.stdout.write("Nobody to welcome (all sent, or no matches).")
            return

        if not opts["commit"]:
            for user in users:
                self.stdout.write(f"would send: {user.email}")
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {len(users)} welcome email(s) NOT sent. "
                    "Re-run with --commit to send."
                )
            )
            return

        sender = ThrottledSender()
        sent = failed = 0
        for user in users:
            try:
                sender.send(send_welcome, user)
            except Exception as exc:  # noqa: BLE001 — keep the batch going
                failed += 1
                self.stderr.write(f"FAILED {user.email}: {exc}")
                continue
            WelcomeEmail.objects.create(user=user)
            sent += 1
            self.stdout.write(f"sent: {user.email}")
        self.stdout.write(self.style.SUCCESS(f"Welcomed {sent}; {failed} failed."))
