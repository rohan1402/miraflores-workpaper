"""Current state = project(packet, events).

A pure function: same packet and same events always give the same state. It never
writes anything and never changes the packet. Everything the screen shows about
human work comes from here; the checker reads the result.

Replay order is the log position (the integer id the store assigns inside the insert
transaction), never the wall clock: two events can share a second. The `at` time is
only used to answer "as of this date" (pass `as_of`), which buys season replay,
"since I last looked", freeze at filing, and amend on top.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field

from .areas import CALIFORNIA, RETURN, SIGNED_SCOPES, lines_in_area
from .events import Event
from .packet import Packet
from .taxeffect import Effect, category_for_line, direction_for_line, estimate

DISPOSITIONS = {"used", "duplicate", "superseded", "not_extracted", "partial"}
PARTNER_THRESHOLD = 1000  # firm rule: adjustments with a tax effect over 1,000 need the partner

# The version summary, mapped to the lines it reports, so a reopened partner release can name causes.
SUMMARY_LINES = {
    "federal": {"agi": "F1040.11", "taxable_income": "F1040.15", "total_tax": "F1040.24",
                "payments": "F1040.33", "balance_due": "F1040.37", "penalty": "F1040.38"},
    "california": {"total_agi": "F540NR.17", "ca_agi": "F540NR.32", "total_tax": "F540NR.64",
                   "payments": "F540NR.78", "balance_due": "F540NR.97", "penalty": "FTB5805.penalty"},
}


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
    original: object         # the figure on screen when the person adjusted (after earlier adjustments)
    value: object            # the figure they set
    version: str             # return version they adjusted against
    effect: dict | None      # estimated tax effect stored with the act; what the partner signs
    reason: str | None
    finding: str | None      # checker finding it answers, if any
    applied: bool = False    # set after replay: does `original` still match the figure on screen?


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
    area: str                # a work area, 'california', or 'return' for the partner release
    level: str               # preparer | reviewer | partner
    version: str
    covered: dict            # the values signed
    fingerprint: str
    waiver: str | None = None
    waived: tuple[dict, ...] = ()   # area sign-off: open error findings signed over, with their stored effect
    approves: tuple[int, ...] = ()  # partner release: the large adjustments it approves
    accepts: tuple[str, ...] = ()   # partner release: the large waived findings it accepts


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
    adjustments: dict[str, list[Adjustment]] = field(default_factory=dict)  # per line, in log order
    figures: dict[str, object] = field(default_factory=dict)                # line -> figure after adjustments
    review_notes: dict[int, ReviewNote] = field(default_factory=dict)
    signoffs: dict[str, dict[str, SignOff]] = field(default_factory=dict)  # scope -> level -> sign-off
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

    def line_value(self, key: str):
        """The figure as the workpaper currently stands: engine value plus the adjustments that still apply."""
        return self.figures.get(key, self.original_value(key))

    def applied_adjustments(self) -> list[Adjustment]:
        return [a for chain in self.adjustments.values() for a in chain if a.applied]

    def stale_adjustments(self) -> list[Adjustment]:
        """Adjustments whose 'from' no longer matches the figure on screen (a new version, or an undo before them)."""
        return [a for chain in self.adjustments.values() for a in chain if not a.applied]

    # ---- review notes --------------------------------------------------------

    def open_review_notes(self) -> list[ReviewNote]:
        return [n for n in self.review_notes.values() if n.is_open]


# ---- the replay ----------------------------------------------------------------

def project(packet: Packet, events: list[Event], as_of: str | None = None) -> State:
    """Replay `events` in log order on top of the packet, up to `as_of` if given."""
    applied = sorted((e for e in events if as_of is None or e.at <= as_of), key=lambda e: e.id)
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
    _settle_adjustments(state)
    return state


def _settle_adjustments(state: State) -> None:
    """Walk each line's adjustments in log order. One applies only if its 'from' equals the figure on screen."""
    for key, chain in state.adjustments.items():
        figure = state.original_value(key)
        for adj in chain:
            adj.applied = _same(adj.original, figure)
            if adj.applied:
                figure = adj.value
        state.figures[key] = figure


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.005
    return a == b


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
        state.adjustments.setdefault(key, []).append(Adjustment(
            **_act(e), line=key, original=e.payload["from"], value=e.payload["to"],
            version=e.payload.get("version", state.version_id), effect=e.payload.get("effect"),
            reason=e.reason, finding=e.payload.get("finding"),
        ))


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
            waiver=e.payload.get("waiver"), waived=tuple(e.payload.get("waived", ())),
        )


