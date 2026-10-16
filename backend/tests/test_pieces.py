"""Answering a finding, piece by piece (D37).

A finding's correction is made of pieces, each measured from the engine's figure. A piece is applied
when its line now shows it; a finding is addressed when all its deciding pieces are. Only an
adjustment or a judgment call answers a finding: asking the client or attaching a file does not.
These were found by the fact-check of the hand-in write-ups.
"""

import pytest
from fastapi.testclient import TestClient

from workpaper.api import create_app

from test_filing import DANIEL, HELEN, PRIYA, act, as_, ok

E1 = "SUPPLEMENT_BASIS_UNUSED:D11"
E6 = "DUPLICATE_PAGE:D23#page3"
E7 = "CLOSING_PRORATION_NOT_APPLIED:SchA.5b:D54"
E9 = "REPAIR_LOOKS_LIKE_IMPROVEMENT:SchE.14A:D47"
E13_FTB = "ESTIMATES_VS_FTB_ACCOUNT:F540NR.72"
E13_YEAR = "TAX_YEAR_FIELD_CONFLICT:F540NR.72:ev-1076"
E21 = "CLIENT_BUSINESS_SHARE:call-01"
STALE = "STALE_REFERENCE:SchB.1.6"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "workpaper.db", heartbeat_seconds=0.05)) as c:
        yield c


def findings(client):
    data = client.get("/api/findings", headers=as_(PRIYA)).json()
    return {f["id"]: f for f in data["findings"]}, data["net_effect"]


def fix(client, finding, line, to=None):
    """Save the card's fix for one line (its figure unless `to` is given)."""
    card = findings(client)[0][finding]
    chosen = next(x for x in card["fixes"] if x["line"] == line)
    return ok(act(client, PRIYA, "adjust", [f"line:{line}"], {"to": chosen["to"] if to is None else to, "finding": finding},
                  reason="per the card"))["event"]


# ---- only an adjustment or a judgment call answers a finding ---------------------------------------

def test_asking_or_attaching_does_not_close_a_finding(client):
    _, before = findings(client)
    ok(act(client, PRIYA, "question", [f"finding:{STALE}", "line:SchB.1.6"], {"to": "client", "text": "Which rate?"}))
    r = client.post("/api/attachments", headers=as_(PRIYA), data={"targets": f"finding:{E21}", "base_tip": "1"},
                    files={"file": ("call.txt", b"call notes", "text/plain")})
    assert r.status_code == 200
    found, after = findings(client)
    assert found[STALE]["status"] == "open" and found[E21]["status"] == "open"
    assert (after["federal"], after["california"]) == (before["federal"], before["california"])


# ---- one fix per line, with the pieces on that line combined ----------------------------------------

def test_the_card_offers_one_fix_per_line(client):
    found, _ = findings(client)
    lines = lambda fid: [(x["line"], x["to"]) for x in found[fid]["fixes"]]   # noqa: E731
    assert lines(E1) == [("F8949.B.N1", 140.0), ("F8949.B.N3", -620.0), ("F8949.E.N4", 5880.0)]
    assert lines(E21) == [("SchC.25", 2172.0), ("SchC.27a.1", 6634.0)]     # phone and internet: one figure
    assert lines(E6) == [("SchC.44a", 8100), ("SchC.9", 5670)]
    assert lines(E7) == [("SchA.5b", 6508.0)]                               # SchA.5d and 5e only follow


def test_a_finding_is_addressed_only_when_every_piece_is_applied(client):
    _, start = findings(client)
    first = fix(client, E1, "F8949.B.N1")
    found, net = findings(client)
    card = found[E1]
    assert card["status"] == "open" and [c["applied_by"] for c in card["changes"]] == [first["id"], None, None]
    assert net["federal"] == start["federal"] + 6647          # only N1's estimated dollars leave the open total
    assert [x["line"] for x in card["fixes"]] == ["F8949.B.N3", "F8949.E.N4"]
    fix(client, E1, "F8949.B.N3")
    last = fix(client, E1, "F8949.E.N4")
    found, net = findings(client)
    assert (found[E1]["status"], found[E1]["addressed_by"]) == ("addressed", last["id"])
    assert net["federal"] == start["federal"] + 15536 and found[E1]["fixes"] == []


