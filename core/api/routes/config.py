"""Настройки, LLM, роли."""

from __future__ import annotations

from fastapi import FastAPI

from core.api.schemas import ConfigBody, MasterPromptBody, RolesBody
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/config")
    def api_get_config() -> dict:
        return service.get_config_dict()

    @app.get("/api/llm/providers")
    def api_llm_providers() -> list:
        return service.get_llm_providers()

    @app.get("/api/llm/models")
    def api_llm_models(provider: str = "grok") -> dict:
        return service.get_llm_models(provider)

    @app.post("/api/config")
    def api_save_config(body: ConfigBody) -> dict:
        service.save_config(body.model_dump())
        return {"ok": True}

    @app.get("/api/roles")
    def api_roles() -> dict:
        return service.get_roles_dict()

    @app.post("/api/roles")
    def api_save_roles(body: RolesBody) -> dict:
        service.save_roles(body.model_dump())
        return {"ok": True}

    @app.get("/api/master-prompt")
    def api_get_master_prompt() -> dict:
        return service.get_master_prompt()

    @app.post("/api/master-prompt")
    def api_save_master_prompt(body: MasterPromptBody) -> dict:
        service.save_master_prompt(body.model_dump())
        return {"ok": True}
