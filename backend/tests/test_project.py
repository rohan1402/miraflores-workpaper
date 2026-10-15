"""project(packet, events): replay, undo, adjustments, sign-offs that reopen, partner blockers."""

from workpaper.areas import SIGNED_AREAS, area_of_line
from workpaper.checker import run_checker
from workpaper.project import (
    adjustment_effect, area_status, needs_partner, project, release_blockers, signoff_payload, signoff_status,
)

from conftest import ev, log

MARCH = "2026-03-15T00:00:00Z"   # v1 is current
APRIL = "2026-04-01T00:00:00Z"   # v2 is current (corrected Meridian 1099)
JULY = "2026-07-01T00:00:00Z"    # v3 is current (Ridgeline K-1)


def test_empty_log_is_the_packet_as_delivered(packet):
    state = project(packet, [])
    assert state.version_id == "v3"
    assert state.tip == 0
    assert state.line_value("F1040.26") == 13000


def test_adjust_keeps_the_original(packet):
    state = project(packet, log(ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000},
                                   reason="IRS transcript shows 3,000 on 1/15")))
    assert state.line_value("F1040.26") == 12000
    assert state.original_value("F1040.26") == 13000
    adj = state.adjustments["F1040.26"]
    assert (adj.actor, adj.reason) == ("st-01", "IRS transcript shows 3,000 on 1/15")
    effect = adjustment_effect(state, adj)
    assert (effect.federal, effect.california) == (1000, 0)   # a federal payment has no California effect


def test_undo_is_a_new_event_that_reverses_an_old_one(packet):
    events = log(
        ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000}),
        ev("undo", ["event:1"], reason="wrong line", payload={"undoes": {"targets": ["line:F1040.26"]}}),
    )
    state = project(packet, events)
    assert state.line_value("F1040.26") == 13000
    assert state.undone == {1}
    assert len(state.events) == 2  # history keeps both


def test_replay_to_any_date(packet):
    events = log(ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000}, at="2026-05-01T00:00:00Z"))
    assert project(packet, events, as_of=APRIL).line_value("F1040.26") == 13000
    assert project(packet, events, as_of=JULY).line_value("F1040.26") == 12000
    assert project(packet, events, as_of=MARCH).version_id == "v1"


def test_adjustment_goes_stale_when_a_new_version_changes_the_line(packet):
    # In March (v1) someone adjusts the M9 lot; the corrected 1099 in v2 changes that line.
    v1_value = packet.lines["v1"]["F8949.D.M9"]["value"]
    events = log(ev("adjust", ["line:F8949.D.M9"], payload={"from": v1_value, "to": 0}, at=MARCH))
    assert project(packet, events, as_of=MARCH).line_value("F8949.D.M9") == 0
    later = project(packet, events, as_of=APRIL)
    assert later.line_value("F8949.D.M9") == packet.lines["v2"]["F8949.D.M9"]["value"]
    assert [a.line for a in later.stale_adjustments()] == ["F8949.D.M9"]


def _signed(packet, area, level, at, actor="st-01", role="preparer", **kw):
    payload = signoff_payload(project(packet, [], as_of=at), area, level, **kw)
    return ev("sign_off", [f"area:{area}"], actor=actor, role=role, payload=payload, at=at)


def test_march_investments_signoff_reopens_when_the_corrected_1099_arrives(packet):
    events = log(_signed(packet, "investments_and_digital_assets", "preparer", MARCH))
    signed = project(packet, events, as_of=MARCH).signoffs["investments_and_digital_assets"]["preparer"]

    assert signoff_status(project(packet, events, as_of=MARCH), signed)["status"] == "signed"
    status = signoff_status(project(packet, events, as_of=APRIL), signed)
    assert status["status"] == "reopened"
    assert (status["signed_version"], status["current_version"]) == ("v1", "v2")
    changed = {c["key"] for c in status["changes"]}
    assert {"F8949.D.M9", "F8949.A.M6", "F8949.A.M14", "F8949.D.M14"} <= changed  # M9 basis, M6 wash, M14 term