def test_a_fix_made_on_the_line_page_is_not_counted_twice(client):
    _, start = findings(client)
    ok(act(client, PRIYA, "adjust", ["line:F8949.B.N3"], {"to": -620}, reason="supplemental basis"))
    found, net = findings(client)
    n3 = next(c for c in found[E1]["changes"] if c["line"] == "F8949.B.N3")
    assert n3["applied_by"] is not None and net["federal"] == start["federal"] + 6647


def test_part_of_a_line_can_be_applied_and_the_rest_stays_open(client):
    ok(act(client, PRIYA, "adjust", ["line:SchC.25"], {"to": 2832}, reason="phone 70% business"))   # phone only
    found, _ = findings(client)
    pieces = [(c["to"], bool(c["applied_by"])) for c in found[E21]["changes"] if c["line"] == "SchC.25"]
    assert pieces == [(2832.0, True), (2820.0, False)]
    assert [(x["line"], x["from"], x["to"]) for x in found[E21]["fixes"]][0] == ("SchC.25", 2832, 2172.0)


def test_a_different_figure_made_for_the_finding_answers_that_line(client):
    # The person decides: the card's figure is a proposal, not an order.
    fix(client, E21, "SchC.25", to=2500)
    found, _ = findings(client)
    assert all(c["applied_by"] for c in found[E21]["changes"] if c["line"] == "SchC.25")
    assert [x["line"] for x in found[E21]["fixes"]] == ["SchC.27a.1"]


def test_undoing_a_fix_reopens_its_piece(client):
    event = fix(client, E1, "F8949.B.N1")
    ok(act(client, DANIEL, "undo", [f"event:{event['id']}"], reason="wrong lot"))
    found, _ = findings(client)
    assert all(c["applied_by"] is None for c in found[E1]["changes"])


# ---- a card fix stores the card's estimate ---------------------------------------------------------

@pytest.mark.parametrize("finding,line,card", [
    (E7, "SchA.5b", (1462, 332)),    # the SALT cap crossing, which the line's own rate misses
    (E9, "SchE.14A", (3364, 694)),   # with the first-year depreciation and the California-source rate
])
def test_a_card_fix_stores_the_cards_estimate(client, finding, line, card):
    found, _ = findings(client)
    assert (found[finding]["fixes"][0]["effect"]["federal"], found[finding]["fixes"][0]["effect"]["california"]) == card
    to = found[finding]["fixes"][0]["to"]
    preview = client.get(f"/api/estimate?line={line}&to={to}", headers=as_(PRIYA)).json()["effect"]
    assert (preview["federal"], preview["california"]) == card
    stored = fix(client, finding, line)["payload"]["effect"]
    assert (stored["federal"], stored["california"]) == card
    assert findings(client)[0][finding]["status"] == "addressed"


def test_the_same_figure_from_the_line_page_stores_the_same_estimate(client):
    stored = ok(act(client, PRIYA, "adjust", ["line:SchA.5b"], {"to": 6508}, reason="seller's share"))["event"]
    assert (stored["payload"]["effect"]["federal"], stored["payload"]["effect"]["california"]) == (1462, 332)


# ---- two findings on the same dollars: fixing one answers both ---------------------------------------

def test_the_tax_year_card_is_answered_by_the_ftb_fix(client):
    _, start = findings(client)
    fix(client, E13_FTB, "F540NR.72")
    found, net = findings(client)
    assert found[E13_FTB]["status"] == "addressed" and found[E13_YEAR]["status"] == "addressed"
    assert found[E13_YEAR]["fixes"] == []                     # no second fix that would remove a valid payment
    assert net["california"] == start["california"] - 3500     # the 3,500 leaves the open total once


# ---- the line-level model: what the review of the first design found --------------------------------
E5 = "SAME_MONEY_TWO_SOURCES:SchC.1:D21"
E8 = "ANSWER_BARS_DEDUCTION:Sch1.17"
E12 = "ESTIMATES_VS_TRANSCRIPT:F1040.26"
E14 = "EVIDENCE_AFTER_COMPUTATION:msg-07"
EXTENSION = "EXTENSION_VS_TRANSCRIPT:Sch3.10"


def adjust(client, line, to, finding=None):
    payload = {"to": to, **({"finding": finding} if finding else {})}
    return ok(act(client, PRIYA, "adjust", [f"line:{line}"], payload, reason="per the documents"))["event"]


def accept(client, finding):
    return ok(act(client, DANIEL, "judgment_call", [f"finding:{finding}"],
                  {"decision": "leave the rest as is", "authority": "firm rule 4"}, reason="reviewed"))["event"]


