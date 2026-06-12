"""Mint a dev-API bearer token for a user.

    uv run python manage.py create_devapi_token --user dr@ricopic.one --label "rico laptop"

Prints the raw token **once** — it is not recoverable afterwards. Put it in the
MCP server's environment as ``LSP_DEVAPI_TOKEN`` (see mcp/README.md). The bound
user must hold the Web Coordinator or Web Developer staff role (or be a
superuser) for the token to authorize anything.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from devapi.models import DevApiToken

User = get_user_model()


class Command(BaseCommand):
    help = "Create a dev-API bearer token for a user (prints the raw token once)."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="User email.")
        parser.add_argument("--label", required=True, help="Where the token lives.")

    def handle(self, *args, **opts):
        try:
            user = User.objects.get(email__iexact=opts["user"])
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with email {opts['user']!r}.") from exc

        token, raw = DevApiToken.issue(user, opts["label"])

        self.stdout.write(self.style.SUCCESS(f"Created token #{token.pk} for {user.email}."))
        self.stdout.write("")
        self.stdout.write("  " + self.style.WARNING(raw))
        self.stdout.write("")
        self.stdout.write(
            "Copy it now — it will not be shown again. Set it as LSP_DEVAPI_TOKEN "
            "for the MCP server."
        )
