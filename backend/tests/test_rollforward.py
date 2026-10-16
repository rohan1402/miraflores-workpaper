"""Rolling 2025 into 2026 (D30 to D33): carryovers traced and flagged, assets, the 2026 estimates."""

import re

import pytest
from fastapi.testclient import TestClient

from workpaper.api import create_app
from workpaper.checker import run_checker
from workpaper.project import adjustment_payload, project
from workpaper.rollforward import PLAN_CALIFORNIA, rollforward

from conftest import ev, log
from test_filing import DANIEL, HELEN, JO, PRIYA, accepted, act, as_, filing, ok


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "workpaper.db", heartbeat_seconds=0.05)) as c:
        yield c


def view(packet, events=()):
    state = project(packet, log(*events))
    return rollforward(packet, state, run_checker(packet, state), None, state)


def carryover(v, key, jurisdiction="federal"):
    return next(c for c in v["carryovers"][jurisdiction] if c["key"] == key)


# ---- carryovers: traced, flagged, never re-estimated (D30) ----------------------------------

def test_each_carryover_shows_where_it_came_from_and_where_it_goes(packet):
    v = view(packet)
    mtc = carryover(v, "minimum_tax_credit_from_2025_amt")
    assert mtc["by_version"] == {"v1": 3722, "v2": 3700, "v3": 3871} and mtc["out_2026"] == 3871
    assert mtc["lines"] == ["F6251.11"]
    short = carryover(v, "capital_loss_short")
    assert (short["in_2025"], short["out_2026"], short["lines"]) == (3200, 0, ["SchD.6", "SchD.14", "SchD.16"])
    assert carryover(v, "capital_loss", "california")["in_2025"] == 3200 + 11000
    assert carryover(v, "ridgeline_capital_account_end")["sources"] == ["ev-0970"]   # the K-1's ending capital


def test_open_corrections_under_a_carryover_flag_it_for_recomputing(packet):
    sep = carryover(view(packet), "sep_contribution_not_deductible_for_2025")
    assert sep["out_2026"] == 2786                     # the engine's figure stays; nothing is re-estimated
    assert "SchC.1" in sep["moved"]["open_corrections"] and sep["moved"]["why"].startswith("moved since the engine")
    assert carryover(view(packet), "scorp_stock_basis_end")["moved"] is None


def test_an_adjustment_under_a_carryover_flags_it(packet):
    adjust = ev("adjust", ["line:SchC.18"], reason="receipt",
                payload=adjustment_payload(project(packet, []), "SchC.18", 1000))
    sep = carryover(view(packet, [adjust]), "sep_contribution_not_deductible_for_2025")
    assert sep["moved"]["adjusted"] == ["SchC.18"] and sep["out_2026"] == 2786


def test_assets_carry_unless_disposed_of(packet):
    assets = {a["asset"]: a for a in view(packet)["assets"]}
    assert assets["SAC-BLDG"]["carried"] and not assets["AUS-BLDG"]["carried"]
    printer = next(d for d in view(packet)["carryovers"]["california_depreciation"] if d["asset"] == "STU-PRINTER")
    assert printer["difference"] == printer["federal_accumulated"] - printer["california_accumulated"]
    assert {a["amt_difference_2025"] for a in assets.values()} == {0.0}   # zero on every asset: the fact to carry


# ---- the 2026 estimates (D31, D32) -------------------------------------------------------------

def test_the_safe_harbor_is_110_percent_of_2025_tax_in_installments(packet):
    est = view(packet)["estimates"]
    assert (est["federal"]["base_total_tax_2025"], est["federal"]["annual"]) == (81962, 90158)
    assert [i["amount"] for i in est["federal"]["installments"]] == [22540, 22540, 22540, 22538]
    harbor = est["california"]["safe_harbor"]
    assert (harbor["annual"], [i["amount"] for i in harbor["installments"]]) == (20761, [6228, 8304, 6229])
    # No method chosen yet: the safe harbor and the overpay note, and nothing marked as the amount to pay.
    assert est["california"]["chosen"] is None and est["california"]["to_pay"] is None
    assert est["california"]["overpay_note"].startswith("This likely overpays")


