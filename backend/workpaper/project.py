"""Current state = project(packet, events).

A pure function: same packet and same events always give the same state. It never
writes anything and never changes the packet. Everything the screen shows about
human work comes from here; the checker reads the result.

Replaying the log is what buys undo, "since I last looked", season replay
(pass `as_of`), freeze at filing, and amend on top.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field

from .areas import RETURN, SIGNED_AREAS, lines_in_area
from .events import Event
from .packet import Packet
from .taxeffect import Effect, category_for_line, estimate

DISPOSITIONS = {"used", "duplicate", "superseded", "not_extracted", "partial"}


# ---- what people did, as it appears in state --------------------------------

@dataclass
class Act:
    event_id: int
    actor: str
    role: str
    at: str


@dataclass
class Disposition(Act):
    document: str
    disposition: str
    detail: dict
    reason: str | None


@dataclass
class Verification(Act):
    ref: str                 # ev id or line:KEY
    verification_type: str   # one of the firm's verification types
    value: object            # the value the person looked at
    via: str                 # 'verify' or 'accept_document'


@dataclass
class Adjustment(Act):
    line: str
    original: object         # engine value the person adjusted from
    value: object            # value they set
    version: str             # return version they adjusted against
    reason: str | None
    finding: str | None      # checker finding it answers, if any


@dataclass
class ReviewNote(Act):
    targets: tuple[str, ...]
    text: str
    resolved: Act | None = None
    resolution: str | None = None

    @property
    def is_open(self) -> bool:
        return self.resolved is None


@dataclass
class SignOff(Act):
    area: str                # a signed area, or 'return' for the partner release
    level: str               # preparer | reviewer | partner
    version: str
    covered: dict            # the values signed: {line key: value}
    fingerprint: str
    waiver: str | None = None


@dataclass
class Record(Act):
    """Notes, questions, answers, evidence, judgment calls, sensitive views: kept as history."""
    action: str
    targets: tuple[str, ...]
    payload: dict
    reason: str | None


@dataclass
class State:
    packet: Packet
    as_of: str | None
    tip: int
    version_id: str
    events: list[Event] = field(default_factory=list)
    undone: set[int] = field(default_factory=set)
    dispositions: dict[str, Disposition] = field(default_factory=dict)
    verifications: dict[str, list[Verification]] = field(default_factory=dict)
    adjustments: dict[str, Adjustment] = field(default_factory=dict)   # latest per line
    review_notes: dict[int, ReviewNote] = field(default_factory=dict)
    signoffs: dict[str, dict[str, SignOff]] = field(default_factory=dict)  # area -> level -> sign-off
    partner_release: SignOff | None = None
    partner_approvals: dict[int, Act] = field(default_factory=dict)     # adjustment event id -> approval
    records: list[Record] = field(default_factory=list)
    standards: dict = field(default_factory=dict)

    # ---- lines ---------------------------------------------------------------

    @property
    def version(self) -> dict:
        return self.packet.version_by_id[self.version_id]

    @property
    def lines(self) -> dict[str, dict]:
        return self.packet.lines[self.version_id]

    def original_value(self, key: str):
        line = self.lines.get(key)
        return line["value"] if line else None

    def active_adjustment(self, key: str) -> Adjustment | None:
        """An adjustment applies only while the engine value is still the one it was made against.

        If a newer version changed the line, the adjustment is stale: the engine value
        shows and the adjustment waits for a person to confirm or redo it.
        """
        adj = self.adjustments.get(key)
        if adj is None or adj.original != self.original_value(key):
            return None
        return adj

    def line_value(self, key: str):
        """The value as the workpaper currently stands: adjusted if adjusted, else the engine's."""
        adj = self.active_adjustment(key)
        return adj.value if adj else self.original_value(key)

    def stale_adjustments(self) -> list[Adjustment]:
        return [a for k, a in self.adjustments.items() if self.active_adjustment(k) is None]

    # ---- review notes --------------------------------------------------------

    def open_review_notes(self) -> list[ReviewNote]:
        return [n for n in self.review_notes.values() if n.is_open]


# ---- the replay ----------------------------------------------------------------

def project(packet: Packet, events: list[Event], as_of: str | None = None) -> State:
    """Replay `events` (in log order) on top of the packet, up to `as_of` if given."""
    applied = [e for e in events if as_of is None or e.at <= as_of]
    version = packet.version_at(as_of)
    state = State(
        packet=packet,
        as_of=as_of,
        tip=applied[-1].id if applied else 0,
        version_id=version["version"],
        events=applied,
        standards=copy.deepcopy(packet.raw["firm"]["starter_standards"]),
    )
    # An undo reverses its target. Collect them first so the target is skipped on replay.
    state.undone = {
        _event_id(t) for e in applied if e.action == "undo" for t in e.targets if t.startswith("event:")
    }
    for e in applied:
        if e.id in state.undone or e.action == "undo":
            continue
        APPLY.get(e.action, _apply_record)(state, e)
    return state


