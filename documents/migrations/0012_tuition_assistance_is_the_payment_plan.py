"""Tuition assistance IS the payment plan application (task #491).

Follows 0011. The document still described two processes: a self-service
installment plan needing "no special authorization", and a separate hardship
request emailed to the Treasurer, shared with the Board, proposing "the amount
you can reasonably pay as a symbolic contribution". Neither half is accurate:

- They are one process. A member asking for assistance is applying for a
  payment plan, and that application is filed and decided on the site
  (``TuitionPlanApplication`` → the Board's queue at /admin-tools/tuition-plans/).
- Board approval is exactly what an installment plan now needs, so "no special
  authorization is needed" is backwards.
- An approved plan is the full annual tuition across 2 or 9 installments. The
  ledger has no reduced-obligation or waiver mechanism, so the copy must not
  imply the Board sets a lower total.

The stale copy is what led a Board member to think assistance requests were a
separate Board-wide email process. The document title stays "Tuition
Assistance" — members and existing links know it by that name, and the body
now states the equivalence.

Member-facing copy uses commas, not em dashes (house style).
"""

from django.db import migrations

SLUG = "tuition-assistance"

BODY = """\
Tuition supports the School and your formation within it. This page explains how tuition is paid, and how to apply for a payment plan if paying the year at once is not workable for you.

## Paying your tuition

Each academic year, record your tuition decision on your [My LSP Account page](/formation/?tab=account). You can pay the full year at once, apply to the Board for a payment plan, or skip the year, and the page keeps a record of the decision you chose and when.

- **Pay in full** in September. The annual tuition is {{ annual_tuition }}.
- **Apply for a payment plan** if paying the year at once is not workable, whether because of an exceptional situation, hardship, or living in a country with different wages and costs of living. See "Applying for a payment plan" below.
- **Skip the year.** Your four years of tuition need not be consecutive, so you may skip a year and resume later. While skipping, you pay the regular per-event fee for seminars rather than the covered-by-tuition rate.

Your [My LSP Account page](/formation/?tab=account) also shows your statement: every charge and payment on your account, with a running balance.

If your payments fall short, you will receive a reminder to pay the balance; if tuition remains unpaid after reminders, the administrator raises the matter with the Board.

It remains each member's responsibility to keep their own record of tuition payments. If you find a payment or a fee from before this website that your account does not show, you can report it from your Account page and the Treasurer will review it.

## Applying for a payment plan

A payment plan spreads the year's tuition across the year. It is what the School has also called tuition assistance: one process, applied for and recorded on the site.

Before applying, discuss your situation with your advisor and agree on a plan. Then:

1. On your [My LSP Account page](/formation/?tab=account), choose "I want to apply to the Board for a payment plan" and tell the Board briefly about your circumstances.
2. The Treasurer is notified, and the Board discusses your application at one of their next meetings, usually one to two months after you apply.
3. You are notified of the Board's decision on the site and by email.

While your application is pending, your tuition decision counts as made, so seminars you register for stay covered at the tuition rate.

If the Board approves your application, choose your schedule on your Account page: two payments, in September and February, or nine monthly payments from September through May. The installments together come to the year's full tuition, and you can pay each one from that page.

If the Board is unable to approve your application, your tuition decision opens again so you can choose to pay in full or skip the year.

A few things to keep in mind:

- Apply for each year in which you need a payment plan.
- Keep your own record of your payments and of any exceptions the Board grants.
"""


def rewrite(apps, schema_editor):
    Document = apps.get_model("documents", "Document")
    doc = Document.objects.filter(slug=SLUG).first()
    if doc is None:
        return
    doc.body = BODY
    doc.file = ""
    doc.save(update_fields=["body", "file"])


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0011_tuition_assistance_account_tab"),
    ]

    operations = [
        migrations.RunPython(rewrite, migrations.RunPython.noop),
    ]
