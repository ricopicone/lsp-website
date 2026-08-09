# Referral availability checkbox — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the "Not available" option from the clinician referral response form, replacing the radio pair with a single "I'm available" checkbox plus copy telling a clinician they can simply ignore a request they cannot take.

**Architecture:** A form-and-copy change, not a data-model change. `ReferralResponse.available` stays a `BooleanField` and `interested_responses()` keeps filtering `available=True`, so the follow-up variant split, the detail-page count, and the dashboard column are untouched. The clinician form becomes `BooleanField(required=False)`; the view branches on it — checked saves a response, unchecked deletes any existing one (a withdrawal, not a declaration). The coordinator's manual-record form drops its availability select and always records available, and each response row gains a coordinator-only Remove action so the manual override stays complete.

**Tech Stack:** Django 5.2, pytest-django, Tailwind v4 + DaisyUI v5.

**Spec:** `docs/superpowers/specs/2026-08-08-referral-availability-checkbox-design.md`

## Global Constraints

- **Never write `available=False` from any self-service path.** Historical `False` rows stay in the database untouched and keep rendering their existing grey badge. No data migration.
- **Do not paraphrase Diana's seeded `MessageTemplate` copy** (`referrals/seed_templates.py`). No template seed changes in this plan.
- **Member-facing site copy uses commas, not em dashes** (project convention). Docs and commit messages use unspaced em dashes.
- **Tailwind v4 scans templates only.** Any CSS class set in Python widget attrs must also appear literally in some `.html`. `checkbox checkbox-sm` already appears in templates and is the class to use.
- **Run the suite with `uv run pytest`** and lint with `uv run ruff check .`.
- Work in the worktree `/Users/picone/LSP-Web-Coordinator/lsp-website/.claude-worktrees/rapid-river` (branch `rapid-river`, currently even with `origin/main`). Do not edit the main checkout.

---

### Task 1: The clinician respond page

**Files:**
- Modify: `referrals/forms.py` (class `RespondForm`, ~line 90)
- Modify: `referrals/views.py` (function `respond`, ~line 422)
- Modify: `referrals/templates/referrals/respond.html` (lines 7-12 intro copy, 40-51 the response block)
- Test: `referrals/tests.py` (section "Respond page (step 4)", ~line 245)

**Interfaces:**
- Consumes: `ReferralResponse(request, member, available, message, recorded_by)`; `ReferralRequest.reference`; fixtures `clinician`, `listed`, `coordinator` and helper `make_request(**overrides)` already in `referrals/tests.py`.
- Produces: `RespondForm.available` is now `forms.BooleanField(required=False)` — an unchecked POST simply omits the `available` key. The view's withdrawal message text, asserted by tests: `"Your response was withdrawn"`.

- [ ] **Step 1: Replace the availability test with checkbox + withdrawal tests**

In `referrals/tests.py`, replace `test_clinician_can_respond_and_update` (lines 258-272) with the three tests below. Leave `test_respond_requires_active_list_membership` and `test_respond_blocked_when_closed` as they are — a checkbox input still reads `{"available": "True"}` as checked, so the closed-request test keeps working.

```python
def test_clinician_can_respond_and_update(client, listed, clinician):
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    client.force_login(clinician)
    url = reverse("referrals:respond", args=[req.reference])
    assert client.get(url).status_code == 200

    resp = client.post(url, {"available": "on", "message": "Happy to."})
    assert resp.status_code == 302
    response = ReferralResponse.objects.get(request=req, member=listed)
    assert response.available and response.message == "Happy to."
    assert response.recorded_by is None

    # Editing the note keeps the single row (unique per request+member).
    client.post(url, {"available": "on", "message": "By video only."})
    response.refresh_from_db()
    assert response.message == "By video only."
    assert ReferralResponse.objects.filter(request=req).count() == 1


def test_unchecking_withdraws_the_response(client, listed, clinician):
    """No "unavailable" answer exists: an unchecked box means no response
    on file, so the row goes away (task #531)."""
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    client.force_login(clinician)
    url = reverse("referrals:respond", args=[req.reference])
    client.post(url, {"available": "on", "message": "Happy to."})
    assert ReferralResponse.objects.filter(request=req).count() == 1

    resp = client.post(url, {"message": ""}, follow=True)
    assert ReferralResponse.objects.filter(request=req).count() == 0
    assert any("withdrawn" in str(m) for m in resp.context["messages"])


def test_unchecked_with_no_response_is_a_no_op(client, listed, clinician):
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    client.force_login(clinician)
    url = reverse("referrals:respond", args=[req.reference])
    resp = client.post(url, {"message": ""})
    assert resp.status_code == 302
    assert ReferralResponse.objects.filter(request=req).count() == 0


def test_respond_page_offers_no_unavailable_option(client, listed, clinician):
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    client.force_login(clinician)
    html = client.get(
        reverse("referrals:respond", args=[req.reference]),
    ).content.decode()
    assert 'type="checkbox"' in html
    assert 'type="radio"' not in html
    assert "Not available" not in html
    assert "you can simply ignore this request" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/tests.py -k "respond or withdraw or unchecked" -v`
