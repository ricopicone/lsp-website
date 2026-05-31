# LSP Website — Operations runbook

Recipes for the Web Coordinator. Each is one-shot or low-frequency; the
goal is to have the steps written down so a successor (or you in six
months) can do them without re-discovering.

## Bulk-import members

The bulk importer (`USR-3`) lives at `accounts/management/commands/import_users.py`.

### Prepare the CSV

Columns (only `email` is required; rest optional):

| Column | Notes |
|---|---|
| `email` | required; unique; login identifier |
| `first_name`, `last_name` | optional |
| `role` | `prospective_applicant`, `student`, `pre_candidate`, `candidate`, `analyst`, `scholar`, `pre_candidate_scholar`, `candidate_scholar`, `member`, `external` |
| `is_faculty` | `true`/`false`/`yes`/`no`/`1`/`0` |
| `notes` | free-text, staff-only |
| `bio`, `credentials`, `languages_spoken`, `location`, `phone`, `public_email`, `pronouns`, `year_joined` | optional profile fields |

See `docs/members-import-template.csv` for a sample.

Roles map directly to `Profile.role` values; unknown columns are
rejected up-front. Email matching is case-insensitive (dedupes).
**There is no `tuition_paying` column** — tuition is now a per-year
decision (`payments.TuitionEnrollment`), set by the member or treasurer,
not on import.

### Dry-run, then import

```
# On the EC2 host
scp ./members.csv ec2-user@app:/tmp/members.csv
ssh lsp 'sg docker -c "docker cp /tmp/members.csv lsp-website-web-1:/tmp/members.csv && docker exec lsp-website-web-1 python manage.py import_users /tmp/members.csv --dry-run"'

# If clean, drop --dry-run:
ssh lsp 'sg docker -c "docker exec lsp-website-web-1 python manage.py import_users /tmp/members.csv"'
```

Each new user is created with an **unusable password**. They set one via
the password-reset flow (once SES production access lands and they get a
welcome email; for now, only verified test recipients reliably receive
mail).

To **update** existing users instead of skipping them: add `--update`.

## Set up an event (admin)

Most event creation should go through the Django admin:

1. `/admin/events/event/add/` — fill in title, slug, type, dates, format.
   For online events, put the Zoom link in `access_info` (released only
   to PAID/COMPED registrants).
2. Add Sessions inline (or use the `generate_sessions` management command
   for recurring schedules).
3. Add PriceTiers inline. For a single $100 tier for everyone, set
   audience=All, base_amount=100.00.
4. Set `status=open` and `published=True` to make registration live.

## Seed an event from a script

For the Swales & Hook pilot, we created the row via a one-shot script.
Pattern (run via `ssh lsp 'sg docker -c "docker exec -i lsp-website-web-1 python -"' < /tmp/seed.py`):

```python
import django; django.setup()
from datetime import date, datetime, timezone as dt_tz
from decimal import Decimal
from events.models import Audience, Event, PriceTier, Session

event, _ = Event.objects.update_or_create(
    slug="...",
    defaults={
        "title": "...",
        "event_type": Event.Type.SPECIAL_EVENT,  # or SEMINAR
        "start_date": date(2026, 9, 5),
        "end_date": date(2026, 9, 5),
        "format": Event.Format.ONLINE,
        "access_info": "Zoom link TBD — set in admin.",
        "status": Event.Status.DRAFT,
        "published": False,
    },
)
Session.objects.update_or_create(
    event=event, sequence=1,
    defaults={
        "title": "Lecture",
        "start_at": datetime(2026, 9, 5, 17, 0, tzinfo=dt_tz.utc),
        "end_at": datetime(2026, 9, 5, 19, 0, tzinfo=dt_tz.utc),
        "location": "Online (Zoom)",
    },
)
PriceTier.objects.update_or_create(
    event=event, session=None, audience=Audience.ALL,
    defaults={"base_amount": Decimal("100.00")},
)
```

## Add a user as faculty