def stored(event):
    return event["payload"]["effect"]["federal"], event["payload"]["effect"]["california"]


def test_a_different_figure_for_one_card_answers_both_findings_on_the_same_dollars(client):
    adjust(client, "F540NR.72", 11000, finding=E13_FTB)       # the person's figure, not the card's 10,500
    found, _ = findings(client)
    assert found[E13_FTB]["status"] == "addressed" and found[E13_YEAR]["status"] == "addressed"


def test_a_fix_moved_away_later_reopens_the_line(client):
    _, start = findings(client)
    first = adjust(client, "SchC.25", 2500, finding=E21)
    later = adjust(client, "SchC.25", 3000)                    # a line-page adjustment, for no finding
    found, net = findings(client)
    assert all(c["applied_by"] is None for c in found[E21]["changes"] if c["line"] == "SchC.25")
    # What is open on the line is the card's estimate less what the two adjustments stored.
    left = 464 - stored(first)[0] - stored(later)[0]
    assert net["federal"] == start["federal"] - 464 + left
    fx = next(x for x in found[E21]["fixes"] if x["line"] == "SchC.25")
    assert (fx["from"], fx["to"], fx["effect"]["federal"]) == (3000, 2172.0, left)


@pytest.mark.parametrize("finding,line,first,card", [
    (E7, "SchA.5b", 9000, (1462, 332)),
    (E8, "Sch1.17", 7200, (4464, 605)),                        # a figure set to 0, after half of it
    (E12, "F1040.26", 12500, (1000, 0)),                       # payments: the agency's figure
])
def test_after_a_partial_adjustment_the_card_finishes_the_line(client, finding, line, first, card):
    _, start = findings(client)
    one = adjust(client, line, first)
    found, net = findings(client)
    fx = found[finding]["fixes"][0]
    assert fx["to"] == next(c["to"] for c in found[finding]["changes"] if c["line"] == line)   # the documented figure
    assert fx["from"] == first
    two = fix(client, finding, line)
    assert tuple(a + b for a, b in zip(stored(one), stored(two))) == card    # the two add up to the card
    found, end = findings(client)
    assert found[finding]["status"] == "addressed"
    # The headline adds the open pieces exactly and rounds once, so taking one out can move it by a dollar.
    assert abs(end["federal"] - (start["federal"] - card[0])) <= 1
    assert abs(end["california"] - (start["california"] - card[1])) <= 1


def test_a_large_remainder_reaches_the_partner(client):
    adjust(client, "SchA.5b", 13000)                           # a small first step, under the threshold
    two = fix(client, E7, "SchA.5b")
    assert two["payload"]["effect"]["federal"] > 1000
    trace = client.get("/api/lines/SchA.5b", headers=as_(PRIYA)).json()
    assert [a["needs_partner"] for a in trace["adjustments"]] == [False, True]


def test_a_line_that_only_follows_stores_no_effect(client):
    fix(client, E7, "SchA.5b")
    _, before = findings(client)
    follow = adjust(client, "SchA.5d", 34378)
    assert stored(follow) == (0, 0)
    _, after = findings(client)
    assert (after["federal"], after["california"]) == (before["federal"], before["california"])


def test_a_card_fix_shows_no_fresh_estimate_on_the_line_page(client):
    fix(client, E9, "SchE.14A")
    trace = client.get("/api/lines/SchE.14A", headers=as_(PRIYA)).json()
    assert [a["effect"]["differs"] for a in trace["adjustments"]] == [False]


def test_an_adjustment_must_change_the_figure(client):
    r = act(client, PRIYA, "adjust", ["line:SchC.1"], {"to": 163700, "finding": E5}, reason="no change")
    assert r.status_code == 422 and "already shows" in " ".join(r.json()["refused"])
    assert findings(client)[0][E5]["status"] == "open"


def test_accepting_a_partly_fixed_finding_covers_only_what_was_open(client):
    _, start = findings(client)
    n1 = fix(client, E1, "F8949.B.N1")
    judgment = accept(client, E1)
    assert judgment["payload"]["effect"]["federal"] == -6647 - 2242                 # N3 and N4, left as they are
    assert judgment["payload"]["figures"][E1] == {"F8949.B.N1": 140.0, "F8949.B.N3": 18480.0, "F8949.E.N4": 15300.0}
    found, net = findings(client)
    assert found[E1]["status"] == "accepted"
    assert [bool(c["applied_by"]) for c in found[E1]["changes"]] == [True, False, False]   # the tag stays
    assert found[E1]["effect"]["federal"] == -6647 - 2242      # what was left out: N3 and N4
    # Undo the N1 fix: the acceptance saw N1 at 140, so it no longer holds and all the dollars are open again.
    ok(act(client, DANIEL, "undo", [f"event:{n1['id']}"], reason="wrong lot"))
    found, net = findings(client)
    assert found[E1]["status"] == "open" and found[E1]["details"]["acceptance_changed"]["lines"] == ["F8949.B.N1"]
    assert net["federal"] == start["federal"]


