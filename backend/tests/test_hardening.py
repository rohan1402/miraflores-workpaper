"""Nothing malformed reaches the append-only log, and reads survive bad input (D35).

The log can never be edited, so one malformed event would break every screen that replays it, for
good. Every case below was reproduced against the running app by an adversarial review workflow
before it was fixed. The rule at the door: each act takes a fixed set of keys of fixed types (others
are dropped), and every target is a well-formed reference.
"""

import pytest
from fastapi.testclient import TestClient

from workpaper.api import create_app
from workpaper.events import Event
from workpaper.rollforward import PLAN_CALIFORNIA

from test_filing import DANIEL, HELEN, JO, MARCUS, PRIYA, accepted, act, as_, ok

NOTICE = "notice:N-2025-L566"
READS = ["/api/return", "/api/findings", "/api/health", "/api/rollforward", "/api/timeline", "/api/events",
         "/api/since", "/api/filing", "/api/firm/time", "/api/history?ref=line:SchC.18", "/api/search?q=SchC"]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "workpaper.db", heartbeat_seconds=0.05)) as c:
        yield c


def tip(client):
    return client.get("/api/me", headers=as_(PRIYA)).json()["tip"]


def refused(response, words):
    assert response.status_code == 422, response.text
    assert any(words in r for r in response.json()["refused"]), response.json()


def reads_work(client):
    for url in READS:
        assert client.get(url, headers=as_(DANIEL)).status_code == 200, url


# ---- each act takes its own keys, of its own types --------------------------------------------

def test_keys_an_act_does_not_take_are_dropped(client):
    stored = ok(act(client, MARCUS, "question", ["line:SchC.18"],
                    {"text": "q", "to": "client", "finding": ["x"], "value_type": ["x"], "undoes": {"targets": [1]},
                     "meta": {"value_type": {}}}))["event"]
    assert stored["payload"] == {"text": "q", "to": "client"}
    reads_work(client)


@pytest.mark.parametrize("person,action,targets,payload,words", [
    (PRIYA, "adjust", ["line:SchC.18"], {"to": 100, "finding": {"a": 1}}, "finding must be a finding id"),
    (PRIYA, "judgment_call", ["finding:SSN_MISMATCH:theo"], {"decision": "d", "authority": "a", "finding": [1]},
     "finding must be a finding id"),
    (PRIYA, "adjust", ["line:SchC.18"], {"to": True}, "to must be a real amount"),
    (PRIYA, "log_time", ["time:business"], {"hours": True}, "hours must be a real amount"),
    (PRIYA, "log_time", ["time:business"], {"hours": 1, "on": {"value_type": []}}, "on must be a date"),
    (PRIYA, "note", ["line:SchC.18"], {"text": ["not", "text"]}, "text must be text"),
    (PRIYA, "disposition", ["D31"], {"disposition": "partial", "pages": [[32]]}, "pages must be a list of page numbers"),
    (JO, "set_standard", [], {"path": ["variance_review"], "value": 5}, "path must be text"),
    (JO, "set_standard", [], {"path": "variance_review", "value": {"and_over_amount": 1000}}, "value must be a number"),
])
def test_a_key_of_the_wrong_type_is_refused_and_nothing_is_stored(client, person, action, targets, payload, words):
    before = tip(client)
    refused(act(client, person, action, targets, payload, reason="r"), words)
    assert tip(client) == before


# ---- every target is a well-formed reference --------------------------------------------------------

def test_a_malformed_or_extra_target_is_refused(client):
    note = ok(act(client, DANIEL, "review_note", ["line:SchC.18"], {"text": "check this"}))["event"]["id"]
    refused(act(client, DANIEL, "resolve_review_note", [f"event:{note}", "line:SchC.18"], {"text": "done"}),
            "exactly one event")
    big = ok(act(client, PRIYA, "adjust", ["line:SchC.18"], {"to": 500000}, reason="big"))["event"]["id"]
    refused(act(client, HELEN, "approve_adjustment", [f"event:{big}", "event:x"]), "Not a reference the workpaper knows")
    refused(act(client, HELEN, "approve_adjustment", [f"event:{big}", f"event:{note}"]), "over the partner threshold")
    refused(act(client, PRIYA, "note", ["nonsense"], {"text": "t"}), "Not a reference the workpaper knows")
    refused(act(client, PRIYA, "note", ["doc:D31#pageX"], {"text": "t"}), "Not a reference the workpaper knows")
    ok(act(client, HELEN, "approve_adjustment", [f"event:{big}"]))
    reads_work(client)


