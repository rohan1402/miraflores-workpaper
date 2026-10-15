"""Step 5: filing, the agency's answer, the freeze, amendments, the notice and the examiner (D23 to D25),
and the firm's time, standards and search."""

import re

import pytest
from fastapi.testclient import TestClient

from workpaper.api import create_app
from workpaper.areas import RETURN, SIGNED_SCOPES
from workpaper.events import Event, StaleTip
from workpaper.filing import Transmission, agency_answer, presented_return, settlement
from workpaper.project import project, signoff_payload

from conftest import ev, log

PRIYA, DANIEL, HELEN, MARCUS, JO = "st-01", "st-02", "st-03", "st-04", "st-05"
NGOZI, ERIK, EXAMINER = "cu-01", "cu-02", "irs-examiner"
THEO = "SSN_MISMATCH:theo"
NOTICE = "notice:N-2025-L566"
SSN_SHAPED = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "workpaper.db", heartbeat_seconds=0.05)) as c:
        yield c


def as_(person):
    return {"X-Person": person}


def act(client, person, action, targets, payload=None, reason=None, base_tip=None):
    tip = client.get("/api/me", headers=as_(person)).json()["tip"] if base_tip is None else base_tip
    return client.post("/api/actions", headers=as_(person), json={
        "action": action, "targets": targets, "payload": payload or {}, "reason": reason, "base_tip": tip})


def ok(response):
    assert response.status_code == 200, response.json()
    return response.json()


def released(client):
    """Setup, straight into the log: every area signed (with a waiver) by Priya and Daniel, then Helen's
    release. The acts under test go through the API."""
    store, packet = client.app.state.snapshots.store, client.app.state.snapshots.packet
    for area in SIGNED_SCOPES:
        for who, level in ((PRIYA, "preparer"), (DANIEL, "reviewer")):
            payload = signoff_payload(project(packet, store.all()), area, level, waiver="Signed with open items.", waived=[])
            store.append(Event(actor=who, role=level, action="sign_off", targets=(f"area:{area}",), payload=payload,
                               base_tip=store.tip()))
    payload = signoff_payload(project(packet, store.all()), RETURN, "partner")
    store.append(Event(actor=HELEN, role="partner", action="partner_release", targets=("return",), payload=payload,
                       base_tip=store.tip()))


def both_sign(client):
    for who in (NGOZI, ERIK):
        ok(act(client, who, "sign_8879", ["return"]))


def filing(client):
    return client.get("/api/filing", headers=as_(HELEN)).json()


def accepted(client):
    """Released, the number corrected from last year's return, signed and transmitted: accepted."""
    released(client)
    ok(act(client, PRIYA, "correct_identity", ["household:theo"], {"document": "D06", "finding": THEO},
           reason="last year's return prints Theo's number"))
    both_sign(client)
    ok(act(client, PRIYA, "transmit", ["return"]))


# ---- before anything goes out --------------------------------------------------------

def test_nothing_goes_out_without_the_partner_release_and_both_8879s(client):
    r = act(client, NGOZI, "sign_8879", ["return"])
    assert r.status_code == 422 and "nothing to sign yet" in r.json()["refused"][0]
    released(client)
    r = act(client, PRIYA, "transmit", ["return"])
    assert r.status_code == 422 and r.json()["refused"] == [
        "Ngozi Okafor has not signed the 8879 for the return as it stands now.",
        "Erik Lindqvist has not signed the 8879 for the return as it stands now."]
    ok(act(client, NGOZI, "sign_8879", ["return"]))
    assert act(client, PRIYA, "transmit", ["return"]).json()["refused"] == [
        "Erik Lindqvist has not signed the 8879 for the return as it stands now."]


def test_only_a_client_signs_the_8879_and_only_staff_transmit(client):
    released(client)
    assert act(client, PRIYA, "sign_8879", ["return"]).status_code == 403
    assert act(client, NGOZI, "transmit", ["return"]).status_code == 403


# ---- the agency reads the digits on the return (D23) -----------------------------------

