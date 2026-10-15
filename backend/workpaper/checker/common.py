"""Shared pieces for the checker rules.

Ground rule for every rule in this package: no rule names a packet id (no D10,
no ev-1045, no qa-41). Rules know tax forms and document types (W-2 box 16 is
state wages, Sch1.17 is self-employed health insurance, a 1098-C box 4c is the
sale price), and they read the printed pages. That is what makes them checks
that do not trust the engine, instead of a list of answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from ..packet import Packet, page_ref
from ..project import State
from ..taxeffect import Effect

# Machine states (D2). The machine never says "verified".
DISAGREEMENT = "disagreement"   # the value does not match its printed page
CONFLICT = "conflict"           # a source says one thing, the return uses it another way
STALE = "stale"                 # newer evidence or an out-of-date reference
OPEN_ITEM = "open_item"         # something must be dispositioned or obtained before sign-off
VARIANCE = "variance"           # swing from last year over the firm standard; needs an explanation
PROMPT = "prompt"               # treatment needs a person's call (classification, substantiation)


@dataclass
class Change:
    """One correction to one piece of a line.

    `component` names the piece being corrected: a source value (ev-1075), a client answer
    (qa-41), a page (doc:D23#page3), a reference (ref:fx...). Two findings that correct the
    same component of the same line describe the same dollars and are counted once; a second
    component on the same line is a second, real correction.
    `effect` is this piece's estimated tax effect; None for lines that only follow (totals, miles).
    """
    line: str
    original: object
    proposed: object
    component: str
    effect: Effect | None = None
    counted_in: str | None = None        # set when another finding already counts these same dollars
    counted_in_title: str | None = None  # that finding's title, for people to read

    @property
    def delta(self) -> float:
        return (self.proposed or 0) - (self.original or 0)

    def as_dict(self) -> dict:
        return {"line": self.line, "from": self.original, "to": self.proposed, "component": self.component,
                "effect": self.effect.as_dict() if self.effect else None, "counted_in": self.counted_in,
                "counted_in_title": self.counted_in_title}


@dataclass
class Finding:
    code: str                  # stable check code, e.g. ESTIMATES_VS_TRANSCRIPT; never renumbered
    subject: str               # what it is about, e.g. F1040.26
    rule: str                  # R01 .. R13: the display group, may be renumbered
    kind: str                  # one of the machine states above
    title: str
    message: str
    targets: list[str]         # what is wrong: lines (line:KEY), values, documents
    evidence: list[str]        # what proves it: pages, agency records, client answers
    severity: str = "warning"  # error | warning | info
    changes: list[Change] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    quotes: list[dict] = field(default_factory=list)  # page passages it relies on: {"ref": page ref, "text": ...}
    status: str = "open"       # open | accepted (judgment call) | addressed (adjustment or disposition)
    addressed_by: int | None = None
    id: str = field(init=False)

    def __post_init__(self):
        # Stable, so a person's answer keeps pointing at the same check: "<CODE>:<subject>".
        self.id = f"{self.code}:{self.subject}"

    @property
    def effect(self) -> Effect | None:
        """The dollars this finding counts: its own pieces added exactly, rounded once.
        Pieces another finding already counts are left out, so the cards add up to the total."""
        return Effect.combine([c.effect for c in self.changes if c.counted_in is None])

    @property
    def shared(self) -> list[dict]:
        """Pieces whose dollars are already counted in another finding (the same payment, found twice)."""
        return [{"line": c.line, "component": c.component, "counted_in": c.counted_in,
                 "counted_in_title": c.counted_in_title, "effect": c.effect.as_dict() if c.effect else None}
                for c in self.changes if c.counted_in is not None and c.effect is not None]

    def as_dict(self) -> dict:
        effect = self.effect
        return {
            "id": self.id, "code": self.code, "rule": self.rule, "kind": self.kind, "severity": self.severity,
            "title": self.title, "message": self.message,
            "targets": self.targets, "evidence": self.evidence, "quotes": self.quotes,
            "changes": [c.as_dict() for c in self.changes],
            "effect": effect.as_dict() if effect else None, "shared": self.shared,
            "details": self.details, "status": self.status, "addressed_by": self.addressed_by,
        }


class Context:
    """What every rule gets: the packet, the projected state, and convenient lookups."""

    def __init__(self, packet: Packet, state: State):
        self.packet = packet
        self.state = state
        self.tax_year = packet.tax_year
        self.version = state.version
        self.lines = state.lines
        self.rates = state.version["tax_effect_rates"]
        self.params = packet.raw["engine_reference"]["parameters"]
        self.standards = state.standards
        # Figures that should agree and do (machine state "ties"). Rules add to this as they go.
        self.reconciliations: list[dict] = []

    def value(self, key: str):
        return self.state.line_value(key)

    def visible(self, at: str | None) -> bool:
        """Was this item available at the projection's clock?"""
        return self.state.as_of is None or (at is not None and at <= self.state.as_of)

    def documents(self) -> list[dict]:
        return [d for d in self.packet.raw["documents"] if self.visible(d["received_at"])]

    def source_values(self, line: dict) -> list[dict]:
        return [self.packet.values[s] for s in line["sources"] if s in self.packet.values]

    def lines_using(self, ev_ids: set[str]) -> list[str]:
        return [k for k, line in self.lines.items() if ev_ids & set(line["sources"])]

    def ca_residency(self) -> tuple[str, str] | None:
        for r in self.packet.raw["household"]["residency"]:
            if r["state"] == "CA" and r["status"] == "resident":
                return r["from"], r["to"]
        return None

    def ca_effect_category_for_sale(self, sold: str) -> str | None:
        """README: a sale during California residency is fully California-source (ca_source_income).
        A sale after the move is not California income at all for a part-year resident."""
        window = self.ca_residency()
        if window and window[0] <= sold <= window[1]:
            return "ca_source_income"
        return None


# ---- reading printed pages -------------------------------------------------------

_NUMBER = re.compile(r"\(?-?\$?\d[\d,]*(?:\.\d+)?\)?")


def amounts_in(text: str) -> set[float]:
    """Every number printed in a piece of text, as positive floats rounded to cents."""
    out = set()
    for m in _NUMBER.finditer(text):
        token = m.group(0).strip("()$-").replace(",", "").replace("$", "")
        try:
            out.add(round(float(token), 2))
        except ValueError:
            pass
    return out


def prints_amount(text: str, amount: float) -> bool:
    return round(abs(float(amount)), 2) in amounts_in(text)


def date_forms(iso: str) -> list[str]:
    """The ways a date can appear on a page."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return [str(iso)]
    return [
        d.isoformat(), d.strftime("%m/%d/%Y"), f"{d.month}/{d.day}/{d.year}", d.strftime("%m/%d/%y"),
        d.strftime("%B %-d, %Y"), d.strftime("%b %-d, %Y"), d.strftime("%m/%Y"),
    ]


def appears_on_page(ev: dict, page: str) -> bool:
    """Does an extracted value appear on its printed page?"""
    v, kind = ev["value"], ev["value_type"]
    if kind in ("money", "integer", "quantity", "percent"):
        if prints_amount(page, v):
            return True
        return kind == "percent" and prints_amount(page, float(v) * 100)
    if kind == "date":
        return any(form in page for form in date_forms(v))
    if kind == "boolean":
        return True  # check boxes have no printed text to compare
    text = str(v).lower()
    read = (ev.get("text_as_read") or "").lower()
    return text in page.lower() or (bool(read) and read in page.lower())


def money(x: float) -> str:
    return f"{x:,.2f}" if abs(x - round(x)) > 0.004 else f"{x:,.0f}"


def page_of(ev: dict) -> str:
    return page_ref(ev["document_id"], ev["page"])


@lru_cache(maxsize=None)
def issuer_core(issuer: str) -> str:
    """'Northlake Bank, N.A.' -> 'northlake bank'; 'Coinhaven Exchange, Inc.' -> 'coinhaven exchange'."""
    name = issuer.split("(")[0]
    name = re.sub(r",?\s*(inc\.?|llc|llp|lp|n\.a\.|co\.|corp\.?|ab)\s*$", "", name.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9 &]", "", name.lower()).strip()


def issuer_words(issuer: str, n: int = 2) -> str:
    """First n words of an issuer name, used to spot the same company named on another page."""
    return " ".join(issuer_core(issuer).split()[:n])


def mentions(text: str, phrase: str) -> bool:
    return bool(phrase) and phrase.lower() in text.lower()


def sentence_with(text: str, needle: str) -> str | None:
    """The printed sentence (or semicolon clause) that contains `needle`, exactly as printed."""
    for part in re.split(r"(?<=[.;])\s+", text):
        if needle in part:
            return part.strip()
    return None


def quote(doc_id: str, page: int, text: str | None) -> list[dict]:
    """A page passage a finding relies on, for the screen to mark next to the number."""
    return [{"ref": page_ref(doc_id, page), "text": text}] if text else []


def quote_from(ctx: "Context", doc_id: str, needle: str) -> list[dict]:
    """The printed sentence containing `needle`, on whichever page of the document prints it."""
    for page in ctx.packet.documents[doc_id]["pages"]:
        sentence = sentence_with(page["printed_content"], needle)
        if sentence:
            return quote(doc_id, page["page"], sentence)
    return []


def lot_fields(packet: Packet, doc_id: str) -> dict[str, dict]:
    """Group a broker document's lot values: {'N1': {'basis': ev, 'sold': ev, ...}}."""
    lots: dict[str, dict] = {}
    for ev in packet.values_by_doc.get(doc_id, []):
        m = re.match(r"^([A-Z]+\d+)_(\w+)$", ev["field"])
        if m:
            lots.setdefault(m.group(1), {})[m.group(2)] = ev
    return lots


def line_sources_by_field(ctx: Context, line: dict, suffix: str) -> dict | None:
    """The source value of a lot line whose field ends with `suffix` (e.g. '_basis')."""
    for ev in ctx.source_values(line):
        if ev["field"].endswith(suffix):
            return ev
    return None
