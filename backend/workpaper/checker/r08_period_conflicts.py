"""R08. Period and year conflicts.

A number can tie to its page and still belong to a different period than the line
uses it for. Three versions of that:

  (a) a document's tax-year field says another year, but the line counts it for this one,
  (b) a part-year resident's W-2 reports a state's wages from an employer outside that state;
      only wages earned while a resident are that state's source income,
  (c) a buyer's closing statement shows the seller paid part of the year's property tax,
      but the return deducts the whole year's bill.

Catches: E13 (Sep 15 payment printed as tax year 2024), E2 (Halvorsen box 16 used whole;
only 22,469 was earned before the move), E7 (home property tax not reduced by the seller's 6,912).
"""

from __future__ import annotations

import re
from datetime import date

from ..taxeffect import estimate
from .common import CONFLICT, Change, Context, Finding, issuer_core, issuer_words, mentions, money

CA_WAGES_LINE = "SchCA540NR.1.E"      # Schedule CA (540NR) line 1, column E: California-source wages
HOME_PROPERTY_TAX_LINE = "SchA.5b"    # Schedule A line 5b: real estate taxes


def check(ctx: Context) -> list[Finding]:
    return _year_fields(ctx) + _part_year_wages(ctx) + _closing_proration(ctx)


# (a) -------------------------------------------------------------------------

def _year_fields(ctx: Context) -> list[Finding]:
    findings = []
    for key, line in ctx.lines.items():
        for ev in ctx.source_values(line):
            if not ev["field"].endswith("_year") or str(ev["value"]) == str(ctx.tax_year):
                continue
            prefix = ev["field"][: -len("_year")]
            siblings = {x["field"]: x for x in ctx.packet.values_by_doc[ev["document_id"]] if x["field"].startswith(prefix + "_")}
            amount = siblings.get(f"{prefix}_amount")
            when = siblings.get(f"{prefix}_date")
            counted = amount and amount["id"] in line["sources"]
            if not counted:
                continue
            category = "payment" if key.startswith(("F1040.2", "F1040.3", "F540NR.7")) else None
            jurisdiction = "california" if line["jurisdiction"] == "california" else "federal"
            effect = estimate(ctx.rates, **{jurisdiction: [(category, -amount["value"])]}) if category else None
            findings.append(Finding(
                id=f"R08:{key}:{ev['id']}", rule="R08", kind=CONFLICT,
                title="Document says another tax year",
                message=(f"{key} ({line['label']}) counts the {when['value'] if when else ''} payment of "
                         f"{money(amount['value'])}, but {ev['document_id']} prints it as tax year {ev['value']} "
                         f"(read at {ev['confidence']})."),
                targets=[f"line:{key}", ev["id"], amount["id"]], evidence=[f"doc:{ev['document_id']}#page{ev['page']}"],
                severity="error",
                changes=[Change(key, ctx.value(key), ctx.value(key) - amount["value"])], effect=effect,
                details={"printed_year": ev["value"], "amount": amount["value"]},
            ))
    return findings


# (b) -------------------------------------------------------------------------

def _employer_state(page: str) -> str | None:
    """The two-letter state at the end of the employer block of a W-2 ('... Austin TX.')."""
    m = re.search(r"Employer (.*?)\. Employee", page)
    if not m:
        return None
    states = re.findall(r"\b([A-Z]{2})\b", m.group(1))
    return states[-1] if states else None


def _part_year_wages(ctx: Context) -> list[Finding]:
    window = ctx.ca_residency()
    line = ctx.lines.get(CA_WAGES_LINE)
    if not window or not line or (window[0] <= f"{ctx.tax_year}-01-01" and window[1] >= f"{ctx.tax_year}-12-31"):
        return []
    findings = []
    for ev in ctx.source_values(line):
        doc = ctx.packet.documents[ev["document_id"]]
        if doc["document_type"] != "W-2" or ev["field"] != "box16":
            continue
        fields = {x["field"]: x for x in ctx.packet.values_by_doc[doc["id"]]}
        page = ctx.packet.page_text(doc["id"], ev["page"])
        employer_state = _employer_state(page)
        if fields.get("box15_state", {}).get("value") != "CA" or employer_state in (None, "CA"):
            continue
        findings.append(_part_year_finding(ctx, doc, ev, fields, page, employer_state, window))
    return findings


