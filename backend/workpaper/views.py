"""What each screen shows, built from (packet, state, checker result). Pure functions.

The API calls these and masks the result on the way out. The browser renders them and
computes nothing about the return itself.

Simulated documents: a page is its printed text plus value boxes (`position`). `image`
is empty today; a real page image can fill it later without changing the tracing.
"""

from __future__ import annotations

from collections import defaultdict

from .areas import CALIFORNIA, SIGNED_SCOPES, lines_in_area
from .checker import RULES, CheckResult
from .checker.r10_prior_year_variance import prior_line_key
from .concurrency import ConflictRule
from .events import Event
from .packet import Packet, page_ref, parse_page_ref, ref_kind
from .project import (
    State, area_status, effect_view, large_adjustments, release_blockers, signoff_status,
)
from .roles import home_config, verbs

MACHINE_PRIORITY = ["disagreement", "conflict", "stale", "open_item", "prompt", "variance"]

# The two-year strip (D1): (jurisdiction, name, label, 2025 line, 2024 line, sign of the 2024 line)
STRIP = [
    ("federal", "agi", "Adjusted gross income", "F1040.11", "F1040.11", 1),
    ("federal", "taxable_income", "Taxable income", "F1040.15", "F1040.15", 1),
    ("federal", "total_tax", "Total tax", "F1040.24", "F1040.24", 1),
    ("federal", "balance_due", "Balance due (refund negative)", "F1040.37", "F1040.34", -1),  # 2024 was a refund
    ("california", "ca_agi", "California AGI", "F540NR.32", "CA540.17", 1),
    ("california", "taxable_income", "California taxable income", "F540NR.35", "CA540.19", 1),
    ("california", "total_tax", "California total tax", "F540NR.64", "CA540.64", 1),
    ("california", "balance_due", "California balance due (refund negative)", "F540NR.97", "CA540.111", 1),
]


def event_view(e: Event) -> dict:
    return {"id": e.id, "at": e.at, "actor": e.actor, "role": e.role, "action": e.action,
            "targets": list(e.targets), "payload": e.payload, "reason": e.reason}


def meta(state: State) -> dict:
    return {"version": state.version_id, "computed_at": state.version["computed_at"],
            "trigger": state.version["trigger"], "tip": state.tip, "as_of": state.as_of}


# ---- home ------------------------------------------------------------------------

def home(packet: Packet, state: State, result: CheckResult, scopes: ConflictRule, person: dict) -> dict:
    """The return, 2025 vs 2024, by work area. Role changes the default slice and the verbs, not the home."""
    budget = packet.raw["firm"]["budget_hours"]
    areas = [scope_summary(state, result, scopes, a, budget.get(a)) for a in home_config(person)["area_order"]]
    areas.append(scope_summary(state, result, scopes, CALIFORNIA, budget.get(CALIFORNIA)))
    open_findings = [f for f in result.findings if f.status == "open"]
    return {
        "meta": meta(state),
        "person": {k: person[k] for k in ("id", "name", "role")},
        "verbs": verbs(person),
        "config": home_config(person),
        "strip": strip(packet, state, result),
        "areas": areas,
        "partner_release": signoff_status(state, state.partner_release),
        "release_blockers": release_blockers(state),
        "findings": {sev: sum(1 for f in open_findings if f.severity == sev) for sev in ("error", "warning", "info")},
        "open_corrections": result.net_effect,
    }


