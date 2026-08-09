# Referral addendum — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Referral Coordinator send an addendum about an already-distributed request, to either the clinicians it went to or the whole referral list, with the text kept on the record and shown to clinicians.

**Architecture:** Distribution starts logging its recipients (`ReferralRequest.distributed_to`, M2M to `ReferralListMember`), which is what makes "only the clinicians this went to" answerable. `services.send_addendum` resolves the audience, renders a new seeded `ADDENDUM` message template, mails each clinician individually through the notifications center, records a `ReferralAddendum` row, and optionally moves the response deadline. The text renders on both the coordinator detail page and the clinician respond page, and is redacted by the retention purge.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-08-08-referral-addendum-design.md`

## Global Constraints

- **"Addendum" everywhere, never "follow-up".** Step 5 already owns that word (`build_followup`, `followup_none/one/many`, the Compose follow-up button). Model, template key, URL, and UI copy all say addendum.
- **Do not paraphrase Diana's seeded template wording.** The new `ADDENDUM` seed is a plain skeleton written fresh, and no existing seed text is edited (`referrals/seed_templates.py`).
- **Member-facing site copy uses commas, not em dashes.** Docs and commit messages use unspaced em dashes.
- **Tailwind v4 scans templates only** — any class set in Python widget attrs must also appear literally in a `.html`. Existing referral forms use `_SELECT`, `_TEXT_INPUT`, `_textarea(n)` helpers in `referrals/forms.py`; reuse them rather than inventing classes.
- **Every automated path keeps a human override** (project principle). Here that means no auto-send: an addendum is always composed and sent by hand, so `ReferralSettings` gains no toggle.
- Latest referrals migration is `0003_blockedsubmission_referralrequest_held_at_and_more`. New migrations are `0004_*` and `0005_*`; generate them with `uv run python manage.py makemigrations referrals`, never hand-numbered.
- Run tests with `uv run pytest`, lint with `uv run ruff check .`. Work in the worktree `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/rapid-river` on branch `rapid-river`.

---

### Task 1: Log who a distribution reached

**Files:**
- Modify: `referrals/models.py` (class `ReferralRequest`, near `distributed_at` ~line 175)
- Modify: `referrals/services.py` (function `distribute`, ~line 223)
- Create: `referrals/migrations/0004_referralrequest_distributed_to.py` (generated)
- Test: `referrals/tests.py` (distribution section, near `test_distribute_emails_active_clinicians_anonymized`)

**Interfaces:**
- Produces: `ReferralRequest.distributed_to` — M2M to `ReferralListMember`, `blank=True`, `related_name="distributed_requests"`. Means *clinicians who have received this request*; senders `.add()` to it, never `.set()`.

- [ ] **Step 1: Write the failing test**

Add to `referrals/tests.py` beside the other distribution tests:

```python
def test_distribute_records_its_recipients(listed, clinician):
    """Who a request went to has to be a recorded fact, or a later addendum
    cannot target them (task #531)."""
    req = make_request()
    services.distribute(req)
    assert list(req.distributed_to.all()) == [listed]

    # A clinician added afterwards is not retroactively a recipient.
    later = User.objects.create_user(email="later@example.com", password="pw")
    later_listed = ReferralListMember.objects.create(
        user=later, onboarded_at=timezone.now(),
    )
    assert later_listed not in req.distributed_to.all()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest referrals/tests.py::test_distribute_records_its_recipients -v`
Expected: FAIL, `AttributeError: 'ReferralRequest' object has no attribute 'distributed_to'`.

- [ ] **Step 3: Add the field**

In `referrals/models.py`, inside `ReferralRequest` next to `distributed_at`:

```python
    distributed_to = models.ManyToManyField(
        "ReferralListMember", blank=True, related_name="distributed_requests",
        help_text="Clinicians who have received this request, whether by the "
                  "original distribution or a later addendum.",
    )
```

- [ ] **Step 4: Record recipients when distributing**

In `referrals/services.py`, in `distribute`, after the send loop and before the `req.status` assignment:

```python
    for member in members:
        notifications.referral_request(member.user, req, subject, body)
    req.distributed_at = timezone.now()
    req.responses_due_at = due
    req.status = ReferralRequest.Status.DISTRIBUTED
    req.save(update_fields=["distributed_at", "responses_due_at", "status"])
    req.distributed_to.add(*members)
    return len(members)
