# Errors Found in the Okafor-Lindqvist Packet

Raw material for deliverable 3 ("the errors you found, and how your design surfaced them").
Every item below was checked against `documents[].pages[].printed_content` (the truth) and the other records in the packet. Line keys and ev ids refer to return version v3 unless stated.

Tax effects are estimates using v3 `tax_effect_rates` (per-dollar), as the README instructs. Items fully California-source use `ca_source_income` for the California effect. Large changes can cross thresholds, so the real system would recompute. Negative = less tax / bigger refund.

---

## Summary: errors with a dollar effect

| # | Error | Fed effect | CA effect | Check that surfaces it |
|---|---|---:|---:|---|
| E1 | RSU lots N1, N3, N4 taxed at zero basis; supplemental basis (D11) not matched | -15,536 | -2,445 | Supplemental-basis match |
| E2 | Halvorsen W-2 box 16 ($111,300) used as California-source wages; only $22,469 earned before the move | 0 | -5,685 | Residency-period / document-period conflict |
| E3 | Schedule C gross receipts add Form 1099-K $12,400 already deposited and booked in sales | -4,402 | -384 | Same money, two sources |
| E4 | SE health insurance $14,400 deducted though Erik was eligible for Ngozi's employer family coverage (qa-25) | +4,464 | +605 | Client answer contradicts treatment |
| E5 | Donated car deducted at client's $6,000; Form 1098-C shows sold for $2,900 | +806 | +149 | Client answer contradicts document |
| E6 | Mileage log page 3 is a second scan of page 2; business miles 11,800 should be 8,100 | +919 | +80 | Duplicate page; prior-year variance |
| E7 | Home real estate tax: full $13,420 deducted; seller paid $6,912 for 1/1 to 7/7 at closing | +1,462 | +332 | Cross-document period conflict |
| E8 | Lonestar payoff interest $2,150 added on top of Form 1098 that already includes it | +559 | +103 | Same money, two sources |
| E9 | HVAC $11,000 at Fremont Way (whole heat pump system) expensed as repair; should be capitalized | +3,364 | +694 | Classification review prompt |
| E10 | Northlake sweep interest $1,840 counted twice (composite D28 and separate 1099-INT D29) | -640 | -127 | Same money, two sources |
| E11 | Swedish interest converted at 2024 average rate (10.56) instead of 2025 (9.86) | +43 | +9 | Stale reference value |
| E12 | Federal estimates $13,000 include client's "4,000 I think"; IRS transcript shows $3,000 (total $12,000) | +1,000 | 0 | Agency record reconciliation |
| E13 | California estimates $14,000 include Sep 15 payment designated tax year 2024; FTB holds it as a 2024 credit (total $10,500) | 0 | +3,500 | Agency record reconciliation; document field conflict |
| E14 | Crypto lot C6 at zero basis and short-term; client (msg-07, after v3) says bought 3/15/2021 for ~$3,050 | -1,312 | -195 | Evidence newer than the computation |
| E15 | Meridian page 32 never read: lot M18 (proceeds $250, basis $310) missing | -21 | 0 | Unread page = open item |
| E21 | Schedule C personal share per call notes: phone 70% business, internet 50%, Spotify personal | +541 | +47 | Call note evidence vs books |
| | **Net (approximate)** | **-8,753** | **-3,317** | |

At v3 the federal return shows $4,220 due. After these corrections it becomes roughly a $4,500 overpayment. California tax falls by about $6,800 while payments fall by $3,500, so the California refund grows from $8,256 to roughly $11,600. California also holds a separate $3,500 credit on the 2024 account.

---

## Detail

**E1. RSU basis missing.** Northlake 1099-B (D28 p3) prints RSU basis "(not reported)", so N1, N3 and N4 went to Form 8949 at $0 basis. The Corvane supplemental statement (D11 p2) gives adjusted basis: RSU-2502 $19,100, RSU-2505 $19,100, RSU-2308 $9,420. The W-2 confirms it: D08 box 14 RSU $38,200 = 19,100 + 19,100. Engine rule R-8949-LOT uses supplemental basis "only if matched"; the lot ids differ (N1 vs RSU-2502), so the match failed. The ESPP lot did match. RSU income is being taxed twice. Lines: F8949.B.N1, F8949.B.N3, F8949.E.N4.