def test_payment_corrections_move_the_balance_not_the_tax(packet):
    payment = ev("adjust", ["line:F1040.26"], reason="transcript",
                 payload=adjustment_payload(project(packet, []), "F1040.26", 12000))
    expense = ev("adjust", ["line:SchC.18"], reason="receipt",
                 payload=adjustment_payload(project(packet, []), "SchC.18", 1000))
    assert view(packet, [payment])["estimates"]["federal"]["base_total_tax_2025"] == 81962
    moved = view(packet, [expense])["estimates"]["federal"]["base_total_tax_2025"]
    assert moved == 81962 + expense.payload["effect"]["federal"]


# ---- built from the return as filed (D31, D33) -----------------------------------------------------

def test_the_opening_is_built_from_the_return_as_filed(client):
    before = client.get("/api/rollforward", headers=as_(PRIYA)).json()
    assert before["built_from"]["filed"] is False
    accepted(client)
    ok(act(client, HELEN, "open_amendment", ["return"], reason="later correction"))
    ok(act(client, PRIYA, "adjust", ["line:SchC.18"], {"to": 1000}, reason="receipt"))
    after = client.get("/api/rollforward", headers=as_(PRIYA)).json()
    assert after["built_from"]["filed"] is True and after["built_from"]["kind"] == "original"
    # The open amendment is not filed yet, so 2026 still starts from what was filed.
    assert after["estimates"]["federal"]["base_total_tax_2025"] == before["estimates"]["federal"]["base_total_tax_2025"]


def test_the_california_method_is_decided_after_filing_and_shown(client):
    accepted(client)
    assert filing(client)["frozen"] is True
    r = act(client, PRIYA, "judgment_call", ["finding:SSN_MISMATCH:theo"], {"decision": "x", "authority": "y"}, reason="r")
    assert r.status_code == 422 and "frozen" in r.json()["refused"][0]          # the filed return stays frozen
    ok(act(client, DANIEL, "judgment_call", [PLAN_CALIFORNIA],
           {"method": "projected", "projected_2026_tax": 6000,
            "decision": "Pay 90% of projected 2026 California tax", "authority": "R&TC 19136.3"},
           reason="only the Sacramento rental and Ridgeline's share are California income in 2026"))
    california = client.get("/api/rollforward", headers=as_(PRIYA)).json()["estimates"]["california"]
    chosen = california["chosen"]
    assert (chosen["by"], chosen["projected_2026_tax"], chosen["annual"]) == (DANIEL, 6000, 5400)
    assert [i["amount"] for i in chosen["installments"]] == [1620, 2160, 1620]      # 30/40/30 of 90% of 6,000
    assert california["to_pay"] == "projected" and california["overpay_note"] is None
    assert california["safe_harbor"]["annual"] == 20761                              # still shown beside it


def test_the_90_percent_method_needs_the_projected_tax(client):
    base = {"decision": "Pay 90%", "authority": "R&TC 19136.3"}
    for payload, expect in [({**base, "method": "projected"}, "needs the projected 2026 California tax"),
                            ({**base, "method": "projected", "projected_2026_tax": "a lot"}, "must be a real amount"),
                            ({**base, "method": "projected", "projected_2026_tax": -5}, "needs the projected"),
                            ({**base}, "Choose the method")]:
        r = act(client, PRIYA, "judgment_call", [PLAN_CALIFORNIA], payload, reason="r")
        assert r.status_code == 422 and any(expect in x for x in r.json()["refused"]), payload


def test_choosing_the_safe_harbor_marks_it_to_pay_and_keeps_the_note(client):
    ok(act(client, PRIYA, "judgment_call", [PLAN_CALIFORNIA],
           {"method": "safe_harbor", "decision": "Pay the 110% safe harbor", "authority": "R&TC 19136.3"}, reason="certainty"))
    california = client.get("/api/rollforward", headers=as_(PRIYA)).json()["estimates"]["california"]
    assert california["to_pay"] == "safe_harbor" and california["chosen"]["annual"] == 20761
    assert california["overpay_note"] is not None