def strip(packet: Packet, state: State, result: CheckResult) -> list[dict]:
    """AGI, taxable income, total tax, balance due, federal and California, with last year and the
    variance flag. Balance due also shows the estimated effect of human adjustments and of the
    checker's open corrections; the engine cannot be rerun, so both are labelled estimates."""
    prior = packet.raw["prior_years"]["return_2024"]["lines"]
    standard = state.standards["variance_review"]
    adjusted = {"federal": 0, "california": 0}
    for adj in state.applied_adjustments():
        if adj.effect:
            adjusted["federal"] += adj.effect["federal"]
            adjusted["california"] += adj.effect["california"]
    rows = []
    for jurisdiction, name, label, line, prior_line, sign in STRIP:
        now = state.version["summary"][jurisdiction].get(name, state.line_value(line))
        before = prior.get(prior_line)
        before = sign * before if isinstance(before, (int, float)) else None
        row = {"jurisdiction": jurisdiction, "name": name, "label": label, "line": line,
               "value": now, "prior": before, "variance": _variance(now, before, standard)}
        if name == "balance_due":
            row["estimated"] = {
                "after_adjustments": now + adjusted[jurisdiction],
                "after_open_corrections": now + adjusted[jurisdiction] + result.net_effect[jurisdiction],
                "estimate": True,
            }
        rows.append(row)
    return rows


def _variance(now, before, standard) -> bool:
    if not isinstance(now, (int, float)) or not isinstance(before, (int, float)):
        return False
    change = abs(now - before)
    pct = change / abs(before) * 100 if before else float("inf")
    return change > standard["and_over_amount"] and pct > standard["flag_if_change_over_percent"]


def scope_summary(state: State, result: CheckResult, scopes: ConflictRule, area: str, budget) -> dict:
    status = area_status(state, area)
    open_here = [f for f in result.findings if f.status == "open" and f"area:{area}" in scopes.refs_scope(f.targets)]
    return {
        "id": area, "label": SIGNED_SCOPES[area], "lens": area == CALIFORNIA,
        "lines": len(lines_in_area(state.lines, area)), "budget_hours": budget,
        "open_findings": {sev: sum(1 for f in open_here if f.severity == sev) for sev in ("error", "warning", "info")},
        "preparer": status["preparer"], "reviewer": status["reviewer"],
        "complete": status["complete"], "problems": status["problems"],
    }


# ---- one area -------------------------------------------------------------------

def area_view(packet: Packet, state: State, result: CheckResult, scopes: ConflictRule, area: str) -> dict:
    """The lines of one work area (or the California lens). Brokerage lots collapse into one row
    per account, tied to the account's printed summary; the lots open underneath."""
    by_line = _findings_by_line(result)
    rows, lots_by_doc = [], defaultdict(list)
    for key in lines_in_area(state.lines, area):
        row = line_row(packet, state, result, key, by_line)
        broker = _broker_of(packet, state.lines[key])
        if broker:
            lots_by_doc[broker].append(row)
        else:
            rows.append(row)   # box totals and computed lots stay in the line list
    budget = packet.raw["firm"]["budget_hours"].get(area)
    return {
        "meta": meta(state),
        "area": scope_summary(state, result, scopes, area, budget),
        "lines": rows,
        "accounts": [_account(packet, result, doc, lots) for doc, lots in sorted(lots_by_doc.items())],
    }


def _broker_of(packet: Packet, line: dict) -> str | None:
    """The document that printed a lot's proceeds: the brokerage account the lot belongs to."""
    if not line["key"].startswith("F8949."):
        return None
    return next((packet.values[s]["document_id"] for s in line["sources"]
                 if s in packet.values and packet.values[s]["field"].endswith("_proceeds")), None)


def _account(packet: Packet, result: CheckResult, doc_id: str, lots: list[dict]) -> dict:
    tie = next((r for r in result.reconciliations if r.get("document") == doc_id), None)
    gaps = [f.id for f in result.findings if f.status == "open" and f.code in ("PAGE_NOT_READ", "BROKER_SUMMARY_GAP")
            and any(t == doc_id or t.startswith(f"doc:{doc_id}#") for t in f.targets)]
    doc = packet.documents.get(doc_id, {})
    return {
        "document": doc_id, "title": doc.get("title"), "lots": len(lots),
        "gain": round(sum(r["value"] for r in lots if isinstance(r["value"], (int, float))), 2),
        "summary": "ties" if tie else ("gap" if gaps else "no printed summary"),
        "reconciliation": tie, "gap_findings": gaps,
        "open_findings": sorted({fid for r in lots for fid in r["findings"]}),
        "lot_rows": lots,
    }


