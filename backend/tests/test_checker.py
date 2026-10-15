"""Every error in docs/ERRORS.md is found by the checker, with the tax effect ERRORS.md gives.

The tests are the answer key; the rules are not. The rules never name a packet id
(see test_rules_do_not_name_packet_ids at the bottom).
"""

import ast
import re
from pathlib import Path

import pytest

from workpaper.checker import RULES, run_checker
from workpaper.project import project

from conftest import ev, find, log

# ---- errors with a dollar effect (ERRORS.md summary table) ---------------------

DOLLAR_ERRORS = [
    # error, rule, a ref the finding must point at, federal effect, California effect
    ("E1",  "R04", "line:F8949.B.N1",       -15536, -2445),
    ("E2",  "R08", "line:SchCA540NR.1.E",        0, -5685),
    ("E3",  "R03", "line:SchC.1",            -4402,  -384),
    ("E4",  "R07", "line:Sch1.17",            4464,   605),
    ("E5",  "R07", "line:F8283.A1.vehicle",    806,   149),
    ("E6",  "R02", "line:SchC.9",              919,    80),
    ("E7",  "R08", "line:SchA.5b",            1462,   332),
    ("E8",  "R03", "line:SchA.8a",             559,   103),
    ("E9",  "R11", "line:SchE.14A",           3364,   694),
    ("E10", "R03", "line:SchB.1.1",           -640,  -127),
    ("E11", "R09", "line:SchB.1.6",             43,     9),
    ("E12", "R05", "line:F1040.26",           1000,     0),
    ("E13", "R05", "line:F540NR.72",             0,  3500),
    ("E14", "R13", "line:F8949.H.C6",        -1312,  -195),
    ("E15", "R06", "doc:D31#page32",           -21,     0),
    ("E21", "R07", "line:SchC.25",             541,    47),
]


@pytest.mark.parametrize("error,rule,ref,federal,california", DOLLAR_ERRORS, ids=[e[0] for e in DOLLAR_ERRORS])
def test_dollar_errors_are_found_with_their_tax_effect(result, error, rule, ref, federal, california):
    f = find(result, rule, ref)
    assert f.status == "open"
    assert f.changes, f"{error}: the finding should propose a change"
    assert (f.effect.federal, f.effect.california) == (federal, california)
    assert f.effect.estimate  # the UI must label it an estimate


def test_net_effect_matches_errors_md(result):
    # ERRORS.md: net (approximate) -8,753 federal, -3,317 California.
    assert (result.net_effect["federal"], result.net_effect["california"]) == (-8753, -3317)


# ---- details that make each finding useful, not just present --------------------

def test_e1_rsu_lots_are_matched_to_the_supplement(result):
    f = find(result, "R04", "line:F8949.B.N1")
    assert {"line:F8949.B.N1", "line:F8949.B.N3", "line:F8949.E.N4"} <= set(f.targets)
    assert "D11" in f.evidence
    assert "W-2 box 14 RSU 38,200 agrees" in f.message


def test_e2_uses_the_paystub_at_the_move(result):
    f = find(result, "R08", "line:SchCA540NR.1.E")
    assert "22,469" in f.message and "TX" in f.message
    assert {"qa-45", "ev-1081"} <= set(f.evidence)


def test_e3_quotes_the_books_deposit_detail(result):
    f = find(result, "R03", "line:SchC.1")
    assert "D15 page 3" in f.message
    assert f.changes[0].proposed == 151300


def test_e6_duplicate_page_and_miles(result):
    f = find(result, "R02", "line:SchC.44a")
    assert [(c.line, c.proposed) for c in f.changes] == [("SchC.44a", 8100), ("SchC.9", 5670)]


def test_e12_names_the_client_guess(result):
    f = find(result, "R05", "line:F1040.26")
    assert "qa-41" in f.evidence
    assert "3,000 on 2026-01-15" in f.message


def test_e13_is_also_a_tax_year_conflict(result):
    f = find(result, "R08", "line:F540NR.72")
    assert "tax year 2024" in f.message
    assert "ev-1076" in f.targets


def test_e14_drafts_the_long_term_lot(result):
    f = find(result, "R13", "line:F8949.H.C6")
    assert [(c.line, c.proposed) for c in f.changes] == [("F8949.H.C6", None), ("F8949.K.C6", 2275.0)]
    assert "a person must decide" in f.message


def test_e15_explains_the_broker_summary_gap(result):
    f = find(result, "R06", "doc:D31#page32")
    assert "M18" in f.message and "this page is the difference" in f.message
    assert f.severity == "error"


def test_e21_business_shares(result):
    f = find(result, "R07", "line:SchC.25")
    assert f.details["disallowed"] == {"Telephone": 648.0, "Internet": 660.0, "Software and subscriptions": 216.0}


# ---- errors with no direct dollar effect ---------------------------------------

def test_e16_care_provider_ein_misread(result):
    f = find(result, "R01", "ev-1045")
    assert "74-3829156" in f.message           # what the page prints
    assert "line:F2441.1b" in f.targets        # where the wrong value landed
    assert result.by_id("R01:F2441.1b:tin").details["on_document"] == ["74-3829156"]  # the form prints it too


def test_e17_theo_ssn(result, packet):
    f = find(result, "R12", "household:theo")
    assert {"doc:D71#page1", "doc:D06#page1", "agency:/efile/0"} <= set(f.evidence)
    assert "666-74" not in f.message  # messages show only the last four digits


