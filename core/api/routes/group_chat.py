"""Групповая переписка аккаунтов."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core.api.schemas import (
    GroupChatAccountsBody,
    GroupChatJoinLinkBody,
    GroupChatSettingsBody,
    GroupChatStartBody,
)
from core.app_service import AppService


def register(app: FastAPI, service: AppService) -> None:
    @app.get("/api/group-chat/settings")
    def api_group_chat_settings() -> dict:
        return service.get_group_chat_settings()

    @app.post("/api/group-chat/settings")
    def api_save_group_chat_settings(body: GroupChatSettingsBody) -> dict:
        return service.save_group_chat_settings(body.model_dump())

    @app.post("/api/group-chat/common-chats")
    def api_common_chats(body: GroupChatAccountsBody) -> dict:
        try:
            chats = service.discover_group_chats(body.account_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"chats": chats}

    @app.post("/api/group-chat/join-link")
    def api_join_group_chat_link(body: GroupChatJoinLinkBody) -> dict:
        try:
            return service.join_group_chat_by_link(body.account_ids, body.link)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/group-chat/status")
    def api_group_chat_status() -> dict:
        return service.get_group_chat_status()

    @app.post("/api/group-chat/start")
    def api_group_chat_start(body: GroupChatStartBody) -> dict:
        overrides = {
            aid: item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for aid, item in (body.role_overrides or {}).items()
        }
        ok, msg = service.start_group_chat(
            account_ids=body.account_ids,
            chat_id=body.chat_id,
            topic=body.topic,
            role_overrides=overrides,
            activity_weights=body.activity_weights or {},
            account_schedules=body.account_schedules or {},
            friendships=body.friendships or {},
            extra_context=body.extra_context,
            chat_title=body.chat_title,
        )
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True}

    @app.post("/api/group-chat/apply")
    def api_group_chat_apply(body: GroupChatStartBody) -> dict:
        overrides = {
            aid: item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for aid, item in (body.role_overrides or {}).items()
        }
        ok, msg = service.apply_group_chat_scene(
            account_ids=body.account_ids,
            chat_id=body.chat_id,
            topic=body.topic,
            role_overrides=overrides,
            activity_weights=body.activity_weights or {},
            account_schedules=body.account_schedules or {},
            friendships=body.friendships or {},
            extra_context=body.extra_context,
            chat_title=body.chat_title,
        )
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "message": msg}

    @app.post("/api/group-chat/stop")
    def api_group_chat_stop() -> dict:
        service.stop_group_chat()
        return {"ok": True}
