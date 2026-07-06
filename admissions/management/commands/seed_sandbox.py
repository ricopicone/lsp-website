"""Build a training sandbox for the admissions workflow.

Creates a self-contained cast of **personas owned by a trainee** plus sample
applications at two stages, so a coordinator can walk the whole flow —
acknowledge, invite interviewers, watch the introductions, decide — and *see
every email*, because all the cast's mail is redirected to the trainee
(tagged ``[SANDBOX]``) and never reaches a real member. The cast is all
personas, so the interview invitation stays within the sandbox.

    manage.py seed_sandbox --owner coordinator@example.org
    manage.py seed_sandbox --owner coordinator@example.org --reset

``--reset`` clears that trainee's existing sandbox first (repeatable runs).
The trainee needs the Applications Coordinator role (or superuser) to reach
the console, and can impersonate the personas to drive the analyst side.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Profile, User
from admissions.models import Application, ApplicationInterview
from availability import services as avail
from availability.models import AnalystFunction


class Command(BaseCommand):
    help = "Seed a per-trainee admissions training sandbox (personas + sample apps)."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True, help="Trainee's email.")
        parser.add_argument("--reset", action="store_true",
                            help="Clear this trainee's sandbox first.")

    def handle(self, *args, **opts):
        owner = User.objects.filter(email__iexact=opts["owner"]).first()
        if owner is None:
            raise CommandError(f"No user with email {opts['owner']!r}.")
        slug = slugify(owner.email.split("@")[0]) or str(owner.pk)

        if opts["reset"]:
            self._reset(owner)

        # --- the cast (personas owned by the trainee) ---
        analyst_yes = self._persona(owner, slug, "analyst-available",
                                    "Sandbox Analyst", "(available)", Profile.Role.ANALYST)
        analyst_unknown = self._persona(owner, slug, "analyst-unknown",
                                        "Sandbox Analyst", "(unknown)", Profile.Role.ANALYST)
        analyst_no = self._persona(owner, slug, "analyst-unavailable",
                                   "Sandbox Analyst", "(unavailable)", Profile.Role.ANALYST)
        interviews_fn = AnalystFunction.objects.get(slug="application-interviews")
        advisor_fn = AnalystFunction.objects.get(slug="advisor")
        avail.set_availability(analyst_yes.profile, interviews_fn, "yes")
        avail.set_availability(analyst_yes.profile, advisor_fn, "yes")
        avail.set_availability(analyst_no.profile, interviews_fn, "no")
        # analyst_unknown left without rows → Unknown.

        applicant1 = self._persona(owner, slug, "applicant-one", "Sandbox Applicant",
                                   "One", Profile.Role.PROSPECTIVE_APPLICANT)
        applicant2 = self._persona(owner, slug, "applicant-two", "Sandbox Applicant",
                                   "Two", Profile.Role.PROSPECTIVE_APPLICANT)

        # --- sample applications at two stages ---
        self._application(applicant1, Application.Status.SUBMITTED)
        app2 = self._application(applicant2, Application.Status.INTERVIEWING)
        app2.interviewers_invited_at = timezone.now()
        app2.save(update_fields=["interviewers_invited_at"])
        # Two completed interviews on app2 → ready for the coordinator to decide.
        for analyst in (analyst_yes, analyst_unknown):
            ApplicationInterview.objects.get_or_create(
                application=app2, interviewer=analyst,
                defaults={
                    "agreed_at": timezone.now(),
                    "completed_at": timezone.localdate(),
                    "report": "Sandbox interview report — a thoughtful candidate.",
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nSandbox ready for {owner.email}."
        ))
        self.stdout.write(
            "  App 1 (Submitted): practice Acknowledge then Invite — the invite "
            "reaches the sandbox analysts only, and every email comes to you.\n"
            "  App 2 (Interviewing, both reports in): practice the decision.\n"
            f"  Cast: {analyst_yes.email}, {analyst_unknown.email}, "
            f"{analyst_no.email}, {applicant1.email}, {applicant2.email}\n"
            "  Console: /admin-tools/applications/  (needs the Applications "
            "Coordinator role or superuser). Impersonate a persona to drive the "
            "analyst side."
        )

    # -- helpers ----------------------------------------------------------

    def _email(self, slug, key):
        # .invalid never resolves; delivery is redirected to the owner anyway.
        return f"sandbox-{slug}-{key}@lacanschool.invalid"

    def _persona(self, owner, slug, key, first, last, role) -> User:
        email = self._email(slug, key)
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email=email, first_name=first, last_name=last)
        user.set_unusable_password()
        user.first_name, user.last_name = first, last
        user.save()
        p = user.profile
        p.is_persona = True
        p.persona_owner = owner
        p.role = role
        p.standing = Profile.Standing.ACTIVE
        p.public = False
        p.save()
        return user

    def _application(self, applicant, status) -> Application:
        app, _ = Application.objects.get_or_create(
            applicant=applicant,
            defaults={
                "track": Application.Track.ANALYST,
                "background": Application.Background.CLINICAL,
                "eligibility_note": "PhD, Clinical Psychology — SANDBOX",
                "letter_of_intent": "Sandbox application for training the "
                "admissions workflow.",
                "status": status,
                "submitted_at": timezone.now(),
            },
        )
        if app.status != status:
            app.status = status
            app.save(update_fields=["status"])
        return app

    def _reset(self, owner):
        apps = Application.objects.filter(applicant__profile__persona_owner=owner)
        n_apps = apps.count()
        apps.delete()  # cascades interviews
        n_users = User.objects.filter(
            profile__persona_owner=owner, profile__is_persona=True
        ).delete()
        self.stdout.write(f"Reset: removed {n_apps} application(s) and {n_users[0]} object(s).")
