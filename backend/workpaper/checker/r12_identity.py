"""R12. Identity.

Every SSN on the return comes from the client organizer, which the client typed.
The checker looks for each person's SSN printed on a document (a Social Security
card, a W-2, last year's return) and compares. A mismatch rejects the e-file; no
document at all leaves the "Identity verified" step open.

Messages show only the last four digits. Full numbers are in `details` under keys
starting with 'ssn', so role masking has one place to act.

Catches: E17 (Theo's organizer SSN ends 3309; last year's return and the Social
Security card print 3390). The 2024 return arrived in January, so this was
catchable before the July e-file rejection.
"""

from __future__ import annotations

import re

from .common import CONFLICT, OPEN_ITEM, Context, Finding

SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
NAME_WINDOW = 80  # characters before an SSN in which the person's name must appear


def check(ctx: Context) -> list[Finding]:
    printed = _printed_ssns(ctx)
    efile = ctx.packet.raw["tax_agency_records"]["efile"]
    findings = []
    for person in ctx.packet.people.values():
        organizer = person.get("ssn")
        if not organizer:
            continue
        seen = printed.get(person["id"], [])
        rejections = [f"agency:/efile/{i}" for i, sub in enumerate(efile)
                      if ctx.visible(sub["date"]) and any(person["name"] in err["message"] for err in sub.get("errors", []))]
        different = [s for s in seen if s["ssn"] != organizer]
        if different:
            docs = sorted({s["doc"] for s in different})
            findings.append(Finding(
                id=f"R12:{person['id']}", rule="R12", kind=CONFLICT,
                title="SSN on the organizer does not match the documents",
                message=(f"{person['name']}'s SSN on the client organizer ends {organizer[-4:]}; "
                         f"{' and '.join(_describe(ctx, d) for d in docs)} {'print' if len(docs) > 1 else 'prints'} "
                         f"one ending {different[0]['ssn'][-4:]}."
                         + (" The federal e-file was rejected for this dependent's TIN." if rejections else "")),
                targets=[f"household:{person['id']}"],
                evidence=[f"doc:{s['doc']}#page{s['page']}" for s in different] + rejections,
                severity="error",
                details={"ssn_on_organizer": organizer, "ssn_on_documents": sorted({s["ssn"] for s in different})},
            ))
        elif not seen:
            findings.append(Finding(
                id=f"R12:{person['id']}", rule="R12", kind=OPEN_ITEM,
                title="No document supports this SSN",
                message=(f"{person['name']}'s SSN (ending {organizer[-4:]}) comes only from the client organizer. "
                         f"No document in the packet prints it."),
                targets=[f"household:{person['id']}"], evidence=rejections, severity="warning",
                details={"ssn_on_organizer": organizer},
            ))
    return findings


def _printed_ssns(ctx: Context) -> dict[str, list[dict]]:
    """{person id: [{doc, page, ssn}]}: every SSN printed next to a household member's name."""
    out: dict[str, list[dict]] = {}
    for d in ctx.documents():
        for page in d["pages"]:
            text = page["printed_content"]
            for m in SSN.finditer(text):
                person = _named_before(ctx, text, m.start()) or _owner(ctx, d)
                if person:
                    out.setdefault(person, []).append({"doc": d["id"], "page": page["page"], "ssn": m.group(0)})
    return out


def _named_before(ctx: Context, text: str, at: int) -> str | None:
    """The household member whose name appears closest before position `at`."""
    window = text[max(0, at - NAME_WINDOW):at]
    best, best_pos = None, -1
    for p in ctx.packet.people.values():
        for name in {p["name"], p["name"].split()[0]}:
            pos = window.rfind(name)
            if pos > best_pos:
                best, best_pos = p["id"], pos
    return best


def _owner(ctx: Context, doc: dict) -> str | None:
    """Fallback: who a document belongs to (taxpayer, spouse, dependent:<id>)."""
    belongs = doc["belongs_to"]
    if belongs.startswith("dependent:"):
        return belongs.split(":", 1)[1]
    role = {"taxpayer": "taxpayer", "spouse": "spouse"}.get(belongs)
    return next((p["id"] for p in ctx.packet.people.values() if p["role"] == role), None) if role else None


def _describe(ctx: Context, doc_id: str) -> str:
    return f"{doc_id} ({ctx.packet.documents[doc_id]['title']})"
