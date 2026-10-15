# MiraFlores Workpaper: Decisions Log

Single source of truth for what we decided and why. Feeds the one-pager, the video script and interview prep.
Status key: OPEN (still being discussed), LOCKED (decided), REVISIT (decided but flagged).

---

## Core idea (LOCKED as working pitch, wording still Rohan's to own)

A map of where every number came from, plus a permanent record of everything people did to those numbers. The workpaper is that record.

Mentor's framing of the same idea: trace line > inputs > extracted value > printed field, keep every human act as history, and let a checker re-read the printed pages and the IRS/FTB records without trusting the engine.

## Data model (LOCKED as direction)

1. **The packet, loaded as delivered and never edited.** documents > pages (printed_content = truth) > extracted_values (what the pipeline read, can be wrong) > return lines (sources = ev ids or qa ids, inputs = other line keys). All three return versions kept side by side.
2. **An append-only record of what people did.** Each entry: who, role, when, target(s), action, payload, reason. Actions: verify, accept document, adjust, note, review note, question, answer, attach evidence, judgment call, waiver, sign-off, file, amend, view sensitive data. Current state = packet + entries replayed in order.
3. **Calculated live, never stored:**
   - Checker: extracted value vs printed page, re-add totals, cross-document reconciliations, agreement with IRS transcript and FTB account.
   - Sign-off status: a sign-off stores a fingerprint of the values it covered, against a return version; a mismatch reopens it with a reason.

What it buys: undo (reversing entry), "since I last looked", season replay, freeze at filing, amend on top, notice response as an exported slice.

Known tradeoffs: more complex than CRUD; rebuilding state means replaying entries (fine for one household, needs snapshots at firm scale); tax effect of adjustments is an estimate using the packet's per-dollar rates since the engine can't be rerun, and the UI must say so.

## D4. Stack: LOCKED

**One long-lived Python process: FastAPI serving a React (Vite) frontend, on Railway or Fly, one link.**

- **Storage:** SQLite in WAL mode on a persistent volume. It holds only the event log, per-person last-seen markers, and file metadata. The 1.9 MB packet stays a read-only file, loaded as delivered. Inserts happen inside transactions. Video line: "Moving to Postgres is a connection-string change, because the app only ever inserts events." Postgres earns its place only when a second writer process exists.
- **Live updates:** server-sent events. Actions (verify, note, sign-off) are ordinary POSTs; the server appends the event and pushes it to other sessions. Websockets rejected: no shared typing in this product.
- **"Since I last looked":** a stored last-seen event id per person, so it survives closing the laptop.
- **Concurrency:** each request carries the log tip the person was looking at. Notes always append. A sign-off or adjustment made against an older tip gets HTTP 409, and the screen shows the event that landed first. SQLite serializes inserts.
- **Where logic lives:** server only, as pure functions. `project(packet, events)` rebuilds current state; the checker compares that state with printed pages and IRS/FTB records. Both testable without the web app. Checker findings are derived, never written into the human log. The browser only renders the role-filtered result and applies incoming events until the next refresh. No TypeScript copy of the rules (it would drift).
- **Masking is server-side:** the raw packet is never shipped to the browser (Marcus Bell, st-04, has no sensitive-data clearance). A role switcher that only hides fields in the browser is a failure.
- **Attachments:** stored by content hash on the same volume. The log records who attached it, what it supports, and the hash. Downloads pass the same role check; unmasked views are logged.
- **Interview risks to manage:** a React layer Rohan can't walk through (keep rules in Python he can open on camera: replay, checker, 409 rule, masking); a free host that sleeps during recording (use an always-on tier); browser-only role hiding.

---

## D1. Home screen: LOCKED

**The return, 2025 vs 2024, grouped by work area. Role is a filter rail on that return, not a separate home.**

