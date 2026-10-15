"""Estimated tax effect of a change, using the packet's per-dollar rates.

We cannot rerun the engine. The README says: multiply the change by the matching
rate in return_versions[].tax_effect_rates. This is an estimate and the UI must
say so. Large changes can cross thresholds; the real system would recompute.

Sign convention: a positive effect means more tax due (or a smaller refund).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Payments and credits change tax or balance due one for one. A payment that goes
# down by 1,000 means 1,000 more is due, so the effect is the negative of the change.
ONE_FOR_ONE = {"payment": -1.0, "credit": -1.0}

# 8949 boxes: A-C short-term, D-F long-term, G-I short-term digital assets, J-L long-term digital assets.
SHORT_TERM_BOXES = set("ABCGHI")


def round_half_up(x: float) -> int:
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


@dataclass
class Effect:
    federal: int = 0
    california: int = 0
    workings: list[str] = field(default_factory=list)  # how the estimate was built, for display
    estimate: bool = True

    def as_dict(self) -> dict:
        return {"federal": self.federal, "california": self.california,
                "workings": self.workings, "estimate": self.estimate}


def estimate(rates: dict, federal: list[tuple[str, float]] = (), california: list[tuple[str, float]] = ()) -> Effect:
    """federal / california: lists of (rate category, change in dollars).

    Category is a key of tax_effect_rates (wages, interest, schc_profit, stcg, ltcg,
    ordinary_income, adjustment, salt, itemized, ca_source_income) or 'payment'/'credit'.
    """
    eff = Effect()
    fed_total = 0.0
    for category, delta in federal:
        rate = _rate(rates, category, "federal_per_dollar")
        fed_total += delta * rate
        eff.workings.append(f"federal: {delta:+,.2f} x {category} {rate} = {delta * rate:+,.2f}")
    ca_total = 0.0
    for category, delta in california:
        rate = _rate(rates, category, "california_per_dollar")
        ca_total += delta * rate
        eff.workings.append(f"california: {delta:+,.2f} x {category} {rate} = {delta * rate:+,.2f}")
    eff.federal = round_half_up(fed_total)
    eff.california = round_half_up(ca_total)
    return eff


def _rate(rates: dict, category: str, key: str) -> float:
    if category in ONE_FOR_ONE:
        return ONE_FOR_ONE[category]
    return rates[category][key]


def gain_category(box: str) -> str:
    return "stcg" if box.upper() in SHORT_TERM_BOXES else "ltcg"


def category_for_line(key: str) -> str | None:
    """Default federal rate category for a return line, by form. None if no single rate fits."""
    if key.startswith("SchC.") or key.startswith("SchSE."):
        return "schc_profit"
    if key.startswith("SchB."):
        return "interest"
    if key.startswith("F8949."):
        box = key.split(".")[1]
        return gain_category(box)
    if key.startswith("SchE.") or key.startswith("F4562-E."):
        return "ordinary_income"
    if key.startswith("SchA.5"):
        return "salt"
    if key.startswith("SchA.") or key.startswith("F8283."):
        return "itemized"
    if key in ("Sch1.15", "Sch1.16", "Sch1.17", "Sch1.13"):
        return "adjustment"
    if key in ("F1040.1a", "F1040.1z"):
        return "wages"
    if key in ("F1040.25a", "F1040.25d", "F1040.26", "Sch3.10", "F540NR.71", "F540NR.72", "F540NR.73"):
        return "payment"
    return None