def _apply_partner_release(state: State, e: Event) -> None:
    approves = tuple(e.payload.get("approves", ()))
    state.partner_release = SignOff(
        **_act(e), area=RETURN, level="partner", version=e.payload["version"],
        covered=e.payload["covered"], fingerprint=e.payload["fingerprint"],
        waiver=e.payload.get("waiver"), approves=approves, accepts=tuple(e.payload.get("waivers", ())),
    )
    for adjustment_id in approves:  # Helen signs once: the release approves the large adjustments it lists
        state.partner_approvals[adjustment_id] = Act(**_act(e))


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


# ---- adjustments: what to store when a person adjusts --------------------------

def adjustment_payload(state: State, key: str, to, finding: str | None = None) -> dict:
    """The payload an adjust event stores: from = the figure on screen, to, the version, and the
    estimated tax effect at this version's rates. The stored effect is what the partner signs."""
    original = state.line_value(key)
    effect = estimate_adjustment(state, key, original, to)
    payload = {"from": original, "to": to, "version": state.version_id,
               "effect": {**effect.as_dict(), "rates_version": state.version_id} if effect else None}
    if finding:
        payload["finding"] = finding
    return payload


def estimate_adjustment(state: State, key: str, original, value) -> Effect | None:
    """Estimated tax effect of changing a line, from the current version's per-dollar rates."""
    if not isinstance(value, (int, float)) or not isinstance(original, (int, float)):
        return None
    direction = direction_for_line(key)
    if direction is None:
        return None
    line = state.lines.get(key, {})
    delta = (value - original) * direction  # an expense that falls raises the income the rate measures
    rates = state.version["tax_effect_rates"]
    if line.get("jurisdiction") == "california":
        # California-only line: a payment, or a California-source amount (Schedule CA column E).
        if key.startswith("SchCA540NR.") and key.endswith(".E"):
            return estimate(rates, california=[("ca_source_income", delta)])
        category = category_for_line(key)
        return estimate(rates, california=[(category, delta)]) if category else None
    category = category_for_line(key)
    if category is None:
        return None
    if category == "payment":
        return estimate(rates, federal=[(category, delta)])  # a federal payment has no California effect
    # A federal income or deduction change flows into California AGI at the same category's rate.
    return estimate(rates, federal=[(category, delta)], california=[(category, delta)])


def effect_view(state: State, adj: Adjustment) -> dict:
    """The stored effect, and a fresh estimate beside it when the rates have moved since."""
    fresh = estimate_adjustment(state, adj.line, adj.original, adj.value)
    fresh_d = fresh.as_dict() if fresh else None
    stored = adj.effect
    differs = bool(stored and fresh_d and (stored["federal"], stored["california"]) != (fresh_d["federal"], fresh_d["california"]))
    return {"stored": stored, "fresh": fresh_d if differs else None, "differs": differs}


def needs_partner(adj: Adjustment) -> bool:
    """Firm rule, tested on the effect stored with the adjustment (what the partner will sign)."""
    eff = adj.effect
    return bool(eff) and (abs(eff["federal"]) > PARTNER_THRESHOLD or abs(eff["california"]) > PARTNER_THRESHOLD)


def large_adjustments(state: State) -> list[Adjustment]:
    return [a for a in state.applied_adjustments() if needs_partner(a)]


def large_waivers(state: State) -> list[dict]:
    """Open errors signed over with a waiver whose stored effect is over the firm threshold.
    Like a large adjustment, each one must reach the partner: the release lists it."""
    found: dict[str, dict] = {}
    for area, levels in state.signoffs.items():
        for signoff in levels.values():
            for w in signoff.waived:
                if abs(w.get("federal", 0)) > PARTNER_THRESHOLD or abs(w.get("california", 0)) > PARTNER_THRESHOLD:
                    found.setdefault(w["id"], {**w, "area": area, "signoff_event": signoff.event_id})
    return [found[k] for k in sorted(found)]


# ---- sign-offs: derived, never stored ------------------------------------------