- Top of screen: a two-year strip, federal and California: AGI, taxable income, total tax, balance due. Every figure clickable.
- Variance flags use the firm standard: over 10% AND over $1,000 vs prior year.
- Large detail collapses: one investments row per account (proceeds, basis, wash, tied to printed summary); the 260 Brightpath lots open underneath.
- Role changes the default slice and the verbs:
  - Priya (preparer): wages, investments, business first; dollars and year-over-year deltas.
  - Daniel (reviewer): adjustments, variances, anything someone else changed.
  - Helen (partner): bottom line, area signatures, filing blockers from the firm's required steps.
  - Jo (administrator): edits firm standards.
  - Sam (quality reviewer): receives the return after filing.
  - Marcus (preparer, no sensitive-data clearance): SSNs, bank and account numbers, IP PINs masked; every unmask logged.
  - Examiner view: frozen, read-only, for the 2028 Letter 566.
  - Ngozi and Erik (client): a separate question surface, not a role inside the workpaper.

**Why we changed from the queue idea (good video/interview story):** 2,663 of 3,012 values are at 0.99+ confidence and only 2 are under 0.80. The planted mistakes sit inside the 0.99 pile or on pages never read. A "what needs me" queue would point at the 0.41 handwritten receipt and walk past the real errors. The data, not taste, decided this.

## D2. Can software mark a number verified?: LOCKED

**No. Only a person verifies, and the machine never uses the word "verified."**

- The firm's 5 verification types are all human acts: agreed to source document, recalculated, confirmed with client, agreed to prior year, agreed to third-party record. No "high confidence" type.
- "Ties to the page" is a machine state and looks different from "verified" (initials + time belong to a person). Tying is the weaker check: a value can tie to its page and still be the wrong document or a known mistake.
- To avoid 1,826 meaningless clicks:
  - Accept one open document in one act, page beside the values. History records who accepted which values.
  - An account whose lots tie to its printed summary can be accepted at the summary. Lots stay visible, not individually verified.
  - No "accept all machine-checked" for the whole return.
