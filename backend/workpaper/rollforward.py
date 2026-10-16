"""Rolling 2025 into 2026 (D30 to D33): the carryovers with their history, the asset register's
ending depreciation, and the 2026 estimates. Pure functions of the projected state.

Everything is built from the return as filed (the last filed transmission), or, before filing,
from the return as it stands, labelled so. The engine's carryovers are shown as it computed them.
When a person changed a line one rests on, or an open checker correction touches one, the
carryover is flagged for recomputing, never re-estimated (D30).
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from .checker import CheckResult
from .packet import Packet
from .project import State
from .taxeffect import category_for_line, is_amount, round_half_up

# Where each carryover is worked out on the 2025 return: (key prefix, the 2025 lines, the matching
# 2024 carryover prefix). Form knowledge, like SUMMARY_LINES; the packet names the carryovers.
CARRYOVER_LINES = [
    ("capital_loss", ["SchD.6", "SchD.14", "SchD.16"], "capital_loss"),
    ("passive", ["F8582.1c", "F8582.4"], "passive"),
    ("minimum_tax_credit", ["F6251.11"], "amt_credit"),
    ("charitable", ["SchA.14"], "charitable"),
    ("section_179", ["F4562-C.12"], None),
    ("ira_nondeductible_basis", ["F8606.14"], None),
    ("scorp_stock_basis", ["F7203.15"], None),
    ("sep_contribution", ["Sch1.16"], None),
]
# A partnership capital account is not a return line; it is the K-1's ending capital.
CAPITAL_ACCOUNT_FIELD = "cap_end"

# The California method decision is a judgment call on this reference (D32). Its payload names the
# method: "safe_harbor" (110% of 2025 tax) or "projected" (90% of a projected 2026 California tax,
# which the judgment must carry as projected_2026_tax).
PLAN_CALIFORNIA = "plan:california_estimates_2026"
CALIFORNIA_METHODS = {"safe_harbor", "projected"}
PROJECTED_SHARE = 0.90
OVERPAY_NOTE = ("This likely overpays: after the move, California taxes only California-source income in 2026. "
                "The 90% method needs a projection of 2026 California tax, which the engine cannot make.")

# planning_reference_2026: federal "110% of 2025 total tax (2025 AGI over 150,000)", California
# "110% of 2025 tax (2025 California AGI 150,000 or more)". Below the threshold it is 100%.
HIGH_INCOME = 150_000


# ---- carryovers --------------------------------------------------------------------

def carryovers(packet: Packet, state: State, result: CheckResult) -> dict:
    out = state.version["carryovers_out"]
    into = packet.raw["prior_years"]["carryovers_into_2025"]
    versions = [v for v in packet.versions if v["computed_at"] <= state.version["computed_at"]]
    rows = {"federal": [], "california": []}
    for jurisdiction in ("federal", "california"):
        came_in = into if jurisdiction == "federal" else into.get("california", {})
        for key, value in out[jurisdiction].items():
            if key == "depreciation_basis_differences":
                continue
            lines, into_prefix = _lines_for(key)
            sources = _capital_account_values(packet, state) if "capital_account" in key else []
            rows[jurisdiction].append({
                "key": key, "label": key.replace("_", " "), "out_2026": value,
                "in_2025": _came_in(came_in, key, into_prefix),
                "by_version": {v["version"]: v["carryovers_out"][jurisdiction].get(key) for v in versions},
                "lines": [k for k in lines if k in state.lines], "sources": sources,
                "moved": _moved(state, result, lines),
            })
    return {**rows, "california_depreciation": _california_depreciation(state)}


def _lines_for(key: str) -> tuple[list[str], str | None]:
    for prefix, lines, into_prefix in CARRYOVER_LINES:
        if key.startswith(prefix):
            return lines, into_prefix
    return [], None


def _came_in(came_in: dict, key: str, into_prefix: str | None):
    if key in came_in:
        return came_in[key]
    matches = [v for k, v in came_in.items() if into_prefix and k.startswith(into_prefix) and isinstance(v, (int, float))]
    return sum(matches) if matches else None


def _capital_account_values(packet: Packet, state: State) -> list[str]:
    return [ev["id"] for ev in packet.values.values()
            if ev["field"] == CAPITAL_ACCOUNT_FIELD and state.document_visible(packet.documents[ev["document_id"]])]


def rests_on(state: State, lines: list[str]) -> set[str]:
    """The lines a carryover is worked out on, and every line they are built from."""
    seen, todo = set(), [k for k in lines if k in state.lines]
    while todo:
        key = todo.pop()
        if key not in seen:
            seen.add(key)
            todo += [k for k in state.lines[key]["inputs"] if k in state.lines]
    return seen


def feeds(state: State, key: str) -> set[str]:
    """The lines a line is added into. A line the engine never had (a lot from an unread page, or one a
    correction proposes) feeds what its siblings feed: F8949.B.M18 goes where F8949.B.N1 goes."""
    if key in state.packet.lines[state.version_id]:
        return {k for k, line in state.lines.items() if key in line["inputs"]}
    prefix = key.rsplit(".", 1)[0] + "."
    return {k for k, line in state.lines.items() if any(i.startswith(prefix) for i in line["inputs"])}


def _moved(state: State, result: CheckResult, lines: list[str]) -> dict | None:
    """Did anything move under this carryover since the engine computed it (D30)? A line counts if
    the carryover is built from it, or if it is added into a line the carryover is built from."""
    under = rests_on(state, lines)

    def is_under(key: str) -> bool:
        return key in under or bool(feeds(state, key) & under)

    adjusted = sorted({a.line for a in state.applied_adjustments() if is_under(a.line)})
    corrected = sorted(k for k in result.corrected_lines if is_under(k))
    if not adjusted and not corrected:
        return None
    return {"adjusted": adjusted, "open_corrections": corrected,
            "why": "moved since the engine computed it: recompute"}


def _california_depreciation(state: State) -> list[dict]:
    """California's depreciation basis that differs from federal, per asset (carried to 2026)."""
    differences = state.version["carryovers_out"]["california"].get("depreciation_basis_differences", {})
    assets = {a["asset_id"]: a for a in state.version["assets"]}
    return [{"asset": asset_id, "description": assets.get(asset_id, {}).get("description"), "difference": amount,
             "federal_accumulated": assets.get(asset_id, {}).get("federal", {}).get("accumulated_end"),
             "california_accumulated": assets.get(asset_id, {}).get("california", {}).get("accumulated_end")}
            for asset_id, amount in differences.items()]


