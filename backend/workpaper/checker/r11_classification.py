"""R11. Classification and substantiation prompts.

Some numbers are right but treated wrong, or deductible only with paper the
packet does not have. The checker cannot decide these; it puts the question in
front of a person with the evidence attached.

  (a) Repairs that look like improvements: an invoice behind a repairs line that is
      over the de minimis amount, or that replaces or installs a whole system.
      An improvement is capitalized and depreciated instead of expensed.
  (b) Charitable gifts of 250 or more need a written acknowledgment that says whether
      any goods or services were given in return. A receipt without that sentence
      does not substantiate the gift.

Catches: E9 (11,000 heat pump system at the Sacramento rental expensed as a repair),
E20 (the St. Brigid receipt has no goods-or-services statement).
"""

from __future__ import annotations

import re
from datetime import date

from ..taxeffect import estimate
from .common import PROMPT, Change, Context, Finding, money, quote_from

DE_MINIMIS_PER_ITEM = 2500           # IRS de minimis safe harbor without an audited financial statement
IMPROVEMENT_WORDS = re.compile(r"\b(install(ed)?|replace(d|ment)?|new (\S+ ){0,3}(system|roof|unit)|removed)\b", re.I)
RESIDENTIAL_RENTAL_LIFE = 27.5       # MACRS straight line, mid-month convention
GIFT_ACKNOWLEDGMENT_OVER = 250
GOODS_OR_SERVICES = re.compile(r"no goods or services (were )?provided|goods or services provided:\s*no", re.I)


def check(ctx: Context) -> list[Finding]:
    return _repairs(ctx) + _gift_acknowledgments(ctx)


# (a) -------------------------------------------------------------------------

def _repairs(ctx: Context) -> list[Finding]:
    threshold = ctx.standards.get("classification_review", {}).get("repairs_over", DE_MINIMIS_PER_ITEM)
    findings = []
    for key, line in ctx.lines.items():
        if not line["label"].lower().startswith("repairs"):
            continue
        column = key[-1] if key.startswith("SchE.") else None
        address = ctx.engine(f"SchE.1{column}") if column else None
        if not isinstance(address, str):
            continue
        street = address.split(",")[0].strip()  # '1450 Fremont Way, Sacramento CA' -> '1450 Fremont Way'
        for d in ctx.documents():
            if d["document_type"] != "invoice" or street not in d["title"]:
                continue
            text = ctx.packet.document_text(d["id"])
            total = next((ev for ev in ctx.packet.values_by_doc[d["id"]] if ev["value_type"] == "money"), None)
            if total is None:
                continue
            words = sorted({m.group(0).lower() for m in IMPROVEMENT_WORDS.finditer(text)})
            if total["value"] <= threshold and not words:
                continue
            findings.append(_improvement(ctx, key, line, d, total, words, address, text))
    return findings


def _improvement(ctx: Context, key: str, line: dict, invoice: dict, total: dict, words: list, address: str, text: str) -> Finding:
    amount = total["value"]
    placed = _invoice_date(ctx, invoice["id"])
    first_year = _first_year_depreciation(amount, placed) if placed else 0.0
    net_income_change = amount - first_year
    in_california = re.search(r"\bCA\b", address) is not None
    old = ctx.engine(key)
    effect = estimate(ctx.rates, federal=[("ordinary_income", net_income_change)],
                      california=[("ca_source_income" if in_california else "ordinary_income", net_income_change)])
    effect.workings.append("Rental losses are subject to the passive loss limits; the engine would recompute them.")
    return Finding(
        code="REPAIR_LOOKS_LIKE_IMPROVEMENT", subject=f"{key}:{invoice['id']}", rule="R11", kind=PROMPT,
        title="Repair that looks like an improvement",
        message=(f"{key} ({line['label']}) expenses {money(amount)} from {invoice['id']}: \"{text[:200]}\" "
                 f"It is over the {money(DE_MINIMIS_PER_ITEM)} de minimis amount"
                 + (f" and the invoice says {', '.join(words)}" if words else "")
                 + f". If it is an improvement, capitalize it as a {RESIDENTIAL_RENTAL_LIFE}-year asset placed in "
                 f"service {placed}: about {money(first_year)} of depreciation this year instead of a "
                 f"{money(amount)} expense."),
        targets=[f"line:{key}", total["id"]], evidence=[invoice["id"]] + _call_notes_mentioning(ctx, ["hvac", "heat pump", "furnace"]),
        severity="warning",
        changes=[Change(key, old, old - amount, total["id"], effect)],
        quotes=_improvement_passages(ctx, invoice["id"], text),
        details={"amount": amount, "placed_in_service": placed, "first_year_depreciation": first_year},
    )


def _improvement_passages(ctx: Context, doc_id: str, text: str) -> list[dict]:
    """The invoice sentences that say what was removed, replaced or installed (at most two)."""
    out: list[dict] = []
    for m in IMPROVEMENT_WORDS.finditer(text):
        for q in quote_from(ctx, doc_id, m.group(0)):
            if q not in out:
                out.append(q)
    return out[:2]


def _invoice_date(ctx: Context, doc_id: str) -> str | None:
    for ev in ctx.packet.values_by_doc[doc_id]:
        if ev["value_type"] == "date":
            return ev["value"]
    m = re.search(r"dated (\d{2})/(\d{2})/(\d{4})", ctx.packet.document_text(doc_id))
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def _first_year_depreciation(cost: float, placed: str) -> float:
    """Residential rental property, straight line over 27.5 years, mid-month convention."""
    month = date.fromisoformat(placed).month
    months = 12 - month + 0.5
    return round(cost / RESIDENTIAL_RENTAL_LIFE * months / 12, 2)


def _call_notes_mentioning(ctx: Context, words: list[str]) -> list[str]:
    out = []
    for item in ctx.packet.client_items.values():
        text = " ".join(item.get("notes") or [item.get("text") or item.get("answer") or ""]).lower()
        if ctx.visible(item["at"]) and any(w in text for w in words):
            out.append(item["id"])
    return out


# (b) -------------------------------------------------------------------------

def _gift_acknowledgments(ctx: Context) -> list[Finding]:
    findings = []
    for d in ctx.documents():
        if d["document_type"] != "donation_receipt":
            continue
        for page in d["pages"]:
            amounts = [ev for ev in ctx.packet.values_by_doc[d["id"]]
                       if ev["page"] == page["page"] and ev["value_type"] == "money"
                       and isinstance(ev["value"], (int, float)) and ev["value"] >= GIFT_ACKNOWLEDGMENT_OVER]
            if not amounts or GOODS_OR_SERVICES.search(page["printed_content"]):
                continue
            ev = amounts[0]
            lines = ctx.lines_using({ev["id"]})
            findings.append(Finding(
                code="GIFT_WITHOUT_ACKNOWLEDGMENT", subject=ev["id"], rule="R11", kind=PROMPT,
                title="Gift of 250 or more without a proper acknowledgment",
                message=(f"{d['id']} page {page['page']} supports a gift of {money(ev['value'])}, but the receipt has no "
                         f"statement that no goods or services were provided: \"{page['printed_content'][:180]}\" "
                         f"Obtain a written acknowledgment from {d['issuer']} before relying on it."),
                targets=[ev["id"]] + [f"line:{k}" for k in lines], evidence=[f"doc:{d['id']}#page{page['page']}"],
                severity="warning",
                details={"amount": ev["value"], "confidence": ev["confidence"]},
            ))
    return findings
