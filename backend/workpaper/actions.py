"""Writes: turn a request into an event, and check it against the firm's rules first.

Both functions are pure. The browser sends only what the person chose (the line and the
new figure, the area to sign, the reason). The server computes everything derived: an
adjustment's from and its tax effect, a sign-off's covered values and fingerprint, the
values an acceptance covers. Nothing the browser computes is trusted.

Refusals: 403 when the role may not do this at all, 422 when it breaks a firm rule.
A stale view is not checked here; the event store refuses it with 409 (concurrency.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import notices
from .areas import RETURN, SIGNED_SCOPES
from .checker import CheckResult
from .concurrency import GUARDED, ConflictRule
from .events import Event
from .filing import filing_status
from .identity import number_on, ssns_on_return
from .packet import Packet, ref_kind
from .project import (
    DISPOSITIONS, State, adjustment_payload, large_adjustments, release_blockers, signoff_payload,
)
from .roles import ROLE_ACTIONS, SIGN_LEVEL


@dataclass
class Refusal(Exception):
    status: int          # 403: the role may not do this; 422: it breaks a firm rule
    reasons: list[str]


def prepare(packet: Packet, state: State, result: CheckResult, scopes: ConflictRule, person: dict, action: str,
            targets: list[str], payload: dict | None, reason: str | None, base_tip: int) -> Event:
    """Build the event the log will store. Raises Refusal(403) if the role may not act at all."""
    if action not in ROLE_ACTIONS.get(person["role"], set()):
        raise Refusal(403, [f"{person['name']} ({person['role']}) may not {action.replace('_', ' ')}"])
    p = dict(payload or {})
    if action == "adjust":
        key = _one(targets, "line")[len("line:"):]
        adds = None
        if key not in state.lines:
            adds = result.proposed_line(key)
            if adds is None:
                raise Refusal(422, [f"{key} is not a line on {state.version_id}, and no finding proposes adding it."])
        p = adjustment_payload(state, key, p.get("to"), p.get("finding"), adds=adds)
    elif action == "sign_off":
        area = _one(targets, "area")[len("area:"):]
        waiver = (p.get("waiver") or "").strip() or None
        p = signoff_payload(state, area, SIGN_LEVEL[person["role"]], waiver=waiver,
                            waived=_waived(result, scopes, area) if waiver else None)
    elif action == "partner_release":
        p = signoff_payload(state, RETURN, "partner", waiver=p.get("waiver"))
    elif action == "accept_document":
        doc = _one(targets, "document")
        values = packet.values_by_doc.get(doc, [])
        p = {"verification_type": p.get("verification_type"), "at_summary": bool(p.get("at_summary")),
             "values": {ev["id"]: ev["value"] for ev in values}}
    elif action == "verify":
        p = {"verification_type": p.get("verification_type"),
             "values": {t: _current_value(packet, state, t) for t in targets}}
    elif action == "judgment_call":
        p["effect"] = _accepted_effect(result, targets, p.get("finding"))
    elif action == "correct_identity":
        person_id = _one(targets, "person")[len("household:"):]
        p = {"person": person_id, "document": p.get("document"), **({"finding": p["finding"]} if p.get("finding") else {})}
    elif action in ("sign_8879", "transmit"):
        # What the clients sign and what the agency receives: the return as it stands now, computed here.
        status = filing_status(state)
        p = {"presented": status["presented"], "fingerprint": status["fingerprint"]}
        if action == "transmit":
            p["kind"] = status["next_kind"]
    elif action == "open_amendment":
        filed = filing_status(state)["filed"]
        p = {"amends": filed.event_id if filed else None}
    elif action == "notice_response":
        p = {"item": p.get("item"), "text": (p.get("text") or "").strip()}
    elif action == "release_notice_response":
        notice = notices.notice_by_ref(state, _one(targets, "notice"))
        p = notices.package(packet, state, notice) if notice else {}
    elif action == "log_time":
        p = {"hours": p.get("hours"), "on": p.get("on"), "text": (p.get("text") or "").strip()}
    elif action == "undo":
        target = next((e for e in state.events if f"event:{e.id}" == _one(targets, "event")), None)
        p = {"undoes": {"action": target.action, "targets": list(target.targets)} if target else {}}
    return Event(actor=person["id"], role=person["role"], action=action, targets=tuple(targets),
                 payload=p, reason=(reason or "").strip() or None, base_tip=base_tip)


def validate(packet: Packet, state: State, result: CheckResult, scopes: ConflictRule,
             person: dict, event: Event) -> None:
    """Apply the firm's rules to a prepared event. Raises Refusal(422) with every reason that applies."""
    planning = event.action == "judgment_call" and event.targets and all(ref_kind(t) == "plan" for t in event.targets)
    if event.action in FROZEN_REFUSES and not planning and (status := filing_status(state))["frozen"]:
        raise Refusal(422, [f"The return was filed (event {status['filed'].event_id}) and is frozen. "
                            f"Open an amendment to change it."])
    check = CHECKS.get(event.action)
    reasons = check(packet, state, result, scopes, person, event) if check else []
    if reasons:
        raise Refusal(422, reasons)


