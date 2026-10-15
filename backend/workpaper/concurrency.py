"""The 409 rule, as a pure function of the packet and the log.

Each write carries the log tip the person was looking at (base_tip). If newer events
exist, we ask: did any of them change something this write depends on? If yes, the
write is refused and the person sees the event that landed first.

- Notes, questions, answers, evidence and views append. They never conflict and never
  count as a newer change: a view of an SSN must not block a sign-off.
- Guarded acts (sign-off, adjust, verify, accept, disposition, undo, standards) conflict
  with a newer state-changing event on an overlapping scope.
- Scope: the targets, plus every signed scope they touch. A line touches its area and,
  if it rests on California evidence, the California lens. A field touches every area that
  owns its document, and the lens only if that field feeds a California figure. California
  owns no documents: Halvorsen box 16 overlaps wages and California together, box 1 only wages.
- The partner release compares what the partner saw with what is true now: the bottom-line
  fingerprint (with the large adjustments), the unsigned scopes, and the open review notes.
  Priya verifying a Brightpath lot does not block Helen; a new review note does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .areas import (
    CALIFORNIA, RETURN, SIGNED_SCOPES, area_of_line, california_fields, document_owners, scopes_of_line,
)
from .packet import Packet, parse_page_ref, ref_kind

if TYPE_CHECKING:
    from .events import Event

# Acts that only add to the record.
APPEND_ONLY = {"note", "question", "answer", "attach_evidence", "view_sensitive",
               "review_note", "resolve_review_note", "judgment_call", "notice_response", "log_time"}

# Acts refused if made against a stale view; also the acts that make others' views stale.
GUARDED = {"sign_off", "partner_release", "approve_adjustment", "adjust", "undo",
           "accept_document", "verify", "disposition", "set_standard",
           "correct_identity", "sign_8879", "transmit", "open_amendment", "release_notice_response"}


class ConflictRule:
    """Called by the event store inside the insert transaction: rule(new, seen, newer) -> Event | None."""

    def __init__(self, packet: Packet):
        self.packet = packet
        lines = packet.lines[packet.versions[-1]["version"]]
        self.line_scopes = {key: scopes_of_line(key, line) for key, line in lines.items()}
        self.owners = document_owners(packet, lines)                   # never includes California
        self.california_fields = california_fields(packet.values, lines)

    def __call__(self, new: "Event", seen: list["Event"], newer: list["Event"]) -> "Event | None":
        if new.action not in GUARDED:
            return None
        if new.action == "partner_release":
            return self._release_conflict(seen, newer)
        if new.action == "sign_8879":
            return self._presented_conflict(seen, newer)
        if new.action == "release_notice_response":
            # The partner releases what she read: a newer draft of any item means she has not read it.
            return next((e for e in newer if e.action == "notice_response"), None)
        mine = self.scope(new)
        return next((e for e in newer if e.action in GUARDED and self.scope(e) & mine), None)

    def scope(self, event: "Event") -> set[str]:
        targets = list(event.targets)
        if event.action == "undo":
            # An undo is self-describing: the store keeps the reversed event's targets in the payload.
            targets += event.payload.get("undoes", {}).get("targets", [])
        return self.refs_scope(targets)

    def refs_scope(self, refs: list[str]) -> set[str]:
        """The references themselves plus every signed scope they touch ('area:<id>')."""
        result: set[str] = set()
        for t in refs:
            result.add(t)
            kind = ref_kind(t)
            if kind == "line":
                key = t[len("line:"):]
                result |= {f"area:{s}" for s in self.line_scopes.get(key, {area_of_line(key)})}
            elif kind in ("value", "document", "page"):
                doc, fields = self._document_and_fields(t, kind)
                if doc:
                    result.add(doc)
                    result |= {f"area:{a}" for a in self.owners.get(doc, set())}
                    if fields & self.california_fields:
                        result.add(f"area:{CALIFORNIA}")
        return result

    def _document_and_fields(self, ref: str, kind: str) -> tuple[str | None, set[str]]:
        """The document an act lands on, and the fields it covers (one value, one page, or all)."""
        if kind == "value":
            ev = self.packet.values.get(ref)
            return (ev["document_id"], {ref}) if ev else (None, set())
        doc, page = parse_page_ref(ref) if kind == "page" else (ref, None)
        return doc, {ev["id"] for ev in self.packet.values_by_doc.get(doc, []) if page is None or ev["page"] == page}

    def _presented_conflict(self, seen: list["Event"], newer: list["Event"]) -> "Event | None":
        """A client signs the return they were shown. If it changed since, refuse (D23)."""
        return _changes_presented(self.packet, seen, newer)

    def _release_conflict(self, seen: list["Event"], newer: list["Event"]) -> "Event | None":
        from .project import project  # imported here: project imports events, events receives this rule
        before = release_view(project(self.packet, seen))
        log = list(seen)
        for e in newer:
            log.append(e)
            # Append-only acts never conflict themselves, but these three change what the release covers:
            # an open review note blocks it, and a large accepted finding is listed on it (D20).
            if e.action in APPEND_ONLY and e.action not in ("review_note", "resolve_review_note", "judgment_call"):
                continue
            if release_view(project(self.packet, log)) != before:
                return e
        return None


def _changes_presented(packet: Packet, seen: list["Event"], newer: list["Event"]) -> "Event | None":
    from .filing import presented_return
    from .project import fingerprint, project
    before = fingerprint(presented_return(project(packet, seen)))
    log = list(seen)
    for e in newer:
        log.append(e)
        if e.action in APPEND_ONLY:
            continue
        if fingerprint(presented_return(project(packet, log))) != before:
            return e
    return None


def release_view(state) -> tuple:
    """What the partner release depends on. If any of this changed since the partner looked, refuse."""
    from .project import area_status, covered_values, fingerprint
    return (
        fingerprint(covered_values(state, RETURN)),
        tuple(a for a in SIGNED_SCOPES if not area_status(state, a)["complete"]),
        tuple(sorted(n.event_id for n in state.open_review_notes())),
    )
