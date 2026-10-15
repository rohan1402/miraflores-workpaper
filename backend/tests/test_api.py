"""Step 2: the API. Roles enforced on the server, masking on the way out, writes with 409, live updates."""

import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from workpaper.api import create_app
from workpaper.areas import SIGNED_SCOPES
from workpaper.live import event_stream, sse

PRIYA, DANIEL, HELEN, MARCUS, JO = "st-01", "st-02", "st-03", "st-04", "st-05"
NGOZI, EXAMINER = "cu-01", "irs-examiner"

# What must never leave the server unmasked (the answer key, written out on purpose).
SECRETS = ["666-41-2287", "666-52-9134", "666-38-1106", "666-74-3309", "666-74-3390",
           "482915", "4483019276", "990000017", "SE45 8000 0000 0412 7783 9901", "41207", "88310"]
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


def assert_no_secrets(text: str, where: str):
    leaked = [s for s in SECRETS if s in text]
    shaped = SSN_SHAPED.findall(text)
    assert not leaked and not shaped, f"{where} leaks {leaked or shaped}"


# ---- identity and the role switcher ------------------------------------------

def test_every_request_needs_a_person(client):
    assert client.get("/api/return").status_code == 401


def test_role_switcher_lists_staff_clients_and_the_examiner(client):
    people = {p["id"]: p for p in client.get("/api/people").json()}
    assert people[MARCUS] == {"id": MARCUS, "name": "Marcus Bell", "role": "preparer", "clearance": False}
    assert people[NGOZI]["role"] == "client" and people[EXAMINER]["role"] == "examiner"


def test_session_cookie_identifies_the_person(client):
    me = client.post("/api/session", json={"person": DANIEL}).json()
    assert me["person"]["role"] == "reviewer" and "review_note" in me["verbs"]
    assert client.get("/api/me").json()["person"]["id"] == DANIEL   # the cookie is sent from now on


def test_role_changes_the_default_slice_not_the_home(client):
    priya = client.get("/api/return", headers=as_(PRIYA)).json()
    daniel = client.get("/api/return", headers=as_(DANIEL)).json()
    assert [a["id"] for a in priya["areas"]][:3] == ["wages_and_stock_compensation", "investments_and_digital_assets",
                                                     "business"]
    assert daniel["config"]["default_filters"] == ["adjusted", "variance", "changed_by_others"]
    assert priya["strip"] == daniel["strip"]   # same return


# ---- masking (D11) ---------------------------------------------------------------

@pytest.mark.parametrize("person", [MARCUS, HELEN, EXAMINER])
def test_no_screen_leaks_sensitive_data(client, person, packet):
    h = as_(person)
    pages = ["/api/return", "/api/documents", "/api/findings", "/api/events", "/api/checker/summary"]
    pages += [f"/api/areas/{a}" for a in SIGNED_SCOPES]
    pages += [f"/api/documents/{d}" for d in packet.documents]
    if person == MARCUS:
        pages += [f"/api/lines/{k}" for k in packet.lines["v3"]]
    for url in pages:
        r = client.get(url, headers=h)
        assert r.status_code == 200, url
        assert_no_secrets(r.text, url)


def test_pages_are_masked_but_still_readable(client):
    page = client.get("/api/documents/D09", headers=as_(HELEN)).json()["pages"][0]["text"]
    assert "Employee Ngozi Okafor, SSN ***-**-2287." in page
    d36 = client.get("/api/documents/D36", headers=as_(HELEN)).json()["pages"][0]["text"]
    assert "Savings account ****9901." in d36


def test_identity_finding_keeps_last_four_and_masks_details(client):
    findings = client.get("/api/findings", headers=as_(HELEN)).json()["findings"]
    theo = next(f for f in findings if f["id"] == "SSN_MISMATCH:theo")
    assert "ends 3309" in theo["message"]
    assert theo["details"]["ssn_on_organizer"] == "***-**-3309"


