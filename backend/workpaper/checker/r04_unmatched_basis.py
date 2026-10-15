"""R04. Unmatched supplemental basis.

A sale reported with zero or "not reported" basis is taxed on its full proceeds.
For stock compensation that is almost always wrong: the shares' basis is the
income already taxed on the W-2. The checker looks for that basis elsewhere in
the packet (a stock plan supplemental statement lot with the same acquisition
date, and W-2 box 14) instead of trusting the engine's "only if matched" rule.

Lots with no basis and no supporting document are reported as open items.

Catches: E1 (RSU lots N1, N3, N4 at zero basis; the supplement gives 19,100,
19,100 and 9,420). Also surfaces the Coinhaven C6 lot (E14) as missing basis.
"""

from __future__ import annotations

from ..taxeffect import gain_category, estimate
from .common import CONFLICT, OPEN_ITEM, Change, Context, Finding, line_sources_by_field, money

SUPPLEMENT_TYPES = {"stock_plan_supplement"}


def check(ctx: Context) -> list[Finding]:
    supplements = _supplement_lots(ctx)
    matched: dict[str, list] = {}
    findings = []
    for key, line in ctx.lines.items():
        if not key.startswith("F8949."):
            continue
        basis = line_sources_by_field(ctx, line, "_basis")
        if basis is None or basis["value"] not in (0, None):
            continue
        if basis["value"] == 0 and (basis.get("text_as_read") or "").strip() not in ("", "not reported"):
            continue  # a real printed zero
        acquired = line_sources_by_field(ctx, line, "_acquired")
        sold = line_sources_by_field(ctx, line, "_sold")
        match = supplements.get(acquired["value"]) if acquired else None
        if match:
            matched.setdefault(match["doc"], []).append((key, line, basis, sold, match))
        else:
            findings.append(_missing(ctx, key, line, basis))
    for doc_id, lots in matched.items():
        findings.append(_unmatched(ctx, doc_id, lots))
    return findings


def _supplement_lots(ctx: Context) -> dict[str, dict]:
    """{acquired date: {doc, lot, basis ev}} from every stock plan supplemental statement."""
    out = {}
    for d in ctx.documents():
        if d["document_type"] not in SUPPLEMENT_TYPES:
            continue
        for lot, fields in lot_fields_with_dashes(ctx, d["id"]).items():
            if "acquired" in fields and "adjusted_basis" in fields:
                out[fields["acquired"]["value"]] = {"doc": d["id"], "lot": lot, "basis": fields["adjusted_basis"]}
    return out


def lot_fields_with_dashes(ctx: Context, doc_id: str) -> dict[str, dict]:
    """Supplement lots look like 'RSU-2502_adjusted_basis'; group by the part before the field name."""
    lots: dict[str, dict] = {}
    for ev in ctx.packet.values_by_doc.get(doc_id, []):
        lot, sep, name = ev["field"].partition("_")
        if sep:
            lots.setdefault(lot, {})[name] = ev
    return lots


def _unmatched(ctx: Context, doc_id: str, lots: list) -> Finding:
    changes, targets, evidence = [], [], [doc_id]
    lines_text = []
    for key, line, basis_ev, sold_ev, match in lots:
        new_basis = match["basis"]["value"]
        box = key.split(".")[1]
        old = ctx.value(key)
        ca_cat = ctx.ca_effect_category_for_sale(sold_ev["value"]) if sold_ev else None
        effect = estimate(ctx.rates, federal=[(gain_category(box), -new_basis)],
                          california=[(ca_cat, -new_basis)] if ca_cat else [])
        changes.append(Change(key, old, round(old - new_basis, 2), basis_ev["id"], effect))
        targets += [f"line:{key}", basis_ev["id"]]
        evidence.append(match["basis"]["id"])
        lines_text.append(f"{key.split('.')[-1]} = {match['lot']} {money(new_basis)}")
    corroboration = _w2_box14(ctx, doc_id, [m for *_, m in lots])
    if corroboration:
        evidence.append(corroboration["ev"])
    total = sum(m["basis"]["value"] for *_, m in lots)
    return Finding(
        code="SUPPLEMENT_BASIS_UNUSED", subject=doc_id, rule="R04", kind=CONFLICT,
        title="Basis on a supplemental statement was not used",
        message=(f"{len(lots)} lots went to Form 8949 at zero basis, but {doc_id} "
                 f"({ctx.packet.documents[doc_id]['title']}) gives their basis: {'; '.join(lines_text)} "
                 f"(total {money(total)}). The same income is already on the W-2, so it is being taxed twice."
                 + (f" W-2 box 14 RSU {money(corroboration['value'])} agrees." if corroboration else "")),
        targets=targets, evidence=evidence, severity="error",
        changes=changes,
        details={"supplement": doc_id, "basis_total": total},
    )


def _w2_box14(ctx: Context, supplement_doc: str, matches: list) -> dict | None:
    """W-2 box 14 RSU income for the year should equal the basis of RSUs that vested this year."""
    vested_this_year = sum(m["basis"]["value"] for m in matches
                           if m["lot"].startswith("RSU") and str(ctx.tax_year) in str(_acquired(ctx, m)))
    for d in ctx.documents():
        if d["document_type"] != "W-2":
            continue
        for ev in ctx.packet.values_by_doc[d["id"]]:
            if ev["field"].lower() == "box14_rsu" and abs(ev["value"] - vested_this_year) <= 1:
                return {"ev": ev["id"], "value": ev["value"]}
    return None


def _acquired(ctx: Context, match: dict) -> str:
    lots = lot_fields_with_dashes(ctx, match["doc"])
    return lots[match["lot"]]["acquired"]["value"]


def _missing(ctx: Context, key: str, line: dict, basis_ev: dict) -> Finding:
    return Finding(
        code="SALE_BASIS_MISSING", subject=key, rule="R04", kind=OPEN_ITEM,
        title="Sale with no basis and no supporting document",
        message=(f"{key} ({line['label']}) is taxed at zero basis. "
                 f"{basis_ev['document_id']} reads the basis as {basis_ev['value']!r} "
                 f"(confidence {basis_ev['confidence']}). No document in the packet supplies it."),
        targets=[f"line:{key}", basis_ev["id"]], evidence=[basis_ev["document_id"]],
        severity="warning",
        details={"basis_read": basis_ev["value"], "confidence": basis_ev["confidence"]},
    )