```

- [ ] **Step 5: Generate the migration and run the tests**

Run: `uv run python manage.py makemigrations referrals && uv run pytest referrals/tests.py -v`
Expected: a new `0004_*` migration file; all referrals tests PASS.

- [ ] **Step 6: Commit**

```bash
git add referrals/models.py referrals/services.py referrals/migrations/0004_*.py referrals/tests.py
git commit -m "feat(referrals): record which clinicians a distribution reached (task #531)"
```

---

### Task 2: The addendum model, template, and send service

**Files:**
- Modify: `referrals/models.py` (add `ReferralAddendum` after `ReferralResponse`; add the `ADDENDUM` key to `MessageTemplate.Key` ~line 97)
- Modify: `referrals/seed_templates.py` (add the `addendum` entry)
- Modify: `referrals/notifications.py` (add `referral_addendum`)
- Modify: `referrals/services.py` (add `send_addendum`; extend `purge_expired` ~line 330)
- Create: `referrals/migrations/0005_referraladdendum.py` (generated)
- Modify: `referrals/admin.py` (register the model, mirroring `ReferralResponseAdmin` ~line 38)
- Test: `referrals/tests.py`

**Interfaces:**
- Consumes: `ReferralRequest.distributed_to` (Task 1); `MessageTemplate.get(key)`; `services.render_template(text, context)`; `services._refuse_if_suppressed(req, action)`; `services._absolute(path)`; `emails.send_to_clinician(user, subject, body)`.
- Produces:
  - `ReferralAddendum.Audience.DISTRIBUTED = "distributed"`, `.ALL = "all"`
  - `services.send_addendum(req, text, audience, sent_by=None, responses_due_at=None) -> ReferralAddendum`
  - `notifications.referral_addendum(user, request_obj, subject, body) -> None`
  - `MessageTemplate.Key.ADDENDUM = "addendum"`

- [ ] **Step 1: Write the failing tests**

Add a new section to `referrals/tests.py`:

**Two traps these tests are written around.** Mail from the notifications center is sent on `transaction.on_commit`, so it is invisible to `mailoutbox` unless the send is wrapped in `django_capture_on_commit_callbacks(execute=True)` — copy the pattern from `test_distribute_emails_active_clinicians_anonymized`. And the retention window is `ReferralSettings.retention_months` (default 12), so a purge test must date the request from that setting rather than a hand-picked number of days.

```python
# ---- Addendum ---------------------------------------------------------------


def add_clinician(email="second@example.com") -> ReferralListMember:
    """A second listed clinician, created mid-test so it can stand for
    someone who joined the list after a distribution went out."""
    user = User.objects.create_user(
        email=email, password="pw", first_name="Ben", last_name="Beta",
    )
    return ReferralListMember.objects.create(
        user=user, onboarded_at=timezone.now(),
    )


def test_addendum_to_distributed_skips_later_additions(
    listed, django_capture_on_commit_callbacks,
):
    req = make_request()
    services.distribute(req)
    add_clinician()  # joined the list only after the request went out
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        addendum = services.send_addendum(
            req, "They are looking for a sliding scale.",
            ReferralAddendum.Audience.DISTRIBUTED,
        )
    assert addendum.recipient_count == 1
    assert [m.to for m in mail.outbox] == [[listed.user.email]]
    assert "sliding scale" in mail.outbox[0].body
    assert req.reference in mail.outbox[0].body


def test_addendum_to_everyone_reaches_and_records_new_members(listed):
    req = make_request()
    services.distribute(req)
    later = add_clinician()

    addendum = services.send_addendum(
        req, "Sliding scale, please.", ReferralAddendum.Audience.ALL,
    )
    assert addendum.recipient_count == 2
    assert later in req.distributed_to.all()


