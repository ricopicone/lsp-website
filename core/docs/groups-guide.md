# Groups at the LSP—a guide

LSP's collaborative bodies are realized in this web application in an abstraction we call a **Group**. 
This guide explains who starts each kind of Group, who approves it, how people join, who runs it,
and how it ends. It's for staff, the Board of Directors, the Program Committee, and
faculty—no technical background needed.

## The five kinds

Here are the five kinds of group and how they are created in the system.

| Kind | What it is | Who initiates in the app |
|---|---|---|
| **Committee** | A standing body that carries the school's work | Set up by staff (foundational) |
| **Working Group** | A standing, task-oriented group serving the school | The Board charters it |
| **Seminar** | A year-long teaching seminar led by faculty | Faculty propose, or the PC builds it |
| **Cartel** | A few members + a "plus-one", formed around a shared question | Any member proposes it |
| **Reading Group** | A group reading a shared text together | A standing, openly-joinable group |

Here we're calling the Board of Directors, the Program Committee, and the Meeting of Analysts *committees*.

## What every Group has

A **Workspace**—one page per Group, with tabs for an overview, a private
discussion forum, a private chat, shared works and files, a schedule, tasks, and settings.

## Ideas that apply to every Group

**Leaders.** A Group's *leaders* are the people who run it—they can edit its
roster, settings, and schedule (and, for committees, its charter). You lead a
Group if you are one of its named leaders (chair, co-chair, faculty, or
organizer), or you're on the Program Committee, LSP Staff, or the Board, or a
site administrator. **Cartels are the exception:** a cartel has no chair—every
member leads it together, *except* the plus-one, who is a guest, not a leader.
One safeguard: a Group must always keep at least one leader—the last leader
can't leave or be removed until another is in place.

**Access.** Active members of a Group take part fully. For some kinds
of Group, after a person leaves it, they retain *archive-only access*, which is read-only—you can read past discussion and released works but not post. 
It's what you keep after you leave, after a Seminar year ends without
re-enrolling, or after a Group is archived.

**Archiving.** Archiving dissolves a Group: it goes read-only (no new posts or
members) but nothing is deleted, and past members keep read access. Managers can
reactivate it later. This is the graceful way to end a Group.

## The kinds in detail

It is important to remember that the following describes the way these bodies work 
in the app, not necessarily how they function in general. The app is just a vehicle.

### Committees

Committees are foundational—set up by staff, not proposed. Members are
**appointed**: a leader adds them on the Settings tab and sets each role
(chair, secretary, treasurer, …). Leaders—the chair, the Board, the
Program Committee, and LSP Staff—can edit the committee's **charter**
right on the Settings tab. Committee members and leaders schedule meetings on
the Schedule tab.

**End.** Committees are standing, so they rarely close; a leader can archive
one (read-only, reversible) if it is dissolved.

**Existing committees.** The Board, the Program Committee, and the Meeting of
Analysts already exist as committees.

**Automatic membership (the Meeting of Analysts).** A committee can be set so
that everyone in a given role is automatically a member. The Meeting of Analysts
works this way: every Analyst belongs to it automatically.

### Working Groups

- **Create:** a *Board of Directors* member clicks **New working group**, names it, sets
  its **chair**, and adds starting members. No separate approval—the Board's
  creation is the authorization.
- **Join:** managers add people from the Workspace **Settings** tab. No open
  join.
- **Run:** the chair, plus the Board and LSP Staff.
- **Schedule:** members and leaders add meetings on the Schedule tab.
- **End:** the chair or the Board archives it once its work is done.

### Seminars

- **Create—two ways:** the *Program Committee* builds a seminar directly
  in the Program admin; or **any member** clicks **Propose a seminar** (on the
  Program page) with the title, dates, format, and instructors—optionally as a
  *new year of an existing seminar*.
- **Approve a proposal:** the *Program Committee*, on the **Proposals**
  tab of the Program admin. Approving *creates the seminar* and adds it to the
  year's program (you publish the program separately). Declining records a
  reason the faculty member can see and respond to.
- **Join:** students **register** (and pay, unless covered by tuition).
- **Each year:** if faculty want to continue, a seminar keeps the same Workspace across years. Students must
  *re-enroll* each year to stay active; otherwise they keep read-only access
  to past materials.
- **Run:** the faculty (edit the description, set pricing codes, see the roster)
  and the Program Committee.
- **Faculty standing:** teaching a seminar is what makes someone faculty—when a
  seminar is approved, its instructors are granted faculty standing
  automatically (the first seminar you teach gives you the faculty flag).
- **End:** a seminar runs year to year as long as faculty open a new year; when
  none is opened, the last year ends and its Workspace stays a read-only
  archive. A leader can also archive the whole seminar.

### Cartels

- **Create:** any member clicks **Propose a cartel**, describes the guiding
  question and other information, and can name people to receive special
  invitations. Once approved, the cartel is published to the whole school, so
  any member can find it and apply.
- **Approve:** the *Program Committee* sees the proposal in a review queue and
  approves or declines it. The *Cartel Coordinator* can add feedback, but the PC
  decides. A declined proposal can be edited and resubmitted.
- **Join:** accept an invitation; *apply* to an open cartel (a member then
  accepts you); or be invited to be its *plus-one* (who may be someone outside
  the school, invited to create an account).
- **Run:** the members together — the plus-one is a guest, not a leader. Any
  member can close it to new applicants, reopen it, or archive it.
- **Schedule:** any member of the cartel can manage its meetings.
- **End:** any member archives it when the cartel has run its course.

### Reading Groups

- **Create:** a standing, open group.
- **Join:** if it has no fee, any member **joins with one click** (no approval, no payment). If a
  reading group runs a *paid year*, members **register** for that year
  instead.
- **Run:** *organizers* (plus LSP Staff and the Program Committee), who can
  open a new paid year.
- **Schedule:** organizers add meetings on the Schedule tab.
- **End:** an organizer archives it when it winds down; otherwise it stands.

## How do I…?

- **Propose a seminar** (any member)—**Program page → Propose a seminar**; track
  or resubmit it on the same page.
- **Propose a cartel** (any member)—**Groups → Cartels → Propose a cartel**.
- **Start a working group** (Board)—**Groups → Working Groups → New working
  group**.
- **Review cartel proposals** (PC / Coordinator)—**Groups → Cartels → Review
  proposals**.
- **Approve a seminar proposal** (PC)—**Program admin → Proposals →
  Approve & mint** (or Decline with a reason), then publish the program.
- **Edit a committee's charter** (chair / Board / staff)—the committee's
  Workspace → **Settings** tab.
- **Add or remove a member** (leaders)—the Group's **Settings** tab →
  **Members** (you can't remove the last leader without naming another first).
- **Leave a Group** (any member)—**Leave group** at the top of the Workspace.
- **Archive or reactivate a Group** (leaders)—the **Settings** tab.

---

*Developer reference: `docs/group-governance-technical.md`.*
