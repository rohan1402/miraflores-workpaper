"""R07. Client answer vs treatment.

Client answers are evidence, but a distinct kind: a guess, a memory, a "yes" to a
question that changes the law that applies. This rule compares them both ways:

  (a) a line that took the client's number while a document on the same line prints another,
  (b) an answer that bars a deduction the return takes (employer coverage vs SE health insurance),
  (c) call notes or messages that give a business share, or call something personal,
      for an expense the books deduct in full,
  (d) "no" answers that the documents contradict,
  (e) answers about basis that the prior-year return contradicts.

Catches: E5 (car at the client's 6,000; the 1098-C says sold for 2,900), E4 (SE health
insurance though eligible for employer family coverage), E21 (phone 70%, internet 50%,
Spotify personal), qa-14 and qa-15 (no sales vs 282 lots and 12 crypto sales), qa-31 (IRA basis).
"""

from __future__ import annotations

import re

from ..taxeffect import category_for_line, estimate
from .common import CONFLICT, Change, Context, Finding, money, prints_amount

STOPWORDS = {"the", "and", "with", "about", "this", "that", "from", "for", "his", "her", "per", "are", "was",
             "has", "have", "into", "only", "estimates"}


def check(ctx: Context) -> list[Finding]:
    return (_line_took_client_number(ctx) + _eligibility_bars_deduction(ctx) + _business_share(ctx)
            + _no_answers_vs_documents(ctx) + _basis_answers_vs_prior_year(ctx))


def _answers(ctx: Context, kind: str = "questionnaire") -> list[dict]:
    return [c for c in ctx.packet.client_items.values() if c["kind"] == kind and ctx.visible(c["at"])]


def snippet(text: str, amount: float, width: int = 60) -> str:
    """The printed words around an amount, so the finding quotes the page."""
    for token in (f"{amount:,.2f}", f"{amount:,.0f}"):
        i = text.find(token)
        if i >= 0:
            start = max(0, text.rfind(";", 0, i) + 1, text.rfind(".", 0, i - 3) + 1, i - width)
            return text[start:i + len(token)].strip()
    return ""


# (a) -------------------------------------------------------------------------

def _line_took_client_number(ctx: Context) -> list[Finding]:
    findings = []
    for key, line in ctx.lines.items():
        value = ctx.value(key)
        if not isinstance(value, (int, float)):
            continue
        answers = [ctx.packet.client_items[s] for s in line["sources"]
                   if s in ctx.packet.client_items and ctx.packet.client_items[s]["kind"] == "questionnaire"]
        took = [a for a in answers if prints_amount(a["answer"], value)]
        if not took:
            continue
        docs = {ev["document_id"] for ev in ctx.source_values(line)}
        for doc_id in docs:
            printed = [ev for ev in ctx.packet.values_by_doc[doc_id] if ev["value_type"] == "money"]
            if not printed or any(ev["value"] == value for ev in printed):
                continue
            doc_amount = printed[0]["value"] if len(printed) == 1 else None
            quote = snippet(ctx.packet.document_text(doc_id), doc_amount) if doc_amount else ""
            category = category_for_line(key)
            changes = []
            if doc_amount is not None:
                delta = doc_amount - value
                effect = estimate(ctx.rates, federal=[(category, delta)], california=[(category, delta)]) if category else None
                changes = [Change(key, value, doc_amount, took[0]["id"], effect)]
            findings.append(Finding(
                code="CLIENT_FIGURE_VS_DOCUMENT", subject=key, rule="R07", kind=CONFLICT,
                title="Line uses the client's number; the document prints another",
                message=(f"{key} ({line['label']}) is {money(value)}, the client's figure in {took[0]['id']} "
                         f"(\"{took[0]['answer']}\"). {doc_id} ({ctx.packet.documents[doc_id]['title']}) prints "
                         + (f"\"{quote}\"." if quote else f"{', '.join(money(ev['value']) for ev in printed)}.")),
                targets=[f"line:{key}"], evidence=[took[0]["id"], doc_id] + [ev["id"] for ev in printed],
                severity="error", changes=changes,
                details={"client_figure": value, "document_figures": [ev["value"] for ev in printed]},
            ))
    return findings


# (b) -------------------------------------------------------------------------

