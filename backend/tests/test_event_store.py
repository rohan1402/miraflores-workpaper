"""Layer 2: the event log is append-only, ordered, and refuses stale sign-offs and adjustments (409)."""

import sqlite3

import pytest

from workpaper.concurrency import ConflictRule
from workpaper.events import StaleTip

from conftest import ev


def test_append_assigns_ids_and_time(store):
    a = store.append(ev("note", ["line:F1040.26"], payload={"text": "check transcript"}))
    b = store.append(ev("note", ["D10"], payload={"text": "phone photo"}, base_tip=1))
    assert (a.id, b.id) == (1, 2)
    assert a.at and b.at >= a.at
    assert [e.id for e in store.all()] == [1, 2]
    assert store.tip() == 2


def test_the_database_refuses_edits_and_deletes(store):
    store.append(ev("note", ["D10"], payload={"text": "x"}))
    db = sqlite3.connect(store.path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE events SET reason = 'changed' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM events WHERE id = 1")
    db.close()


def test_unknown_action_is_refused(store):
    with pytest.raises(ValueError):
        store.append(ev("delete_everything", ["D10"]))


def test_signoff_against_a_stale_view_gets_409_with_the_event_that_landed_first(store):
    # Priya and Daniel both look at the log at tip 0.
    adjustment = store.append(ev("adjust", ["line:SchC.9"], payload={"from": 8260, "to": 5670}, reason="duplicate page"))
    # Daniel signs Business without having seen the adjustment.
    with pytest.raises(StaleTip) as err:
        store.append(ev("sign_off", ["area:business"], actor="st-02", role="reviewer",
                        payload={"level": "reviewer"}, base_tip=0))
    assert err.value.conflicting.id == adjustment.id
    # After refreshing (base_tip=1) the same sign-off goes in.
    assert store.append(ev("sign_off", ["area:business"], actor="st-02", role="reviewer",
                           payload={"level": "reviewer"}, base_tip=1)).id == 2


def test_notes_always_append(store):
    store.append(ev("adjust", ["line:SchC.9"], payload={"from": 8260, "to": 5670}))
    note = store.append(ev("note", ["line:SchC.9"], actor="st-02", payload={"text": "why?"}, base_tip=0))
    assert note.id == 2


def test_notes_and_views_do_not_move_the_conflict_tip(store):
    # Daniel looks at Payments at tip 0. Meanwhile Priya writes a note and Marcus unmasks an SSN.
    store.append(ev("note", ["line:F1040.26"], payload={"text": "check transcript"}))
    store.append(ev("view_sensitive", ["ev-0034"], actor="st-04", payload={"field": "employee_ssn"}, base_tip=1))
    signed = store.append(ev("sign_off", ["area:payments"], actor="st-02", role="reviewer",
                             payload={"level": "reviewer"}, base_tip=0))
    assert signed.id == 3


def test_a_field_overlaps_every_area_that_owns_its_document(store):
    # Verifying Halvorsen box 16 (a California wage figure) after Daniel looked blocks his California sign-off.
    verify = store.append(ev("verify", ["ev-0047"], payload={"verification_type": "agreed_to_source_document"}))
    with pytest.raises(StaleTip) as err:
        store.append(ev("sign_off", ["area:california"], actor="st-02", role="reviewer",
                        payload={"level": "reviewer"}, base_tip=0))
    assert err.value.conflicting.id == verify.id
    with pytest.raises(StaleTip):
        store.append(ev("sign_off", ["area:wages_and_stock_compensation"], actor="st-02", role="reviewer",
                        payload={"level": "reviewer"}, base_tip=0))


def test_a_field_that_feeds_no_california_figure_does_not_touch_the_lens(store):
    store.append(ev("verify", ["ev-0035"], payload={"verification_type": "agreed_to_source_document"}))  # box 1
    signed = store.append(ev("sign_off", ["area:california"], actor="st-02", role="reviewer",
                             payload={"level": "reviewer"}, base_tip=0))
    assert signed.id == 2


def test_california_owns_no_documents(packet):
    owners = ConflictRule(packet).owners
    assert not any("california" in areas for areas in owners.values())
    assert owners["D09"] == {"wages_and_stock_compensation", "payments", "deductions_and_credits"}
    assert "pass_throughs_and_basis" in owners["D38"]   # the state supplement goes with its K-1


def test_california_line_adjustment_overlaps_wages_and_california(store):
    store.append(ev("adjust", ["line:SchCA540NR.1.E"], payload={"from": 218400, "to": 129569}))
    for area in ("california", "wages_and_stock_compensation"):
        with pytest.raises(StaleTip):
            store.append(ev("sign_off", [f"area:{area}"], actor="st-02", role="reviewer",
                            payload={"level": "reviewer"}, base_tip=0))
    # Business does not own that line: no conflict.
    assert store.append(ev("sign_off", ["area:business"], actor="st-02", role="reviewer",
                           payload={"level": "reviewer"}, base_tip=0)).id == 2


def test_change_in_another_area_does_not_block(store):
    store.append(ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000}))  # payments
    signed = store.append(ev("sign_off", ["area:business"], payload={"level": "preparer"}, base_tip=0))
    assert signed.id == 2