- **Document disposition comes first:** used, duplicate (D10), superseded (D30 by D31), not extracted (D07, D69, D70, D72), partial (D30, D31: page 32 unread). A partial page is an open item even if every extracted value is 0.99.
- Value states the reviewer can sort by: ties, disagreement (doesn't match page), conflict (document says one thing, the line uses it another way), adjusted, verified, stale.
- Client answers are a distinct kind of evidence. qa-41 ("4,000 I think") is a source of the federal estimates line and is a guess, not a form.

## D3. Sign-off scope: LOCKED

**Preparer and reviewer sign work areas. The partner signs the return once.** Line-level sign-off rejected: v2 to v3 changed 89 lines and there are 302 Form 8949 lines; one late K-1 would lift dozens of signatures.

- Signed areas (the parts of the return that own documents): wages and stock compensation, investments and digital assets, business, rentals and the sale, passthroughs and basis, deductions and credits, payments.
- Time-only buckets (budgeted, not signed): intake and engagement, partner review.
- California: a real time budget and a cross-cutting review lens. Every area shows its state column next to the federal one (e.g. W-2 box 15/16/17 beside box 1). A California finding reopens the area that owns the document. (REVISIT resolved in D8: California gets its own preparer and reviewer signature over a view of the California figures, and owns no documents.)
- Two ticks per area: preparer and reviewer, never the same person (firm rule).
- Partner release = the "Partner sign-off" required step. Blocked while any review note is open or any area is unsigned.
- Any adjustment with a federal or California tax effect over $1,000 needs Helen's sign-off on that adjustment (firm rule).
- Assignment starts on the whole engagement (Priya, Daniel, Helen per assignment_at_start). Areas drive sign-off and time budgets, not initial staffing.
- **Reopen against a version, with a reason, only when covered values change.** Example: the March investments sign-off on v1 lifts when D31 arrives: "M9 basis $6,900 to $4,880, M14 short-term to long-term, M6 wash $735 to $512." A review note does not lift a sign-off. A small receipt does not lift the partner release unless the bottom line moves. The June K-1 lifts passthroughs and the partner release but leaves wages alone.
- **Signed waivers allowed:** sign with an open item and a sentence (extended return, late K-1, unfiled 1099-NECs). Otherwise people sign clean areas just to file.

---

## Error leads (confirmed against the packet, 2026-10-14)

Superseded by the full hunt: see `docs/ERRORS.md` (16 errors with dollar effect, 5 without, 6 judgment calls, outside filings, and the 13 checker rules they imply). The original six leads below are E12, E13, E2, E15, E19, E18 there.

Feeds deliverable 3. Each needs: what's wrong, evidence, tax effect, and which screen surfaces it.

1. **Federal estimated payments overstated by $1,000.** F1040.26 = $13,000, built from 3 x $3,000 EFTPS (D67) + qa-41 "4,000 I think" for Jan 14. IRS transcript shows $3,000 on 2026-01-15. Should be $12,000. Surfaced by: checker vs IRS transcript; required step "Estimated payments agreed to IRS and FTB records."
2. **California estimated payments overstated by $3,500.** F540NR.72 = $14,000 (4 x $3,500). The Sep 15 2025 Web Pay payment was designated tax year 2024 (D68 pay5_year = 2024, conf 0.98) and the FTB account holds it as a 2024 credit. FTB shows only 3 payments for 2025 = $10,500. Surfaced by: checker vs FTB account; "conflict" state (document year vs line use).
3. **Halvorsen W-2 California wages/withholding (D09).** Box 15 CA, box 16 $111,300, box 17 $4,180, all at 0.99, from an Austin TX employer. CA residency ended 2025-07-14. Client (qa-45): new employer kept withholding California until September by mistake. Ties to the page perfectly but is a payroll error; CA-source wage allocation needs review. Surfaced by: state column beside box 1; client answer linked as evidence.
4. **Meridian unread page 32 (D30/D31 partial).** M18 Ironwood REIT cash in lieu: proceeds $250, basis $310, short-term noncovered, never extracted. Engine diagnostic flags $71,965 summary vs $71,715 lots; the $250 gap is exactly this lot. Surfaced by: document disposition "partial" as open item; summary-vs-lots reconciliation.
5. **Meridian corrected 1099 (D31 supersedes D30).** M9 basis $6,900 to $4,880, M6 wash $735 to $512, M14 short to long term. Surfaced by: superseded disposition; version diff; investments sign-off reopening.
6. **Duplicate W-2 image (D10 = photo of D09).** Engine counted once; workpaper must mark it duplicate so it can't be verified into a second set of wages. Surfaced by: document disposition.

Low-confidence reads (not the real errors, but must be handled): ev-0919 Coinhaven C6 cost basis = null (0.60), ev-1049 handwritten cash gift $1,500 (0.41).

Context numbers: AGI $228,409 (2024) to $445,590 (2025); wages $156,039 to $212,400. Brightpath D74 = 1,826 values / 260 lots.

---

## Step 1 build decisions (LOCKED 2026-10-14, after Rohan's review)

Made while building the backend core and reviewed by Rohan. D5, D8, D9, D10 locked as proposed with his additions; D6, D7, D11 locked with his changes. Code lives in `backend/workpaper/`.

### D5. The checker knows tax forms, not this packet: LOCKED

Rules refer to form lines and boxes (Sch1.17, W-2 box 16, 1098-C box 4c), document types and printed page text. They never name a packet id (D10, ev-1045, qa-41). A test (`test_rules_do_not_name_packet_ids`) parses every rule file and fails if one does. The tests hold the answer key; the rules do not.

- The packet-id test is the right gate, but it cannot catch an answer key written as page wording ("70%", "installed"). Phrase matching is used only for a cue the pipeline did not extract as a field.
- On camera: show one rule stated in form language, e.g. R08's "W-2 box 15 says CA while the residency periods say the taxpayer left on 7/14", and say the phrase match is only for a cue the pipeline did not extract.
- Result: all 16 dollar errors found with the ERRORS.md tax effect to the dollar; net -8,753 federal, -3,317 California.

### D6. Event shape and what is stored vs derived: LOCKED (changed)

One row per act: actor, role, at, action, targets, payload, reason, base_tip.

- An adjustment stores from, to, the version, and the estimated tax effect at that version's rates. Recomputing the effect on every read would let Helen sign "$1,200" and a later replay show a different number. If rates move, the screen shows a fresh estimate beside the stored one (`effect_view`). The $1,000 partner test reads the stored effect.
- An adjustment's from is the figure on screen after earlier adjustments, not the raw engine value. On replay each adjustment applies only while the current figure still equals its from; otherwise it is stale (a new version changed the line, or an earlier adjustment was undone) and waits for a person.
- Replay order is the integer id assigned inside the insert transaction. Wall-clock `at` is only for "as of this date"; two events can share a second. The store refuses an `at` earlier than the last one, so "as of a date" is always a prefix of the log.
- A sign-off stores the version, every covered value and their fingerprint, so the record shows exactly what was signed.
- Undo is a new event that points at the old one. SQLite triggers refuse UPDATE and DELETE on the events table.

### D7. The 409 rule: LOCKED (changed)

- Notes, questions, answers, evidence and views append and do not move the conflict tip. A view of an SSN must not block a sign-off.
- Guarded acts (sign-off, adjust, verify, accept, disposition, undo, standards) are refused if a newer guarded act overlaps their scope.
- Scope of a line: its area, plus California if it rests on California evidence. Scope of a field: every area that owns its document, plus California only if that field feeds a California figure. California owns no documents. An adjustment to Halvorsen box 16 overlaps wages and California together; verifying box 1 touches only the areas that own the W-2.
- The partner release is refused only when what it depends on changed since the partner looked: the summary fingerprint (which includes the large adjustments), the set of unsigned areas, or the set of open review notes. Priya verifying a Brightpath lot does not give Helen a 409.
- The rule needs the packet, so the store is handed a `ConflictRule(packet)` instead of importing one.

### D8. Computed lines belong to the return; California is a signature over a view: LOCKED (refines D3, resolves its REVISIT)

AMT, NIIT, the QBI limit, credits that phase out with AGI, penalties and amount owed move whenever anything moves, so they sit under the partner's signature. Computed California tax and the refund sit there too, in the version summary.

California gets a real preparer tick and a real reviewer tick, and it owns no documents. It is a signature over a view, not a ninth owner of the W-2.

- The wages area still fingerprints Halvorsen box 1 and box 16 together (F1040.1a and SchCA540NR.1.E), so wages cannot be signed without the state boxes in view. An adjustment to the box 16 figure lifts both signatures.
- The lens fingerprints the allocation and the California-only figures: the residency dates, the state split of items other areas own (the California lines that rest on California evidence), the Ridgeline state supplement, California depreciation, and the FTB payments, including the September payment tagged as tax year 2024.
- Fields in the lens are named by what they are ("Meridian Brokerage int_3"), not by which copy they were read from. A corrected 1099 that repeats the same California figure leaves the lens in place.
- An unsigned lens blocks the partner release, like an unsigned area.
- Documents belong to the areas whose lines use them. A document that only feeds return-level lines belongs with the same issuer's other documents (the Ridgeline state supplement goes with its K-1, in passthroughs).

Checked against the packet:
- v1 to v2 (corrected Meridian 1099): moves federal gain, so investments reopens (cause D31) and the partner release lifts because the summary moved. The lens stays in place.
- v2 to v3: passthroughs, payments, rentals, investments and the lens reopen; wages does not. The lens's cause is D38, the Ridgeline state supplement (its California share and SchCA540NR.17.E).
- Each reopened value names its cause. The extension payment (Sch3.10) names `timeline:extension-2026-04-14`: it shares a version with the K-1 but is not caused by it.

### D9. Findings have stable codes and are answered, not edited: LOCKED (with changes)

- Ids use a stable check code: `ESTIMATES_VS_TRANSCRIPT:F1040.26`. Rule numbers (R01 to R13) are only a display group and may be renumbered without breaking old judgments.
- The headline tax effect comes from building each corrected line once. Each proposed change names the piece of the line it corrects (a source value, a payment, a lot, a page). Two findings on the same piece share those dollars and count once (both F540NR.72 findings remove the same Sep 15 payment, ev-1075). A second piece on the same line is a real second correction and counts too (phone and internet on SchC.25).
- A judgment call marks the finding accepted. It stays visible and leaves the tax-effect total. It must record the authority relied on (firm rule); without one it answers nothing.
- An adjustment or disposition pointing at a finding marks it addressed.

### D10. Partner release covers the bottom line plus large adjustments: LOCKED

The release fingerprints the version summary plus every adjustment whose stored effect is over 1,000. The release event lists the large adjustments it approves, so Helen signs once; they are not separate blockers. A small receipt does not lift the release; a large adjustment does. Release is blocked by open review notes and unsigned areas.

### D11. Sensitive data: LOCKED (changed)

- The leak is the printed page, not just the extracted values: the simulated W-2 prints the full SSN in `printed_content`, and pages carry bank account numbers and the IP PIN.
- Mask on the way out, server-side, by value_type (ssn, account numbers) and by any SSN-shaped string in any text, including printed pages. To build in step 2.
- Findings keep the writing rule: messages show the last four digits; full numbers only in `details` under keys starting with `ssn`.
- An unmasked view is an audit event (`view_sensitive`). Like a note, it does not move the conflict tip.

## Step 2 build decisions (OPEN until Rohan locks them)

The API, roles, masking and live updates (2026-10-14). Code: `backend/workpaper/api.py`, `roles.py`, `actions.py`, `masking.py`, `views.py`, `live.py`.

### D12. Identity comes from the role switcher: OPEN

The switcher sets a cookie (`wp_person`; header `X-Person` also works for tools and tests). There is no real authentication in the prototype. Everything after "who you are" is enforced on the server. A cookie rather than a header because the browser's live-update connection (EventSource) cannot send custom headers.

### D13. Everyone sees masked data; one logged door out: OPEN (implements D11)

- Every JSON response passes through the masker on its way out (the default response class), so an endpoint cannot forget. The masker builds its list from the packet's own labels (value_type ssn and account_number, PIN fields, the household's SSNs, IP PINs and bank numbers, the e-file signature PINs) and also masks anything SSN-shaped, including text people type into notes.
- Helen sees masked data too. Unmasked values leave only through `POST /api/unmask`, which needs clearance and appends a `view_sensitive` event first. Marcus gets 403 and nothing is logged.
- A file cannot be masked, so downloading an attachment counts as an unmasked view: clearance required, and logged. A client can download only what they uploaded.
- Unmask records are an audit trail, not a change to the workpaper: they stay out of "since I last looked" and the live stream, and appear in the view log (`/api/audit/sensitive-views`, partner and administrator).
- The log stores what people typed, unmasked. Masking is applied on the way out, never by rewriting the record.