Expected: FAIL. `test_unchecking_withdraws_the_response` fails because the required `TypedChoiceField` rejects a POST with no `available` key (the row survives), and `test_respond_page_offers_no_unavailable_option` fails on `type="radio"` / "Not available" still being present.

- [ ] **Step 3: Turn the form field into a checkbox**

In `referrals/forms.py`, replace the `available` field of `RespondForm`:

```python
class RespondForm(forms.ModelForm):
    """The clinician's step-4 response.

    One checkbox, never a choice (task #531): a clinician who is not
    available lets the request pass. Submitting it unchecked withdraws a
    response rather than recording "unavailable".
    """

    available = forms.BooleanField(
        required=False,
        label="I'm available to work with this person",
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-sm"}),
    )

    class Meta:
        model = ReferralResponse
        fields = ["available", "message"]
        widgets = {"message": _textarea(4)}
```

- [ ] **Step 4: Branch the view on the checkbox**

In `referrals/views.py`, replace the body of the `if form.is_valid():` block inside `respond` (lines 439-450) with:

```python
        if form.is_valid():
            if form.cleaned_data["available"]:
                response = form.save(commit=False)
                response.request = req
                response.member = member
                response.recorded_by = None
                response.save()
                messages.success(
                    request,
                    "Thank you — your response was recorded and connected to "
                    f"referral {req.reference}.",
                )
            else:
                if existing is not None:
                    existing.delete()
                messages.success(
                    request,
                    "Your response was withdrawn, you are no longer listed "
                    f"as available for referral {req.reference}.",
                )
            return redirect("referrals:respond", reference=reference)
```

- [ ] **Step 5: Rewrite the response block in the template**

In `referrals/templates/referrals/respond.html`, replace lines 40-51 (the `{% if existing %}` note and the radio `<div>`) with:

```html
    {% if existing %}
    <p class="text-sm text-base-content/60">
      You responded {{ existing.updated_at|date:"M j, Y, g:i a" }}. Unchecking
      the box below withdraws your response.
    </p>
    {% endif %}
    <div class="space-y-1">
      <label class="flex items-center gap-2 text-sm font-medium text-base-content">
        {{ form.available }}
        <span>{{ form.available.label }}</span>
      </label>
      <p class="text-xs text-base-content/60">
        If you're not available, you can simply ignore this request. No response is needed.
      </p>
      {% for error in form.available.errors %}<span class="block text-xs text-error">{{ error }}</span>{% endfor %}
    </div>
```

Then fix the intro copy at lines 7-12, which still describes responding "as available" as one of two answers:

```html
    <p class="text-base-content/70 text-sm">
      A request for referral received through the LSP website. The
      requester's name and email are withheld; if you respond, the Referral
      Coordinator sends them your practice details from your
      <a href="{% url 'profile_edit' %}" class="link">profile</a>.
    </p>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest referrals/tests.py -v`
Expected: PASS, whole file. The follow-up variant tests (`test_followup_variant_none_substitutes_location`, `..._single_includes_profile_details`, `..._many_and_override`) must pass untouched — that is the proof the none/one/many split is undisturbed.

- [ ] **Step 7: Commit**

```bash
git add referrals/forms.py referrals/views.py referrals/templates/referrals/respond.html referrals/tests.py
git commit -m "feat(referrals): one availability checkbox, no unavailable option (task #531)"
```

---

### Task 2: The coordinator's side and the guide