# ---- the asset register --------------------------------------------------------------

def asset_register(state: State) -> list[dict]:
    """Every asset at the end of 2025: what carries into 2026, and what was disposed of."""
    out = []
    for a in state.version["assets"]:
        out.append({
            "asset": a["asset_id"], "description": a["description"], "activity": a["activity"],
            "placed_in_service": a["placed_in_service"], "method": a["method"], "life_years": a["life_years"],
            "cost": a["cost"], "federal_accumulated": a["federal"]["accumulated_end"],
            "california_accumulated": a["california"]["accumulated_end"],
            "amt_difference_2025": a["amt"]["difference_from_regular"],
            "carried": not a.get("disposed"), "disposed": a.get("disposed"),
        })
    return out


# ---- the 2026 estimates -----------------------------------------------------------------

def total_tax_2025(state: State) -> dict:
    """2025 total tax: the engine's, moved by each adjustment's estimated tax effect. Payment
    corrections change the balance, not the tax, so they are left out (D31)."""
    tax = {j: state.version["summary"][j]["total_tax"] for j in ("federal", "california")}
    for adj in state.applied_adjustments():
        if adj.effect and category_for_line(adj.line) != "payment":
            for j in tax:
                tax[j] += adj.effect[j]
    return tax


def estimates_2026(packet: Packet, state: State, clock: str, now: State | None = None) -> dict:
    """`state` is the return as filed; `now` is the current log, where a planning decision made
    after filing lives."""
    plan = packet.raw["planning_reference_2026"]
    summary = state.version["summary"]
    tax = total_tax_2025(state)

    federal_pct = 1.10 if summary["federal"]["agi"] > HIGH_INCOME else 1.00
    federal_annual = round_half_up(tax["federal"] * federal_pct)
    federal = _installments(federal_annual, plan["federal_estimate_due_dates"],
                            [1 / len(plan["federal_estimate_due_dates"])] * len(plan["federal_estimate_due_dates"]), clock)

    california_pct = 1.10 if summary["california"]["ca_agi"] >= HIGH_INCOME else 1.00
    safe_harbor_annual = round_half_up(tax["california"] * california_pct)
    california_dates, california_shares = plan["california_estimate_due_dates"], plan["california_installment_percentages"]
    safe_harbor = {"annual": safe_harbor_annual,
                   "installments": _installments(safe_harbor_annual, california_dates, california_shares, clock)}

    # The firm's choice (D32). Until there is one, nothing is marked as the amount to pay. Only a
    # decision that names a method (and, for the 90% method, the projected tax) sets an amount.
    decision = next((r for r in reversed((now or state).records)
                     if r.action == "judgment_call" and PLAN_CALIFORNIA in r.targets
                     and usable_plan(r.payload)), None)
    chosen = None
    if decision:
        method = decision.payload["method"]
        chosen = {"method": method, "decision": decision.payload.get("decision"),
                  "authority": decision.payload.get("authority"), "by": decision.actor, "at": decision.at,
                  "reason": decision.reason, "event": decision.event_id}
        if method == "projected":
            projected = decision.payload["projected_2026_tax"]
            annual = round_half_up(projected * PROJECTED_SHARE)
            chosen |= {"projected_2026_tax": projected, "share": PROJECTED_SHARE, "annual": annual,
                       "installments": _installments(annual, california_dates, california_shares, clock)}
        else:
            chosen |= {"annual": safe_harbor["annual"], "installments": safe_harbor["installments"]}
    return {
        "federal": {"base_total_tax_2025": tax["federal"], "percent": federal_pct, "annual": federal_annual,
                    "installments": federal, "rule": plan["federal_safe_harbor"]},
        "california": {"base_total_tax_2025": tax["california"], "percent": california_pct,
                       "rule": plan["california_safe_harbor"], "plan_ref": PLAN_CALIFORNIA,
                       "safe_harbor": safe_harbor, "chosen": chosen,
                       "to_pay": chosen["method"] if chosen else None,
                       "overpay_note": None if chosen and chosen["method"] == "projected" else OVERPAY_NOTE},
        "known_2026_changes": plan["known_2026_changes_for_this_household"],
        "estimate": True,
    }