@pytest.mark.parametrize("finding,line,moved_to", [
    (E8, "Sch1.17", 100),          # the line moved most of the way before the acceptance
    (E21, "SchC.25", 2832),        # one of the line's two pieces shown before the acceptance
    (E9, "SchE.14A", 3000),        # an acceptance that would have reached the partner
])
def test_undoing_a_move_made_before_an_acceptance_reopens_the_finding(client, finding, line, moved_to):
    _, start = findings(client)
    move = adjust(client, line, moved_to)
    accept(client, finding)
    ok(act(client, DANIEL, "undo", [f"event:{move['id']}"], reason="not yet"))
    found, net = findings(client)
    assert found[finding]["status"] == "open" and found[finding]["details"]["acceptance_changed"]["lines"] == [line]
    assert (net["federal"], net["california"]) == (start["federal"], start["california"])


def test_correcting_an_accepted_line_answers_the_finding(client):
    accept(client, E7)
    adjust(client, "SchA.5b", 6508)
    assert findings(client)[0][E7]["status"] == "addressed"


def test_a_finding_already_answered_cannot_be_accepted(client):
    stale = client.get("/api/me", headers=as_(DANIEL)).json()["tip"]
    fixed = fix(client, E7, "SchA.5b")
    r = act(client, DANIEL, "judgment_call", [f"finding:{E7}"], {"decision": "as is", "authority": "firm rule 4"},
            reason="from a stale card", base_tip=stale)
    assert r.status_code == 422 and f"already addressed (event {fixed['id']})" in " ".join(r.json()["refused"])
    accept(client, E1)
    r = act(client, PRIYA, "judgment_call", [f"finding:{E1}"], {"decision": "again", "authority": "firm rule 4"}, reason="r")
    assert r.status_code == 422 and "already accepted" in " ".join(r.json()["refused"])


def test_landing_after_a_fix_at_another_figure_stores_the_rest(client):
    first = adjust(client, "SchA.5b", 9000, finding=E7)       # the person's own figure, for the finding
    preview = client.get("/api/estimate?line=SchA.5b&to=6508", headers=as_(PRIYA)).json()["effect"]
    second = adjust(client, "SchA.5b", 6508)                   # then the documented figure, from the line page
    assert (preview["federal"], preview["california"]) == stored(second)
    assert tuple(a + b for a, b in zip(stored(first), stored(second))) == (1462, 332)
    trace = client.get("/api/lines/SchA.5b", headers=as_(PRIYA)).json()
    assert [a["needs_partner"] for a in trace["adjustments"]] == [False, True]


def test_the_corrected_figure_is_the_one_the_card_offers(client):
    adjust(client, "SchC.25", 3000)
    adjust(client, "Sch3.10", 30000)
    found = client.get("/api/findings", headers=as_(PRIYA)).json()
    corrected = found["corrected_lines"]
    assert (corrected["SchC.25"]["original"], corrected["SchC.25"]["corrected"]) == (3000, 2172.0)
    assert (corrected["Sch3.10"]["original"], corrected["Sch3.10"]["corrected"]) == (30000, 36000)


def test_a_line_page_fix_of_the_crypto_lot_is_not_counted_twice(client):
    _, start = findings(client)
    move = adjust(client, "F8949.H.C6", 2275)                  # the long-term gain, kept in box H
    found, net = findings(client)
    assert found[E14]["status"] == "open" and found[E14]["fixes"] == []   # moving the lot to box K is not a figure
    assert found[E14]["effect"]["federal"] == -1312 - stored(move)[0]   # only the rest stays open
    assert net["federal"] == start["federal"] - stored(move)[0]   # -1,312 left the open total; the rest is back in it


