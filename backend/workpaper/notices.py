"""Answering a notice with a self-contained record (D24).

A notice about this return exists only after a federal acceptance (D23). For each item under
examination the firm writes an answer and picks the evidence it rests on (lines, documents,
client answers, attached files). The partner releases it. The release stores the whole package,
resolved against the return as filed: the examiner reads exactly what was released, even if the
workpaper changes afterwards (an amendment). Internal review notes, notes and checker findings
never go in.

Evidence is suggested from the item's own words ("Schedule A line 12", "Form 8283", "Schedule C
gross receipts", "Forms 1099-NEC"), never from packet ids.
"""

from __future__ import annotations

import re

from .filing import accepted_original, this_years_notices
from .packet import Packet, parse_page_ref, ref_kind
from .project import State, fingerprint, project


def visible_notices(state: State) -> list[dict]:
    """Notices about this return that have arrived: after an acceptance, on their date."""
    if not accepted_original(state):
        return []
    return [n for n in this_years_notices(state.packet)
            if not n.get("document") or state.document_visible(state.packet.documents[n["document"]])]


def notice_by_ref(state: State, ref: str) -> dict | None:
    return next((n for n in visible_notices(state) if f"notice:{n['id']}" == ref), None)


def items(notice: dict) -> list[str]:
    return notice.get("items_under_examination") or [notice.get("summary", "")]


# ---- what the firm drafted ------------------------------------------------------

def drafts(state: State, notice_id: str) -> dict[int, dict]:
    """The latest draft answer per item: {item index: {text, evidence, by, at, event}}."""
    out = {}
    for r in state.records:
        if r.action == "notice_response" and f"notice:{notice_id}" in r.targets:
            out[r.payload["item"]] = {"text": r.payload["text"], "evidence": [t for t in r.targets if t != f"notice:{notice_id}"],
                                      "by": r.actor, "at": r.at, "event": r.event_id}
    return out


def releases(state: State, notice_id: str) -> list:
    return [r for r in state.records if r.action == "release_notice_response" and r.payload.get("notice") == notice_id]


# ---- suggested evidence -----------------------------------------------------------

SCHEDULE_LINE = re.compile(r"Schedule ([A-Z0-9]+) line (\d+[a-z]?)")
FORM = re.compile(r"Form (\d{4}[A-Z]?)\b")
SCHEDULE_WORDS = re.compile(r"Schedule ([A-Z]) ([a-z][a-z ]+?)(?=[:,.;(]|$)")
INFORMATION_RETURN = re.compile(r"\b(1099-[A-Z]+|1098-[A-Z]|W-2)\b")


def suggest(packet: Packet, state: State, text: str) -> list[str]:
    """Lines and documents an item's words point at, plus the documents and client answers
    those lines rest on. A person still chooses what to send."""
    lines: list[str] = []
    for schedule, number in SCHEDULE_LINE.findall(text):
        key = f"Sch{schedule}.{number}"
        if key in state.lines:
            lines += [key] + [k for k in state.lines[key]["inputs"] if k in state.lines]
    for form in FORM.findall(text):
        lines += [k for k in state.lines if k.startswith(f"F{form}.")]
    for schedule, words in SCHEDULE_WORDS.findall(text):
        lines += [k for k, line in state.lines.items()
                  if k.startswith(f"Sch{schedule}.") and line["label"].lower() == words.strip().lower()]
    docs: list[str] = []
    for kind in INFORMATION_RETURN.findall(text):
        docs += [d["id"] for d in packet.raw["documents"] if d["document_type"] == kind and state.document_visible(d)]
    client: list[str] = []
    for key in lines:
        for s in state.lines[key]["sources"]:
            if s in packet.values:
                docs.append(packet.values[s]["document_id"])
            elif ref_kind(s) == "client":
                client.append(s)
    return _unique([f"line:{k}" for k in lines] + docs + client)


def _unique(refs: list[str]) -> list[str]:
    seen, out = set(), []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ---- the released package ----------------------------------------------------------