def _part_year_finding(ctx, doc, box16, fields, page, employer_state, window) -> Finding:
    said = [f"{CA_WAGES_LINE} uses all of {doc['id']} box 16 ({money(box16['value'])}) as California wages. "
            f"The employer is in {employer_state}, and California residency ended {window[1]}."]
    note = re.search(r"\(([^)]*\d{2}/\d{2}/\d{4}[^)]*)\)", page)
    if note:
        said.append(f"The W-2 itself says: \"{note.group(1)}\"")
    evidence = [f"doc:{doc['id']}#page{box16['page']}"]
    changes, effect = [], None

    stub = _paystub_at_move(ctx, doc, window[1])
    if stub:
        ca_ytd = stub["ev"]["value"]
        drop = box16["value"] - ca_ytd
        old = ctx.value(CA_WAGES_LINE)
        changes.append(Change(CA_WAGES_LINE, old, old - drop))
        effect = estimate(ctx.rates, california=[("ca_source_income", -drop)])
        evidence.append(stub["ev"]["id"])
        said.append(f"The paystub {stub['doc']} shows California taxable wages {money(ca_ytd)} year to date as of "
                    f"{stub['as_of']}: California-source wages from this employer should be about {money(ca_ytd)}, "
                    f"not {money(box16['value'])}.")
    for a in ctx.packet.client_items.values():
        if a["kind"] != "questionnaire" or not ctx.visible(a["at"]):
            continue
        text = a["answer"]
        if mentions(text, issuer_words(doc["issuer"], 1)) or ("california" in text.lower() and "employer" in text.lower()):
            evidence.append(a["id"])
            said.append(f"{a['id']}: \"{text}\"")
    withheld = fields.get("box17")
    if withheld:
        said.append(f"The {money(withheld['value'])} withheld (box 17) still counts as a California payment.")
    return Finding(
        id=f"R08:{CA_WAGES_LINE}:{doc['id']}", rule="R08", kind=CONFLICT,
        title="State wages outside the residency period",
        message=" ".join(said), targets=[f"line:{CA_WAGES_LINE}", box16["id"]], evidence=evidence,
        severity="error", changes=changes, effect=effect,
        details={"employer_state": employer_state, "residency_end": window[1]},
    )


def _paystub_at_move(ctx: Context, w2: dict, residency_end: str) -> dict | None:
    """A paystub from the same employer whose year-to-date figures stop at the move."""
    for d in ctx.documents():
        if d["document_type"] != "paystub" or issuer_core(d["issuer"]) != issuer_core(w2["issuer"]):
            continue
        text = ctx.packet.document_text(d["id"])
        m = re.search(r"[Yy]ear-to-date as of (\d{2})/(\d{2})/(\d{4})", text)
        ca = next((ev for ev in ctx.packet.values_by_doc[d["id"]] if "ca" in ev["field"] and "wages" in ev["field"]), None)
        if not m or not ca:
            continue
        as_of = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if abs((as_of - date.fromisoformat(residency_end)).days) <= 7:
            return {"doc": d["id"], "ev": ca, "as_of": as_of.isoformat()}
    return None


# (c) -------------------------------------------------------------------------

ADDRESS = re.compile(r"\b(\d{3,5} [A-Z][a-z]+ [A-Z][a-z]+)")


def _closing_proration(ctx: Context) -> list[Finding]:
    line = ctx.lines.get(HOME_PROPERTY_TAX_LINE)
    if not line:
        return []
    findings = []
    for d in ctx.documents():
        if d["document_type"] != "closing_statement_buyer":
            continue
        address = ADDRESS.search(d["title"])
        credit = next((ev for ev in ctx.packet.values_by_doc[d["id"]] if "tax" in ev["field"] and ev["value_type"] == "money"), None)
        if not address or not credit:
            continue
        same_property = [ev for ev in ctx.source_values(line)
                         if address.group(1) in ctx.packet.documents[ev["document_id"]]["title"]
                         or address.group(1) in ctx.packet.document_text(ev["document_id"])]
        value = ctx.value(HOME_PROPERTY_TAX_LINE)
        if not same_property or not any(ev["value"] == value for ev in same_property):
            continue  # the line is not the full bill for this property, so the credit may already be out
        findings.append(_proration_finding(ctx, d, credit, address.group(1), value))
    return findings


def _proration_finding(ctx: Context, closing: dict, credit: dict, address: str, value: float) -> Finding:
    quote = re.search(r"Seller credit[^.]*?: [\d,]+\.\d{2}", ctx.packet.document_text(closing["id"]))
    new_5b = value - credit["value"]
    changes = [Change(HOME_PROPERTY_TAX_LINE, value, new_5b)]
    total_line, capped_line = ctx.lines.get("SchA.5d"), ctx.lines.get("SchA.5e")
    fed_itemized_change = -credit["value"]
    if total_line and capped_line:
        old_total, old_capped = ctx.value("SchA.5d"), ctx.value("SchA.5e")
        new_total = old_total - credit["value"]
        cap = old_capped if old_total > old_capped else None   # the cap for this AGI, when it binds
        new_capped = min(new_total, cap) if cap is not None else new_total
        changes += [Change("SchA.5d", old_total, new_total), Change("SchA.5e", old_capped, new_capped)]
        fed_itemized_change = new_capped - old_capped
    # Federal: only the part below the SALT cap moves itemized deductions.
    # California: no SALT cap, so the whole credit comes out of California itemized deductions.
    effect = estimate(ctx.rates, federal=[("itemized", fed_itemized_change)],
                      california=[("salt", -credit["value"])])
    return Finding(
        id=f"R08:{HOME_PROPERTY_TAX_LINE}:{closing['id']}", rule="R08", kind=CONFLICT,
        title="Property tax for a period before the purchase",
        message=(f"{HOME_PROPERTY_TAX_LINE} deducts the full {money(value)} bill for {address}, but the buyer's closing "
                 f"statement {closing['id']} says \"{quote.group(0) if quote else money(credit['value'])}\". The seller "
                 f"paid that part; the buyer's deductible share is {money(new_5b)}."),
        targets=[f"line:{HOME_PROPERTY_TAX_LINE}"], evidence=[closing["id"], credit["id"]],
        severity="error", changes=changes, effect=effect,
        details={"seller_credit": credit["value"], "property": address},
    )
