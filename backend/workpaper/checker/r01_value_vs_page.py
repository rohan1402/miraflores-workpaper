"""R01. Value vs page.

Every extracted value must appear on its printed page, and every name or tax ID
a return line prints must match the document it came from. Confidence does not
matter here: a 0.97 value that is not on the page is still wrong.

Catches: E16 (care provider EIN digits swapped), E20 (handwritten amount read as
1,500 from '$?,500.00'), E29 (provider name on Form 2441 not the name on the
statement), and the zero bases on the RSU lots that R04 then explains.
"""

from __future__ import annotations

import re

from .common import DISAGREEMENT, Context, Finding, appears_on_page, issuer_core, issuer_words, money, page_of

TIN = re.compile(r"\b\d{2}-\d{7}\b")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def check(ctx: Context) -> list[Finding]:
    return _values_vs_pages(ctx) + _line_text_vs_source(ctx)


def _values_vs_pages(ctx: Context) -> list[Finding]:
    findings = []
    visible_docs = {d["id"] for d in ctx.documents()}
    for ev in ctx.packet.raw["extracted_values"]:
        if ev["document_id"] not in visible_docs or ev["value"] is None:
            continue  # nothing read: R04 and R13 handle missing values
        page = ctx.packet.page_text(ev["document_id"], ev["page"])
        if appears_on_page(ev, page):
            continue
        lines = ctx.lines_using({ev["id"]})
        blank_read_as_zero = ev["value"] == 0 and not (ev.get("text_as_read") or "").strip()
        details = {"value": ev["value"], "text_as_read": ev["text_as_read"], "confidence": ev["confidence"]}
        if ev["value_type"] in ("ein", "ssn"):
            pattern = TIN if ev["value_type"] == "ein" else SSN
            details["printed_ids_on_page"] = pattern.findall(page)
        if blank_read_as_zero:
            message = (f"{ev['label']} ({ev['document_id']} page {ev['page']}) was recorded as 0, "
                       f"but the page prints no amount there.")
        elif ev["value_type"] in ("ein", "ssn") and details["printed_ids_on_page"]:
            message = (f"{ev['label']} was read as {ev['value']} (confidence {ev['confidence']}), "
                       f"but the page prints {', '.join(details['printed_ids_on_page'])}.")
        else:
            shown = money(ev["value"]) if isinstance(ev["value"], (int, float)) else ev["value"]
            message = (f"{ev['label']} was read as {shown} (confidence {ev['confidence']}), "
                       f"but {shown} does not appear on {ev['document_id']} page {ev['page']}.")
        findings.append(Finding(
            code="VALUE_NOT_ON_PAGE", subject=ev["id"], rule="R01", kind=DISAGREEMENT,
            title="Value not on its printed page",
            message=message,
            targets=[ev["id"]] + [f"line:{k}" for k in lines],
            evidence=[page_of(ev)],
            severity="info" if ev["value"] == 0 and not lines else "warning",
            details=details,
        ))
    return findings


def _line_text_vs_source(ctx: Context) -> list[Finding]:
    """A line that prints a payer or provider must print the name and tax ID on its document."""
    findings = []
    prior_lines = ctx.packet.raw["prior_years"]["return_2024"]["lines"]
    for key, line in ctx.lines.items():
        docs = {ev["document_id"] for ev in ctx.source_values(line)}
        if len(docs) != 1:
            continue
        doc_id = docs.pop()
        doc = ctx.packet.documents[doc_id]
        text = ctx.packet.document_text(doc_id)
        label = line["label"]

        for tin in TIN.findall(label):
            if tin not in text:
                findings.append(Finding(
                    code="LINE_TIN_NOT_ON_DOCUMENT", subject=key, rule="R01", kind=DISAGREEMENT,
                    title="Tax ID on the return is not on the document",
                    message=(f"{key} prints tax ID {tin}; {doc_id} prints {', '.join(TIN.findall(text)) or 'none'}."),
                    targets=[f"line:{key}"], evidence=[f"doc:{doc_id}#page1"],
                    details={"on_return": tin, "on_document": TIN.findall(text)},
                ))

        named = _name_in_label(label, doc["issuer"])
        if named and issuer_core(named) != issuer_core(doc["issuer"]):
            evidence = [f"doc:{doc_id}#page1"]
            for py_key, py_value in prior_lines.items():
                if isinstance(py_value, str) and issuer_core(doc["issuer"]) in issuer_core(py_value):
                    evidence.append(f"py:/return_2024/lines/{py_key}")
            findings.append(Finding(
                code="LINE_NAME_NOT_ON_DOCUMENT", subject=key, rule="R01", kind=DISAGREEMENT,
                title="Name on the return is not the name on the document",
                message=(f"{key} names '{named}', but {doc_id} is from '{doc['issuer']}'."),
                targets=[f"line:{key}"], evidence=evidence,
                details={"on_return": named, "on_document": doc["issuer"]},
            ))
    return findings


def _name_in_label(label: str, issuer: str) -> str | None:
    """If the label names the issuer (same first two words), return the name as the label prints it."""
    first_two = issuer_words(issuer, 2)
    if len(first_two.split()) < 2:
        return None
    m = re.search(re.escape(first_two), label, flags=re.I)
    if not m:
        return None
    return re.split(r"[,;(]| - ", label[m.start():])[0].strip()
