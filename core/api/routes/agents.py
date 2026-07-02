"""AI-агенты."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.api.schemas import AgentBody, AgentStartBody
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/agents")
    def api_agents() -> list:
        return service.get_agents()

    @app.post("/api/agents")
    def api_save_agent(body: AgentBody) -> dict:
        try:
            service.save_agent(body.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/agents/{account_id}")
    def api_delete_agent(account_id: str) -> dict:
        if not service.delete_agent(account_id):
            raise HTTPException(404, "Агент не найден")
        return {"ok": True}

    @app.get("/api/agents/stats")
    def api_agent_stats() -> dict:
        return service.get_agent_stats()

    @app.post("/api/agents/start")
    def api_start_agents(body: AgentStartBody) -> dict:
        account_ids = body.account_ids or None
        ok, msg = service.start_agents(account_ids)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True}

    @app.post("/api/agents/stop")
    def api_stop_agents() -> dict:
        service.stop_agents()
        return {"ok": True}
