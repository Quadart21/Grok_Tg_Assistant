"""Аккаунты, сессии, профили."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.api.schemas import (
    BulkProfileBody,
    ConvertSessionsBody,
    ProfilePreviewBody,
    ProxyBody,
    SessionProfileBody,
)
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/accounts")
    def api_accounts() -> list:
        return service.get_accounts()

    @app.post("/api/sessions/convert")
    def api_convert_sessions(body: ConvertSessionsBody) -> dict:
        account_ids = body.account_ids or None
        return service.convert_tdata(account_ids)

    @app.get("/api/accounts/{account_id}/proxy")
    def api_get_proxy(account_id: str) -> dict:
        return service.get_proxy_form(account_id)

    @app.post("/api/accounts/{account_id}/proxy")
    def api_save_proxy(account_id: str, body: ProxyBody) -> dict:
        if not body.host or not body.port:
            raise HTTPException(400, "Укажите адрес и порт")
        service.save_proxy(account_id, body.model_dump())
        return {"ok": True}

    @app.delete("/api/accounts/{account_id}/proxy")
    def api_clear_proxy(account_id: str) -> dict:
        service.clear_proxy(account_id)
        return {"ok": True}

    @app.post("/api/accounts/bulk-profile")
    def api_bulk_profile(body: BulkProfileBody) -> dict:
        return service.bulk_update_profiles(body.model_dump())

    @app.post("/api/accounts/profile-preview")
    def api_profile_preview(body: ProfilePreviewBody) -> dict:
        return service.preview_profile_generation(body.model_dump())

    @app.get("/api/accounts/{account_id}/profile")
    def api_get_account_profile(account_id: str) -> dict:
        try:
            return service.get_account_profile(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/accounts/{account_id}/profile")
    def api_save_account_profile(account_id: str, body: SessionProfileBody) -> dict:
        try:
            return service.update_account_profile(account_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/accounts/{account_id}/profile/rotate-photo")
    def api_rotate_account_photo(account_id: str) -> dict:
        try:
            return service.rotate_account_profile_photo_now(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/accounts/{account_id}/profile/refresh-about")
    def api_refresh_account_about(account_id: str) -> dict:
        try:
            return service.refresh_account_about_now(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
