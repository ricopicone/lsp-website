# Rehearsing an online event's video meeting

A dress rehearsal for an in-site Daily meeting, written for the first big one
(*Working with Masochism*, 2026-09-06, external speaker) but reusable for any
online event. Budget **45 minutes** with six people.

The point is not to prove the software works in the abstract. It is to walk the
path a real participant walks, on real machines and real networks, and find the
thing nobody thought of.

---

## 1. Before the rehearsal

### 1.1 Run the pre-flight on the real event

```
manage.py event_video_preflight <event-slug>
```

Read-only: it reports the room's **live** config, and will not create a room.
Everything should be `OK`. A `WARN` is a judgement call; a `FAIL` is a stop.

On prod, via SSM (`sudo -iu ec2-user`, service `web_blue` or `web_green` — find
it with `docker compose ps`).

### 1.2 Build the mirror event

Create a throwaway event that matches the real one on every field that affects
the meeting. A mirror, not the real event: a different slug means a different
Daily room, so nothing you do in rehearsal can touch the live one.

| Field | Set it to |
|---|---|
| `title` | Something unmistakable, e.g. "REHEARSAL — ignore this event" |
| `event_type` | Same as the real event (`special_event` for a one-off) |
| `format` | `online` |
| `speaker_spotlight` | Same as the real event |
| `recording_mode` | Same as the real event |
| `record_video` | Same as the real event |
| `registration_eligibility` | Same as the real event |
| `published` / `status` | `True` / `open` — registration must really work |
| one `Session` | **Scheduled at the rehearsal time**, so `is_live()` is genuinely true |

That last row matters. The attendee Join button only appears inside the live
window (`JOIN_PREOPEN` 15 min before the session through `JOIN_GRACE` 30 min
after). Rehearsing outside it tests the host path only.

### 1.3 Provision the mirror room deliberately

```
manage.py event_video_preflight <rehearsal-slug> --provision
```

Then re-run it **without** `--provision` and confirm it is still green.

---

## 2. Cast

Six roles. Only the speaker must be the real person.

| Role | Who | What it tests |
|---|---|---|
| **Speaker** | the actual speaker, own machine, own network, own slides | screen share, moderator controls, the highest-variance component in the whole event |
| **Host** | the event organiser | pre-open, moderation, recording start/stop |
| **Member attendee** | any member | the ordinary paid-registration join |
| **Guest attendee** | someone with **no account yet** | signup → email verification → registration → join |
| **Latecomer** | anyone | joining 20 minutes in |
| **Disruptor** | anyone willing | host mute/remove, and rejoining after a crash |

The guest attendee must genuinely start from nothing. Reusing an existing
account skips the longest untested chain, which is the one strangers are on.

---

## 3. Per-role scripts

Hand each person only their own script.

### Speaker

1. Ten minutes before, open the event page and click **Test your video & audio**.
   Work through the device check.
2. At T-15, open the event page and click **Open room (host)**.
3. When people arrive, share your slides (**Share** in the meeting toolbar).
   Ask whether the text is readable — do not assume.
4. Talk for a few minutes. Pause and take a question from chat.
5. Open the **People** panel. Find the disruptor and mute them.
6. Try turning your camera off and back on.
7. Leave the meeting using the **Leave** button.

### Host

1. At T-15, open the event page. Confirm the room opens and you have moderator
   controls.
2. Watch for "Live now · N in the room" on the event page as people join.
3. Once the speaker is presenting, start a recording. Stop it two minutes later.
   **Then confirm the recording stopped** — the indicator clears for everyone,
   and afterwards the recording's duration should be about two minutes, not the
   length of the whole rehearsal. This is the rehearsal for a partial recording
   (see below); if stopping doesn't work cleanly, you need to know now.
4. If anyone reports being stuck, note exactly what they saw. **Their words, not
   your interpretation.**

### Member attendee

1. Register for the rehearsal event as you normally would.
2. At T-0, open the event page and click **Join the meeting room**.
3. Confirm you arrive **muted with your camera off** (if spotlight is on).
4. Unmute yourself, say something, mute again.
5. Ask a question in chat.
6. Raise your hand (hand icon in the toolbar). Confirm the speaker can see it.

### Guest attendee

**Start signed out, with an account that does not exist yet.**

1. Open the event page as a stranger would. Follow the registration prompt.
2. Create an account. Wait for the verification email.
3. Click the link in the email, then the confirm button on the page it opens.
4. Complete registration and payment.
5. Join the meeting at T-0.

Note **how long each step took** and anything that made you hesitate.

### Latecomer

1. Do nothing until 20 minutes after the start.
2. Then open the event page and join.
3. Confirm you arrive muted and camera-off, and that you can hear immediately.