def test_the_organizers_number_is_rejected_and_california_is_held(client):
    released(client)
    both_sign(client)
    sent = ok(act(client, DANIEL, "transmit", ["return"]))["event"]["id"]
    answer = filing(client)["transmissions"][-1]["answer"]
    assert answer["federal"]["status"] == "rejected" and answer["federal"]["errors"][0]["code"] == "R0000-504-02"
    assert answer["california"]["status"] == "not_transmitted" and answer["wrong_tins"] == ["theo"]
    assert filing(client)["frozen"] is False
    theo = next(f for f in client.get("/api/findings", headers=as_(HELEN)).json()["findings"] if f["id"] == THEO)
    assert f"event:{sent}" in theo["evidence"]   # the rejection is the firm's own transmission, not a dated script
    r = act(client, HELEN, "undo", [f"event:{sent}"], reason="pretend it never went")
    assert r.status_code == 422 and "cannot be undone" in r.json()["refused"][0]


def test_accepting_the_finding_without_changing_the_number_is_still_rejected(client):
    released(client)
    ok(act(client, PRIYA, "judgment_call", [f"finding:{THEO}"], {"decision": "file as is",
                                                                "authority": "client organizer"}, reason="r"))
    both_sign(client)
    ok(act(client, PRIYA, "transmit", ["return"]))
    assert filing(client)["transmissions"][-1]["answer"]["federal"]["status"] == "rejected"


def test_correcting_the_number_reopens_the_8879_and_the_next_transmission_is_accepted(client):
    released(client)
    both_sign(client)
    ok(act(client, PRIYA, "transmit", ["return"]))                                  # rejected
    ok(act(client, PRIYA, "correct_identity", ["household:theo"], {"document": "D71", "finding": THEO},
           reason="Social Security card"))
    status = filing(client)
    assert status["form_8879"]["current"] is False and all(s["signed"] for s in status["form_8879"]["signers"].values())
    both_sign(client)
    ok(act(client, PRIYA, "transmit", ["return"]))
    status = filing(client)
    answer = status["transmissions"][-1]["answer"]
    assert (answer["federal"]["status"], answer["federal"]["submission_id"]) == ("accepted", "71530420261950019871")
    assert answer["california"]["status"] == "accepted"
    assert status["frozen"] is True and status["stage"] == "filed and accepted"
    theo = next(f for f in client.get("/api/findings", headers=as_(HELEN)).json()["findings"] if f["id"] == THEO)
    assert theo["status"] == "addressed"


def test_last_years_return_already_had_the_number_in_march(packet):
    march = project(packet, [], as_of="2026-03-15T23:59:59Z")
    assert march.document_visible(packet.documents["D06"]) and not march.document_visible(packet.documents["D71"])
    fixed = project(packet, log(ev("correct_identity", ["household:theo"], payload={"person": "theo", "document": "D06"})),
                    as_of="2026-12-31T00:00:00Z")
    assert agency_answer(packet, presented_return(fixed), "original")["federal"]["status"] == "accepted"


@pytest.mark.parametrize("payload,expect", [
    ({"document": "D09"}, "does not print an SSN for Theo"),
    ({"document": "D99"}, "Name a document that has arrived"),
])
def test_a_number_comes_only_from_a_document_that_prints_it(client, payload, expect):
    r = act(client, PRIYA, "correct_identity", ["household:theo"], payload, reason="r")
    assert r.status_code == 422 and expect in r.json()["refused"][0]


# ---- the freeze, after acceptance ------------------------------------------------------

def test_the_filed_return_is_frozen_but_notes_still_append(client):
    accepted(client)
    r = act(client, PRIYA, "adjust", ["line:F1040.26"], {"to": 12000}, reason="transcript")
    assert r.status_code == 422 and "frozen" in r.json()["refused"][0]
    assert act(client, PRIYA, "note", ["line:F1040.26"], {"text": "found after filing"}).status_code == 200


