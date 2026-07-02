"""Диалоги и настройки переписок."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.api.schemas import ClearDialogsBody, DialogSettingsBody, DialogUpdateBody
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/dialogs")
    def api_dialogs() -> list:
        return service.get_dialogs()

    @app.post("/api/dialogs/clear-all")
    def api_clear_all_dialogs(body: ClearDialogsBody) -> dict:
        count = service.clear_dialogs(body.account_id or None, body.delete_completely)
        return {"ok": True, "cleared": count}

    @app.post("/api/dialogs/{key:path}/clear-memory")
    def api_clear_dialog_memory(key: str) -> dict:
        if not service.clear_dialog_memory(key):
            raise HTTPException(404, "Диалог не найден")
        return {"ok": True}

    @app.get("/api/dialogs/{key:path}")
    def api_dialog_detail(key: str) -> dict:
        detail = service.get_dialog_detail(key)
        if not detail:
            raise HTTPException(404, "Диалог не найден")
        return detail

    @app.patch("/api/dialogs/{key:path}")
    def api_dialog_update(key: str, body: DialogUpdateBody) -> dict:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        if not service.update_dialog(key, data):
            raise HTTPException(404, "Диалог не найден")
        return {"ok": True}

    @app.delete("/api/dialogs/{key:path}")
    def api_dialog_delete(key: str) -> dict:
        if not service.delete_dialog_record(key):
            raise HTTPException(404, "Диалог не найден")
        return {"ok": True}

    @app.get("/api/dialog-settings")
    def api_get_dialog_settings() -> dict:
        return service.get_dialog_settings()

    @app.post("/api/dialog-settings")
    def api_save_dialog_settings(body: DialogSettingsBody) -> dict:
        service.save_dialog_settings(body.model_dump())
        return {"ok": True}