**Files:**
- Modify: `referrals/forms.py` (class `RecordResponseForm`, ~line 106)
- Modify: `referrals/views.py` (function `record_response`, ~line 167; add `remove_response` after it)
- Modify: `referrals/urls.py` (~line 34, beside the `record-response` route)
- Modify: `referrals/templates/referrals/detail.html` (response rows ~142-160; manual-record form ~175-178)
- Modify: `core/docs/referrals-guide.md` (~lines 50-54)
- Test: `referrals/tests.py` (coordinator section, near `test_coordinator_actions_roundtrip` ~line 447)

**Interfaces:**
- Consumes: `coordinator_required` decorator (`referrals/views.py:44`); `_get_request(reference)`; `RecordResponseForm(member, message)` after this task — the `available` field is gone.
- Produces: URL name `referrals:remove_response`, path `<_ADMIN>/<reference>/remove-response/<int:pk>/`, POST-only, redirects to `referrals:detail`.

- [ ] **Step 1: Write the failing tests**

Add to `referrals/tests.py` in the coordinator section:

```python
def test_record_response_is_always_available(client, coordinator, listed):
    """The coordinator's escape hatch records a response; there is no
    availability question to answer any more (task #531)."""
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    client.force_login(coordinator)
    resp = client.post(
        reverse("referrals:record_response", args=[req.reference]),
        {"member": listed.pk, "message": "By phone."},
    )
    assert resp.status_code == 302
    response = ReferralResponse.objects.get(request=req, member=listed)
    assert response.available
    assert response.recorded_by == coordinator


def test_coordinator_can_remove_a_response(client, coordinator, listed):
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    response = ReferralResponse.objects.create(request=req, member=listed)
    client.force_login(coordinator)
    resp = client.post(
        reverse("referrals:remove_response", args=[req.reference, response.pk]),
    )
    assert resp.status_code == 302
    assert not ReferralResponse.objects.filter(pk=response.pk).exists()


def test_remove_response_forbidden_without_role(client, clinician, listed):
    req = make_request(status=ReferralRequest.Status.DISTRIBUTED)
    response = ReferralResponse.objects.create(request=req, member=listed)
    client.force_login(clinician)
    resp = client.post(
        reverse("referrals:remove_response", args=[req.reference, response.pk]),
    )
    assert resp.status_code == 403
    assert ReferralResponse.objects.filter(pk=response.pk).exists()
```

Also update the existing `test_coordinator_actions_roundtrip` (~line 447): its `record_response` POST currently sends `{"member": listed.pk, "available": "True", "message": "By phone."}`. Drop the `"available": "True"` key so the form no longer receives a field it doesn't declare.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest referrals/tests.py -k "record_response or remove_response" -v`
Expected: FAIL — `NoReverseMatch: 'remove_response' is not a valid view function or pattern name` for the two removal tests; `test_record_response_is_always_available` fails because `RecordResponseForm.available` is required and the POST omits it, so the view redirects with "Couldn't record that response" and no row exists.

- [ ] **Step 3: Drop the availability select from the coordinator form**

In `referrals/forms.py`, `RecordResponseForm` becomes:

```python
class RecordResponseForm(forms.Form):
    """Coordinator escape hatch: record a clinician's response by hand
    (e.g. one received by email or in conversation). Recorded responses
    are always available ones — there is no unavailable answer (#531)."""

    member = forms.ModelChoiceField(
        queryset=ReferralListMember.objects.filter(is_active=True),
        label="Clinician", widget=_SELECT,
    )
    message = forms.CharField(
        required=False, widget=_textarea(2), label="Note",
    )
```

- [ ] **Step 4: Record as available, and add the removal view**

In `referrals/views.py`, change the `defaults` dict inside `record_response` (lines 174-178) to:

```python
            defaults={
                "available": True,
                "message": form.cleaned_data["message"],
                "recorded_by": request.user,
            },
```

Then add this view immediately after `record_response`:

```python
@coordinator_required
@require_POST
def remove_response(request, reference, pk):
    """Take a response off a request — the manual counterpart to a
    clinician unchecking their own box (task #531)."""
    req = _get_request(reference)
    response = get_object_or_404(ReferralResponse, pk=pk, request=req)
    member = str(response.member)
    response.delete()
    messages.success(request, f"Removed the response from {member}.")
    return redirect("referrals:detail", reference=reference)
```

Check the imports at the top of `referrals/views.py`: add `get_object_or_404` to the `django.shortcuts` import and `from django.views.decorators.http import require_POST` if either is missing.