**E2. California-source wages.** D09 box 15 CA, box 16 $111,300, box 17 $4,180, all at 0.99 and tie to the page. But: residency in CA ended 7/14 (household), D09 itself notes "payroll kept California as the work state through 09/30/2025", qa-45 says this was a mistake, and the 7/18 paystub (D73) shows CA taxable wages $22,469 year-to-date through 7/15. Line SchCA540NR.1.E uses box 16 under rule R-CA-WAGES-SOURCE. The $4,180 withheld still counts as a California payment.

**E3. Gross receipts.** Rule R-SCHC-GROSS adds 1099-K amounts "the engine could not match to a books deposit." D15 p3: Atlas paid $41,200, of which $12,400 came through Paywell card processing, deposited gross and recorded as sales. Reconciliation: 1099-NECs $142,000 + non-1099 clients $9,300 = $151,300 = books revenue. The 2028 Letter 566 (D72) asks for exactly this reconciliation (1099-NEC $142,000 and 1099-K $12,400).

**E4. SE health insurance.** qa-25: "both of Ngozi's employers offer family coverage, but Erik kept his own individual plan." 2024 return (Sch1.17 note) disallowed it for the same reason. D45 shows family HDHP coverage. Sch1.17 = $14,400. The adjustment rate does not capture the QBI increase.

**E5. Vehicle donation.** D66 (Form 1098-C): box 4a sold at arm's length, box 4c gross proceeds $2,900. F8283.A1.vehicle uses qa-39 ("Kelley Blue Book said about 6,000"). Also under examination in the 2028 Letter 566.

**E6. Mileage.** D23 p3 printed text: "(Second scan of the May-Aug sheet - same handwriting and coffee stain as page 2.)" Rule R-MILEAGE-PAGE-TOTALS sums all four page totals (2,600 + 3,700 + 3,700 + 1,800 = 11,800). Correct: 8,100 miles. SchC.9 $8,260 should be $5,670. Prior year was 7,400 miles, so the 59% jump also trips the variance standard.

**E7. Home property tax.** D54: seller credit for 2025 county taxes 1/1 to 7/7: $6,912. D58: full $13,420 paid 12/18 by escrow. Buyer's deductible share is $6,508. SchA.5b uses $13,420. Federal SALT then falls below the $40,000 cap (34,378), so the change reaches taxable income.

**E8. Mortgage interest.** D55 box 1 $13,900 "includes ... interest paid at payoff 11/20/2025." D56 payoff statement: interest $2,150, "(Interest is reported on the 2025 Form 1098.)" SchA.8a adds both.

**E9. HVAC.** D46 lists $11,000 inside repairs. D47 and call-01: removed failed furnace and condenser, installed a new heat pump system, air handler, line set, thermostat, permit. That is a capital improvement: new 27.5-year asset placed in service 8/12/2025 (about $150 depreciation in 2025). Sacramento rental, so fully California-source.

**E10. Interest double count.** SchB.1.1 "Northlake Securities - bank sweep (composite 1099-INT)" $1,840 from D28, and SchB.1.2 "Northlake Bank, N.A." $1,840 from D29. D29 p1: "bank sweep program for Northlake Securities account ending 7731." Same interest. 2024 had one line.

**E11. Stale FX.** SchB.1.6 label: "SEK 18,450.00 at 10.56 SEK/USD" with source `ref:fx.SEK.2024_average`. Packet fx_rates 2025_average = 9.86. Interest $1,747 should be $1,871.

**E12. Federal estimates.** F1040.26 = $13,000: D67 three $3,000 payments plus qa-41 "Paid January 14, 2026 - 4,000 I think" (rule R-ESTIMATED-PAYMENTS falls back to the questionnaire). IRS transcript (D69 data): four $3,000 payments, the last on 1/15/2026. Required step "Estimated payments agreed to IRS and FTB records" would fail.

**E13. California estimates.** F540NR.72 = $14,000 (rule: every FTB payment dated 4/1/2025 to 1/15/2026). D68 pay5 (9/15/2025, $3,500) printed and extracted as tax year 2024 (0.98). FTB account: 2025 payments $10,500; the 9/15 payment "held as a 2024 credit." Action: request FTB transfer or claim refund on 2024.