def covered_values(state: State, area: str) -> dict:
    """What a sign-off covers: every line in the area (or the California lens), as it currently stands.

    For the partner release ('return'): the bottom line of the current version plus every
    adjustment whose stored effect is over the firm threshold. A small receipt does not
    lift the partner release; a large adjustment does.
    """
    if area == RETURN:
        covered = {f"summary.{j}.{k}": v for j, totals in state.version["summary"].items() for k, v in totals.items()}
        for adj in large_adjustments(state):
            covered[f"adjustment.{adj.event_id}"] = {"line": adj.line, "to": adj.value, "effect": adj.effect}
        for w in large_waivers(state):
            covered[f"waived.{w['id']}"] = {"area": w["area"], "federal": w["federal"], "california": w["california"]}
        return covered
    covered = {key: state.line_value(key) for key in lines_in_area(state.lines, area)}
    if area == CALIFORNIA:
        covered.update(_california_view(state, list(covered)))
    return covered


def _california_view(state: State, lens_lines: list[str]) -> dict:
    """What the California signature covers besides the line values: the allocation and the
    California-only figures behind them. The residency dates, every field the lens lines rest on
    (box 16, the state supplement's California share, each FTB payment with its tax-year tag,
    including the September payment tagged 2024), and the California depreciation of each asset."""
    view: dict = {"household.residency": state.packet.raw["household"]["residency"]}
    assets = {a["asset_id"]: a for a in state.version["assets"]}
    for key in lens_lines:
        for s in state.lines[key]["sources"]:
            if s in state.packet.values:
                view[field_key(state.packet, s)] = state.packet.values[s]["value"]
            elif s.startswith("asset:") and s[len("asset:"):] in assets:
                view[s] = assets[s[len("asset:"):]]["california"]
    return view


def field_key(packet: Packet, ev_id: str) -> str:
    """A field named by what it is, not by which copy it was read from: 'field:Meridian Brokerage int_3'.
    A corrected 1099 that repeats the same California figure leaves the view unchanged."""
    ev = packet.values[ev_id]
    return f"field:{packet.documents[ev['document_id']]['issuer']} {ev['field']}"


def fingerprint(covered: dict) -> str:
    return hashlib.sha256(json.dumps(covered, sort_keys=True, default=str).encode()).hexdigest()


def signoff_payload(state: State, area: str, level: str, waiver: str | None = None,
                    waived: list[dict] | None = None) -> dict:
    """Build the payload a sign-off event stores: version, the covered values, their fingerprint.

    An area sign-off with a waiver also stores the open error findings it signs over, each with
    its estimated effect (`waived`). A partner release lists the large adjustments it approves
    and the large waived findings it accepts, so Helen signs both once."""
    covered = covered_values(state, area)
    payload = {"level": level, "version": state.version_id, "covered": covered, "fingerprint": fingerprint(covered)}
    if area == RETURN:
        payload["approves"] = [a.event_id for a in large_adjustments(state)]
        payload["waivers"] = [w["id"] for w in large_waivers(state)]
    if waiver:
        payload["waiver"] = waiver
        payload["waived"] = list(waived or [])
    return payload


def signoff_status(state: State, signoff: SignOff | None) -> dict:
    """Is a sign-off still good? It reopens only when a covered value changed, and says why."""
    if signoff is None:
        return {"status": "unsigned"}
    current = covered_values(state, signoff.area)
    if fingerprint(current) == signoff.fingerprint:
        return {"status": "signed", "by": signoff.actor, "event": signoff.event_id, "version": signoff.version}
    causes_of = _cause_finder(state, signoff)
    changes = [
        {"key": k, "signed": signoff.covered.get(k), "now": current.get(k), "causes": causes_of(k)}
        for k in sorted(set(signoff.covered) | set(current))
        if signoff.covered.get(k) != current.get(k)
    ]
    by_cause: dict[str, list[str]] = {}
    for c in changes:
        for cause in c["causes"]:
            by_cause.setdefault(cause, []).append(c["key"])
    return {
        "status": "reopened",
        "by": signoff.actor,
        "event": signoff.event_id,
        "signed_version": signoff.version,
        "current_version": state.version_id,
        "changes": changes,
        "causes": by_cause,
    }


