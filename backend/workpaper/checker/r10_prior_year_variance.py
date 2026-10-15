"""R10. Prior-year variance.

Any line that moved more than the firm standard from last year needs an
explanation (firm standard: over 10% AND over 1,000). The threshold is read from
the firm standards in the projected state, so when the administrator changes it,
the flags change with it. A prior-year note on the same line is shown, because
the prior preparer's reason is often the explanation, or the warning.

Numbered sub-lines (SchB.1.1, SchB.1.2 ...) are positional: line 1.2 was Meridian
in 2024 and Northlake Bank in 2025. They are matched to last year by payer name,
and a payer with no line last year is reported as new.

This rule does not decide anything is wrong. It makes sure a person looked.

Surfaces: E6 (business miles 7,400 to 11,800), E4 (SE health insurance 0 to 14,400),
E3 (gross receipts 128,400 to 163,700), E10 (a second Northlake interest line that
2024 did not have), and every other swing over the standard.
"""

from __future__ import annotations

import re

from .common import VARIANCE, Context, Finding, money

DETAIL_FORMS = ("F8949.",)  # lot-level detail is reviewed by account, not against last year


def check(ctx: Context) -> list[Finding]:
    standard = ctx.standards["variance_review"]
    pct_limit = standard["flag_if_change_over_percent"]
    amount_limit = standard["and_over_amount"]
    prior = ctx.packet.raw["prior_years"]["return_2024"]
    findings = []
    for key, line in ctx.lines.items():
        now = ctx.value(key)
        if not _number(now) or key.startswith(DETAIL_FORMS):
            continue
        prior_key = _prior_match(key, line["label"], prior)
        if prior_key is None:
            continue
        before = prior["lines"].get(prior_key, 0) if prior_key != _NEW else 0
        if not _number(before):
            continue
        change = now - before
        pct = abs(change) / abs(before) * 100 if before else float("inf")
        if abs(change) <= amount_limit or pct <= pct_limit:
            continue
        note = prior["notes"].get(prior_key) if prior_key != _NEW else None
        if prior_key == _NEW:
            what = f"has no matching line in {ctx.tax_year - 1} (new payer or item, {money(now)})."
        else:
            pct_text = "new this year" if before == 0 else f"{change / abs(before):+.0%}"
            what = (f"went from {money(before)} in {ctx.tax_year - 1}"
                    + (f" (as {prior_key})" if prior_key != key else "")
                    + f" to {money(now)} ({pct_text}, {money(change)}).")
        findings.append(Finding(
            code="PRIOR_YEAR_VARIANCE", subject=key, rule="R10", kind=VARIANCE,
            title="Swing from last year over the firm standard",
            message=f"{key} ({line['label']}) {what}" + (f" Prior-year note: \"{note}\"" if note else ""),
            targets=[f"line:{key}"],
            evidence=([f"py:/return_2024/lines/{prior_key}"] if prior_key != _NEW else [])
                     + ([f"py:/return_2024/notes/{prior_key}"] if note else []),
            severity="info",
            details={"prior_line": None if prior_key == _NEW else prior_key, "prior": before, "current": now,
                     "change": change, "percent": None if before == 0 else round(pct, 1), "prior_note": note},
        ))
    return findings


_NEW = "<new>"


def prior_line_key(key: str, label: str, prior: dict) -> str | None:
    """The 2024 line to compare a 2025 line with (matched by payer for numbered sub-lines), or None."""
    match = _prior_match(key, label, prior)
    return None if match in (None, _NEW) else match


def _prior_match(key: str, label: str, prior: dict) -> str | None:
    """The prior-year line to compare with, _NEW for a new payer, or None if there is nothing to compare."""
    if key.count(".") < 2:
        return key if key in prior["lines"] else None
    parent = key.rsplit(".", 1)[0] + "."
    siblings = [k for k in prior["lines"] if k.startswith(parent)]
    if not siblings:
        return None  # the whole schedule is new this year (e.g. California nonresident forms)
    name = _payer(label)
    for k in siblings:
        if name and _payer(prior["line_labels"].get(k, "")) == name:
            return k
    return _NEW


def _payer(label: str) -> str:
    """'Interest - Northlake Securities - bank sweep' -> 'northlake securities'."""
    parts = label.split(" - ")
    name = parts[1] if len(parts) > 1 else parts[0]
    return " ".join(re.findall(r"[a-z]+", name.lower())[:2])


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)
