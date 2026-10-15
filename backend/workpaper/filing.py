"""Filing: the clients' 8879, transmission, the agency's answer, the freeze and amendments (D23, D25).

Pure functions of the projected state. The log holds only the acts (sign_8879, transmit,
open_amendment) and what was transmitted. The agency's answer is worked out again on every
read from the packet's own records, so it can never drift from them.

The agency is simulated from tax_agency_records.efile, which holds the only answers it gives:
- a transmitted SSN that is not the number the agency holds for that person: the packet's federal
  rejection (R0000-504-02), and California held, not transmitted;
- otherwise the packet's federal acceptance, and California transmitted after it and accepted.
The agency reads the digits on the return, never the checker's status. An amended return goes
through the same check: a wrong number gets the packet's rejection and California is held; a right
one is recorded as filed, since the packet holds no acceptance for an amendment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .identity import printed_ssns, ssns_on_return
from .packet import Packet
from .project import State, fingerprint, signoff_status

JURISDICTIONS = ("federal", "california")


# ---- what the clients approve and what is transmitted ------------------------------

def presented_return(state: State) -> dict:
    """The return as presented to the clients and as transmitted: the engine's summary, the balance
    moved by the estimated effect of every applied adjustment, each line a person changed or added,
    and the SSN of everyone on it. An 8879 signs this; any change to it reopens the 8879."""
    moved = {j: 0 for j in JURISDICTIONS}
    for adj in state.applied_adjustments():
        if adj.effect:
            for j in JURISDICTIONS:
                moved[j] += adj.effect[j]
    summary = state.version["summary"]
    return {
        "version": state.version_id,
        "engine_summary": summary,
        "adjustments_effect": moved,
        "estimated_balance_due": {j: summary[j]["balance_due"] + moved[j] for j in JURISDICTIONS},
        "changed_lines": {a.line: state.line_value(a.line) for a in state.applied_adjustments()},
        "identity": {pid: v["ssn"] for pid, v in ssns_on_return(state).items()},
    }


# ---- the simulated agency -----------------------------------------------------------

_AGENCY_SSNS: dict[int, dict[str, str]] = {}


def agency_ssns(packet: Packet) -> dict[str, str]:
    """The number the agency holds for each person: what the packet's documents print for them, at
    any date (the agency's records do not wait for the firm's mail). No record if they disagree."""
    if id(packet) not in _AGENCY_SSNS:
        records = {}
        for pid, seen in printed_ssns(packet, packet.raw["documents"]).items():
            numbers = {s["ssn"] for s in seen}
            if len(numbers) == 1:
                records[pid] = numbers.pop()
        _AGENCY_SSNS[id(packet)] = records
    return _AGENCY_SSNS[id(packet)]


def agency_answer(packet: Packet, presented: dict, kind: str) -> dict:
    """The agency's answer to one transmission, taken from tax_agency_records.efile. The TIN check
    comes first, for an original and an amendment alike."""
    held = agency_ssns(packet)
    wrong = sorted(pid for pid, ssn in presented["identity"].items() if held.get(pid) and held[pid] != ssn)
    efile = packet.raw["tax_agency_records"]["efile"]
    if wrong:
        return {"federal": _packet_answer(efile, "federal", "rejected"),
                "california": _packet_answer(efile, "california", "not_transmitted"), "wrong_tins": wrong}
    if kind == "amended":
        note = "The packet holds no agency acceptance for an amended return; recorded as filed."
        return {"federal": {"status": "filed", "note": note}, "california": {"status": "filed", "note": note},
                "wrong_tins": []}
    return {"federal": _packet_answer(efile, "federal", "accepted"),
            "california": _packet_answer(efile, "california", "accepted"), "wrong_tins": []}


def _packet_answer(efile: list[dict], jurisdiction: str, status: str) -> dict:
    i, sub = next((i, s) for i, s in enumerate(efile) if s["jurisdiction"] == jurisdiction and s["status"] == status)
    return {"status": status, "submission_id": sub["submission_id"], "errors": sub.get("errors", []),
            "ref": f"agency:/efile/{i}"}


# ---- transmissions, rounds and the freeze ---------------------------------------------

@dataclass
class Transmission:
    event_id: int
    at: str
    actor: str
    kind: str            # original | amended
    presented: dict      # the return as transmitted
    fingerprint: str
    answer: dict         # the agency's answer, derived

    @property
    def filed(self) -> bool:
        """Original: the federal return was accepted. Amended: recorded as filed."""
        return self.answer["federal"]["status"] in ("accepted", "filed")


def transmissions(state: State) -> list[Transmission]:
    return [Transmission(r.event_id, r.at, r.actor, r.payload["kind"], r.payload["presented"], r.payload["fingerprint"],
                         agency_answer(state.packet, r.payload["presented"], r.payload["kind"]))
            for r in state.records if r.action == "transmit"]


def accepted_original(state: State) -> Transmission | None:
    return next((t for t in transmissions(state) if t.kind == "original" and t.filed), None)


def filing_status(state: State) -> dict:
    """Where the return stands: frozen after a filing until an amendment opens; the current round
    (original, or an amendment) and what it still needs before it can be transmitted."""
    sent = transmissions(state)
    filed = [t for t in sent if t.filed]
    amendments = [r for r in state.records if r.action == "open_amendment"]
    last_filed = filed[-1] if filed else None
    amendment_open = bool(amendments and last_filed and amendments[-1].event_id > last_filed.event_id)
    frozen = bool(last_filed) and not amendment_open
    round_start = amendments[-1].event_id if amendment_open else 0
    presented = presented_return(state)
    current_fp = fingerprint(presented)
    release = _release(state, round_start)
    signatures = _form_8879(state, current_fp, round_start)
    blockers = []
    if frozen:
        blockers.append(f"The return was filed (event {last_filed.event_id}) and is frozen. Open an amendment to change it.")
    if not release["current"]:
        blockers.append(release["why"])
    blockers += [f"{s['name']} has not signed the 8879 for the return as it stands now."
                 for s in signatures["signers"].values() if not s["current"]]
    return {
        "frozen": frozen,
        "filed": last_filed,
        "amendment_open": amendment_open,
        "amendment": amendments[-1] if amendment_open else None,
        "round_start": round_start,
        "next_kind": "amended" if any(t.kind == "original" and t.filed for t in sent) else "original",
        "presented": presented,
        "fingerprint": current_fp,
        "release": release,
        "form_8879": signatures,
        "transmit_blockers": blockers,
        "transmissions": sent,
    }


def _release(state: State, round_start: int) -> dict:
    """Transmit needs the partner release, signed in this round and still current."""
    rel = state.partner_release
    if rel is None or rel.event_id <= round_start:
        return {"current": False, "why": "The partner has not released the return" +
                (" since the amendment opened." if round_start else ".")}
    if signoff_status(state, rel)["status"] != "signed":
        return {"current": False, "why": "The partner release reopened: something it signed changed."}
    return {"current": True, "why": None, "event": rel.event_id, "by": rel.actor, "at": rel.at}


def _form_8879(state: State, current_fp: str, round_start: int) -> dict:
    """Both spouses sign the 8879 for the return as presented. A signature counts only for the
    return it signed: a later change (an adjustment, an SSN) leaves it signed but not current."""
    signers = {}
    for cid in state.packet.client_users:
        mine = [r for r in state.records if r.action == "sign_8879" and r.actor == cid and r.event_id > round_start]
        last = mine[-1] if mine else None
        signers[cid] = {"name": state.packet.client_users[cid]["name"], "signed": bool(last),
                        "current": bool(last) and last.payload["fingerprint"] == current_fp,
                        "at": last.at if last else None, "event": last.event_id if last else None}
    return {"signers": signers, "current": all(s["current"] for s in signers.values())}


# ---- after acceptance: the payment or the refund -------------------------------------

def settlement(packet: Packet, filed: Transmission, previous: Transmission | None = None) -> dict:
    """What the accepted return leaves to pay or to refund, per jurisdiction (D23). The balance is
    the estimated balance of the return that was transmitted, dated the day it was transmitted (the
    acceptance; the script's July 20 stays off the calendar). A payment after the original due date
    carries interest and a late-payment penalty, estimated from post_filing_rates.
    For an amendment, the difference from the return filed before it."""
    out = {}
    for j in JURISDICTIONS:
        if filed.answer[j]["status"] not in ("accepted", "filed"):
            continue
        balance = filed.presented["estimated_balance_due"][j]
        if previous:
            balance -= previous.presented["estimated_balance_due"][j]
        if balance > 0:
            out[j] = {"kind": "payment", "amount": balance, "on": filed.at[:10],
                      **_late_charges(packet, j, balance, filed.at[:10])}
        elif balance < 0:   # a refund is dated the same way, and carries no interest or penalty
            out[j] = {"kind": "refund", "amount": -balance, "on": filed.at[:10]}
    return out


def months_late(due: str, paid: str) -> int:
    """Months or part of a month after the due date (how the late-payment penalty counts)."""
    d, p = date.fromisoformat(due), date.fromisoformat(paid)
    return max(0, (p.year - d.year) * 12 + (p.month - d.month) + (1 if p.day > d.day else 0))


def original_due_date(packet: Packet) -> str:
    return next(d["date"] for d in packet.raw["firm"]["deadlines"] if "original due date" in d["what"])


def _late_charges(packet: Packet, jurisdiction: str, balance: float, paid_on: str) -> dict:
    """An extension of time to file is not an extension of time to pay: interest and the late-payment
    penalty run from the original due date. Simple estimates; the agency computes the real figures."""
    due = original_due_date(packet)
    days = (date.fromisoformat(paid_on) - date.fromisoformat(due)).days
    if days <= 0:
        return {"interest": 0, "penalty": 0, "workings": [], "estimate": True}
    months = months_late(due, paid_on)
    rates = packet.raw["post_filing_rates"]
    if jurisdiction == "federal":
        rate, per_month, flat = rates["irs_underpayment_interest_rate_annual"], rates["irs_failure_to_pay_penalty_per_month"], 0.0
    else:
        rate = rates["ftb_interest_rate_annual"]
        flat, per_month = (float(x) / 100 for x in re.findall(r"[\d.]+(?=%)", rates["ftb_late_payment_penalty"]))
    interest = round(balance * rate * days / 365)
    penalty = round(balance * (flat + per_month * months))
    return {"interest": interest, "penalty": penalty, "estimate": True, "workings": [
        f"interest: {balance:,.0f} x {rate:.1%} x {days} days / 365 = {interest:,}",
        (f"late payment: {balance:,.0f} x ({flat:.1%} + {per_month:.1%} x {months} months) = {penalty:,}" if flat
         else f"late payment: {balance:,.0f} x {per_month:.1%} x {months} months = {penalty:,}"),
    ]}


# ---- the notice: it exists only once a return was accepted (D23) -----------------------

def this_years_notices(packet: Packet) -> list[dict]:
    return [n for n in packet.raw["tax_agency_records"]["notices"] if n["tax_year"] == packet.tax_year]


def hidden_documents(state: State) -> set[str]:
    """Notices about this return (and their documents) appear only after a federal acceptance."""
    if accepted_original(state):
        return set()
    return {n["document"] for n in this_years_notices(state.packet) if n.get("document")}