def test_addendum_skips_deactivated_clinicians(
    listed, django_capture_on_commit_callbacks,
):
    req = make_request()
    services.distribute(req)
    gone = add_clinician()
    gone.is_active = False
    gone.save()
    mail.outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        addendum = services.send_addendum(
            req, "Sliding scale.", ReferralAddendum.Audience.ALL,
        )
    assert addendum.recipient_count == 1
    assert [m.to for m in mail.outbox] == [[listed.user.email]]


def test_addendum_can_extend_the_response_window(listed):
    req = make_request()
    services.distribute(req)
    req.refresh_from_db()
    later = req.responses_due_at + timedelta(days=7)

    services.send_addendum(
        req, "Sliding scale.", ReferralAddendum.Audience.ALL,
        responses_due_at=later,
    )
    req.refresh_from_db()
    assert req.responses_due_at == later


def test_addendum_refused_on_a_held_request(listed):
    req = make_request(status=ReferralRequest.Status.HELD)
    with pytest.raises(services.SuppressedStatusError):
        services.send_addendum(
            req, "Sliding scale.", ReferralAddendum.Audience.ALL,
        )


def test_purge_redacts_addendum_text(listed):
    req = make_request()
    services.distribute(req)
    addendum = services.send_addendum(
        req, "They are looking for a sliding scale.",
        ReferralAddendum.Audience.ALL,
    )
    config = ReferralSettings.load()
    req.status = ReferralRequest.Status.REPLIED
    req.replied_at = timezone.now() - timedelta(
        days=30 * config.retention_months + 30,
    )
    req.save()

    assert services.purge_expired() == 1
    addendum.refresh_from_db()
    assert "sliding scale" not in addendum.text
```

Add `ReferralAddendum` to the `from .models import (...)` block at the top of the test module.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest referrals/tests.py -k addendum -v`
Expected: FAIL at import, `ImportError: cannot import name 'ReferralAddendum' from 'referrals.models'`.

- [ ] **Step 3: Add the model and the template key**

In `referrals/models.py`, add `ADDENDUM = "addendum", _("Addendum to a distributed request")` to `MessageTemplate.Key`, and add this model after `ReferralResponse`:

```python
class ReferralAddendum(models.Model):
    """Something the coordinator told the clinicians after distribution.

    Kept on the record (not just sent) so the respond page can show it to a
    clinician who opens their link a week later (task #531).
    """

    class Audience(models.TextChoices):
        DISTRIBUTED = "distributed", _("Clinicians this request went to")
        ALL = "all", _("Everyone on the referral list")

    request = models.ForeignKey(
        ReferralRequest, on_delete=models.CASCADE, related_name="addenda",
    )
    text = models.TextField()
    audience = models.CharField(
        max_length=20, choices=Audience.choices, default=Audience.DISTRIBUTED,
    )
    recipient_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("sent_at",)
        verbose_name_plural = "referral addenda"

    def __str__(self) -> str:
        return f"Addendum to {self.request.reference}"
```

- [ ] **Step 4: Seed the message template**

In `referrals/seed_templates.py`, add an `addendum` entry to `SEED_TEMPLATES`. Write it plainly — this is a skeleton for Diana to rewrite on the Templates tab, not an imitation of her voice:

```python
    MessageTemplate.Key.ADDENDUM: {
        "subject": "Referral {reference}, additional information",
        "body": (
            "Dear colleague,\n\n"
            "There is additional information about referral {reference}:\n\n"
            "{addendum}\n\n"
            "If you are available to work with this person, please respond on "
            "the site by {due_date}: {respond_url}\n\n"
            "Warmly,\n"
            "Referral Coordinator\n"
            "Lacanian School of Psychoanalysis"
        ),
    },
```

Match the surrounding dict's exact formatting and the closing used by the other seeds; open `referrals/seed_templates.py` and copy the sign-off verbatim rather than the placeholder above if it differs.

- [ ] **Step 5: Add the notification wrapper**

In `referrals/notifications.py`:

