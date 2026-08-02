# Faculty Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a faculty guide at `/guides/faculty/` explaining how to run a seminar or reading group (pricing codes included), and make the two code changes that keep it true.

**Architecture:** Three independent changes, smallest first. (1) `can_edit_event` consults the task #480 lead predicate for seminars and reading groups, so a reading group's ORGANIZER conveners reach the faculty tools. (2) `PricingCodeForm`'s person picker becomes usable. (3) A Markdown guide file plus its slug in `GUIDE_SLUGS`, linked from the faculty tools panel.

**Tech Stack:** Django 5.2, pytest-django, Markdown guides rendered by `content.loader`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-02-faculty-guide-design.md`.
- The guide is member-facing site copy: **commas, not em dashes** (the 2026-07-06 style exception). In-repo prose (docstrings, this plan, the spec) keeps unspaced em dashes.
- Run tests from the worktree root with `uv run pytest`; lint with `uv run ruff check .`.
- No migrations, no schema changes, no new dependencies.
- DaisyUI semantic tokens only in templates (`text-base-content/60`, `link`), never hardcoded colors.

---

### Task 1: Reading-group conveners reach the faculty tools

**Files:**
- Modify: `events/permissions.py:12-30`
- Test: `events/test_faculty_views.py` (append)

**Interfaces:**
- Consumes: `workgroups.permissions.is_workgroup_lead(user, workgroup) -> bool` (task #480).
- Produces: `events.permissions.can_edit_event(user, event) -> bool`, unchanged signature, wider truth set.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_faculty_views.py`:

```python
# ---- Reading-group conveners (task #495) -------------------------------


@pytest.fixture
def reading_group(db):
    rg = Event.objects.create(
        title="Reading Seminar XI", slug="reading-xi",
        event_type=Event.Type.READING_GROUP,
        start_date=date(2026, 9, 1), end_date=date(2027, 5, 1),
        published=True, status=Event.Status.OPEN,
    )
    rg.ensure_workgroup()
    return rg


def _convener(reading_group, email="convener@example.com"):
    """A convener as the proposal flow creates one: ORGANIZER on the reading
    group's workgroup, with no FACULTY role anywhere."""
    from django.utils import timezone

    from workgroups.models import WorkgroupMembership

    u = User.objects.create_user(email=email, password="x")
    WorkgroupMembership.objects.create(
        workgroup=reading_group.workgroup, user=u,
        role=WorkgroupMembership.Role.ORGANIZER,
        start_date=timezone.localdate(),
    )
    return u


@pytest.mark.django_db
def test_reading_group_convener_may_edit_the_offering(reading_group):
    from events.permissions import can_edit_event

    convener = _convener(reading_group)
    assert reading_group.is_faculty(convener) is False   # ORGANIZER, not FACULTY
    assert can_edit_event(convener, reading_group) is True


@pytest.mark.django_db
def test_plain_member_of_a_reading_group_may_not_edit_it(reading_group):
    from django.utils import timezone

    from events.permissions import can_edit_event
    from workgroups.models import WorkgroupMembership

    member = User.objects.create_user(email="member@example.com", password="x")
    WorkgroupMembership.objects.create(
        workgroup=reading_group.workgroup, user=member,
        role=WorkgroupMembership.Role.MEMBER,
        start_date=timezone.localdate(),
    )
    assert can_edit_event(member, reading_group) is False


@pytest.mark.django_db
def test_pc_workgroup_lead_gains_nothing_on_a_special_event():
    """A special event shares the Programming Committee's workgroup, so lead
    status there must not be read as leading the event (the PC clause already
    covers real PC members)."""
    from django.utils import timezone

    from committees.models import Committee
    from events.permissions import can_edit_event
    from workgroups.models import WorkgroupMembership

    special = Event.objects.create(
        title="Working with Masochism", slug="masochism-495",
        event_type=Event.Type.SPECIAL_EVENT,
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 1),
    )
    special.ensure_workgroup()
    assert special.workgroup == Committee.objects.get(
        slug="programming-committee",
    ).workgroup
    # An ex-chair whose term has ended leads nothing today.
    stranger = User.objects.create_user(email="ex@example.com", password="x")
    WorkgroupMembership.objects.create(
        workgroup=special.workgroup, user=stranger,
        role=WorkgroupMembership.Role.CHAIR,
        start_date=date(2020, 9, 1), end_date=date(2021, 9, 1),
    )
    assert can_edit_event(stranger, special) is False


@pytest.mark.django_db
def test_convener_sees_the_roster_tab_with_the_mint_form(client, reading_group):
    convener = _convener(reading_group, email="tab@example.com")
    client.force_login(convener)
    url = reading_group.workgroup.get_absolute_url() + "?tab=roster"
    body = client.get(url).content.decode()
    assert "Generate a pricing code" in body
    assert reverse("events:generate_code", args=[reading_group.slug]) in body
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_faculty_views.py -k "convener or plain_member or pc_workgroup_lead" -q`
Expected: the convener tests FAIL (`assert False is True`); the PC and plain-member tests already pass.

- [ ] **Step 3: Implement**

