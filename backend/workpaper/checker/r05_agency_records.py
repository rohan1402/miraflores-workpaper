"""R05. Agency reconciliation.

Payments on the return must agree with what the IRS and the FTB actually hold.
The agency record wins over a confirmation, a client's memory, or the engine.
Each claimed payment is matched to an agency payment (same amount, within a week);
whatever does not match becomes its own correction, named after the source that
carries it (a client answer, a confirmation line), so another check that corrects
the same payment is not counted twice.

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
        source = f"IRS account transcript as of {irs['as_of']}"
        ref = "agency:/irs_account_transcript_2025"
        estimates = [t for t in irs["transactions"] if t["code"] == "670" and "estimated" in t["description"].lower()]
        extension = [t for t in irs["transactions"] if t["code"] == "670" and "extension" in t["description"].lower()]
        findings += _reconcile(ctx, "ESTIMATES_VS_TRANSCRIPT", "F1040.26", estimates, source, ref, "federal")
        if extension:
            findings += _reconcile(ctx, "EXTENSION_VS_TRANSCRIPT", "Sch3.10", extension, source, ref, "federal")
    ftb = ctx.packet.raw["tax_agency_records"]["ftb_account"]
    if ctx.visible(ftb["as_of"]):
        payments = ftb.get(f"tax_year_{ctx.tax_year}_payments", [])
        other_years = {k: v for k, v in ftb.items()
                       if k.startswith("tax_year_") and k != f"tax_year_{ctx.tax_year}_payments"}
        findings += _reconcile(ctx, "ESTIMATES_VS_FTB_ACCOUNT", "F540NR.72", payments,
                               f"FTB account as of {ftb['as_of']}", "agency:/ftb_account", "california", other_years)
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


def _reconcile(ctx: Context, code: str, key: str, agency: list[dict], source: str, agency_ref: str,
               jurisdiction: str, other_years: dict | None = None) -> list[Finding]:
    line = ctx.lines.get(key)
    if line is None:
        return []
    agency_amounts = [(t["date"], float(t["amount"])) for t in agency if isinstance(t["amount"], (int, float))]
    agency_total = sum(a for _, a in agency_amounts)
    claimed_total = ctx.engine(key)
    now = ctx.value(key)
    moved = isinstance(now, (int, float)) and abs(now - claimed_total) > 0.005
    if abs(claimed_total - agency_total) <= 1:
        if not moved:
            ctx.reconciliations.append({"check": code, "line": key, "status": "ties",
                                        "line_value": claimed_total, "agency_total": agency_total, "source": source})
            return []
        # The engine agreed with the agency, and an adjustment moved the line away. The fix is to put
        # it back: one piece of no change from the engine's figure, so what is open is the reverse of
        # what the adjustment stored (D37).
        return [Finding(
            code=code, subject=key, rule="R05", kind=CONFLICT,
            title="Payments do not agree with the agency record",
            message=(f"{key} ({line['label']}) now shows {money(now)}; the {source} shows {money(agency_total)}. "
                     f"The engine's {money(claimed_total)} agreed with the agency; an adjustment moved the line away."),
            targets=[f"line:{key}"], evidence=[agency_ref], severity="error",
            changes=[Change(key, claimed_total, claimed_total, f"{agency_ref}:moved",
                            estimate(ctx.rates, **{jurisdiction: [("payment", 0.0)]}))],
            details={"agency_total": agency_total, "line_value": claimed_total, "now": now, "source": source,
                     "agency_payments": agency_amounts},
        )]

    unmatched_agency = list(agency_amounts)
    claimed = _claimed_payments(ctx, line)
    for when, amount in list(claimed):  # first take out every exact match
        hit = next((p for p in unmatched_agency if p[1] == amount and _days(p[0], when) <= MATCH_WINDOW_DAYS), None)
        if hit:
            unmatched_agency.remove(hit)
            claimed.remove((when, amount))

    changes, explanations, evidence = [], [], [agency_ref]
    for when, amount in claimed:
        component, said = _source_of(ctx, line, when, amount, evidence)
        near = min(unmatched_agency, key=lambda p: _days(p[0], when), default=None)
        if near and _days(near[0], when) <= MATCH_WINDOW_DAYS:
            unmatched_agency.remove(near)
            delta = near[1] - amount
            said.append(f"The agency shows {money(near[1])} on {near[0]}.")
        else:
            delta = -amount
            said += _held_elsewhere(when, amount, other_years or {})
        explanations.append(f"Claimed {when} {money(amount)} has no match. " + " ".join(said))
        changes.append(Change(key, claimed_total, claimed_total + delta, component,
                              estimate(ctx.rates, **{jurisdiction: [("payment", delta)]})))

    residual = (agency_total - claimed_total) - sum(c.delta for c in changes)
    if abs(residual) > 1:  # agency payments the line does not claim at all
        changes.append(Change(key, claimed_total, claimed_total + residual, f"{agency_ref}:unclaimed",
                              estimate(ctx.rates, **{jurisdiction: [("payment", residual)]})))
        explanations.append(f"The agency holds {money(residual)} the line does not claim.")

    if isinstance(now, (int, float)) and abs(now - agency_total) <= 1:
        # A person's adjustment already brought the line into agreement: record that it ties now.
        ctx.reconciliations.append({"check": code, "line": key, "status": "ties", "line_value": now,
                                    "agency_total": agency_total, "source": source, "after_adjustment": True})
    return [Finding(
        code=code, subject=key, rule="R05", kind=CONFLICT,
        title="Payments do not agree with the agency record",
        message=(f"{key} ({line['label']}) claims {money(claimed_total)}; the {source} shows "
                 f"{money(agency_total)}. Difference {money(abs(agency_total - claimed_total))}. "
                 + " ".join(explanations)
                 + (f" The return now shows {money(now)}." if moved else "")).strip(),
        targets=[f"line:{key}"], evidence=evidence, severity="error", changes=changes,
        details={"agency_total": agency_total, "line_value": claimed_total, "now": now, "source": source,
                 "agency_payments": agency_amounts},
    )]


def _source_of(ctx: Context, line: dict, when: str, amount: float, evidence: list) -> tuple[str, list[str]]:
    """Which source carries a claimed payment: a client answer that prints it, or the dated value on a
    confirmation. Returns the component name for the correction and what to say about it."""
    for ref in line["sources"]:
        item = ctx.packet.client_items.get(ref)
        if item and item["kind"] == "questionnaire" and prints_amount(item["answer"], amount):
            evidence.append(ref)
            return ref, [f"It comes from the client's answer {ref}: \"{item['answer'].rstrip('.')}\"."]
    for ev in ctx.source_values(line):
        if ev["value_type"] == "date" and ev["value"] == when:
            prefix = ev["field"].rsplit("_", 1)[0]
            siblings = {x["field"]: x for x in ctx.packet.values_by_doc[ev["document_id"]]}
            said = []
            year_ev = siblings.get(f"{prefix}_year")
            if year_ev and str(year_ev["value"]) != str(ctx.tax_year):
                said.append(f"{ev['document_id']} prints this payment as tax year {year_ev['value']}.")
                evidence.append(year_ev["id"])
            amount_ev = siblings.get(f"{prefix}_amount")
            return (amount_ev["id"] if amount_ev else ev["id"]), said
    return f"payment:{when}:{amount:.2f}", []


def _held_elsewhere(when: str, amount: float, other_years: dict) -> list[str]:
    return [f"The agency holds it under {name.replace('_', ' ')}: {p.get('note', '')}".strip()
            for name, payments in other_years.items() for p in payments
            if p["amount"] == amount and _days(p["date"], when) <= MATCH_WINDOW_DAYS]


def _days(a: str, b: str) -> int:
    return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
