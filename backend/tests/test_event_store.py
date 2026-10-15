"""Layer 2: the event log is append-only, ordered, and refuses stale sign-offs and adjustments (409)."""

import sqlite3

import pytest

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


def test_change_in_another_area_does_not_block(store):
    store.append(ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000}))  # payments
    signed = store.append(ev("sign_off", ["area:business"], payload={"level": "preparer"}, base_tip=0))
    assert signed.id == 2


def test_two_people_adjusting_the_same_line(store):
    store.append(ev("adjust", ["line:SchA.5b"], payload={"from": 13420, "to": 6508}))
    with pytest.raises(StaleTip):
        store.append(ev("adjust", ["line:SchA.5b"], actor="st-04", payload={"from": 13420, "to": 13000}, base_tip=0))


def test_partner_release_is_stale_after_any_change(store):
    store.append(ev("verify", ["ev-1045"], payload={"verification_type": "agreed_to_source_document"}))
    with pytest.raises(StaleTip):
        store.append(ev("partner_release", ["return"], actor="st-03", role="partner", base_tip=0))


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