def usable_plan(payload: dict) -> bool:
    """The same test the server applies when the decision is recorded (actions._california_plan):
    the safe harbor, or the 90% method with a projected tax in whole dollars, zero or more."""
    method, projected = payload.get("method"), payload.get("projected_2026_tax")
    if method == "safe_harbor":
        return True
    return method == "projected" and is_amount(projected) and projected >= 0 and float(projected).is_integer()


def _installments(annual: int, dates: list[str], shares: list[float], clock: str) -> list[dict]:
    """Split a year's amount over its due dates; the last one takes the rounding."""
    amounts = [round_half_up(annual * s) for s in shares[:-1]]
    amounts.append(annual - sum(amounts))
    return [{"due": d, "amount": a, "passed": d < clock[:10]} for d, a in zip(dates, amounts)]


# ---- the whole roll-forward ---------------------------------------------------------------

def rollforward(packet: Packet, state: State, result: CheckResult, filed, now: State | None = None) -> dict:
    """`state` and `result` are the return as filed (or as it stands, if `filed` is None); `now`
    is the current log, for the decisions made since."""
    clock = state.as_of or datetime.now(timezone.utc).isoformat()
    return {
        "built_from": ({"filed": True, "event": filed.event_id, "at": filed.at, "kind": filed.kind,
                        "submission": filed.answer["federal"].get("submission_id")}
                       if filed else {"filed": False, "note": "Not filed yet: built from the return as it stands."}),
        "version": state.version_id,
        "carryovers": carryovers(packet, state, result),
        "assets": asset_register(state),
        "estimates": estimates_2026(packet, state, clock, now),
    }


# ---- the export for next year's preparer -----------------------------------------------------

