"""Convert the Tuition Assistance document from a served PDF to inline HTML.

The source PDF embedded soon-to-be-stale details — named office holders
("the Treasurer (currently Joseph Scalia III)", "LSP's administrator
(currently Shanna Carlson de la Torre)"), a hard-coded $2,000 figure, and the
old Wix payment URL. Holding the content as markdown lets it stay current:
names are genericized to the roles, the amount is the live
``{{ annual_tuition }}`` token (sourced from the current TuitionPeriod), and
the link points at the on-site tuition page.

Clearing ``file`` stops the site serving the old PDF (the download view 404s
without a file). The orphaned S3 object is left in the private bucket, where
it is unreachable except through the app.
"""

from django.db import migrations

SLUG = "tuition-assistance"

BODY = """\
### For all members

1. Tuition can be paid in full in September, or in installments over the course of the year until the following June.
2. The website is already set up for you to make a payment in full or in installments, on the [tuition page](/tuition/).
3. No special authorization is required for paying a full tuition in installments.
4. At the end of the academic year, in June, the administrator will check to make sure that everyone who is paying tuition has made payments totaling {{ annual_tuition }}. If someone comes up short, they will email the individual to remind them to pay the remaining balance.
5. If despite reminders tuition remains unpaid, the administrator will escalate the matter with the Board.
6. It is a member's responsibility to keep a written record of their tuition payments.

### For members with exceptional cases, extreme hardship, or living in countries with different wages and costs of living

1. After discussing your situation with your advisor and coming up with a plan, you should directly address any request for tuition assistance to the Board. Such a request needs to be sent to the Treasurer detailing your circumstances and with a suggestion of the amount you can reasonably pay as a symbolic contribution towards your tuition.
2. The Treasurer will share your email with the rest of the Board, and the Board will discuss your request at one of their following meetings (anywhere from 1 to 2 months from when you submit your request).
3. After meeting, the Board will respond to your request via the Treasurer within two weeks.
4. Please note that tuition assistance requests should be submitted each year in which you seek tuition assistance.
5. It is your responsibility to keep a written record of your payments as well as the exceptions granted by the Board.
"""


def convert(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    doc = Document.objects.filter(slug=SLUG).first()
    if doc is None:
        return
    doc.body = BODY
    doc.file = ""
    doc.save(update_fields=["body", "file"])


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0007_document_body_alter_document_file"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop),
    ]
