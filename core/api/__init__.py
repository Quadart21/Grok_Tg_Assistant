"""Регистрация HTTP-маршрутов API."""

from __future__ import annotations

from fastapi import FastAPI

from core.api.routes import accounts, agents, config, dialogs, engine, proxies, system
from core.app_service import AppService


def register_api_routes(app: FastAPI, service: AppService) -> None:
    system.register(app, service)
    config.register(app, service)
    accounts.register(app, service)
    proxies.register(app, service)
    dialogs.register(app, service)
    engine.register(app, service)
    agents.register(app, service)