def package(packet: Packet, state: State, notice: dict) -> dict:
    """Everything the examiner will read, resolved against the return as filed."""
    filed = accepted_original(state)
    as_filed = project(packet, [e for e in state.events if e.id <= filed.event_id])
    names = {**{s["id"]: s["name"] for s in packet.raw["firm"]["staff"]},
             **{c["id"]: c["name"] for c in packet.raw["firm"]["client_users"]}}
    answers = drafts(state, notice["id"])
    attachments = {r.event_id: r for r in state.records if r.action == "attach_evidence"}
    out = []
    for i, text in enumerate(items(notice)):
        draft = answers.get(i, {})
        out.append({"item": i, "examined": text, "answer": draft.get("text"),
                    "evidence": [_resolve(packet, as_filed, ref, names, attachments) for ref in draft.get("evidence", [])]})
    body = {"notice": notice["id"], "type": notice["type"], "dated": notice["dated"],
            "response_due": notice.get("response_due"), "filed_event": filed.event_id,
            "filed_submission": filed.answer["federal"].get("submission_id"),
            "firm": {k: packet.raw["firm"]["firm_identity"][k] for k in ("address", "phone")} | {"name": packet.raw["firm"]["name"]},
            "items": out}
    return {**body, "fingerprint": fingerprint(body)}


def _resolve(packet: Packet, as_filed: State, ref: str, names: dict, attachments: dict) -> dict:
    kind = ref_kind(ref)
    if kind == "line":
        key = ref[len("line:"):]
        line = as_filed.lines.get(key)
        if line is None:
            return {"ref": ref, "kind": "missing"}
        verified = [{"type": v.verification_type, "by": names.get(v.actor, v.actor), "at": v.at}
                    for s in [ref, *line["sources"]] for v in as_filed.verifications.get(s, [])]
        return {
            "ref": ref, "kind": "line", "key": key, "label": line["label"], "as_filed": as_filed.line_value(key),
            "engine_value": line["value"],
            "adjustments": [{"from": a.original, "to": a.value, "reason": a.reason, "at": a.at}
                            for a in as_filed.adjustments.get(key, []) if a.applied],
            "inputs": [{"key": k, "label": as_filed.lines[k]["label"], "value": as_filed.line_value(k)}
                       for k in line["inputs"] if k in as_filed.lines],
            "sources": [_source(packet, s) for s in line["sources"]],
            "verified": verified,
        }
    if kind == "document":
        d = packet.documents[ref]
        return {"ref": ref, "kind": "document", "title": d["title"], "issuer": d["issuer"], "received_at": d["received_at"],
                "pages": [{"page": p["page"], "text": p["printed_content"]} for p in d["pages"]]}
    if kind == "client":
        return {"ref": ref, "kind": "client", **client_words(packet.client_items.get(ref, {}))}
    if kind == "event" and int(ref[len("event:"):]) in attachments:
        r = attachments[int(ref[len("event:"):])]
        return {"ref": ref, "kind": "attachment", "file_name": r.payload.get("file_name"), "sha256": r.payload.get("sha256"),
                "size": r.payload.get("size"), "note": r.payload.get("text")}
    return {"ref": ref, "kind": "missing"}


def client_words(item: dict) -> dict:
    """What the client said, the same way for a questionnaire answer, a message and a call note."""
    if item.get("kind") == "questionnaire":
        return {"text": f"{item['question']}: {item['answer']}", "from": item.get("answered_by"), "at": item["at"]}
    if item.get("kind") == "message":
        return {"text": item["text"], "from": item.get("from"), "at": item["at"]}
    if item.get("kind") == "call_note":
        notes = item["notes"]
        return {"text": " ".join(map(str, notes)) if isinstance(notes, list) else str(notes),
                "from": ", ".join(map(str, item.get("participants", []))), "at": item["at"]}
    return {"text": None, "from": None, "at": None}


def _source(packet: Packet, s: str) -> dict:
    if s in packet.values:
        ev = packet.values[s]
        return {"ref": s, "kind": "value", "document": ev["document_id"], "page": ev["page"], "field": ev["field"],
                "value": ev["value"], "title": packet.documents[ev["document_id"]]["title"]}
    if ref_kind(s) == "client":
        return {"ref": s, "kind": "client", **client_words(packet.client_items.get(s, {}))}
    if ref_kind(s) == "page":
        doc, page = parse_page_ref(s)
        return {"ref": s, "kind": "page", "document": doc, "page": page}
    return {"ref": s, "kind": ref_kind(s)}