def _cause_finder(state: State, signoff: SignOff):
    """Explain each changed covered value: the new documents or records behind a version change,
    and the events (adjustments, undos) after the sign-off."""
    version_causes = version_change_causes(state.packet, signoff.version, state.version_id)

    def causes_of(key: str) -> list[str]:
        if key.startswith("adjustment."):
            return [f"event:{key.split('.', 1)[1]}"]
        if key.startswith("waived."):   # a large waived finding: the sign-off that waived it
            found = [w for w in large_waivers(state) if w["id"] == key[len("waived."):]]
            return [f"event:{found[0]['signoff_event']}"] if found else ["recomputed"]
        if key.startswith("field:"):   # a California figure changed, entered or left: the document it sits on
            return _documents_for_field(state, signoff.version, key) or ["recomputed"]
        if key.startswith(("asset:", "household.")):
            return [key]
        line_key = _summary_line(key) if key.startswith("summary.") else key
        found = list(version_causes(line_key)) if signoff.version != state.version_id else []
        for e in state.events:
            if e.id > signoff.event_id and e.action in ("adjust", "undo") and (
                    f"line:{line_key}" in e.targets
                    or f"line:{line_key}" in e.payload.get("undoes", {}).get("targets", [])):
                found.append(f"event:{e.id}")
        return found or ["recomputed"]
    return causes_of


def _documents_for_field(state: State, signed_version: str, key: str) -> list[str]:
    """The documents a California field key was read from, now or in the signed version (newest first)."""
    found = []
    for version_id in (state.version_id, signed_version):
        for line in state.packet.lines[version_id].values():
            for s in line["sources"]:
                if s in state.packet.values and field_key(state.packet, s) == key:
                    doc = state.packet.values[s]["document_id"]
                    if doc not in found:
                        found.append(doc)
        if found:
            return found
    return found


def _summary_line(key: str) -> str:
    _, jurisdiction, name = key.split(".", 2)
    return SUMMARY_LINES.get(jurisdiction, {}).get(name, key)


def version_change_causes(packet: Packet, old_id: str, new_id: str):
    """Why a line differs between two versions. Walks the line and its changed inputs and returns the
    documents new in `new_id` that it cites, and any reference the old version did not cite
    (e.g. timeline:extension-2026-04-14 for the extension payment)."""
    old, new = packet.lines[old_id], packet.lines[new_id]
    old_v, new_v = packet.version_by_id[old_id], packet.version_by_id[new_id]
    new_docs = set(new_v["documents_used"]) - set(old_v["documents_used"])
    # A document superseded in the new version is explained by the new document from the same issuer
    # (a line that only cited the old copy was removed because the corrected copy arrived).
    replaced_by = {
        doc: sorted(d for d in new_docs if packet.documents[d]["issuer"] == packet.documents[doc]["issuer"]) or [doc]
        for doc in set(new_v["documents_superseded"]) - set(old_v["documents_superseded"])
    }
    memo: dict[str, list[str]] = {}

    def causes(key: str) -> list[str]:
        if key in memo:
            return memo[key]
        memo[key] = []  # guards against cycles
        line_new, line_old = new.get(key), old.get(key)
        line = line_new or line_old
        if line is None:
            return []
        old_sources = set(line_old["sources"]) if line_old else set()
        found: set[str] = set()
        for s in line["sources"]:
            if s in packet.values:
                doc = packet.values[s]["document_id"]
                if doc in new_docs:
                    found.add(doc)
                elif doc in replaced_by:
                    found |= set(replaced_by[doc])
            elif s not in old_sources:
                found.add(s)
        for inp in line["inputs"]:
            if (new.get(inp) or {}).get("value") != (old.get(inp) or {}).get("value"):
                found |= set(causes(inp))
        memo[key] = sorted(found)
        return memo[key]

    return causes


def area_status(state: State, area: str) -> dict:
    """Preparer and reviewer ticks for a work area or the California lens. Different people (firm rule)."""
    levels = state.signoffs.get(area, {})
    preparer = signoff_status(state, levels.get("preparer"))
    reviewer = signoff_status(state, levels.get("reviewer"))
    problems = []
    p, r = levels.get("preparer"), levels.get("reviewer")
    if p and r and p.actor == r.actor:
        problems.append("preparer and reviewer are the same person (firm rule)")
    complete = preparer["status"] == "signed" and reviewer["status"] == "signed" and not problems
    return {"area": area, "preparer": preparer, "reviewer": reviewer, "problems": problems, "complete": complete}


def release_blockers(state: State) -> list[str]:
    """Why the partner cannot release the return yet. Empty list = clear to release.

    Large adjustments are not blockers: the release lists them and approves them in the same act.
    """
    blockers = [f"open review note (event {note.event_id})" for note in state.open_review_notes()]
    for area in SIGNED_SCOPES:
        # A signed waiver counts as signed: the open item and the sentence are on the sign-off.
        if not area_status(state, area)["complete"]:
            blockers.append(f"area not signed: {area}")
    return blockers