def test_e17_was_catchable_before_the_efile_rejection(packet):
    march = run_checker(packet, project(packet, [], as_of="2026-03-01T00:00:00Z"))
    f = find(march, "R12", "household:theo")
    assert f.evidence == ["doc:D06#page1"]  # last year's return already printed the right number


def test_e18_duplicate_w2(result):
    f = find(result, "R02", "D10")
    assert f.details["duplicate_of"] == "D09"
    assert f.details["lines_using_copy"] == []


def test_e19_corrected_1099_supersedes(result):
    f = find(result, "R02", "D30")
    diffs = {d["field"]: (d["old"], d["new"]) for d in f.details["differences"]}
    assert diffs["M9_basis"] == (6900.0, 4880.0)
    assert diffs["M6_wash"] == (735.0, 512.0)
    assert diffs["M14_term"] == ("short", "long")
    assert f.details["engine_switched_in"] == "v2"


def test_e20_church_receipt(result):
    assert "1,500 does not appear" in find(result, "R01", "ev-1049").message
    assert find(result, "R11", "ev-1049").title.startswith("Gift of 250 or more")
    assert "line:SchA.11" in find(result, "R13", "msg-08").targets


def test_e29_provider_name(result):
    f = find(result, "R01", "line:F2441.1a")
    assert f.details == {"on_return": "Bright Oak Preschool", "on_document": "Bright Oak Kids Club"}
    assert "py:/return_2024/lines/F2441.provider" in f.evidence


def test_exactly_eleven_values_are_not_on_their_page(result):
    off_page = [f for f in result.findings if f.rule == "R01" and f.id.startswith("R01:ev-")]
    assert len(off_page) == 11


# ---- client answers that conflict with documents --------------------------------

@pytest.mark.parametrize("answer,expect", [("qa-14", "282 sales"), ("qa-15", "12 sales"), ("qa-31", "7,000 of basis")])
def test_client_answers_contradicted(result, answer, expect):
    assert expect in find(result, "R07", answer).message


def test_documents_without_extraction_need_a_disposition(result):
    for doc in ("D07", "D69", "D70", "D72"):
        assert find(result, "R06", doc).kind == "open_item"


def test_variances_over_the_firm_standard(result):
    flagged = {f.targets[0] for f in result.findings if f.rule == "R10"}
    assert {"line:SchC.44a", "line:Sch1.17", "line:SchC.1", "line:SchB.1.2"} <= flagged
    assert "Erik was covered on Ngozi's employer plan" in find(result, "R10", "line:Sch1.17").message


# ---- things that look wrong but are right --------------------------------------

def test_what_ties_is_recorded(result):
    ties = {r.get("document") or r.get("line") for r in result.reconciliations}
    assert {"D74", "D34", "Sch3.10"} <= ties
    brightpath = next(r for r in result.reconciliations if r.get("document") == "D74")
    assert (brightpath["lots"], brightpath["summary_proceeds"]) == (260, 334728.52)


def test_the_machine_never_says_verified(result):
    assert set(result.value_states.values()) <= {"ties", "disagreement", "conflict", "not_read"}
    assert all(f.kind != "verified" for f in result.findings)


# ---- findings are derived: a person's act changes the next run ------------------

def test_fixing_the_number_clears_the_finding(packet):
    events = log(ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000, "finding": "R05:F1040.26"},
                    reason="Agreed to IRS transcript"))
    after = run_checker(packet, project(packet, events))
    assert after.by_id("R05:F1040.26") is None
    assert {"check": "R05", "line": "F1040.26", "status": "ties"}.items() <= next(
        r for r in after.reconciliations if r.get("line") == "F1040.26").items()


def test_disposition_addresses_the_duplicate(packet):
    events = log(ev("disposition", ["D10"], payload={"disposition": "duplicate", "of": "D09"}, reason="phone photo of D09"))
    f = run_checker(packet, project(packet, events)).by_id("R02:D10")
    assert (f.status, f.addressed_by) == ("addressed", 1)


def test_judgment_call_addresses_a_finding_and_undo_reopens_it(packet):
    judgment = ev("judgment_call", ["finding:R13:msg-07"], payload={"decision": "accept 3,050 basis",
                  "authority": "Treas. Reg. 1.1012-1"}, reason="bank statement supports the purchase")
    addressed = run_checker(packet, project(packet, log(judgment))).by_id("R13:msg-07")
    assert addressed.status == "addressed"
    undone = run_checker(packet, project(packet, log(judgment, ev("undo", ["event:1"])))).by_id("R13:msg-07")
    assert undone.status == "open"


# ---- the ground rule ------------------------------------------------------------

PACKET_ID = re.compile(r"\b(D\d{2}|ev-\d{4}|qa-\d{2}|msg-\d{2}|call-\d{2}|st-\d{2}|cu-\d{2})\b")


def test_rules_do_not_name_packet_ids():
    """A rule may know tax forms (Sch1.17, box 16, Form 1098-C) but never this packet's ids.
    Docstrings may cite the errors they catch; code may not."""
    checker_dir = Path(__file__).resolve().parents[1] / "workpaper" / "checker"
    offenders = []
    for path in sorted(checker_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                      and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if PACKET_ID.search(node.value):
                    offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert offenders == []


def test_every_rule_produces_findings(result):
    assert {f.rule for f in result.findings} == set(RULES)
