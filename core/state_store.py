from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ProxyConfig
from core.json_store import read_json, write_json_atomic


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dialog_key(account_id: str, target_username: str) -> str:
    return f"{account_id}:{target_username.lower().lstrip('@')}"


@dataclass
class ChatMessage:
    role: str
    content: str
    ts: str
    msg_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "ts": self.ts,
            "msg_id": self.msg_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChatMessage:
        return cls(
            role=str(data["role"]),
            content=str(data["content"]),
            ts=str(data.get("ts", "")),
            msg_id=data.get("msg_id"),
        )


@dataclass
class AccountBinding:
    account_id: str
    role_prompt: str = ""
    role_group_name: str = ""
    proxy_type: str = "socks5"
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_username: str = ""
    proxy_password: str = ""
    updated_at: str = ""

    def to_proxy(self) -> ProxyConfig | None:
        if not self.proxy_host or not self.proxy_port:
            return None
        return ProxyConfig(
            account_id=self.account_id,
            proxy_type=self.proxy_type,
            host=self.proxy_host,
            port=self.proxy_port,
            username=self.proxy_username,
            password=self.proxy_password,
        )

    @classmethod
    def from_proxy(cls, account_id: str, proxy: ProxyConfig | None, role_prompt: str, role_group_name: str = "") -> AccountBinding:
        binding = cls(
            account_id=account_id,
            role_prompt=role_prompt,
            role_group_name=role_group_name,
            updated_at=_now_iso(),
        )
        if proxy and proxy.host:
            binding.proxy_type = proxy.proxy_type
            binding.proxy_host = proxy.host
            binding.proxy_port = proxy.port
            binding.proxy_username = proxy.username
            binding.proxy_password = proxy.password
        return binding

    def to_dict(self) -> dict:
        return {
            "role_prompt": self.role_prompt,
            "role_group_name": self.role_group_name,
            "proxy_type": self.proxy_type,
            "proxy_host": self.proxy_host,
            "proxy_port": self.proxy_port,
            "proxy_username": self.proxy_username,
            "proxy_password": self.proxy_password,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, account_id: str, data: dict) -> AccountBinding:
        return cls(
            account_id=account_id,
            role_prompt=str(data.get("role_prompt", "")),
            role_group_name=str(data.get("role_group_name", "")),
            proxy_type=str(data.get("proxy_type", "socks5")),
            proxy_host=str(data.get("proxy_host", "")),
            proxy_port=int(data.get("proxy_port", 0)),
            proxy_username=str(data.get("proxy_username", "")),
            proxy_password=str(data.get("proxy_password", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass
class DialogRecord:
    account_id: str
    target_username: str
    role_prompt: str = ""
    extra_context: str = ""
    language: str = "ru"
    target_user_id: int | None = None
    status: str = "active"
    created_at: str = ""
    last_activity: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    auto_reply: bool = True
    goal: str = ""
    dialog_extra_context: str = ""
    max_replies: int = 0
    replies_count: int = 0
    notes: str = ""
    dialog_mode: str = "outreach"

    @property
    def key(self) -> str:
        return _dialog_key(self.account_id, self.target_username)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "target_username": self.target_username,
            "role_prompt": self.role_prompt,
            "extra_context": self.extra_context,
            "language": self.language,
            "target_user_id": self.target_user_id,
            "status": self.status,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "messages": [m.to_dict() for m in self.messages],
            "auto_reply": self.auto_reply,
            "goal": self.goal,
            "dialog_extra_context": self.dialog_extra_context,
            "max_replies": self.max_replies,
            "replies_count": self.replies_count,
            "notes": self.notes,
            "dialog_mode": self.dialog_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DialogRecord:
        return cls(
            account_id=str(data["account_id"]),
            target_username=str(data["target_username"]),
            role_prompt=str(data.get("role_prompt", "")),
            extra_context=str(data.get("extra_context", "")),
            language=str(data.get("language", "ru")),
            target_user_id=data.get("target_user_id"),
            status=str(data.get("status", "active")),
            created_at=str(data.get("created_at", "")),
            last_activity=str(data.get("last_activity", "")),
            messages=[ChatMessage.from_dict(m) for m in data.get("messages", [])],
            auto_reply=bool(data.get("auto_reply", True)),
            goal=str(data.get("goal", "")),
            dialog_extra_context=str(data.get("dialog_extra_context", "")),
            max_replies=int(data.get("max_replies", 0)),
            replies_count=int(data.get("replies_count", 0)),
            notes=str(data.get("notes", "")),
            dialog_mode=str(data.get("dialog_mode", "outreach")),
        )


@dataclass
class GroupChatMessage:
    speaker_account_id: str
    speaker_name: str
    text: str
    ts: str
    msg_id: int | None = None
    external: bool = False
    reply_to_msg_id: int | None = None
    reply_to_speaker_account_id: str = ""
    reply_to_external: bool = False

    def to_dict(self) -> dict:
        return {
            "speaker_account_id": self.speaker_account_id,
            "speaker_name": self.speaker_name,
            "text": self.text,
            "ts": self.ts,
            "msg_id": self.msg_id,
            "external": self.external,
            "reply_to_msg_id": self.reply_to_msg_id,
            "reply_to_speaker_account_id": self.reply_to_speaker_account_id,
            "reply_to_external": self.reply_to_external,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GroupChatMessage:
        return cls(
            speaker_account_id=str(data.get("speaker_account_id", "")),
            speaker_name=str(data.get("speaker_name", "")),
            text=str(data.get("text", "")),
            ts=str(data.get("ts", "")),
            msg_id=data.get("msg_id"),
            external=bool(data.get("external", False)),
            reply_to_msg_id=data.get("reply_to_msg_id"),
            reply_to_speaker_account_id=str(data.get("reply_to_speaker_account_id", "")),
            reply_to_external=bool(data.get("reply_to_external", False)),
        )


@dataclass
class GroupSessionRecord:
    chat_id: int
    topic: str = ""
    chat_title: str = ""
    account_ids: list[str] = field(default_factory=list)
    role_prompts: dict[str, str] = field(default_factory=dict)
    role_names: dict[str, str] = field(default_factory=dict)
    activity_weights: dict[str, float] = field(default_factory=dict)
    account_schedules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    friendships: dict[str, list[str]] = field(default_factory=dict)
    extra_context: str = ""
    status: str = "idle"
    created_at: str = ""
    last_activity: str = ""
    messages: list[GroupChatMessage] = field(default_factory=list)
    session_counts: dict[str, int] = field(default_factory=dict)
    day_counts: dict[str, int] = field(default_factory=dict)
    day_key: str = ""
    group_day_count: int = 0

    def to_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "topic": self.topic,
            "chat_title": self.chat_title,
            "account_ids": list(self.account_ids),
            "role_prompts": dict(self.role_prompts),
            "role_names": dict(self.role_names),
            "activity_weights": dict(self.activity_weights),
            "account_schedules": {
                str(k): [dict(item) for item in items if isinstance(item, dict)]
                for k, items in self.account_schedules.items()
            },
            "friendships": {
                str(k): [str(friend) for friend in friends]
                for k, friends in self.friendships.items()
            },
            "extra_context": self.extra_context,
            "status": self.status,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "messages": [m.to_dict() for m in self.messages],
            "session_counts": dict(self.session_counts),
            "day_counts": dict(self.day_counts),
            "day_key": self.day_key,
            "group_day_count": self.group_day_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GroupSessionRecord:
        return cls(
            chat_id=int(data.get("chat_id", 0)),
            topic=str(data.get("topic", "")),
            chat_title=str(data.get("chat_title", "")),
            account_ids=[str(a) for a in data.get("account_ids", [])],
            role_prompts={str(k): str(v) for k, v in (data.get("role_prompts") or {}).items()},
            role_names={str(k): str(v) for k, v in (data.get("role_names") or {}).items()},
            activity_weights={
                str(k): float(v) for k, v in (data.get("activity_weights") or {}).items()
            },
            account_schedules={
                str(k): [dict(item) for item in items if isinstance(item, dict)]
                for k, items in (data.get("account_schedules") or {}).items()
                if isinstance(items, list)
            },
            friendships={
                str(k): [str(friend) for friend in friends]
                for k, friends in (data.get("friendships") or {}).items()
                if isinstance(friends, list)
            },
            extra_context=str(data.get("extra_context", "")),
            status=str(data.get("status", "idle")),
            created_at=str(data.get("created_at", "")),
            last_activity=str(data.get("last_activity", "")),
            messages=[GroupChatMessage.from_dict(m) for m in data.get("messages", [])],
            session_counts={str(k): int(v) for k, v in (data.get("session_counts") or {}).items()},
            day_counts={str(k): int(v) for k, v in (data.get("day_counts") or {}).items()},
            day_key=str(data.get("day_key", "")),
            group_day_count=int(data.get("group_day_count", 0)),
        )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.accounts: dict[str, AccountBinding] = {}
        self.dialogs: dict[str, DialogRecord] = {}
        self.group_session: GroupSessionRecord | None = None
        self.load()

    def load(self) -> None:
        with self._lock:
            data = read_json(self.path, {})
            self.accounts = {
                acc_id: AccountBinding.from_dict(acc_id, item)
                for acc_id, item in data.get("accounts", {}).items()
            }
            self.dialogs = {
                key: DialogRecord.from_dict(item) for key, item in data.get("dialogs", {}).items()
            }
            gs = data.get("group_session")
            self.group_session = GroupSessionRecord.from_dict(gs) if isinstance(gs, dict) else None

    def _payload(self) -> dict:
        return {
            "accounts": {acc_id: b.to_dict() for acc_id, b in self.accounts.items()},
            "dialogs": {key: d.to_dict() for key, d in self.dialogs.items()},
            "group_session": self.group_session.to_dict() if self.group_session else None,
        }

    def save(self) -> None:
        with self._lock:
            write_json_atomic(self.path, self._payload())

    def upsert_group_session(self, session: GroupSessionRecord) -> GroupSessionRecord:
        with self._lock:
            if not session.created_at:
                session.created_at = _now_iso()
            session.last_activity = _now_iso()
            self.group_session = session
            self.save()
            return session

    def add_group_message(
        self,
        session: GroupSessionRecord,
        speaker_account_id: str,
        speaker_name: str,
        text: str,
        msg_id: int | None = None,
        external: bool = False,
        reply_to_msg_id: int | None = None,
        reply_to_speaker_account_id: str = "",
        reply_to_external: bool = False,
        max_stored: int = 200,
    ) -> None:
        with self._lock:
            if msg_id is not None and any(m.msg_id == msg_id for m in session.messages):
                return
            session.messages.append(
                GroupChatMessage(
                    speaker_account_id=speaker_account_id,
                    speaker_name=speaker_name,
                    text=text,
                    ts=_now_iso(),
                    msg_id=msg_id,
                    external=external,
                    reply_to_msg_id=reply_to_msg_id,
                    reply_to_speaker_account_id=reply_to_speaker_account_id,
                    reply_to_external=reply_to_external,
                )
            )
            if len(session.messages) > max_stored:
                session.messages = session.messages[-max_stored:]
            session.last_activity = _now_iso()
            self.group_session = session
            self.save()

    def get_account_binding(self, account_id: str) -> AccountBinding | None:
        with self._lock:
            return self.accounts.get(account_id)

    def save_account_binding(
        self,
        account_id: str,
        role_prompt: str,
        proxy: ProxyConfig | None,
        role_group_name: str = "",
    ) -> AccountBinding:
        with self._lock:
            binding = AccountBinding.from_proxy(account_id, proxy, role_prompt, role_group_name)
            self.accounts[account_id] = binding
            self.save()
            return binding

    def get_dialog(self, account_id: str, target_username: str) -> DialogRecord | None:
        with self._lock:
            return self.dialogs.get(_dialog_key(account_id, target_username))

    def list_dialogs_for_account(self, account_id: str, statuses: set[str] | None = None) -> list[DialogRecord]:
        with self._lock:
            result = [d for d in self.dialogs.values() if d.account_id == account_id]
            if statuses:
                result = [d for d in result if d.status in statuses]
            return sorted(result, key=lambda d: d.last_activity or d.created_at, reverse=True)

    def list_all_dialogs(self, statuses: set[str] | None = None) -> list[DialogRecord]:
        with self._lock:
            result = list(self.dialogs.values())
            if statuses:
                result = [d for d in result if d.status in statuses]
            return sorted(result, key=lambda d: d.last_activity or d.created_at, reverse=True)

    def upsert_dialog(self, dialog: DialogRecord) -> DialogRecord:
        with self._lock:
            if not dialog.created_at:
                dialog.created_at = _now_iso()
            dialog.last_activity = _now_iso()
            self.dialogs[dialog.key] = dialog
            self.save()
            return dialog

    def add_message(self, dialog: DialogRecord, role: str, content: str, msg_id: int | None = None, max_stored: int = 150) -> None:
        with self._lock:
            if msg_id is not None and any(m.msg_id == msg_id for m in dialog.messages):
                return
            dialog.messages.append(ChatMessage(role=role, content=content, ts=_now_iso(), msg_id=msg_id))
            if len(dialog.messages) > max_stored:
                dialog.messages = dialog.messages[-max_stored:]
            dialog.last_activity = _now_iso()
            self.dialogs[dialog.key] = dialog
            self.save()

    def get_dialog_by_key(self, key: str) -> DialogRecord | None:
        with self._lock:
            return self.dialogs.get(key)

    def delete_dialog(self, key: str) -> bool:
        with self._lock:
            if key in self.dialogs:
                del self.dialogs[key]
                self.save()
                return True
            return False

    def clear_dialog_memory(self, key: str) -> bool:
        """Стереть историю сообщений; диалог не будет возобновлён при следующем запуске."""
        with self._lock:
            dialog = self.dialogs.get(key)
            if not dialog:
                return False
            dialog.messages = []
            dialog.replies_count = 0
            dialog.status = "closed"
            dialog.auto_reply = False
            dialog.last_activity = _now_iso()
            self.dialogs[key] = dialog
            self.save()
            return True

    def delete_dialogs_for_account(self, account_id: str) -> int:
        with self._lock:
            keys = [k for k, d in self.dialogs.items() if d.account_id == account_id]
            for key in keys:
                del self.dialogs[key]
            if keys:
                self.save()
            return len(keys)

    def delete_all_dialogs(self) -> int:
        with self._lock:
            count = len(self.dialogs)
            if count:
                self.dialogs.clear()
                self.save()
            return count

    def set_dialog_status(self, dialog: DialogRecord, status: str) -> None:
        with self._lock:
            dialog.status = status
            dialog.last_activity = _now_iso()
            self.dialogs[dialog.key] = dialog
            self.save()

    def pause_all_active(self) -> None:
        with self._lock:
            changed = False
            for dialog in self.dialogs.values():
                if dialog.status == "active":
                    dialog.status = "paused"
                    changed = True
            if changed:
                self.save()