def _findings_by_line(result: CheckResult) -> dict[str, list]:
    out = defaultdict(list)
    for f in result.findings:
        if f.status != "open":
            continue
        for t in f.targets:
            if t.startswith("line:"):
                out[t[len("line:"):]].append(f)
    return out


def line_row(packet: Packet, state: State, result: CheckResult, key: str, by_line: dict | None = None) -> dict:
    line = state.lines[key]
    by_line = by_line if by_line is not None else _findings_by_line(result)
    findings = by_line.get(key, [])
    prior = packet.raw["prior_years"]["return_2024"]
    prior_key = prior_line_key(key, line["label"], prior)
    adjustments = [a for a in state.adjustments.get(key, []) if a.applied]
    return {
        "key": key, "label": line["label"], "form": line["form"], "line": line["line"],
        "jurisdiction": line["jurisdiction"],
        "value": state.line_value(key), "engine_value": line["value"],
        "prior": prior["lines"].get(prior_key) if prior_key else None, "prior_line": prior_key,
        "variance": any(f.code == "PRIOR_YEAR_VARIANCE" for f in findings),
        "machine_state": _machine_state(result, line, findings),
        "human_state": _human_state(state, key, adjustments),
        "findings": [f.id for f in findings],
        "sources": len(line["sources"]),
    }


def _machine_state(result: CheckResult, line: dict, findings: list) -> str | None:
    kinds = {f.kind for f in findings}
    for kind in MACHINE_PRIORITY:
        if kind in kinds:
            return kind
    states = {result.value_states.get(s) for s in line["sources"] if s.startswith("ev-")}
    if not states:
        return None
    return "ties" if states == {"ties"} else sorted(states - {"ties"})[0]


def _human_state(state: State, key: str, adjustments: list) -> dict | None:
    """Only a person verifies (D2). Adjusted beats verified; a verification of an older figure is stale."""
    if adjustments:
        a = adjustments[-1]
        return {"state": "adjusted", "by": a.actor, "at": a.at, "event": a.event_id}
    verifications = state.verifications.get(f"line:{key}", [])
    if verifications:
        v = verifications[-1]
        current = state.line_value(key)
        return {"state": "verified" if v.value == current else "stale", "type": v.verification_type,
                "by": v.actor, "at": v.at, "event": v.event_id}
    return None


# ---- trace a number (both directions) ---------------------------------------------

def line_trace(packet: Packet, state: State, result: CheckResult, key: str) -> dict:
    """Where a number came from (inputs and sources down to the page field) and where it goes (used by)."""
    line = state.lines[key]
    by_line = _findings_by_line(result)
    engine_rules = packet.raw["engine_reference"]["rules"]
    return {
        "meta": meta(state),
        "line": line_row(packet, state, result, key, by_line),
        "rule": {"id": line["rule"], "description": engine_rules.get(line["rule"])},
        "note": line.get("note"),
        "inputs": [line_row(packet, state, result, k, by_line) for k in line["inputs"] if k in state.lines],
        "used_by": sorted(k for k, other in state.lines.items() if key in other["inputs"]),
        "sources": [resolve_source(packet, state, result, s) for s in line["sources"]],
        "versions": {v["version"]: packet.lines[v["version"]].get(key, {}).get("value") for v in packet.versions},
        "adjustments": [{"event": a.event_id, "by": a.actor, "at": a.at, "from": a.original, "to": a.value,
                         "reason": a.reason, "applied": a.applied, "effect": effect_view(state, a),
                         "needs_partner": a in large_adjustments(state),
                         "partner_approved": a.event_id in state.partner_approvals}
                        for a in state.adjustments.get(key, [])],
        "verifications": [_verification(v) for v in state.verifications.get(f"line:{key}", [])],
        "findings": [f.as_dict() for f in result.findings if f"line:{key}" in f.targets],
    }