def test_marcus_cannot_unmask_and_nothing_is_logged(client):
    r = client.post("/api/unmask", headers=as_(MARCUS), json={"ref": "ev-0034"})
    assert r.status_code == 403
    assert client.get("/api/me", headers=as_(MARCUS)).json()["tip"] == 0


def test_cleared_unmask_is_logged_and_does_not_move_the_conflict_tip(client):
    r = client.post("/api/unmask", headers=as_(PRIYA), json={"ref": "household:theo"})
    assert r.json()["value"] == "666-74-3309"
    log = client.get("/api/audit/sensitive-views", headers=as_(HELEN)).json()
    assert [(e["actor"], e["targets"]) for e in log] == [(PRIYA, ["household:theo"])]
    # Daniel looked before the unmask (tip 0); his sign-off still goes in.
    signed = act(client, DANIEL, "sign_off", ["area:payments"], {"waiver": "estimates under review"}, base_tip=0)
    assert signed.status_code == 200, signed.json()


def test_view_log_is_for_partner_and_administrator(client):
    assert client.get("/api/audit/sensitive-views", headers=as_(JO)).status_code == 200
    assert client.get("/api/audit/sensitive-views", headers=as_(MARCUS)).status_code == 403


# ---- writes: the server computes, the firm's rules apply ------------------------

def test_server_computes_the_adjustment_ignoring_what_the_browser_claims(client):
    r = act(client, PRIYA, "adjust", ["line:SchC.9"],
            {"to": 5670, "from": 1, "effect": {"federal": 0, "california": 0}}, reason="page 3 is a second scan")
    payload = r.json()["event"]["payload"]
    assert (payload["from"], payload["to"]) == (8260, 5670)
    assert (payload["effect"]["federal"], payload["effect"]["california"]) == (919, 80)


def test_stale_signoff_gets_409_with_the_event_that_landed_first(client):
    adjust = act(client, PRIYA, "adjust", ["line:SchC.9"], {"to": 5670}, reason="duplicate page")
    r = act(client, DANIEL, "sign_off", ["area:business"], {"waiver": "x"}, base_tip=0)
    assert r.status_code == 409
    assert r.json()["conflict"]["id"] == adjust.json()["event"]["id"]


@pytest.mark.parametrize("person,action,targets,payload,reason,expect", [
    (MARCUS, "partner_release", ["return"], {}, None, "may not partner release"),
    (NGOZI, "adjust", ["line:SchC.9"], {"to": 1}, "x", "may not adjust"),
    (EXAMINER, "note", ["line:F1040.26"], {"text": "?"}, None, "may not note"),
    (JO, "sign_off", ["area:business"], {}, None, "may not sign off"),
])
def test_roles_are_enforced(client, person, action, targets, payload, reason, expect):
    r = act(client, person, action, targets, payload, reason)
    assert r.status_code == 403 and expect in r.json()["refused"][0]


@pytest.mark.parametrize("action,targets,payload,reason,expect", [
    ("judgment_call", ["finding:EVIDENCE_AFTER_COMPUTATION:msg-07"], {"decision": "keep zero basis"}, "x",
     "authority relied on"),
    ("adjust", ["line:SchC.9"], {"to": 5670}, None, "needs a reason"),
    ("verify", ["ev-1045"], {"verification_type": "high_confidence"}, None, "Verification type must be one of"),
    ("sign_off", ["area:business"], {}, None, "Open items in this area"),
    ("disposition", ["D10"], {"disposition": "ignored"}, None, "Disposition must be one of"),
])
def test_firm_rules_refuse_with_422(client, action, targets, payload, reason, expect):
    r = act(client, PRIYA, action, targets, payload, reason)
    assert r.status_code == 422 and any(expect in x for x in r.json()["refused"]), r.json()


def test_signing_with_open_items_needs_a_waiver_sentence(client):
    r = act(client, PRIYA, "sign_off", ["area:business"], {"waiver": "Mileage and 1099-K open with Erik; see notes."})
    assert r.status_code == 200
    assert r.json()["event"]["payload"]["level"] == "preparer"   # the level comes from the role, not the browser