# After filing, nothing that changes the return or its record is accepted until an amendment opens
# (D25). Notes, questions, answers, evidence, time and the notice response still append; the
# firm's standards are firm-wide, not this return's; a planning decision is about 2026 (D32).
FROZEN_REFUSES = (GUARDED | {"judgment_call"}) - {"set_standard", "open_amendment", "release_notice_response"}


# ---- one check per action -------------------------------------------------------

def _sign_off(packet, state, result, scopes, person, e) -> list[str]:
    area = e.targets[0][len("area:"):]
    if area not in SIGNED_SCOPES:
        return [f"{area} is not a signed area"]
    reasons = []
    level = e.payload["level"]
    other = state.signoffs.get(area, {}).get("reviewer" if level == "preparer" else "preparer")
    if other and other.actor == person["id"]:
        reasons.append("A person may not review or sign off on work they prepared (firm rule).")
    if level == "reviewer":
        own = [a.line for a in state.applied_adjustments()
               if a.actor == person["id"] and f"area:{area}" in scopes.refs_scope([f"line:{a.line}"])]
        if own:
            reasons.append(f"You adjusted {', '.join(sorted(own))} in this area; another reviewer must sign "
                           f"(a person may not review work they prepared).")
    open_errors = [f.id for f in _open_errors(result, scopes, area)]
    if open_errors and not (e.payload.get("waiver") or "").strip():
        reasons.append(f"Open items in this area: {', '.join(open_errors)}. Resolve them or sign with a waiver "
                       f"sentence that says why.")
    return reasons


def _verification_type(packet, state, result, scopes, person, e) -> list[str]:
    allowed = state.standards["verification_types"]
    vt = e.payload.get("verification_type")
    return [] if vt in allowed else [f"Verification type must be one of: {', '.join(allowed)}."]


def _verify(packet, state, result, scopes, person, e) -> list[str]:
    reasons = _verification_type(packet, state, result, scopes, person, e)
    missing = [t for t in e.targets
               if not (t in packet.values or (t.startswith("line:") and t[len("line:"):] in state.lines))]
    if not e.targets:
        reasons.append("Choose what you verified.")
    if missing:
        reasons.append(f"Nothing to verify at {', '.join(missing)}.")
    return reasons


