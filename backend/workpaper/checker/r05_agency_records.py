"""R05. Agency reconciliation.

Payments on the return must agree with what the IRS and the FTB actually hold.
The agency record wins over a confirmation, a client's memory, or the engine.
Each claimed payment is matched to an agency payment (same amount, within a week);
whatever does not match is explained from its source.

Catches: E12 (federal estimates include the client's "4,000 I think"; IRS shows 3,000),
E13 (a California payment the FTB holds as a 2024 credit).
"""

from __future__ import annotations

import re
from datetime import date

from ..taxeffect import estimate
from .common import CONFLICT, Change, Context, Finding, money, prints_amount

NOTE_PAYMENT = re.compile(r"(\d{4}-\d{2}-\d{2}) ([\d,]+\.\d{2})")
MATCH_WINDOW_DAYS = 7


def check(ctx: Context) -> list[Finding]:
    findings = []
    irs = _latest_irs_snapshot(ctx)
    if irs:
        estimates = [t for t in irs["transactions"]
                     if t["code"] == "670" and "estimated" in t["description"].lower()]
        extension = [t for t in irs["transactions"]
                     if t["code"] == "670" and "extension" in t["description"].lower()]
        source = f"IRS account transcript as of {irs['as_of']}"
        findings += _reconcile(ctx, "F1040.26", estimates, source, "agency:/irs_account_transcript_2025", "federal")
        if extension:
            findings += _reconcile(ctx, "Sch3.10", extension, source, "agency:/irs_account_transcript_2025", "federal")
    ftb = ctx.packet.raw["tax_agency_records"]["ftb_account"]
    if ctx.visible(ftb["as_of"]):
        payments = ftb.get(f"tax_year_{ctx.tax_year}_payments", [])
        other_years = {k: v for k, v in ftb.items() if k.startswith("tax_year_") and k != f"tax_year_{ctx.tax_year}_payments"}
        findings += _reconcile(ctx, "F540NR.72", payments, f"FTB account as of {ftb['as_of']}",
                               "agency:/ftb_account", "california", other_years)
    return findings


def _latest_irs_snapshot(ctx: Context) -> dict | None:
    snaps = [s for s in ctx.packet.raw["tax_agency_records"]["irs_account_transcript_2025"] if ctx.visible(s["as_of"])]
    return max(snaps, key=lambda s: s["as_of"]) if snaps else None


def _claimed_payments(ctx: Context, line: dict) -> list[tuple[str, float]]:
    """The payments the line is built from: the engine's own note, else its dated source values."""
    found = [(d, float(a.replace(",", ""))) for d, a in NOTE_PAYMENT.findall(line.get("note") or "")]
    if found:
        return found
    evs = ctx.source_values(line)
    dates = [ev for ev in evs if ev["value_type"] == "date"]
    amounts = [ev for ev in evs if ev["value_type"] == "money"]
    return [(d["value"], a["value"]) for d, a in zip(dates, amounts)]


def _reconcile(ctx: Context, key: str, agency: list[dict], source: str, agency_ref: str,
               jurisdiction: str, other_years: dict | None = None) -> list[Finding]:
    line = ctx.lines.get(key)
    if line is None:
        return []
    agency_amounts = [(t["date"], float(t["amount"])) for t in agency if isinstance(t["amount"], (int, float))]
    agency_total = sum(a for _, a in agency_amounts)
    claimed_total = ctx.value(key)
    if abs(claimed_total - agency_total) <= 1:
        ctx.reconciliations.append({"check": "R05", "line": key, "status": "ties",
                                    "line_value": claimed_total, "agency_total": agency_total, "source": source})
        return []

    unmatched_agency = list(agency_amounts)
    explanations, evidence = [], [agency_ref]
    for when, amount in _claimed_payments(ctx, line):
        hit = next((p for p in unmatched_agency if p[1] == amount and _days(p[0], when) <= MATCH_WINDOW_DAYS), None)
        if hit:
            unmatched_agency.remove(hit)
            continue
        explanations.append(_explain(ctx, line, when, amount, unmatched_agency, other_years or {}, evidence))

    delta = agency_total - claimed_total
    category = "payment"
    effect = estimate(ctx.rates, **{jurisdiction: [(category, delta)]})
    return [Finding(
        id=f"R05:{key}", rule="R05", kind=CONFLICT,
        title="Payments do not agree with the agency record",
        message=(f"{key} ({line['label']}) claims {money(claimed_total)}; the {source} shows "
                 f"{money(agency_total)}. Difference {money(abs(delta))}. " + " ".join(explanations)).strip(),
        targets=[f"line:{key}"], evidence=evidence, severity="error",
        changes=[Change(key, claimed_total, agency_total)], effect=effect,
        details={"agency_total": agency_total, "line_value": claimed_total, "source": source,
                 "agency_payments": agency_amounts},
    )]


def _explain(ctx: Context, line: dict, when: str, amount: float, unmatched_agency: list,
             other_years: dict, evidence: list) -> str:
    """Why one claimed payment has no agency match: which source carries it, and what the agency holds."""
    parts = [f"Claimed {when} {money(amount)} has no match."]
    for ref in line["sources"]:
        item = ctx.packet.client_items.get(ref)
        if item and item["kind"] == "questionnaire" and prints_amount(item["answer"], amount):
            parts.append(f"It comes from the client's answer {ref}: \"{item['answer'].rstrip('.')}\".")
            evidence.append(ref)
    for ev in ctx.source_values(line):
        if ev["value_type"] == "date" and ev["value"] == when:
            prefix = ev["field"].rsplit("_", 1)[0]
            year_ev = next((x for x in ctx.packet.values_by_doc[ev["document_id"]]
                            if x["field"] == f"{prefix}_year"), None)
            if year_ev and str(year_ev["value"]) != str(ctx.tax_year):
                parts.append(f"{ev['document_id']} prints this payment as tax year {year_ev['value']}.")
                evidence.append(year_ev["id"])
    near = min(unmatched_agency, key=lambda p: _days(p[0], when), default=None)
    if near and _days(near[0], when) <= MATCH_WINDOW_DAYS:
        parts.append(f"The agency shows {money(near[1])} on {near[0]}.")
    for name, payments in other_years.items():
        for p in payments:
            if p["amount"] == amount and _days(p["date"], when) <= MATCH_WINDOW_DAYS:
                parts.append(f"The agency holds it under {name.replace('_', ' ')}: {p.get('note', '')}".strip())
    return " ".join(parts)


def _days(a: str, b: str) -> int:
    return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
