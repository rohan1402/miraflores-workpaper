"""R13. Evidence newer than the computation.

The engine's latest version was computed at a moment. Anything that arrived after
it (a client message, a call, a document) was not in that computation. The checker
lists each one and links it to what it may change: the documents of any issuer it
names, the household members it names, and the lines built from those documents.

When a message gives a cost and a purchase date for a sale with no basis, the
checker drafts the change. A person decides whether the support is enough.

Catches: E14 (msg-07: the C6 bitcoin was bought 03/15/2021 for about 3,050), msg-08
(the parish confirmed the 1,500 gift), and D71 / msg-10 (Theo's Social Security card).
"""

from __future__ import annotations

import re
from datetime import date

from ..taxeffect import estimate
from .common import STALE, Change, Context, Finding, issuer_words, line_sources_by_field, money

COST = re.compile(r"for about ([\d,]+(?:\.\d{2})?)|cost (?:of )?([\d,]+(?:\.\d{2})?)")
DATE_MDY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def check(ctx: Context) -> list[Finding]:
    computed = ctx.version["computed_at"]
    findings = []
    for item in ctx.packet.client_items.values():
        if item["kind"] in ("message", "call_note") and item["at"] > computed and ctx.visible(item["at"]):
            findings.append(_client_item(ctx, item, computed))
    for d in ctx.documents():
        if d["received_at"] > computed:
            findings.append(_document(ctx, d, computed))
    return findings


def _text(item: dict) -> str:
    return " ".join(item.get("notes") or [item.get("text") or ""])


def _client_item(ctx: Context, item: dict, computed: str) -> Finding:
    text = _text(item)
    docs = _documents_named(ctx, text)
    people = [p["id"] for p in ctx.packet.people.values() if p["name"].split()[0] in text]
    lines = _lines_from(ctx, docs, text)
    changes, drafted = [], ""
    basis = _drafted_basis(ctx, lines, text)
    if basis:
        changes, drafted = basis
    linked = [f"line:{k}" for k in lines] + docs + [f"household:{p}" for p in people]
    return Finding(
        code="EVIDENCE_AFTER_COMPUTATION", subject=item["id"], rule="R13", kind=STALE,
        title="Evidence arrived after the return was computed",
        message=(f"{item['id']} ({item['at'][:10]}) arrived after {ctx.version['version']} was computed "
                 f"({computed[:10]}): \"{text}\""
                 + (f" It concerns {', '.join(linked)}." if linked else " It names nothing on the return.")
                 + drafted),
        targets=linked or [item["id"]], evidence=[item["id"]],
        severity="warning" if linked else "info",
        changes=changes,
        details={"arrived": item["at"], "version_computed": computed},
    )


def _document(ctx: Context, d: dict, computed: str) -> Finding:
    belongs = d["belongs_to"]
    person = belongs.split(":", 1)[1] if belongs.startswith("dependent:") else None
    return Finding(
        code="EVIDENCE_AFTER_COMPUTATION", subject=d["id"], rule="R13", kind=STALE,
        title="Document arrived after the return was computed",
        message=(f"{d['id']} ({d['title']}) was received {d['received_at'][:10]}, after "
                 f"{ctx.version['version']} was computed ({computed[:10]}). Nothing in the return uses it yet."),
        targets=[d["id"]] + ([f"household:{person}"] if person else []), evidence=[f"doc:{d['id']}#page1"],
        severity="warning",
        details={"arrived": d["received_at"], "version_computed": computed},
    )


def _documents_named(ctx: Context, text: str) -> list[str]:
    """Documents whose issuer the text names (first one or two words of the issuer)."""
    out = []
    plain = re.sub(r"[^a-z0-9 &]", "", text.lower())  # same normalization as issuer names: 'St. Brigid' -> 'st brigid'
    for d in ctx.documents():
        for n in (2, 1):
            name = issuer_words(d["issuer"], n)
            if len(name) >= 5 and re.search(rf"\b{re.escape(name)}\b", plain):
                out.append(d["id"])
                break
    return out


def _lines_from(ctx: Context, docs: list[str], text: str) -> list[str]:
    """Lines built from those documents; narrowed to sales with no basis if the text is about cost."""
    lines = [k for k, line in ctx.lines.items() if {ev["document_id"] for ev in ctx.source_values(line)} & set(docs)]
    if re.search(r"\b(cost|basis)\b", text.lower()):
        missing = [k for k in lines if (b := line_sources_by_field(ctx, ctx.lines[k], "_basis")) and b["value"] in (0, None)]
        if missing:
            return missing
    return lines


def _drafted_basis(ctx: Context, lines: list[str], text: str):
    """A message that gives cost and purchase date for a no-basis sale: draft the corrected lot."""
    if len(lines) != 1 or not lines[0].startswith("F8949."):
        return None
    cost_m, date_m = COST.search(text), DATE_MDY.search(text)
    if not cost_m or not date_m:
        return None
    key = lines[0]
    line = ctx.lines[key]
    cost = float((cost_m.group(1) or cost_m.group(2)).replace(",", ""))
    acquired = date(int(date_m.group(3)), int(date_m.group(1)), int(date_m.group(2)))
    sold_ev = line_sources_by_field(ctx, line, "_sold")
    proceeds_ev = line_sources_by_field(ctx, line, "_proceeds")
    if not sold_ev or not proceeds_ev:
        return None
    sold = date.fromisoformat(sold_ev["value"])
    proceeds = proceeds_ev["value"]
    long_term = (sold - acquired).days > 365
    box = key.split(".")[1]
    new_box = {"G": "J", "H": "K", "I": "L", "A": "D", "B": "E", "C": "F"}.get(box, box) if long_term else box
    new_gain = round(proceeds - cost, 2)
    old_gain = ctx.value(key)
    new_key = key.replace(f".{box}.", f".{new_box}.")
    fed = [("stcg" if box in "ABCGHI" else "ltcg", -old_gain), ("ltcg" if long_term else "stcg", new_gain)]
    ca_cat = ctx.ca_effect_category_for_sale(sold_ev["value"])
    effect = estimate(ctx.rates, federal=fed, california=[(ca_cat, new_gain - old_gain)] if ca_cat else [])
    lot = line_sources_by_field(ctx, line, "_basis")["id"]  # the component: this lot's basis
    changes = [Change(key, old_gain, None if new_key != key else new_gain, lot, effect)]
    if new_key != key:  # the lot moves to the long-term box; the effect is already on the first change
        changes.append(Change(new_key, None, new_gain, lot))
    drafted = (f" Draft: basis {money(cost)}, acquired {acquired.isoformat()}, so the sale is "
               f"{'long' if long_term else 'short'}-term with gain {money(new_gain)} instead of {money(old_gain)}. "
               f"The only support named is the client's own record; a person must decide if it is enough.")
    return changes, drafted