```python
def referral_addendum(user, request_obj, subject: str, body: str) -> None:
    """Tell a clinician something changed about a request they've received.

    Its own wrapper rather than ``referral_request``: that one titles the row
    "a new anonymized referral request" and dedupes, which would swallow the
    second bell row (task #531).
    """
    notify(
        user, Category.REFERRAL_REQUEST,
        title=f"Referral request {request_obj.reference}, addendum",
        body="The Referral Coordinator added information to this request.",
        url=reverse("referrals:respond", args=[request_obj.reference]),
        target=request_obj,
        email_fn=lambda: emails.send_to_clinician(user, subject, body),
    )
```

- [ ] **Step 6: Write the send service**

In `referrals/services.py`, after `distribute`:

```python
def send_addendum(
    req: ReferralRequest,
    text: str,
    audience: str,
    sent_by=None,
    responses_due_at=None,
) -> ReferralAddendum:
    """Tell the clinicians something changed about a distributed request.

    ``audience`` picks between the clinicians the request has already reached
    and the whole active list; either way, deactivated members are skipped and
    everyone reached is recorded on ``req.distributed_to`` (task #531).
    """
    _refuse_if_suppressed(req, "send an addendum for")
    if audience == ReferralAddendum.Audience.DISTRIBUTED:
        members = list(
            req.distributed_to.filter(is_active=True).select_related("user")
        )
    else:
        members = list(
            ReferralListMember.objects.filter(is_active=True)
            .select_related("user")
        )
    if responses_due_at and responses_due_at != req.responses_due_at:
        req.responses_due_at = responses_due_at
        req.save(update_fields=["responses_due_at"])
    due = req.responses_due_at
    tpl = MessageTemplate.get(MessageTemplate.Key.ADDENDUM)
    context = {
        "reference": req.reference,
        "addendum": text,
        "due_date": due.strftime("%B %-d, %Y") if due else "(no date set)",
        "respond_url": _absolute(
            reverse("referrals:respond", args=[req.reference]),
        ),
    }
    subject = render_template(tpl.subject, context)
    body = render_template(tpl.body, context)
    for member in members:
        notifications.referral_addendum(member.user, req, subject, body)
    req.distributed_to.add(*members)
    return ReferralAddendum.objects.create(
        request=req, text=text, audience=audience,
        recipient_count=len(members), sent_by=sent_by,
    )
```

Add `ReferralAddendum` to the `from .models import (...)` block at the top of `referrals/services.py`.

- [ ] **Step 7: Redact addenda in the retention purge**

In `referrals/services.py`, inside `purge_expired`'s loop, after `req.coordinator_notes = ""`:

```python
        req.addenda.update(
            text=f"(redacted after {config.retention_months} months)",
        )
```

- [ ] **Step 8: Register it in Django admin**

In `referrals/admin.py`, mirroring `ReferralResponseAdmin`:

```python
@admin.register(ReferralAddendum)
class ReferralAddendumAdmin(admin.ModelAdmin):
    list_display = ("request", "audience", "recipient_count", "sent_at",
                    "sent_by")
    list_filter = ("audience",)
```

Add `ReferralAddendum` to the model import at the top of `referrals/admin.py`.

- [ ] **Step 9: Generate the migration and run the tests**

Run: `uv run python manage.py makemigrations referrals && uv run pytest referrals/tests.py -v`
Expected: a new `0005_*` migration; all referrals tests PASS.

- [ ] **Step 10: Commit**

```bash
git add referrals/models.py referrals/seed_templates.py referrals/notifications.py referrals/services.py referrals/admin.py referrals/migrations/0005_*.py referrals/tests.py
git commit -m "feat(referrals): send an addendum to a distributed request (task #531)"
```

---

### Task 3: The coordinator's compose page and the clinician's view

**Files:**
- Modify: `referrals/forms.py` (add `AddendumForm` after `RecordResponseForm`)
- Modify: `referrals/views.py` (add `addendum` view after `record_response`)
- Modify: `referrals/urls.py` (add the route beside `record-response`)
- Create: `referrals/templates/referrals/addendum.html`
- Modify: `referrals/templates/referrals/detail.html` (Steps list + a new addenda section)
- Modify: `referrals/templates/referrals/respond.html` (show addenda under the request details)
- Test: `referrals/tests.py`

