"""Пул прокси и привязка к аккаунтам."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.api.schemas import (
    BulkProxyBody,
    ProxyAutoBindBody,
    ProxyBindBody,
    ProxyBulkIdsBody,
    ProxyPoolImportBody,
    ProxyRecheckBody,
)
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.post("/api/proxy/bulk")
    def api_bulk_proxy(body: BulkProxyBody) -> dict:
        lines = [ln.strip() for ln in body.lines.splitlines() if ln.strip()]
        return service.import_proxy_pool(lines, body.type)

    @app.get("/api/proxy-pool")
    def api_proxy_pool() -> dict:
        return service.get_proxy_pool()

    @app.post("/api/proxy-pool/import")
    def api_proxy_pool_import(body: ProxyPoolImportBody) -> dict:
        lines = [ln.strip() for ln in body.lines.splitlines() if ln.strip()]
        if not lines:
            raise HTTPException(400, "Вставьте список прокси")
        return service.import_proxy_pool(lines, body.type)

    @app.post("/api/proxy-pool/recheck")
    def api_proxy_pool_recheck(body: ProxyRecheckBody = ProxyRecheckBody()) -> dict:
        proxy_ids = body.proxy_ids if body.proxy_ids else None
        return service.recheck_proxy_pool(proxy_ids)

    @app.post("/api/proxy-pool/{proxy_id}/recheck")
    def api_proxy_pool_recheck_one(proxy_id: str) -> dict:
        return service.recheck_proxy_pool([proxy_id])

    @app.post("/api/proxy-pool/bulk-delete")
    def api_proxy_pool_bulk_delete(body: ProxyBulkIdsBody) -> dict:
        if not body.proxy_ids:
            raise HTTPException(400, "Выберите прокси")
        return service.bulk_delete_proxy_pool(body.proxy_ids, body.unbind)

    @app.post("/api/proxy-pool/purge-dead")
    def api_proxy_pool_purge_dead(unbind: bool = True) -> dict:
        return service.purge_dead_proxy_pool(unbind=unbind)

    @app.post("/api/proxy-pool/auto-bind")
    def api_proxy_pool_auto_bind(body: ProxyAutoBindBody) -> dict:
        account_ids = body.account_ids or None
        proxy_ids = body.proxy_ids or None
        return service.auto_bind_proxies(account_ids, proxy_ids)

    @app.delete("/api/proxy-pool/{proxy_id}")
    def api_proxy_pool_delete(proxy_id: str, unbind: bool = False) -> dict:
        try:
            service.delete_proxy_pool_item(proxy_id, unbind=unbind)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    @app.post("/api/accounts/{account_id}/proxy/bind")
    def api_bind_account_proxy(account_id: str, body: ProxyBindBody) -> dict:
        proxy_id = (body.proxy_id or "").strip() or None
        try:
            service.bind_account_proxy(account_id, proxy_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}
