"""R02. Duplicate documents and pages, and superseded documents.

Two documents of the same type from the same issuer for the same year that carry
the same values are one document seen twice. If one is marked CORRECTED, it
supersedes the other. Inside a document, two pages that carry the same values
are one page scanned twice.

The engine may have handled some of these (it counted the Halvorsen W-2 once),
but a person still has to disposition the second copy, or it can be verified
into a second set of wages.

Catches: E18 (phone photo of the Halvorsen W-2), E19 (corrected Meridian 1099),
E6 (mileage log page 3 is a second scan of page 2, so business miles are overstated).
"""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from itertools import combinations

from ..taxeffect import estimate
from .common import CONFLICT, OPEN_ITEM, Change, Context, Finding, issuer_core, money

SAME_VALUES_SHARE = 0.9   # share of fields that must match for two documents to be copies


def check(ctx: Context) -> list[Finding]:
    return _duplicate_documents(ctx) + _duplicate_pages(ctx)


def _fields(ctx: Context, doc_id: str) -> dict:
    return {ev["field"]: ev["value"] for ev in ctx.packet.values_by_doc.get(doc_id, [])}


def _duplicate_documents(ctx: Context) -> list[Finding]:
    groups = defaultdict(list)
    for d in ctx.documents():
        groups[(d["document_type"], issuer_core(d["issuer"]), d["tax_year"], d["belongs_to"])].append(d)

    findings = []
    for docs in groups.values():
        for a, b in combinations(sorted(docs, key=lambda d: d["received_at"]), 2):
            fa, fb = _fields(ctx, a["id"]), _fields(ctx, b["id"])
            union = set(fa) | set(fb)
            if len(union) < 3:
                continue
            same = [k for k in union if fa.get(k) == fb.get(k)]
            if len(same) / len(union) < SAME_VALUES_SHARE:
                continue
            diffs = [{"field": k, "old": fa.get(k), "new": fb.get(k)} for k in sorted(union) if fa.get(k) != fb.get(k)]
            if a.get("marked_corrected") or b.get("marked_corrected"):
                findings.append(_superseded(ctx, a, b, diffs))
            else:
                findings.append(_duplicate(ctx, a, b, diffs))
    return findings


def _duplicate(ctx: Context, original: dict, copy: dict, diffs: list) -> Finding:
    copy_ids = {ev["id"] for ev in ctx.packet.values_by_doc[copy["id"]]}
    used_by = ctx.lines_using(copy_ids)
    in_use = copy["id"] in ctx.version["documents_used"]
    disp = ctx.state.dispositions.get(copy["id"])
    if used_by:
        engine = f"Lines {', '.join(used_by)} use its values, so it may be counted twice."
    else:
        engine = "No line uses its values (the engine matched it), but they could still be verified into a second set."
    finding = Finding(
        id=f"R02:{copy['id']}", rule="R02", kind=OPEN_ITEM,
        title="Duplicate document",
        message=(f"{copy['id']} ({copy['title']}) carries the same {len(copy_ids) - len(diffs)} of "
                 f"{len(copy_ids)} values as {original['id']}. {engine}"
                 + (f" {ctx.version['version']} lists it as used." if in_use else "")),
        targets=[copy["id"]] + [f"line:{k}" for k in used_by],
        evidence=[original["id"], f"doc:{copy['id']}#page1"],
        severity="error" if used_by else "warning",
        details={"duplicate_of": original["id"], "differences": diffs, "lines_using_copy": used_by},
    )
    if disp and disp.disposition == "duplicate":
        finding.status, finding.addressed_by = "addressed", disp.event_id
    return finding


def _superseded(ctx: Context, a: dict, b: dict, diffs: list) -> Finding:
    old, new = (a, b) if b.get("marked_corrected") else (b, a)
    old_ids = {ev["id"] for ev in ctx.packet.values_by_doc[old["id"]]}
    still_used = ctx.lines_using(old_ids)
    switched = next((v["version"] for v in ctx.packet.versions if old["id"] in v["documents_superseded"]), None)
    changed = "; ".join(f"{d['field']} {d['old']} to {d['new']}" for d in diffs)
    disp = ctx.state.dispositions.get(old["id"])
    finding = Finding(
        id=f"R02:{old['id']}", rule="R02", kind=CONFLICT if still_used else OPEN_ITEM,
        title="Superseded by a corrected document",
        message=(f"{new['id']} is marked CORRECTED and replaces {old['id']}. Changed: {changed}. "
                 + (f"The engine switched in {switched}." if switched else "The engine has not switched.")
                 + (f" Lines still using the old document: {', '.join(still_used)}." if still_used else "")),
        targets=[old["id"], new["id"]] + [f"line:{k}" for k in still_used],
        evidence=[f"doc:{new['id']}#page1"],
        severity="error" if still_used else "warning",
        details={"superseded": old["id"], "by": new["id"], "differences": diffs, "engine_switched_in": switched},
    )
    if disp and disp.disposition == "superseded":
        finding.status, finding.addressed_by = "addressed", disp.event_id
    return finding


