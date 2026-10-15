"""R06. Unread pages and unextracted documents.

A page the pipeline never read is an open item, even if every value it did read
is at 0.99. A document that was not extracted at all must be dispositioned by a
person. The checker reads the unread page itself, and re-adds each broker's lots
against the broker's printed summary, so a gap is explained instead of just flagged.

Catches: E15 (Meridian page 32: lot M18, proceeds 250, basis 310, never read; the
broker's summary is 250 higher than its lots for exactly this reason). Also lists
D07, D69, D70, D72 as needing a disposition, and records that Brightpath ties.
"""

from __future__ import annotations

import re

from ..taxeffect import estimate, gain_category
from .common import DISAGREEMENT, OPEN_ITEM, Change, Context, Finding, amounts_in, lot_fields, money

BROKER_TYPES = {"1099-composite", "1099-B", "1099-DA"}
LOT_ON_PAGE = re.compile(
    r"(?P<lot>[A-Z]+\d+) (?P<desc>.+?) .*?acquired (?P<acquired>\d{4}-\d{2}-\d{2}) sold (?P<sold>\d{4}-\d{2}-\d{2}) "
    r"proceeds (?P<proceeds>[\d,]+\.\d{2}) basis (?P<basis>[\d,]+\.\d{2}) (?P<term>short|long)-term (?P<covered>non)?covered"
)


def check(ctx: Context) -> list[Finding]:
    findings = []
    superseded = set(ctx.version["documents_superseded"])
    gaps = {d["id"]: _summary_vs_lots(ctx, d) for d in ctx.documents() if d["document_type"] in BROKER_TYPES}
    for d in ctx.documents():
        status = d["extraction"]["status"]
        if status == "not_extracted":
            findings.append(_not_extracted(ctx, d))
        elif status == "partial":
            for page in unread_pages(ctx, d):
                findings.append(_unread_page(ctx, d, page, d["id"] in superseded, gaps.get(d["id"])))
    for doc_id, gap in gaps.items():
        if gap and gap["gap"] and not any(f.details.get("explains_gap") == doc_id for f in findings):
            findings.append(_unexplained_gap(ctx, doc_id, gap))
    return findings


PRINTED_MONEY = re.compile(r"\d[\d,]*\.\d{2}")
PAGE_NUMBER = re.compile(r"[Pp]age (\d+)")


def unread_pages(ctx: Context, doc: dict) -> list[dict]:
    """Pages of a partial document the pipeline did not read.

    A page is unread if the pipeline's own reason names it, or if it prints dollar
    amounts but yielded no values. Pages that print nothing to read ("no further
    transactions") are not open items.
    """
    named = {int(n) for n in PAGE_NUMBER.findall(doc["extraction"].get("reason") or "")}
    read = {ev["page"] for ev in ctx.packet.values_by_doc.get(doc["id"], [])}
    return [p for p in doc["pages"]
            if p["page"] in named or (p["page"] not in read and PRINTED_MONEY.search(p["printed_content"]))]


def _summary_vs_lots(ctx: Context, doc: dict) -> dict | None:
    """Re-add the broker's lots and compare with the proceeds the broker printed as its summary."""
    summary = sum(ev["value"] for ev in ctx.packet.values_by_doc.get(doc["id"], [])
                  if not re.match(r"^[A-Z]+\d+_", ev["field"])
                  and ("proceeds" in ev["field"] or ev["field"] == "total")
                  and isinstance(ev["value"], (int, float)))
    lots = lot_fields(ctx.packet, doc["id"])
    lot_total = sum(f["proceeds"]["value"] for f in lots.values()
                    if "proceeds" in f and isinstance(f["proceeds"]["value"], (int, float)))
    if not summary or not lots:
        return None
    gap = round(summary - lot_total, 2)
    if gap == 0:
        ctx.reconciliations.append({"check": "R06", "document": doc["id"], "status": "ties",
                                    "summary_proceeds": summary, "lot_proceeds": lot_total, "lots": len(lots)})
    return {"summary": summary, "lots_total": lot_total, "lots": len(lots), "gap": gap}


