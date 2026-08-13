"""Seed disposable test *personas* — one per archetype — for the Web
Coordinator's "View as" tool. Idempotent; safe to re-run.

Personas are real (login-disabled) accounts flagged ``Profile.is_persona`` so
impersonating them is fully writable (actions land on throwaways, not real
members). Run: ``manage.py seed_personas``.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Profile

User = get_user_model()

# (slug, last_name, role, is_faculty, committee_slug, committee_role)
PERSONAS = [
    ("member", "Member", Profile.Role.MEMBER, False, None, None),
    ("pre-candidate", "Pre-Candidate", Profile.Role.PRE_CANDIDATE, False, None, None),
    ("candidate", "Candidate Analyst", Profile.Role.CANDIDATE, False, None, None),
    ("analyst", "Analyst", Profile.Role.ANALYST, False, None, None),
    ("scholar", "Scholar", Profile.Role.SCHOLAR, False, None, None),
    ("auditor", "Auditor", Profile.Role.EXTERNAL, False, None, None),
    ("faculty", "Faculty", Profile.Role.ANALYST, True, None, None),
    ("board-chair", "Board Chair", Profile.Role.ANALYST, False, "board", "chair"),
    ("pc", "Programming Committee", Profile.Role.ANALYST, False,
     "programming-committee", "member"),
]


class Command(BaseCommand):
    help = "Seed test personas for the 'View as' tool (idempotent)."

    def handle(self, *args, **opts):
        from committees.models import Committee

        created = updated = 0
        for slug, last, role, is_faculty, committee_slug, committee_role in PERSONAS:
            email = f"persona+{slug}@lacanschool.org"
            user, was_created = User.objects.get_or_create(
                email=email,
                defaults={"first_name": "Persona", "last_name": last, "is_active": True},
            )
            if was_created:
                user.set_unusable_password()
                user.first_name, user.last_name = "Persona", last
                user.save()
                created += 1
            else:
                updated += 1
            p = user.profile
            p.role = role
            p.is_faculty = is_faculty
            p.is_persona = True
            p.public = False
            p.save()

            if committee_slug:
                committee = Committee.objects.filter(slug=committee_slug).first()
                if committee is not None:
                    wg = committee.workgroup
                    if not wg.memberships.filter(user=user, end_date__isnull=True).exists():
                        from workgroups.models import WorkgroupMembership
                        WorkgroupMembership.objects.create(
                            workgroup=wg, user=user, role=committee_role,
                            start_date=timezone.localdate(),
                        )

        self.stdout.write(self.style.SUCCESS(
            f"Personas: {created} created, {updated} updated."
        ))
