"""The FastAPI process boots, holds the packet, opens the event store, and serves the checker summary."""

from fastapi.testclient import TestClient

from workpaper.api import create_app


def test_health_and_checker_summary(tmp_path, packet):
    with TestClient(create_app(db_path=tmp_path / "workpaper.db")) as client:
        health = client.get("/api/health").json()
        assert health["packet_sha256"] == packet.sha256
        assert (health["current_version"], health["log_tip"]) == ("v3", 0)

        summary = client.get("/api/checker/summary").json()
        assert summary["net_effect"]["federal"] == -8753
        assert set(summary["rules"]) == {f"R{n:02d}" for n in range(1, 14)}