**E14. Crypto C6.** D35: "TRANSFER-IN 2025-06-01 (cost basis unknown)." Engine used $0 basis and the transfer date (short-term). msg-07 (6/30/2026, after v3): bought on CryptoNorth 3/15/2021 for about $3,050; only evidence is a bank statement line. Judgment: accept with that support attached, or keep zero basis. Lot becomes long-term with gain $2,275 instead of $5,325.

**E15. Unread page.** D30 and D31 extraction status "partial": page 32 not read. Printed: M18 Ironwood REIT cash in lieu, proceeds $250, basis $310, short-term noncovered. Engine diagnostic flags the $250 summary-vs-detail gap but does not say why. Small dollars, but the IRS has this 1099-B line; the 2023 CP2000 (D70) was exactly an unreported 1099-B sale.

**E21. Personal expenses in books.** call-01: mobile plan 4 lines, business share 70% (books $2,160, deduct $1,512); home internet 50% (books $1,320, deduct $660); Spotify Family $216 is personal. Schedule C expenses fall by $1,524. Note: with the simplified home office method, internet is arguable; recorded as a preparer judgment with the client's estimate as evidence.

---

## Errors with no direct dollar effect (still must be caught)

- **E16. Care provider EIN misread.** D62 printed "Tax ID 74-3829156"; extracted ev-1045 "74-3829516" (0.97). Flows to F2441.1b. Wrong provider TIN on Form 2441 undermines the $5,000 dependent care exclusion. Surfaced by value-vs-page check (one of only 11 values that do not appear on their page).
- **E17. Theo's SSN.** Household (client organizer) 666-74-3309; Social Security card D71 (arrived 7/13/2026) 666-74-3390. Caused the 7/13 federal e-file rejection R0000-504-02 and the California hold. Surfaced by "Identity verified" required step: dependent SSNs have no document behind them until D71.
- **E18. Duplicate W-2 image.** D10 is a phone photo of D09. Engine counted once (F1040.1a note), but D10's 17 values are all 0.99 and could be verified into a second set of wages. Surfaced by document disposition = duplicate.
- **E19. Superseded 1099.** D31 (corrected) replaces D30: M9 basis 6,900 to 4,880, M6 wash 735 to 512, M14 short to long term (acquired 2024-10-15 to 2024-09-15). Engine handled in v2. Surfaced by disposition = superseded and sign-off reopening.
- **E20. Handwritten church receipt.** D64 printed "$?,500.00 ... first digit ambiguous (could be read as 1 or 7)"; extracted $1,500 at 0.41. msg-08: parish confirmed $1,500 by phone, bank check #2207. Amount resolved, but the receipt has no goods-or-services statement, which a gift of $250+ needs. Action: obtain a proper acknowledgment.
- **E29. Provider name.** F2441.1a label says "Bright Oak Preschool"; D61 and the 2024 return say "Bright Oak Kids Club." Cosmetic but lands on the filed form.

## Judgment calls the workpaper must record (not errors, decisions)

- **J1. SEP excess.** Contribution $18,000 (D26). Limit is 20% of (net profit minus half SE tax): $15,214 at v3, lower after E3/E6/E21. Excess must be withdrawn by the extended due date or it faces a 6% excise each year.
- **J2. Equipment method.** what_if `equipment_section179`: electing section 179 instead of 100% bonus leaves federal tax unchanged and saves California $1,050. Equipment is 100% business use (call-01). Recommend the election; record it.
- **J3. California AMT on the ISO exercise.** 1,000 shares, spread $40,000 (D12), granted 2022 by a California employer, exercised 7/30/2025 after the move. Engine does not compute California AMT (F540NR.61 = 0). Needs manual Schedule P (540NR) review.
- **J4. Condo held for sale.** Unit listed 10/1 after the lease ended 9/30; October HOA and similar costs while only held for sale are questionable Schedule E expenses. Small.
- **J5. Rental insurance $1,850** rests only on qa-36 (no document). Accept with client confirmation or request the policy.
- **J6. Late federal balance.** Extension paid $36,000 (based on v2). Whatever remains due after 4/15 accrues interest (7%) and failure-to-pay (0.5%/month). After corrections the federal return likely shows an overpayment, which changes the 7/20 "balance paid" event.

