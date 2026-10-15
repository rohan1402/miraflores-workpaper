"""Who is on the return, and with which SSN.

The client organizer (household.people, typed by the client) supplies every SSN. A person
corrects one by pointing at a document that prints it: correct_identity {"person", "document"}.
The log stores which document, never the digits, so the record reads "Theo's number taken from
the 2024 return" and the digits come from the page.

The checker (R12) and the simulated agency (filing.py) read the same printed numbers.
"""

from __future__ import annotations

import re

from .packet import Packet

SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
NAME_WINDOW = 80  # characters before an SSN in which the person's name must appear


def printed_ssns(packet: Packet, documents: list[dict]) -> dict[str, list[dict]]:
    """{person id: [{doc, page, ssn}]}: every SSN printed next to a household member's name."""
    out: dict[str, list[dict]] = {}
    for d in documents:
        for page in d["pages"]:
            text = page["printed_content"]
            for m in SSN.finditer(text):
                person = _named_before(packet, text, m.start()) or _owner(packet, d)
                if person:
                    out.setdefault(person, []).append({"doc": d["id"], "page": page["page"], "ssn": m.group(0)})
    return out


def number_on(packet: Packet, person: str, doc_id: str) -> str | None:
    """The SSN a document prints for one person, if it prints exactly one."""
    found = {s["ssn"] for s in printed_ssns(packet, [packet.documents[doc_id]]).get(person, [])}
    return found.pop() if len(found) == 1 else None


def ssns_on_return(state) -> dict[str, dict]:
    """Everyone's SSN as the return now carries it: the organizer's, unless a person replaced it
    with the number a document prints. {person: {"ssn", "source": "organizer" | doc id, "event"}}"""
    out = {}
    for pid, person in state.packet.people.items():
        if not person.get("ssn"):
            continue
        fix = state.identity_corrections.get(pid)
        if fix and (number := number_on(state.packet, pid, fix["document"])):
            out[pid] = {"ssn": number, "source": fix["document"], "event": fix["event"]}
        else:
            out[pid] = {"ssn": person["ssn"], "source": "organizer", "event": None}
    return out


def _named_before(packet: Packet, text: str, at: int) -> str | None:
    """The household member whose name appears closest before position `at`."""
    window = text[max(0, at - NAME_WINDOW):at]
    best, best_pos = None, -1
    for p in packet.people.values():
        for name in {p["name"], p["name"].split()[0]}:
            pos = window.rfind(name)
            if pos > best_pos:
                best, best_pos = p["id"], pos
    return best


def _owner(packet: Packet, doc: dict) -> str | None:
    """Fallback: who a document belongs to (taxpayer, spouse, dependent:<id>)."""
    belongs = doc["belongs_to"]
    if belongs.startswith("dependent:"):
        return belongs.split(":", 1)[1]
    role = {"taxpayer": "taxpayer", "spouse": "spouse"}.get(belongs)
    return next((p["id"] for p in packet.people.values() if p["role"] == role), None) if role else None
