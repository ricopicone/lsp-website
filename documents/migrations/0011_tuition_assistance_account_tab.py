"""Point the Tuition Assistance body at the Account tab (task #443).

Follows 0010. The Tuition tab was folded into a single **Account** tab in
task #439, so "My LSP Tuition page" / ``?tab=tuition`` reads stale — it
still lands correctly (the hub redirects the old querystring), but the copy
names a page that no longer exists. Two content changes beyond the rename:

- The Account page now carries a full statement (charges and payments on one
  running balance), so "installments and payment history" undersells it.
- Members can now report a payment or fee from before the website for the
  treasurer to review, which is exactly what the old "keep your own record"
  advice was compensating for. That advice stays, with the new route added.
"""

from django.db import migrations

SLUG = "tuition-assistance"

BODY = """\
Tuition supports the School and your formation within it. This page explains how tuition is paid and how to ask for assistance if you need it.

## Paying your tuition

Each academic year, record your tuition decision on your [My LSP Account page](/formation/?tab=account). You can pay the full year at once, spread it across installments, or skip the year, and the page keeps a record of the decision you chose and when.

- **Pay in full** in September, or pay in **installments** over the year, either in two payments (September and February) or monthly from September through May. No special authorization is needed to pay in installments.
- **Skip the year.** Your four years of tuition need not be consecutive, so you may skip a year and resume later. While skipping, you pay the regular per-event fee for seminars rather than the covered-by-tuition rate.

You can set up or change your plan and make payments any time on your [My LSP Account page](/formation/?tab=account), which also shows your statement: every charge and payment on your account, with a running balance.

If your payments fall short, you will receive a reminder to pay the balance; if tuition remains unpaid after reminders, the administrator raises the matter with the Board.

It remains each member's responsibility to keep their own record of tuition payments. If you find a payment or a fee from before this website that your account does not show, you can report it from your Account page and the Treasurer will review it.

## Requesting tuition assistance

If you have an exceptional situation, extreme hardship, or live in a country with different wages and costs of living, you can request tuition assistance from the Board. After discussing your situation with your advisor and agreeing on a plan:

1. Send your request to the [Treasurer](mailto:treasurer@lacanschool.org), describing your circumstances and suggesting the amount you can reasonably pay as a symbolic contribution toward your tuition.
2. The Treasurer shares your request with the rest of the Board, who discuss it at one of their next meetings (usually one to two months after you submit it).
3. After meeting, the Board responds to you through the Treasurer within two weeks.

A few things to keep in mind:

- Submit a tuition assistance request for each year in which you seek assistance.
- Keep your own record of your payments and of any exceptions the Board grants.
"""


def retarget(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    doc = Document.objects.filter(slug=SLUG).first()
    if doc is None:
        return
    doc.body = BODY
    doc.file = ""
    doc.save(update_fields=["body", "file"])


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0010_drop_yearend_reconciliation_sentence"),
    ]

    operations = [
        migrations.RunPython(retarget, migrations.RunPython.noop),
    ]
