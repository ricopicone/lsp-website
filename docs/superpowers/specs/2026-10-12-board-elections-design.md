# Board elections

Task #813. Design date 2026-10-12.

## The ask

> We need an election system, administered by a member of the school who isn't
> on the Board or running for the Board. It will be me this year, but it should
> be a separate role that can be assigned by the Board. Members can vote. The
> system should include an open to all members call for self-nominations, a
> self-nomination process with a cutoff date, followed by a period of voting.
> The voting administrator should be able to see the status of the voting and
> be able to see who has voted. [...] Status of votes in general should be
> visible (i.e., open, closed), but I'm not sure if they want leaders or
> tallies visible.

Nothing for elections exists in the code. The Board's own roster
(`committees.Committee(slug="board")` → `Workgroup` → `WorkgroupMembership`
with terms) is where directors live; that stays the record of who serves.

## What the bylaws say (2024-12-29 revision)

The site has to implement the School's rules, not invent them. The relevant
text, Article 3 §1 and Article 12:

- **Who may stand.** "The Board shall be composed of members of the School
  elected from among its Candidates and Analysts." Applicants send "a
  motivation letter [...] clearly stating their motivation, their interests
  and what they can bring to the Board and the School."
- **The Board reviews candidacies.** Applications go "to the Board of
  Directors [...] for review and selection." "The applicants whose application
  for candidacy has been rejected by the Board will be contacted by a Board
  member personally to explain the reasons for such rejection."
- **The Board publishes the slate** "with their motivation letters," and
  communicates "the timeline and **means of vote** (in person, by mail or
  electronic)." The bylaws set **no counting rule**, no secrecy rule, and no
  quorum for a member election: the means of vote is the Board's to choose.
- **No contest.** "If there are seven or fewer candidates running who satisfy
  the other requirements of the Board, no election will take place and those
  individuals will serve as the next Board of Directors."
- **Composition.** 5–7 directors, "no less than three (3) analysts."
- **Results** go to the membership "within one (1) week of the end of the
  voting period."
- **Terms.** Two years, to December 31 following the next annual election.
- **Who votes.** Members are analysts and scholars, and those admitted as
  candidates or pre-candidates in either track; "All above who have paid their
  fees are voting members" (Art. 12 §2(e)); "Members in good standing shall
  have voting rights" (Art. 13 §2).

The President and Vice President are elected by the Board itself and are out
of scope.

## Decisions (Rico, 2026-10-12)

1. **The Board review step is modelled.** Between the nomination cutoff and
   voting, Board members accept or decline each nomination.
2. **Ballots are linked to their voter, and the link is shown only to the
   voter.** The administrator sees *who has voted*, never *how*; the member
   can see and change their own ballot until close. Someone with direct
   database access could still join the two; the help page says so.
3. **Ballots are ranked.** The counting rule is a **per-election setting**,
   because the bylaws leave the means of vote to the Board: **STV** (default)
   or **most votes** counted from each ballot's top N preferences. The Board's
   answer to Rico's email changes a setting, not the code.
4. **Voters** are the bylaws' member roles in active standing, with the
   administrator able to add or remove individuals with a recorded reason.
   "Paid their fees" is applied by a human: the dues ledger is still
   mid-cleanup (Accounts → Owing), so an automatic check could disenfranchise
   someone. Dues status is *shown* to the administrator, never enforced.
5. **Candidates** are analysts, scholars, candidates and candidate scholars.
   Pre-candidates of either track may not stand. The Board review can still
   decline anyone.
6. **The three-analyst minimum is flagged, not enforced.** Plain STV runs; if
   the elected directors plus continuing directors include fewer than three
   analysts, the administrator and Board see a prominent warning, and the
   remedy (e.g. a Director-at-Large appointment) is theirs.
7. **The administrator sets every date**, and the dates drive the windows.
   Judgment steps (Board review, publish slate, run count, publish results)
   stay buttons.
8. **Built on the site** (not an outside voting service), so the roll,
   who-voted and the count are one auditable record.

Defaults chosen in the design discussion, not asked:

- A voter may change their ballot until voting closes.
- Visibility is a per-election setting (Rico is asking the Board). During
  voting: *status only* (default) or *status + turnout*. After the count:
  *winners only* (default) or *winners + the round-by-round count*. No partial
  tally of preferences is ever shown while voting is open — an incomplete STV
  count is misleading.
- Seating winners on the Board roster stays a manual step on Board →
  Membership. Nothing changes the Board automatically.

## Lifecycle