def _event_id(ref: str) -> int:
    return int(ref[len("event:"):])


def _act(e: Event) -> dict:
    return {"event_id": e.id, "actor": e.actor, "role": e.role, "at": e.at}


def _apply_disposition(state: State, e: Event) -> None:
    for doc in e.targets:
        state.dispositions[doc] = Disposition(
            **_act(e), document=doc, disposition=e.payload["disposition"],
            detail={k: v for k, v in e.payload.items() if k != "disposition"}, reason=e.reason,
        )


def _apply_verify(state: State, e: Event) -> None:
    values = e.payload.get("values", {})
    for ref in e.targets:
        state.verifications.setdefault(ref, []).append(Verification(
            **_act(e), ref=ref, verification_type=e.payload["verification_type"],
            value=values.get(ref), via="verify",
        ))


def _apply_accept_document(state: State, e: Event) -> None:
    # The payload lists exactly which values the person accepted, with the values they saw.
    for ref, value in e.payload.get("values", {}).items():
        state.verifications.setdefault(ref, []).append(Verification(
            **_act(e), ref=ref, verification_type=e.payload["verification_type"],
            value=value, via="accept_document",
        ))
    _apply_record(state, e)


def _apply_adjust(state: State, e: Event) -> None:
    for target in e.targets:
        key = target[len("line:"):]
        state.adjustments[key] = Adjustment(
            **_act(e), line=key, original=e.payload["from"], value=e.payload["to"],
            version=e.payload.get("version", state.version_id), reason=e.reason,
            finding=e.payload.get("finding"),
        )


def _apply_review_note(state: State, e: Event) -> None:
    state.review_notes[e.id] = ReviewNote(**_act(e), targets=e.targets, text=e.payload.get("text", ""))


def _apply_resolve_review_note(state: State, e: Event) -> None:
    for t in e.targets:
        note = state.review_notes.get(_event_id(t))
        if note is not None:
            note.resolved = Act(**_act(e))
            note.resolution = e.payload.get("text") or e.reason


def _apply_sign_off(state: State, e: Event) -> None:
    for t in e.targets:
        area = t[len("area:"):]
        state.signoffs.setdefault(area, {})[e.payload["level"]] = SignOff(
            **_act(e), area=area, level=e.payload["level"], version=e.payload["version"],
            covered=e.payload["covered"], fingerprint=e.payload["fingerprint"],
            waiver=e.payload.get("waiver"),
        )


def _apply_partner_release(state: State, e: Event) -> None:
    state.partner_release = SignOff(
        **_act(e), area=RETURN, level="partner", version=e.payload["version"],
        covered=e.payload["covered"], fingerprint=e.payload["fingerprint"], waiver=e.payload.get("waiver"),
    )


def _apply_approve_adjustment(state: State, e: Event) -> None:
    for t in e.targets:
        state.partner_approvals[_event_id(t)] = Act(**_act(e))


def _apply_set_standard(state: State, e: Event) -> None:
    # payload: {"path": "variance_review.flag_if_change_over_percent", "value": 15}
    node = state.standards
    *parents, leaf = e.payload["path"].split(".")
    for p in parents:
        node = node.setdefault(p, {})
    node[leaf] = e.payload["value"]
    _apply_record(state, e)


def _apply_record(state: State, e: Event) -> None:
    state.records.append(Record(**_act(e), action=e.action, targets=e.targets, payload=e.payload, reason=e.reason))


APPLY = {
    "disposition": _apply_disposition,
    "verify": _apply_verify,
    "accept_document": _apply_accept_document,
    "adjust": _apply_adjust,
    "review_note": _apply_review_note,
    "resolve_review_note": _apply_resolve_review_note,
    "sign_off": _apply_sign_off,
    "partner_release": _apply_partner_release,
    "approve_adjustment": _apply_approve_adjustment,
    "set_standard": _apply_set_standard,
}


# ---- derived, never stored -----------------------------------------------------

