# Old → new content migration map

A complete account of the old Wix site's content (every page in its sitemap) and
where each piece lives—or needs to live—on the new Django site, so nothing is
lost when Wix is sunset. Built from a full audit of the live old site
(`https://www.lacanschool.org`) in June 2026.

**Status legend**

- ✅ **Covered** — the new site already holds this (built feature or imported data).
- ✍️ **Migrate** — content exists on the old site and must be hand-carried into an
  existing new-site place (no code needed, but a person must do it).
- ⚠️ **Gap** — no clear home yet; needs a decision and probably a new content page.
- 🔍 **Verify** — check on the live old site before sunset (empty page, or content
  WebFetch couldn't render, e.g. payment widgets).

---

## Structural pages

| Old page | What it holds | New home | Status |
|---|---|---|---|
| `abouttheschool` | Mission ("Founded in 1990…"), 501(c)(3), **Bylaws PDF**, Board roster (2025–26), Program Committee roster + `programcommittee@`, Meeting of Analysts, "Guarantee of the Lack of the School" | Mission prose → `/about/` (`content/pages/about.md`); Bylaws PDF → `/documents/`; Board + PC rosters → Committees under `/groups/` | ⚠️/✍️ — homes exist but Bylaws PDF, the governance narrative, and committee rosters must be deliberately entered |
| `psychoanalyticformation` | Formation philosophy, **tuition $2,500/yr × 4 yrs**, control-analysis requirements, Analyst vs Scholar tracks, equity statement; **4 PDFs** (Analyst Guidelines, Scholar Guidelines, Scholar Founding Text, Statement of Teaching) | Prose → a new `content/pages/formation.md` (+ link from `/the-school/`); apply flow → admissions/My-LSP; 4 PDFs → `/documents/` | ⚠️ — `/the-school/` has the *process* but not the prose, the tuition figures, the two-track text, or the founding PDFs (these are likely the "3 founding docs pending publication") |
| `findanalyst` | Intro + caveat ("may not be a clinician or practicing currently… many work remotely"), referral survey pointer | `/find-an-analyst/` (map) + referrals app (live) | ✅ — port the caveat prose onto the page |
| `members` | The full member roster (50+ profiles: name, credentials, languages, location, phone, email, photo) | `/directory/` | ✅ — this was the import source (80 members loaded) |
| `members-1` | A members hub; "THE ARCHIVE" + footer links (Founding Texts, Bylaws, Cartel Texts, Calendar) | Targets → `/documents/`, `/groups/`, `/calendar/` | ⚠️ — decide whether `/documents/` absorbs the "Archive" name or a dedicated Archive landing is wanted |
| `secretaries` | Actually a single seminar page — "Secretaries to the Psychotic Subject – Seminar III" (Casey Butcher; readings; 1st/3rd Tue; $150 or tuition) | An `Event` under `/program/` | ✅ — fits the Event model 1:1 |
| `thearchive` | Members-only repository landing; **usage/permission agreement** ("…not to publish, cite, share… without written permission"); forum discontinued | Parlêtre + `/documents/` + My LSP | ✍️ — the usage-agreement policy text needs a home (Documents intro or content page) |
| `archivewelcome` | Members-archive onboarding prose; **~24h account-approval** process; lists benefits incl. **LSP Newsletters archive** | Members welcome content page / Parlêtre intro; newsletters → `/documents/` | ✍️ — preserve the newsletters archive + the approval-expectation copy |
| `resources` | **Member-author article/book bibliography** (Bennett, Carlson de la Torre, Cavanagh, Davidson, Lovett, Rogers, Swales, Vanderwees, Yu) + curated **external links** (peer schools & journals) + disclaimer | Member articles → `/works/`; external links → a new "Resources/Links" `content/pages/` page | ⚠️ — highest-risk: links + legacy citations have no auto-populated home; hand-migrate, keep the disclaimer |
| `contribute` | Member submission invite (Passage/Palimpsest); **revoke-permission policy** ("posted until you revoke in writing to the web coordinator") | Works/Documents submission flow | ✍️ — capture the revoke-permission terms in the new publishing copy |
| `payments` | Payments hub; 501(c)(3) tax-deductible language; **Tuition Assistance PDF** | `/dues/`, `/donate/`, event registration | ✍️ — download & re-host the Tuition Assistance PDF; carry the 501(c)(3) language to `/donate/` |
| `payforeventorseminar` | Wix/Stripe payment widget (event/seminar) | Event registration → Stripe Checkout | ✅/🔍 — replaced; verify no fee schedule is hidden in the widget |
| `paylspschooltuition` | Wix/Stripe widget (tuition/dues) | `/dues/` + tuition lifecycle | ✅/🔍 — replaced; verify no hidden prices |
| `makeadonationtolsp` | Wix/Stripe widget (donation) | `/donate/` | ✅ |
| `moreimages` | **Artwork gallery — ~18 captioned modern works** (Miró, Kandinsky, Rauschenberg, Rothko, Diebenkorn, Motherwell, de Kooning, Duchamp, Liz Chalfin, Tobey, Hasegawa, Bowerman …) | Source assets for the Classic-theme artwork heroes (task #259) | ✍️ — capture image files + exact captions/attributions; these are the curated artworks |
| `extra` | Palimpsests-archive landing; library imagery (Bodleian, Mazarine, Trinity Long Room, de Waal "Library of Exile") | `/documents/` / members archive; library images → asset library | ✍️ — low risk; capture captions if reused |

## Seminars / offerings / events

Almost all of these map cleanly to an **`Event`** under `/program/` (or a **Group**
for cartels/reading groups). The Event model already has `description`,
`readings`, `schedule_note`, `fee_note`, `contact`, faculty, and sessions — so a
full migration means re-entering each as an Event, not paraphrasing it to a stub.

| Old page | New home | Notes |
|---|---|---|
| `other-offerings` | `/program/` (index) | Listing only; component pages hold content |
| `seminars2025-2026` | `/program/` (index) | 2025–26 academic-year listing (~11 seminars) |
| `scholarlyseminarseries` | Event | ✍️ unique abstract worth keeping verbatim |
| `seminarsxxiiiandxxiv` | Event | Davidson; *The Sinthome* reading |
| `seminarviii` | Event | Yu & Zhou; Beijing time |
| `workoftheletter` | Event | ✍️ rich reading list + epistolary rationale |
| `directionoftreatment` | Event | ✍️ full reading list + Graph of Desire rationale |
| `fourlessons` | Event (archived) | Sept 2025; completed run |
| `freudreadinggroup` | Group (reading group) or Event | reading list + framing text |
| `graphingdesirewritingdreams` | Event | ✍️ distinctive format rules, readings, CE credits |
| `intersubjectivity` | Event | Mandarin/Beijing; reading list |
| `introductiontobigother` | Event | continues Seminar II |
| `introductiontolacan` | Event | 2-session intro (Jan/Feb 2026) |
| `izcovichlectures` | Event (guest) | ✍️ abstract, tiered fees, CE, bio |
| `lacanianclinicalpractice` | Event | reading list + clinical-frame rationale |
| `psychoanalytictrainingpart7` | Event | ✍️ instructor framing; part of a numbered series (Parts 1–6 archived elsewhere?) |
| `cartelwork` | `/groups/cartels/` (landing copy) | coordinator contact + cartel-formation framing |
| `cartelontopologypartii` | `/groups/cartels/` (record) | empty placeholder — no content |
| `workingdays` | Event (admin-only type) | placeholder ("text here") — incomplete |
| `cinemalacan` | 🔍 verify | returned empty chrome — check in Wix editor |
| `lacanianclinicalworkshop` | 🔍 verify | returned empty chrome — check in Wix editor |
| `temporalityandcausality` | 🔍 verify | returned empty chrome — check in Wix editor |

---

## At-risk content — the punch list (prioritized)

These are the items that will be **lost on sunset** unless someone acts. None are
auto-covered.

1. **Documents to download & re-host in `/documents/`** (Wix `_files` URLs die with the site):
   - Bylaws PDF (from `abouttheschool`)
   - 4 formation PDFs: Analyst Guidelines, Scholar Guidelines, Scholar Founding Text, Statement of Teaching (from `psychoanalyticformation`)
   - Tuition Assistance PDF (from `payments`)
   - **LSP Newsletters archive** (referenced in `archivewelcome` — confirm the files exist and grab them)
2. **A formation content page** (`content/pages/formation.md`): philosophy, **tuition $2,500/yr × 4**, control-analysis requirements, Analyst vs Scholar tracks, equity statement.
3. **A governance home**: mission/501(c)(3)/"Guarantee of the Lack" narrative (→ `/about/`), and **Board + Program Committee rosters with terms** entered on Committee pages under `/groups/`.
4. **A Resources/Links page**: the curated external links (peer Lacanian schools + journals) and the legacy member-article citations + disclaimer (articles also → `/works/`).
5. **Policy texts to preserve** in new publishing/terms copy: the Archive usage agreement (`thearchive`) and the revoke-permission terms (`contribute`).
6. **The "Archive" naming decision**: does `/documents/` (+ Parlêtre + Works + My LSP) absorb "The Archive," or do we want a named Archive landing?
7. **Sweep the seminar catalog**: re-enter every old seminar/offering as an `Event`, preserving the rich ones verbatim (✍️ rows above). Diff the old page list against the `events` table before discarding anything (note: `import_program_2026_2027` re-runs clobber admin edits — reconcile, don't re-import).
8. **Verify-before-sunset**: the three empty seminar pages (`cinemalacan`, `lacanianclinicalworkshop`, `temporalityandcausality`) and the three Stripe widget pages (possible hidden fee schedules) — check these in the Wix editor while it's still up.
9. **Artwork capture** (task #259): the ~18 captioned works on `moreimages` + library images on `extra` are the source assets for the Classic theme; preserve files + exact captions/attributions regardless of the Modern/Classic decision.

## What's already safe

The member **Directory**, the **Find-an-Analyst** map + referral workflow, event
**registration/payments** (Stripe), **Dues/Donate**, the **Calendar**, and the
**2026–27 Program** are already built and (for the directory/program) populated —
so the bulk of the *functional* old site is covered. The risks above are almost
entirely **written content and linked documents**, not features.