**Interfaces:**
- Consumes: `services.send_addendum(...)`, `ReferralAddendum.Audience` (Task 2); the `coordinator_required` decorator and `_get_request(reference)` in `referrals/views.py`; form widget helpers `_SELECT`, `_textarea(n)` in `referrals/forms.py`.
- Produces: URL name `referrals:addendum`, path `<_ADMIN>/<reference>/addendum/`, GET renders the compose page and POST sends.

- [ ] **Step 1: Write the failing tests**

```python
def test_coordinator_sends_an_addendum_from_the_page(
    client, coordinator, listed, django_capture_on_commit_callbacks,
):
    req = make_request()
    services.distribute(req)
    mail.outbox.clear()
    client.force_login(coordinator)
    url = reverse("referrals:addendum", args=[req.reference])
    assert client.get(url).status_code == 200

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url, {
            "text": "They are looking for a sliding scale.",
            "audience": ReferralAddendum.Audience.DISTRIBUTED,
        })
    assert resp.status_code == 302
    addendum = ReferralAddendum.objects.get(request=req)
    assert addendum.sent_by == coordinator
    assert addendum.recipient_count == 1
    assert "sliding scale" in mail.outbox[0].body


def test_addendum_page_forbidden_without_role(client, clinician, listed):
    req = make_request()
    services.distribute(req)
    client.force_login(clinician)
    assert client.get(
        reverse("referrals:addendum", args=[req.reference]),
    ).status_code == 403


def test_addendum_shows_on_both_pages(client, coordinator, listed, clinician):
    req = make_request()
    services.distribute(req)
    services.send_addendum(
        req, "They are looking for a sliding scale.",
        ReferralAddendum.Audience.ALL,
    )

    client.force_login(clinician)
    page = client.get(reverse("referrals:respond", args=[req.reference]))
    assert b"sliding scale" in page.content

    client.force_login(coordinator)
    page = client.get(reverse("referrals:detail", args=[req.reference]))
    assert b"sliding scale" in page.content


def test_addendum_page_refuses_a_closed_request(client, coordinator, listed):
    req = make_request(status=ReferralRequest.Status.CLOSED)
    client.force_login(coordinator)
    resp = client.get(reverse("referrals:addendum", args=[req.reference]))
    assert resp.status_code == 302  # bounced back to the detail page
    assert not ReferralAddendum.objects.exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest referrals/tests.py -k addendum -v`
