"""The checker: rules that re-read the printed pages and the agency records without trusting the engine.

run_checker(packet, state) is a pure function. Its output is derived every time
from the packet plus the projected state, and is never written to the event log.
When a person fixes a number or answers a finding, the next run reflects it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from ..packet import Packet
from ..project import State, estimate_adjustment
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
    lines: dict = field(default_factory=dict)            # line -> LineState, for every line a finding corrects

    def by_id(self, finding_id: str) -> Finding | None:
        return next((f for f in self.findings if f.id == finding_id), None)

    def estimate_for(self, line: str, figure, state: State) -> Effect | None:
        """The estimate an adjustment of `line` to `figure` stores (D37). A line's estimate depends only
        on its figure: where the checker can price the figure (the documented figure, the engine's
        figure, or a figure showing some of the pieces, such as the phone share alone), that price;
        anywhere else, the line's own rate from the engine's figure. An adjustment stores the change:
        that estimate less what the line's adjustments already stored. So whatever the path, a line's
        adjustments add up to the estimate for where it stands, and a round trip nets to nothing.
        None for a line no finding corrects, or one not yet adjusted at an unpriced figure: the line's
        own rate from the figure now is then the same thing."""
        st = self.lines.get(line)
        if st is None or not isinstance(figure, (int, float)) or isinstance(figure, bool):
            return None
        estimate = st.price(figure)
        if estimate is None and st.stored:   # the line's own rate, measured from the engine's figure
            estimate = estimate_adjustment(state, line, st.pieces[0].original, figure)
        return Effect.less(estimate, st.stored) if estimate is not None else None

    def acceptance_effect(self, ids: list[str]) -> Effect | None:
        """What accepting these findings as they are would leave out of the total (D20, D37): their
        pieces not yet on the return, each counted once, less any already left out by another acceptance.
        A piece counted on another open card is included, since the acceptance answers that card too."""
        pieces: dict[tuple[str, str], Change] = {}
        for f in self.findings:
            if f.id in ids:
                for c in f.changes:
                    if c.applied_by is None and not c.counted_in_accepted:
                        pieces.setdefault((c.line, c.component), c)
        return Effect.combine([c.open_effect for c in pieces.values()])

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
    lines = _settle_lines(findings, state)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule, f.id))
    corrected, net = build_corrections([f for f in findings if f.status in ("open", "accepted")], lines)
    return CheckResult(
        findings=findings,
        reconciliations=ctx.reconciliations,
        value_states=_value_states(ctx, findings),
        corrected_lines=corrected,
        lines=lines,
        net_effect=net,
    )


def _mark_answered(findings: list[Finding], state: State) -> None:
    """Only two acts answer a finding by naming it (D37).

    - A judgment call that records the authority relied on (firm rule) marks it 'accepted':
      it stays visible, and its proposed change no longer counts in the tax-effect total.
      A judgment call without an authority does not answer anything.
    - An adjustment made for a finding with no pieces to apply marks it 'addressed', while it is the
      latest adjustment on the return for its line: an undo, or a later move, reopens it. For a
      finding with pieces, _settle_lines decides, line by line, from what the return now shows.
    A question, an answer, an attached file or a note about a finding answers nothing: asking the
    client is not fixing the return. Rules mark dispositions and SSN corrections themselves.
    """
    answered: dict[str, tuple[str, int]] = {}
    missing_authority: dict[str, int] = {}
    with_pieces = {f.id for f in findings if f.changes}
    targets = {f.id: set(f.targets) for f in findings}
    latest: dict[str, int] = {}          # line -> the adjustment on the return for it now
    for a in state.applied_adjustments():
        latest[a.line] = a.event_id
    for e in state.events:
        if e.id in state.undone or e.action not in ANSWERING:
            continue
        refs = [t[len("finding:"):] for t in e.targets if t.startswith("finding:")]
        if isinstance(e.payload.get("finding"), str):   # only a finding id answers a finding
            refs.append(e.payload["finding"])
        for ref in refs:
            if e.action == "judgment_call":
                authority = e.payload.get("authority")
                if isinstance(authority, str) and authority.strip():
                    answered[ref] = ("accepted", e.id)
                else:
                    missing_authority[ref] = e.id
            elif ref not in with_pieces and set(e.targets) & targets.get(ref, set()) \
                    and e.id in latest.values():   # an adjustment of its line, still the one on the return
                answered[ref] = ("addressed", e.id)
    for f in findings:
        if f.id in answered and f.status == "open":
            f.status, f.addressed_by = answered[f.id]
        elif f.id in missing_authority:
            f.details["judgment_without_authority"] = missing_authority[f.id]


# The acts that can answer a finding by naming it.
ANSWERING = {"judgment_call", "adjust"}


@dataclass
class LineState:
    """One return line the findings say is wrong, and how far people have corrected it (D37)."""
    line: str
    pieces: list[Change]          # the distinct pieces on this line (by component), across the findings
    target: float | None          # the documented figure: the engine's plus every piece; None if one removes the line
    effect: Effect | None         # the pieces' estimate, from the engine's figure to the documented one
    now: object                   # the figure on the return
    adjusted: bool                # a person has adjusted this line
    stored: list[dict]            # the effects stored by the adjustments on this line
    follows_only: bool            # every piece is a computed line with no effect of its own
    corrected_by: int | None = None   # the adjustment after which the line is corrected
    left: Effect | None = None        # moved but not corrected: the estimate less what is stored

    def price(self, figure: float) -> Effect | None:
        """The checker's estimate for this line at `figure`, from the engine's figure, when it has one:
        nothing at the engine's figure, the pieces' estimate at a figure that shows them. A line whose
        pieces only follow (SchA.5d after SchA.5b) is priced at nothing: its effect is on the line it
        follows. None for any other figure, and for pieces that carry no dollars (miles)."""
        base = self.pieces[0].original or 0
        shown = [] if abs(figure - base) < 0.01 else shows(self.pieces, figure)
        if abs(figure - base) >= 0.01 and not shown:
            return None
        if self.follows_only:
            return Effect(workings=[f"{self.line} follows another line; its effect is stored there"])
        if all(c.effect is None for c in self.pieces):
            return None
        return Effect.combine([c.effect for c in shown]) or Effect(workings=[f"{self.line} at the engine's figure"])


def _settle_lines(findings: list[Finding], state: State) -> dict[str, LineState]:
    """Decide, line by line, what people's adjustments have already put on the return (D37).

    Each line a finding corrects has one documented figure: the engine's figure plus every piece on it
    (a line can carry several, like the phone and internet shares on SchC.25, and two findings can
    carry the same piece, like the FTB record and the tax-year conflict on F540NR.72). The line is
    corrected when its latest adjustment lands on that figure, or was made for a finding on the line
    (the person decided the figure). A line moved but not corrected still counts what is left: the
    pieces' estimate less what its adjustments stored. So nothing is counted twice or lost, whatever
    order fixes come in, and a fix that is undone or moved away reopens.

    A finding is addressed when every line it decides is corrected. Pieces that only follow (SchA.5d
    after SchA.5b) and pieces the app cannot apply (a line it cannot add) decide nothing. An
    acceptance covers the finding's lines as they were when it was made (their figures, and the
    adjustments behind them), like a sign-off: once one of them changes (a fix undone, a line moved
    or corrected, even back to the same figure), the acceptance no longer holds, and the finding is judged again: addressed if every line it decides is now
    corrected, otherwise open until someone answers it again.
    """
    chain: dict[str, list] = {}
    for adj in state.applied_adjustments():
        chain.setdefault(adj.line, []).append(adj)
    live = [f for f in findings if f.status in ("open", "accepted") and f.changes]
    entries: dict[str, list[tuple[Finding, Change]]] = {}
    for f in live:
        for c in f.changes:
            entries.setdefault(c.line, []).append((f, c))

    lines: dict[str, LineState] = {}
    shown: dict[tuple[str, str], int] = {}
    for line, found in entries.items():
        pieces: dict[str, Change] = {}
        for _, c in found:
            pieces.setdefault(c.component, c)
        distinct = list(pieces.values())
        removes = any(c.proposed is None for c in distinct)
        target = None if removes else round((distinct[0].original or 0) + sum(c.delta for c in distinct), 2)
        adjs = chain.get(line, [])
        st = LineState(line=line, pieces=distinct, target=target, effect=Effect.combine([c.effect for c in distinct]),
                       now=state.line_value(line), adjusted=bool(adjs), stored=[a.effect for a in adjs if a.effect],
                       follows_only=all(follows(state, c) for c in distinct))
        if adjs:
            last = adjs[-1]
            named = isinstance(last.finding, str) and last.finding in {f.id for f, _ in found}
            lands = target is not None and isinstance(st.now, (int, float)) and abs(st.now - target) < 0.01
            if named or lands:
                st.corrected_by = last.event_id
            else:
                for c in shows(distinct, st.now):   # the figure may show some pieces (the phone share)
                    shown[(line, c.component)] = last.event_id
                st.left = Effect.less(st.effect, st.stored)
        lines[line] = st

    for f in live:
        for c in f.changes:
            st = lines[c.line]
            c.applied_by = st.corrected_by or shown.get((c.line, c.component))
    # On a moved line, what is left counts once: on the first piece still open, nothing on the others.
    for st in lines.values():
        if st.left is None:
            continue
        still_open = [c.component for c in st.pieces if (st.line, c.component) not in shown]
        for f, c in entries[st.line]:
            if c.applied_by is None:
                c.left = st.left if still_open and c.component == still_open[0] else Effect()

    judgments = {r.event_id: r for r in state.records if r.action == "judgment_call"}
    for f in live:
        if f.status == "accepted":
            changed = changed_since(f, judgments.get(f.addressed_by), state)
            if changed:
                f.details["acceptance_changed"] = {"event": f.addressed_by, "lines": changed}
                f.status, f.addressed_by = "open", None
        deciding = [c for c in f.changes if decides(state, c)]
        if f.status == "open" and deciding and all(c.applied_by is not None for c in deciding):
            f.status, f.addressed_by = "addressed", max(c.applied_by for c in deciding)
    # An acceptance answers the findings on the same dollars, as a fix does (the FTB record and the
    # tax-year conflict both correct the Sep 15 payment).
    for f in live:
        left = {(c.line, c.component) for c in f.changes if c.applied_by is None}
        if f.status == "open" and left:
            by = next((g for g in live if g.status == "accepted"
                       and left <= {(c.line, c.component) for c in g.changes}), None)
            if by:
                f.status, f.addressed_by = "accepted", by.addressed_by
                f.details["accepted_with"] = by.id
    return lines


def changed_since(f: Finding, judgment, state: State) -> list[str]:
    """The finding's lines that are no longer as its acceptance saw them (D37): another figure, or the
    same figure reached by other adjustments (a fix made for the finding corrects its line; a move to
    the same figure does not)."""
    figures, made = (_seen(judgment, key, f.id) for key in ("figures", "adjustments"))
    if figures is None:
        return []
    applied: dict[str, list[int]] = {}
    for a in state.applied_adjustments():
        applied.setdefault(a.line, []).append(a.event_id)
    return sorted(line for line in dict.fromkeys(c.line for c in f.changes)
                  if figures.get(line) != state.line_value(line)
                  or (made is not None and made.get(line) != applied.get(line, [])))


def _seen(judgment, key: str, finding_id: str) -> dict | None:
    """What a judgment recorded about one finding's lines: `figures` or `adjustments`."""
    seen = judgment.payload.get(key) if judgment else None
    seen = seen.get(finding_id) if isinstance(seen, dict) else None
    return seen if isinstance(seen, dict) else None


