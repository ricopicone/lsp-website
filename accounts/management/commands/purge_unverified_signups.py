"""Delete self-signups that never confirmed their email address (task #471).

Verification stops a bot account from being *usable*; it does not stop the row
being created. Without this sweep the table still fills with abandoned
never-confirmed accounts.

Safety rests on the grandfathering migration: every account that existed
before verification shipped carries an ``email_verified_at``, so an
administratively deactivated member can never match this query.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User

DEFAULT_AGE_DAYS = 7


class Command(BaseCommand):
    help = "Delete never-verified signups older than --days (default 7)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=DEFAULT_AGE_DAYS,
            help="Age in days past which an unconfirmed signup is deleted.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List what would be deleted without deleting it.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = User.objects.filter(
            is_active=False,
            profile__email_verified_at__isnull=True,
            date_joined__lt=cutoff,
        )

        count = stale.count()
        if not count:
            self.stdout.write("No unverified signups to purge.")
            return

        for user in stale:
            self.stdout.write(
                f"  {user.email} (joined {user.date_joined:%Y-%m-%d})"
            )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Would delete {count}."))
            return

        stale.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} unverified signups."))
