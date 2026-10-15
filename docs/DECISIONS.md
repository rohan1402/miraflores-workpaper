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
- California: a real time budget and a cross-cutting review lens, not an independent signature. Every area shows its state column next to the federal one (e.g. W-2 box 15/16/17 beside box 1). A California finding reopens the area that owns the document. (REVISIT: our interpretation of the mentor's point; confirm during build.)
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

## Build plan

1. Hunt the remaining planted errors (6 leads above so far).
2. Lock idea and data model. DONE (D1 to D3 locked; stack pending confirmation).
3. Core: return home (two-year strip, areas), document viewer with simulated pages, click-to-trace, checker.
4. Workflow: document disposition and acceptance, adjustments with tax effect, review notes, area sign-offs with reopen, waivers, roles, client questions, timeline replay.
5. Filing and firm: extension, e-file rejection, freeze and amend, notice response and examiner view, masking and view logs, time vs budget.
6. Deploy, one-pager, error report, video.