def _not_extracted(ctx: Context, d: dict) -> Finding:
    disp = ctx.state.dispositions.get(d["id"])
    finding = Finding(
        code="DOCUMENT_NOT_EXTRACTED", subject=d["id"], rule="R06", kind=OPEN_ITEM,
        title="Document not extracted",
        message=(f"{d['id']} ({d['title']}) was not extracted. Pipeline reason: {d['extraction']['reason']} "
                 f"A person must disposition it and record where its content is used."),
        targets=[d["id"]], evidence=[f"doc:{d['id']}#page1"], severity="warning",
        details={"reason": d["extraction"]["reason"]},
    )
    if disp:
        finding.status, finding.addressed_by = "addressed", disp.event_id
    return finding


def _unread_page(ctx: Context, d: dict, page: dict, superseded: bool, gap: dict | None) -> Finding:
    text = page["printed_content"]
    lot = LOT_ON_PAGE.search(text)
    changes, said = [], []
    page_ref = f"doc:{d['id']}#page{page['page']}"
    explains_gap = None
    if lot:
        proceeds = float(lot["proceeds"].replace(",", ""))
        basis = float(lot["basis"].replace(",", ""))
        gain = round(proceeds - basis, 2)
        box = {("short", True): "B", ("short", False): "A", ("long", True): "E", ("long", False): "D"}[
            (lot["term"], bool(lot["covered"]))]
        key = f"F8949.{box}.{lot['lot']}"
        ca_cat = ctx.ca_effect_category_for_sale(lot["sold"])
        effect = estimate(ctx.rates, federal=[(gain_category(box), gain)],
                          california=[(ca_cat, gain)] if ca_cat else [])
        changes.append(Change(key, None, gain, page_ref, effect))
        said.append(f"It prints lot {lot['lot']}: sold {lot['sold']}, proceeds {money(proceeds)}, basis {money(basis)}, "
                    f"{lot['term']}-term, which is missing from Form 8949 ({key}, gain {money(gain)}).")
        if gap and abs(gap["gap"] - proceeds) < 0.01:
            explains_gap = d["id"]
            said.append(f"The broker's printed summary ({money(gap['summary'])}) is {money(gap['gap'])} more than "
                        f"the {gap['lots']} lots read ({money(gap['lots_total'])}); this page is the difference.")
    elif amounts_in(text):
        said.append(f"The page prints amounts the return does not use: {', '.join(money(a) for a in sorted(amounts_in(text)))}.")
    disp = ctx.state.dispositions.get(d["id"])
    finding = Finding(
        code="PAGE_NOT_READ", subject=f"{d['id']}#page{page['page']}", rule="R06", kind=OPEN_ITEM,
        title="Page never read",
        message=(f"{d['id']} page {page['page']} was not read by the pipeline. " + " ".join(said)
                 + (" This document is superseded; the same page is unread on the corrected copy." if superseded else "")),
        targets=[page_ref] + [f"line:{c.line}" for c in changes],
        evidence=[page_ref],
        severity="info" if superseded else "error",
        changes=[] if superseded else changes,
        details={"explains_gap": explains_gap, "superseded": superseded},
    )
    if disp and disp.disposition == "partial" and page["page"] in disp.detail.get("pages", []):
        finding.status, finding.addressed_by = "addressed", disp.event_id
    return finding


def _unexplained_gap(ctx: Context, doc_id: str, gap: dict) -> Finding:
    return Finding(
        code="BROKER_SUMMARY_GAP", subject=doc_id, rule="R06", kind=DISAGREEMENT,
        title="Broker lots do not add to the printed summary",
        message=(f"{doc_id} prints summary proceeds {money(gap['summary'])}; its {gap['lots']} lots add to "
                 f"{money(gap['lots_total'])} (gap {money(gap['gap'])})."),
        targets=[doc_id], evidence=[f"doc:{doc_id}#page1"], severity="warning", details=gap,
    )
