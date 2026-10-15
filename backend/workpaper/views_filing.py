"""What the filing, client and notice screens read (D23 to D25). Pure functions; masking happens on
the way out like every other response."""

from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape

from . import notices
from .filing import JURISDICTIONS, Transmission, filing_status, settlement
from .packet import Packet
from .project import State


def _transmission(packet: Packet, t: Transmission, before: Transmission | None) -> dict:
    return {
        "event": t.event_id, "at": t.at, "by": t.actor, "kind": t.kind, "answer": t.answer, "filed": t.filed,
        "estimated_balance_due": t.presented["estimated_balance_due"],
        "settlement": settlement(packet, t, before if t.kind == "amended" else None) if t.filed else {},
    }


def transmissions_view(packet: Packet, status: dict) -> list[dict]:
    out, last_filed = [], None
    for t in status["transmissions"]:
        out.append(_transmission(packet, t, last_filed))
        if t.filed:
            last_filed = t
    return out


def filing_view(packet: Packet, state: State) -> dict:
    """Where the return stands on its way out of the firm, and after."""
    status = filing_status(state)
    sent = transmissions_view(packet, status)
    filed = status["filed"]
    comparison = None
    if status["amendment_open"] and filed:
        # Amend on top: the return as filed beside the return as it stands now (1040-X style).
        now = status["presented"]["estimated_balance_due"]
        then = filed.presented["estimated_balance_due"]
        changed = {k: v for k, v in status["presented"]["changed_lines"].items()
                   if filed.presented["changed_lines"].get(k) != v}
        comparison = {"balance_as_filed": then, "balance_now": now,
                      "net_change": {j: now[j] - then[j] for j in JURISDICTIONS},
                      "lines_changed_since_filing": changed, "estimate": True}
    return {
        "stage": stage(status),
        "frozen": status["frozen"],
        "amendment_open": status["amendment_open"],
        "amendment": ({"event": status["amendment"].event_id, "by": status["amendment"].actor,
                       "at": status["amendment"].at, "reason": status["amendment"].reason}
                      if status["amendment"] else None),
        "next_kind": status["next_kind"],
        "release": status["release"],
        "form_8879": status["form_8879"],
        "transmit_blockers": status["transmit_blockers"],
        "presented": status["presented"],
        "transmissions": sent,
        "filed_event": filed.event_id if filed else None,
        "comparison": comparison,
        "extension": extension(packet),
        "deadlines": deadlines(packet, state),
    }


def stage(status: dict) -> str:
    if status["amendment_open"]:
        return "amendment open"
    if status["frozen"]:
        return "amended return filed" if status["filed"].kind == "amended" else "filed and accepted"
    if any(t.answer["federal"]["status"] == "rejected" for t in status["transmissions"]):
        return "rejected; fix and transmit again"
    if status["form_8879"]["current"]:
        return "signed by the clients; ready to transmit"
    if status["release"]["current"]:
        return "released by the partner; waiting for the 8879"
    return "in preparation and review"


def extension(packet: Packet) -> dict:
    """The April extension, as the packet scripts it: Form 4868 estimated from v2, and its payment."""
    event = next((t for t in packet.raw["timeline"] if t["event"] == "extension_filed_with_payment"), None)
    estimate = packet.raw["what_if"]["extension"]
    return {"filed_at": event["at"] if event else None, "by": event["actor"] if event else None,
            "detail": event["detail"] if event else None, "estimate": estimate,
            "note": packet.raw["post_filing_rates"]["note"]}


def deadlines(packet: Packet, state: State) -> list[dict]:
    """The firm's deadlines for this engagement, counted from the projection's clock (or today)."""
    today = (state.as_of or datetime.now(timezone.utc).isoformat())[:10]
    out = []
    for d in packet.raw["firm"]["deadlines"]:
        days = (date.fromisoformat(d["date"]) - date.fromisoformat(today)).days
        out.append({**d, "days_left": days, "passed": days < 0})
    return sorted(out, key=lambda d: d["date"])


# ---- the clients' surface: approve and sign, then their copy ---------------------------

def client_return_view(packet: Packet, state: State, person: dict) -> dict:
    status = filing_status(state)
    presented = status["presented"]
    sent = transmissions_view(packet, status)
    return {
        "can_sign": status["release"]["current"] and not status["frozen"]
                    and not status["form_8879"]["signers"].get(person["id"], {}).get("current", False),
        "waiting_for": None if status["release"]["current"] else "The firm has not finished the return yet.",
        "summary": {j: {"agi": presented["engine_summary"][j].get("agi", presented["engine_summary"][j].get("ca_agi")),
                        "total_tax": presented["engine_summary"][j]["total_tax"],
                        "payments": presented["engine_summary"][j]["payments"],
                        "estimated_balance_due": presented["estimated_balance_due"][j]} for j in JURISDICTIONS},
        "people": [{"name": packet.people[pid]["name"], "ssn": ssn} for pid, ssn in presented["identity"].items()],
        "form_8879": status["form_8879"],
        "frozen": status["frozen"],
        "copy": next((s for s in reversed(sent) if s["filed"]), None),   # the client's copy of what was filed
        "rejections": [s for s in sent if s["answer"]["federal"]["status"] == "rejected"],
    }


