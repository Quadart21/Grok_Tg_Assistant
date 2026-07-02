from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import ProxyConfig


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


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.accounts: dict[str, AccountBinding] = {}
        self.dialogs: dict[str, DialogRecord] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.accounts = {
            acc_id: AccountBinding.from_dict(acc_id, item)
            for acc_id, item in data.get("accounts", {}).items()
        }
        self.dialogs = {
            key: DialogRecord.from_dict(item) for key, item in data.get("dialogs", {}).items()
        }

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "accounts": {acc_id: b.to_dict() for acc_id, b in self.accounts.items()},
                "dialogs": {key: d.to_dict() for key, d in self.dialogs.items()},
            }
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_account_binding(self, account_id: str) -> AccountBinding | None:
        return self.accounts.get(account_id)

    def save_account_binding(
        self,
        account_id: str,
        role_prompt: str,
        proxy: ProxyConfig | None,
        role_group_name: str = "",
    ) -> AccountBinding:
        binding = AccountBinding.from_proxy(account_id, proxy, role_prompt, role_group_name)
        self.accounts[account_id] = binding
        self.save()
        return binding

    def get_dialog(self, account_id: str, target_username: str) -> DialogRecord | None:
        return self.dialogs.get(_dialog_key(account_id, target_username))

    def list_dialogs_for_account(self, account_id: str, statuses: set[str] | None = None) -> list[DialogRecord]:
        result = [d for d in self.dialogs.values() if d.account_id == account_id]
        if statuses:
            result = [d for d in result if d.status in statuses]
        return sorted(result, key=lambda d: d.last_activity or d.created_at, reverse=True)

    def list_all_dialogs(self, statuses: set[str] | None = None) -> list[DialogRecord]:
        result = list(self.dialogs.values())
        if statuses:
            result = [d for d in result if d.status in statuses]
        return sorted(result, key=lambda d: d.last_activity or d.created_at, reverse=True)

    def upsert_dialog(self, dialog: DialogRecord) -> DialogRecord:
        if not dialog.created_at:
            dialog.created_at = _now_iso()
        dialog.last_activity = _now_iso()
        self.dialogs[dialog.key] = dialog
        self.save()
        return dialog

    def add_message(self, dialog: DialogRecord, role: str, content: str, msg_id: int | None = None, max_stored: int = 150) -> None:
        if msg_id is not None and any(m.msg_id == msg_id for m in dialog.messages):
            return
        dialog.messages.append(ChatMessage(role=role, content=content, ts=_now_iso(), msg_id=msg_id))
        if len(dialog.messages) > max_stored:
            dialog.messages = dialog.messages[-max_stored:]
        dialog.last_activity = _now_iso()
        self.dialogs[dialog.key] = dialog
        self.save()

    def get_dialog_by_key(self, key: str) -> DialogRecord | None:
        return self.dialogs.get(key)

    def delete_dialog(self, key: str) -> bool:
        if key in self.dialogs:
            del self.dialogs[key]
            self.save()
            return True
        return False

    def clear_dialog_memory(self, key: str) -> bool:
        """Стереть историю сообщений; диалог не будет возобновлён при следующем запуске."""
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
        keys = [k for k, d in self.dialogs.items() if d.account_id == account_id]
        for key in keys:
            del self.dialogs[key]
        if keys:
            self.save()
        return len(keys)

    def delete_all_dialogs(self) -> int:
        count = len(self.dialogs)
        if count:
            self.dialogs.clear()
            self.save()
        return count

    def set_dialog_status(self, dialog: DialogRecord, status: str) -> None:
        dialog.status = status
        dialog.last_activity = _now_iso()
        self.dialogs[dialog.key] = dialog
        self.save()

    def pause_all_active(self) -> None:
        changed = False
        for dialog in self.dialogs.values():
            if dialog.status == "active":
                dialog.status = "paused"
                changed = True
        if changed:
            self.save()
