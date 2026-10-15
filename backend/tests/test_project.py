"""project(packet, events): replay, undo, adjustments, sign-offs that reopen, partner release."""

from workpaper.areas import SIGNED_SCOPES, area_of_line
from workpaper.checker import run_checker
from workpaper.project import (
    adjustment_payload, area_status, covered_values, effect_view, large_adjustments, needs_partner, project,
    release_blockers, signoff_payload, signoff_status,
)

from conftest import ev, log

MARCH = "2026-03-15T00:00:00Z"   # v1 is current
APRIL = "2026-04-01T00:00:00Z"   # v2 is current (corrected Meridian 1099)
JULY = "2026-07-01T00:00:00Z"    # v3 is current (Ridgeline K-1 and state supplement, extension payment)


def adjust(packet, key, to, at="", events=(), **kw):
    """An adjust event built the way the server builds it: from = the figure on screen, effect stored."""
    state = project(packet, list(events), as_of=at or None)
    return ev("adjust", [f"line:{key}"], payload=adjustment_payload(state, key, to), at=at, **kw)


def test_empty_log_is_the_packet_as_delivered(packet):
    state = project(packet, [])
    assert state.version_id == "v3"
    assert state.tip == 0
    assert state.line_value("F1040.26") == 13000


def test_adjust_keeps_the_original_and_stores_its_effect(packet):
    events = log(adjust(packet, "F1040.26", 12000, reason="IRS transcript shows 3,000 on 1/15"))
    state = project(packet, events)
    assert state.line_value("F1040.26") == 12000
    assert state.original_value("F1040.26") == 13000
    adj = state.adjustments["F1040.26"][0]
    assert (adj.actor, adj.reason) == ("st-01", "IRS transcript shows 3,000 on 1/15")
    assert (adj.effect["federal"], adj.effect["california"]) == (1000, 0)  # a federal payment has no CA effect


def test_stored_effect_stays_when_rates_change_and_a_fresh_one_shows_beside_it(packet):
    # Adjusted in April at v2 rates; v3 changes California's adjustment rate (-0.068 to -0.042).
    events = log(adjust(packet, "Sch1.17", 0, at=APRIL))
    adj = project(packet, events).adjustments["Sch1.17"][0]
    view = effect_view(project(packet, events), adj)
    assert view["stored"]["california"] == 979   # 14,400 x 0.068: what Helen would have signed
    assert view["differs"] and view["fresh"]["california"] == 605   # 14,400 x 0.042 at v3


def test_chained_adjustments_start_from_the_figure_on_screen(packet):
    first = adjust(packet, "F1040.26", 12000)
    second = ev("adjust", ["line:F1040.26"], actor="st-02", role="reviewer",
                payload={"from": 12000, "to": 11500, "version": "v3"})
    state = project(packet, log(first, second))
    assert state.line_value("F1040.26") == 11500
    assert [a.applied for a in state.adjustments["F1040.26"]] == [True, True]


def test_undoing_an_earlier_adjustment_makes_a_later_one_stale(packet):
    first = adjust(packet, "F1040.26", 12000)
    second = ev("adjust", ["line:F1040.26"], payload={"from": 12000, "to": 11500, "version": "v3"})
    undo = ev("undo", ["event:1"], reason="wrong", payload={"undoes": {"targets": ["line:F1040.26"]}})
    state = project(packet, log(first, second, undo))
    assert state.line_value("F1040.26") == 13000      # the second was made against 12,000, which is gone
    assert [a.event_id for a in state.stale_adjustments()] == [2]


def test_undo_is_a_new_event_that_reverses_an_old_one(packet):
    events = log(
        adjust(packet, "F1040.26", 12000),
        ev("undo", ["event:1"], reason="wrong line", payload={"undoes": {"targets": ["line:F1040.26"]}}),
    )
    state = project(packet, events)
    assert state.line_value("F1040.26") == 13000
    assert state.undone == {1}
    assert len(state.events) == 2  # history keeps both


def test_replay_order_is_the_log_position_not_the_clock(packet):
    same_second = "2026-10-01T09:00:00Z"
    first = ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000}, at=same_second, id=1)
    second = ev("adjust", ["line:F1040.26"], payload={"from": 12000, "to": 11500}, at=same_second, id=2)
    assert project(packet, [second, first]).line_value("F1040.26") == 11500


def test_replay_to_any_date(packet):
    events = log(adjust(packet, "F1040.26", 12000, at="2026-05-01T00:00:00Z"))
    assert project(packet, events, as_of=APRIL).line_value("F1040.26") == 13000
    assert project(packet, events, as_of=JULY).line_value("F1040.26") == 12000
    assert project(packet, events, as_of=MARCH).version_id == "v1"


