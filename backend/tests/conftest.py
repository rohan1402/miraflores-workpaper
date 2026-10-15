import pytest

from workpaper.checker import run_checker
from workpaper.events import Event, EventStore
from workpaper.packet import load_packet
from workpaper.project import project


@pytest.fixture(scope="session")
def packet():
    return load_packet()


@pytest.fixture(scope="session")
def result(packet):
    """The checker run on the packet as delivered, with no human events yet."""
    return run_checker(packet, project(packet, []))


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "events.db", attachments_dir=tmp_path / "attachments")
    yield s
    s.close()


def ev(action, targets, actor="st-01", role="preparer", payload=None, reason=None, base_tip=0, at="", id=0):
    """Shorthand for building an event in tests. Pass id and at to use it without a store."""
    return Event(actor=actor, role=role, action=action, targets=tuple(targets),
                 payload=payload or {}, reason=reason, base_tip=base_tip, at=at, id=id)


def log(*events):
    """Number a list of events as the store would (ids 1..n), for projecting without a database."""
    from dataclasses import replace
    return [replace(e, id=i, at=e.at or f"2026-10-01T00:00:{i:02d}Z") for i, e in enumerate(events, start=1)]


def find(result, rule, ref):
    """The one finding of `rule` that points at `ref` (in its targets or evidence)."""
    hits = [f for f in result.findings if f.rule == rule and (ref in f.targets or ref in f.evidence)]
    assert len(hits) == 1, f"expected one {rule} finding on {ref}, got {[f.id for f in hits]}"
    return hits[0]