def test_reviewer_may_not_review_what_they_adjusted(client):
    act(client, DANIEL, "adjust", ["line:SchC.9"], {"to": 5670}, reason="duplicate page")
    r = act(client, DANIEL, "sign_off", ["area:business"], {"waiver": "open items noted"})
    assert r.status_code == 422 and "may not review work they prepared" in r.json()["refused"][0]


def test_a_waiver_stores_the_errors_it_signs_over(client):
    r = act(client, PRIYA, "sign_off", ["area:business"], {"waiver": "Open with Erik; resolving before release."})
    waived = {w["id"]: (w["federal"], w["california"]) for w in r.json()["event"]["payload"]["waived"]}
    assert waived == {"DUPLICATE_PAGE:D23#page3": (919, 80),
                      "SAME_MONEY_TWO_SOURCES:SchC.1:D21": (-4402, -384),
                      "ANSWER_BARS_DEDUCTION:Sch1.17": (4464, 605)}



def test_partner_release_is_refused_while_blockers_remain(client):
    r = act(client, HELEN, "partner_release", ["return"])
    assert r.status_code == 422
    assert "area not signed: california" in r.json()["refused"]


# ---- reading ------------------------------------------------------------------

def test_home_strip_shows_both_years_and_the_estimates(client):
    strip = {(r["jurisdiction"], r["name"]): r for r in client.get("/api/return", headers=as_(HELEN)).json()["strip"]}
    agi = strip[("federal", "agi")]
    assert (agi["value"], agi["prior"], agi["variance"]) == (445590, 228409, True)
    due = strip[("federal", "balance_due")]
    assert due["estimated"]["after_open_corrections"] == 4220 - 8753


def test_brokerage_lots_collapse_into_accounts(client):
    accounts = {a["document"]: a for a in client.get("/api/areas/investments_and_digital_assets",
                                                     headers=as_(PRIYA)).json()["accounts"]}
    assert (accounts["D74"]["lots"], accounts["D74"]["summary"]) == (260, "ties")
    assert accounts["D31"]["summary"] == "gap"


def test_trace_shows_client_answers_as_their_own_kind_of_evidence(client):
    trace = client.get("/api/lines/F1040.26", headers=as_(PRIYA)).json()
    kinds = {s["ref"]: s["kind"] for s in trace["sources"]}
    assert kinds["qa-41"] == "client_questionnaire" and kinds["ev-1056"] == "document_value"
    assert trace["used_by"] == ["F1040.33"]


def test_document_says_why_it_landed_nowhere(client):
    d10 = client.get("/api/documents/D10", headers=as_(PRIYA)).json()
    assert d10["landed_on"] == [] and d10["not_used_because"] == "duplicate of D09 (not yet dispositioned)"


def test_clients_cannot_read_the_workpaper(client):
    assert client.get("/api/return", headers=as_(NGOZI)).status_code == 403


# ---- since I last looked ----------------------------------------------------------

def test_since_i_last_looked(client):
    act(client, PRIYA, "adjust", ["line:SchC.9"], {"to": 5670}, reason="duplicate page")
    act(client, DANIEL, "note", ["line:SchC.9"], {"text": "agree"})
    since = client.get("/api/since", headers=as_(DANIEL)).json()
    assert [e["action"] for e in since["events"]] == ["adjust"]   # not his own note
    client.post("/api/seen", headers=as_(DANIEL), json={"event_id": since["tip"]})
    assert client.get("/api/since", headers=as_(DANIEL)).json()["events"] == []


# ---- the client's question surface ------------------------------------------------

def test_question_to_the_client_and_the_answer(client):
    q = act(client, PRIYA, "question", ["qa-41"], {"to": "client", "text": "Can you send the EFTPS record for January?"})
    qid = q.json()["event"]["id"]
    seen_by_client = client.get("/api/client/questions", headers=as_(NGOZI)).json()["questions"]
    assert [x["question"]["id"] for x in seen_by_client] == [qid]
    a = act(client, NGOZI, "answer", [f"event:{qid}"], {"text": "It was 3,000 on January 15."})
    assert a.status_code == 200
    answers = client.get("/api/client/questions", headers=as_(PRIYA)).json()["questions"][0]["answers"]
    assert answers[0]["payload"]["text"] == "It was 3,000 on January 15."