def test_adjustment_goes_stale_when_a_new_version_changes_the_line(packet):
    events = log(adjust(packet, "F8949.D.M9", 0, at=MARCH))   # made against v1's M9
    assert project(packet, events, as_of=MARCH).line_value("F8949.D.M9") == 0
    later = project(packet, events, as_of=APRIL)               # the corrected 1099 changes M9
    assert later.line_value("F8949.D.M9") == packet.lines["v2"]["F8949.D.M9"]["value"]
    assert [a.line for a in later.stale_adjustments()] == ["F8949.D.M9"]


# ---- sign-offs (D3, D8) ----------------------------------------------------------

def _signed(packet, area, level, at, actor="st-01", role="preparer", **kw):
    payload = signoff_payload(project(packet, [], as_of=at), area, level, **kw)
    target = "return" if area == "return" else f"area:{area}"
    action = "partner_release" if area == "return" else "sign_off"
    return ev(action, [target], actor=actor, role=role, payload=payload, at=at)


def test_corrected_1099_reopens_investments_and_the_release_but_not_california(packet):
    events = log(
        _signed(packet, "investments_and_digital_assets", "preparer", MARCH),
        _signed(packet, "california", "preparer", MARCH),
        _signed(packet, "wages_and_stock_compensation", "preparer", MARCH),
        _signed(packet, "return", "partner", MARCH, actor="st-03", role="partner"),
    )
    april = project(packet, events, as_of=APRIL)
    investments = area_status(april, "investments_and_digital_assets")["preparer"]
    assert investments["status"] == "reopened"
    assert (investments["signed_version"], investments["current_version"]) == ("v1", "v2")
    assert {"F8949.D.M9", "F8949.A.M6", "F8949.A.M14", "F8949.D.M14"} <= {c["key"] for c in investments["changes"]}
    assert set(investments["causes"]) == {"D31"}   # the corrected Meridian 1099
    assert area_status(april, "california")["preparer"]["status"] == "signed"
    assert area_status(april, "wages_and_stock_compensation")["preparer"]["status"] == "signed"
    release = signoff_status(april, april.partner_release)
    assert release["status"] == "reopened"         # the summary moved
    assert "summary.federal.agi" in {c["key"] for c in release["changes"]}


def test_june_k1_and_state_supplement_reopen_passthroughs_and_california_not_wages(packet):
    events = log(*(_signed(packet, a, "preparer", APRIL)
                   for a in ("wages_and_stock_compensation", "pass_throughs_and_basis", "california", "payments")))
    july = project(packet, events, as_of=JULY)
    assert area_status(july, "wages_and_stock_compensation")["preparer"]["status"] == "signed"
    assert area_status(july, "pass_throughs_and_basis")["preparer"]["status"] == "reopened"
    california = area_status(july, "california")["preparer"]
    assert california["status"] == "reopened"
    assert sorted(california["causes"]["D38"]) == [   # the Ridgeline state supplement
        "SchCA540NR.17.E", "field:Ridgeline Real Estate Fund III LP pct_CA"]


def test_extension_payment_is_named_as_its_own_cause(packet):
    events = log(_signed(packet, "payments", "preparer", APRIL))
    payments = area_status(project(packet, events, as_of=JULY), "payments")["preparer"]
    sch3_10 = next(c for c in payments["changes"] if c["key"] == "Sch3.10")
    assert sch3_10["causes"] == ["timeline:extension-2026-04-14"]   # same version as the K-1, not caused by it
    assert "D37" not in sch3_10["causes"]


# ---- California: a signature over a view, not an owner of documents ---------------

def test_the_lens_fingerprints_the_allocation_and_california_only_figures(packet):
    covered = covered_values(project(packet, []), "california")
    assert covered["household.residency"][0] == {"state": "CA", "from": "2025-01-01", "to": "2025-07-14",
                                                 "status": "resident"}
    assert covered["field:California Franchise Tax Board pay5_year"] == "2024"   # the September payment's tag
    assert covered["field:Halvorsen Data LLC box16"] == 111300.0
    assert covered["field:Ridgeline Real Estate Fund III LP pct_CA"] == 0.22    # the state supplement
    assert "asset:SAC-APPL" in covered and "FTB3885A.STU-PRINTER" in covered     # California depreciation
    assert "F540NR.72" in covered                                                # FTB payments
    # Computed California tax and the refund belong to the bottom line, not the lens.
    assert "F540NR.64" not in covered and "F540NR.97" not in covered
    assert {"total_tax", "balance_due"} <= set(packet.version_by_id["v3"]["summary"]["california"])


def test_wages_fingerprints_box_1_and_box_16_together(packet):
    covered = covered_values(project(packet, []), "wages_and_stock_compensation")
    assert {"F1040.1a", "SchCA540NR.1.E"} <= set(covered)