def _accept_document(packet, state, result, scopes, person, e) -> list[str]:
    """Accepting a document verifies all its values in one act (D21). Refused for a copy, a superseded
    document, or one with unread pages not yet dispositioned: otherwise accepting D10 would verify a
    second set of wages. A copy or a superseded document is never accepted, so its unread pages
    are not mentioned; the other document is the one to accept."""
    reasons = _verification_type(packet, state, result, scopes, person, e)
    if not e.payload.get("values"):
        reasons.append("That document has no values to accept.")
    doc = e.targets[0]
    open_findings = [f for f in result.findings if f.status == "open"]
    disp = state.dispositions.get(doc)
    if disp and disp.disposition in ("duplicate", "superseded"):
        other = disp.detail.get("of") or disp.detail.get("by")
        return reasons + [f"{doc} is dispositioned {disp.disposition}; accept {other} instead."]
    for f in open_findings:
        if f.code == "DUPLICATE_DOCUMENT" and f.subject == doc:
            return reasons + [f"{doc} looks like a copy of {f.details['duplicate_of']}. Record its disposition first."]
        if f.code == "SUPERSEDED_DOCUMENT" and f.subject == doc:
            return reasons + [f"{doc} is replaced by the corrected {f.details['by']}. Record its disposition first."]
    named = disp.detail.get("pages", []) if disp and disp.disposition == "partial" else []
    for f in open_findings:
        if f.code == "PAGE_NOT_READ" and f.subject.startswith(f"{doc}#page"):
            page = int(f.subject.split("#page")[1])
            if page not in named:   # still open after the disposition only for the lot it prints, not the page
                reasons.append(f"Page {page} of {doc} was never read. Record a partial disposition for it first.")
    return reasons


def _adjust(packet, state, result, scopes, person, e) -> list[str]:
    reasons = []
    if not e.reason:
        reasons.append("An adjustment needs a reason.")
    if not isinstance(e.payload.get("to"), (int, float)):
        reasons.append("An adjustment needs a numeric new figure.")
    return reasons


def _judgment_call(packet, state, result, scopes, person, e) -> list[str]:
    reasons = []
    if not (e.payload.get("authority") or "").strip():
        reasons.append("Every judgment call records the authority relied on (firm rule).")
    if not (e.payload.get("decision") or "").strip():
        reasons.append("A judgment call needs the decision.")
    return reasons


def _undo(packet, state, result, scopes, person, e) -> list[str]:
    target_id = int(e.targets[0][len("event:"):])
    target = next((x for x in state.events if x.id == target_id), None)
    if target is None:
        return [f"There is no event {target_id}."]
    if target.action == "undo":
        return ["An undo cannot be undone; record the act again instead."]
    if target.action in ("transmit", "release_notice_response"):
        return ["That left the firm (the agency or the examiner has it); it cannot be undone."]
    if target.action == "sign_8879":
        return ["A client's signature is replaced only by the client signing again."]
    if target_id in state.undone:
        return [f"Event {target_id} is already undone."]
    if target.actor != person["id"] and person["role"] not in ("reviewer", "partner"):
        return ["Only the person who acted, a reviewer or the partner can undo it."]
    return [] if e.reason else ["An undo needs a reason."]


def _resolve_review_note(packet, state, result, scopes, person, e) -> list[str]:
    note = state.review_notes.get(int(e.targets[0][len("event:"):]))
    if note is None or not note.is_open:
        return ["That is not an open review note."]
    return []


def _approve_adjustment(packet, state, result, scopes, person, e) -> list[str]:
    ids = {a.event_id for a in large_adjustments(state)}
    return [] if int(e.targets[0][len("event:"):]) in ids else ["That is not an adjustment over the partner threshold."]


def _partner_release(packet, state, result, scopes, person, e) -> list[str]:
    return release_blockers(state)


def _set_standard(packet, state, result, scopes, person, e) -> list[str]:
    node = state.standards
    for part in e.payload.get("path", "").split("."):
        if not isinstance(node, dict) or part not in node:
            return [f"There is no firm standard {e.payload.get('path')!r}."]
        node = node[part]
    value = e.payload.get("value")
    reasons = [] if e.reason else ["A change to a firm standard needs a reason."]
    if isinstance(node, (int, float)) and not (isinstance(value, (int, float)) and value >= 0):
        reasons.append("That standard is a number of zero or more.")
    elif isinstance(node, list) and not (isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value)):
        reasons.append("That standard is a list of entries, none of them empty.")
    elif isinstance(node, str) and not (isinstance(value, str) and value.strip()):
        reasons.append("That standard is a sentence.")
    return reasons


