"""Rewrite the Tuition Assistance body for clarity and accuracy.

Follows 0008 (which de-PDF'd the document). This pass reworks the copy to:

- open with a lead paragraph instead of the bare "For all members" heading,
  and split into two real sections ("Paying your tuition" / "Requesting
  tuition assistance");
- describe the yearly tuition **decision** as actually built on the My LSP
  Tuition page (pay in full, installments, or **skip the year**), with links
  to that page (/formation/?tab=tuition);
- link "the Treasurer" to a role address (treasurer@lacanschool.org) now that
  the named office holder has been removed;
- keep the live {{ annual_tuition }} figure.

Member-facing copy uses commas, not em dashes (house style).
"""

from django.db import migrations

SLUG = "tuition-assistance"

BODY = """\
Tuition supports the School and your formation within it. This page explains how tuition is paid and how to ask for assistance if you need it.

## Paying your tuition

Each academic year, record your tuition decision on your [My LSP Tuition page](/formation/?tab=tuition). You can pay the full year at once, spread it across installments, or skip the year, and the page keeps a record of the decision you chose and when.

- **Pay in full** in September, or pay in **installments** over the year, either in two payments (September and February) or monthly from September through May. No special authorization is needed to pay in installments.
- **Skip the year.** Your four years of tuition need not be consecutive, so you may skip a year and resume later. While skipping, you pay the regular per-event fee for seminars rather than the covered-by-tuition rate.

You can set up or change your plan and make payments any time on your [My LSP Tuition page](/formation/?tab=tuition), which also shows your installments and payment history.

At the end of the academic year, in June, the administrator confirms that everyone paying tuition has paid the full annual amount of {{ annual_tuition }}. If your payments fall short, you will receive a reminder to pay the balance; if tuition remains unpaid after reminders, the administrator raises the matter with the Board.

It remains each member's responsibility to keep their own written record of tuition payments.

## Requesting tuition assistance

If you have an exceptional situation, extreme hardship, or live in a country with different wages and costs of living, you can request tuition assistance from the Board. After discussing your situation with your advisor and agreeing on a plan:

1. Send your request to the [Treasurer](mailto:treasurer@lacanschool.org), describing your circumstances and suggesting the amount you can reasonably pay as a symbolic contribution toward your tuition.
2. The Treasurer shares your request with the rest of the Board, who discuss it at one of their next meetings (usually one to two months after you submit it).
3. After meeting, the Board responds to you through the Treasurer within two weeks.

A few things to keep in mind:

- Submit a tuition assistance request for each year in which you seek assistance.
- Keep your own written record of your payments and of any exceptions the Board grants.
"""


def reword(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    doc = Document.objects.filter(slug=SLUG).first()
    if doc is None:
        return
    doc.body = BODY
    doc.file = ""
    doc.save(update_fields=["body", "file"])


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0008_convert_tuition_assistance_to_html"),
    ]

    operations = [
        migrations.RunPython(reword, migrations.RunPython.noop),
    ]