def resolve_source(packet: Packet, state: State, result: CheckResult, ref: str) -> dict:
    """A source as the trace shows it. Client answers are a distinct kind of evidence (D2)."""
    kind = ref_kind(ref)
    if kind == "value":
        ev = packet.values[ref]
        doc = packet.documents[ev["document_id"]]
        return {"kind": "document_value", "ref": ref, "document": ev["document_id"], "title": doc["title"],
                "page": ev["page"], "page_ref": page_ref(ev["document_id"], ev["page"]), "field": ev["field"],
                "label": ev["label"], "value": ev["value"], "value_type": ev["value_type"],
                "text_as_read": ev["text_as_read"], "position": ev["position"], "confidence": ev["confidence"],
                "machine_state": result.value_states.get(ref),
                "verified": [_verification(v) for v in state.verifications.get(ref, [])]}
    if kind == "client":
        item = packet.client_items[ref]
        text = item.get("answer") or item.get("text") or " ".join(item.get("notes", []))
        return {"kind": f"client_{item['kind']}", "ref": ref, "at": item["at"], "text": text,
                "question": item.get("question"), "from": item.get("from") or item.get("answered_by")}
    labels = {"param": "engine_parameter", "fx": "engine_parameter", "prior_year": "prior_year",
              "agency": "agency_record", "asset": "asset", "timeline": "timeline", "person": "household",
              "page": "page"}
    return {"kind": labels.get(kind, kind), "ref": ref, "value": _resolve_quietly(packet, state, ref)}


def _resolve_quietly(packet: Packet, state: State, ref: str):
    if ref.startswith("asset:"):
        asset_id = ref[len("asset:"):]
        found = next((a for a in state.version["assets"] if a["asset_id"] == asset_id), None)
        return found or next((a for a in packet.raw["prior_years"]["asset_records"] if a["asset_id"] == asset_id), None)
    if ref.startswith("timeline:"):
        return next((t for t in packet.raw["timeline"] if t["id"] == ref[len("timeline:"):]), None)
    try:
        return packet.resolve(ref)
    except (KeyError, IndexError, ValueError):
        return None


def _verification(v) -> dict:
    return {"event": v.event_id, "by": v.actor, "at": v.at, "type": v.verification_type, "value": v.value, "via": v.via}


# ---- documents ------------------------------------------------------------------

def document_index(packet: Packet, state: State, result: CheckResult, scopes: ConflictRule) -> list[dict]:
    """Every document, where it landed, its disposition, and what is open on it."""
    landed = _lines_by_document(state)
    out = []
    for d in packet.raw["documents"]:
        if state.as_of and d["received_at"] > state.as_of:
            continue
        disp = state.dispositions.get(d["id"])
        out.append({
            "id": d["id"], "title": d["title"], "type": d["document_type"], "issuer": d["issuer"],
            "received_at": d["received_at"], "pages": d["page_count"], "extraction": d["extraction"]["status"],
            "corrected": d.get("marked_corrected"),
            "disposition": {"value": disp.disposition, "by": disp.actor, "event": disp.event_id} if disp else None,
            "lines": len(landed.get(d["id"], ())),
            "owners": sorted(scopes.owners.get(d["id"], set())),
            "open_findings": sum(1 for f in result.findings if f.status == "open" and _touches_document(packet, f, d["id"])),
        })
    return out


