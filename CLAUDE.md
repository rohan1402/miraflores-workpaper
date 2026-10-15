# MiraFlores Workpaper (take-home case study)

Rohan Pant (MS Data Science, Rutgers) is building this as the case study for the **AI Engineer (Tax)** role at MiraFlores AI. Doing it exceptionally well gets him an interview. Rohan records a video explaining every technical decision and will defend the code in an interview, so he must understand everything: explain choices as you go, let him make the calls, and keep the code readable rather than clever.

The brief is `data/Case_Study_Redesign_the_Tax_Workpaper.pdf`. Read it first. The client data is `data/okafor_lindqvist_2025_packet.json` (1.9 MB). Its `readme` key defines every field. Read that too.

## Read these before doing anything

- `docs/DECISIONS.md`: the locked design decisions D1 to D4 and why. Do not reopen a LOCKED decision without asking Rohan.
- `docs/ERRORS.md`: the errors already found in the packet, with evidence, tax effect, and the 13 checker rules they imply. The checker must surface all of them.

## What we are building (deliverables)

1. A working web app at a link, loading the packet **as delivered**, saving everything, with a role switcher.
2. One page on the core idea and data model.
3. The errors found, and how the design surfaced them.
4. A video walkthrough (Rohan records it; we draft the script).
Also: say how AI was used.

## Core idea

A map of where every number came from, plus a permanent record of everything people did to those numbers. The workpaper is that record.

- Layer 1: the packet, read-only, never edited. documents > pages (`printed_content` is the truth) > extracted_values (what the pipeline read, can be wrong) > return lines (`sources` = ev ids, qa ids or refs; `inputs` = other line keys). Three return versions v1, v2, v3 (v3 is current).
- Layer 2: an append-only event log of human actions (who, role, when, targets, action, payload, reason). Current state = `project(packet, events)`.
- Derived live, never stored: checker findings; sign-off validity (fingerprint of covered values vs current).

## Stack (D4, locked)

- One long-lived Python process: **FastAPI** serving a **React (Vite)** frontend. Deploy to Railway or Fly, always-on tier.
- **SQLite in WAL mode** on a persistent volume: events, per-person last-seen event id, attachment metadata. The packet stays a file.
- **Server-sent events** for live updates. Actions are normal POSTs.
- Concurrency: each write carries the log tip the user saw. Notes always append; a sign-off or adjustment against a stale tip returns **409** with the event that landed first.
- **All rules live in Python as pure functions**, testable without the web app: `project()`, the checker, the 409 rule, role masking. The browser only renders role-filtered results. No TypeScript copy of rules.
- **Masking is server-side.** Never ship the raw packet to the browser (Marcus Bell, st-04, has no sensitive-data clearance: SSNs, bank/account numbers, IP PINs masked; every unmask is logged).
- Attachments stored by content hash on the volume; downloads pass the same role check.

## Key product rules (from D1 to D3)

- Home = the return, 2025 vs 2024, grouped by work area, two-year strip at top (AGI, taxable income, total tax, balance due; federal and California). Role is a filter rail that changes default slice and verbs, not a separate home.
- Variance flag: over 10% AND over $1,000 vs prior year (firm standard).
- Large detail collapses: one row per brokerage account tied to its printed summary; lots open underneath.
- Only a person verifies. Machine states: ties, disagreement, conflict, stale. Human states: verified (with one of the 5 firm verification types), adjusted. The machine never says "verified."
- Accept a whole document in one act; accept a brokerage account at its summary when lots tie.
- Document disposition comes first: used, duplicate (D10), superseded (D30), not extracted (D07, D69, D70, D72), partial (D30, D31 page 32).
- Client answers (qa-*, msg-*, call-*) are a distinct kind of evidence.
- Sign-offs: preparer + reviewer (different people) per work area: wages and stock compensation, investments and digital assets, business, rentals and the sale, passthroughs and basis, deductions and credits, payments. California is a cross-cutting lens that can reopen the owning area. Partner signs the return once, plus any adjustment with tax effect over $1,000. Partner release blocked by open review notes or unsigned areas. Sign-offs reopen only when covered values change, against a version, with a reason. Signed waivers allowed.
- Tax effect of an adjustment = change x `return_versions[].tax_effect_rates` (federal and California per dollar). Label it as an estimate. Credits and payments are 1:1. Fully California-source items use `ca_source_income` for the California effect.

## People (packet `firm.staff` and `firm.client_users`)

Priya Raman st-01 preparer; Daniel Ortiz st-02 reviewer; Helen Strand st-03 partner; Marcus Bell st-04 preparer, no clearance; Jo Kimura st-05 administrator (edits firm standards); Sam Adeyemi st-06 quality reviewer (after filing). Clients Ngozi Okafor and Erik Lindqvist get a separate question surface. Plus a frozen read-only examiner view for the 2028 Letter 566.

## Packet facts worth knowing

- 74 documents, 3,012 extracted values (2,663 at confidence >= 0.99; only 2 below 0.80). The real mistakes sit inside the high-confidence values.
- Brightpath D74: 1,826 values, 260 lots, ties to its printed summary to the cent.
- v2 to v3 changed 89 lines; 302 Form 8949 lines in v3.
- Timeline has 29 scripted events through 2028 (e-file rejection, acceptance, payments, notice) for replay.
- `tools/` holds the analysis scripts used to find the errors (run with `python3 -I tools/<script>.py data/okafor_lindqvist_2025_packet.json ...`). They are a starting point for the checker.

## Build order

1. Backend core: packet loader, SQLite event store, `project()`, checker implementing the 13 rules in ERRORS.md, with pytest tests that assert each error in ERRORS.md is found.
2. API + masking + roles + SSE.
3. Frontend: return home (two-year strip, work areas), simulated document view with field highlights (use `position` boxes on rendered `printed_content`; structure it so real page images can replace it), click-to-trace both directions.
4. Workflow: dispositions, accept/verify, adjustments with tax effect, review notes, sign-offs with reopen, waivers, client questions, timeline replay, "since I last looked".
5. Filing and firm: extension, e-file rejection, freeze at filing, amend on top, notice response + examiner view, view logs, time vs budget, search, firm standards editing.
6. Deploy; one-pager; error report from ERRORS.md; video script.

## Writing style for anything Rohan will send or read

Never use em dashes. Use commas, colons or periods. Plain, direct language.
