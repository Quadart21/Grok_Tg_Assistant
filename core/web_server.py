"""Локальный веб-сервер — панель управления в браузере."""

from __future__ import annotations

import socket
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.api import register_api_routes
from core.app_service import AppService


def _free_port(preferred: int = 8787) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def create_app(base_dir: Path) -> tuple[FastAPI, AppService, int]:
    service = AppService(base_dir)
    static_dir = base_dir / "web" / "panel"
    port = _free_port()

    app = FastAPI(title="Kot_Teamlead", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    register_api_routes(app, service)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app, service, port


def run_web_panel(base_dir: Path, open_browser: bool = True) -> None:
    app, _service, port = create_app(base_dir)
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        webbrowser.open(url)
    print(f"\n  Kot_Teamlead — панель: {url}\n  Разработчик: Kot_Teamlead\n  Только на вашем ПК (локально)\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