def _eligibility_bars_deduction(ctx: Context) -> list[Finding]:
    """Self-employed health insurance is not allowed for months the person could join an
    employer-subsidized plan, including a spouse's employer plan (IRC 162(l)(2)(B))."""
    key = "Sch1.17"
    value = ctx.value(key)
    if not value:
        return []
    yes = [a for a in _answers(ctx)
           if "eligible" in a["question"].lower() and "coverage" in a["question"].lower()
           and a["answer"].strip().lower().startswith("yes")]
    if not yes:
        return []
    prior_note = ctx.packet.raw["prior_years"]["return_2024"]["notes"].get(key)
    effect = estimate(ctx.rates, federal=[("adjustment", -value)], california=[("adjustment", -value)])
    effect.workings.append("Not captured: the QBI deduction also changes with this adjustment.")
    return [Finding(
        code="ANSWER_BARS_DEDUCTION", subject=key, rule="R07", kind=CONFLICT,
        title="Client answer bars a deduction the return takes",
        message=(f"{key} deducts {money(value)} of self-employed health insurance, but {yes[0]['id']} answers "
                 f"\"{yes[0]['answer']}\" to \"{yes[0]['question']}\" Eligibility for an employer plan, "
                 f"including a spouse's, bars the deduction for those months."
                 + (f" The 2024 return did not take it: \"{prior_note}\"" if prior_note else "")),
        targets=[f"line:{key}"], evidence=[a["id"] for a in yes] + ([f"py:/return_2024/notes/{key}"] if prior_note else []),
        severity="error", changes=[Change(key, value, 0, yes[0]["id"], effect)],
    )]


# (c) -------------------------------------------------------------------------

def _business_share(ctx: Context) -> list[Finding]:
    accounts = _books_accounts(ctx)
    items = _books_items(ctx)
    findings = []
    sources = _answers(ctx, "call_note") + _answers(ctx, "message")
    for item in sources:
        notes = item.get("notes") or [item.get("text", "")]
        disallow: dict[str, dict] = {}
        quotes = []
        for note in notes:
            pct = re.search(r"(\d{1,3})%", note)
            if pct:
                account = _best_account(note, accounts, _household_names(ctx))
                if account:
                    share = int(pct.group(1)) / 100
                    amount = round(account["amount"] * (1 - share), 2)
                    disallow.setdefault(account["name"], {"amount": 0.0, "ev": account["ev"]})["amount"] += amount
                    quotes.append(f"\"{note}\" ({account['name']} {money(account['amount'])}, deduct "
                                  f"{money(account['amount'] - amount)})")
            elif "personal" in note.lower():
                for name, (amount, account_name) in items.items():
                    if name.lower() in note.lower() and account_name in accounts:
                        acct = accounts[account_name]
                        disallow.setdefault(account_name, {"amount": 0.0, "ev": acct["ev"]})["amount"] += amount
                        quotes.append(f"\"{note}\" ({name} {money(amount)} in {account_name})")
        if disallow:
            findings.append(_business_share_finding(ctx, item, disallow, quotes))
    return findings


def _books_accounts(ctx: Context) -> dict[str, dict]:
    """Expense accounts in the books with their printed description: {'Telephone': {...}}."""
    accounts = {}
    books = [d for d in ctx.documents() if d["document_type"].startswith("books_")]
    for d in books:
        for ev in ctx.packet.values_by_doc[d["id"]]:
            if ev["value_type"] == "money" and ev["field"][:1].isupper():
                accounts.setdefault(ev["field"], {"name": ev["field"], "amount": ev["value"], "ev": ev["id"], "text": ev["field"]})
        for page in d["pages"]:
            for sentence in re.split(r"(?<=\.)\s+", page["printed_content"]):
                m = re.match(r"([A-Z][A-Za-z &-]+?) ([\d,]+\.\d{2})[: ]", sentence)
                if m and m.group(1) in accounts:
                    accounts[m.group(1)]["text"] += " " + sentence
    return accounts


def _books_items(ctx: Context) -> dict[str, tuple[float, str]]:
    """Line items the books detail lists inside an account: {'Spotify Family': (216.0, 'Software and subscriptions')}."""
    items = {}
    for d in ctx.documents():
        if d["document_type"] != "books_transaction_detail":
            continue
        for page in d["pages"]:
            m = re.match(r".*?([A-Z][A-Za-z &-]+?) ([\d,]+\.\d{2}) includes (.*)", page["printed_content"])
            if not m:
                continue
            for name, amount in re.findall(r"([A-Z][\w]*(?: [A-Z][\w]*)*) ([\d,]+\.\d{2})", m.group(3)):
                items[name] = (float(amount.replace(",", "")), m.group(1))
    return items


def _household_names(ctx: Context) -> set[str]:
    """People's names are not evidence of which account a note is about."""
    return {part.lower() for p in ctx.packet.people.values() for part in re.findall(r"[A-Za-z]+", p["name"])}


