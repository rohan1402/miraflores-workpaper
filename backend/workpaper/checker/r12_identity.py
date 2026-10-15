"""R12. Identity.

Every SSN on the return comes from the client organizer, which the client typed.
The checker looks for each person's SSN printed on a document (a Social Security
card, a W-2, last year's return) and compares. A mismatch rejects the e-file; no
document at all leaves the "Identity verified" step open.

Messages show only the last four digits. Full numbers are in `details` under keys
starting with 'ssn', so role masking has one place to act. The printed numbers are read by
identity.py, which the simulated agency (filing.py) shares.

A person answers the finding by correcting the number from a document (correct_identity);
the agency reads the digits on the return, so an accepted finding with the old number still
gets rejected.

Catches: E17 (Theo's organizer SSN ends 3309; last year's return and the Social
Security card print 3390). The 2024 return arrived in January, so this was
catchable before the July e-file rejection.
"""

from __future__ import annotations

from ..filing import transmissions
from ..identity import printed_ssns, ssns_on_return
from .common import CONFLICT, OPEN_ITEM, Context, Finding


def check(ctx: Context) -> list[Finding]:
    printed = printed_ssns(ctx.packet, ctx.documents())
    on_return = ssns_on_return(ctx.state)
    rejected = [t for t in transmissions(ctx.state) if t.answer["federal"]["status"] == "rejected"]
    findings = []
    for pid, now in on_return.items():
        person = ctx.packet.people[pid]
        organizer = person["ssn"]
        seen = printed.get(pid, [])
        # The firm's own transmissions the agency rejected for this person's number (D23).
        rejections = [f"event:{t.event_id}" for t in rejected if pid in t.answer["wrong_tins"]]
        different = [s for s in seen if s["ssn"] != organizer]
        if different:
            docs = sorted({s["doc"] for s in different})
            finding = Finding(
                code="SSN_MISMATCH", subject=pid, rule="R12", kind=CONFLICT,
                title="SSN on the organizer does not match the documents",
                message=(f"{person['name']}'s SSN on the client organizer ends {organizer[-4:]}; "
                         f"{' and '.join(_describe(ctx, d) for d in docs)} {'print' if len(docs) > 1 else 'prints'} "
                         f"one ending {different[0]['ssn'][-4:]}."
                         + (" The federal e-file was rejected for this dependent's TIN." if rejections else "")),
                targets=[f"household:{pid}"],
                evidence=[f"doc:{s['doc']}#page{s['page']}" for s in different] + rejections,
                severity="error",
                details={"ssn_on_organizer": organizer, "ssn_on_documents": sorted({s["ssn"] for s in different}),
                         "documents": docs},
                answer={"act": "correct_identity", "person": pid, "documents": docs},
            )
            # The return now carries the number the documents print: the correction answers it.
            if now["source"] != "organizer" and all(s["ssn"] == now["ssn"] for s in seen):
                finding.status, finding.addressed_by = "addressed", now["event"]
                finding.answer = None
            findings.append(finding)
        elif not seen:
            findings.append(Finding(
                code="SSN_UNSUPPORTED", subject=pid, rule="R12", kind=OPEN_ITEM,
                title="No document supports this SSN",
                message=(f"{person['name']}'s SSN (ending {organizer[-4:]}) comes only from the client organizer. "
                         f"No document in the packet prints it."),
                targets=[f"household:{pid}"], evidence=rejections, severity="warning",
                details={"ssn_on_organizer": organizer},
            ))
    return findings


def _describe(ctx: Context, doc_id: str) -> str:
    return f"{doc_id} ({ctx.packet.documents[doc_id]['title']})"