An `Election` passes through these phases. **The phase is computed from dates
and step timestamps, never stored**, so there is no phase field to drift from
the dates (the #532 lesson: one predicate, not a copy).

| Phase | Begins when | Ends when |
|---|---|---|
| Draft | created | `nominations_open_at` passes (or *Open now*) |
| Nominations open | `nominations_open_at` | `nominations_close_at` (or *Close now*) |
| Board review | nominations close | *Publish slate* |
| Slate published | *Publish slate* | voting opens, or *Close as elected without a vote* |
| Voting open | `voting_open_at` **and** the slate is published | `voting_close_at` (or *Close now*) |
| Voting closed | voting closes | *Run count* |
| Counted | *Run count* | *Publish results* |
| Results published | *Publish results* | — |
| Elected without a vote | *Close as elected without a vote* | — |

Rules:

- **Dates.** The administrator sets `nominations_open_at`,
  `nominations_close_at`, `voting_open_at`, `voting_close_at` and
  `results_due` (a date; defaults to one week after voting closes, per the
  bylaws). Validation: each window opens before it closes, and nominations
  close before voting opens.
- **Edits are audited and never re-open a closed window.** A future date may be
  moved either way. A window that is currently open may have its close moved
  *later* (an extension). A date that has passed cannot be moved earlier, and
  a closed window cannot be re-opened by editing a date. Every edit appends a
  line to the Election's audit note.
- **Open now / Close now** buttons beside each window set the corresponding
  date to now (audited), for when the administrator does not want to wait.
- **Voting never opens before the slate is published.** If `voting_open_at`
  arrives first, the console says so and voting opens the moment the slate is
  published.
- **No contest.** When the number of accepted candidates is at most the number
  of seats, the console says the bylaws call for no vote and offers *Close as
  elected without a vote*; the administrator decides. (The bylaws say "seven or
  fewer"; with every seat up that is the same test, and with fewer seats open
  the seat count is what matters. The console quotes the bylaw text either
  way.)
- **The one-week results deadline** is shown on the console as a due date once
  voting closes.

### The scheduled job

Window openings send email, so something must notice that a date has passed.
`elections.services.advance_elections()` runs from the existing five-minute
`send_meeting_reminders` host timer (as #716's session reminder did), so no
host change is needed. It:

- sends the **call for nominations** once `nominations_open_at` has passed;
- **freezes the voter roll** and sends the **voting-open** notice once voting
  has opened;

each stamped by a timestamp on the Election (`call_sent_at`,
`roll_frozen_at`, `voting_notice_sent_at`) set inside a `select_for_update`
transaction **before** mail is queued, so overlapping runs send once. Closing a
window sends nothing and needs no job: the forms check the clock.

## Roles and access

- **New `StaffRole.ELECTION_ADMINISTRATOR`** (`election_administrator`),
  seeded by a `core` data migration in the `0013_seed_registrar_role`
  pattern. Board → Appointments lists every StaffRole except the officers, so
  it appears there with no new screen; the hardcoded role list in
  `board.html`'s landing card is updated.
- **Appointments warns** (does not block) when the role is given to a
  serving director, and **the nomination form refuses** the role's holder:
  the administrator may not stand.
- **Excluded from directory badges**, like Registrar and LSP Staff: it is a
  process role, not a public office.
- **The console gate is the role plus superusers.** Unlike most consoles it
  does **not** admit the Web Coordinator by default: the role exists to be
  impartial, and knowing who has voted should not come bundled with another
  office. (Rico holds both this year by appointment, not by bundling.)
- **Board review** is gated by `committees.permissions.is_on_committee(user,
  "board")` plus superusers, on a page in the Board's admin.

## Data model (new `elections` app)

**`Election`**

- `title`, `slug`, `seats` (positive int).
- `nominations_open_at`, `nominations_close_at`, `voting_open_at`,
  `voting_close_at` (datetimes), `results_due` (date).
- `count_method`: `stv` (default) | `top_n`.
- `show_during_voting`: `status` (default) | `turnout`.
- `show_results`: `winners` (default) | `full`.
- Step timestamps: `call_sent_at`, `slate_published_at`, `roll_frozen_at`,
  `voting_notice_sent_at`, `counted_at`, `results_published_at`,
  `acclaimed_at`, each with a `_by` user FK where a person acts.
- `count_result` (JSON, null until counted): the count's full record, so
  published results are fixed rather than recomputed per page view.
- `audit_notes` (text, append-only, `[date] who: what` lines).
- `phase` is a property over the above.

**`Nomination`** — unique `(election, user)`.

- `letter` (text, required), `submitted_at`, `updated_at`, `withdrawn_at`.
- `role_at_submission` (the member's role then).
- Review: `status` `pending` | `accepted` | `declined`, `reviewed_by`,
  `reviewed_at`, `board_note` (private to the Board and administrator).
- Editable and withdrawable by the member until nominations close. A
  withdrawn nomination may be re-submitted while the window is open.

**`VoterRollEntry`** — unique `(election, user)`.

- `kind`: `override_add` | `override_remove` (before the freeze) or `voter`
  (after it). `reason`, `by`, `at`; `role_at_freeze` on voter rows.
- Before the freeze the roll page shows the *computed* eligible list with
  overrides applied. At the freeze the roll is written out as `voter` rows:
  everyone eligible, plus adds, minus removes.
- After the freeze the administrator may still **add** a voter (audited). A
  voter may be **removed** only if they have not voted; otherwise refused.

**`Ballot`** — unique `(election, voter)`; `cast_at`, `updated_at`.
**`BallotRanking`** — `(ballot, nomination, rank)`, unique `(ballot, rank)`
and `(ballot, nomination)`.

- A ballot must rank at least one candidate and may rank as many as it likes.
- Changing a ballot replaces its rankings in one transaction.
- Only accepted, non-withdrawn nominations of this election can be ranked.

### Eligibility

`elections.eligibility`:

- `VOTER_ROLES` = analyst, scholar, candidate, candidate_scholar,
  pre_candidate, pre_candidate_scholar, member (the `Member` role is the
  bylaws' clause (a), previous Foundation Group members; see Open questions).
- `CANDIDATE_ROLES` = analyst, scholar, candidate, candidate_scholar.
- A voter is an active `User`, `profile.role in VOTER_ROLES`,
  `profile.standing == ACTIVE`, not `is_persona`, not deceased.
- Deliberately **not** `accounts.permissions.lsp_members()`: that answers
  "may this person see members-only pages" and admits Django staff, LSP Staff
  and Auditors serving on committees. Voting is narrower.
- A candidate is a voter whose role is in `CANDIDATE_ROLES` and who does not
  hold the Election Administrator role.
- The roll page shows each person's current-year dues state from
  `payments.ledger` as information only.

## Ballot secrecy

The decision is "linked, shown only to the voter." It holds by structure:

- **`elections/ballots.py` is the only module that reads `BallotRanking`.**
  It has two exits: `own_ballot(user, election)` (the member's page) and
  `anonymous_ballots(election)` (the counter), which returns lists of
  nomination ids in rank order, with no voter, shuffled.
- **Who has voted** is read as the set of voter ids with a `Ballot` row. The
  console shows *voted / not yet*, never `cast_at`: in an electorate of about
  sixty, a timestamp can identify a voter.
- **`Ballot` and `BallotRanking` are not registered in Django admin** and are
  not exposed by the `devapi` API.
- **Tests pin all three**: admin registry, the devapi URL map, and a source
  scan that no module except `ballots.py` (and migrations/tests) references
  `BallotRanking`.
- **Emails never carry a vote.** The ballot-recorded email says it was
  recorded and how to review or change it, nothing more.
- **The administrator's help page says plainly** that the database still links
  a ballot to its voter, so someone with direct database access could read
  it, and that no screen on the site does.

## Counting

`elections/counting.py` holds pure functions — anonymous ballots in, a result
dict out, no database — so they can be tested exhaustively.

**STV.** Scottish STV as specified in the Scottish Local Government Elections
Order 2007 (weighted inclusive Gregory transfers, Droop quota, transfer values
truncated to five decimal places). The implementer works from the Order's
counting rules directly and cites the rule number beside each step.

- Quota = floor(valid ballots / (seats + 1)) + 1.
- A candidate reaching quota is elected. Surpluses transfer largest first, at a
  value of surplus ÷ the candidate's total, applied to each ballot's current
  value. With no surplus to transfer, the lowest candidate is excluded and
  their ballots transfer at their current value.
- A ballot with no further continuing preference is exhausted.
- When continuing candidates equal the remaining seats, all are elected.
- **Ties** (for surplus order or exclusion) are broken by the most recent
  preceding stage at which the tied candidates differed. If they never
  differed, **by lot**: the site draws with a recorded random seed and the
  result is flagged on the console and Board page, so a human may redo the
  draw publicly instead.

**Most votes (`top_n`).** Each ballot gives one vote to each of its top N
ranked candidates (N = seats). The N highest totals win; a tie for the last
seat is drawn by lot, recorded and flagged as above.

**Result record** (stored in `Election.count_result`): method, seats, valid
ballots, quota (STV), each stage's totals, transfers and exhausted value,
elected in order, any lot draws with their seed, and the analyst-minimum check.

**The three-analyst check.** Elected candidates' `role_at_submission`, plus the
Board's serving directors whose term outlasts this election (`end_date` after
the coming December 31), counted for `analyst`. Fewer than three shows a
warning; nothing is changed.

## Screens

**Election Administrator console** — `/admin-tools/elections/`, a card on the
`/admin-tools/` hub for the role. One election at a time is the normal case;
the console lists past elections beneath the current one. Tabs:

- **Overview.** The phase timeline with each date, the next action, and
  counts: nominations, accepted, roll size, turnout. The no-contest notice and
  the results-due date appear here.
- **Settings.** Seats, dates, counting rule, visibility. Edits audited; the
  date rules above enforced.
- **Nominations.** Each nomination with its letter and the Board's decision
  and note. Read-only; *Publish slate* lives here once review is done (it
  refuses while any nomination is still pending).
- **Voter roll.** The roll with role, standing and dues state; add/remove with
  a reason. During voting, a *voted / not yet* column and **Remind those who
  haven't voted**, which emails only the not-yet voters (audited, with count).
- **Count.** *Run count* (after voting closes), the elected, the analyst
  check, lot draws, and for STV the stages. *Publish results*.
- **Help.** The process, the bylaws excerpt, and the secrecy statement.

**Board review** — `/admin-tools/board/elections/`, a card on the Board
landing page while an election is in review. Nominations with letters,
*Accept* / *Decline* with a private note, and a standing reminder that a
declined applicant must be contacted personally by a Board member. Board
members see nothing about the roll or who has voted (unless one also holds
the administrator role, which Appointments warns against).

**Member tab** — My LSP → **Election**, added in `formation/tabs.py` for
eligible voters while an election is past Draft and until 30 days after
results are published (or elected-without-a-vote). By phase:

- *Nominations open:* the call, and for those who may stand the nomination
  form (letter), then their own nomination with edit/withdraw.
- *Board review:* their own nomination's status — *under review*.
- *Slate published / voting:* the slate with letters; their own nomination
  status (*accepted* / *not accepted* — the personal contact comes from the
  Board).
- *Voting open:* the ballot — each candidate with a rank `<select>` (1st, 2nd,
  … or unranked), so it works without JavaScript. Duplicate ranks are refused
  with a message; gaps are closed up on save. After voting, their own ballot
  with *Change my ballot*.
- Always: the election's status (open / closed) and, if enabled, turnout.
- *Results published:* winners, or winners and stages, per the setting.

Copy is member-facing, so commas rather than em dashes.

## Email and notifications

A new `notifications.Category.ELECTIONS` ("Elections"), in the membership
section, **email-locked**: the bylaws require that members be informed, so a
member cannot switch it off. Sent via `ThrottledSender`, From
`core.email.school_from("LSP Election Administrator")`, Reply-To the role
holder (the officer-owned-mail precedent).

| Message | To | When |
|---|---|---|
| Call for nominations | everyone eligible to vote | nominations open (job) |
| Nomination received | the nominee | on submit / edit |
| Candidacy accepted | each accepted nominee | *Publish slate* |
| Voting is open | the frozen roll | voting opens (job) |
| Reminder | roll members who have not voted | administrator's button |
| Ballot recorded | the voter | on cast / change (no choices) |
| Results | the roll | *Publish results* (or elected without a vote) |

No email to a declined nominee: the bylaws give that to a Board member in
person. Each message also rings the bell.

## Testing

- **Counting** (pure): hand-worked STV cases covering a first-stage election,
  surplus transfer with fractional values, exclusion, exhausted ballots, the
  "remaining equals seats" close, tie by earlier stage, tie by lot (seeded),
  and partial ballots; the same for `top_n`. Each case states its expected
  stages, not only the winners.
- **Phase** with a frozen clock at every boundary, including a 17:30 Pacific
  instant (the `local-date-not-utc-date` straddle).
- **Date edits:** extension allowed, re-opening refused, earlier-than-past
  refused, audit line written.
- **Eligibility:** each role, each standing, personas, deceased, overrides,
  the freeze, post-freeze add, refusal to remove someone who voted, the
  administrator refused as a nominee.
- **Secrecy** (structural): admin registry, devapi URL map, source scan.
- **The job:** call and voting notice each sent once across overlapping runs;
  voting does not open before the slate is published.
- **Views:** every gate (administrator, Board, member, non-member, anonymous
  → login redirect per `gate_or_login`), ballot validation, change-ballot,
  nomination edit/withdraw at the window edges.
- **Browser walkthrough** of the full lifecycle before shipping.

## Out of scope

- **Paper or in-person ballots.** Entering one would show the administrator a
  vote. A member who cannot vote online is added to the roll and helped to
  vote on the site.
- **The President / Vice President election** (the Board's own).
- **Automatic Board seating.** The results page links to Board → Membership.
- **Election-related changes to Parlêtre or the directory**, beyond excluding
  the new role from badges.

## Open questions for the Board (Rico's email)

These do not block the build — each is a setting or a one-line constant:

1. Visibility during voting (status / turnout) and of results (winners /
   full count).
2. The counting rule (STV / most votes).
3. Whether the `Member` role (previous Foundation Group members) and the
   *emeritus* / *retired* / *on leave* standings vote. Default: `Member`
   votes; only *active* standing votes; the administrator's add covers
   exceptions.