In `events/permissions.py`, add the module-level import and constant after the existing import:

```python
from workgroups.models import WorkgroupMembership
from workgroups.permissions import is_workgroup_lead

#: Event types whose workgroup leadership confers the event's faculty surfaces.
#: A seminar or reading group owns its workgroup, so whoever leads that group
#: runs the offering: faculty for a seminar, and the ORGANIZER conveners a
#: reading group is given instead (``EventProposal.approve`` — "reading groups
#: are organizer-led, not faculty"). Cartels are member-led and stay out; the
#: PC-organized types share the Programming Committee's own workgroup, where
#: "lead" would mean "leads the PC" — already covered, more precisely, by the
#: committee clause in ``can_edit_event``.
LEAD_LED_EVENT_TYPES = frozenset({"seminar", "reading_group"})


def _leads_offering(user, event) -> bool:
    """Whether ``user`` leads the workgroup of an offering they'd thereby run."""
    if event.event_type not in LEAD_LED_EVENT_TYPES or not event.workgroup_id:
        return False
    return is_workgroup_lead(user, event.workgroup)
```

Then extend `can_edit_event`'s docstring and add the clause next to the faculty check:

```python
    if event.is_faculty(user) or event.is_presenter(user):
        return True
    if _leads_offering(user, event):
        return True
```

Docstring gains a sentence: `the leads of a seminar's or reading group's own workgroup (task #495 — a reading group's conveners hold ORGANIZER, not FACULTY),`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest events/test_faculty_views.py events/test_seminar_workspace.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add events/permissions.py events/test_faculty_views.py
git commit -m "feat(events): reading-group conveners reach their faculty tools (task #495)"
```

---

### Task 2: A usable person picker on the pricing-code form

**Files:**
- Modify: `events/forms.py:63-91`
- Test: `events/test_faculty_views.py` (append)

**Interfaces:**
- Produces: `events.forms.PricingCodeForm` with `restricted_to_user` re-labelled, re-ordered, and filtered. No field added or removed, so both call sites (`events/views.py:301`, `workgroups/views.py:387`) are untouched.

- [ ] **Step 1: Write the failing tests**

Append to `events/test_faculty_views.py`:

```python
# ---- The pricing-code person picker (task #495) ------------------------


@pytest.mark.django_db
def test_code_recipient_picker_labels_by_name_and_email():
    from events.forms import PricingCodeForm

    person = User.objects.create_user(
        email="ext@example.com", password="x",
        first_name="Ada", last_name="Byron",
    )
    field = PricingCodeForm().fields["restricted_to_user"]
    assert field.label_from_instance(person) == "Ada Byron (ext@example.com)"
    nameless = User.objects.create_user(email="bare@example.com", password="x")
    assert field.label_from_instance(nameless) == "bare@example.com"


@pytest.mark.django_db
def test_code_recipient_picker_hides_never_verified_signups():
    from django.utils import timezone

    from events.forms import PricingCodeForm

    real = User.objects.create_user(email="real@example.com", password="x")
    real.profile.email_verified_at = timezone.now()
    real.profile.save(update_fields=["email_verified_at"])

    bot = User.objects.create_user(email="bot@example.com", password="x", is_active=False)
    bot.profile.email_verified_at = None
    bot.profile.save(update_fields=["email_verified_at"])

    # Deactivated but verified (e.g. a deceased member) stays pickable: only the
    # never-verified signups purge_unverified_signups deletes are hidden.
    departed = User.objects.create_user(email="gone@example.com", password="x")
    departed.profile.email_verified_at = timezone.now()
    departed.profile.save(update_fields=["email_verified_at"])
    departed.is_active = False
    departed.save(update_fields=["is_active"])

    pickable = set(PricingCodeForm().fields["restricted_to_user"].queryset)
    assert real in pickable
    assert departed in pickable
    assert bot not in pickable


@pytest.mark.django_db
def test_code_recipient_picker_help_text_names_the_external_case():
    from events.forms import PricingCodeForm

    help_text = PricingCodeForm().fields["restricted_to_user"].help_text
    assert "free account" in help_text
    assert "—" not in help_text  # site copy uses commas, not em dashes
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest events/test_faculty_views.py -k "code_recipient" -q`
Expected: FAIL — the default label is the bare email, the bot row is present, and the help text is the model's.

- [ ] **Step 3: Implement**

In `events/forms.py`, above `PricingCodeForm`:

```python
def _code_recipient_queryset():
    """Accounts a pricing code may be pinned to.

    Everyone except the never-verified signups ``purge_unverified_signups``
    treats as bot rows (task #471): inactive *and* carrying no
    ``email_verified_at``. A deceased member's account is deactivated but keeps
    its stamp, so this never hides a real person.
    """
    from accounts.models import User

    return User.objects.exclude(
        is_active=False, profile__email_verified_at__isnull=True,
    ).order_by("last_name", "first_name", "email")


def _person_label(user) -> str:
    """"Ada Byron (ada@example.com)", or the email alone for a nameless row."""
    name = user.get_full_name().strip()
    return f"{name} ({user.email})" if name else user.email