def _correct_identity(packet, state, result, scopes, person, e) -> list[str]:
    """Take a person's SSN from a document that prints it (D23). The log keeps the document, not digits."""
    pid, doc = e.payload["person"], e.payload.get("document")
    if pid not in packet.people or not packet.people[pid].get("ssn"):
        return [f"{pid} is not someone on the return."]
    if doc not in packet.documents or not state.document_visible(packet.documents[doc]):
        return ["Name a document that has arrived."]
    number = number_on(packet, pid, doc)
    if number is None:
        return [f"{doc} does not print an SSN for {packet.people[pid]['name']}."]
    if ssns_on_return(state)[pid]["ssn"] == number:
        return [f"The return already carries the number {doc} prints."]
    return [] if e.reason else ["Say why the number changes."]


def _sign_8879(packet, state, result, scopes, person, e) -> list[str]:
    status = filing_status(state)
    if not status["release"]["current"]:
        return [f"There is nothing to sign yet: {status['release']['why']}"]
    if status["form_8879"]["signers"][person["id"]]["current"]:
        return ["You already signed the return as it stands."]
    return []


def _transmit(packet, state, result, scopes, person, e) -> list[str]:
    """Transmit needs the partner release and a current 8879 from both spouses (D23). It does not need
    the identity finding closed: the agency answers from the digits on the return."""
    return filing_status(state)["transmit_blockers"]


def _open_amendment(packet, state, result, scopes, person, e) -> list[str]:
    status = filing_status(state)
    if status["amendment_open"]:
        return ["An amendment is already open."]
    if not status["frozen"]:
        return ["Nothing to amend: the return has not been filed."]
    return [] if e.reason else ["An amendment needs a reason."]


def _notice_response(packet, state, result, scopes, person, e) -> list[str]:
    notice = notices.notice_by_ref(state, next((t for t in e.targets if t.startswith("notice:")), ""))
    if notice is None:
        return ["There is no such notice (a notice about this return arrives only after it was accepted)."]
    reasons = []
    if not isinstance(e.payload.get("item"), int) or not 0 <= e.payload["item"] < len(notices.items(notice)):
        reasons.append("Answer one of the items the notice lists.")
    if not e.payload.get("text"):
        reasons.append("Write the answer.")
    return reasons


def _release_notice_response(packet, state, result, scopes, person, e) -> list[str]:
    notice = notices.notice_by_ref(state, e.targets[0])
    if notice is None:
        return ["There is no such notice."]
    answered = notices.drafts(state, notice["id"])
    missing = [i + 1 for i in range(len(notices.items(notice))) if i not in answered]
    return [f"Item {', '.join(map(str, missing))} has no answer yet."] if missing else []


def _log_time(packet, state, result, scopes, person, e) -> list[str]:
    bucket = e.targets[0][len("time:"):] if e.targets and e.targets[0].startswith("time:") else None
    reasons = []
    if bucket not in packet.raw["firm"]["budget_hours"]:
        reasons.append(f"Log time to one of: {', '.join(packet.raw['firm']['budget_hours'])}.")
    hours = e.payload.get("hours")
    if not isinstance(hours, (int, float)) or not 0 < hours <= 12:
        reasons.append("Hours are more than 0 and at most 12 per entry.")
    return reasons


def _disposition(packet, state, result, scopes, person, e) -> list[str]:
    """Disposition comes first (D2): say what the document is to the return, and why."""
    reasons = []
    value = e.payload.get("disposition")
    if value not in DISPOSITIONS:
        reasons.append(f"Disposition must be one of: {', '.join(sorted(DISPOSITIONS))}.")
    if not e.targets or any(t not in packet.documents for t in e.targets):
        reasons.append("A disposition targets documents.")
    if not e.reason:
        reasons.append("A disposition needs a reason.")
    if value == "duplicate" and e.payload.get("of") not in packet.documents:
        reasons.append("A duplicate names the document it copies (of).")
    if value == "superseded" and e.payload.get("by") not in packet.documents:
        reasons.append("A superseded document names the document that replaces it (by).")
    if value == "partial":
        pages = e.payload.get("pages") or []
        known = {p["page"] for t in e.targets if t in packet.documents for p in packet.documents[t]["pages"]}
        if not pages or not set(pages) <= known:
            reasons.append("A partial disposition lists the pages it covers (pages).")
    return reasons