- [ ] **Step 5: Add the URL**

In `referrals/urls.py`, directly after the `record-response` entry (lines 34-35):

```python
    path(f"{_ADMIN}/<str:reference>/remove-response/<int:pk>/",
         views.remove_response, name="remove_response"),
```

- [ ] **Step 6: Update the detail template**

In `referrals/templates/referrals/detail.html`, remove the availability label block from the manual-record form (lines 175-178):

```html
        <label class="block space-y-1 text-sm">
          <span class="text-base-content/60">Availability</span>
          {{ record_form.available }}
        </label>
```

Keep the available/not-available badges on the response rows (lines 146-150) exactly as they are — historical rows still need them. Add a Remove action to each row, inside the `<div class="flex flex-wrap items-center gap-2">` after the `recorded_by` badge (line 152), following the repo's `<dialog>` confirm pattern (`payments/templates/payments/member/_note_modal.html`):

```html
          {% if not req.is_purged %}
          <button type="button" class="btn btn-ghost btn-xs" aria-label="Remove response"
                  onclick="document.getElementById('rmresp-{{ resp.pk }}').showModal()">Remove</button>
          <dialog id="rmresp-{{ resp.pk }}" class="modal">
            <div class="modal-box max-w-sm whitespace-normal text-left">
              <h3 class="font-serif text-lg mb-2">Remove this response?</h3>
              <p class="text-sm text-base-content/70">{{ resp.member }} will no longer be listed as available for this referral, and their details will not appear in the follow-up.</p>
              <form method="post" action="{% url 'referrals:remove_response' req.reference resp.pk %}">
                {% csrf_token %}
                <div class="modal-action mt-3">
                  <button type="submit" class="btn btn-error btn-sm">Remove</button>
                  <button type="button" class="btn btn-ghost btn-sm"
                          onclick="document.getElementById('rmresp-{{ resp.pk }}').close()">Cancel</button>
                </div>
              </form>
            </div>
            <form method="dialog" class="modal-backdrop"><button>close</button></form>
          </dialog>
          {% endif %}
```

A text label rather than an icon button here on purpose: `detail.html` loads no template-tag library, the `{% icon %}` set has no trash glyph (`parletre/templatetags/parletre_tags.py`), and one action on a roomy row reads clearer spelled out.

- [ ] **Step 7: Update the coordinator guide**

In `core/docs/referrals-guide.md`, replace the "Record a response manually" bullet (~lines 50-53) and the sentence about clinicians responding, so the Help tab matches the form:

```markdown
- **Record a response manually**—the escape hatch for a clinician who
  replies to you by email or in person: pick their name and their details
  flow into the follow-up like any other response. Clinicians who are not
  available simply do not respond, so there is no availability to record.
  Use **Remove** on a response to take it back off the request.
```

Watch the rendered-markdown gotcha: a `-` starting a wrapped line inside a list item silently becomes a nested bullet.

- [ ] **Step 8: Run the full suite and the linter**

Run: `uv run pytest referrals/ -v && uv run ruff check .`
Expected: all referrals tests PASS, ruff clean.

- [ ] **Step 9: Commit**

```bash
git add referrals/forms.py referrals/views.py referrals/urls.py referrals/templates/referrals/detail.html referrals/tests.py core/docs/referrals-guide.md
git commit -m "feat(referrals): record responses as available, add a remove action (task #531)"
```

---

### Task 3: Verify end to end

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest`
Expected: PASS. If anything outside `referrals/` touches the respond form or `RecordResponseForm`, fix it here rather than leaving it to CI.

- [ ] **Step 2: Rebuild CSS and eyeball the two pages**

Run: `npm run build:css`, then `uv run python manage.py runserver` and visit `/referrals/<reference>/respond/` as a listed clinician and `/admin-tools/referrals/<reference>/` as the coordinator. Confirm the checkbox renders as a DaisyUI checkbox (not a bare browser box, which would mean the Tailwind class was dropped), the ignore-copy reads well, and the Remove dialog opens and cancels cleanly.

- [ ] **Step 3: Check prod data before deploying**

Count existing `available=False` rows on prod (via SSM, per the `prod-host-access-ssm` memory):

```
ReferralResponse.objects.filter(available=False).count()
```

They are expected to survive untouched and keep rendering the grey badge. This is a read-only sanity check, not a migration.