# ---- the notice: drafts for the firm, the released package for the examiner -------------

def notices_view(packet: Packet, state: State) -> list[dict]:
    out = []
    for n in notices.visible_notices(state):
        drafts = notices.drafts(state, n["id"])
        released = notices.releases(state, n["id"])
        out.append({
            "id": n["id"], "ref": f"notice:{n['id']}", "type": n["type"], "agency": n["agency"], "dated": n["dated"],
            "response_due": n.get("response_due"), "document": n.get("document"),
            "items": [{"item": i, "text": text, "suggested": notices.suggest(packet, state, text), "draft": drafts.get(i)}
                      for i, text in enumerate(notices.items(n))],
            "released": [{"event": r.event_id, "by": r.actor, "at": r.at, "fingerprint": r.payload.get("fingerprint")}
                         for r in released],
            "changed_since_release": bool(released) and any(d["event"] > released[-1].event_id for d in drafts.values()),
        })
    return out


def examiner_view(state: State) -> list[dict]:
    """Only what the partner released, as it was released (D24)."""
    out = []
    for n in notices.visible_notices(state):
        released = notices.releases(state, n["id"])
        if released:
            out.append({**released[-1].payload, "released_at": released[-1].at, "released_event": released[-1].event_id})
    return out


# ---- the released response as one file ---------------------------------------------------

def export_html(released: list[dict], firm_name: str) -> str:
    """A self-contained record for the examiner: no scripts, no links out, everything inline.
    `released` is already masked by the caller."""
    parts = ["<!doctype html><meta charset='utf-8'><title>Response to examination</title>"
             "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 16px;color:#111}"
             "h1,h2,h3{line-height:1.25}pre{white-space:pre-wrap;background:#f5f5f2;padding:.6rem;border-radius:4px}"
             "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:.3rem;text-align:left}"
             ".muted{color:#666}</style>"]
    for r in released:
        parts.append(f"<h1>{escape(r['type'])}: response from {escape(firm_name)}</h1>"
                     f"<p class='muted'>Notice dated {escape(r['dated'])}; response due {escape(str(r.get('response_due')))}. "
                     f"Return as filed: federal submission {escape(str(r.get('filed_submission')))}. "
                     f"Released {escape(r['released_at'][:10])}.</p>")
        for item in r["items"]:
            parts.append(f"<h2>Item {item['item'] + 1}</h2><p><em>{escape(item['examined'])}</em></p>"
                         f"<h3>Our answer</h3><p>{escape(item['answer'] or '')}</p>")
            for ev in item["evidence"]:
                parts.append(_export_evidence(ev))
    return "".join(parts)


def _export_evidence(ev: dict) -> str:
    kind = ev["kind"]
    if kind == "line":
        rows = "".join(f"<tr><td>{escape(s['ref'])}</td><td>{escape(str(s.get('title') or s.get('kind')))}</td>"
                       f"<td>{escape(str(s.get('field') or ''))}</td><td>{escape(str(s.get('value') if 'value' in s else s.get('text') or ''))}</td></tr>"
                       for s in ev["sources"])
        adjusted = "".join(f"<li>Adjusted from {escape(str(a['from']))} to {escape(str(a['to']))}: {escape(a['reason'] or '')}</li>"
                           for a in ev["adjustments"])
        verified = "".join(f"<li>{escape(v['type'].replace('_', ' '))} by {escape(v['by'])}, {escape(v['at'][:10])}</li>"
                           for v in ev["verified"])
        return (f"<h3>{escape(ev['key'])} {escape(ev['label'])}: {escape(str(ev['as_filed']))} as filed</h3>"
                + (f"<ul>{adjusted}</ul>" if adjusted else "")
                + (f"<table><tr><th>Source</th><th>Document</th><th>Field</th><th>Value</th></tr>{rows}</table>" if rows else "")
                + (f"<p>Verified:</p><ul>{verified}</ul>" if verified else ""))
    if kind == "document":
        pages = "".join(f"<p class='muted'>Page {p['page']}</p><pre>{escape(p['text'])}</pre>" for p in ev["pages"])
        return f"<h3>{escape(ev['ref'])} {escape(ev['title'])}</h3>{pages}"
    if kind == "client":
        return f"<h3>Client: {escape(ev['ref'])}</h3><p>{escape(ev.get('text') or '')}</p><p class='muted'>{escape(str(ev.get('from') or ''))}</p>"
    if kind == "attachment":
        return (f"<h3>Attached file: {escape(str(ev['file_name']))}</h3>"
                f"<p class='muted'>sha256 {escape(str(ev['sha256']))}, {ev.get('size')} bytes. {escape(ev.get('note') or '')}</p>")
    return f"<p class='muted'>{escape(ev['ref'])}: not found in the return as filed.</p>"