### D14. Writes: the browser sends intent, the server computes the rest: OPEN

`POST /api/actions` with the action, targets, the person's choice (a new figure, a waiver sentence, a verification type), a reason and the log tip they saw. The server then:

1. refuses with 403 if the role may not do this at all;
2. computes everything derived: an adjustment's from and stored effect, a sign-off's covered values and fingerprint and level (from the role, not the browser), the values an acceptance covers;
3. refuses with 422 if a firm rule is broken: judgment calls need an authority; adjustments need a reason; verification types come from the firm's five; a person may not review work they prepared (including lines they adjusted in that area); the partner release needs no blockers;
4. appends, or returns 409 with the event that landed first.

New rule to confirm: **signing an area that has open error findings needs a waiver sentence** (D3 allows signed waivers; this makes signing over open items explicit instead of silent).

### D15. Live updates and "since I last looked": OPEN

Server-sent events. After an append the API publishes the event; each open stream sends it, masked and filtered for that person (clients see questions sent to the client and their own acts; the examiner's view is frozen, so no live events). A reconnecting browser sends Last-Event-ID and gets the missed events from the log first. "Since I last looked" is the log after the person's stored last-seen id, minus their own acts.

### D16. Reads are cached by log tip: OPEN

project() and the checker are pure, so the server keeps one result and rebuilds it only when the log tip moves. About 0.25 seconds per change; reads are milliseconds.

### D17. Clients and the examiner: OPEN

Clients have a separate question surface (`/api/client/questions`, answer, upload) and get 403 on the workpaper. The examiner reads the workpaper masked and can do nothing; freezing it at filing comes in step 5.

## Build plan

1. Hunt the remaining planted errors (6 leads above so far).
2. Lock idea and data model. DONE (D1 to D3 locked; stack pending confirmation).
3. Core: return home (two-year strip, areas), document viewer with simulated pages, click-to-trace, checker.
4. Workflow: document disposition and acceptance, adjustments with tax effect, review notes, area sign-offs with reopen, waivers, roles, client questions, timeline replay.
5. Filing and firm: extension, e-file rejection, freeze and amend, notice response and examiner view, masking and view logs, time vs budget.
6. Deploy, one-pager, error report, video.
