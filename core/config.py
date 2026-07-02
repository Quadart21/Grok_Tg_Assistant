from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.llm_providers import DEFAULT_PROVIDER, provider_info
from core.master_prompt import DEFAULT_MASTER_PROMPT, MasterPromptConfig


@dataclass
class AppConfig:
    telegram_api_id: int
    telegram_api_hash: str
    grok_api_key: str
    grok_model: str = "grok-3-mini"
    llm_provider: str = DEFAULT_PROVIDER
    llm_model: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    openrouter_api_key: str = ""
    sessions_dir: str = "sessions"
    proxies_file: str = "config/proxies.json"
    roles_file: str = "roles.json"
    delay_between_messages_sec: int = 30
    max_concurrent_accounts: int = 10
    message_language: str = "ru"
    reply_delay_min_sec: int = 5
    reply_delay_max_sec: int = 25
    state_file: str = "data/state.json"
    telegram_2fa_password: str = ""

    def get_llm_api_key(self) -> str:
        info = provider_info(self.llm_provider or DEFAULT_PROVIDER)
        key = str(getattr(self, info.key_field, "") or "").strip()
        if key:
            return key
        if info.id == "grok":
            return (self.grok_api_key or "").strip()
        return ""

    def get_llm_model(self) -> str:
        if (self.llm_model or "").strip():
            return self.llm_model.strip()
        if self.llm_provider in ("", "grok") and (self.grok_model or "").strip():
            return self.grok_model.strip()
        return provider_info(self.llm_provider or DEFAULT_PROVIDER).default_model

    def llm_configured(self) -> bool:
        return bool(self.get_llm_api_key())

    @classmethod
    def load(cls, path: Path) -> AppConfig:
        data = json.loads(path.read_text(encoding="utf-8"))
        llm_provider = str(data.get("llm_provider") or DEFAULT_PROVIDER)
        llm_model = str(data.get("llm_model") or "")
        grok_key = str(data.get("grok_api_key") or "")
        grok_model = str(data.get("grok_model", "grok-3-mini"))
        if not data.get("llm_provider") and grok_key:
            llm_provider = "grok"
        if not llm_model and llm_provider == "grok":
            llm_model = grok_model
        return cls(
            telegram_api_id=int(data["telegram_api_id"]),
            telegram_api_hash=str(data["telegram_api_hash"]),
            grok_api_key=grok_key,
            grok_model=grok_model,
            llm_provider=llm_provider,
            llm_model=llm_model,
            openai_api_key=str(data.get("openai_api_key") or ""),
            gemini_api_key=str(data.get("gemini_api_key") or ""),
            anthropic_api_key=str(data.get("anthropic_api_key") or ""),
            deepseek_api_key=str(data.get("deepseek_api_key") or ""),
            openrouter_api_key=str(data.get("openrouter_api_key") or ""),
            sessions_dir=str(data.get("sessions_dir", "sessions")),
            proxies_file=str(data.get("proxies_file", "proxies.txt")),
            roles_file=str(data.get("roles_file", "roles.json")),
            delay_between_messages_sec=int(data.get("delay_between_messages_sec", 30)),
            max_concurrent_accounts=int(data.get("max_concurrent_accounts", 10)),
            message_language=str(data.get("message_language", "ru")),
            reply_delay_min_sec=int(data.get("reply_delay_min_sec", 5)),
            reply_delay_max_sec=int(data.get("reply_delay_max_sec", 25)),
            state_file=str(data.get("state_file", "data/state.json")),
            telegram_2fa_password=str(data.get("telegram_2fa_password", "")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.llm_provider == "grok" and self.grok_api_key:
            pass
        elif self.llm_provider == "grok":
            self.grok_api_key = self.get_llm_api_key()
        if self.llm_provider == "grok" and not self.llm_model:
            self.llm_model = self.grok_model
        path.write_text(
            json.dumps(
                {
                    "telegram_api_id": self.telegram_api_id,
                    "telegram_api_hash": self.telegram_api_hash,
                    "llm_provider": self.llm_provider or DEFAULT_PROVIDER,
                    "llm_model": self.llm_model or self.get_llm_model(),
                    "grok_api_key": self.grok_api_key,
                    "grok_model": self.grok_model,
                    "openai_api_key": self.openai_api_key,
                    "gemini_api_key": self.gemini_api_key,
                    "anthropic_api_key": self.anthropic_api_key,
                    "deepseek_api_key": self.deepseek_api_key,
                    "openrouter_api_key": self.openrouter_api_key,
                    "sessions_dir": self.sessions_dir,
                    "proxies_file": self.proxies_file,
                    "roles_file": self.roles_file,
                    "delay_between_messages_sec": self.delay_between_messages_sec,
                    "max_concurrent_accounts": self.max_concurrent_accounts,
                    "message_language": self.message_language,
                    "reply_delay_min_sec": self.reply_delay_min_sec,
                    "reply_delay_max_sec": self.reply_delay_max_sec,
                    "state_file": self.state_file,
                    "telegram_2fa_password": self.telegram_2fa_password,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


@dataclass
class ProxyConfig:
    account_id: str
    proxy_type: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    def to_telethon_proxy(self) -> tuple | None:
        if not self.host or not self.port:
            return None
        import socks

        type_map = {
            "socks5": socks.SOCKS5,
            "socks4": socks.SOCKS4,
            "http": socks.HTTP,
        }
        proxy_type = type_map.get(self.proxy_type.lower())
        if proxy_type is None:
            return None
        if self.username:
            return (proxy_type, self.host, self.port, True, self.username, self.password)
        return (proxy_type, self.host, self.port)


@dataclass
class RoleGroup:
    name: str
    role_prompt: str
    accounts: list[str] = field(default_factory=list)


@dataclass
class RolesConfig:
    default_role: str
    groups: list[RoleGroup] = field(default_factory=list)
    account_assignments: dict[str, str] = field(default_factory=dict)
    master_prompt: MasterPromptConfig = field(default_factory=MasterPromptConfig)

    @classmethod
    def load(cls, path: Path) -> RolesConfig:
        if not path.exists():
            return cls(default_role="Вы дружелюбный собеседник. Пишете первым в Telegram.")
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = [
            RoleGroup(
                name=g["name"],
                role_prompt=g["role_prompt"],
                accounts=list(g.get("accounts", [])),
            )
            for g in data.get("groups", [])
        ]
        assignments = {str(k): str(v) for k, v in data.get("account_assignments", {}).items()}
        if not assignments:
            for group in groups:
                for acc in group.accounts:
                    assignments[acc] = group.name
        master_raw = data.get("master_prompt")
        master = (
            MasterPromptConfig.from_dict(master_raw)
            if isinstance(master_raw, dict)
            else MasterPromptConfig()
        )
        return cls(
            default_role=str(data.get("default_role", "")),
            groups=groups,
            account_assignments=assignments,
            master_prompt=master,
        )

    def save(self, path: Path) -> None:
        self.sync_group_accounts_from_assignments()
        payload: dict[str, Any] = {
            "master_prompt": self.master_prompt.to_dict(),
            "default_role": self.default_role,
            "account_assignments": self.account_assignments,
            "groups": [
                {
                    "name": g.name,
                    "role_prompt": g.role_prompt,
                    "accounts": g.accounts,
                }
                for g in self.groups
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def sync_group_accounts_from_assignments(self) -> None:
        for group in self.groups:
            group.accounts = [
                acc
                for acc, group_name in self.account_assignments.items()
                if group_name == group.name
            ]

    def role_name_for_account(self, account_id: str) -> str:
        assigned = self.account_assignments.get(account_id, "")
        if assigned:
            return assigned
        for group in self.groups:
            if account_id in group.accounts:
                return group.name
        return "по умолчанию"

    def prompt_for_account(self, account_id: str) -> str:
        assigned = self.account_assignments.get(account_id, "")
        if assigned:
            for group in self.groups:
                if group.name == assigned:
                    return group.role_prompt
        for group in self.groups:
            if account_id in group.accounts:
                return group.role_prompt
        return self.default_role