def test_the_payment_or_refund_uses_the_balance_of_the_accepted_return(packet):
    owed = Transmission(1, "2026-07-20T00:00:00Z", PRIYA, "original",
                        {"estimated_balance_due": {"federal": 4220, "california": -8256}}, "x",
                        {"federal": {"status": "accepted"}, "california": {"status": "accepted"}})
    out = settlement(packet, owed)
    assert out["california"] == {"kind": "refund", "amount": 8256}
    assert (out["federal"]["kind"], out["federal"]["amount"], out["federal"]["penalty"]) == ("payment", 4220, 84)  # 4 months
    assert out["federal"]["interest"] == round(4220 * 0.07 * 96 / 365)
    corrected = Transmission(1, "2026-07-20T00:00:00Z", PRIYA, "original",
                             {"estimated_balance_due": {"federal": -4533, "california": -11573}}, "x",
                             {"federal": {"status": "accepted"}, "california": {"status": "accepted"}})
    assert settlement(packet, corrected)["federal"] == {"kind": "refund", "amount": 4533}   # the July 20 payment does not play


def test_the_scripted_agency_answers_are_not_on_the_calendar_and_the_notice_waits_for_an_acceptance(client):
    season = [i["event"] for i in client.get("/api/timeline", headers=as_(HELEN)).json() if i["kind"] == "season"]
    assert "efile_rejected" not in season and "notice_received" not in season
    assert client.get("/api/documents/D72", headers=as_(HELEN)).status_code == 404
    accepted(client)
    items = client.get("/api/timeline", headers=as_(HELEN)).json()
    assert "notice_received" in [i["event"] for i in items if i["kind"] == "season"]
    assert [i["detail"][:16] for i in items if i["event"] == "agency_answer"] == ["Federal accepted"]
    assert client.get("/api/documents/D72", headers=as_(HELEN)).status_code == 200


def test_a_client_signs_what_they_were_shown(client):
    released(client)
    tip = client.get("/api/me", headers=as_(NGOZI)).json()["tip"]
    ok(act(client, PRIYA, "adjust", ["line:F1040.26"], {"to": 12000}, reason="Agreed to IRS transcript"))
    assert act(client, NGOZI, "sign_8879", ["return"], base_tip=tip).status_code == 409


# ---- amend on top (D25) ---------------------------------------------------------------

def test_an_amendment_is_a_full_second_round(client):
    accepted(client)
    assert act(client, PRIYA, "open_amendment", ["return"], reason="r").status_code == 403
    ok(act(client, HELEN, "open_amendment", ["return"], reason="Estimates agreed to the IRS transcript"))
    ok(act(client, PRIYA, "adjust", ["line:F1040.26"], {"to": 12000, "finding": "ESTIMATES_VS_TRANSCRIPT:F1040.26"},
           reason="Agreed to IRS transcript"))
    status = filing(client)
    assert status["stage"] == "amendment open" and status["next_kind"] == "amended"
    assert status["comparison"]["net_change"] == {"federal": 1000, "california": 0}
    assert "The partner has not released the return since the amendment opened." in status["transmit_blockers"]
    released(client)
    both_sign(client)
    ok(act(client, DANIEL, "transmit", ["return"]))
    status = filing(client)
    last = status["transmissions"][-1]
    assert last["kind"] == "amended" and last["answer"]["federal"]["status"] == "filed"
    assert last["settlement"]["federal"]["amount"] == 1000   # what the amendment adds, not the whole balance
    assert status["frozen"] is True and status["stage"] == "amended return filed"


# ---- the notice and the examiner (D24) ---------------------------------------------------

def test_the_notice_exists_only_after_an_acceptance(client):
    assert client.get("/api/notices", headers=as_(PRIYA)).json()["notices"] == []
    r = act(client, PRIYA, "notice_response", [NOTICE], {"item": 0, "text": "x"})
    assert r.status_code == 422


def test_evidence_is_suggested_from_the_items_own_words(client):
    accepted(client)
    items = client.get("/api/notices", headers=as_(PRIYA)).json()["notices"][0]["items"]
    assert {"line:SchA.12", "line:F8283.A1.stock", "line:F8283.A1.vehicle", "D66", "qa-39"} <= set(items[0]["suggested"])
    assert {"line:SchC.1", "D16", "D17", "D18", "D19", "D20", "D21"} <= set(items[1]["suggested"])


