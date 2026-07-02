from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SECRETARY_PROMPT = (
    "Ты личный секретарь владельца этого Telegram-аккаунта. "
    "Веди живой диалог с собеседником: помни контекст, уточняй детали, отвечай от имени владельца. "
    "Если не знаешь ответ — честно скажи и предложи передать вопрос владельцу."
)


@dataclass
class SecretaryAgent:
    account_id: str
    name: str = "Секретарь"
    prompt: str = DEFAULT_SECRETARY_PROMPT
    language: str = "ru"
    extra_context: str = ""
    goal: str = ""
    allowed_users: list[str] = field(default_factory=list)
    blocked_users: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "prompt": self.prompt,
            "language": self.language,
            "extra_context": self.extra_context,
            "goal": self.goal,
            "allowed_users": self.allowed_users,
            "blocked_users": self.blocked_users,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretaryAgent:
        return cls(
            account_id=str(data["account_id"]),
            name=str(data.get("name") or "Секретарь"),
            prompt=str(data.get("prompt") or DEFAULT_SECRETARY_PROMPT),
            language=str(data.get("language") or "ru"),
            extra_context=str(data.get("extra_context") or ""),
            goal=str(data.get("goal") or ""),
            allowed_users=_normalize_users(data.get("allowed_users")),
            blocked_users=_normalize_users(data.get("blocked_users")),
            enabled=bool(data.get("enabled", True)),
        )

    def allows_user(self, username: str) -> bool:
        user = username.lower().lstrip("@")
        blocked = {u.lower().lstrip("@") for u in self.blocked_users if u.strip()}
        if user in blocked:
            return False
        allowed = {u.lower().lstrip("@") for u in self.allowed_users if u.strip()}
        if allowed and user not in allowed:
            return False
        return True


def _normalize_users(value: Any) -> list[str]:
    if isinstance(value, str):
        return [x.strip().lstrip("@") for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip().lstrip("@") for x in value if str(x).strip()]
    return []


@dataclass
class AgentsConfig:
    agents: list[SecretaryAgent] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> AgentsConfig:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        agents = [SecretaryAgent.from_dict(item) for item in data.get("agents", [])]
        return cls(agents=agents)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"agents": [a.to_dict() for a in self.agents]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, account_id: str) -> SecretaryAgent | None:
        for agent in self.agents:
            if agent.account_id == account_id:
                return agent
        return None

    def upsert(self, agent: SecretaryAgent) -> None:
        for i, existing in enumerate(self.agents):
            if existing.account_id == agent.account_id:
                self.agents[i] = agent
                return
        self.agents.append(agent)

    def remove(self, account_id: str) -> bool:
        before = len(self.agents)
        self.agents = [a for a in self.agents if a.account_id != account_id]
        return len(self.agents) < before
