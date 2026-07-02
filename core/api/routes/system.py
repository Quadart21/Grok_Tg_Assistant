"""Системные маршруты: статус, логи."""

from __future__ import annotations

from fastapi import FastAPI

from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/status")
    def api_status() -> dict:
        return service.get_status()

    @app.get("/api/logs")
    def api_logs(offset: int = 0) -> dict:
        logs = service.get_logs()
        return {"lines": logs[offset:], "total": len(logs)}