# ---- attachments ------------------------------------------------------------------

def test_attachments_are_stored_by_hash_and_downloads_are_logged(client):
    up = client.post("/api/attachments", headers=as_(NGOZI), data={"targets": "msg-07", "note": "bank line"},
                     files={"file": ("cryptonorth.pdf", b"03/15/2021 CryptoNorth -3,050.00", "application/pdf")})
    assert up.status_code == 200, up.json()
    digest = up.json()["sha256"]
    assert client.get(f"/api/attachments/{digest}", headers=as_(NGOZI)).status_code == 200   # own upload
    assert client.get(f"/api/attachments/{digest}", headers=as_(MARCUS)).status_code == 403
    assert client.get(f"/api/attachments/{digest}", headers=as_(PRIYA)).content.startswith(b"03/15/2021")
    log = client.get("/api/audit/sensitive-views", headers=as_(HELEN)).json()
    assert [e["targets"] for e in log] == [[f"attachment:{digest}"]]


def test_household_uploads_are_visible_to_both_clients(client):
    up = client.post("/api/attachments", headers=as_(NGOZI), data={"targets": "msg-08"},
                     files={"file": ("receipt.pdf", b"St. Brigid 1,500", "application/pdf")})
    erik = "cu-02"
    assert client.get(f"/api/attachments/{up.json()['sha256']}", headers=as_(erik)).status_code == 200


# ---- the read cache ---------------------------------------------------------------

def test_an_unmask_does_not_rebuild_the_return(client):
    snapshots = client.app.state.snapshots
    client.get("/api/return", headers=as_(PRIYA))
    builds = snapshots.builds
    client.post("/api/unmask", headers=as_(PRIYA), json={"ref": "ev-0034"})
    client.get("/api/return", headers=as_(PRIYA))
    assert snapshots.builds == builds          # an unmask is an insert, but changes nothing
    act(client, PRIYA, "note", ["line:F1040.26"], {"text": "transcript pulled"})
    client.get("/api/return", headers=as_(PRIYA))
    assert snapshots.builds == builds + 1      # a note is part of the workpaper


# ---- live updates -----------------------------------------------------------------

def test_stream_sends_the_backlog_then_live_events_masked_and_filtered():
    async def run():
        queue: asyncio.Queue = asyncio.Queue()
        backlog = [{"id": 1, "actor": PRIYA, "action": "note", "targets": [], "payload": {"text": "SSN 666-41-2287"}},
                   {"id": 2, "actor": PRIYA, "action": "view_sensitive", "targets": ["ev-0034"], "payload": {}}]
        await queue.put({"id": 1, "actor": PRIYA, "action": "note", "targets": [], "payload": {}})   # already sent
        await queue.put({"id": 3, "actor": DANIEL, "action": "review_note", "targets": [], "payload": {"text": "?"}})
        polls = iter([False, False, False, True])

        async def get_backlog(last):
            return [e for e in backlog if e["id"] > last]

        async def disconnected():
            return next(polls)

        from workpaper.api import _visible
        from workpaper.masking import Masker
        from workpaper.packet import load_packet
        masker = Masker(load_packet())
        staff = {"id": DANIEL, "role": "reviewer"}
        return [chunk async for chunk in event_stream(get_backlog, queue, 0, lambda e: _visible(staff, e),
                                                      masker, disconnected, heartbeat=0.01)]

    chunks = asyncio.run(run())
    events = [c for c in chunks if c.startswith("id:")]
    assert [c.split("\n")[0] for c in events] == ["id: 1", "id: 3"]   # unmask record not streamed, id 1 not repeated
    assert "***-**-2287" in events[0] and "666-41-2287" not in events[0]
    assert ": keep-alive\n\n" in chunks


def test_sse_wire_format():
    assert sse(7, "wp-event", {"a": 1}) == 'id: 7\nevent: wp-event\ndata: {"a": 1}\n\n'