def test_moving_a_tied_payment_line_off_the_agency_record_is_a_finding(client):
    _, start = findings(client)
    assert EXTENSION not in findings(client)[0]
    move = adjust(client, "Sch3.10", 30000)
    found, net = findings(client)
    card = found[EXTENSION]
    assert card["status"] == "open" and "now shows 30,000" in card["message"]
    assert (card["fixes"][0]["from"], card["fixes"][0]["to"]) == (30000, 36000)
    assert card["effect"]["federal"] == -stored(move)[0]           # putting it back reverses what was stored
    assert net["federal"] == start["federal"] - stored(move)[0]
    fix(client, EXTENSION, "Sch3.10")
    assert EXTENSION not in findings(client)[0]


def test_the_ira_basis_check_reads_the_figure_on_the_return(client):
    rows = lambda: [f for f in findings(client)[0].values() if f["code"] == "ANSWER_VS_PRIOR_YEAR"]   # noqa: E731
    assert [f["severity"] for f in rows()] == ["info"]
    adjust(client, "F8606.2", 0)
    assert [f["severity"] for f in rows()] == ["error"]


def test_a_corrected_line_no_longer_flags_its_finding(client):
    fix(client, E1, "F8949.B.N1")
    trace = client.get("/api/lines/F8949.B.N1", headers=as_(PRIYA)).json()
    assert E1 not in trace["line"]["findings"]
    trace = client.get("/api/lines/F8949.B.N3", headers=as_(PRIYA)).json()
    assert E1 in trace["line"]["findings"]


# ---- the second design's review: priced figures, followers, the same dollars accepted -----------------

@pytest.mark.parametrize("finding,line,card", [(E7, "SchA.5b", (1462, 332)), (E9, "SchE.14A", (3364, 694))])
def test_a_round_trip_nets_to_nothing_and_a_refix_stores_the_card(client, finding, line, card):
    _, start = findings(client)
    there = fix(client, finding, line)
    back = adjust(client, line, next(c["from"] for c in findings(client)[0][finding]["changes"]))   # the engine's figure
    assert tuple(-x for x in stored(back)) == stored(there)
    found, net = findings(client)
    assert found[finding]["effect"]["federal"] == card[0] and (net["federal"], net["california"]) == (start["federal"], start["california"])
    again = fix(client, finding, line)
    ok(act(client, DANIEL, "undo", [f"event:{there['id']}"], reason="redo"))     # the first fix and its reversal drop out
    trace = client.get(f"/api/lines/{line}", headers=as_(PRIYA)).json()
    assert [a["event"] for a in trace["adjustments"] if a["applied"]] == [again["id"]]
    assert stored(again) == card and findings(client)[0][finding]["status"] == "addressed"


def test_a_line_that_only_follows_always_sums_to_nothing(client):
    step = adjust(client, "SchA.5d", 37834)                    # half way, at the line's own rate
    landing = adjust(client, "SchA.5d", 34378)                 # its documented figure: the reverse of the step
    assert tuple(a + b for a, b in zip(stored(step), stored(landing))) == (0, 0)
    back = adjust(client, "SchA.5d", 41290)                    # back to the engine's figure: nothing again
    assert stored(back) == (0, 0)
    assert stored(fix(client, E7, "SchA.5b")) == (1462, 332)


def test_accepting_one_of_two_findings_on_the_same_dollars_answers_both_once(client):
    _, start = findings(client)
    judgment = accept(client, E13_YEAR)                        # the card whose piece is counted on the FTB card
    assert (judgment["payload"]["effect"]["federal"], judgment["payload"]["effect"]["california"]) == (0, 3500)
    found, net = findings(client)
    assert found[E13_FTB]["status"] == "accepted" and found[E13_YEAR]["status"] == "accepted"
    assert net["california"] == start["california"] - 3500
    release = client.get("/api/return", headers=as_(HELEN)).json()["release_will_approve"]["acceptances"]
    assert [(a["id"], a["california"]) for a in release] == [(E13_YEAR, 3500)]
    r = act(client, DANIEL, "judgment_call", [f"finding:{E13_FTB}"], {"decision": "as is", "authority": "rule"}, reason="r")
    assert r.status_code == 422 and "already accepted" in " ".join(r.json()["refused"])


def test_the_tax_year_card_says_what_accepting_it_leaves_out(client):
    card = findings(client)[0][E13_YEAR]
    assert card["effect"] is None                              # its dollars are counted on the FTB card
    assert (card["accept_effect"]["california"], card["partner_if_accepted"]) == (3500, True)