def decides(state: State, c: Change) -> bool:
    """A piece decides whether its finding is addressed unless it only follows, or the app cannot
    apply it (a line the return lacks and no way to add it)."""
    return not follows(state, c) and (c.line in state.lines or bool(c.adds))


def shows(pieces: list[Change], figure, already: float = 0.0) -> list[Change]:
    """The largest set of pieces that a line's figure shows, measured from the engine's figure (the
    pieces' common `original`, nothing for a line a person added) plus `already`, the pieces applied
    before. Empty when it shows none of them."""
    if not isinstance(figure, (int, float)) or isinstance(figure, bool):
        return []
    usable = [c for c in pieces if c.proposed is not None]
    if not usable:
        return []
    base = (usable[0].original or 0) + already
    for size in range(len(usable), 0, -1):
        if size not in (1, len(usable)) and len(usable) > 8:
            continue   # a guard; no line here carries more than three pieces
        for subset in combinations(usable, size):
            if abs(base + sum(c.delta for c in subset) - figure) < 0.01:
                return list(subset)
    return []


def follows(state: State, c: Change) -> bool:
    """A piece on a computed line that carries no tax effect only follows another piece."""
    line = state.lines.get(c.line)
    return c.effect is None and bool(line and line["inputs"])


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


def build_corrections(findings: list[Finding], lines: dict | None = None) -> tuple[dict, dict]:
    """Build each corrected line once from the open findings, and the headline effect from it.

    A line is corrected piece by piece. Two findings that correct the same piece (the FTB
    reconciliation and the tax-year conflict both remove the Sep 15 payment from F540NR.72)
    describe the same dollars, so the piece counts once. A different piece of the same line
    is a real second correction and counts too. Pieces are added exactly and rounded once.
    Pieces already applied to the return are left out (D37): their dollars are in the adjustment.
    So are pieces an accepted finding already left out: their dollars are in the acceptance.
    With the line states (`lines`), each line shows the figure on the return now and its documented
    figure, the one its card fix offers.
    """
    accepted: dict[tuple[str, str], Finding] = {}
    # The finding a judgment named shows the dollars; one accepted with it points there.
    for f in sorted(findings, key=lambda f: "accepted_with" in f.details):
        if f.status == "accepted":
            for c in f.changes:
                if c.applied_by is None:
                    accepted.setdefault((c.line, c.component), f)
    pieces: dict[tuple[str, str], Change] = {}
    found_by: dict[tuple[str, str], list[str]] = {}
    titles = {f.id: f.title for f in findings}
    disagreements = []
    for f in findings:
        for c in f.changes:
            if c.applied_by is not None:
                continue
            key = (c.line, c.component)
            if key in accepted and accepted[key] is not f:
                c.counted_in, c.counted_in_title = accepted[key].id, accepted[key].title
                c.counted_in_accepted = True    # the card shows "same dollars, accepted there"
                continue
            if f.status != "open":
                continue
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
        st = (lines or {}).get(line)
        now = st.now if st else c.original   # the figure on the return now
        entry = corrected.setdefault(line, {"original": now, "pieces": []})
        entry["pieces"].append({"component": component, "change": c.delta, "proposed": c.proposed,
                                "found_by": found_by[(line, component)]})
    for line, entry in corrected.items():
        st = (lines or {}).get(line)
        removed = any(p["proposed"] is None for p in entry["pieces"])
        entry["corrected"] = st.target if st else (
            None if removed else round((entry["original"] or 0) + sum(p["change"] for p in entry["pieces"]), 2))

    total = Effect.combine([c.open_effect for c in pieces.values()])
    net = {
        "federal": total.federal if total else 0,
        "california": total.california if total else 0,
        "estimate": True,
        # The findings whose cards carry these dollars (each piece belongs to the finding that found it first).
        "findings": sorted({ids[0] for key, ids in found_by.items() if pieces[key].open_effect is not None}),
        "disagreements": disagreements,
    }
    return corrected, net