# ---- defense in depth: an event already in a log cannot break the reads ------------------------------

def test_malformed_events_already_in_a_log_do_not_break_the_reads(client):
    # Events written straight to the store, as if recorded before these checks existed.
    store = client.app.state.snapshots.store
    for e in [
        Event(actor=DANIEL, role="reviewer", action="review_note", targets=("line:SchC.18",), payload={"text": "n"}),
        Event(actor=DANIEL, role="reviewer", action="resolve_review_note", targets=("event:1", "line:SchC.18"),
              payload={"text": "done"}),
        Event(actor=HELEN, role="partner", action="approve_adjustment", targets=("event:x",), payload={}),
        Event(actor=PRIYA, role="preparer", action="undo", targets=("event:y",), payload={}),
        Event(actor=MARCUS, role="preparer", action="question", targets=("line:SchC.18",),
              payload={"text": "q", "to": "client", "finding": ["x"], "value_type": ["x"]}),
        Event(actor=PRIYA, role="preparer", action="judgment_call", targets=("finding:SSN_MISMATCH:theo",),
              payload={"decision": "d", "authority": ["a"], "finding": {"x": 1}}),
    ]:
        store.append(Event(**{**e.__dict__, "base_tip": store.tip()}))
    reads_work(client)


# ---- the California plan answers no finding (D32, D34) -------------------------------------------

def test_a_planning_decision_cannot_answer_a_finding(client):
    plan = {"method": "safe_harbor", "decision": "d", "authority": "a", "finding": "DUPLICATE_PAGE:D23#page3"}
    refused(act(client, PRIYA, "judgment_call", [PLAN_CALIFORNIA], plan, reason="r"), "answers no finding")
    accepted(client)   # after filing, it must not slip a finding on the filed return through the freeze
    assert act(client, DANIEL, "judgment_call", [PLAN_CALIFORNIA], plan, reason="r").status_code == 422
    finding = next(f for f in client.get("/api/findings", headers=as_(PRIYA)).json()["findings"]
                   if f["id"] == "DUPLICATE_PAGE:D23#page3")
    assert finding["status"] == "open"


@pytest.mark.parametrize("sent,stored", [(6000.0, 6000), (-0.0, 0)])
def test_the_projected_tax_is_stored_in_whole_dollars(client, sent, stored):
    ok(act(client, PRIYA, "judgment_call", [PLAN_CALIFORNIA],
           {"method": "projected", "projected_2026_tax": sent, "decision": "d", "authority": "a"}, reason="r"))
    chosen = client.get("/api/rollforward", headers=as_(PRIYA)).json()["estimates"]["california"]["chosen"]
    assert chosen["projected_2026_tax"] == stored and type(chosen["projected_2026_tax"]) is int


# ---- firm standards change one field at a time, keeping its type ----------------------------------

@pytest.mark.parametrize("path,value,words", [
    ("variance_review", 5, "one standard at a time"),
    ("variance_review.and_over_amount", "lots", "a number of zero or more"),
    ("rules", "one rule", "a list of entries"),
])
def test_a_standard_change_keeps_the_shape_of_the_standards(client, path, value, words):
    refused(act(client, JO, "set_standard", [], {"path": path, "value": value}, reason="r"), words)
    assert client.get("/api/firm/standards", headers=as_(JO)).status_code == 200


# ---- a notice answer cites evidence that exists; files go through the upload route -----------------

def test_a_notice_answer_cites_evidence_that_exists(client):
    accepted(client)
    for bad in ("line:NOPE.1", "D99", "event:1"):
        refused(act(client, PRIYA, "notice_response", [NOTICE, bad], {"item": 0, "text": "answer"}), "Cite evidence that exists")
    refused(act(client, PRIYA, "notice_response", [NOTICE, "event:1e999"], {"item": 0, "text": "a"}), "Not a reference")
    refused(act(client, PRIYA, "notice_response", [NOTICE], {"item": True, "text": "answer"}), "item must be a whole number")
    assert client.get(f"/api/notices/preview?notice={NOTICE}", headers=as_(PRIYA)).status_code == 200