### Disruptor

1. Join at T-0 and unmute yourself. Talk over the speaker until muted.
2. Once muted, confirm you *can* unmute yourself again (the spotlight is soft
   by design, not a lock).
3. Force-quit your browser entirely. Reopen it and rejoin from the event page.
4. Report whether rejoining worked on the first try.

---

## 4. Browser matrix

Spread the cast across these. Do not let everyone use Chrome on a Mac.

- Chrome, desktop
- **Safari, macOS** — historically the weak spot
- **Safari, iOS** — the other weak spot
- Chrome, Android
- Firefox, desktop (nice to have)

---

## 5. Checklist

One line per beat. Fill it in live.

| # | Check | Pass? | Notes |
|---|---|---|---|
| 1 | Host opens the room at T-15 | | |
| 2 | Event page shows "Live now · N in the room" | | |
| 3 | Guest completes signup → verification → registration unaided | | |
| 4 | Every attendee arrives muted and camera-off | | |
| 5 | Speaker's screen share is legible to everyone | | |
| 6 | Audio is clean, no feedback or echo | | |
| 7 | Chat works, speaker sees questions | | |
| 8 | Raise-hand works and is visible to the speaker | | |
| 9 | Host mutes the disruptor successfully | | |
| 10 | Muted attendee can unmute themselves again | | |
| 11 | Recording starts and stops | | |
| 11a | An ordinary attendee has **no** Record button (host-only) | | |
| 12 | Latecomer joins cleanly at +20 min | | |
| 13 | Force-quit participant rejoins on the first try | | |
| 14 | Leave returns everyone to the event page | | |
| 15 | Recording appears afterwards and plays, gated correctly | | |
| 16 | Works on Safari macOS | | |
| 17 | Works on Safari iOS | | |

---

## 5a. Recording only part of an event

Presenters sometimes want one portion recorded and the rest not — for *Working
with Masochism* (2026-09-06), the first half but not the second. The system
supports this with no special configuration, but the failure mode is human.

**Setup.** Leave the event at `record_video=False` and `recording_mode` at its
default. That gives hosts a Record button with nothing recording automatically.
**Do not set `record_video=True`**: it auto-starts the moment a host joins, so it
captures the pre-talk setup, and it flips the resulting recording's default
visibility from staff-only to members-visible.

**On the day.**

1. **Name one person** to run the recording, and put it in their script. "Whoever
   remembers" is how the second half ends up on tape.
2. Press Record when the talk actually begins, not when the room opens.
3. Press Stop at the break. Watch the recording indicator clear.
4. Afterwards, check the recording's duration matches the portion you meant to
   capture. That is the unambiguous confirmation.

**If it goes wrong.** There is no trimming. If unwanted material lands in the
file, the options are deleting the whole recording (host/staff can, and it
removes the file from S3 and from Daily as well as the database row) or editing
it outside the system. There is no partial fix inside the site.

**Consent.** Daily shows a recording indicator to every participant for the whole
time it is rolling, so the room can see its own state — and can say something if
it is still recording after the point it should have stopped.

---

## 6. Teardown

**Delete the registrations before the event.** `Registration.event` and
`Registration.price_tier` are both `on_delete=PROTECT`, so deleting the event
first just errors.

If a recording was made, delete it too unless you want to keep it.

---

## 7. Known risks and their mitigations

**A host who joins and leaves the tab open.** The event page will show "Live now"
to registrants for as long as the tab is joined, and Daily bills participant
minutes the whole time. Largely contained by the prejoin screen: opening the room
page lands you on the device check, so you are not actually *in* the room until
you click through. Still: **close the tab when you are done.** If you want to
know exactly when an idle session closes on its own, watch the presence
indicator after the rehearsal ends — the domain has no
`empty_session_close_delay` set, so this is unmeasured.

**Room config freezes at first open.** Opening a room creates it, and until
`ensure_room` reconciles a given property, a room created early keeps whatever
config existed that day. Reconciliation now covers the full property set, but
the habit still matters: run the pre-flight, do not open a real event's room
casually to "check something."

**The token window.** Tokens now stretch to cover the whole live window, so a
rejoin late in a long event works. Outside the live window a host gets the flat
`DAILY_TOKEN_TTL_MINUTES`, which is correct — but it means a host who opens the
room many hours early and leaves it sitting may need to reload the page.

---

## 8. Afterwards

Write up what broke, in the participants' own words. Anything unresolved becomes
a stated known risk with a mitigation, not a quiet omission. Then re-run:

```
manage.py event_video_preflight <real-event-slug>
```

on the **real** event, and confirm it is green.