def test_a_judgment_must_name_a_finding_on_the_return_now(client):
    r = act(client, DANIEL, "judgment_call", [f"finding:{EXTENSION}"], {"decision": "keep", "authority": "rule"}, reason="r")
    assert r.status_code == 422 and "not a finding on the return now" in " ".join(r.json()["refused"])


@pytest.mark.parametrize("line,finding,refusal", [
    ("Sch3.10", EXTENSION, "is not an open finding"),         # the move would create the finding it names
    ("SchB.1.6", "SSN_MISMATCH:theo", "does not concern SchB.1.6"),
    ("SchC.27a.1", E7, "does not concern SchC.27a.1"),
])
def test_a_fix_must_name_an_open_finding_on_its_line(client, line, finding, refusal):
    r = act(client, PRIYA, "adjust", [f"line:{line}"], {"to": 1, "finding": finding}, reason="r")
    assert r.status_code == 422 and refusal in " ".join(r.json()["refused"])


# ---- the third review: a line's estimate depends only on where it stands -------------------------------

def test_a_lines_adjustments_add_up_to_the_estimate_for_where_it_stands(client):
    direct = adjust(client, "SchE.14A", 9000)                  # a figure the checker cannot price
    undo = ok(act(client, DANIEL, "undo", [f"event:{direct['id']}"], reason="redo by another route"))["event"]
    assert undo
    there = fix(client, E9, "SchE.14A")
    on = adjust(client, "SchE.14A", 9000)                      # the same figure, after the card fix
    assert tuple(a + b for a, b in zip(stored(there), stored(on))) == stored(direct)


def test_an_acceptance_does_not_come_back_by_another_route(client):
    fix(client, E7, "SchA.5b")
    adjust(client, "SchA.5b", 9000)
    accept(client, E7)
    adjust(client, "SchA.5b", 13420)
    adjust(client, "SchA.5b", 9000)                            # the figure the acceptance saw, reached again
    found, _ = findings(client)
    assert found[E7]["status"] == "open" and found[E7]["details"]["acceptance_changed"]["lines"] == ["SchA.5b"]


def test_a_line_moved_back_to_a_fixed_figure_is_not_the_fix(client):
    fix(client, E1, "F8949.E.N4", to=1170)                     # a figure the person decided, for the finding
    accept(client, E1)
    adjust(client, "F8949.E.N4", 10590)
    adjust(client, "F8949.E.N4", 1170)                         # same figure, but no longer the fix made for E1
    assert findings(client)[0][E1]["status"] == "open"


def test_a_judgment_answers_one_finding_at_a_time(client):
    r = act(client, DANIEL, "judgment_call", [f"finding:{E1}", f"finding:{E9}"], {"decision": "as is", "authority": "rule"},
            reason="r")
    assert r.status_code == 422 and "one finding at a time" in " ".join(r.json()["refused"])


# ---- the fourth review: what the cards say ---------------------------------------------------------------

def test_the_same_dollars_note_shows_what_is_still_open(client):
    adjust(client, "F540NR.72", 12000)                         # 2,000 of the 3,500 already on the return
    found, _ = findings(client)
    assert found[E13_FTB]["effect"]["california"] == 1500
    assert [s["effect"]["california"] for s in found[E13_YEAR]["shared"]] == [1500]


def test_an_accepted_card_has_nothing_still_open(client):
    adjust(client, "SchC.25", 2832)
    accept(client, E21)
    card = findings(client)[0][E21]
    assert card["status"] == "accepted" and card["fixes"] == [] and card["accept_effect"] is None


# ---- the fifth review: findings with no pieces ---------------------------------------------------------
NOT_ON_PAGE = "VALUE_NOT_ON_PAGE:ev-0498"


def test_a_finding_with_no_pieces_reopens_when_its_fix_is_undone_or_moved(client):
    step = adjust(client, "F8949.B.N1", 9000)
    adjust(client, "F8949.B.N1", 140, finding=NOT_ON_PAGE)
    assert findings(client)[0][NOT_ON_PAGE]["status"] == "addressed"
    ok(act(client, DANIEL, "undo", [f"event:{step['id']}"], reason="redo"))   # the fix no longer applies
    assert findings(client)[0][NOT_ON_PAGE]["status"] == "open"
    adjust(client, "F8949.B.N1", 140, finding=NOT_ON_PAGE)
    adjust(client, "F8949.B.N1", 19240)                        # moved back
    assert findings(client)[0][NOT_ON_PAGE]["status"] == "open"
