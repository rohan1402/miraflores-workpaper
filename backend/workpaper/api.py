"""FastAPI app: one long-lived process holding the packet in memory and the event store open.

- Reads rebuild state with project() and the checker (cached until the log tip moves) and
  return what views.py builds. Every JSON response passes through the masker on its way out.
- Writes are POST /api/actions: prepare (server computes everything derived), validate (firm
  rules), append (409 if stale), then publish to the live streams.
- Unmasked values leave only through POST /api/unmask, which needs clearance and logs a
  view_sensitive event first. Attachment downloads count as unmasked views.
- Identity comes from the role switcher (cookie wp_person, or header X-Person). There is no
  real authentication in this prototype; everything after "who you are" is enforced here.

Run locally:  cd backend && ../.venv/bin/uvicorn workpaper.api:app --reload
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import views
from .actions import Refusal, prepare, validate
from .areas import SIGNED_SCOPES
from .checker import RULES, CheckResult, run_checker
from .concurrency import ConflictRule
from .events import Event, EventStore, StaleTip
from .live import Broadcaster, event_stream
from .masking import Masker, reveal
from .packet import PACKET_PATH, REPO_ROOT, Packet, load_packet
from .project import State, project
from .roles import can_unmask, home_config, is_staff, people, verbs

DEFAULT_DB = REPO_ROOT / "var" / "workpaper.db"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
COOKIE = "wp_person"


class ActionIn(BaseModel):
    action: str
    targets: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    reason: str | None = None
    base_tip: int                 # the log tip the person was looking at


class SessionIn(BaseModel):
    person: str


class SeenIn(BaseModel):
    event_id: int


class UnmaskIn(BaseModel):
    ref: str                      # ev id, household:<id>[.field], doc:<id>#page<n>, household.bank_account


class Snapshots:
    """project() and the checker are pure, so their result only changes when the workpaper changes.

    One unmasked projection, masked on the way out. It is keyed on the content tip: the newest
    event that is not an unmask record, so viewing an SSN does not rebuild the return.
    """

    def __init__(self, packet: Packet, store: EventStore):
        self.packet, self.store = packet, store
        self._lock = threading.Lock()
        self._tip = -1
        self._state: State | None = None
        self._result: CheckResult | None = None
        self.builds = 0

    def get(self) -> tuple[State, CheckResult]:
        with self._lock:
            tip = self.store.content_tip()
            if tip != self._tip:
                self._state = project(self.packet, self.store.all())
                self._result = run_checker(self.packet, self._state)
                self._tip = tip
                self.builds += 1
            return self._state, self._result


def create_app(packet_path: Path | str = PACKET_PATH, db_path: Path | str | None = None,
               heartbeat_seconds: float = 15.0) -> FastAPI:
    db_path = Path(db_path or os.environ.get("WORKPAPER_DB", DEFAULT_DB))
    packet = load_packet(packet_path)
    scopes = ConflictRule(packet)
    store = EventStore(db_path, scopes, attachments_dir=db_path.parent / "attachments")
    masker = Masker(packet)
    everyone = people(packet)
    household_clients = set(packet.client_users)
    live = Broadcaster()
    snapshots = Snapshots(packet, store)

    class MaskedJSON(JSONResponse):
        """Every JSON response is masked on the way out. Only the unmask endpoint bypasses it."""
        def render(self, content) -> bytes:
            return super().render(masker(content))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        live.attach(asyncio.get_running_loop())
        yield
        store.close()

    app = FastAPI(title="MiraFlores Workpaper", lifespan=lifespan, default_response_class=MaskedJSON)
    app.state.snapshots = snapshots

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return MaskedJSON(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Refusal)
    async def refused(request: Request, exc: Refusal):
        return MaskedJSON(status_code=exc.status, content={"refused": exc.reasons})

    @app.exception_handler(StaleTip)
    async def stale(request: Request, exc: StaleTip):
        # 409: show the event that landed first, so the person can look again before acting.
        return MaskedJSON(status_code=409, content={"conflict": views.event_view(exc.conflicting), "tip": store.tip()})

    # ---- who is acting --------------------------------------------------------

    def current_person(request: Request) -> dict:
        person_id = request.headers.get("x-person") or request.cookies.get(COOKIE)
        if person_id not in everyone:
            raise HTTPException(401, "Pick a person in the role switcher first.")
        return everyone[person_id]

    def workpaper_reader(person: dict = Depends(current_person)) -> dict:
        """Staff and the examiner read the workpaper. Clients have their own question surface (D1)."""
        if person["role"] == "client":
            raise HTTPException(403, "Clients use the question surface, not the workpaper.")
        return person

    def publish(e: Event) -> None:
        live.publish(views.event_view(e))

    # ---- session and people ---------------------------------------------------

    @app.get("/api/health")
    def health():
        state, _ = snapshots.get()
        return {"packet": packet.raw["packet"]["name"], "packet_sha256": packet.sha256,
                "tax_year": packet.tax_year, "current_version": state.version_id, "log_tip": state.tip}

    @app.get("/api/people")
    def list_people():
        return [{k: p[k] for k in ("id", "name", "role")} | {"clearance": bool(p.get("sensitive_data_clearance"))}
                for p in everyone.values()]

    @app.post("/api/session")
    def start_session(body: SessionIn):
        if body.person not in everyone:
            raise HTTPException(404, "No such person.")
        response = MaskedJSON(content=_me(everyone[body.person]))
        # Kept for 30 days, so the person survives a browser restart (D12: HttpOnly, SameSite=Lax).
        response.set_cookie(COOKIE, body.person, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
        return response

    @app.get("/api/me")
    def me(person: dict = Depends(current_person)):
        return _me(person)

    def _me(person: dict) -> dict:
        return {"person": {k: person[k] for k in ("id", "name", "role")},
                "clearance": can_unmask(person), "verbs": verbs(person), "config": home_config(person),
                "last_seen": store.last_seen(person["id"]), "tip": store.tip()}

    # ---- reading the workpaper ------------------------------------------------

    @app.get("/api/return")
    def the_return(person: dict = Depends(workpaper_reader)):
        state, result = snapshots.get()
        return views.home(packet, state, result, scopes, person)

    @app.get("/api/areas/{area}")
    def area(area: str, person: dict = Depends(workpaper_reader)):
        if area not in SIGNED_SCOPES:
            raise HTTPException(404, f"No area {area}.")
        state, result = snapshots.get()
        return views.area_view(packet, state, result, scopes, area)

    @app.get("/api/lines/{key}")
    def line(key: str, person: dict = Depends(workpaper_reader)):
        state, result = snapshots.get()
        if key not in state.lines:
            raise HTTPException(404, f"No line {key} on {state.version_id}.")
        return views.line_trace(packet, state, result, key)

    @app.get("/api/documents")
    def documents(person: dict = Depends(workpaper_reader)):
        state, result = snapshots.get()
        return views.document_index(packet, state, result, scopes)

    @app.get("/api/documents/{doc_id}")
    def document(doc_id: str, person: dict = Depends(workpaper_reader)):
        if doc_id not in packet.documents:
            raise HTTPException(404, f"No document {doc_id}.")
        state, result = snapshots.get()
        return views.document_view(packet, state, result, scopes, doc_id)

    @app.get("/api/findings")
    def findings(area: str | None = None, status: str | None = None, person: dict = Depends(workpaper_reader)):
        _, result = snapshots.get()
        return views.findings_view(result, scopes, area=area, status=status)

    @app.get("/api/checker/summary")
    def checker_summary(person: dict = Depends(workpaper_reader)):
        _, result = snapshots.get()
        by_rule = Counter(f.rule for f in result.findings if f.status == "open")
        return {
            "rules": {rule: {"title": title, "open": by_rule.get(rule, 0)} for rule, (title, _) in RULES.items()},
            "open": sum(by_rule.values()),
            "net_effect": result.net_effect,
            "ties": len(result.reconciliations),
        }

    @app.get("/api/events")
    def events(after: int = 0, person: dict = Depends(workpaper_reader)):
        return [views.event_view(e) for e in store.after(after)]

    # ---- since I last looked --------------------------------------------------

    @app.get("/api/since")
    def since(person: dict = Depends(workpaper_reader)):
        """What others changed since this person last looked. Unmask records are audit, not changes."""
        last = store.last_seen(person["id"])
        return {"last_seen": last, "tip": store.tip(),
                "events": [views.event_view(e) for e in store.after(last)
                           if e.actor != person["id"] and e.action != "view_sensitive"]}

    @app.get("/api/audit/sensitive-views")
    def sensitive_views(person: dict = Depends(current_person)):
        """The view log: every unmasked view, who and when. For the partner and the administrator."""
        if person["role"] not in ("partner", "firm_administrator"):
            raise HTTPException(403, "The view log is for the partner and the firm administrator.")
        return [views.event_view(e) for e in store.all() if e.action == "view_sensitive"]

    @app.post("/api/seen")
    def seen(body: SeenIn, person: dict = Depends(current_person)):
        store.mark_seen(person["id"], min(body.event_id, store.tip()))
        return {"last_seen": store.last_seen(person["id"])}

    # ---- writing --------------------------------------------------------------

    @app.post("/api/actions")
    def act(body: ActionIn, person: dict = Depends(current_person)):
        if body.action == "view_sensitive":
            raise Refusal(422, ["Unmask through /api/unmask, which logs the view."])
        state, result = snapshots.get()
        event = prepare(packet, state, result, scopes, person, body.action, body.targets, body.payload, body.reason,
                        body.base_tip)
        validate(packet, state, result, scopes, person, event)
        try:
            stored = store.append(event)
        except ValueError as exc:
            raise Refusal(422, [str(exc)])
        publish(stored)
        return {"event": views.event_view(stored), "tip": stored.id}

    @app.post("/api/unmask")
    def unmask(body: UnmaskIn, person: dict = Depends(current_person)):
        if not can_unmask(person):
            raise HTTPException(403, f"{person['name']} has no sensitive-data clearance.")
        value = reveal(packet, body.ref)
        if value is None:
            raise HTTPException(404, f"Nothing to unmask at {body.ref}.")
        logged = _log_view(person, body.ref)
        # Deliberately not masked: this is the one door out, and it is logged above.
        return JSONResponse({"ref": body.ref, "value": value, "logged_event": logged.id})

    def _log_view(person: dict, ref: str) -> Event:
        stored = store.append(Event(actor=person["id"], role=person["role"], action="view_sensitive",
                                    targets=(ref,), payload={}, base_tip=store.tip()))
        publish(stored)
        return stored

    # ---- attachments (stored by content hash) ---------------------------------

    @app.post("/api/attachments")
    def upload(file: UploadFile = File(...), targets: str = Form(...), note: str = Form(""),
               base_tip: int = Form(0), person: dict = Depends(current_person)):
        data = file.file.read()
        state, result = snapshots.get()
        refs = [t.strip() for t in targets.split(",") if t.strip()]
        event = prepare(packet, state, result, scopes, person, "attach_evidence", refs, {}, None, base_tip)
        digest = store.put_attachment(data, file.filename or "upload", file.content_type or "application/octet-stream",
                                      person["id"])
        event = Event(**{**event.__dict__, "payload": {"sha256": digest, "file_name": file.filename,
                                                       "content_type": file.content_type, "size": len(data),
                                                       "text": note}})
        validate(packet, state, result, scopes, person, event)
        stored = store.append(event)
        publish(stored)
        return {"event": views.event_view(stored), "sha256": digest}

    @app.get("/api/attachments/{digest}")
    def download(digest: str, person: dict = Depends(current_person)):
        meta = store.attachment_meta(digest)
        if meta is None:
            raise HTTPException(404, "No such attachment.")
        if person["role"] == "client":
            # One household: what either client uploaded, both clients can open.
            if meta["stored_by"] not in household_clients:
                raise HTTPException(403, "Clients can open only what the household uploaded.")
        elif can_unmask(person):
            _log_view(person, f"attachment:{digest}")   # a file cannot be masked: a download is an unmasked view
        else:
            raise HTTPException(403, f"{person['name']} has no sensitive-data clearance to open files.")
        return FileResponse(store.attachments_dir / digest[:2] / digest, media_type=meta["content_type"],
                            filename=meta["file_name"])

    # ---- the client's question surface ----------------------------------------

    @app.get("/api/client/questions")
    def client_questions(person: dict = Depends(current_person)):
        if not (person["role"] == "client" or is_staff(person)):
            raise HTTPException(403, "Not available in this role.")
        state, _ = snapshots.get()
        questions = [e for e in state.events if e.action == "question" and e.payload.get("to") == "client"]
        answers = [e for e in state.events if e.action == "answer"]
        return {"questions": [
            {"question": views.event_view(q),
             "answers": [views.event_view(a) for a in answers if f"event:{q.id}" in a.targets]}
            for q in questions]}

    # ---- live updates ---------------------------------------------------------

    @app.get("/api/stream")
    async def stream(request: Request, after: int | None = None, person: dict = Depends(current_person)):
        last = after if after is not None else int(request.headers.get("last-event-id") or store.tip())
        queue = live.subscribe()

        async def backlog(last_id: int) -> list[dict]:
            return [views.event_view(e) for e in await run_in_threadpool(store.after, last_id)]

        async def body():
            try:
                async for chunk in event_stream(backlog, queue, last, lambda e: _visible(person, e), masker,
                                                request.is_disconnected, heartbeat_seconds):
                    yield chunk
            finally:
                live.unsubscribe(queue)

        return StreamingResponse(body(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- the frontend (one process, one link) ---------------------------------
    # Registered last, so every /api route above wins. The built files hold no client data.
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


def _visible(person: dict, event: dict) -> bool:
    """Staff see every change (unmask records stay in the view log). A client sees questions sent
    to the client and their own acts. The examiner's view is frozen at filing: no live events."""
    if event["action"] == "view_sensitive":
        return False
    if is_staff(person):
        return True
    if person["role"] == "client":
        return event["actor"] == person["id"] or (event["action"] == "question"
                                                  and event["payload"].get("to") == "client")
    return False


app = create_app()