def covered_values(state: State, area: str) -> dict:
    """What a sign-off on `area` covers: every line in the area, as it currently stands.

    For the partner release ('return'): the bottom line of the current version plus
    every adjustment whose tax effect is over the firm threshold. A small receipt
    does not lift the partner release; a large adjustment does.
    """
    if area == RETURN:
        covered = {f"summary.{j}.{k}": v for j, totals in state.version["summary"].items() for k, v in totals.items()}
        for adj in state.adjustments.values():
            if state.active_adjustment(adj.line) and needs_partner(state, adj):
                covered[f"adjustment.{adj.line}"] = adj.value
        return covered
    return {key: state.line_value(key) for key in lines_in_area(state.lines, area)}


def fingerprint(covered: dict) -> str:
    return hashlib.sha256(json.dumps(covered, sort_keys=True, default=str).encode()).hexdigest()


def signoff_payload(state: State, area: str, level: str, waiver: str | None = None) -> dict:
    """Build the payload a sign-off event stores: version, the covered values, their fingerprint."""
    covered = covered_values(state, area)
    payload = {"level": level, "version": state.version_id, "covered": covered, "fingerprint": fingerprint(covered)}
    if waiver:
        payload["waiver"] = waiver
    return payload


def signoff_status(state: State, signoff: SignOff | None) -> dict:
    """Is a sign-off still good? It reopens only when a covered value changed."""
    if signoff is None:
        return {"status": "unsigned"}
    current = covered_values(state, signoff.area)
    if fingerprint(current) == signoff.fingerprint:
        return {"status": "signed", "by": signoff.actor, "event": signoff.event_id, "version": signoff.version}
    changes = [
        {"key": k, "signed": signoff.covered.get(k), "now": current.get(k)}
        for k in sorted(set(signoff.covered) | set(current))
        if signoff.covered.get(k) != current.get(k)
    ]
    return {
        "status": "reopened",
        "by": signoff.actor,
        "event": signoff.event_id,
        "signed_version": signoff.version,
        "current_version": state.version_id,
        "changes": changes,
    }


def area_status(state: State, area: str) -> dict:
    """Preparer and reviewer ticks for a work area. The reviewer must be a different person."""
    levels = state.signoffs.get(area, {})
    preparer = signoff_status(state, levels.get("preparer"))
    reviewer = signoff_status(state, levels.get("reviewer"))
    problems = []
    p, r = levels.get("preparer"), levels.get("reviewer")
    if p and r and p.actor == r.actor:
        problems.append("preparer and reviewer are the same person (firm rule)")
    complete = preparer["status"] == "signed" and reviewer["status"] == "signed" and not problems
    return {"area": area, "preparer": preparer, "reviewer": reviewer, "problems": problems, "complete": complete}


def adjustment_effect(state: State, adj: Adjustment) -> Effect | None:
    """Estimated tax effect of an adjustment, from the version's per-dollar rates."""
    if not isinstance(adj.value, (int, float)) or not isinstance(adj.original, (int, float)):
        return None
    line = state.lines.get(adj.line, {})
    delta = adj.value - adj.original
    rates = state.version["tax_effect_rates"]
    if line.get("jurisdiction") == "california":
        # California-only line: a payment, or a California-source amount (Schedule CA column E).
        if adj.line.startswith("SchCA540NR.") and adj.line.endswith(".E"):
            return estimate(rates, california=[("ca_source_income", delta)])
        category = category_for_line(adj.line)
        return estimate(rates, california=[(category, delta)]) if category else None
    category = category_for_line(adj.line)
    if category is None:
        return None
    if category == "payment":
        return estimate(rates, federal=[(category, delta)])  # a federal payment has no California effect
    # A federal income or deduction change flows into California AGI at the same category's rate.
    return estimate(rates, federal=[(category, delta)], california=[(category, delta)])


def needs_partner(state: State, adj: Adjustment) -> bool:
    """Firm rule: any adjustment with a federal or state tax effect over 1,000 needs partner sign-off."""
    eff = adjustment_effect(state, adj)
    return eff is not None and (abs(eff.federal) > 1000 or abs(eff.california) > 1000)


def release_blockers(state: State) -> list[str]:
    """Why the partner cannot release the return yet. Empty list = clear to release."""
    blockers = []
    for note in state.open_review_notes():
        blockers.append(f"open review note (event {note.event_id})")
    for area in SIGNED_AREAS:
        # A signed waiver counts as signed: the open item and the sentence are on the sign-off.
        if not area_status(state, area)["complete"]:
            blockers.append(f"area not signed: {area}")
    for adj in state.adjustments.values():
        if state.active_adjustment(adj.line) and needs_partner(state, adj) and adj.event_id not in state.partner_approvals:
            blockers.append(f"adjustment to {adj.line} needs partner sign-off (event {adj.event_id})")
    return blockers
