"""Рассылка и движок outreach."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.api.schemas import StartBody
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/engine")
    def api_engine() -> dict:
        return service.get_engine_stats()

    @app.post("/api/engine/start")
    def api_start(body: StartBody) -> dict:
        targets = [t.strip().lstrip("@") for t in body.targets.splitlines() if t.strip()]
        account_ids = body.account_ids or None
        ok, msg = service.start_engine(
            targets,
            account_ids,
            body.extra_context,
            body.enable_dialog,
            body.resume_existing,
            body.resume_only,
        )
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True}

    @app.post("/api/engine/stop")
    def api_stop() -> dict:
        service.stop_engine()
        return {"ok": True}