def _duplicate_pages(ctx: Context) -> list[Finding]:
    findings = []
    for d in ctx.documents():
        by_page = defaultdict(list)
        for ev in ctx.packet.values_by_doc.get(d["id"], []):
            by_page[ev["page"]].append(ev)
        for p1, p2 in combinations(sorted(by_page), 2):
            v1 = [ev["value"] for ev in by_page[p1]]
            v2 = [ev["value"] for ev in by_page[p2]]
            if len(v1) < 5 or v1 != v2:
                continue
            text1, text2 = ctx.packet.page_text(d["id"], p1), ctx.packet.page_text(d["id"], p2)
            similarity = SequenceMatcher(None, text1, text2).ratio()
            findings.append(_duplicate_page(ctx, d, p1, p2, by_page, similarity))
    return findings


def _duplicate_page(ctx: Context, doc: dict, p1: int, p2: int, by_page: dict, similarity: float) -> Finding:
    """Page p2 repeats page p1. If a line adds a value from each, the second one is counted twice."""
    second_ids = {ev["id"] for ev in by_page[p2]}
    first_ids = {ev["id"] for ev in by_page[p1]}
    changes, effect, messages = [], None, []
    for key in ctx.lines_using(second_ids):
        line = ctx.lines[key]
        if not (first_ids & set(line["sources"])):
            continue  # only a problem when the same line also uses the first copy
        dup = [ctx.packet.values[s] for s in line["sources"] if s in second_ids]
        overcount = sum(ev["value"] for ev in dup if isinstance(ev["value"], (int, float)))
        old = ctx.value(key)
        new = old - overcount
        changes.append(Change(key, old, new))
        messages.append(f"{key} adds both copies: {money(old)} should be {money(new)}.")
        changes += _rate_lines_downstream(ctx, key, old, new)
    if len(changes) > 1:
        # A downstream line priced at a per-unit rate (standard mileage) is the dollar effect.
        dollar = changes[-1]
        expense_drop = dollar.original - dollar.proposed
        effect = estimate(ctx.rates, federal=[("schc_profit", expense_drop)], california=[("schc_profit", expense_drop)]) \
            if dollar.line.startswith("SchC.") else None
        messages.append(f"{dollar.line} {money(dollar.original)} should be {money(dollar.proposed)}.")
    return Finding(
        id=f"R02:{doc['id']}#page{p2}", rule="R02", kind=CONFLICT if changes else OPEN_ITEM,
        title="Duplicate page",
        message=(f"{doc['id']} page {p2} carries the same {len(by_page[p2])} values as page {p1} "
                 f"(printed text {similarity:.0%} alike). " + " ".join(messages)).strip(),
        targets=[f"doc:{doc['id']}#page{p2}"] + [f"line:{c.line}" for c in changes],
        evidence=[f"doc:{doc['id']}#page{p1}", f"doc:{doc['id']}#page{p2}"],
        severity="error" if changes else "warning",
        changes=changes, effect=effect,
        details={"page": p2, "duplicate_of_page": p1, "text_similarity": round(similarity, 3)},
    )


def _rate_lines_downstream(ctx: Context, key: str, old: float, new: float) -> list[Change]:
    """Lines computed as this line times an engine rate (e.g. miles x standard mileage rate)."""
    out = []
    for k, line in ctx.lines.items():
        if key not in line["inputs"]:
            continue
        for src in line["sources"]:
            if src.startswith("ref:param."):
                rate = ctx.packet.resolve(src)
                if isinstance(rate, (int, float)) and abs(old * rate - ctx.value(k)) <= 1:
                    out.append(Change(k, ctx.value(k), round(new * rate)))
    return out