```

And in `PricingCodeForm`:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The field faculty reach for when extending a scholarship to a named
        # person: it defaulted to every account in the database, unordered and
        # labelled by bare email (task #495).
        field = self.fields["restricted_to_user"]
        field.queryset = _code_recipient_queryset()
        field.label_from_instance = _person_label
        field.label = "Only this person may use it"
        field.help_text = (
            "Leave blank and anyone holding the code may redeem it. Someone "
            "outside the school needs a free account before you can pick them "
            "here, so a one-use code you send them works either way."
        )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest events/test_faculty_views.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add events/forms.py events/test_faculty_views.py
git commit -m "feat(events): name the people in the pricing-code picker (task #495)"
```

---

### Task 3: The guide

**Files:**
- Create: `content/pages/guides/faculty.md`
- Modify: `content/guides.py:28-36` (add `"faculty"` after `"seminars"`)
- Modify: `events/templates/events/_faculty_tools.html` (one link, top of the panel)
- Test: `content/test_guides.py` (append)

**Interfaces:**
- Consumes: the frontmatter contract `title` / `summary` / `checklist` read by `content.guides._load`.
- Produces: guide slug `faculty`, reachable at `reverse("guide_detail", args=["faculty"])`.

- [ ] **Step 1: Write the failing tests**

Append to `content/test_guides.py`:

```python
@pytest.mark.django_db
def test_faculty_guide_listed_and_answers_the_pricing_code_question(client):
    body = client.get(reverse("guide_detail", args=["faculty"])).content.decode()
    # The question that prompted the guide: a reduced fee for someone outside
    # the school.
    assert "free account" in body
    assert "Fixed amount" in body
    assert "one use" in body
    # Where the tools are, for both kinds of group.
    assert "Roster" in body
    assert "reading group" in body.lower()
    # Listed on the index like every other guide.
    assert "Running a seminar or reading group" in client.get(
        reverse("guides_index"),
    ).content.decode()


@pytest.mark.django_db
def test_faculty_guide_uses_commas_not_em_dashes():
    """Member-facing site copy, per the 2026-07-06 style exception."""
    from content import guides

    guide = guides.get_guide("faculty")
    assert guide is not None
    assert "—" not in guide.body_html
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest content/test_guides.py -k faculty -q`
Expected: FAIL with a 404 (no such slug yet).

- [ ] **Step 3: Write the guide**

Create `content/pages/guides/faculty.md` with frontmatter `title: Running a seminar or reading group`, `summary: Your tools for the event page, the roster, and per-person pricing, including discount and scholarship codes.`, and no `checklist:` line. Body sections, in order, following the spec: What's yours to decide / Where your tools are / Editing your event page / Who's registered / Fees, discounts, and scholarships (the two recipes, the $0 code, what a code cannot do) / Reading groups / Access details, the room, recordings / Who to ask.

Copy rules: commas, never em dashes. Link with site-relative paths (`/program/`, `/guides/seminars/`) as the other guides do. Name real UI strings ("Generate a pricing code", "Restricted to user", "Faculty view") so the reader can find them.

- [ ] **Step 4: List it**

In `content/guides.py`, `GUIDE_SLUGS` becomes:

```python
GUIDE_SLUGS: list[str] = [
    "logging-in",
    "profile",
    "seminars",
    "faculty",
    "parletre",
    "cartels",
    "my-formation",
    "tuition-dues",
]
```

- [ ] **Step 5: Link the panel to it**

In `events/templates/events/_faculty_tools.html`, immediately inside the opening `<div class="space-y-8">`:

```html
  <p class="text-sm text-base-content/60">
    New to these tools? <a href="/guides/faculty/" class="link">Running a seminar or reading group</a> explains the roster, approvals, and how to extend a discount or a scholarship.
  </p>
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest content/test_guides.py events/test_faculty_views.py -q`
Expected: all pass, including `test_all_listed_guides_render`.

- [ ] **Step 7: Commit**

```bash
git add content/pages/guides/faculty.md content/guides.py content/test_guides.py events/templates/events/_faculty_tools.html
git commit -m "docs(guides): a faculty guide to running a seminar or reading group (task #495)"
```

---

### Task 4: Full verification

- [ ] **Step 1: Whole suite**

Run: `uv run pytest -q`
Expected: no failures (the suite runs under pytest-xdist; a template-scanning test excludes `.claude-worktrees`).

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Merge and push**

```bash
git checkout main && git merge --no-ff vivid-meadow -m "Merge vivid-meadow: faculty guide + convener access (task #495)" && git push origin main
```

Then confirm the Deploy workflow goes green — a push to main is not a deploy until the suite passes (`pushed-is-not-deployed`).

## Self-review

- Spec coverage: guide (Task 3), convener fix (Task 1), mint form (Task 2), the four listed tests spread across Tasks 1-3, out-of-scope items deliberately absent.
- No placeholders: every code step carries the literal code; the guide's prose is specified by section and copy rule rather than transcribed, which is the one place drafting belongs in the writing.
- Type consistency: `_leads_offering` / `LEAD_LED_EVENT_TYPES` / `_code_recipient_queryset` / `_person_label` are each defined once and referenced under those names.
