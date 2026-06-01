"""Move cartel governance onto the generic Workgroup layer.

Copies each cartel's status/reviewer trail into a ``WorkgroupProposal`` and its
invitations / join-requests into ``WorkgroupInvitation`` / ``WorkgroupJoinRequest``
(both now FK'd to the workgroup, not the cartel). Idempotent and an empty-db
no-op; the legacy fields/models are dropped in the next migration (0007).
"""

from django.db import migrations


def copy_to_generic(apps, schema_editor):
    Cartel = apps.get_model("cartels", "Cartel")
    CartelInvitation = apps.get_model("cartels", "CartelInvitation")
    CartelJoinRequest = apps.get_model("cartels", "CartelJoinRequest")
    WorkgroupProposal = apps.get_model("workgroups", "WorkgroupProposal")
    WorkgroupInvitation = apps.get_model("workgroups", "WorkgroupInvitation")
    WorkgroupJoinRequest = apps.get_model("workgroups", "WorkgroupJoinRequest")

    for cartel in Cartel.objects.all():
        WorkgroupProposal.objects.get_or_create(
            workgroup_id=cartel.workgroup_id,
            defaults={
                "proposed_by_id": cartel.generator_id,
                "status": cartel.status,
                "reviewed_by_id": cartel.reviewed_by_id,
                "reviewed_at": cartel.reviewed_at,
                "review_note": cartel.review_note,
            },
        )

    for inv in CartelInvitation.objects.all():
        WorkgroupInvitation.objects.get_or_create(
            workgroup_id=inv.cartel.workgroup_id,
            invited_user_id=inv.invited_user_id,
            defaults={
                "created_by_id": inv.cartel.generator_id,
                "accepted_at": inv.accepted_at,
            },
        )

    for req in CartelJoinRequest.objects.all():
        WorkgroupJoinRequest.objects.get_or_create(
            workgroup_id=req.cartel.workgroup_id,
            applicant_id=req.applicant_id,
            status=req.status,
            defaults={
                "message": req.message,
                "decided_by_id": req.decided_by_id,
                "decided_at": req.decided_at,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("cartels", "0005_cartel_coordinator_feedback_alter_cartel_review_note_and_more"),
        ("workgroups", "0008_workgroupproposal_workgroupinvitation_and_more"),
    ]

    operations = [
        migrations.RunPython(copy_to_generic, migrations.RunPython.noop),
    ]
