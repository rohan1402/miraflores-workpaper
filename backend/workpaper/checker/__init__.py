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
from .common import CONFLICT, DISAGREEMENT, Context, Finding

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
    net_effect: dict = field(default_factory=dict)

    def by_id(self, finding_id: str) -> Finding | None:
        return next((f for f in self.findings if f.id == finding_id), None)

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "reconciliations": self.reconciliations,
            "value_states": self.value_states,
            "net_effect": self.net_effect,
        }


def run_checker(packet: Packet, state: State) -> CheckResult:
    ctx = Context(packet, state)
    findings: list[Finding] = []
    for _, check in RULES.values():
        findings += check(ctx)
    _mark_answered(findings, state)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule, f.id))
    return CheckResult(
        findings=findings,
        reconciliations=ctx.reconciliations,
        value_states=_value_states(ctx, findings),
        net_effect=net_effect([f for f in findings if f.status == "open"]),
    )


def _mark_answered(findings: list[Finding], state: State) -> None:
    """A finding is addressed when a person's event points at it: an adjustment made for it,
    a judgment call, a waiver or a note that targets 'finding:<id>'."""
    answered: dict[str, int] = {}
    for e in state.events:
        if e.id in state.undone or e.action in ("undo", "note", "review_note"):
            continue
        for t in e.targets:
            if t.startswith("finding:"):
                answered[t[len("finding:"):]] = e.id
        if e.payload.get("finding"):
            answered[e.payload["finding"]] = e.id
    for f in findings:
        if f.id in answered and f.status == "open":
            f.status, f.addressed_by = "addressed", answered[f.id]


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


def net_effect(findings: list[Finding]) -> dict:
    """Total estimated effect of the proposed changes. Two findings that change the same
    line (the payments reconciliation and the tax-year conflict) are counted once."""
    seen: set[str] = set()
    federal = california = 0
    counted = []
    for f in findings:
        if f.effect is None:
            continue
        lines = {c.line for c in f.changes}
        if lines & seen:
            continue
        seen |= lines
        federal += f.effect.federal
        california += f.effect.california
        counted.append(f.id)
    return {"federal": federal, "california": california, "findings": counted, "estimate": True}
