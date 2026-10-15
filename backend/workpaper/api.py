"""FastAPI app: one long-lived process holding the packet in memory and the event store open.

Step 1 exposes only what carries no sensitive data. Findings, documents and the
return come in step 2, behind server-side role masking.

Run locally:  cd backend && ../.venv/bin/uvicorn workpaper.api:app --reload
"""

from __future__ import annotations

import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .checker import RULES, run_checker
from .events import EventStore
from .packet import PACKET_PATH, REPO_ROOT, load_packet
from .project import project

DEFAULT_DB = REPO_ROOT / "var" / "workpaper.db"


def create_app(packet_path: Path | str = PACKET_PATH, db_path: Path | str | None = None) -> FastAPI:
    db_path = db_path or os.environ.get("WORKPAPER_DB", DEFAULT_DB)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.packet = load_packet(packet_path)
        app.state.store = EventStore(db_path, attachments_dir=Path(db_path).parent / "attachments")
        yield
        app.state.store.close()

    app = FastAPI(title="MiraFlores Workpaper", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        packet = app.state.packet
        state = project(packet, app.state.store.all())
        return {
            "packet": packet.raw["packet"]["name"],
            "packet_sha256": packet.sha256,
            "tax_year": packet.tax_year,
            "current_version": state.version_id,
            "log_tip": state.tip,
        }

    @app.get("/api/checker/summary")
    def checker_summary():
        packet = app.state.packet
        result = run_checker(packet, project(packet, app.state.store.all()))
        by_rule = Counter(f.rule for f in result.findings if f.status == "open")
        return {
            "rules": {rule: {"title": title, "open": by_rule.get(rule, 0)} for rule, (title, _) in RULES.items()},
            "open": sum(by_rule.values()),
            "net_effect": result.net_effect,
            "ties": len(result.reconciliations),
        }

    return app


app = create_app()
