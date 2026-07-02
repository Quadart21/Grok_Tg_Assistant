"""Shared runtime context for domain services."""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path

from core.agent_engine import AgentEngine, AgentStats
from core.config import AppConfig, RolesConfig
from core.dialog_engine import DialogEngine, EngineStats
from core.state_store import StateStore


class AppContext:
    """Paths, config, engines, logs — общее для всех сервисов."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config_path = base_dir / "config" / "settings.json"
        self.roles_path = base_dir / "roles.json"
        self.proxies_path = base_dir / "config" / "proxies.json"
        self.dialog_settings_path = base_dir / "config" / "dialog_settings.json"
        self.agents_path = base_dir / "config" / "agents.json"
        self.master_prompt_path = base_dir / "config" / "master_prompt.json"
        self.config = self._load_config()
        self.roles = self._load_roles()
        self.state_store = StateStore(base_dir / self.config.state_file)
        self.engine: DialogEngine | None = None
        self.agent_engine: AgentEngine | None = None
        self.worker_thread: threading.Thread | None = None
        self.agent_thread: threading.Thread | None = None
        self._logs: deque[str] = deque(maxlen=500)
        self._stats = EngineStats()
        self._agent_stats = AgentStats()
        self._running = False
        self._agent_running = False
        self._running_agent_ids: set[str] = set()
        self._outreach_account_ids: set[str] = set()
        self._lock = threading.Lock()

    def _load_config(self) -> AppConfig:
        if not self.config_path.exists():
            example = self.base_dir / "config" / "settings.example.json"
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if example.exists():
                self.config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                AppConfig(telegram_api_id=0, telegram_api_hash="", grok_api_key="").save(
                    self.config_path
                )
        cfg = AppConfig.load(self.config_path)
        self.proxies_path = self.base_dir / cfg.proxies_file
        if self.proxies_path.suffix != ".json":
            self.proxies_path = self.base_dir / "config" / "proxies.json"
        return cfg

    def _load_roles(self) -> RolesConfig:
        if not self.roles_path.exists():
            example = self.base_dir / "roles.example.json"
            if example.exists():
                self.roles_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return RolesConfig.load(self.roles_path)

    def log(self, message: str) -> None:
        self._logs.append(message)

    def get_logs(self, since: int = 0) -> list[str]:
        logs = list(self._logs)
        if since > 0:
            return logs[since:]
        return logs

    def reload_roles(self) -> RolesConfig:
        self.roles = RolesConfig.load(self.roles_path)
        return self.roles

    def reload_config(self) -> AppConfig:
        self.config = AppConfig.load(self.config_path)
        return self.config
