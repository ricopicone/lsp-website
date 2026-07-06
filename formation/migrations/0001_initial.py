import admissions.storage
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        # ``Advancement`` was created by ``admissions.0002_advancement`` on the
        # ``admissions_advancement`` table. This migration moves it into the
        # ``formation`` app in Django's state only — the table is untouched.
        ("admissions", "0002_advancement"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Advancement",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "kind",
                            models.CharField(
                                choices=[
                                    ("palimpsest", "Palimpsest (Precandidate → Candidate)"),
                                    (
                                        "passage",
                                        "Passage / Traversée (Candidate → Analyst / Scholar)",
                                    ),
                                ],
                                default="palimpsest",
                                max_length=12,
                            ),
                        ),
                        ("from_role", models.CharField(max_length=32)),
                        (
                            "statement",
                            models.TextField(
                                help_text="The member's statement — why they are ready for this step."
                            ),
                        ),
                        (
                            "palimpsest",
                            models.FileField(
                                blank=True,
                                help_text="Optional written palimpsest / supporting document (private).",
                                storage=admissions.storage.cv_storage,
                                upload_to="palimpsest/%Y/",
                            ),
                        ),
                        (
                            "recommendation",
                            models.TextField(
                                blank=True,
                                help_text="The Advisor's recommendation to the Meeting.",
                            ),
                        ),
                        (
                            "presented_at",
                            models.DateField(
                                blank=True,
                                help_text="Date the Advisor presented the demande to the Meeting of the Analysts; blank = not yet presented.",
                                null=True,
                            ),
                        ),
                        (
                            "last_reminded_at",
                            models.DateTimeField(
                                blank=True,
                                help_text="When the Advisor was last reminded to present (reminder cron).",
                                null=True,
                            ),
                        ),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    (
                                        "requested",
                                        "Requested — awaiting advisor's recommendation",
                                    ),
                                    ("presented", "Presented to the Meeting of the Analysts"),
                                    ("approved", "Approved"),
                                    ("declined", "Not approved"),
                                    ("withdrawn", "Withdrawn"),
                                ],
                                db_index=True,
                                default="requested",
                                max_length=12,
                            ),
                        ),
                        (
                            "requested_at",
                            models.DateTimeField(default=django.utils.timezone.now),
                        ),
                        ("decided_at", models.DateTimeField(blank=True, null=True)),
                        ("decision_note", models.TextField(blank=True)),
                        (
                            "staff_notes",
                            models.TextField(blank=True, help_text="Internal reviewer notes."),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "advisor",
                            models.ForeignKey(
                                blank=True,
                                help_text="The member's Advisor at the time of the demande.",
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="advancements_advised",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "decided_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="advancement_decisions",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "member",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="advancements",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "admissions_advancement",
                        "ordering": ("-requested_at",),
                        "constraints": [
                            models.UniqueConstraint(
                                condition=models.Q(("status__in", ("requested", "presented"))),
                                fields=("member",),
                                name="admissions_one_open_advancement_per_member",
                            )
                        ],
                    },
                ),
            ],
            database_operations=[],  # table already exists — no SQL
        ),
    ]
