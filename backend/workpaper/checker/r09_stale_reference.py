"""R09. Stale reference.

A line that cites a reference value for another year (an exchange rate, a rate
table) is computed with the wrong number even though every document value is right.
For exchange rates the checker recomputes with this year's rate from the packet.

Catches: E11 (Swedish interest converted at the 2024 average rate 10.56 instead of 9.86).
"""

from __future__ import annotations

import re

from ..taxeffect import category_for_line, estimate
from .common import STALE, Change, Context, Finding, money

YEAR = re.compile(r"(20\d{2})")


def check(ctx: Context) -> list[Finding]:
    findings = []
    for key, line in ctx.lines.items():
        for ref in line["sources"]:
            if not ref.startswith("ref:"):
                continue
            years = YEAR.findall(ref)
            if not years or all(int(y) == ctx.tax_year for y in years):
                continue
            findings.append(_stale(ctx, key, line, ref, int(years[0])))
    return findings


def _stale(ctx: Context, key: str, line: dict, ref: str, used_year: int) -> Finding:
    current_ref = ref.replace(str(used_year), str(ctx.tax_year))
    used, current = ctx.packet.resolve(ref), ctx.packet.resolve(current_ref)
    changes, extra = [], ""
    foreign = next((ev for ev in ctx.source_values(line) if ev["value_type"] == "money"), None)
    if ref.startswith("ref:fx.") and foreign and isinstance(current, (int, float)):
        recomputed = round(foreign["value"] / current)
        old = ctx.engine(key)
        category = category_for_line(key)
        delta = recomputed - old
        effect = estimate(ctx.rates, federal=[(category, delta)], california=[(category, delta)]) if category else None
        changes.append(Change(key, old, recomputed, ref, effect))
        extra = (f" At the {ctx.tax_year} rate ({current}), {money(foreign['value'])} converts to "
                 f"{money(recomputed)}, not {money(old)}.")
    return Finding(
        code="STALE_REFERENCE", subject=key, rule="R09", kind=STALE,
        title="Reference value from another year",
        message=(f"{key} ({line['label']}) uses {ref} = {used}, a {used_year} value on a {ctx.tax_year} return."
                 + (f" The packet has {current_ref} = {current}." if current is not None else "") + extra),
        targets=[f"line:{key}"], evidence=[ref] + ([current_ref] if current is not None else []),
        severity="warning", changes=changes,
        details={"used": used, "current": current},
    )