def export_html(view: dict, firm_name: str) -> str:
    """The roll-forward as one file: no scripts, no links out. `view` is already masked."""
    e = escape
    built = view["built_from"]
    parts = ["<!doctype html><meta charset='utf-8'><title>2026 opening</title>"
             "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 16px;color:#111}"
             "table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}td,th{border-bottom:1px solid #ddd;"
             "padding:.3rem;text-align:left}td.n{text-align:right}.muted{color:#666}</style>",
             f"<h1>Okafor-Lindqvist: 2026 opening</h1><p class='muted'>{e(firm_name)}. Built from "
             + (f"the return as filed (event {built['event']}, {e(built['at'][:10])}, submission {e(str(built['submission']))})"
                if built["filed"] else e(built["note"]))
             + f", version {e(view['version'])}.</p>"]
    for j in ("federal", "california"):
        rows = "".join(
            f"<tr><td>{e(c['label'])}</td><td class='n'>{e(str(c['in_2025']))}</td>"
            f"<td>{e(', '.join(f'{v}: {x}' for v, x in c['by_version'].items()))}</td><td class='n'>{e(str(c['out_2026']))}</td>"
            f"<td>{e(', '.join(c['lines'] + c['sources']))}</td><td>{_moved_words(c['moved'])}</td></tr>"
            for c in view["carryovers"][j])
        parts.append(f"<h2>{j.title()} carryovers</h2><table><tr><th>Carryover</th><th>In from 2024</th><th>By version</th>"
                     f"<th>Out to 2026</th><th>2025 lines</th><th>Flag</th></tr>{rows}</table>")
    rows = "".join(f"<tr><td>{e(a['asset'])}</td><td>{e(a['description'])}</td><td class='n'>{a['federal_accumulated']:,.2f}</td>"
                   f"<td class='n'>{a['california_accumulated']:,.2f}</td><td class='n'>{a['amt_difference_2025']:,.2f}</td>"
                   f"<td>{'carried' if a['carried'] else 'disposed'}</td></tr>"
                   for a in view["assets"])
    parts.append(f"<h2>Assets at the end of 2025</h2><table><tr><th>Asset</th><th>Description</th><th>Federal accumulated</th>"
                 f"<th>California accumulated</th><th>AMT difference 2025</th><th></th></tr>{rows}</table>")
    federal = view["estimates"]["federal"]
    parts.append(f"<h2>2026 federal estimates (estimate)</h2><p>{e(federal['rule'])}</p>"
                 f"<p>{federal['percent']:.0%} of 2025 total tax {federal['base_total_tax_2025']:,} = {federal['annual']:,}.</p>"
                 + _schedule(federal["installments"]))
    california = view["estimates"]["california"]
    chosen, harbor = california["chosen"], california["safe_harbor"]
    parts.append(f"<h2>2026 California estimates (estimate)</h2><p>{e(california['rule'])}</p>")
    if chosen and chosen["method"] == "projected":
        parts.append(f"<p><strong>To pay:</strong> 90% of projected 2026 California tax {chosen['projected_2026_tax']:,.0f} = "
                     f"{chosen['annual']:,}.</p>" + _schedule(chosen["installments"]))
    elif chosen:
        parts.append("<p><strong>To pay:</strong> the safe harbor below.</p>")
    else:
        parts.append("<p><strong>No method chosen yet.</strong> Nothing is marked as the amount to pay.</p>")
    if chosen:
        parts.append(f"<p>Decision: {e(chosen['decision'])} (authority: {e(chosen['authority'])}).</p>")
    parts.append(f"<p>Safe harbor: {california['percent']:.0%} of 2025 California tax {california['base_total_tax_2025']:,} = "
                 f"{harbor['annual']:,}.</p>" + _schedule(harbor["installments"])
                 + (f"<p>{e(california['overpay_note'])}</p>" if california["overpay_note"] else ""))
    parts.append("<h2>Known changes for 2026</h2><ul>" + "".join(f"<li>{e(t)}</li>" for t in view["estimates"]["known_2026_changes"]) + "</ul>")
    return "".join(parts)


def _moved_words(moved: dict | None) -> str:
    """The flag and the lines that moved under it, named (D34)."""
    if not moved:
        return ""
    named = [f"adjusted: {', '.join(moved['adjusted'])}"] if moved["adjusted"] else []
    named += [f"open corrections: {', '.join(moved['open_corrections'])}"] if moved["open_corrections"] else []
    return f"{escape(moved['why'])} ({escape('; '.join(named))})"


def _schedule(installments: list[dict]) -> str:
    return "<table>" + "".join(f"<tr><td>{escape(i['due'])}</td><td class='n'>{i['amount']:,}</td></tr>"
                               for i in installments) + "</table>"