def document_view(packet: Packet, state: State, result: CheckResult, scopes: ConflictRule, doc_id: str) -> dict:
    """A simulated document: each page's printed text with value boxes, where each value landed, or why not."""
    d = packet.documents[doc_id]
    landed = _lines_by_document(state).get(doc_id, set())
    values_by_page = defaultdict(list)
    for ev in packet.values_by_doc.get(doc_id, []):
        values_by_page[ev["page"]].append(ev)
    used_by = defaultdict(list)
    for key, line in state.lines.items():
        for s in line["sources"]:
            if s in packet.values and packet.values[s]["document_id"] == doc_id:
                used_by[s].append(key)
    unread = {int(p) for f in result.findings if f.code == "PAGE_NOT_READ"
              for t in f.targets if t.startswith(f"doc:{doc_id}#page") for p in [parse_page_ref(t)[1]]}
    pages = []
    for page in d["pages"]:
        pages.append({
            "page": page["page"], "ref": page_ref(doc_id, page["page"]), "image": None,
            "text": page["printed_content"], "read": page["page"] not in unread,
            "values": [{"id": ev["id"], "field": ev["field"], "label": ev["label"], "value": ev["value"],
                        "value_type": ev["value_type"], "text_as_read": ev["text_as_read"],
                        "position": ev["position"], "confidence": ev["confidence"],
                        "machine_state": result.value_states.get(ev["id"]), "lines": used_by.get(ev["id"], []),
                        "verified": [_verification(v) for v in state.verifications.get(ev["id"], [])]}
                       for ev in values_by_page.get(page["page"], [])],
        })
    disp = state.dispositions.get(doc_id)
    findings = [f for f in result.findings if _touches_document(packet, f, doc_id)]
    return {
        "meta": meta(state),
        "document": {k: v for k, v in d.items() if k != "pages"},
        "owners": sorted(scopes.owners.get(doc_id, set())),
        "disposition": {"value": disp.disposition, "detail": disp.detail, "by": disp.actor,
                        "event": disp.event_id, "reason": disp.reason} if disp else None,
        "landed_on": sorted(landed),
        "not_used_because": None if landed else _why_not_used(d, state, findings),
        "pages": pages,
        "findings": [f.as_dict() for f in findings],
    }


def _lines_by_document(state: State) -> dict[str, set[str]]:
    out = defaultdict(set)
    for key, line in state.lines.items():
        for s in line["sources"]:
            if s in state.packet.values:
                out[state.packet.values[s]["document_id"]].add(key)
    return out


def _touches_document(packet: Packet, f, doc_id: str) -> bool:
    """Does a finding point at this document, one of its pages, or one of its values?"""
    for t in f.targets + f.evidence:
        if t == doc_id or t.startswith(f"doc:{doc_id}#"):
            return True
        if t in packet.values and packet.values[t]["document_id"] == doc_id:
            return True
    return False


def _why_not_used(d: dict, state: State, findings: list) -> str:
    """A document that landed nowhere says why: disposition, extraction, supersession or duplication."""
    disp = state.dispositions.get(d["id"])
    if disp:
        return f"dispositioned {disp.disposition}" + (f": {disp.reason}" if disp.reason else "")
    for f in findings:
        if f.code == "DUPLICATE_DOCUMENT" and d["id"] in f.targets:
            return f"duplicate of {f.details['duplicate_of']} (not yet dispositioned)"
        if f.code == "SUPERSEDED_DOCUMENT" and f.details.get("superseded") == d["id"]:
            return f"superseded by {f.details['by']} (not yet dispositioned)"
    if d["extraction"]["status"] == "not_extracted":
        return f"not extracted: {d['extraction']['reason']}"
    return "no return line cites it yet"


# ---- findings ---------------------------------------------------------------------

def findings_view(result: CheckResult, scopes: ConflictRule, area: str | None = None, status: str | None = None) -> dict:
    found = [f for f in result.findings
             if (status is None or f.status == status)
             and (area is None or f"area:{area}" in scopes.refs_scope(f.targets))]
    return {
        "rules": {rule: title for rule, (title, _) in RULES.items()},
        "findings": [f.as_dict() for f in found],
        "corrected_lines": result.corrected_lines,
        "net_effect": result.net_effect,
        "reconciliations": result.reconciliations,
    }