def test_the_examiner_sees_only_what_the_partner_released(client):
    accepted(client)
    assert client.get("/api/return", headers=as_(EXAMINER)).status_code == 403
    notice = client.get("/api/notices", headers=as_(PRIYA)).json()["notices"][0]
    ok(act(client, PRIYA, "notice_response", [NOTICE] + notice["items"][0]["suggested"],
           {"item": 0, "text": "Acknowledgments and the 1098-C attached."}))
    r = act(client, HELEN, "release_notice_response", [NOTICE])
    assert r.status_code == 422 and "Item 2 has no answer yet" in r.json()["refused"][0]
    ok(act(client, PRIYA, "notice_response", [NOTICE, "line:SchC.1", "D21"], {"item": 1, "text": "Receipts reconcile."}))
    ok(act(client, DANIEL, "review_note", ["line:SchC.1"], {"text": "internal: check the 1099-K"}))
    assert client.get("/api/examiner", headers=as_(EXAMINER)).json()["released"] == []
    ok(act(client, HELEN, "release_notice_response", [NOTICE]))
    view = client.get("/api/examiner", headers=as_(EXAMINER))
    package = view.json()["released"][0]
    assert [i["answer"] for i in package["items"]] == ["Acknowledgments and the 1098-C attached.", "Receipts reconcile."]
    assert package["items"][0]["evidence"][0]["as_filed"] == 20500
    assert "internal: check" not in view.text and not SSN_SHAPED.findall(view.text)
    export = client.get("/api/examiner/export", headers=as_(EXAMINER))
    assert export.status_code == 200 and "Receipts reconcile." in export.text and not SSN_SHAPED.findall(export.text)


def test_a_release_is_refused_if_a_draft_changed_after_the_partner_looked(store):
    draft = store.append(ev("notice_response", [NOTICE], payload={"item": 0, "text": "v2"}))
    with pytest.raises(StaleTip) as err:
        store.append(ev("release_notice_response", [NOTICE], actor=HELEN, role="partner", base_tip=0))
    assert err.value.conflicting.id == draft.id


# ---- the firm: time, standards, search ---------------------------------------------------

def test_time_is_logged_against_the_budget(client):
    ok(act(client, MARCUS, "log_time", ["time:business"], {"hours": 2.5, "text": "Schedule C"}))
    ok(act(client, PRIYA, "log_time", ["time:business"], {"hours": 1.5}))
    assert act(client, PRIYA, "log_time", ["time:nowhere"], {"hours": 1}).status_code == 422
    assert act(client, PRIYA, "log_time", ["time:business"], {"hours": 30}).status_code == 422
    business = next(b for b in client.get("/api/firm/time", headers=as_(HELEN)).json()["buckets"] if b["bucket"] == "business")
    assert (business["logged"], business["left"], business["over"], business["by_person"]) == (4.0, -0.5, True,
                                                                                              {MARCUS: 2.5, PRIYA: 1.5})


def test_the_administrator_changes_a_standard_with_a_reason_and_the_checker_follows(client):
    flagged = lambda: {f["id"] for f in client.get("/api/findings", headers=as_(HELEN)).json()["findings"]  # noqa: E731
                       if f["code"] == "PRIOR_YEAR_VARIANCE"}
    before = flagged()
    path = "variance_review.flag_if_change_over_percent"
    assert act(client, JO, "set_standard", [], {"path": path, "value": 50}).status_code == 422          # no reason
    assert act(client, JO, "set_standard", [], {"path": path, "value": "lots"}, reason="r").status_code == 422
    assert act(client, PRIYA, "set_standard", [], {"path": path, "value": 50}, reason="r").status_code == 403
    ok(act(client, JO, "set_standard", [], {"path": path, "value": 50}, reason="Firm review: only large swings"))
    assert flagged() < before
    changes = client.get("/api/firm/standards", headers=as_(JO)).json()["changes"]
    assert changes[0]["value"] == 50 and changes[0]["reason"] == "Firm review: only large swings"


def test_search_finds_the_file_but_never_a_hidden_number(client):
    found = client.get("/api/search?q=8283", headers=as_(MARCUS)).json()
    assert {"line:F8283.A1.stock", "line:F8283.A1.vehicle"} <= {r["ref"] for r in found["groups"]["lines"]}
    for person in (PRIYA, MARCUS):
        assert client.get("/api/search?q=666-74", headers=as_(person)).json()["groups"] == {}
        assert client.get("/api/search?q=4483019276", headers=as_(person)).json()["groups"] == {}
