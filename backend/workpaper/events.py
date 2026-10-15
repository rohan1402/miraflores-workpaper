"""Layer 2: the append-only log of what people did.

Every human act is one row: who, in which role, when, on what, what they did,
the details, why, and the log tip they were looking at when they did it.
Rows are never updated or deleted (SQLite triggers refuse it). Undo is a new
row that reverses an earlier one.

Storage is SQLite in WAL mode: one writer process, many readers, no server to run.
The packet is not stored here; it stays a read-only file.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


# Every action the log accepts. project() gives each one its meaning.
ACTIONS = {
    "disposition",          # document disposition: used, duplicate, superseded, not_extracted, partial
    "accept_document",      # accept every value of a document (or an account at its summary) in one act
    "verify",               # a person verifies values or lines with one of the firm's verification types
    "adjust",               # change a line's value without losing the original
    "undo",                 # reverse an earlier event
    "note",                 # plain note; always appends
    "review_note",          # review note; open until resolved; blocks partner release
    "resolve_review_note",
    "question",             # question to the client or a colleague
    "answer",
    "attach_evidence",      # attach a file, message or note as evidence
    "judgment_call",        # judgment, election, due diligence or penalty decision, with authority
    "sign_off",             # preparer or reviewer signs a work area (optionally with a waiver)
    "approve_adjustment",   # partner signs an adjustment with tax effect over the firm threshold
    "partner_release",      # partner signs the return once
    "set_standard",         # administrator changes a firm standard
    "view_sensitive",       # someone unmasked sensitive data
}


@dataclass(frozen=True)
class Event:
    actor: str                      # staff id (st-01) or client user id (cu-01)
    role: str                       # role at the time of the act
    action: str
    targets: tuple[str, ...]        # references: ev-0001, D10, line:F1040.26, area:business, event:12 ...
    payload: dict = field(default_factory=dict)
    reason: str | None = None
    base_tip: int = 0               # id of the newest event the actor had seen
    at: str = ""                    # ISO-8601 UTC, for "as of this date"; filled by the store if empty
    id: int = 0                     # log position, assigned in the insert transaction; replay order


class StaleTip(Exception):
    """The write was made against an old view and something relevant landed first (HTTP 409)."""

    def __init__(self, conflicting: Event):
        super().__init__(f"event {conflicting.id} ({conflicting.action}) landed first")
        self.conflicting = conflicting


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT    NOT NULL,
    actor     TEXT    NOT NULL,
    role      TEXT    NOT NULL,
    action    TEXT    NOT NULL,
    targets   TEXT    NOT NULL,   -- JSON array of references
    payload   TEXT    NOT NULL,   -- JSON object
    reason    TEXT,
    base_tip  INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE IF NOT EXISTS last_seen (
    person    TEXT PRIMARY KEY,
    event_id  INTEGER NOT NULL,
    at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    sha256        TEXT PRIMARY KEY,
    file_name     TEXT    NOT NULL,
    content_type  TEXT    NOT NULL,
    size          INTEGER NOT NULL,
    stored_by     TEXT    NOT NULL,
    stored_at     TEXT    NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# The 409 rule: (new event, events the actor had seen, newer events) -> the event that landed first, or None.
ConflictRuleFn = Callable[["Event", list["Event"], list["Event"]], "Event | None"]


class EventStore:
    """SQLite-backed event log. One instance per process; safe to share across threads.

    The store does not know the rules. It is given the conflict rule (concurrency.ConflictRule),
    which needs the packet to know which areas own a document.
    """

    def __init__(self, path: Path | str, conflict_rule: ConflictRuleFn, attachments_dir: Path | str | None = None):
        self.path = str(path)
        self.conflict_rule = conflict_rule
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self.attachments_dir = Path(attachments_dir) if attachments_dir else None

    def close(self) -> None:
        self._db.close()

    # ---- writing -------------------------------------------------------------

    def append(self, event: Event) -> Event:
        """Append one event inside a transaction and return it with its id.

        The 409 rule: if the actor's base_tip is behind the log and a newer event
        touches the same thing (see concurrency.ConflictRule), refuse with StaleTip.
        Notes and other append-only actions never conflict.

        The id is assigned here, inside the transaction, and is the replay order.
        `at` must not go backwards, so "as of a date" is always a prefix of the log;
        two events may share the same second.
        """
        if event.action not in ACTIONS:
            raise ValueError(f"unknown action {event.action!r}")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")  # take the write lock before reading the tip
            try:
                tip = self._tip()
                if event.base_tip > tip:
                    raise ValueError(f"base_tip {event.base_tip} is ahead of the log tip {tip}")
                if event.base_tip < tip:
                    log = self._rows_after(0)
                    seen = [e for e in log if e.id <= event.base_tip]
                    newer = [e for e in log if e.id > event.base_tip]
                    conflict = self.conflict_rule(event, seen, newer)
                    if conflict is not None:
                        raise StaleTip(conflict)
                at = event.at or utc_now()
                last_at = self._db.execute("SELECT MAX(at) FROM events").fetchone()[0]
                if last_at and at < last_at:
                    raise ValueError(f"event time {at} is earlier than the last event {last_at}")
                cur = self._db.execute(
                    "INSERT INTO events (at, actor, role, action, targets, payload, reason, base_tip)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (at, event.actor, event.role, event.action, json.dumps(list(event.targets)),
                     json.dumps(event.payload, sort_keys=True), event.reason, event.base_tip),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return replace(event, id=cur.lastrowid, at=at)

    # ---- reading -------------------------------------------------------------

    def tip(self) -> int:
        with self._lock:
            return self._tip()

    def all(self) -> list[Event]:
        with self._lock:
            return self._rows_after(0)

    def after(self, event_id: int) -> list[Event]:
        with self._lock:
            return self._rows_after(event_id)

    def _tip(self) -> int:
        return self._db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]

    def _rows_after(self, event_id: int) -> list[Event]:
        rows = self._db.execute("SELECT * FROM events WHERE id > ? ORDER BY id", (event_id,)).fetchall()
        return [_row_to_event(r) for r in rows]

    # ---- "since I last looked" -----------------------------------------------

    def mark_seen(self, person: str, event_id: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO last_seen (person, event_id, at) VALUES (?, ?, ?)"
                " ON CONFLICT(person) DO UPDATE SET event_id = excluded.event_id, at = excluded.at",
                (person, event_id, utc_now()),
            )

    def last_seen(self, person: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT event_id FROM last_seen WHERE person = ?", (person,)).fetchone()
        return row[0] if row else 0

    # ---- attachments (stored by content hash) --------------------------------

    def put_attachment(self, data: bytes, file_name: str, content_type: str, stored_by: str) -> str:
        if self.attachments_dir is None:
            raise RuntimeError("no attachments directory configured")
        digest = hashlib.sha256(data).hexdigest()
        target = self.attachments_dir / digest[:2] / digest
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO attachments (sha256, file_name, content_type, size, stored_by, stored_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (digest, file_name, content_type, len(data), stored_by, utc_now()),
            )
        return digest

    def attachment_meta(self, digest: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM attachments WHERE sha256 = ?", (digest,)).fetchone()
        return dict(row) if row else None


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        at=row["at"],
        actor=row["actor"],
        role=row["role"],
        action=row["action"],
        targets=tuple(json.loads(row["targets"])),
        payload=json.loads(row["payload"]),
        reason=row["reason"],
        base_tip=row["base_tip"],
    )
