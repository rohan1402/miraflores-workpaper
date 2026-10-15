"""The firm's screens: time against budget, firm standards, search. Pure functions."""

from __future__ import annotations

from collections import defaultdict

from .checker import CheckResult
from .notices import client_words
from .packet import Packet
from .project import State

# ---- time against budget ---------------------------------------------------------


def time_view(packet: Packet, state: State) -> dict:
    """Hours logged per budget bucket (the work areas, plus intake and partner review), by person."""
    budget = packet.raw["firm"]["budget_hours"]
    logged: dict[str, float] = defaultdict(float)
    by_person: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    entries = []
    for r in state.records:
        if r.action != "log_time":
            continue
        bucket = r.targets[0][len("time:"):]
        logged[bucket] += r.payload["hours"]
        by_person[bucket][r.actor] += r.payload["hours"]
        entries.append({"event": r.event_id, "bucket": bucket, "hours": r.payload["hours"], "by": r.actor,
                        "at": r.at, "on": r.payload.get("on"), "text": r.payload.get("text")})
    buckets = [{"bucket": b, "budget": hours, "logged": round(logged[b], 2),
                "left": round(hours - logged[b], 2), "over": logged[b] > hours,
                "by_person": {p: round(h, 2) for p, h in by_person[b].items()}}
               for b, hours in budget.items()]
    total_budget = sum(budget.values())
    total_logged = round(sum(logged.values()), 2)
    return {"buckets": buckets, "total": {"budget": total_budget, "logged": total_logged,
                                          "left": round(total_budget - total_logged, 2)},
            "entries": list(reversed(entries))}


# ---- firm standards --------------------------------------------------------------------

def standards_view(packet: Packet, state: State) -> dict:
    """The standards in force (the starter set as changed by the administrator), and each change."""
    changes = [{"event": r.event_id, "path": r.payload["path"], "value": r.payload["value"], "by": r.actor,
                "at": r.at, "reason": r.reason} for r in state.records if r.action == "set_standard"]
    return {"standards": {k: v for k, v in state.standards.items() if k != "note"},
            "starter": {k: v for k, v in packet.raw["firm"]["starter_standards"].items() if k != "note"},
            "changes": list(reversed(changes))}


# ---- search ----------------------------------------------------------------------------

LIMIT = 25


def search(packet: Packet, state: State, result: CheckResult, query: str, mask) -> dict:
    """Search lines, documents, read values, findings, client words and people's notes.

    Matching runs on masked text, for everyone: a search cannot be used to test whether a hidden
    number is in the file. Someone cleared to see it still opens it through the logged door."""
    q = query.strip().lower()
    if len(q) < 2:
        return {"query": query, "groups": {}}

    def hit(*texts) -> bool:
        return any(q in str(mask(t)).lower() for t in texts if t is not None)

    groups: dict[str, list[dict]] = defaultdict(list)
    for key, line in state.lines.items():
        if hit(key, line["label"]):
            groups["lines"].append({"ref": f"line:{key}", "key": key, "label": line["label"],
                                    "value": state.line_value(key)})
    for d in packet.raw["documents"]:
        if state.document_visible(d) and hit(d["id"], d["title"], d["issuer"], d["document_type"]):
            groups["documents"].append({"ref": d["id"], "title": d["title"], "type": d["document_type"]})
    for ev in packet.values.values():
        if state.document_visible(packet.documents[ev["document_id"]]) and hit(ev["field"], ev["value"]):
            groups["values"].append({"ref": ev["id"], "document": ev["document_id"], "page": ev["page"],
                                     "field": ev["field"], "value": ev["value"]})
    for f in result.findings:
        if hit(f.id, f.title, f.message):
            groups["findings"].append({"ref": f"finding:{f.id}", "id": f.id, "title": f.title, "status": f.status})
    for ref, item in packet.client_items.items():
        words = client_words(item)
        if (state.as_of is None or item["at"] <= state.as_of) and hit(ref, words["text"]):
            groups["client"].append({"ref": ref, **words})
    for r in state.records:
        text = r.payload.get("text") if isinstance(r.payload, dict) else None
        if r.action in ("note", "review_note", "question", "answer", "attach_evidence", "judgment_call",
                        "notice_response") and hit(text, r.reason, r.payload.get("decision"), r.payload.get("file_name")):
            groups["acts"].append({"ref": f"event:{r.event_id}", "action": r.action, "by": r.actor, "at": r.at,
                                   "text": text or r.payload.get("decision") or r.payload.get("file_name") or r.reason})
    for note in state.review_notes.values():
        if hit(note.text):
            groups["acts"].append({"ref": f"event:{note.event_id}", "action": "review_note", "by": note.actor,
                                   "at": note.at, "text": note.text})
    return {"query": query,
            "groups": {g: items[:LIMIT] for g, items in groups.items()},
            "counts": {g: len(items) for g, items in groups.items()}}