def _text_required(packet, state, result, scopes, person, e) -> list[str]:
    return [] if (e.payload.get("text") or "").strip() else ["Write the note."]


def _note(packet, state, result, scopes, person, e) -> list[str]:
    reasons = _text_required(packet, state, result, scopes, person, e)
    if not e.targets:
        reasons.append("Say what the note is about.")
    return reasons


def _question(packet, state, result, scopes, person, e) -> list[str]:
    reasons = _text_required(packet, state, result, scopes, person, e)
    if e.payload.get("to") not in ("client", *packet.staff):
        reasons.append("A question goes to the client or to a colleague (staff id).")
    return reasons


def _answer(packet, state, result, scopes, person, e) -> list[str]:
    target_id = int(e.targets[0][len("event:"):]) if e.targets and e.targets[0].startswith("event:") else None
    question = next((x for x in state.events if x.id == target_id and x.action == "question"), None)
    if question is None:
        return ["An answer targets a question (event:<id>)."]
    if person["role"] == "client" and question.payload.get("to") != "client":
        return ["That question was not sent to the client."]
    return _text_required(packet, state, result, scopes, person, e)


CHECKS = {
    "sign_off": _sign_off,
    "verify": _verify,
    "accept_document": _accept_document,
    "adjust": _adjust,
    "judgment_call": _judgment_call,
    "undo": _undo,
    "resolve_review_note": _resolve_review_note,
    "approve_adjustment": _approve_adjustment,
    "partner_release": _partner_release,
    "set_standard": _set_standard,
    "disposition": _disposition,
    "correct_identity": _correct_identity,
    "sign_8879": _sign_8879,
    "transmit": _transmit,
    "open_amendment": _open_amendment,
    "notice_response": _notice_response,
    "release_notice_response": _release_notice_response,
    "log_time": _log_time,
    "note": _note,
    "review_note": _note,
    "question": _question,
    "answer": _answer,
}


# ---- helpers --------------------------------------------------------------------

def _open_errors(result: CheckResult, scopes: ConflictRule, area: str) -> list:
    return [f for f in result.findings
            if f.status == "open" and f.severity == "error" and f"area:{area}" in scopes.refs_scope(f.targets)]


def _waived(result: CheckResult, scopes: ConflictRule, area: str) -> list[dict]:
    """The open errors a waiver signs over, with the estimated effect at the moment of signing."""
    out = []
    for f in _open_errors(result, scopes, area):
        effect = f.effect
        out.append({"id": f.id, "federal": effect.federal if effect else 0,
                    "california": effect.california if effect else 0})
    return out


def _accepted_effect(result: CheckResult, targets: list[str], finding: str | None) -> dict:
    """What accepting a finding leaves out of the total: its estimated effect at the moment of the
    judgment call (D20). Computed here, so a figure the browser sends is never stored."""
    ids = [t[len("finding:"):] for t in targets if t.startswith("finding:")] + ([finding] if finding else [])
    effects = [f.effect for f in result.findings if f.id in ids and f.effect]
    return {"federal": sum(e.federal for e in effects), "california": sum(e.california for e in effects)}


def _one(targets: list[str], kind: str) -> str:
    if len(targets) != 1 or ref_kind(targets[0]) != kind:
        raise Refusal(422, [f"This act targets exactly one {kind}."])
    return targets[0]


def _current_value(packet: Packet, state: State, ref: str):
    if ref.startswith("line:"):
        return state.line_value(ref[len("line:"):])
    ev = packet.values.get(ref)
    return ev["value"] if ev else None