def test_the_export_is_one_masked_file(client):
    r = client.get("/api/rollforward/export", headers=as_(PRIYA))
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "<script" not in r.text and not re.findall(r"\b\d{3}-\d{2}-\d{4}\b", r.text)
    assert "Out to 2026" in r.text and "<td class='n'>3871</td>" in r.text   # the Form 8801 credit carried
    # The flag names the lines that moved under it, in the file itself (D34), and each asset carries its AMT difference.
    assert re.search(r"moved since the engine computed it: recompute \(open corrections: [^)]*SchC\.1\b", r.text)
    assert "AMT difference 2025" in r.text and "No method chosen yet" in r.text


def test_a_decision_without_a_method_sets_no_amount(packet):
    # A judgment recorded before methods were required (or written straight to the log) names no method.
    legacy = ev("judgment_call", [PLAN_CALIFORNIA], actor=DANIEL, role="reviewer",
                payload={"decision": "90% of projected 2026 California-source tax", "authority": "R&TC 19136.3"})
    california = view(packet, [legacy])["estimates"]["california"]
    assert california["chosen"] is None and california["to_pay"] is None and california["overpay_note"]


# ---- the review's findings: numbers that are not real amounts, and lots the engine never had ----

def test_a_number_that_is_not_a_real_amount_is_refused_and_nothing_is_stored(client):
    tip = client.get("/api/me", headers=as_(PRIYA)).json()["tip"]
    plan = '{"action": "judgment_call", "targets": ["%s"], "reason": "r", "base_tip": %d, "payload": ' % (PLAN_CALIFORNIA, tip)
    bodies = [
        plan + '{"method": "projected", "projected_2026_tax": 1e999, "decision": "d", "authority": "a"}}',      # infinity
        plan + '{"method": "projected", "projected_2026_tax": 1%s, "decision": "d", "authority": "a"}}' % ("0" * 400),
        '{"action": "adjust", "targets": ["line:SchC.18"], "reason": "r", "base_tip": %d, "payload": {"to": 1e999}}' % tip,
        '{"action": "log_time", "targets": ["time:business"], "base_tip": %d, "payload": {"hours": 1e999}}' % tip,
    ]
    for body in bodies:
        r = client.post("/api/actions", headers={**as_(PRIYA), "Content-Type": "application/json"}, content=body)
        assert r.status_code == 422 and "real amount" in r.json()["refused"][0], body[:60]
    r = client.post("/api/actions", headers={**as_(JO), "Content-Type": "application/json"}, content=(
        '{"action": "set_standard", "targets": [], "reason": "r", "base_tip": %d, '
        '"payload": {"path": "variance_review.and_over_amount", "value": 1e999}}' % tip))
    assert r.status_code == 422
    assert client.get("/api/me", headers=as_(PRIYA)).json()["tip"] == tip           # nothing was stored
    assert client.get("/api/rollforward", headers=as_(PRIYA)).status_code == 200


@pytest.mark.parametrize("payload,expect", [
    ({"method": "projected", "projected_2026_tax": 6000.5}, "in whole dollars"),   # no arithmetic that does not add up
    ({"method": ["projected"], "projected_2026_tax": 5}, "method must be text"),    # a list is refused, not a 500
    ({"method": {}, "projected_2026_tax": 5}, "method must be text"),
])
def test_the_california_method_is_checked_for_shape(client, payload, expect):
    r = act(client, PRIYA, "judgment_call", [PLAN_CALIFORNIA], {**payload, "decision": "d", "authority": "a"}, reason="r")
    assert r.status_code == 422 and any(expect in x for x in r.json()["refused"])


def test_a_lot_the_engine_never_had_is_named_under_the_carryovers_it_feeds(packet, result):
    # The missing page-32 lot and the C6 lot in box K are open corrections on lines not on the return.
    short = carryover(view(packet), "capital_loss_short")
    assert {"F8949.B.M18", "F8949.K.C6"} <= set(short["moved"]["open_corrections"])
    adds = result.proposed_line("F8949.B.M18")
    added = ev("adjust", ["line:F8949.B.M18"], reason="lot M18",
               payload=adjustment_payload(project(packet, []), "F8949.B.M18", -60.0, "PAGE_NOT_READ:D31#page32", adds=adds))
    assert "F8949.B.M18" in carryover(view(packet, [added]), "capital_loss_short")["moved"]["adjusted"]
