"""Repair receipt bell rows that point at a page they can't reach.

``payments:thanks`` is public and deliberately 404s registration payments, but
receipt notifications linked every payment there — so a registration receipt's
bell row landed on a not-found page. The URL is denormalized onto the row, so
already-sent rows need rewriting to the registration confirmation page.
"""

import re

from django.db import migrations

THANKS = re.compile(r"^/payments/(\d+)/thanks/$")


def repair(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Payment = apps.get_model("payments", "Payment")

    for note in Notification.objects.filter(category="payment_receipt"):
        match = THANKS.match(note.url)
        if not match:
            continue
        payment = Payment.objects.filter(pk=int(match.group(1))).first()
        if payment is None or not payment.registration_id:
            continue
        note.url = f"/registrations/{payment.registration_id}/confirmation/"
        note.save(update_fields=("url",))


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0010_alter_notification_category"),
        ("payments", "0022_balancereminder"),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
