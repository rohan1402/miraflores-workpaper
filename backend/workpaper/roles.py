"""Who is who, what each role may do, and what each role sees first (D1).

Roles are enforced on the server. The browser only learns which verbs to show.
There is no real authentication in this prototype: the role switcher picks a person,
and everything after that is enforced here.
"""

from __future__ import annotations

from .areas import SIGNED_AREAS
from .packet import Packet

# The IRS examiner for the 2028 Letter 566 is not in the packet's staff list.
EXAMINER = {"id": "irs-examiner", "name": "IRS examiner (Letter 566)", "role": "examiner",
            "sensitive_data_clearance": False}

STAFF_ROLES = {"preparer", "reviewer", "partner", "firm_administrator", "quality_reviewer"}

# Which acts each role may record. view_sensitive also needs clearance (see can_unmask).
ROLE_ACTIONS: dict[str, set[str]] = {
    "preparer": {"disposition", "accept_document", "verify", "adjust", "undo", "note", "question",
                 "attach_evidence", "judgment_call", "sign_off", "view_sensitive",
                 "correct_identity", "transmit", "notice_response", "log_time"},
    "reviewer": {"disposition", "accept_document", "verify", "adjust", "undo", "note", "question",
                 "attach_evidence", "judgment_call", "sign_off", "review_note", "resolve_review_note",
                 "view_sensitive", "correct_identity", "transmit", "notice_response", "log_time"},
    "partner": {"adjust", "undo", "note", "question", "attach_evidence", "judgment_call", "review_note",
                "resolve_review_note", "approve_adjustment", "partner_release", "view_sensitive",
                "transmit", "open_amendment", "notice_response", "release_notice_response", "log_time"},
    "firm_administrator": {"note", "set_standard", "view_sensitive", "log_time"},
    "quality_reviewer": {"note", "review_note", "view_sensitive", "log_time"},
    "client": {"answer", "attach_evidence", "sign_8879"},
    "examiner": set(),
}

# The sign-off level a role signs. The partner signs the return once (partner_release).
SIGN_LEVEL = {"preparer": "preparer", "reviewer": "reviewer"}

# D1: role is a filter rail on the same return. It changes the default slice and emphasis, not the home.
HOME = {
    "preparer": {"surface": "workpaper", "focus": "dollars and year-over-year deltas",
                 "area_order": ["wages_and_stock_compensation", "investments_and_digital_assets", "business"],
                 "default_filters": []},
    "reviewer": {"surface": "workpaper", "focus": "adjustments, variances, anything someone else changed",
                 "area_order": [], "default_filters": ["adjusted", "variance", "changed_by_others"]},
    "partner": {"surface": "workpaper", "focus": "bottom line, area signatures, filing blockers",
                "area_order": [], "default_filters": ["blockers"]},
    "firm_administrator": {"surface": "standards", "focus": "firm standards", "area_order": [],
                           "default_filters": []},
    "quality_reviewer": {"surface": "workpaper", "focus": "the return after filing", "area_order": [],
                         "default_filters": []},
    "client": {"surface": "questions", "focus": "questions from the firm", "area_order": [], "default_filters": []},
    "examiner": {"surface": "frozen", "focus": "the return as filed, read only", "area_order": [],
                 "default_filters": []},
}


def people(packet: Packet) -> dict[str, dict]:
    """Everyone the role switcher offers: firm staff, the two clients, and the examiner."""
    out = {s["id"]: {**s} for s in packet.raw["firm"]["staff"]}
    for c in packet.raw["firm"]["client_users"]:
        out[c["id"]] = {**c, "sensitive_data_clearance": False}
    out[EXAMINER["id"]] = dict(EXAMINER)
    return out


def is_staff(person: dict) -> bool:
    return person["role"] in STAFF_ROLES


def can_unmask(person: dict) -> bool:
    """Only staff with sensitive-data clearance may see an unmasked value, and each view is logged."""
    return is_staff(person) and bool(person.get("sensitive_data_clearance"))


def verbs(person: dict) -> list[str]:
    allowed = set(ROLE_ACTIONS.get(person["role"], set()))
    if not can_unmask(person):
        allowed.discard("view_sensitive")
    return sorted(allowed)


def home_config(person: dict) -> dict:
    config = HOME[person["role"]]
    order = config["area_order"] + [a for a in SIGNED_AREAS if a not in config["area_order"]]
    return {**config, "area_order": order}