def test_files_are_attached_only_through_the_upload_route(client):
    refused(act(client, PRIYA, "attach_evidence", ["line:SchC.18"], {"sha256": "x", "file_name": {"a": 1}}),
            "through /api/attachments")
    r = client.post("/api/attachments", headers=as_(PRIYA), data={"targets": "line:SchC.18", "base_tip": "999"},
                    files={"file": ("a.txt", b"hello", "text/plain")})
    refused(r, "cannot be ahead of the log")


# ---- reads answer bad input with a 4xx, never a 500 -----------------------------------------------

@pytest.mark.parametrize("url,status", [
    ("/api/estimate?line=SchC.18&to=inf", 422),
    ("/api/estimate?line=SchC.18&to=nan", 422),
    ("/api/filing?as_of=garbage", 422),
    ("/api/return?as_of=2026-13-45", 422),
    (f"/api/events?after={10**30}", 200),
])
def test_reads_answer_bad_input_without_failing(client, url, status):
    assert client.get(url, headers=as_(PRIYA)).status_code == status


def test_an_unmask_of_a_malformed_page_reference_is_not_found(client):
    r = client.post("/api/unmask", headers=as_(PRIYA), json={"ref": "doc:D09#pageX"})
    assert r.status_code == 404


# ---- text that cannot be written as UTF-8 (a lone surrogate) never reaches the log ------------------

SURROGATE_NOTE = '{"action": "note", "targets": [%s], "payload": {"text": %s}, "reason": %s, "base_tip": %d}'


@pytest.mark.parametrize("targets,text,reason", [
    ('"line:SchC.18"', '"hello \\ud800 there"', "null"),    # in the text
    ('"line:SchC.18\\ud800"', '"ok"', "null"),              # in a target
    ('"line:SchC.18"', '"ok"', '"why \\udfff"'),            # in the reason
])
def test_text_that_is_not_utf8_is_refused_and_nothing_is_stored(client, targets, text, reason):
    before = tip(client)
    r = client.post("/api/actions", headers={**as_(PRIYA), "Content-Type": "application/json"},
                    content=SURROGATE_NOTE % (targets, text, reason, before))
    assert r.status_code == 422 and tip(client) == before


def test_a_surrogate_already_in_a_log_does_not_break_a_response(client):
    store = client.app.state.snapshots.store
    store.append(Event(actor=PRIYA, role="preparer", action="note", targets=("line:SchC.18",),
                       payload={"text": "hello \ud800 there"}, base_tip=0))
    store.append(Event(actor=DANIEL, role="reviewer", action="review_note", targets=("line:SchC.18",),
                       payload={"text": "x \udfff"}, base_tip=1))
    reads_work(client)
    assert client.get("/api/rollforward/export", headers=as_(PRIYA)).status_code == 200


def test_a_released_answer_citing_the_call_note_exports(client):
    accepted(client)
    ok(act(client, PRIYA, "notice_response", [NOTICE, "call-01"], {"item": 0, "text": "Per the client call."}))
    ok(act(client, PRIYA, "notice_response", [NOTICE, "line:SchC.1"], {"item": 1, "text": "Receipts reconcile."}))
    ok(act(client, HELEN, "release_notice_response", [NOTICE]))
    r = client.get("/api/examiner/export", headers=as_(HELEN))
    assert r.status_code == 200 and "call-01" in r.text


def test_a_verification_type_is_a_plain_name(client):
    refused(act(client, JO, "set_standard", [], {"path": "verification_types", "value": ["recalculated", "__proto__"]},
                reason="r"), "plain name")


def test_a_reference_number_is_written_in_plain_digits(client):
    # "²" is a digit to str.isdigit() but not to int(): such a reference must never get in.
    for target in ("doc:D10#page²", "event:²", "D¹²"):
        refused(act(client, PRIYA, "note", [target], {"text": "t"}), "Not a reference the workpaper knows")
    assert client.post("/api/unmask", headers=as_(PRIYA), json={"ref": "doc:D09#page²"}).status_code == 404