## Client answers that conflict with documents

- qa-14 "No" investment sales vs 282 brokerage lots and 12 digital asset sales (engine diagnostic).
- qa-15 "didn't really sell, just moved things around" vs 12 dispositions on Form 1099-DA.
- qa-31 "Prior basis: none ... we started doing this in 2025" vs 2024 Form 8606 line 14 = $7,000 (2024 contribution made 2/12/2025). Documents win; engine correctly uses $14,000 total basis; taxable conversion $26.
- qa-39 car "about 6,000" vs 1098-C $2,900 (E5).
- qa-41 "4,000 I think" vs IRS $3,000 (E12).
- qa-25 eligible for employer coverage vs SEHI deduction (E4).

## Filings outside this return that the workpaper must identify

- **Form 3520 for 2023**: Erik's inheritance from his mother (Sparbanken account opened 09/2023, balances over $100,000). Prior preparer left it open ("discussed? no note of resolution"). Late filing penalties can be severe; raise with partner.
- **FinCEN 114 (FBAR) for 2025**: max balance SEK 1,452,300 (about $149,567). Due 10/15/2026, outside engagement.
- **Forms 1099-NEC for 2025**: Quintero $4,800, Patel $2,600 (D27). Due 2/2/2026, not filed (qa-23). Late.
- **Form 8938**: required (year-end ~$123,254 > $100,000); in the return.
- **Ada's own 2025 return**: filed by her with consumer software; must show she can be claimed (related return).
- **Oregon composite (Woodworks)** and **Arizona composite (Ridgeline)**: filed by the entities; no partner filing needed (D38, D39).
- **Form 8801 in 2026**: minimum tax credit from the 2025 ISO AMT.

## Prior preparer vs us

- 2024 home office claimed 300 sq ft; Erik's measurements (D24) show the Sacramento studio was 220 sq ft. 2024 deduction overstated by about $400 (300 x $5 vs 220 x $5). Note for the "prior preparer vs what we changed" record.
- 2024 S corp basis "assumed sufficient": with the 2023 K-1 (D40) it rolls 21,300 to 15,400 (2023) to 2,300 (2024). It was sufficient. 2025 distributions exceed basis by $21,215 (F7203.excess), now correct in v3.
- 2024 8606 basis $7,000 confirmed by D42.

## Things that look wrong but are right (the app should show why)

- Brightpath (D74): 260 lots tie to the printed summary to the cent (proceeds 334,728.52; basis 338,300.26; wash 2,906.29). Accept at the summary.
- All lot holding periods (D74, D31, D28, D35) are consistent with their dates.
- Depreciation roll-forwards (AUS-BLDG accumulated 50,339.99 used in Form 4797; SAC-APPL California year 5 = $484) recompute correctly.
- Excess social security $3,342 (two employers) and additional Medicare tax $500 recompute correctly.

---

## What this means for the checker (build list)

Each finding maps to a check that does not trust the engine:

1. **Value vs page**: every extracted value must appear on its printed page (E16; 11 of 3,012 fail).
2. **Duplicate document / page**: same issuer, same amounts, or page text that says "second scan" (E6, E18).
3. **Same money, two sources**: a line whose sources include two documents describing the same payment (E3, E8, E10).
4. **Unmatched supplemental**: broker basis zero or "not reported" while a supplemental statement or W-2 box 14 shows basis (E1).
5. **Agency reconciliation**: payments vs IRS transcript and FTB account (E12, E13).
6. **Partial extraction**: any unread page is an open item until dispositioned (E15).
7. **Client answer vs treatment**: questionnaire or message contradicts a line or document (E4, E5, qa-14, qa-15, qa-31).
8. **Period / year conflict**: document year field, residency dates, closing-statement proration vs line use (E2, E7, E13).
9. **Stale reference**: line cites a reference value from the wrong year (E11).
10. **Prior-year variance**: firm standard over 10% and over $1,000 (E6 mileage, SEHI 0 to 14,400, gross receipts).
11. **Classification prompt**: repairs over a threshold or with replace/install wording (E9).
12. **Identity**: SSNs and names without a supporting document (E17).
13. **Evidence newer than computation**: messages or documents dated after the version they would change (E14, msg-08).
