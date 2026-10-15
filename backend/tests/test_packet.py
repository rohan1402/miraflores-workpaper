"""Layer 1: the packet loads as delivered and nothing ever changes it."""

import hashlib
import json

from workpaper.checker import run_checker
from workpaper.packet import PACKET_PATH, json_pointer, ref_kind
from workpaper.project import project

from conftest import ev, log


def test_loads_as_delivered(packet):
    assert packet.sha256 == hashlib.sha256(PACKET_PATH.read_bytes()).hexdigest()
    assert len(packet.documents) == 74
    assert len(packet.values) == 3012
    assert [v["version"] for v in packet.versions] == ["v1", "v2", "v3"]
    assert len(packet.lines["v3"]) == 627


def test_projection_and_checker_never_change_the_packet(packet):
    events = log(
        ev("adjust", ["line:F1040.26"], payload={"from": 13000, "to": 12000}, reason="IRS transcript"),
        ev("disposition", ["D10"], payload={"disposition": "duplicate", "of": "D09"}),
    )
    run_checker(packet, project(packet, events))
    assert packet.raw == json.loads(PACKET_PATH.read_text())


def test_reference_kinds():
    assert ref_kind("ev-0001") == "value"
    assert ref_kind("D31") == "document"
    assert ref_kind("doc:D31#page32") == "page"
    assert ref_kind("qa-41") == "client"
    assert ref_kind("py:/carryovers_into_2025/capital_loss_short") == "prior_year"
    assert ref_kind("line:F1040.26") == "line"
    assert ref_kind("area:business") == "area"


def test_resolves_packet_references(packet):
    assert packet.resolve("D31")["marked_corrected"] is True
    assert "page 32" in packet.resolve("doc:D31#page32")["printed_content"]
    assert packet.resolve("qa-41")["answer"].startswith("Paid January 14")
    assert packet.resolve("ref:fx.SEK.2025_average") == 9.86
    assert packet.resolve("agency:/ftb_account/tax_year_2025_payments/0")["amount"] == 3500
    assert json_pointer({"a/b": {"c": 1}}, "/a~1b/c") == 1


def test_version_at_follows_the_season(packet):
    assert packet.version_at("2026-03-10T00:00:00Z")["version"] == "v1"
    assert packet.version_at("2026-04-01T00:00:00Z")["version"] == "v2"
    assert packet.version_at(None)["version"] == "v3"
