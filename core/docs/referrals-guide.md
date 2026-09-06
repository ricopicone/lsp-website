# Referral Coordinator — a guide

This admin area runs the Find-an-Analyst referral process on the site. It
follows the same five steps you've always used—the site just keeps the
records, does the assembly, and sends what you tell it to send.

1. Someone submits the **Find an Analyst** form on the public site.
2. They receive your **acknowledgment** (the "received and being processed"
   reply).
3. The request—**with the requester's name and email withheld**—goes out to
   every active clinician on the referral list, individually.
4. Clinicians who are available say so on the site, with one checkbox; their
   responses collect on the request's page, connected to the referral number
   automatically. A clinician who is not available lets the request pass,
   and one who checked the box can uncheck it later to withdraw.
5. You send the **follow-up**: the site drafts it from your wording, with
   each available clinician's practice details filled in, and you adjust
   anything before it goes.

Nothing here removes your discretion. Every step can run automatically or
wait for your review (see **Settings**), every message is your own editable
wording (see **Templates**), and you can always write to any requester or
clinician directly from your own mailbox instead—the site doesn't mind.

## The Requests tab

Every form submission appears here as a tracked request with a date-based
reference number—**26-0612** for a request received June 12, 2026, with
**26-0612-2** and so on if several arrive the same day. That's "the number
of the referral" and it's what clinicians see; they never see the
requester's name. The status column shows
where each request is in the process:

- **New**—just arrived; no acknowledgment sent yet.
- **Acknowledged**—the requester has your process reply.
- **Distributed**—sent to the referral list; responses are collecting.
- **Replied**—you've sent the follow-up with clinician names.
- **Closed**—done. (You can close a request at any point, and reopen it.)

The filter defaults to **Open** (everything not yet replied or closed).

## A request's page

Click a reference to open the request. You'll find everything the requester
shared, the three sending steps with their buttons, the clinician responses
as they arrive, and a private notes box only you can see.

- **Edit**—on the Request box. Change anything the requester submitted
  before it goes out: most often to take their own name out of the
  description, since clinicians receive everything except the name and email
  fields. What you save here is what the distribution email carries and what
  the clinicians' respond page shows, and each edit leaves a line in the
  notes. A held request can be edited before you release it.
- **Send acknowledgment**—sends your process reply (or resends it).
- **Distribute**—opens a preview of the anonymized request exactly as each
  *active* clinician on the referral list will receive it, with the
  respond-by date it will name. Send from there, or go back and edit the
  request first. Each clinician is emailed individually, with a link to
  respond on the site.
- **Record a response manually**—the escape hatch for a clinician who
  replies to you by email or in person: pick their name and their details
  flow into the follow-up like any other response. A clinician who is not
  available simply doesn't respond, so there is no availability to record.
  **Remove** on a response takes it back off the request.
- **Send an addendum**—for something that changed after the request went
  out, such as the person turning out to need a sliding scale. Choose
  whether it reaches only the clinicians the request already went to or
  everyone on the list, and move the response deadline if the change
  deserves more time. What you write is emailed and also shown on the
  clinicians' respond page, so it stays with the request instead of living
  in one email. Requests distributed before this feature existed have no
  recorded recipient list, so those can only go to everyone.
- **Compose follow-up**—opens the drafted reply. The site picks the right
  variant (no responses, a single clinician, several clinicians) and fills
  in each available clinician's practice details. Edit anything—the
  message sends exactly as it appears in the box.

## The Referral list tab

The clinicians who receive requests. Their practice details—name, title or
credentials, the email and phone they want analysands to use, website—come
from **their own profile on the site**, which they maintain themselves, so
there's no list of contact info for you to keep current.

- **Add to list**—pick any member. Depending on your Settings, the New
  Member Instructions are sent automatically or wait for you.
- **Edit**—see exactly what a requester would receive for this clinician,
  and set an **override**: text that's sent verbatim in place of the
  profile-built block, for any case where the profile isn't right.
- **Send/Resend instructions**—the New Member Instructions, anytime.
- **Deactivate**—takes a clinician off distributions without losing their
  record; reactivate whenever.

## The Templates tab

Every message the process sends, editable: the acknowledgment, the
distribution email, the three follow-up variants, and the New Member
Instructions. Placeholders in braces—like `{name}` or `{clinicians}`—are
filled in when the message is sent; each template's edit page lists the
placeholders available to it. Anything else you write is sent exactly as
written, so edit freely.

## The Settings tab

Each sending step has its own switch:

- **Automatic**—the step fires on its own (the acknowledgment right after
  the form is submitted; distribution on arrival; the follow-up when the
  response window closes; onboarding when you add a clinician).
- **Review first**—the site prepares everything and waits for you to press
  the button.

Change these anytime, per step. The **response window** (how long
clinicians have to respond, shown in the distribution email) and the
**retention period** are here too. The window counts from the day the
request was *received*, not the day you press Distribute, so a delay in
processing doesn't lengthen the requester's wait: received on the 24th with
a ten-day window, responses are due at the end of the day on the 3rd. If a
request is distributed so late that the date has passed, clinicians are
given three days instead. Either way the Distribute page shows the date and
lets you change it for that request.

## Privacy

Requests are visible only to the Referral Coordinator—not to general staff.
Clinicians receiving a distribution see everything the requester shared
*except* their name and email; those stay with you until your follow-up
puts the choice in the requester's hands. After the retention period
(Settings), a finished request's identifying details are automatically
redacted, keeping only the non-identifying record.

## Held submissions and junk

Some submissions are automated. In July 2026 a bot filled every field on the
Find-an-Analyst form with random text, and because acknowledgment and
distribution were both set to automatic, it was acknowledged to a stranger's
address and sent to the whole referral list before anyone saw it.

Two things now sit in front of that.

Submissions that are obviously automated are dropped before they ever become
a request. You never see them. The dashboard shows a count of how many were
blocked in the last 30 days, so you can tell the screen is working.

Submissions that only *look* suspicious are **held**. A held request is on
the dashboard behind the "held for review" badge, and it rings your
notification bell. Nothing has been sent: no acknowledgment to the requester,
no message to the referral list. You have two buttons:

1. **Release** puts it back into the normal workflow, exactly as if it had
   never been held. If acknowledgment and distribution are set to automatic,
   they happen the moment you release it.
2. **Mark as junk** closes it out. Junk requests are hidden from the open
   list.

If a held request sits unreviewed for a few days, you get an email about it.
That threshold is the **held escalation days** setting.

The screen is deliberately cautious, so it will sometimes hold a real
request: an unusual name or a very short description can trip it. That is
why it holds rather than deletes. **Mark as junk** is also available on any
request, for the occasional submission that is clearly not a real referral
but was written by a person and so could never be caught automatically.

## If something doesn't fit the process

That's expected—the process serves the singular case, not the other way
around. Reply to any inquiry from your own mailbox (replies to the
notification emails reach the requester or you correctly), record things
manually, flip a step to review-first, or simply leave a request open as
long as it needs. The site keeps the record; you keep the judgment.
