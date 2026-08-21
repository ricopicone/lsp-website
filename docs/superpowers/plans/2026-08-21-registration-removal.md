# Registration Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Registration Admin console a Remove button that releases a
registrant's place, asks separately whether to refund, and hands anything the
site cannot refund to the treasurer.

**Architecture:** `Registration.cancel()` gains a `refund` keyword so one state
machine serves both the member's self-cancel and a staff removal. A new
`registrations.services.remove_registration` orchestrates the existing pieces
(`cancel`, `void_registration_charge`, `staff_notes`, notifications) and is
called by one thin `registrar_required` POST view. Nothing new is invented; the
service is an entry point.

**Tech Stack:** Django 5.2, pytest-django, DaisyUI v5 `<dialog>` + Tailwind v4,
Stripe (mocked in tests).

**Spec:** `docs/superpowers/specs/2026-08-21-registration-removal-design.md`

## Global Constraints

- Member-facing copy uses commas, not em dashes (`em-dash-prose-style`).
- Dates come from `timezone.localdate()`, never `timezone.now().date()`
  (`core/test_local_dates.py` fails the build otherwise).
- No `disabled` attribute on any submit button (`submit-guard.js`, #545).
- Never add a per-page Django messages loop (`core/test_templates.py`).
- Django template comments `{# … #}` are single-line only.
- Every staff action appends a dated line to `staff_notes` (REG-14).
- `{% icon "name" %}` returns the empty string for an unknown name, silently —
  any new icon must be added to `_ICON_PATHS` in the same commit that uses it.
- Run `uv run pytest` and `uv run ruff check .` before each commit.

---

### Task 1: Split refund from cancellation in the state machine

**Files:**
- Modify: `registrations/models.py` (`Registration.cancel`)
- Test: `registrations/test_removal.py` (create)

**Interfaces:**
- Produces: `Registration.cancel(self, *, refund: bool = True)` — returns the
  Stripe `Refund` object when one was issued, else `None`. With
  `refund=False` a PAID row becomes `CANCELLED` and Stripe is never called.

- [ ] **Step 1: Write the failing tests**

```python
"""Staff removal of a registration (task #627)."""
import pytest
from decimal import Decimal
from unittest import mock

from payments.models import Payment
from registrations.models import Registration


@pytest.mark.django_db
def test_cancel_without_refund_leaves_stripe_alone(paid_registration):
    reg = paid_registration
    with mock.patch("payments.refund.stripe.Refund.create") as create:
        refund = reg.cancel(refund=False)
    assert refund is None
    create.assert_not_called()
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_without_refund_works_on_a_payment_plan(plan_registration):
    """The PlanRefundRequiresTreasurer guard lives inside the refund branch,
    so declining the refund is what makes a plan registration removable."""
    reg = plan_registration
    reg.cancel(refund=False)
    reg.refresh_from_db()
    assert reg.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_still_refunds_by_default(paid_registration):
    """The member's self-cancel path is unchanged."""
    reg = paid_registration
    with mock.patch(
        "payments.refund.stripe.Refund.create",
        return_value={"amount": 30000},
    ) as create:
        refund = reg.cancel()
    create.assert_called_once()
    assert refund == {"amount": 30000}
    reg.refresh_from_db()
    assert reg.status == Registration.Status.REFUNDED
```

Fixtures (`paid_registration`, `plan_registration`) go at the top of the same
file; model them on the existing ones in `registrations/test_cancel.py` rather
than inventing new shapes.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest registrations/test_removal.py -v`
Expected: FAIL — `cancel() got an unexpected keyword argument 'refund'`

- [ ] **Step 3: Implement**

In `registrations/models.py`, change the signature and guard the refund branch:

```python
    def cancel(self, *, refund: bool = True):
        """Cancel this registration. Refunds the payment if PAID.

        ``refund=False`` releases the place without moving money — a staff
        removal states the two decisions separately (task #627), and it is
        also what makes a payment-plan registration cancellable at all, since
        the ``PlanRefundRequiresTreasurer`` guard lives inside the refund
        branch.
        """
        ...
            if refund and self.status == self.Status.PAID:
                ...                      # existing body, unchanged
                self.status = self.Status.REFUNDED
            else:
                self.status = self.Status.CANCELLED
```

Rename the local `refund = None` result variable to `issued` so it does not
shadow the new parameter, and return `issued`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest registrations/test_removal.py registrations/test_cancel.py -v`
Expected: PASS, including every pre-existing self-cancel test.

- [ ] **Step 5: Commit**

```bash
git add registrations/models.py registrations/test_removal.py
git commit -m "feat(registrations): cancel() can release a place without refunding (task #627)"
```

---

### Task 2: The treasurer handoff notification

**Files:**
- Modify: `payments/notifications.py`
- Test: `registrations/test_removal.py`

**Interfaces:**
- Produces: `payments.notifications.removal_left_money(registration, amount, by)`
  — bell + email to every Treasurer `StaffRole` holder; logs a warning and
  returns when the role has no holder.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_removal_left_money_notifies_the_treasurer(paid_registration, treasurer):
    from payments.notifications import removal_left_money
    from notifications.models import Notification

    removal_left_money(
        paid_registration, Decimal("300.00"), by=paid_registration.user,
    )
    note = Notification.objects.filter(user=treasurer).first()
    assert note is not None
    assert "300.00" in note.body


@pytest.mark.django_db
def test_removal_left_money_survives_a_vacant_treasurer_role(paid_registration):
    from payments.notifications import removal_left_money
    removal_left_money(paid_registration, Decimal("300.00"), by=paid_registration.user)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest registrations/test_removal.py -k removal_left_money -v`
Expected: FAIL — `cannot import name 'removal_left_money'`

- [ ] **Step 3: Implement**

Extract the holder lookup `plan_cancel_needs_treasurer` already does into
`_treasurer_holders()` and have both call it, then add:

```python
def removal_left_money(registration, amount, by) -> None:
    """A staff removal released the place but left settled money (task #627).

    Either the registrar chose not to refund, or the site could not refund it
    cleanly (offline payment, a plan, more than one payment). The charge is
    voided either way, so the member now reads as holding credit; this is what
    stops that being silent.
    """
    who = registration.user.get_full_name() or registration.user.email
    for user in _treasurer_holders(registration):
        notify(
            user, Category.ACCOUNT_UPDATES,
            title=f"Removed registration with money still on it: {who}",
            body=(
                f'{who} was removed from "{registration.event.title}" by '
                f"{by.email}. ${amount} they already paid was not refunded, "
                "so it now reads as credit on their account."
            ),
            url=reverse("treasurer_member_detail", args=[registration.user_id]),
            target=registration, dedupe=True,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest registrations/test_removal.py payments/ -k "treasurer or notification" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add payments/notifications.py registrations/test_removal.py
git commit -m "feat(payments): notify the treasurer when a removal leaves money (task #627)"
```

---

### Task 3: Cancellation email carries a reason and drops the re-register line

**Files:**
- Modify: `payments/emails.py` (`send_cancellation_email`)
- Modify: `payments/notifications.py` (`registration_cancelled`)
- Modify: `payments/templates/payments/email/cancellation.txt`
- Test: `registrations/test_removal.py`

**Interfaces:**
- Produces: `send_cancellation_email(registration, refund=None, reason="", staff_removed=False)`
  and `notifications.registration_cancelled(reg, *, refund=None, reason="", staff_removed=False)`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_staff_removal_email_includes_the_reason(paid_registration, mailoutbox):
    from payments.emails import send_cancellation_email
    send_cancellation_email(
        paid_registration, reason="Removed at the faculty's request.",
        staff_removed=True,
    )
    body = mailoutbox[0].body
    assert "Removed at the faculty's request." in body


@pytest.mark.django_db
def test_staff_removal_email_does_not_invite_re_registration(
    paid_registration, mailoutbox,
):
    from payments.emails import send_cancellation_email
    send_cancellation_email(paid_registration, staff_removed=True)
    assert "register again" not in mailoutbox[0].body


@pytest.mark.django_db
def test_self_cancel_email_still_invites_re_registration(
    paid_registration, mailoutbox,
):
    from payments.emails import send_cancellation_email
    send_cancellation_email(paid_registration)
    assert "register again" in mailoutbox[0].body
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest registrations/test_removal.py -k email -v`
Expected: FAIL — `send_cancellation_email() got an unexpected keyword argument 'reason'`

- [ ] **Step 3: Implement**

Add both keywords to `send_cancellation_email`, pass them into the template
context, thread them through `registration_cancelled`'s `email_fn` lambda, and
edit `cancellation.txt`:

```
{% if reason %}{{ reason }}

{% endif %}{% if not staff_removed %}If you'd like to register again, you can do so at:
{{ site_base_url }}/events/{{ registration.event.slug }}/

{% endif %}Questions? Reply to this email, it goes to {{ support_email }}.
```

Keep the existing refund paragraph above this, unchanged.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest registrations/test_removal.py payments/ -k "cancel" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add payments/emails.py payments/notifications.py payments/templates/payments/email/cancellation.txt registrations/test_removal.py
git commit -m "feat(payments): cancellation email carries a reason, drops re-register on staff removal (task #627)"
```

---

### Task 4: The `remove_registration` service

**Files:**
- Modify: `registrations/services.py`
- Test: `registrations/test_removal.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Removal:
    removed: bool              # False when the row was already terminal
    refunded: bool             # a Stripe refund was actually issued
    refunded_amount: Decimal   # what went back (0 when nothing did)
    left_money: Decimal        # settled money not refunded (0 when none)

def remove_registration(reg, by, *, refund: bool = False, reason: str = "",
                        via: str = "registration admin") -> Removal
```

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_remove_awaiting_payment(awaiting_registration, mailoutbox):
    from registrations.services import remove_registration
    out = remove_registration(awaiting_registration, staff_user())
    assert out.removed and not out.refunded and out.left_money == 0
    awaiting_registration.refresh_from_db()
    assert awaiting_registration.status == Registration.Status.CANCELLED
    assert "Removed" in awaiting_registration.staff_notes


@pytest.mark.django_db
def test_remove_expires_an_open_checkout_session(awaiting_registration):
    """A stale tab must not pay for a place that no longer exists (#561)."""
    from registrations.services import remove_registration
    with mock.patch("payments.stripe_sync.expire_open_sessions") as expire:
        remove_registration(awaiting_registration, staff_user())
    expire.assert_called_once()


@pytest.mark.django_db
def test_remove_comped_voids_the_waived_charge(comped_registration):
    from payments.models import Charge
    from registrations.services import remove_registration
    remove_registration(comped_registration, staff_user())
    assert not Charge.objects.filter(
        registration=comped_registration,
    ).exclude(status=Charge.Status.VOID).exists()


@pytest.mark.django_db
def test_remove_paid_with_refund(paid_registration):
    from registrations.services import remove_registration
    with mock.patch(
        "payments.refund.stripe.Refund.create", return_value={"amount": 30000},
    ) as create:
        out = remove_registration(paid_registration, staff_user(), refund=True)
    create.assert_called_once()
    assert out.refunded and out.left_money == 0
    paid_registration.refresh_from_db()
    assert paid_registration.status == Registration.Status.REFUNDED


@pytest.mark.django_db
def test_remove_paid_without_refund_leaves_credit(paid_registration, treasurer):
    from notifications.models import Notification
    from registrations.services import remove_registration
    with mock.patch("payments.refund.stripe.Refund.create") as create:
        out = remove_registration(paid_registration, staff_user(), refund=False)
    create.assert_not_called()
    assert out.left_money == Decimal("300.00")
    paid_registration.refresh_from_db()
    assert paid_registration.status == Registration.Status.CANCELLED
    assert Notification.objects.filter(user=treasurer).exists()


@pytest.mark.django_db
def test_remove_offline_payment_still_releases_the_place(offline_paid_registration):
    """A refund the site cannot issue must not block the removal."""
    from registrations.services import remove_registration
    out = remove_registration(offline_paid_registration, staff_user(), refund=True)
    assert out.removed and not out.refunded
    assert out.left_money > 0


@pytest.mark.django_db
def test_remove_is_idempotent(awaiting_registration, mailoutbox):
    from registrations.services import remove_registration
    remove_registration(awaiting_registration, staff_user())
    before = len(mailoutbox)
    out = remove_registration(awaiting_registration, staff_user())
    assert not out.removed
    assert len(mailoutbox) == before
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest registrations/test_removal.py -k remove_ -v`
Expected: FAIL — `cannot import name 'remove_registration'`

- [ ] **Step 3: Implement**

```python
TERMINAL = (
    Registration.Status.CANCELLED,
    Registration.Status.REFUNDED,
    Registration.Status.DECLINED,
)


def remove_registration(reg, by, *, refund=False, reason="",
                        via="registration admin") -> Removal:
    """Release a registrant's place (task #627).

    Removing and refunding are two decisions; the caller states both. A refund
    the site cannot issue (offline payment, a plan, more than one payment)
    never blocks the removal — the place is released and the money becomes the
    treasurer's.
    """
    from payments.charges import void_registration_charge
    from payments.models import Payment
    from payments.refund import RefundError

    if reg.status in TERMINAL:
        return Removal(removed=False, refunded=False,
                       refunded_amount=Decimal("0"), left_money=Decimal("0"))

    settled = sum(
        (p.amount for p in reg.payments.filter(
            status=Payment.Status.SUCCEEDED,
        )),
        Decimal("0"),
    )

    issued = None
    if refund:
        try:
            issued = reg.cancel(refund=True)
        except RefundError:            # covers PlanRefundRequiresTreasurer
            reg.cancel(refund=False)
    else:
        reg.cancel(refund=False)

    refunded = issued is not None
    left = Decimal("0") if refunded else settled

    void_registration_charge(reg, f"Registration removed by {by.email}.")

    line = (
        f"\n[{timezone.localdate().isoformat()}] Removed by {by.email} via "
        f"{via}. " + (
            f"Refunded ${settled}." if refunded
            else (f"${settled} left unrefunded for the treasurer." if left
                  else "No money had settled.")
        )
    )
    if reason:
        line += f" Reason: {reason}"
    reg.staff_notes = (reg.staff_notes or "") + line
    reg.save(update_fields=("staff_notes",))

    notify_payments.registration_cancelled(
        reg, refund=issued, reason=reason, staff_removed=True,
    )
    if left:
        notify_payments.removal_left_money(reg, left, by)

    return Removal(
        removed=True, refunded=refunded,
        refunded_amount=settled if refunded else Decimal("0"),
        left_money=left,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest registrations/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add registrations/services.py registrations/test_removal.py
git commit -m "feat(registrations): remove_registration service (task #627)"
```

---

### Task 5: The console view, URL, icon and dialog

**Files:**
- Modify: `registrations/views_admin.py`, `registrations/urls.py`
- Modify: `registrations/templates/registrations/registrar/_row_actions.html`
- Modify: `parletre/templatetags/parletre_tags.py` (add the `user-minus` icon)
- Test: `registrations/test_removal.py`

**Interfaces:**
- Consumes: `remove_registration` from Task 4.
- Produces: URL name `registrations:registrar_remove`, path
  `remove/<int:reg_id>/`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_registrar_can_remove(client, registrar, awaiting_registration):
    client.force_login(registrar)
    url = reverse("registrations:registrar_remove", args=[awaiting_registration.id])
    r = client.post(url, {"refund": "no", "reason": "Faculty request."})
    assert r.status_code == 302
    awaiting_registration.refresh_from_db()
    assert awaiting_registration.status == Registration.Status.CANCELLED


@pytest.mark.django_db
def test_non_registrar_gets_404(client, member, awaiting_registration):
    client.force_login(member)
    url = reverse("registrations:registrar_remove", args=[awaiting_registration.id])
    assert client.post(url, {"refund": "no"}).status_code == 404


@pytest.mark.django_db
def test_remove_button_absent_on_a_cancelled_row(client, registrar, cancelled_registration):
    client.force_login(registrar)
    body = client.get(reverse("registrations:registrar") + "?status=all").content.decode()
    assert f"remove-row-{cancelled_registration.id}" not in body
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest registrations/test_removal.py -k "registrar_remove or 404 or button_absent" -v`
Expected: FAIL — `NoReverseMatch: 'registrar_remove' not found`

- [ ] **Step 3: Implement**

View (`views_admin.py`), following `registrar_comp`'s shape:

```python
@registrar_required
@require_POST
def registrar_remove(request, reg_id: int):
    from .services import remove_registration

    reg = get_object_or_404(Registration, pk=reg_id)
    out = remove_registration(
        reg, request.user,
        refund=request.POST.get("refund") == "yes",
        reason=(request.POST.get("reason") or "").strip(),
    )
    if not out.removed:
        messages.warning(request, "That registration was already closed.")
    elif out.refunded:
        messages.success(
            request,
            f"Removed {reg.user.email} and refunded ${out.refunded_amount}.",
        )
    elif out.left_money:
        messages.success(
            request,
            f"Removed {reg.user.email}. ${out.left_money} they paid was not "
            "refunded, and the treasurer has been notified.",
        )
    else:
        messages.success(request, f"Removed {reg.user.email} from {reg.event.title}.")
    return _back(request)
```

URL (`urls.py`), beside the other registrar POST routes:

```python
    path("remove/<int:reg_id>/", views_admin.registrar_remove, name="registrar_remove"),
```

Icon (`parletre_tags.py`), beside `user-plus`:

```python
    "user-minus": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<line x1="22" x2="16" y1="11" y2="11"/>'
    ),
```

Dialog (`_row_actions.html`), following the Decline dialog exactly. The file
has no `in` filter available, so gate it on a `Registration` property rather
than a status list in the template: add `Registration.is_removable` (True when
the status is not one of the three terminal ones) and wrap the button and
dialog in `{% if r.is_removable %}`.

Add a second property, `Registration.refundable_amount` — the amount of the
single succeeded Stripe payment when `is_on_plan(self)` is False and exactly
one succeeded payment exists, else `None`. The refund radio renders only when
it is set, and **`value="no"` carries `checked`**: a Stripe refund cannot be
un-issued, so the reversible option is the default. Where it is `None` but
succeeded payments exist, render the sentence naming the treasurer instead of
the radio.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest registrations/ -v && uv run ruff check .`
Expected: PASS

- [ ] **Step 5: Rebuild CSS and eyeball it**

```bash
npm run build:css
```

Then load `/admin-tools/registrations/` and open the dialog on an awaiting-payment
row and on a paid row; confirm the radio appears only on the latter.

- [ ] **Step 6: Commit**

```bash
git add registrations/ parletre/templatetags/parletre_tags.py
git commit -m "feat(registrations): Remove button in the registrar console (task #627)"
```

---

### Task 6: The guide, and the full sweep

**Files:**
- Modify: `core/docs/registrar-guide.md`
- Modify: `CLAUDE.md` (status log entry)

- [ ] **Step 1: Add Remove to the row-action list**

After the Comp bullet:

```markdown
- **Remove** — takes the person off the event: their place is released, they
  drop off the roster, and they lose access. Removing and refunding are
  separate choices. Where the site can refund cleanly (one card payment) you
  are asked; where it cannot (an offline payment, a payment plan, more than
  one payment) the place is still released and the treasurer is notified to
  settle the money. The member is always emailed, with your reason if you give
  one.
```

- [ ] **Step 2: Correct "What lives elsewhere"**

Replace the *Refunds and cancellations* bullet, which now sends the registrar
away for something they can do:

```markdown
- **Refunding a payment on its own** (without removing anyone): Treasurer Admin.
```

- [ ] **Step 3: Add the CLAUDE.md status-log entry**

Append to the Done list, in the house style: what the gap was, what was built,
and the two decisions (ask-never-guess on refunds; always email, with the
re-register line dropped). Expect a merge conflict there and keep both sides in
log order (`claude-md-status-log-always-conflicts`).

- [ ] **Step 4: Full suite and lint**

Run: `uv run pytest && uv run ruff check .`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add core/docs/registrar-guide.md CLAUDE.md
git commit -m "docs: registration removal in the registrar guide (task #627)"
```