def test_adjusting_the_box_16_figure_lifts_both_signatures(packet):
    events = log(
        _signed(packet, "wages_and_stock_compensation", "preparer", JULY),
        _signed(packet, "california", "preparer", JULY),
        adjust(packet, "SchCA540NR.1.E", 129569, reason="only 22,469 earned before the move"),
    )
    state = project(packet, events)
    for scope in ("wages_and_stock_compensation", "california"):
        status = area_status(state, scope)["preparer"]
        assert status["status"] == "reopened"
        assert status["causes"] == {"event:3": ["SchCA540NR.1.E"]}


def test_an_unsigned_lens_blocks_the_partner_release(packet):
    events = []
    for area in SIGNED_SCOPES:
        if area == "california":
            continue
        events.append(_signed(packet, area, "preparer", JULY))
        events.append(_signed(packet, area, "reviewer", JULY, actor="st-02", role="reviewer"))
    assert release_blockers(project(packet, log(*events))) == ["area not signed: california"]


def test_tax_computation_lines_belong_to_the_return():
    assert area_of_line("F6251.11") == "return"   # AMT moves with everything
    assert area_of_line("F1040.1a") == "wages_and_stock_compensation"
    assert area_of_line("F1040.13") == "return"   # not F1040.1x wages
    assert area_of_line("Sch2.4") == "business"   # SE tax


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
    assert release_blockers(project(packet, [])) == [f"area not signed: {a}" for a in SIGNED_SCOPES]


# ---- partner release (D10) -------------------------------------------------------

def test_release_lists_and_approves_the_large_adjustments_in_one_act(packet):
    sehi = adjust(packet, "Sch1.17", 0, reason="eligible for employer plan")   # stored federal effect +4,464
    state = project(packet, log(sehi))
    assert needs_partner(state.adjustments["Sch1.17"][0])
    assert not any("Sch1.17" in b for b in release_blockers(state))           # not a blocker: the release approves it
    release = ev("partner_release", ["return"], actor="st-03", role="partner",
                 payload=signoff_payload(state, "return", "partner"))
    assert release.payload["approves"] == [1]
    released = project(packet, log(sehi, release))
    assert 1 in released.partner_approvals
    assert signoff_status(released, released.partner_release)["status"] == "signed"


WAIVED = [{"id": "ANSWER_BARS_DEDUCTION:Sch1.17", "federal": 4464, "california": 605},
          {"id": "DUPLICATE_PAGE:D23#page3", "federal": 919, "california": 80}]


def test_large_waived_errors_reach_the_partner_release(packet):
    waiver = ev("sign_off", ["area:business"], payload=signoff_payload(
        project(packet, []), "business", "preparer", waiver="Open with Erik.", waived=WAIVED))
    state = project(packet, log(waiver))
    assert not any("business" in b and "preparer" in b for b in release_blockers(state))  # a waiver counts as signed
    release = signoff_payload(state, "return", "partner")
    assert release["waivers"] == ["ANSWER_BARS_DEDUCTION:Sch1.17"]       # only the one over 1,000
    assert "waived.ANSWER_BARS_DEDUCTION:Sch1.17" in release["covered"]


def test_a_large_waiver_after_the_release_reopens_it(packet):
    release = ev("partner_release", ["return"], actor="st-03", role="partner",
                 payload=signoff_payload(project(packet, []), "return", "partner"))
    waiver = ev("sign_off", ["area:business"], payload=signoff_payload(
        project(packet, []), "business", "preparer", waiver="Open with Erik.", waived=WAIVED))
    state = project(packet, log(release, waiver))
    status = signoff_status(state, state.partner_release)
    assert status["status"] == "reopened"
    assert status["causes"] == {"event:2": ["waived.ANSWER_BARS_DEDUCTION:Sch1.17"]}


def test_partner_threshold_uses_the_stored_effect(packet):
    # Car and truck cut by 3,000 in March: at v1 rates that is +918 federal, under the threshold.
    # At v3 rates the same cut would be +1,065. The stored figure is what was signed, so it decides.
    events = log(adjust(packet, "SchC.9", 5260, at=MARCH))
    state = project(packet, events)
    adj = state.adjustments["SchC.9"][0]
    assert adj.effect["federal"] == 918
    assert effect_view(state, adj)["fresh"]["federal"] == 1065
    assert large_adjustments(state) == []


def test_expense_adjustments_raise_tax(packet):
    # A lower expense means more profit: the stored effect matches the checker's E6 estimate.
    adj = project(packet, log(adjust(packet, "SchC.9", 5670))).adjustments["SchC.9"][0]
    assert (adj.effect["federal"], adj.effect["california"]) == (919, 80)


def test_small_adjustment_does_not_lift_the_partner_release(packet):
    release = ev("partner_release", ["return"], actor="st-03", role="partner",
                 payload=signoff_payload(project(packet, []), "return", "partner"))
    small = ev("adjust", ["line:SchB.1.6"], payload=adjustment_payload(project(packet, []), "SchB.1.6", 1871),
               reason="2025 FX rate")
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
