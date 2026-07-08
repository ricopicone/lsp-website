from django.db import migrations


def forward(apps, schema_editor):
    Cartel = apps.get_model("cartels", "Cartel")
    for cartel in Cartel.objects.select_related("workgroup__proposal").all():
        proposal = cartel.workgroup.proposal
        status = proposal.status
        if status == "open":
            cartel.registration_status = "registered"
        elif status == "proposed":
            cartel.registration_status = "submitted"
            proposal.status = "open"
            proposal.save(update_fields=["status"])
            cartel.workgroup.landing_visibility = "members"
            cartel.workgroup.save(update_fields=["landing_visibility"])
        elif status == "declined":
            cartel.registration_status = "forming"
            proposal.status = "open"
            proposal.save(update_fields=["status"])
            cartel.workgroup.landing_visibility = "members"
            cartel.workgroup.save(update_fields=["landing_visibility"])
        else:  # archived
            cartel.registration_status = "registered"
        cartel.save(update_fields=["registration_status"])


def backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("cartels", "0008_cartel_registration_status_cartelquestion")]
    operations = [migrations.RunPython(forward, backward)]