def _words(text: str, ignore: set[str] = frozenset()) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in STOPWORDS and w not in ignore}


def _best_account(note: str, accounts: dict, ignore: set[str]) -> dict | None:
    """The books account whose name and printed description share the most words with the note (at least 2)."""
    scored = sorted(((len(_words(note, ignore) & _words(a["text"], ignore)), a) for a in accounts.values()),
                    key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] >= 2 else None


def _business_share_finding(ctx: Context, item: dict, disallow: dict, quotes: list) -> Finding:
    changes, total = [], 0.0
    for account, d in disallow.items():
        total += d["amount"]
        effect = estimate(ctx.rates, federal=[("schc_profit", d["amount"])], california=[("schc_profit", d["amount"])])
        for key in ctx.lines_using({d["ev"]}):
            if key.startswith("SchC."):
                # One correction per books account: two accounts on one line are two real corrections.
                changes.append(Change(key, ctx.value(key), round(ctx.value(key) - d["amount"], 2), d["ev"], effect))
    return Finding(
        code="CLIENT_BUSINESS_SHARE", subject=item["id"], rule="R07", kind=CONFLICT,
        title="Client says part of a deducted expense is personal",
        message=(f"The books deduct these expenses in full, but {item['id']} says otherwise: " + "; ".join(quotes)
                 + f". Schedule C expenses fall by {money(total)}. Recording the client's estimate is a preparer judgment."),
        targets=sorted({f"line:{c.line}" for c in changes}) + [d["ev"] for d in disallow.values()],
        evidence=[item["id"]], severity="warning", changes=changes,
        details={"disallowed": {k: v["amount"] for k, v in disallow.items()}, "total": total},
    )


# (d) -------------------------------------------------------------------------

TOPICS = [
    # (words in the question, document types whose sales contradict a "no")
    (("sell", "stock"), {"1099-composite", "1099-B"}),
    (("crypto",), {"1099-DA"}),
]


def _negative(answer: str) -> bool:
    a = answer.strip().lower()
    return a.startswith("no") or "didn't" in a or "did not" in a


def _no_answers_vs_documents(ctx: Context) -> list[Finding]:
    findings = []
    for a in _answers(ctx):
        q = a["question"].lower()
        for words, doc_types in TOPICS:
            if not all(w in q for w in words) or not _negative(a["answer"]):
                continue
            docs = {d["id"] for d in ctx.documents() if d["document_type"] in doc_types}
            sales = [k for k, line in ctx.lines.items() if k.startswith("F8949.")
                     and {ev["document_id"] for ev in ctx.source_values(line)} & docs]
            docs = {ev["document_id"] for k in sales for ev in ctx.source_values(ctx.lines[k])} & docs
            if sales:
                findings.append(Finding(
                    code="ANSWER_VS_DOCUMENTS", subject=a["id"], rule="R07", kind=CONFLICT,
                    title="Client answer contradicted by documents",
                    message=(f"{a['id']} answers \"{a['answer']}\" to \"{a['question']}\", but the documents show "
                             f"{len(sales)} sales on Form 8949 ({', '.join(sorted(docs))}). The return follows the "
                             f"documents; confirm with the client."),
                    targets=[a["id"]], evidence=sorted(docs), severity="warning",
                    details={"sales": len(sales)},
                ))
    return findings


# (e) -------------------------------------------------------------------------

def _basis_answers_vs_prior_year(ctx: Context) -> list[Finding]:
    """Nondeductible IRA basis carries forward on Form 8606 line 14."""
    prior = ctx.packet.raw["prior_years"]["return_2024"]["lines"]
    carried = prior.get("F8606.14")
    if not carried:
        return []
    findings = []
    for a in _answers(ctx):
        if "basis" in a["question"].lower() and "ira" in a["question"].lower() and "none" in a["answer"].lower():
            used = ctx.value("F8606.2")
            engine = (f"The engine used {money(used)} on F8606.2, which agrees with the documents."
                      if used == carried else f"F8606.2 shows {used}.")
            findings.append(Finding(
                code="ANSWER_VS_PRIOR_YEAR", subject=a["id"], rule="R07", kind=CONFLICT,
                title="Client answer contradicted by the prior-year return",
                message=(f"{a['id']} says \"{a['answer'][:90]}...\", but the 2024 Form 8606 line 14 carries "
                         f"{money(carried)} of basis into 2025. {engine}"),
                targets=[a["id"], "line:F8606.2"], evidence=["py:/return_2024/lines/F8606.14"],
                severity="info" if used == carried else "error",
            ))
    return findings