def test_june_k1_reopens_passthroughs_but_leaves_wages_alone(packet):
    events = log(
        _signed(packet, "wages_and_stock_compensation", "preparer", APRIL),
        _signed(packet, "pass_throughs_and_basis", "preparer", APRIL),
    )
    july = project(packet, events, as_of=JULY)
    assert area_status(july, "wages_and_stock_compensation")["preparer"]["status"] == "signed"
    assert area_status(july, "pass_throughs_and_basis")["preparer"]["status"] == "reopened"


def test_tax_computation_lines_belong_to_the_return():
    assert area_of_line("F6251.11") == "return"   # AMT moves with everything
    assert area_of_line("F1040.1a") == "wages_and_stock_compensation"
    assert area_of_line("F1040.13") == "return"   # not F1040.1x wages
    assert area_of_line("Sch2.4") == "business"   # SE tax
    assert area_of_line("SchCA540NR.1.E") == "wages_and_stock_compensation"  # California is a lens


def test_review_note_does_not_lift_a_signoff_but_blocks_release(packet):
    signed = _signed(packet, "business", "preparer", JULY)
    note = ev("review_note", ["line:SchC.9"], actor="st-02", role="reviewer", payload={"text": "mileage page 3?"})
    resolve = ev("resolve_review_note", ["event:2"], payload={"text": "page 3 dispositioned as duplicate"})

    state = project(packet, log(signed, note))
    assert area_status(state, "business")["preparer"]["status"] == "signed"
    assert "open review note (event 2)" in release_blockers(state)

    resolved = project(packet, log(signed, note, resolve))
    assert "open review note (event 2)" not in release_blockers(resolved)


def test_preparer_and_reviewer_must_be_different_people(packet):
    events = log(
        _signed(packet, "payments", "preparer", JULY, actor="st-02", role="reviewer"),
        _signed(packet, "payments", "reviewer", JULY, actor="st-02", role="reviewer"),
    )
    status = area_status(project(packet, events), "payments")
    assert not status["complete"]
    assert status["problems"] == ["preparer and reviewer are the same person (firm rule)"]


def test_release_blockers_on_a_fresh_return(packet):
    blockers = release_blockers(project(packet, []))
    assert blockers == [f"area not signed: {a}" for a in SIGNED_AREAS]


def test_large_adjustment_needs_partner_signoff(packet):
    events = log(ev("adjust", ["line:Sch1.17"], payload={"from": 14400, "to": 0}, reason="eligible for employer plan"))
    state = project(packet, events)
    assert needs_partner(state, state.adjustments["Sch1.17"])   # federal effect +4,464
    assert any("Sch1.17 needs partner sign-off" in b for b in release_blockers(state))
    approved = project(packet, events + [ev("approve_adjustment", ["event:1"], actor="st-03", role="partner",
                                            id=2, at="2026-10-02T00:00:00Z")])
    assert not any("Sch1.17" in b for b in release_blockers(approved))


def test_small_adjustment_does_not_lift_the_partner_release(packet):
    release = ev("partner_release", ["return"], actor="st-03", role="partner",
                 payload=signoff_payload(project(packet, []), "return", "partner"))
    small = ev("adjust", ["line:SchB.1.6"], payload={"from": 1747, "to": 1871}, reason="2025 FX rate")
    state = project(packet, log(release, small))
    assert signoff_status(state, state.partner_release)["status"] == "signed"


def test_accepting_a_document_verifies_each_value_in_one_act(packet):
    values = {e["id"]: e["value"] for e in packet.values_by_doc["D74"]}
    events = log(ev("accept_document", ["D74"], payload={"verification_type": "agreed_to_source_document",
                                                         "values": values, "at_summary": True}))
    state = project(packet, events)
    assert len(values) == 1826
    assert all(state.verifications[ref][0].event_id == 1 for ref in values)


def test_administrator_changes_the_variance_standard(packet):
    before = run_checker(packet, project(packet, []))
    events = log(ev("set_standard", [], actor="st-05", role="firm_administrator",
                    payload={"path": "variance_review.flag_if_change_over_percent", "value": 50}))
    after = run_checker(packet, project(packet, events))
    count = lambda r: sum(1 for f in r.findings if f.rule == "R10")
    assert count(after) < count(before)
    assert packet.raw["firm"]["starter_standards"]["variance_review"]["flag_if_change_over_percent"] == 10
