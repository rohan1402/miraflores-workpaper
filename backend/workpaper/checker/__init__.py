"""The checker: rules that re-read the printed pages and the agency records without trusting the engine.

run_checker(packet, state) is a pure function. Its output is derived every time
from the packet plus the projected state, and is never written to the event log.
When a person fixes a number or answers a finding, the next run reflects it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..packet import Packet
from ..project import State
from . import (
    r01_value_vs_page, r02_duplicates, r03_same_money, r04_unmatched_basis, r05_agency_records,
    r06_unread_pages, r07_client_vs_treatment, r08_period_conflicts, r09_stale_reference,
    r10_prior_year_variance, r11_classification, r12_identity, r13_newer_evidence,
)
from ..taxeffect import Effect
from .common import CONFLICT, DISAGREEMENT, Change, Context, Finding

RULES = {
    "R01": ("Value vs page", r01_value_vs_page.check),
    "R02": ("Duplicate and superseded documents", r02_duplicates.check),
    "R03": ("Same money, two sources", r03_same_money.check),
    "R04": ("Unmatched supplemental basis", r04_unmatched_basis.check),
    "R05": ("Agency reconciliation", r05_agency_records.check),
    "R06": ("Unread pages and unextracted documents", r06_unread_pages.check),
    "R07": ("Client answer vs treatment", r07_client_vs_treatment.check),
    "R08": ("Period and year conflicts", r08_period_conflicts.check),
    "R09": ("Stale reference", r09_stale_reference.check),
    "R10": ("Prior-year variance", r10_prior_year_variance.check),
    "R11": ("Classification and substantiation prompts", r11_classification.check),
    "R12": ("Identity", r12_identity.check),
    "R13": ("Evidence newer than the computation", r13_newer_evidence.check),
}

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class CheckResult:
    findings: list[Finding]
    reconciliations: list[dict]          # figures that should agree and do ("ties")
    value_states: dict[str, str]         # ev id -> ties | disagreement | conflict | not_read
    corrected_lines: dict = field(default_factory=dict)  # line -> original, corrected, the pieces
    net_effect: dict = field(default_factory=dict)

    def by_id(self, finding_id: str) -> Finding | None:
        return next((f for f in self.findings if f.id == finding_id), None)

    def proposed_line(self, key: str) -> dict | None:
        """A line the return lacks that an open finding proposes adding (a lot on an unread page):
        the only way a person may add a line."""
        return next((c.adds for f in self.findings if f.status == "open" for c in f.changes
                     if c.line == key and c.adds), None)

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "reconciliations": self.reconciliations,
            "value_states": self.value_states,
            "corrected_lines": self.corrected_lines,
            "net_effect": self.net_effect,
        }


def run_checker(packet: Packet, state: State) -> CheckResult:
    ctx = Context(packet, state)
    findings: list[Finding] = []
    for _, check in RULES.values():
        findings += check(ctx)
    _mark_answered(findings, state)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule, f.id))
    corrected, net = build_corrections([f for f in findings if f.status == "open"])
    return CheckResult(
        findings=findings,
        reconciliations=ctx.reconciliations,
        value_states=_value_states(ctx, findings),
        corrected_lines=corrected,
        net_effect=net,
    )


def _mark_answered(findings: list[Finding], state: State) -> None:
    """A person answers a finding by pointing an event at its id.

    - A judgment call that records the authority relied on (firm rule) marks it 'accepted':
      it stays visible, and its proposed change no longer counts in the tax-effect total.
      A judgment call without an authority does not answer anything.
    - An adjustment made for it, or any other act that targets 'finding:<id>', marks it 'addressed'.
    Rules mark dispositions themselves (a duplicate dispositioned as duplicate is addressed).
    """
    answered: dict[str, tuple[str, int]] = {}
    missing_authority: dict[str, int] = {}
    for e in state.events:
        if e.id in state.undone or e.action in ("undo", "note", "review_note"):
            continue
        refs = [t[len("finding:"):] for t in e.targets if t.startswith("finding:")]
        if e.payload.get("finding"):
            refs.append(e.payload["finding"])
        for ref in refs:
            if e.action == "judgment_call":
                if (e.payload.get("authority") or "").strip():
                    answered[ref] = ("accepted", e.id)
                else:
                    missing_authority[ref] = e.id
            else:
                answered[ref] = ("addressed", e.id)
    for f in findings:
        if f.id in answered and f.status == "open":
            f.status, f.addressed_by = answered[f.id]
        elif f.id in missing_authority:
            f.details["judgment_without_authority"] = missing_authority[f.id]


def _value_states(ctx: Context, findings: list[Finding]) -> dict[str, str]:
    """Machine state for every extracted value. The machine never says 'verified'."""
    states = {}
    for d in ctx.documents():
        for ev in ctx.packet.values_by_doc.get(d["id"], []):
            states[ev["id"]] = "not_read" if ev["value"] is None else "ties"
    for f in findings:
        for t in f.targets:
            if t in states and f.kind in (DISAGREEMENT, CONFLICT):
                states[t] = f.kind if states[t] in ("ties", "not_read", f.kind) else states[t]
    return states


def build_corrections(findings: list[Finding]) -> tuple[dict, dict]:
    """Build each corrected line once from the open findings, and the headline effect from it.

    A line is corrected piece by piece. Two findings that correct the same piece (the FTB
    reconciliation and the tax-year conflict both remove the Sep 15 payment from F540NR.72)
    describe the same dollars, so the piece counts once. A different piece of the same line
    is a real second correction and counts too. Pieces are added exactly and rounded once.
    """
    pieces: dict[tuple[str, str], Change] = {}
    found_by: dict[tuple[str, str], list[str]] = {}
    titles = {f.id: f.title for f in findings}
    disagreements = []
    for f in findings:
        for c in f.changes:
            key = (c.line, c.component)
            if key in pieces:
                found_by[key].append(f.id)
                c.counted_in = found_by[key][0]   # the card shows "same dollars, counted there"
                c.counted_in_title = titles[c.counted_in]
                if abs(pieces[key].delta - c.delta) > 0.005:
                    disagreements.append({"line": c.line, "component": c.component, "findings": list(found_by[key])})
                continue
            pieces[key] = c
            found_by[key] = [f.id]

    corrected: dict[str, dict] = {}
    for (line, component), c in pieces.items():
        entry = corrected.setdefault(line, {"original": c.original, "pieces": []})
        entry["pieces"].append({"component": component, "change": c.delta, "proposed": c.proposed,
                                "found_by": found_by[(line, component)]})
    for line, entry in corrected.items():
        removed = all(p["proposed"] is None for p in entry["pieces"])
        entry["corrected"] = None if removed else round((entry["original"] or 0) + sum(p["change"] for p in entry["pieces"]), 2)

    total = Effect.combine([c.effect for c in pieces.values()])
    net = {
        "federal": total.federal if total else 0,
        "california": total.california if total else 0,
        "estimate": True,
        # The findings whose cards carry these dollars (each piece belongs to the finding that found it first).
        "findings": sorted({ids[0] for key, ids in found_by.items() if pieces[key].effect is not None}),
        "disagreements": disagreements,
    }
    return corrected, net
