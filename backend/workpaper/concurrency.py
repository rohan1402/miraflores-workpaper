"""The 409 rule, as a pure function.

Each write carries the log tip the person was looking at (base_tip). If newer
events exist, we ask: did any of them change something this write depends on?
If yes, the write is refused and the person sees the event that landed first.

- Notes, questions, answers and views always append. They never conflict.
- Sign-offs, adjustments and the other guarded acts conflict with a newer
  state-changing event on an overlapping scope.
- Scope: the targets themselves, plus the work area of any line target.
  So a sign-off on 'business' conflicts with a newer adjustment to SchC.9.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from .areas import area_of_line

if TYPE_CHECKING:
    from .events import Event

# Acts that are refused if made against a stale view.
GUARDED = {
    "sign_off", "partner_release", "approve_adjustment", "adjust", "undo",
    "accept_document", "verify", "disposition", "set_standard",
}

# Acts that change what others are signing or verifying.
STATE_CHANGING = GUARDED


def scope(event: "Event") -> set[str]:
    targets = list(event.targets)
    if event.action == "undo":
        # An undo is self-describing: the store keeps the reversed event's targets in the payload.
        targets += event.payload.get("undoes", {}).get("targets", [])
    result: set[str] = set()
    for t in targets:
        result.add(t)
        if t.startswith("line:"):
            result.add("area:" + area_of_line(t[len("line:"):]))
    return result


def find_conflict(new: "Event", newer: Iterable["Event"]) -> "Event | None":
    """Return the first newer event that makes `new` stale, or None if it can go in."""
    if new.action not in GUARDED:
        return None
    mine = scope(new)
    if new.action == "partner_release":
        return next((e for e in newer if e.action in STATE_CHANGING), None)
    for e in newer:
        if e.action in STATE_CHANGING and scope(e) & mine:
            return e
    return None
