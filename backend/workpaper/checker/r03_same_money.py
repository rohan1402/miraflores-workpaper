"""R03. Same money, two sources.

A total that adds amounts from two documents is wrong if one document already
contains the other's money. The checker looks for that in the printed pages:

  (a) one document (or another from the same issuer) prints the other's amount
      next to the other issuer's name ("12,400.00 arrived through Paywell Payments"), or
  (b) a statement says its amount is reported on a form from the same issuer
      ("Interest is reported on the 2025 Form 1098").

Only amounts that actually make up the total are compared: the checker first finds
which of the line's sources add up to its value.

Catches: E3 (1099-K already inside books sales), E8 (payoff interest already in the
Form 1098), E10 (sweep interest on the composite 1099 and on the bank's 1099-INT).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from ..taxeffect import category_for_line, estimate
from .common import CONFLICT, Change, Context, Finding, issuer_core, issuer_words, mentions, money, prints_amount

MAX_SOURCES_FOR_SUBSET_SEARCH = 16


@dataclass
class Contribution:
    amount: float
    doc: str
    via: str          # the line the amount sits on
    ev: str | None    # the extracted value, when the amount comes straight from a document


def check(ctx: Context) -> list[Finding]:
    findings = []
    seen_pairs = set()
    for key in ctx.lines:
        parts = contributions(ctx, key)
        for a, b in combinations(parts, 2):
            if a.doc == b.doc:
                continue
            for inner, outer in ((a, b), (b, a)):
                why = contains(ctx, outer.doc, inner)
                if why is None:
                    continue
                pair = (inner.via, inner.doc, outer.doc)
                if pair in seen_pairs:
                    break
                seen_pairs.add(pair)
                findings.append(_finding(ctx, key, inner, outer, why))
                break
    return findings


def contributions(ctx: Context, key: str) -> list[Contribution]:
    """The amounts that add up to a line, each tied to the document it came from."""
    line = ctx.lines[key]
    total = ctx.value(key)
    if not isinstance(total, (int, float)):
        return []
    money_sources = [ev for ev in ctx.source_values(line)
                     if ev["value_type"] == "money" and isinstance(ev["value"], (int, float)) and ev["value"]]
    if money_sources:
        if len({ev["document_id"] for ev in money_sources}) < 2:
            return []  # one document cannot count its own money twice; that is R02's job
        subset = _subset_summing_to(money_sources, total)
        return [Contribution(ev["value"], ev["document_id"], key, ev["id"]) for ev in subset or []]
    if line["rule"] == "R-SUM":
        parts = []
        for inp in line["inputs"]:
            inner = ctx.lines.get(inp)
            docs = {ev["document_id"] for ev in ctx.source_values(inner)} if inner else set()
            value = ctx.value(inp)
            if len(docs) == 1 and isinstance(value, (int, float)) and value:
                parts.append(Contribution(value, docs.pop(), inp, None))
        return parts
    return []


def _subset_summing_to(evs: list[dict], total: float) -> list[dict] | None:
    if abs(sum(ev["value"] for ev in evs) - total) <= 1:
        return evs  # the usual case: every source adds up
    if len(evs) > MAX_SOURCES_FOR_SUBSET_SEARCH:
        return None
    for size in range(len(evs) - 1, 0, -1):
        for combo in combinations(evs, size):
            if abs(sum(ev["value"] for ev in combo) - total) <= 1:
                return list(combo)
    return None


def contains(ctx: Context, outer_doc: str, inner: Contribution) -> str | None:
    """Does `outer_doc` (or its issuer's other documents) already contain `inner`'s money? Say why."""
    docs = ctx.packet.documents
    inner_issuer, outer_issuer = docs[inner.doc]["issuer"], docs[outer_doc]["issuer"]
    family = [d["id"] for d in ctx.documents() if issuer_core(d["issuer"]) == issuer_core(outer_issuer)]
    inner_name = issuer_words(inner_issuer, 2)

    if issuer_core(inner_issuer) != issuer_core(outer_issuer):
        for doc_id in family:
            for page in docs[doc_id]["pages"]:
                text = page["printed_content"]
                if mentions(text, inner_name) and prints_amount(text, inner.amount):
                    return (f"{doc_id} page {page['page']} names {docs[inner.doc]['issuer']} and prints "
                            f"{money(inner.amount)}: the money is already in {outer_doc}.")

    if issuer_words(inner_issuer, 1) == issuer_words(outer_issuer, 1):
        form = f"form {docs[outer_doc]['document_type']}".lower()
        text = ctx.packet.document_text(inner.doc).lower()
        if form in text and ("reported on" in text or "included in" in text):
            return (f"{inner.doc} says its amount is reported on the {docs[outer_doc]['document_type']} "
                    f"from the same lender ({outer_doc}).")
    return None


def _finding(ctx: Context, key: str, inner: Contribution, outer: Contribution, why: str) -> Finding:
    docs = ctx.packet.documents
    category = category_for_line(inner.via) or category_for_line(key)
    effect = estimate(ctx.rates, federal=[(category, -inner.amount)], california=[(category, -inner.amount)]) \
        if category else None
    if inner.ev:  # the amount is one of the line's own sources: take it out of that line
        old = ctx.value(key)
        change = Change(key, old, old - inner.amount, inner.ev, effect)
    else:         # the amount is a whole input line: that line goes to zero
        change = Change(inner.via, ctx.value(inner.via), 0, f"line:{inner.via}", effect)
    return Finding(
        code="SAME_MONEY_TWO_SOURCES", subject=f"{inner.via}:{inner.doc}", rule="R03", kind=CONFLICT,
        title="Same money from two documents",
        message=(f"{key} adds {money(inner.amount)} from {inner.doc} ({docs[inner.doc]['title']}) and "
                 f"{money(outer.amount)} from {outer.doc} ({docs[outer.doc]['title']}). {why}"),
        targets=[f"line:{key}"] + ([f"line:{inner.via}"] if inner.via != key else []) + ([inner.ev] if inner.ev else []),
        evidence=[inner.doc, outer.doc],
        severity="error",
        changes=[change],
        details={"counted_twice": inner.amount, "from": inner.doc, "already_in": outer.doc},
    )