Expected: FAIL, `NoReverseMatch: 'addendum' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the form**

In `referrals/forms.py`, after `RecordResponseForm`:

```python
class AddendumForm(forms.Form):
    """Something to tell the clinicians after distribution (task #531)."""

    text = forms.CharField(
        label="What's changed", widget=_textarea(5),
        help_text="Sent to the clinicians and shown on their respond page.",
    )
    audience = forms.ChoiceField(
        label="Send to", choices=ReferralAddendum.Audience.choices,
        widget=_SELECT,
    )
    responses_due_at = forms.DateTimeField(
        required=False, label="Response deadline",
        widget=forms.DateTimeInput(
            attrs={"type": "date", "class": "input input-bordered w-full"},
            format="%Y-%m-%d",
        ),
    )

    def __init__(self, *args, request_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_obj = request_obj
        if request_obj is not None:
            reached = request_obj.distributed_to.filter(is_active=True).count()
            everyone = ReferralListMember.objects.filter(is_active=True).count()
            choices = [
                (
                    ReferralAddendum.Audience.DISTRIBUTED,
                    f"Only the clinicians this request went to ({reached})"
                    if reached
                    else "Only the clinicians this request went to "
                         "(not recorded for this request)",
                ),
                (
                    ReferralAddendum.Audience.ALL,
                    f"Everyone on the referral list ({everyone})",
                ),
            ]
            self.fields["audience"].choices = choices
            self.fields["audience"].initial = (
                ReferralAddendum.Audience.DISTRIBUTED if reached
                else ReferralAddendum.Audience.ALL
            )
            self.fields["responses_due_at"].initial = (
                request_obj.responses_due_at
            )

    def clean_audience(self):
        """An unrecorded audience cannot be targeted, whatever the POST says."""
        audience = self.cleaned_data["audience"]
        if (
            audience == ReferralAddendum.Audience.DISTRIBUTED
            and self.request_obj is not None
            and not self.request_obj.distributed_to.filter(
                is_active=True,
            ).exists()
        ):
            raise forms.ValidationError(
                "This request has no recorded recipients, so it can only go "
                "to everyone on the referral list.",
            )
        return audience
```

Add `ReferralAddendum` to the model import at the top of `referrals/forms.py`.

- [ ] **Step 4: Add the view**

In `referrals/views.py`, after `record_response`:

```python
@coordinator_required
def addendum(request, reference):
    """Compose and send an addendum to a distributed request (task #531)."""
    req = _get_request(reference)
    sendable = (
        req.status in (
            ReferralRequest.Status.DISTRIBUTED, ReferralRequest.Status.REPLIED,
        )
        and not req.is_purged
    )
    if not sendable:
        messages.error(
            request,
            f"Referral {req.reference} is not open for an addendum.",
        )
        return redirect("referrals:detail", reference=reference)
    if request.method == "POST":
        form = AddendumForm(request.POST, request_obj=req)
        if form.is_valid():
            record = services.send_addendum(
                req,
                form.cleaned_data["text"],
                form.cleaned_data["audience"],
                sent_by=request.user,
                responses_due_at=form.cleaned_data["responses_due_at"],
            )
            messages.success(
                request,
                f"Addendum sent to {record.recipient_count} "
                f"clinician{'' if record.recipient_count == 1 else 's'}.",
            )
            return redirect("referrals:detail", reference=reference)
    else:
        form = AddendumForm(request_obj=req)
    return render(request, "referrals/addendum.html", {
        "req": req,
        "form": form,
    })
```

Add `AddendumForm` to the `from .forms import (...)` block at the top of `referrals/views.py`.

- [ ] **Step 5: Add the URL**

In `referrals/urls.py`, after the `remove-response` entry:

```python
    path(f"{_ADMIN}/<str:reference>/addendum/", views.addendum,
         name="addendum"),
```

- [ ] **Step 6: Write the compose template**

Create `referrals/templates/referrals/addendum.html`, following the shape of `referrals/templates/referrals/followup.html` (open that file and match its block structure and heading classes):

```html
{% extends "referrals/base.html" %}
{% block title %}{{ req.reference }} · Addendum{% endblock %}
{% block tab_content %}
<div class="max-w-2xl space-y-6">
  <header class="space-y-2">
    <h1 class="font-serif text-2xl text-base-content">Addendum to {{ req.reference }}</h1>
    <p class="text-sm text-base-content/70">
      Tell the clinicians something that changed since the request went out. What
      you write is emailed to them and shown on their respond page, so a clinician
      opening their link later sees it without going back to email.
    </p>
  </header>

  <form method="post" class="rounded-xl border border-base-300/60 bg-base-100 p-5 space-y-4">
    {% csrf_token %}
    <label class="block space-y-1">
      <span class="text-sm font-medium text-base-content">{{ form.text.label }}</span>
      {{ form.text }}
      <span class="block text-xs text-base-content/60">{{ form.text.help_text }}</span>
      {% for error in form.text.errors %}<span class="block text-xs text-error">{{ error }}</span>{% endfor %}
    </label>
    <label class="block space-y-1">
      <span class="text-sm font-medium text-base-content">{{ form.audience.label }}</span>
      {{ form.audience }}
      {% for error in form.audience.errors %}<span class="block text-xs text-error">{{ error }}</span>{% endfor %}
    </label>
    <label class="block space-y-1">
      <span class="text-sm font-medium text-base-content">{{ form.responses_due_at.label }}</span>
      {{ form.responses_due_at }}
      <span class="block text-xs text-base-content/60">Leave as it is unless the addendum deserves more time to answer.</span>
      {% for error in form.responses_due_at.errors %}<span class="block text-xs text-error">{{ error }}</span>{% endfor %}
    </label>
    <div class="flex items-center gap-2">
      <button class="btn btn-primary">Send addendum</button>
      <a href="{% url 'referrals:detail' req.reference %}" class="btn btn-ghost">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Show addenda on the coordinator detail page**

In `referrals/templates/referrals/detail.html`, add a section immediately before the "Clinician responses" section (`<h2 ...>Clinician responses</h2>`, ~line 139):

```html
  {# --- Addenda --------------------------------------------------------- #}
  <section class="rounded-xl border border-base-300/60 bg-base-100 p-5 space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 class="font-serif text-xl text-base-content">Addenda</h2>
      {% if req.status == "distributed" or req.status == "replied" %}
      <a href="{% url 'referrals:addendum' req.reference %}" class="btn btn-sm">Send an addendum</a>
      {% endif %}
    </div>
    {% if req.addenda.all %}
    <ul class="space-y-3">
      {% for add in req.addenda.all %}
      <li class="rounded-lg border border-base-300/60 p-3 text-sm space-y-1">
        <div class="flex flex-wrap items-center gap-2 text-base-content/55">
          <span>{{ add.sent_at|date:"M j, Y, g:i a" }}</span>
          <span class="badge badge-ghost badge-sm">{{ add.get_audience_display }}</span>
          <span>{{ add.recipient_count }} clinician{{ add.recipient_count|pluralize }}</span>
        </div>
        <p class="whitespace-pre-line text-base-content/80">{{ add.text }}</p>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="text-base-content/60 text-sm">Nothing added since the request went out.</p>
    {% endif %}
  </section>
```

- [ ] **Step 8: Show addenda on the clinician respond page**

In `referrals/templates/referrals/respond.html`, inside the request-details `<section>`, after the `{% if req.additional_information %}` block and before the `{% if req.responses_due_at %}` deadline paragraph:

```html
    {% for add in req.addenda.all %}
    <div class="rounded-lg border border-warning/40 bg-warning/5 p-3">
      <p class="text-base-content/60 text-xs">Added {{ add.sent_at|date:"M j, Y" }} by the Referral Coordinator</p>
      <p class="whitespace-pre-line text-sm mt-1">{{ add.text }}</p>
    </div>
    {% endfor %}
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest referrals/ -v && uv run ruff check .`
Expected: all PASS, ruff clean.

- [ ] **Step 10: Commit**

```bash
git add referrals/forms.py referrals/views.py referrals/urls.py referrals/templates/referrals/addendum.html referrals/templates/referrals/detail.html referrals/templates/referrals/respond.html referrals/tests.py
git commit -m "feat(referrals): compose an addendum and show it to clinicians (task #531)"
```

---

### Task 4: Guide, full verification, and ship

**Files:**
- Modify: `core/docs/referrals-guide.md`

- [ ] **Step 1: Document the addendum in the coordinator guide**

In `core/docs/referrals-guide.md`, add a bullet to the per-request actions list (beside "Record a response manually" and "Compose follow-up"):

```markdown
- **Send an addendum**—for something that changed after the request went
  out, such as the person turning out to need a sliding scale. Choose
  whether it goes only to the clinicians the request already reached or to
  everyone on the list, and extend the response deadline if the change
  deserves more time. What you write is emailed and also shown on the
  clinicians' respond page, so it stays with the request.
```

Watch the rendered-markdown gotcha: a `-` starting a wrapped line inside a list item silently becomes a nested bullet.

- [ ] **Step 2: Run the full suite and the linter**

Run: `uv run pytest && uv run ruff check .`
Expected: everything PASS (~2760 tests), ruff clean.

- [ ] **Step 3: Commit and merge to main**

```bash
git add core/docs/referrals-guide.md
git commit -m "docs(referrals): document the addendum in the coordinator guide (task #531)"
git -C /Users/picone/LSP-Web-Coordinator/lsp-website merge --no-ff rapid-river
git -C /Users/picone/LSP-Web-Coordinator/lsp-website push origin main
```

- [ ] **Step 4: Verify the deploy goes green**

Pushing to `main` runs CI and, only if it passes, deploys. A pushed commit is not a deployed one — watch the run to completion:

```bash
gh run list --repo ricopicone/lsp-website --limit 1 --json status,conclusion,headSha
```

Expected: `completed` / `success` on the merge SHA. Two migrations (`0004`, `0005`) apply on the container's startup CMD.