def test_two_people_adjusting_the_same_line(store):
    store.append(ev("adjust", ["line:SchA.5b"], payload={"from": 13420, "to": 6508}))
    with pytest.raises(StaleTip):
        store.append(ev("adjust", ["line:SchA.5b"], actor="st-04", payload={"from": 13420, "to": 13000}, base_tip=0))


def _release(base_tip):
    return ev("partner_release", ["return"], actor="st-03", role="partner", base_tip=base_tip,
              payload={"level": "partner", "version": "v3", "covered": {}, "fingerprint": "", "approves": []})


def test_partner_release_is_not_blocked_by_work_that_does_not_change_it(store):
    # Priya verifying a Brightpath lot all afternoon must not give Helen a 409.
    store.append(ev("verify", ["ev-1100"], payload={"verification_type": "agreed_to_source_document"}))
    store.append(ev("note", ["D74"], payload={"text": "lots tie to summary"}, base_tip=1))
    assert store.append(_release(base_tip=0)).id == 3


def test_partner_release_is_refused_after_a_new_review_note(store):
    note = store.append(ev("review_note", ["line:SchC.9"], actor="st-02", role="reviewer", payload={"text": "?"}))
    with pytest.raises(StaleTip) as err:
        store.append(_release(base_tip=0))
    assert err.value.conflicting.id == note.id


def test_partner_release_is_refused_after_a_large_adjustment(store, packet):
    from workpaper.project import adjustment_payload, project
    big = store.append(ev("adjust", ["line:Sch1.17"], payload=adjustment_payload(project(packet, []), "Sch1.17", 0)))
    with pytest.raises(StaleTip) as err:
        store.append(_release(base_tip=0))
    assert err.value.conflicting.id == big.id


def test_base_tip_cannot_be_ahead_of_the_log(store):
    with pytest.raises(ValueError):
        store.append(ev("note", ["D10"], base_tip=5))


def test_log_stays_in_time_order(store):
    store.append(ev("note", ["D10"], at="2026-06-01T00:00:00Z"))
    with pytest.raises(ValueError, match="earlier"):
        store.append(ev("note", ["D10"], at="2026-05-01T00:00:00Z", base_tip=1))


def test_last_seen_survives_reopening(store, tmp_path):
    store.append(ev("note", ["D10"]))
    store.mark_seen("st-02", 1)
    assert store.last_seen("st-02") == 1
    assert store.last_seen("st-03") == 0


def test_attachments_are_stored_once_by_content_hash(store):
    a = store.put_attachment(b"bank statement line", "stmt.pdf", "application/pdf", "st-01")
    b = store.put_attachment(b"bank statement line", "copy.pdf", "application/pdf", "st-02")
    assert a == b
    assert store.attachment_meta(a)["file_name"] == "stmt.pdf"
    assert (store.attachments_dir / a[:2] / a).read_bytes() == b"bank statement line"