```python
from accounts.models import User, Profile
u, _ = User.objects.get_or_create(email="speaker@example.com")
u.first_name = "Speaker"; u.last_name = "Name"; u.save()
u.profile.is_faculty = True
u.profile.bio = "Short bio for the public event page."
u.profile.save()
# Then in admin (or via the event's M2M):
# event.faculty.add(u)
```

## Dry-run a real registration flow (without bothering users)

Pre-conditions:
- Event with `status=open` and `published=True`
- Your email is a verified SES identity (`dr@ricopic.one` already is)
- Stripe test-mode keys in EC2 `.env`
- Stripe Dashboard webhook subscribed to `checkout.session.completed`
  and `charge.refunded`

Steps:

1. Open the event page, register, pay with `4242 4242 4242 4242` /
   any future date / any CVC / any ZIP.
2. Verify: confirmation email arrives; receipt email with
   `LSP-YYYY-NNNN` arrives; Registration flips to PAID in admin;
   event page now shows the access_info block.
3. Cancel from the confirmation page: confirm prompt → Stripe refund
   issued → REFUNDED status; cancellation email arrives.
4. Generate a pricing code from the faculty view, re-register as a
   different test user with the code, verify the discount is applied
   on Stripe Checkout.
5. Download the roster CSV from the faculty view and verify the test
   registration appears.

## SES production access status

```
aws sesv2 get-account --profile lsp --region us-west-2 \
  --query '{ProductionAccess:ProductionAccessEnabled,Sent24h:SendQuota.SentLast24Hours,Max24Hour:SendQuota.Max24HourSend}'
```

Until `ProductionAccess: true`, transactional email only reaches
verified test recipients (`aws sesv2 list-email-identities --profile lsp --region us-west-2`).

## Background tasks (systemd timers on the host)

Recurring jobs run as host-level systemd timers that `docker exec` a
management command in `lsp-website-web-1` (not in-container cron):

| Timer | Command | Purpose |
|---|---|---|
| `lsp-dues-cron.timer` | `send_dues_reminders` + `send_tuition_reminders` | Weekly dues/tuition reminder emails to obligated unpaid/undecided members (from Sept 1, throttled per period) |
| `lsp-parletre-purge.timer` | `purge_expired_messages` | Redacts expired Parlêtre disappearing-channel messages (blackout body + delete attachment files, keep rows) |

Inspect/trigger on the host:

```
ssh lsp 'systemctl list-timers "lsp-*"'
ssh lsp 'systemctl start lsp-parletre-purge.service'   # run once now
ssh lsp 'journalctl -u lsp-parletre-purge.service -n 50'
```

`create_dues_period_if_needed` / `create_tuition_period_if_needed` are
idempotent and ensure the current + next academic-year periods exist;
run them before opening a new year.

## Realtime chat (Parlêtre) deployment notes

Parlêtre's chat uses Django Channels over **daphne (ASGI)** — the
container CMD runs daphne, not a WSGI server, and nginx proxies `/ws/`
to it. The production channel layer is **in-memory** (single daphne
process), which is correct for the current single-container deploy.
`channels_redis` is gated behind `PARLETRE_USE_REDIS=true` (+ a
`RedisPubSubChannelLayer`) for a future multi-process setup — leave it
off unless you scale out, since the pinned redis-py is incompatible with
the older channels_redis client.

## Add an SSH IP to the allowlist

See memory file `aws-ssh-access.md` (`~/.claude/projects/.../memory/`):

```
aws ec2 authorize-security-group-ingress \
  --group-id sg-07ccc0a52994ab3e7 \
  --profile lsp --region us-west-2 \
  --ip-permissions 'IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=<IP>/32,Description="<label>"}]'
```

## Manual override (REG-14) cheat sheet

| Need | Admin path |
|---|---|
| Comp a registration | Registration list → select rows → action *Comp selected registrations* |
| Record an offline payment | Create Payment (method=OFFLINE, status=PENDING, fields filled out) → select → action *Apply payment success* |
| Adjust quoted amount | Edit `Registration.quoted_amount` directly in admin |
| Issue refund | Public flow: cancel button on confirmation page. Staff flow: process refund in Stripe Dashboard, then mark Registration REFUNDED in admin. |
