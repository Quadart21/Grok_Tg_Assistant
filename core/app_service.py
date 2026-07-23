"""Общая логика приложения для веб-панели."""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.agent_config import AgentsConfig, DEFAULT_SECRETARY_PROMPT, SecretaryAgent
from core.master_prompt import MasterPromptConfig
from core.agent_engine import AgentEngine, AgentStats
from core.config import AppConfig, ProxyConfig, RoleGroup, RolesConfig
from core.dialog_settings import DialogSettings
from core.dialog_engine import DialogEngine, EngineStats
from core.group_chat_discovery import discover_common_chats
from core.group_chat_engine import GroupChatEngine, GroupChatStats
from core.group_chat_settings import GroupChatSettings
from core.llm_client import create_llm_client
from core.llm_models import resolve_models, static_models
from core.llm_providers import LLM_PROVIDERS, list_providers_dict, provider_info
from core.proxy_manager import load_proxies, save_proxies
from core.proxy_pool import (
    bind_account,
    create_pool_item,
    delete_pool_item,
    delete_pool_items,
    import_lines_verified,
    load_pool,
    migrate_legacy_proxies,
    pool_path,
    pool_to_api,
    purge_dead_pool_items,
    recheck_pool_items,
    resolve_pool_proxy,
    save_pool,
)
from core.session_manager import (
    SessionFormat,
    discover_sessions,
    filter_accounts_for_roles,
    find_twofa_file,
    is_import_duplicate,
    read_twofa_password,
)

from core.tdata_converter import (
    ConvertResult,
    convert_tdata_to_session,
    has_converted_session,
    remove_session_artifacts,
    session_output_path,
    verify_converted_session,
)
from core.profile_generator import generate_profile, preview_profiles
from core.state_store import AccountBinding, GroupSessionRecord, StateStore
from core.telegram_client import TelegramAccountClient, format_telegram_error


def apply_profile_template(template: str, account_id: str, index: int) -> str:
    """Подстановки: {n} — номер с 1, {i} — с 0, {id} / {account} — id аккаунта."""
    return (
        template.replace("{n}", str(index + 1))
        .replace("{i}", str(index))
        .replace("{id}", account_id)
        .replace("{account}", account_id)
    )


class AppService:
    SESSION_HEALTH_INTERVAL_SEC = 20
    SESSION_HEALTH_CONNECT_TIMEOUT_SEC = 8
    SESSION_HEALTH_MAX_CONCURRENCY = 6

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config_path = base_dir / "config" / "settings.json"
        self.roles_path = base_dir / "roles.json"
        self.proxies_path = base_dir / "config" / "proxies.json"
        self.dialog_settings_path = base_dir / "config" / "dialog_settings.json"
        self.agents_path = base_dir / "config" / "agents.json"
        self.master_prompt_path = base_dir / "config" / "master_prompt.json"
        self.group_chat_settings_path = base_dir / "config" / "group_chat.json"
        self.config = self._load_config()
        self.roles = self._load_roles()
        self.state_store = StateStore(base_dir / self.config.state_file)
        self.engine: DialogEngine | None = None
        self.agent_engine: AgentEngine | None = None
        self.group_chat_engine: GroupChatEngine | None = None
        self.worker_thread: threading.Thread | None = None
        self.agent_thread: threading.Thread | None = None
        self.group_chat_thread: threading.Thread | None = None
        self._logs: deque[str] = deque(maxlen=500)
        self._stats = EngineStats()
        self._agent_stats = AgentStats()
        self._group_chat_stats = GroupChatStats()
        self._running = False
        self._agent_running = False
        self._group_chat_running = False
        self._running_agent_ids: set[str] = set()
        self._outreach_account_ids: set[str] = set()
        self._group_chat_account_ids: set[str] = set()
        self._lock = threading.Lock()
        self._session_health_cache: dict[str, dict[str, Any]] = {}
        self._profile_scheduler_stop = threading.Event()
        self._profile_scheduler_thread = threading.Thread(
            target=self._profile_scheduler_loop,
            daemon=True,
            name="profile-scheduler",
        )
        self._profile_scheduler_thread.start()
        self._session_health_stop = threading.Event()
        self._session_health_thread = threading.Thread(
            target=self._session_health_loop,
            daemon=True,
            name="session-health",
        )
        self._session_health_thread.start()

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

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _parse_iso_dt(self, value: str) -> datetime | None:
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _resolve_profile_library_dir(self, raw_dir: str) -> Path:
        folder = (raw_dir or "").strip()
        if not folder:
            raise ValueError("Укажите папку с фото внутри проекта")
        candidate = (self.base_dir / folder).resolve() if not Path(folder).is_absolute() else Path(folder).resolve()
        base = self.base_dir.resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError("Папка с фото должна находиться внутри проекта") from exc
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError("Папка с фото не найдена")
        return candidate

    def _list_profile_photo_candidates(self, raw_dir: str) -> list[str]:
        folder = self._resolve_profile_library_dir(raw_dir)
        allowed = {".jpg", ".jpeg", ".png", ".webp"}
        return sorted(
            str(path)
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in allowed
        )

    def pick_profile_photo_library_dir(self) -> dict[str, Any]:
        """Открывает системный диалог выбора папки и возвращает путь относительно проекта."""
        import tkinter as tk
        from tkinter import filedialog

        initial = self.base_dir / "assets"
        if not initial.is_dir():
            initial = self.base_dir

        root = tk.Tk()
        root.withdraw()
        try:
            root.wm_attributes("-topmost", True)
        except Exception:
            pass
        try:
            chosen = filedialog.askdirectory(
                parent=root,
                initialdir=str(initial),
                title="Выберите папку с фото внутри проекта",
                mustexist=True,
            )
        finally:
            root.destroy()

        if not chosen:
            return {"cancelled": True, "path": ""}

        resolved = self._resolve_profile_library_dir(chosen)
        relative = resolved.relative_to(self.base_dir.resolve()).as_posix()
        return {"cancelled": False, "path": relative}

    def _profile_rotation_due(self, last_ts: str, every_hours: int) -> bool:
        interval = max(int(every_hours or 0), 1)
        last_dt = self._parse_iso_dt(last_ts)
        if last_dt is None:
            return True
        return self._now_utc() >= last_dt + timedelta(hours=interval)

    def _clean_profile_text(self, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _get_session_for_account(self, account_id: str):
        sessions = {s.account_id: s for s in discover_sessions(self.base_dir / self.config.sessions_dir)}
        session = sessions.get(account_id)
        if not session:
            raise ValueError("Сессия не найдена в папке sessions")
        return session

    def _run_account_profile_update(self, account_id: str, *, first_name: Any = None, last_name: Any = None, username: Any = None, about: Any = None, photo_path: Any = None) -> dict[str, Any]:
        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            raise ValueError("Сначала заполните Telegram API ID и Hash")
        account = next((acc for acc in self.get_accounts() if acc["id"] == account_id), None)
        if not account:
            raise ValueError("Аккаунт не найден")
        if not account.get("session_ready"):
            raise ValueError("Для аккаунта нет рабочего .session")

        session = self._get_session_for_account(account_id)
        proxies = load_proxies(self.proxies_path)
        proxy = self._proxy_for_account(account_id, proxies)
        pwd = read_twofa_password(session, self.config.telegram_2fa_password)
        client = TelegramAccountClient(
            session,
            self.config.telegram_api_id,
            self.config.telegram_api_hash,
            proxy,
            pwd,
        )

        async def run_one() -> dict[str, Any]:
            await client.connect()
            try:
                return await client.update_profile(
                    first_name=self._clean_profile_text(first_name),
                    last_name=self._clean_profile_text(last_name),
                    username=self._clean_profile_text(username),
                    about=self._clean_profile_text(about),
                    photo_path=self._clean_profile_text(photo_path),
                )
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        try:
            profile = loop.run_until_complete(run_one())
        finally:
            loop.close()

        self.state_store.load()
        binding = self.state_store.get_account_binding(account_id) or AccountBinding(account_id=account_id)
        profile.update(self._build_profile_automation_payload(binding))
        return profile

    def _build_profile_automation_payload(self, binding: AccountBinding) -> dict[str, Any]:
        return {
            "auto_photo_enabled": binding.auto_photo_enabled,
            "photo_rotation_hours": binding.photo_rotation_hours,
            "photo_library_dir": binding.photo_library_dir,
            "last_photo_at": binding.last_photo_at,
            "last_photo_path": binding.last_photo_path,
            "auto_about_enabled": binding.auto_about_enabled,
            "about_rotation_hours": binding.about_rotation_hours,
            "about_topic": binding.about_topic,
            "last_about_at": binding.last_about_at,
            "last_about_text": binding.last_about_text,
        }

    def _update_account_automation_settings(self, account_id: str, data: dict[str, Any]) -> AccountBinding:
        self.state_store.load()
        current = self.state_store.get_account_binding(account_id)
        if current is None:
            proxy = self._proxy_for_account(account_id, load_proxies(self.proxies_path))
            current = AccountBinding.from_proxy(account_id, proxy, self.roles.prompt_for_account(account_id), self._role_label(account_id))
        current.auto_photo_enabled = bool(data.get("auto_photo_enabled", current.auto_photo_enabled))
        current.photo_rotation_hours = max(int(data.get("photo_rotation_hours", current.photo_rotation_hours) or 78), 1)
        current.photo_library_dir = str(data.get("photo_library_dir", current.photo_library_dir or "")).strip()
        current.auto_about_enabled = bool(data.get("auto_about_enabled", current.auto_about_enabled))
        current.about_rotation_hours = max(int(data.get("about_rotation_hours", current.about_rotation_hours) or 78), 1)
        current.about_topic = str(data.get("about_topic", current.about_topic or "")).strip()
        return self.state_store.update_account_binding(current)

    def _generate_about_text(self, topic: str, account_id: str) -> str:
        if not self.config.llm_configured():
            raise ValueError("Для автосмены about нужно настроить LLM")
        llm = create_llm_client(self.config, DialogSettings(), MasterPromptConfig())
        system = (
            "Сгенерируй короткое Telegram about на русском языке. "
            "Максимум 70 символов. Без кавычек, эмодзи, хештегов и пояснений."
        )
        user = (
            f"Тематика: {topic.strip()}\n"
            f"Аккаунт: {account_id}\n"
            "Нужна 1 короткая строка для поля 'О себе'."
        )

        async def run_one() -> str:
            return await llm._complete(system, [{"role": "user", "content": user}], temp=0.8, max_tokens=80)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run_one()).strip()
        finally:
            loop.close()

    def _process_profile_automation_for_account(self, account: dict[str, Any], binding: AccountBinding) -> None:
        account_id = account["id"]
        changed = False

        if binding.auto_photo_enabled:
            if not binding.photo_library_dir:
                raise ValueError("Не указана папка с фото для автосмены")
            if self._profile_rotation_due(binding.last_photo_at, binding.photo_rotation_hours):
                candidates = self._list_profile_photo_candidates(binding.photo_library_dir)
                if not candidates:
                    raise ValueError("В папке автосмены фото нет подходящих изображений")
                next_photo = self.state_store.find_available_profile_photo(account_id, candidates)
                self._run_account_profile_update(account_id, photo_path=next_photo)
                binding.last_photo_at = self._now_utc().isoformat()
                binding.last_photo_path = next_photo
                self.state_store.claim_profile_photo(account_id, next_photo)
                changed = True
                self.log(f"↻ Фото профиля обновлено для {account_id}: {Path(next_photo).name}")

        if binding.auto_about_enabled:
            if not binding.about_topic:
                raise ValueError("Не задана тема для автосмены about")
            if self._profile_rotation_due(binding.last_about_at, binding.about_rotation_hours):
                next_about = self._generate_about_text(binding.about_topic, account_id)
                self._run_account_profile_update(account_id, about=next_about)
                binding.last_about_at = self._now_utc().isoformat()
                binding.last_about_text = next_about
                changed = True
                self.log(f"↻ About обновлён для {account_id}")

        if changed:
            self.state_store.update_account_binding(binding)

    def _get_account_binding_for_automation(self, account_id: str) -> tuple[dict[str, Any], AccountBinding]:
        account = next((acc for acc in self.get_accounts() if acc["id"] == account_id), None)
        if not account:
            raise ValueError("Аккаунт не найден")
        if not account.get("session_ready"):
            raise ValueError("Для аккаунта нет рабочего .session")
        self.state_store.load()
        binding = self.state_store.get_account_binding(account_id)
        if binding is None:
            raise ValueError("Сначала сохраните настройки автосмены для этой сессии")
        return account, binding

    def rotate_account_profile_photo_now(self, account_id: str) -> dict[str, Any]:
        account, binding = self._get_account_binding_for_automation(account_id)
        if not binding.auto_photo_enabled:
            raise ValueError("Автосмена фото выключена")
        if not binding.photo_library_dir:
            raise ValueError("Не указана папка с фото для автосмены")
        candidates = self._list_profile_photo_candidates(binding.photo_library_dir)
        if not candidates:
            raise ValueError("В папке автосмены фото нет подходящих изображений")
        next_photo = self.state_store.find_available_profile_photo(account_id, candidates)
        profile = self._run_account_profile_update(account_id, photo_path=next_photo)
        binding.last_photo_at = self._now_utc().isoformat()
        binding.last_photo_path = next_photo
        self.state_store.claim_profile_photo(account_id, next_photo)
        binding = self.state_store.update_account_binding(binding)
        profile.update(self._build_profile_automation_payload(binding))
        self.log(f"↻ Фото профиля обновлено вручную для {account['id']}: {Path(next_photo).name}")
        return {"ok": True, "profile": profile}

    def refresh_account_about_now(self, account_id: str) -> dict[str, Any]:
        account, binding = self._get_account_binding_for_automation(account_id)
        if not binding.auto_about_enabled:
            raise ValueError("Автообновление about выключено")
        if not binding.about_topic:
            raise ValueError("Не задана тема для автосмены about")
        next_about = self._generate_about_text(binding.about_topic, account_id)
        profile = self._run_account_profile_update(account_id, about=next_about)
        binding.last_about_at = self._now_utc().isoformat()
        binding.last_about_text = next_about
        binding = self.state_store.update_account_binding(binding)
        profile.update(self._build_profile_automation_payload(binding))
        self.log(f"↻ About обновлён вручную для {account['id']}")
        return {"ok": True, "profile": profile}

    def _profile_scheduler_loop(self) -> None:
        while not self._profile_scheduler_stop.wait(60):
            try:
                self.state_store.load()
                accounts = self.get_accounts()
                for account in accounts:
                    if not account.get("session_ready"):
                        continue
                    binding = self.state_store.get_account_binding(account["id"])
                    if not binding:
                        continue
                    if not binding.auto_photo_enabled and not binding.auto_about_enabled:
                        continue
                    try:
                        self._process_profile_automation_for_account(account, binding)
                    except Exception as exc:
                        self.log(f"⚠ Автопрофиль {account['id']}: {exc}")
            except Exception as exc:
                self.log(f"⚠ Планировщик профиля: {exc}")

    def _session_runtime_status(self, account_id: str) -> str | None:
        if account_id in self._group_chat_account_ids and self._group_chat_running:
            return "group_chat"
        if account_id in self._outreach_account_ids and self._running:
            return "outreach"
        if account_id in self._running_agent_ids and self._agent_running:
            return "agent"
        return None

    def _session_health_payload(
        self,
        status: str,
        *,
        label: str,
        error: str = "",
        runtime: str = "",
    ) -> dict[str, Any]:
        return {
            "status": status,
            "label": label,
            "error": error,
            "runtime": runtime,
            "checked_at": self._now_utc().isoformat(),
        }

    def _get_session_health(self, account_id: str) -> dict[str, Any]:
        cached = self._session_health_cache.get(account_id)
        if cached:
            return dict(cached)
        return {
            "status": "checking",
            "label": "проверяется",
            "error": "",
            "runtime": "",
            "checked_at": "",
        }

    def _is_fatal_session_error(self, error_text: str) -> bool:
        text = (error_text or "").lower()
        fatal_markers = (
            "auth key",
            "authkey",
            "session revoked",
            "unauthorized",
            "not authorized",
            "user deactivated",
            "deleted/deactivated",
            "banned",
        )
        return any(marker in text for marker in fatal_markers)

    async def _probe_session_health(self, session, proxies: dict[str, ProxyConfig]) -> dict[str, Any]:
        runtime = self._session_runtime_status(session.account_id)
        if runtime:
            runtime_labels = {
                "group_chat": "в работе: групповой чат",
                "outreach": "в работе: рассылка",
                "agent": "в работе: агент",
            }
            return self._session_health_payload(
                "busy",
                label=runtime_labels.get(runtime, "в работе"),
                runtime=runtime,
            )

        if session.format == SessionFormat.TDATA and not has_converted_session(session):
            return self._session_health_payload(
                "needs_conversion",
                label="нужна конвертация",
            )

        if not (self.config.telegram_api_id and self.config.telegram_api_hash):
            return self._session_health_payload(
                "unknown",
                label="нет api id/hash",
            )

        proxy = self._proxy_for_account(session.account_id, proxies)
        two_fa_password = read_twofa_password(session, self.config.telegram_2fa_password)
        client = TelegramAccountClient(
            session=session,
            api_id=self.config.telegram_api_id,
            api_hash=self.config.telegram_api_hash,
            proxy=proxy,
            two_fa_password=two_fa_password,
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=self.SESSION_HEALTH_CONNECT_TIMEOUT_SEC)
            return self._session_health_payload("alive", label="жива")
        except Exception as exc:
            error_text = format_telegram_error(exc)
            is_fatal = self._is_fatal_session_error(error_text)
            return self._session_health_payload(
                "dead" if is_fatal else "error",
                label="ошибка сессии",
                error=error_text,
            )
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _probe_all_session_health(
        self,
        sessions: list[Any],
        proxies: dict[str, ProxyConfig],
    ) -> None:
        semaphore = asyncio.Semaphore(self.SESSION_HEALTH_MAX_CONCURRENCY)

        async def run_one(session) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                try:
                    payload = await self._probe_session_health(session, proxies)
                except Exception as exc:
                    payload = self._session_health_payload(
                        "error",
                        label="ошибка проверки",
                        error=str(exc),
                    )
                return session.account_id, payload

        tasks = [asyncio.create_task(run_one(session)) for session in sessions]
        try:
            for task in asyncio.as_completed(tasks):
                account_id, payload = await task
                self._session_health_cache[account_id] = payload
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with contextlib.suppress(Exception):
                    await task

    def _session_health_loop(self) -> None:
        while not self._session_health_stop.is_set():
            try:
                sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
                proxies = load_proxies(self.proxies_path)
                active_ids = {session.account_id for session in sessions}
                stale_ids = [account_id for account_id in self._session_health_cache if account_id not in active_ids]
                for account_id in stale_ids:
                    self._session_health_cache.pop(account_id, None)
                for session in sessions:
                    self._session_health_cache[session.account_id] = {
                        **self._get_session_health(session.account_id),
                        "status": "checking",
                        "label": "проверяется",
                        "error": "",
                    }
                asyncio.run(self._probe_all_session_health(sessions, proxies))
            except Exception as exc:
                self.log(f"⚠ Монитор сессий: {exc}")

            if self._session_health_stop.wait(self.SESSION_HEALTH_INTERVAL_SEC):
                break

    def get_logs(self, since: int = 0) -> list[str]:
        logs = list(self._logs)
        if since > 0:
            return logs[since:]
        return logs

    def _pool_file(self) -> Path:
        return pool_path(self.base_dir)

    def _load_pool_migrated(self):
        pool = load_pool(self._pool_file())
        legacy = load_proxies(self.proxies_path)
        migrated = migrate_legacy_proxies(pool, legacy)
        if migrated:
            save_pool(self._pool_file(), pool)
            for account_id in list(legacy.keys()):
                legacy.pop(account_id, None)
            save_proxies(self.proxies_path, legacy)
            self.roles = RolesConfig.load(self.roles_path)
            for account_id in pool.bindings:
                proxy = resolve_pool_proxy(pool, account_id)
                if proxy:
                    role_prompt = self.roles.prompt_for_account(account_id)
                    group_name = self._role_label(account_id)
                    self.state_store.save_account_binding(account_id, role_prompt, proxy, group_name)
            self.state_store.save()
        return pool

    def _proxy_for_account(self, account_id: str, proxies: dict[str, ProxyConfig] | None = None) -> ProxyConfig | None:
        pool = self._load_pool_migrated()
        pooled = resolve_pool_proxy(pool, account_id)
        if pooled:
            return pooled
        if proxies is None:
            proxies = load_proxies(self.proxies_path)
        proxy = proxies.get(account_id)
        if proxy and proxy.host:
            return proxy
        binding = self.state_store.get_account_binding(account_id)
        if binding:
            saved = binding.to_proxy()
            if saved:
                return saved
        return None

    def _role_label(self, account_id: str) -> str:
        self.roles = RolesConfig.load(self.roles_path)
        return self.roles.role_name_for_account(account_id)

    def sync_roles_to_state(
        self,
        roles: RolesConfig | None = None,
        previous_roles: RolesConfig | None = None,
    ) -> None:
        """Синхронизировать роли из roles.json в state.json (аккаунты и диалоги рассылки)."""
        roles = roles or RolesConfig.load(self.roles_path)
        self.state_store.load()
        proxies = load_proxies(self.proxies_path)
        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        account_ids = {s.account_id for s in sessions} | set(roles.account_assignments.keys())

        for account_id in account_ids:
            role_prompt = roles.prompt_for_account(account_id)
            group_name = roles.role_name_for_account(account_id)
            proxy = self._proxy_for_account(account_id, proxies)
            self.state_store.save_account_binding(account_id, role_prompt, proxy, group_name)

        for dialog in self.state_store.list_all_dialogs():
            if dialog.dialog_mode == "agent":
                continue
            dialog.role_prompt = roles.prompt_for_account(dialog.account_id)
            self.state_store.upsert_dialog(dialog)

        session = self.state_store.group_session
        if session:
            session_changed = False
            for account_id in session.account_ids:
                next_prompt = roles.prompt_for_account(account_id)
                next_name = roles.role_name_for_account(account_id) or "участник"
                current_prompt = str(session.role_prompts.get(account_id) or "")
                current_name = str(session.role_names.get(account_id) or "") or "участник"

                if previous_roles is None:
                    should_update_prompt = True
                    should_update_name = True
                else:
                    prev_prompt = previous_roles.prompt_for_account(account_id)
                    prev_name = previous_roles.role_name_for_account(account_id) or "участник"
                    should_update_prompt = not current_prompt or current_prompt == prev_prompt
                    should_update_name = not current_name or current_name == prev_name

                if should_update_prompt and current_prompt != next_prompt:
                    session.role_prompts[account_id] = next_prompt
                    session_changed = True
                if should_update_name and current_name != next_name:
                    session.role_names[account_id] = next_name
                    session_changed = True

            if session_changed:
                self.state_store.upsert_group_session(session)

        self.state_store.save()

    def get_status(self) -> dict[str, Any]:
        self.state_store.load()
        self.roles = RolesConfig.load(self.roles_path)
        proxies = load_proxies(self.proxies_path)
        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        with_proxy = sum(1 for s in sessions if self._proxy_for_account(s.account_id, proxies))
        session_health = [self._get_session_health(s.account_id).get("status") for s in sessions]
        alive_sessions = sum(1 for status in session_health if status == "alive")
        dead_sessions = sum(1 for status in session_health if status == "dead")
        busy_sessions = sum(1 for status in session_health if status == "busy")

        info = provider_info(self.config.llm_provider)
        return {
            "telegram_ok": bool(self.config.telegram_api_id and self.config.telegram_api_hash),
            "llm_ok": self.config.llm_configured(),
            "grok_ok": self.config.llm_configured(),
            "llm_provider": self.config.llm_provider,
            "llm_provider_name": info.name,
            "llm_model": self.config.get_llm_model(),
            "accounts_count": len(sessions),
            "alive_sessions": alive_sessions,
            "dead_sessions": dead_sessions,
            "busy_sessions": busy_sessions,
            "proxies_count": with_proxy,
            "paused_dialogs": len(self.state_store.list_all_dialogs({"paused"})),
            "running": self._running,
            "agent_running": self._agent_running,
            "group_chat_running": self._group_chat_running,
            "agents_count": len(AgentsConfig.load(self.agents_path).agents),
            "sessions_path": str(self.base_dir / self.config.sessions_dir),
        }

    def get_llm_providers(self) -> list[dict[str, Any]]:
        items = list_providers_dict()
        for item in items:
            item["models"] = static_models(item["id"])
        return items

    def get_llm_models(self, provider_id: str) -> dict[str, Any]:
        self.config = AppConfig.load(self.config_path)
        provider_id = provider_id if provider_id in LLM_PROVIDERS else self.config.llm_provider
        info = provider_info(provider_id)
        api_key = str(getattr(self.config, info.key_field, "") or "").strip()
        if provider_id == "grok" and not api_key:
            api_key = (self.config.grok_api_key or "").strip()
        current = self.config.get_llm_model() if provider_id == self.config.llm_provider else ""
        local_base = self.config.local_base_url if provider_id == "local" else ""

        async def run() -> dict:
            return await resolve_models(provider_id, api_key, current, local_base)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        finally:
            loop.close()

    def get_config_dict(self) -> dict[str, Any]:
        return {
            "telegram_api_id": self.config.telegram_api_id,
            "telegram_api_hash": self.config.telegram_api_hash,
            "llm_provider": self.config.llm_provider,
            "llm_model": self.config.get_llm_model(),
            "grok_api_key": self.config.grok_api_key,
            "grok_model": self.config.grok_model,
            "openai_api_key": self.config.openai_api_key,
            "gemini_api_key": self.config.gemini_api_key,
            "anthropic_api_key": self.config.anthropic_api_key,
            "deepseek_api_key": self.config.deepseek_api_key,
            "openrouter_api_key": self.config.openrouter_api_key,
            "local_api_key": self.config.local_api_key,
            "local_base_url": self.config.local_base_url,
            "delay_between_messages_sec": self.config.delay_between_messages_sec,
            "max_concurrent_accounts": self.config.max_concurrent_accounts,
            "message_language": self.config.message_language,
            "reply_delay_min_sec": self.config.reply_delay_min_sec,
            "reply_delay_max_sec": self.config.reply_delay_max_sec,
            "telegram_2fa_password": self.config.telegram_2fa_password,
        }

    def save_config(self, data: dict[str, Any]) -> None:
        self.config.telegram_api_id = int(data.get("telegram_api_id") or 0)
        self.config.telegram_api_hash = str(data.get("telegram_api_hash") or "")
        self.config.llm_provider = str(data.get("llm_provider") or "grok")
        self.config.llm_model = str(data.get("llm_model") or "")
        self.config.grok_api_key = str(data.get("grok_api_key") or "")
        self.config.grok_model = str(data.get("grok_model") or "grok-3-mini")
        self.config.openai_api_key = str(data.get("openai_api_key") or "")
        self.config.gemini_api_key = str(data.get("gemini_api_key") or "")
        self.config.anthropic_api_key = str(data.get("anthropic_api_key") or "")
        self.config.deepseek_api_key = str(data.get("deepseek_api_key") or "")
        self.config.openrouter_api_key = str(data.get("openrouter_api_key") or "")
        self.config.local_api_key = str(data.get("local_api_key") or "")
        self.config.local_base_url = str(data.get("local_base_url") or "http://127.0.0.1:8000/v1")
        if self.config.llm_provider == "grok" and not self.config.grok_api_key:
            self.config.grok_api_key = self.config.get_llm_api_key()
        self.config.delay_between_messages_sec = int(data.get("delay_between_messages_sec") or 30)
        self.config.max_concurrent_accounts = int(data.get("max_concurrent_accounts") or 5)
        self.config.message_language = str(data.get("message_language") or "ru")
        self.config.reply_delay_min_sec = int(data.get("reply_delay_min_sec") or 5)
        self.config.reply_delay_max_sec = int(data.get("reply_delay_max_sec") or 25)
        self.config.telegram_2fa_password = str(data.get("telegram_2fa_password") or "")
        self.config.proxies_file = "config/proxies.json"
        self.config.state_file = "data/state.json"
        self.config.save(self.config_path)
        self.state_store = StateStore(self.base_dir / self.config.state_file)

    def _agent_account_ids(self) -> set[str]:
        cfg = AgentsConfig.load(self.agents_path)
        return {a.account_id for a in cfg.agents if a.enabled}

    def _agent_names(self) -> dict[str, str]:
        cfg = AgentsConfig.load(self.agents_path)
        return {a.account_id: a.name for a in cfg.agents if a.enabled}

    def _resolve_outreach_account_ids(self, account_ids: list[str] | None) -> tuple[list[str], list[str]]:
        """Аккаунты для рассылки: без ассистентов и только с рабочим .session."""
        agent_ids = self._agent_account_ids()
        eligible = {a["id"] for a in self.get_accounts() if a.get("outreach_eligible")}
        skipped_agents: list[str] = []

        if account_ids:
            chosen = set(account_ids)
            skipped_agents = sorted(chosen & agent_ids)
            outreach_ids = sorted((chosen - agent_ids) & eligible)
        else:
            outreach_ids = sorted(eligible)

        return outreach_ids, skipped_agents

    def get_accounts(self) -> list[dict[str, Any]]:
        self.state_store.load()
        self.roles = RolesConfig.load(self.roles_path)
        proxies = load_proxies(self.proxies_path)
        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        all_ids = {s.account_id for s in sessions}
        agent_ids = self._agent_account_ids()
        agent_names = self._agent_names()
        result = []
        pool = self._load_pool_migrated()
        for s in sessions:
            proxy = self._proxy_for_account(s.account_id, proxies)
            proxy_id = pool.bindings.get(s.account_id, "")
            proxy_item = pool.item_by_id(proxy_id) if proxy_id else None
            out = session_output_path(s) if s.format == SessionFormat.TDATA else s.path
            twofa_file = find_twofa_file(s)
            session_ready = s.format == SessionFormat.TELEthon or has_converted_session(s)
            is_assistant = s.account_id in agent_ids
            health = self._get_session_health(s.account_id)
            health_status = str(health.get("status", "checking"))
            is_active = session_ready and health_status != "dead"
            outreach_eligible = is_active and not is_assistant
            result.append(
                {
                    "id": s.account_id,
                    "format": s.format.value,
                    "proxy": proxy_item.display_label() if proxy_item else (f"{proxy.host}:{proxy.port}" if proxy else ""),
                    "proxy_id": proxy_id,
                    "role": self._role_label(s.account_id),
                    "session_file": str(out.name) if out.exists() else "",
                    "session_ready": session_ready,
                    "is_active": is_active,
                    "is_assistant": is_assistant,
                    "assistant_name": agent_names.get(s.account_id, ""),
                    "outreach_eligible": outreach_eligible,
                    "twofa_file": twofa_file.name if twofa_file else "",
                    "is_duplicate": is_import_duplicate(s.account_id, all_ids),
                    "session_health": health_status,
                    "session_health_label": health.get("label", "проверяется"),
                    "session_health_error": health.get("error", ""),
                    "session_health_checked_at": health.get("checked_at", ""),
                    "session_health_runtime": health.get("runtime", ""),
                }
            )
        return result

    def convert_tdata(self, account_ids: list[str] | None = None) -> dict[str, Any]:
        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        targets = [s for s in sessions if s.format == SessionFormat.TDATA]
        if account_ids:
            allowed = set(account_ids)
            targets = [s for s in targets if s.account_id in allowed]
        if not targets:
            return {"ok": 0, "failed": 0, "results": [], "message": "Нет tdata для конвертации"}

        global_password = self.config.telegram_2fa_password
        api_id = self.config.telegram_api_id
        api_hash = self.config.telegram_api_hash

        async def run_all() -> list[ConvertResult]:
            results: list[ConvertResult] = []
            for session in targets:
                out_path = session_output_path(session)
                if has_converted_session(session) and out_path.exists():
                    if api_id and api_hash and await verify_converted_session(session, api_id, api_hash):
                        results.append(
                            ConvertResult(
                                account_id=session.account_id,
                                success=True,
                                output_path=str(out_path),
                                error="Уже есть .session — пропущено",
                            )
                        )
                        continue
                    remove_session_artifacts(out_path)
                pwd = read_twofa_password(session, global_password)
                results.append(await convert_tdata_to_session(session, pwd))
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run_all())
        finally:
            loop.close()

        ok = sum(1 for r in results if r.success)
        failed = len(results) - ok
        for r in results:
            if r.success and r.error.startswith("OK"):
                self.log(f"✓ Конверт: {r.account_id} → {Path(r.output_path).name}")
            elif r.success:
                self.log(f"↷ {r.account_id}: {r.error}")
            else:
                self.log(f"✗ Конверт {r.account_id}: {r.error}")

        return {
            "ok": ok,
            "failed": failed,
            "results": [
                {
                    "account_id": r.account_id,
                    "success": r.success,
                    "output_path": r.output_path,
                    "message": r.error,
                }
                for r in results
            ],
        }

    def get_proxy_pool(self) -> dict[str, Any]:
        pool = self._load_pool_migrated()
        return pool_to_api(pool)

    def import_proxy_pool(self, lines: list[str], proxy_type: str = "socks5") -> dict[str, Any]:
        pool = self._load_pool_migrated()
        report = import_lines_verified(pool, lines, proxy_type)
        save_pool(self._pool_file(), pool)
        self.log(
            f"✓ Прокси: +{report.added}, дублей {report.skipped_duplicate}, "
            f"мёртвых {report.skipped_dead}, ошибок разбора {report.skipped_parse}"
        )
        return {"ok": True, "total": len(pool.items), **report.to_dict()}

    def recheck_proxy_pool(self, proxy_ids: list[str] | None = None) -> dict[str, Any]:
        pool = self._load_pool_migrated()
        report = recheck_pool_items(pool, proxy_ids)
        save_pool(self._pool_file(), pool)
        self.log(f"✓ Перепроверка прокси: ok {report.added}, мёртвых {report.skipped_dead}")
        return {"ok": True, "total": len(pool.items), **report.to_dict()}

    def delete_proxy_pool_item(self, proxy_id: str, unbind: bool = False) -> None:
        pool = self._load_pool_migrated()
        try:
            ok, affected = delete_pool_item(pool, proxy_id, unbind=unbind)
        except ValueError:
            raise
        if not ok:
            raise ValueError("Прокси не найден")
        save_pool(self._pool_file(), pool)
        if unbind:
            for account_id in affected:
                self._sync_account_proxy_binding(account_id, None)
        self.log(f"✓ Прокси удалён из пула: {proxy_id}")

    def bulk_delete_proxy_pool(self, proxy_ids: list[str], unbind: bool = True) -> dict[str, Any]:
        pool = self._load_pool_migrated()
        ids = [str(x).strip() for x in proxy_ids if str(x).strip()]
        deleted, affected = delete_pool_items(pool, ids, unbind=unbind)
        save_pool(self._pool_file(), pool)
        if unbind:
            for account_id in affected:
                self._sync_account_proxy_binding(account_id, None)
        self.log(f"✓ Удалено прокси: {deleted}")
        return {"ok": True, "deleted": deleted, "unbound_accounts": affected, "total": len(pool.items)}

    def purge_dead_proxy_pool(self, unbind: bool = True) -> dict[str, Any]:
        pool = self._load_pool_migrated()
        deleted, affected = purge_dead_pool_items(pool, unbind=unbind)
        save_pool(self._pool_file(), pool)
        if unbind:
            for account_id in affected:
                self._sync_account_proxy_binding(account_id, None)
        self.log(f"✓ Удалены мёртвые прокси: {deleted}")
        return {"ok": True, "deleted": deleted, "unbound_accounts": affected, "total": len(pool.items)}

    def auto_bind_proxies(
        self,
        account_ids: list[str] | None = None,
        proxy_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        pool = self._load_pool_migrated()
        accounts = self.get_accounts()
        allowed_accounts = set(account_ids or [])
        if allowed_accounts:
            targets = [a for a in accounts if a["id"] in allowed_accounts]
        else:
            targets = [a for a in accounts if not a.get("proxy_id")]

        allowed_proxies = set(proxy_ids or [])
        if allowed_proxies:
            free_proxies = [
                pool.item_by_id(pid)
                for pid in allowed_proxies
                if pool.item_by_id(pid) and pool.item_by_id(pid).status != "dead"
            ]
        else:
            free_proxies = [
                item
                for item in pool.items
                if item.status == "ok" and pool.usage_count(item.id) == 0
            ]

        free_proxies = [p for p in free_proxies if p]
        paired = min(len(targets), len(free_proxies))
        pairs: list[dict[str, str]] = []
        for i in range(paired):
            acc_id = targets[i]["id"]
            proxy_id = free_proxies[i].id
            bind_account(pool, acc_id, proxy_id)
            proxy = resolve_pool_proxy(pool, acc_id)
            self._sync_account_proxy_binding(acc_id, proxy)
            pairs.append({"account_id": acc_id, "proxy_id": proxy_id})

        save_pool(self._pool_file(), pool)
        self.log(f"✓ Автопривязка: {paired} пар")
        return {
            "ok": True,
            "paired": paired,
            "pairs": pairs,
            "accounts_without_proxy": max(0, len(targets) - paired),
            "proxies_left": max(0, len(free_proxies) - paired),
        }

    def bind_account_proxy(self, account_id: str, proxy_id: str | None) -> None:
        pool = self._load_pool_migrated()
        bind_account(pool, account_id, proxy_id)
        save_pool(self._pool_file(), pool)
        proxies = load_proxies(self.proxies_path)
        proxies.pop(account_id, None)
        save_proxies(self.proxies_path, proxies)
        proxy = resolve_pool_proxy(pool, account_id) if proxy_id else None
        self._sync_account_proxy_binding(account_id, proxy)
        label = pool.item_by_id(proxy_id).display_label() if proxy_id and pool.item_by_id(proxy_id) else "—"
        self.log(f"✓ Прокси для {account_id}: {label}")

    def _sync_account_proxy_binding(self, account_id: str, proxy: ProxyConfig | None) -> None:
        self.roles = RolesConfig.load(self.roles_path)
        role_prompt = self.roles.prompt_for_account(account_id)
        group_name = self._role_label(account_id)
        self.state_store.save_account_binding(account_id, role_prompt, proxy, group_name)

    def get_proxy_form(self, account_id: str) -> dict[str, Any]:
        pool = self._load_pool_migrated()
        proxy_id = pool.bindings.get(account_id, "")
        proxy = self._proxy_for_account(account_id)
        if not proxy:
            return {
                "proxy_id": "",
                "type": "socks5",
                "host": "",
                "port": "",
                "username": "",
                "password": "",
            }
        return {
            "proxy_id": proxy_id,
            "type": proxy.proxy_type,
            "host": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": proxy.password,
        }

    def save_proxy(self, account_id: str, data: dict[str, Any]) -> None:
        """Ручной ввод: проверить, добавить в пул и привязать."""
        pool = self._load_pool_migrated()
        port = int(data.get("port") or 0)
        host = str(data.get("host") or "").strip()
        if not host or not port:
            raise ValueError("Укажите адрес и порт")
        proxy_type = str(data.get("type") or "socks5")
        username = str(data.get("username") or "")
        password = str(data.get("password") or "")

        from core.proxy_checker import proxy_fingerprint

        fp = proxy_fingerprint(proxy_type, host, port, username, password)
        existing = next((x for x in pool.items if x.fingerprint() == fp), None)
        if existing:
            if existing.status == "dead":
                raise ValueError("Такой прокси уже в пуле и помечен как нерабочий")
            pool.bindings[account_id] = existing.id
        else:
            item = create_pool_item(proxy_type, host, port, username, password)
            pool.items.append(item)
            pool.bindings[account_id] = item.id
        save_pool(self._pool_file(), pool)
        proxies = load_proxies(self.proxies_path)
        proxies.pop(account_id, None)
        save_proxies(self.proxies_path, proxies)
        proxy = resolve_pool_proxy(pool, account_id)
        self._sync_account_proxy_binding(account_id, proxy)

    def clear_proxy(self, account_id: str) -> None:
        self.bind_account_proxy(account_id, None)

    def bulk_proxies(self, lines: list[str], proxy_type: str = "socks5") -> int:
        result = self.import_proxy_pool(lines, proxy_type)
        return int(result.get("added", 0))

    def bulk_update_profiles(self, data: dict[str, Any]) -> dict[str, Any]:
        account_ids = [str(x).strip() for x in (data.get("account_ids") or []) if str(x).strip()]
        generate_mode = str(data.get("generate_mode") or "manual").strip().lower()
        lang = str(data.get("lang") or "ru").strip().lower()
        with_username = bool(data.get("with_username"))

        if generate_mode in ("names", "nicks"):
            change_first = True
            change_last = generate_mode == "names" or generate_mode == "nicks"
            change_username = with_username
        else:
            change_first = bool(data.get("change_first_name"))
            change_last = bool(data.get("change_last_name"))
            change_username = bool(data.get("change_username"))

        first_template = str(data.get("first_name") or "")
        last_template = str(data.get("last_name") or "")
        username_template = str(data.get("username") or "")

        if not account_ids:
            return {"ok": 0, "failed": 0, "results": [], "message": "Не выбраны аккаунты"}
        if generate_mode == "manual" and not any([change_first, change_last, change_username]):
            return {"ok": 0, "failed": 0, "results": [], "message": "Отметьте, что менять: имя, фамилию или username"}

        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            return {"ok": 0, "failed": len(account_ids), "results": [], "message": "Укажите Telegram API ID и Hash"}

        accounts_map = {a["id"]: a for a in self.get_accounts()}
        allowed = set(account_ids)
        targets = [accounts_map[aid] for aid in sorted(allowed, key=str.lower) if aid in accounts_map]
        if not targets:
            return {"ok": 0, "failed": 0, "results": [], "message": "Аккаунты не найдены"}

        sessions = {s.account_id: s for s in discover_sessions(self.base_dir / self.config.sessions_dir)}
        proxies = load_proxies(self.proxies_path)
        global_2fa = self.config.telegram_2fa_password
        delay = max(2, min(int(data.get("delay_sec") or 3), 60))
        used_usernames: set[str] = set()

        async def run_all() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            ready_targets = [a for a in targets if a.get("session_ready")]
            skipped = [a for a in targets if not a.get("session_ready")]
            for account in skipped:
                results.append(
                    {
                        "account_id": account["id"],
                        "success": False,
                        "message": "Нет рабочего .session — сначала конвертируйте tdata",
                    }
                )

            for index, account in enumerate(ready_targets):
                acc_id = account["id"]
                session = sessions.get(acc_id)
                if not session:
                    results.append(
                        {"account_id": acc_id, "success": False, "message": "Сессия не найдена в папке sessions"}
                    )
                    continue

                first_name = None
                last_name = None
                username = None

                if generate_mode in ("names", "nicks"):
                    generated = generate_profile(
                        generate_mode,
                        lang,
                        with_username=with_username,
                        used_usernames=used_usernames,
                    )
                    first_name = generated.first_name
                    last_name = generated.last_name if change_last else None
                    username = generated.username if change_username and generated.username else None
                else:
                    if change_first:
                        first_name = apply_profile_template(first_template, acc_id, index)
                    if change_last:
                        last_name = apply_profile_template(last_template, acc_id, index)
                    if change_username:
                        username = apply_profile_template(username_template, acc_id, index)

                proxy = self._proxy_for_account(acc_id, proxies)
                pwd = read_twofa_password(session, global_2fa)
                client = TelegramAccountClient(
                    session,
                    self.config.telegram_api_id,
                    self.config.telegram_api_hash,
                    proxy,
                    pwd,
                )
                try:
                    await client.connect()
                    profile = await client.update_profile(
                        first_name=first_name,
                        last_name=last_name,
                        username=username,
                    )
                    label = profile["username"] or profile["first_name"] or acc_id
                    results.append(
                        {
                            "account_id": acc_id,
                            "success": True,
                            "message": (
                                f"{profile['first_name']} {profile['last_name']}".strip()
                                + (f" @{profile['username']}" if profile["username"] else "")
                            ).strip()
                            or label,
                            "profile": profile,
                        }
                    )
                    self.log(f"✓ Профиль {acc_id}: {results[-1]['message']}")
                except Exception as exc:
                    err = format_telegram_error(exc)
                    results.append({"account_id": acc_id, "success": False, "message": err})
                    self.log(f"✗ Профиль {acc_id}: {err}")
                finally:
                    await client.disconnect()

                if index + 1 < len(ready_targets):
                    await asyncio.sleep(delay)
            return results

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(run_all())
        finally:
            loop.close()

        ok = sum(1 for r in results if r["success"])
        failed = len(results) - ok
        return {
            "ok": ok,
            "failed": failed,
            "results": results,
            "message": f"Готово: {ok} успешно, {failed} ошибок",
        }

    def preview_profile_generation(self, data: dict[str, Any]) -> dict[str, Any]:
        mode = str(data.get("generate_mode") or "names").strip().lower()
        if mode not in ("names", "nicks"):
            mode = "names"
        lang = str(data.get("lang") or "ru").strip().lower()
        count = int(data.get("count") or 5)
        with_username = bool(data.get("with_username"))
        samples = preview_profiles(mode, lang, count, with_username)
        return {"samples": samples}

    def get_account_profile(self, account_id: str) -> dict[str, Any]:
        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            raise ValueError("Сначала заполните Telegram API ID и Hash")
        account = next((acc for acc in self.get_accounts() if acc["id"] == account_id), None)
        if not account:
            raise ValueError("Аккаунт не найден")
        if not account.get("session_ready"):
            raise ValueError("Для аккаунта нет рабочего .session")

        sessions = {s.account_id: s for s in discover_sessions(self.base_dir / self.config.sessions_dir)}
        session = sessions.get(account_id)
        if not session:
            raise ValueError("Сессия не найдена в папке sessions")

        proxies = load_proxies(self.proxies_path)
        proxy = self._proxy_for_account(account_id, proxies)
        pwd = read_twofa_password(session, self.config.telegram_2fa_password)
        client = TelegramAccountClient(
            session,
            self.config.telegram_api_id,
            self.config.telegram_api_hash,
            proxy,
            pwd,
        )

        async def run_one() -> dict[str, Any]:
            await client.connect()
            try:
                return await client.get_profile()
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run_one())
        finally:
            loop.close()

    def update_account_profile(self, account_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            raise ValueError("Сначала заполните Telegram API ID и Hash")
        account = next((acc for acc in self.get_accounts() if acc["id"] == account_id), None)
        if not account:
            raise ValueError("Аккаунт не найден")
        if not account.get("session_ready"):
            raise ValueError("Для аккаунта нет рабочего .session")

        sessions = {s.account_id: s for s in discover_sessions(self.base_dir / self.config.sessions_dir)}
        session = sessions.get(account_id)
        if not session:
            raise ValueError("Сессия не найдена в папке sessions")

        proxies = load_proxies(self.proxies_path)
        proxy = self._proxy_for_account(account_id, proxies)
        pwd = read_twofa_password(session, self.config.telegram_2fa_password)
        client = TelegramAccountClient(
            session,
            self.config.telegram_api_id,
            self.config.telegram_api_hash,
            proxy,
            pwd,
        )

        def clean_text(value: Any) -> str | None:
            if value is None:
                return None
            return str(value).strip()

        async def run_one() -> dict[str, Any]:
            await client.connect()
            try:
                profile = await client.update_profile(
                    first_name=clean_text(data.get("first_name")),
                    last_name=clean_text(data.get("last_name")),
                    username=clean_text(data.get("username")),
                    about=clean_text(data.get("about")),
                    photo_path=clean_text(data.get("photo_path")),
                )
                return {"ok": True, "profile": profile}
            finally:
                await client.disconnect()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run_one())
        finally:
            loop.close()

    def update_account_profile(self, account_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            raise ValueError("Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° Ð·Ð°Ð¿Ð¾Ð»Ð½Ð¸Ñ‚Ðµ Telegram API ID Ð¸ Hash")
        account = next((acc for acc in self.get_accounts() if acc["id"] == account_id), None)
        if not account:
            raise ValueError("ÐÐºÐºÐ°ÑƒÐ½Ñ‚ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½")
        if not account.get("session_ready"):
            raise ValueError("Ð”Ð»Ñ Ð°ÐºÐºÐ°ÑƒÐ½Ñ‚Ð° Ð½ÐµÑ‚ Ñ€Ð°Ð±Ð¾Ñ‡ÐµÐ³Ð¾ .session")

        if bool(data.get("auto_photo_enabled")):
            library_dir = str(data.get("photo_library_dir") or "").strip()
            if not library_dir:
                raise ValueError("Ð£ÐºÐ°Ð¶Ð¸Ñ‚Ðµ Ð¿Ð°Ð¿ÐºÑƒ Ñ Ñ„Ð¾Ñ‚Ð¾ Ð´Ð»Ñ Ð°Ð²Ñ‚Ð¾ÑÐ¼ÐµÐ½Ñ‹")
            candidates = self._list_profile_photo_candidates(library_dir)
            if not candidates:
                raise ValueError("Ð’ ÑƒÐºÐ°Ð·Ð°Ð½Ð½Ð¾Ð¹ Ð¿Ð°Ð¿ÐºÐµ Ð½ÐµÑ‚ Ð¿Ð¾Ð´Ñ…Ð¾Ð´ÑÑ‰Ð¸Ñ… Ð¸Ð·Ð¾Ð±Ñ€Ð°Ð¶ÐµÐ½Ð¸Ð¹")
        if bool(data.get("auto_about_enabled")) and not str(data.get("about_topic") or "").strip():
            raise ValueError("Ð£ÐºÐ°Ð¶Ð¸Ñ‚Ðµ Ñ‚ÐµÐ¼Ñƒ Ð´Ð»Ñ Ð°Ð²Ñ‚Ð¾Ð¾Ð±Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ñ Ð¾ ÑÐµÐ±Ðµ")

        result = self._run_account_profile_update(
            account_id,
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            username=data.get("username"),
            about=data.get("about"),
            photo_path=data.get("photo_path"),
        )
        binding = self._update_account_automation_settings(account_id, data)
        profile = result.setdefault("profile", {})
        if not isinstance(profile, dict):
            profile = {}
            result["profile"] = profile
        profile.update(self._build_profile_automation_payload(binding))
        return result

    def get_roles_dict(self) -> dict[str, Any]:
        self.roles = RolesConfig.load(self.roles_path)
        accounts = self.get_accounts()
        role_accounts = filter_accounts_for_roles(accounts)
        assignments: dict[str, str] = {}
        for acc in accounts:
            assignments[acc["id"]] = self.roles.account_assignments.get(acc["id"], "")
        return {
            "default_role": self.roles.default_role,
            "master_prompt": self.roles.master_prompt.to_dict(),
            "groups": [
                {
                    "name": g.name,
                    "role_prompt": g.role_prompt,
                }
                for g in self.roles.groups
            ],
            "all_accounts": role_accounts,
            "assignments": assignments,
        }

    def save_roles(self, data: dict[str, Any]) -> None:
        existing = RolesConfig.load(self.roles_path)
        master = existing.master_prompt
        if "master_prompt" in data and isinstance(data.get("master_prompt"), dict):
            master = MasterPromptConfig.from_dict(data["master_prompt"])

        groups = [
            RoleGroup(
                name=str(g.get("name") or "Без названия"),
                role_prompt=str(g.get("role_prompt") or ""),
                accounts=[],
            )
            for g in data.get("groups") or []
        ]
        assignments = {str(k): str(v or "") for k, v in (data.get("assignments") or {}).items()}
        default_role = str(data.get("default_role") or existing.default_role)
        if not groups and "groups" not in data:
            groups = existing.groups
        if not assignments and "assignments" not in data:
            assignments = existing.account_assignments

        self.roles = RolesConfig(
            default_role=default_role,
            groups=groups,
            account_assignments=assignments,
            master_prompt=master,
        )
        self.roles.sync_group_accounts_from_assignments()
        self.roles.save(self.roles_path)
        master.save(self.master_prompt_path)
        self.sync_roles_to_state(self.roles, previous_roles=existing)

    def get_dialogs(self) -> list[dict[str, Any]]:
        self.state_store.load()
        status_map = {"active": "активен", "paused": "на паузе", "closed": "закрыт"}
        items = []
        for d in self.state_store.list_all_dialogs():
            items.append(
                {
                    "key": d.key,
                    "account_id": d.account_id,
                    "target": d.target_username,
                    "status": d.status,
                    "status_label": status_map.get(d.status, d.status),
                    "auto_reply": d.auto_reply,
                    "goal": d.goal,
                    "replies_count": d.replies_count,
                    "max_replies": d.max_replies,
                    "messages_count": len(d.messages),
                    "dialog_mode": d.dialog_mode,
                    "last_activity": (d.last_activity or d.created_at or "")[:19].replace("T", " "),
                }
            )
        return items

    def get_dialog_detail(self, key: str) -> dict[str, Any] | None:
        self.state_store.load()
        d = self.state_store.get_dialog_by_key(key)
        if not d:
            return None
        return {
            "key": d.key,
            "account_id": d.account_id,
            "target": d.target_username,
            "status": d.status,
            "auto_reply": d.auto_reply,
            "goal": d.goal,
            "extra_context": d.extra_context,
            "dialog_extra_context": d.dialog_extra_context,
            "max_replies": d.max_replies,
            "replies_count": d.replies_count,
            "notes": d.notes,
            "language": d.language,
            "role_prompt": d.role_prompt[:200] + "..." if len(d.role_prompt) > 200 else d.role_prompt,
            "messages": [
                {"role": m.role, "content": m.content, "ts": m.ts[:19].replace("T", " ")}
                for m in d.messages[-50:]
            ],
        }

    def update_dialog(self, key: str, data: dict[str, Any]) -> bool:
        self.state_store.load()
        d = self.state_store.get_dialog_by_key(key)
        if not d:
            return False
        if "status" in data:
            d.status = str(data["status"])
        if "auto_reply" in data:
            d.auto_reply = bool(data["auto_reply"])
        if "goal" in data:
            d.goal = str(data["goal"])
        if "dialog_extra_context" in data:
            d.dialog_extra_context = str(data["dialog_extra_context"])
        if "max_replies" in data:
            d.max_replies = int(data["max_replies"] or 0)
        if "notes" in data:
            d.notes = str(data["notes"])
        if "replies_count" in data:
            d.replies_count = int(data["replies_count"] or 0)
        self.state_store.upsert_dialog(d)
        return True

    def delete_dialog_record(self, key: str) -> bool:
        self.state_store.load()
        return self.state_store.delete_dialog(key)

    def clear_dialog_memory(self, key: str) -> bool:
        self.state_store.load()
        return self.state_store.clear_dialog_memory(key)

    def clear_dialogs(self, account_id: str | None = None, delete_completely: bool = True) -> int:
        """Удалить диалоги (память переписки). account_id=None — все диалоги."""
        self.state_store.load()
        if account_id:
            if delete_completely:
                count = self.state_store.delete_dialogs_for_account(account_id)
            else:
                count = 0
                for d in self.state_store.list_dialogs_for_account(account_id):
                    if self.state_store.clear_dialog_memory(d.key):
                        count += 1
        elif delete_completely:
            count = self.state_store.delete_all_dialogs()
        else:
            count = 0
            for d in self.state_store.list_all_dialogs():
                if self.state_store.clear_dialog_memory(d.key):
                    count += 1
        return count

    def get_dialog_settings(self) -> dict[str, Any]:
        return DialogSettings.load(self.dialog_settings_path).to_dict()

    def save_dialog_settings(self, data: dict[str, Any]) -> None:
        settings = DialogSettings.from_dict(data)
        settings.save(self.dialog_settings_path)

    def get_master_prompt(self) -> dict[str, Any]:
        self.roles = RolesConfig.load(self.roles_path)
        return self.roles.master_prompt.to_dict()

    def save_master_prompt(self, data: dict[str, Any]) -> None:
        self.roles = RolesConfig.load(self.roles_path)
        self.roles.master_prompt = MasterPromptConfig.from_dict(data)
        self.roles.save(self.roles_path)
        self.roles.master_prompt.save(self.master_prompt_path)

    def get_agents(self) -> list[dict[str, Any]]:
        cfg = AgentsConfig.load(self.agents_path)
        accounts = {a["id"] for a in self.get_accounts()}
        result = []
        for agent in cfg.agents:
            result.append(
                {
                    **agent.to_dict(),
                    "account_exists": agent.account_id in accounts,
                    "running": agent.account_id in self._running_agent_ids,
                }
            )
        return result

    def save_agent(self, data: dict[str, Any]) -> None:
        account_id = str(data.get("account_id") or "").strip()
        if not account_id:
            raise ValueError("Выберите аккаунт")
        agent = SecretaryAgent(
            account_id=account_id,
            name=str(data.get("name") or "Секретарь"),
            prompt=str(data.get("prompt") or DEFAULT_SECRETARY_PROMPT),
            language=str(data.get("language") or "ru"),
            extra_context=str(data.get("extra_context") or ""),
            goal=str(data.get("goal") or ""),
            allowed_users=data.get("allowed_users") or [],
            blocked_users=data.get("blocked_users") or [],
            enabled=bool(data.get("enabled", True)),
        )
        cfg = AgentsConfig.load(self.agents_path)
        cfg.upsert(agent)
        cfg.save(self.agents_path)
        self.log(f"🤖 Ассистент: {account_id} ({agent.name}) — исключён из общей рассылки")

    def delete_agent(self, account_id: str) -> bool:
        cfg = AgentsConfig.load(self.agents_path)
        if not cfg.remove(account_id):
            return False
        cfg.save(self.agents_path)
        return True

    def get_agent_stats(self) -> dict[str, Any]:
        return {
            "running": self._agent_running,
            "active_accounts": self._agent_stats.active_accounts,
            "replies_sent": self._agent_stats.replies_sent,
            "messages_received": self._agent_stats.messages_received,
            "active_dialogs": self._agent_stats.active_dialogs,
            "running_accounts": sorted(self._running_agent_ids),
        }

    def start_agents(self, account_ids: list[str] | None = None) -> tuple[bool, str]:
        with self._lock:
            if self._agent_running:
                return False, "Секретарь уже работает"
            if not self.config.telegram_api_id or not self.config.telegram_api_hash:
                return False, "Укажите Telegram API ID и Hash"
            if not self.config.llm_configured():
                info = provider_info(self.config.llm_provider)
                return False, f"Укажите API-ключ для {info.name}"

            cfg = AgentsConfig.load(self.agents_path)
            enabled = [a for a in cfg.agents if a.enabled]
            if not enabled:
                return False, "Нет настроенных AI-агентов"

            if account_ids:
                allowed = set(account_ids)
                to_run = [a for a in enabled if a.account_id in allowed]
            else:
                to_run = enabled

            if not to_run:
                return False, "Выберите агентов для запуска"

            sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
            session_ids = {s.account_id for s in sessions}
            missing = [a.account_id for a in to_run if a.account_id not in session_ids]
            if missing:
                return False, f"Аккаунты не найдены: {', '.join(missing[:3])}"

            if self._running:
                overlap = set(a.account_id for a in to_run) & self._get_outreach_account_ids()
                if overlap:
                    return False, f"Аккаунты заняты рассылкой: {', '.join(sorted(overlap))}"
            if self._group_chat_running:
                overlap = set(a.account_id for a in to_run) & self._group_chat_account_ids
                if overlap:
                    return False, f"Аккаунты заняты групповым чатом: {', '.join(sorted(overlap))}"

            run_ids = [a.account_id for a in to_run]
            self._agent_running = True
            self._running_agent_ids = set(run_ids)
            self._agent_stats = AgentStats(running=True)

        self.agent_engine = AgentEngine(
            self.config,
            self.base_dir,
            log=self.log,
            on_stats=lambda s: setattr(self, "_agent_stats", s),
        )

        def run_async() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.agent_engine.run(run_ids))
            finally:
                loop.close()
                with self._lock:
                    self._agent_running = False
                    self._running_agent_ids = set()
                self.log("■ Секретарь завершён")

        self.agent_thread = threading.Thread(target=run_async, daemon=True)
        self.agent_thread.start()
        self.log(f"▶ Секретарь запущен: {', '.join(run_ids)}")
        return True, "OK"

    def stop_agents(self) -> None:
        if self.agent_engine:
            self.agent_engine.stop()
            self.log("■ Останавливаем секретаря...")

    def _get_outreach_account_ids(self) -> set[str]:
        return set(self._outreach_account_ids)

    def get_engine_stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total": self._stats.total,
            "success": self._stats.success,
            "failed": self._stats.failed,
            "skipped": self._stats.skipped,
            "replies_sent": self._stats.replies_sent,
            "active_dialogs": self._stats.active_dialogs,
        }

    def start_engine(
        self,
        targets: list[str],
        account_ids: list[str] | None,
        extra_context: str,
        enable_dialog: bool,
        resume_existing: bool,
        resume_only: bool = False,
    ) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return False, "Уже работает"

            if not self.config.telegram_api_id or not self.config.telegram_api_hash:
                return False, "Укажите Telegram API ID и Hash"
            if not self.config.llm_configured():
                info = provider_info(self.config.llm_provider)
                return False, f"Укажите API-ключ для {info.name}"

            sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
            if not sessions:
                return False, "Нет аккаунтов в папке sessions"

            if resume_only:
                self.state_store.load()
                if not self.state_store.list_all_dialogs({"paused", "active"}):
                    return False, "Нет сохранённых диалогов"

            if not resume_only and not targets and not resume_existing:
                return False, "Укажите username или включите продолжение диалогов"

            outreach_list, skipped_agents = self._resolve_outreach_account_ids(account_ids)
            if skipped_agents:
                self.log(f"↷ Ассистенты не участвуют в рассылке: {', '.join(skipped_agents)}")
            if not outreach_list:
                return False, "Нет аккаунтов для рассылки (ассистенты и неактивные исключены)"

            outreach_ids = set(outreach_list)
            if self._agent_running:
                overlap = outreach_ids & self._running_agent_ids
                if overlap:
                    return False, f"Аккаунты заняты секретарём: {', '.join(sorted(overlap))}"
            if self._group_chat_running:
                overlap = outreach_ids & self._group_chat_account_ids
                if overlap:
                    return False, f"Аккаунты заняты групповым чатом: {', '.join(sorted(overlap))}"

            self._running = True
            self._stats = EngineStats()
            self.roles = RolesConfig.load(self.roles_path)
            self.sync_roles_to_state(self.roles)
            self._outreach_account_ids = outreach_ids

        run_targets = [] if resume_only else targets
        if resume_only:
            enable_dialog = True
            resume_existing = True

        self.engine = DialogEngine(
            self.config,
            self.roles,
            self.base_dir,
            log=self.log,
            on_stats=lambda s: setattr(self, "_stats", s),
        )

        def run_async() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self.engine.run(
                        run_targets,
                        outreach_list,
                        extra_context,
                        enable_dialog=enable_dialog,
                        resume_existing=resume_existing,
                    )
                )
            finally:
                loop.close()
                with self._lock:
                    self._running = False
                    self._outreach_account_ids = set()
                self.log("■ Завершено")

        self.worker_thread = threading.Thread(target=run_async, daemon=True)
        self.worker_thread.start()
        self.log("↻ Продолжаем диалоги..." if resume_only else "▶ Запуск...")
        return True, "OK"

    def stop_engine(self) -> None:
        if self.engine:
            self.engine.stop()
            self.log("■ Останавливаем...")

    def get_group_chat_settings(self) -> dict[str, Any]:
        return GroupChatSettings.load(self.group_chat_settings_path).to_dict()

    def save_group_chat_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        settings = GroupChatSettings.from_dict(data)
        settings.save(self.group_chat_settings_path)
        return settings.to_dict()

    @staticmethod
    def _normalize_group_account_schedules(
        account_ids: list[str],
        account_schedules: dict[str, list[dict[str, Any]]] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        normalized: dict[str, list[dict[str, Any]]] = {}
        for account_id in account_ids:
            windows: list[dict[str, Any]] = []
            for item in (account_schedules or {}).get(account_id) or []:
                if not isinstance(item, dict):
                    continue
                start = str(item.get("start") or "").strip()
                end = str(item.get("end") or "").strip()
                if not start or not end:
                    continue
                days_raw = item.get("days")
                days: list[int] = []
                if isinstance(days_raw, list):
                    for day in days_raw:
                        text = str(day or "").strip()
                        if text.isdigit():
                            value = int(text)
                            if 0 <= value <= 6:
                                days.append(value)
                windows.append({"days": days, "start": start, "end": end})
            normalized[account_id] = windows
        return normalized

    @staticmethod
    def _normalize_group_friendships(
        account_ids: list[str],
        friendships: dict[str, list[str]] | None,
    ) -> dict[str, list[str]]:
        allowed = set(account_ids)
        normalized: dict[str, set[str]] = {account_id: set() for account_id in account_ids}
        for account_id in account_ids:
            for friend_id in (friendships or {}).get(account_id) or []:
                friend = str(friend_id or "").strip()
                if not friend or friend == account_id or friend not in allowed:
                    continue
                normalized[account_id].add(friend)
                normalized[friend].add(account_id)
        return {account_id: sorted(friends) for account_id, friends in normalized.items()}

    def discover_group_chats(self, account_ids: list[str]) -> list[dict]:
        if len(account_ids) < 2:
            raise ValueError("Выберите минимум 2 аккаунта")
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                discover_common_chats(self.config, self.base_dir, account_ids, log=self.log)
            )
        finally:
            loop.close()

    def join_group_chat_by_link(self, account_ids: list[str], link: str) -> dict[str, Any]:
        link = (link or "").strip()
        if not link:
            raise ValueError("Укажите ссылку на чат")
        ordered_ids = list(dict.fromkeys(account_ids or []))
        if not ordered_ids:
            raise ValueError("Выберите минимум 1 аккаунт")
        if not self.config.telegram_api_id or not self.config.telegram_api_hash:
            raise ValueError("Укажите Telegram API ID и Hash")

        sessions = {s.account_id: s for s in discover_sessions(self.base_dir / self.config.sessions_dir)}
        proxies = load_proxies(self.proxies_path)
        global_2fa = self.config.telegram_2fa_password

        async def run_all() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            results: list[dict[str, Any]] = []
            joined_chat: dict[str, Any] | None = None
            for account_id in ordered_ids:
                session = sessions.get(account_id)
                if not session:
                    results.append(
                        {
                            "account_id": account_id,
                            "success": False,
                            "message": "Сессия не найдена в папке sessions",
                        }
                    )
                    continue

                proxy = self._proxy_for_account(account_id, proxies)
                pwd = read_twofa_password(session, global_2fa)
                client = TelegramAccountClient(
                    session,
                    self.config.telegram_api_id,
                    self.config.telegram_api_hash,
                    proxy,
                    pwd,
                )
                try:
                    await client.connect()
                    chat = await client.join_chat_by_link(link)
                    joined_chat = joined_chat or chat
                    results.append(
                        {
                            "account_id": account_id,
                            "success": True,
                            "message": f"Вступил: {chat['title']}",
                            "chat": chat,
                        }
                    )
                    self.log(f"✓ {account_id}: вступил в чат {chat['title']}")
                except Exception as exc:
                    err = format_telegram_error(exc)
                    results.append({"account_id": account_id, "success": False, "message": err})
                    self.log(f"✗ {account_id}: не вступил в чат — {err}")
                finally:
                    await client.disconnect()
            return results, joined_chat

        loop = asyncio.new_event_loop()
        try:
            results, joined_chat = loop.run_until_complete(run_all())
        finally:
            loop.close()

        success_count = sum(1 for item in results if item["success"])
        failed_count = len(results) - success_count
        return {
            "ok": success_count > 0,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
            "chat": joined_chat,
            "message": f"Вступление завершено: {success_count} успешно, {failed_count} ошибок",
        }

    def get_group_chat_status(self) -> dict[str, Any]:
        s = self._group_chat_stats
        self.state_store.load()
        session = self.state_store.group_session

        account_ids = list(s.account_ids)
        if not account_ids and session:
            account_ids = list(session.account_ids)

        session_counts = dict(s.session_counts)
        if session and not session_counts:
            session_counts = dict(session.session_counts)

        day_counts = dict(s.day_counts)
        if session and not day_counts:
            day_counts = dict(session.day_counts)

        recent_messages = list(s.recent_messages)
        if session and not recent_messages:
            recent_messages = list(session.messages[-12:])

        running_accounts = sorted(self._group_chat_account_ids)
        participants: list[dict[str, Any]] = []
        role_names = session.role_names if session else {}
        role_prompts = session.role_prompts if session else {}
        weights = session.activity_weights if session else {}
        schedules = session.account_schedules if session else {}
        friendships = session.friendships if session else {}
        online_accounts = (
            self.group_chat_engine.online_accounts()
            if self.group_chat_engine and self._group_chat_running
            else {}
        )
        for account_id in account_ids:
            participants.append(
                {
                    "account_id": account_id,
                    "role_name": role_names.get(account_id, ""),
                    "role_prompt": role_prompts.get(account_id, ""),
                    "weight": weights.get(account_id, 1),
                    "schedule": schedules.get(account_id, []),
                    "friends": friendships.get(account_id, []),
                    "session_count": session_counts.get(account_id, 0),
                    "day_count": day_counts.get(account_id, 0),
                    "running": account_id in self._group_chat_account_ids,
                    "online": online_accounts.get(account_id, account_id in self._group_chat_account_ids),
                }
            )

        return {
            "running": self._group_chat_running,
            "paused_schedule": s.paused_schedule,
            "chat_id": s.chat_id or (session.chat_id if session else 0),
            "chat_title": s.chat_title or (session.chat_title if session else ""),
            "topic": s.topic or (session.topic if session else ""),
            "account_ids": account_ids,
            "messages_sent": s.messages_sent,
            "last_speaker": s.last_speaker,
            "last_message": s.last_message,
            "status_text": s.status_text,
            "session_counts": session_counts,
            "day_counts": day_counts,
            "group_day_count": s.group_day_count or (session.group_day_count if session else 0),
            "recent_messages": recent_messages,
            "pending_external_replies": s.pending_external_replies,
            "last_external_trigger": s.last_external_trigger,
            "running_accounts": running_accounts,
            "online_accounts": online_accounts,
            "participants": participants,
            "extra_context": session.extra_context if session else "",
            "account_schedules": schedules,
            "friendships": friendships,
            "reset_context_on_apply": session.reset_context_on_apply if session else False,
            "debug_fast_mode": session.debug_fast_mode if session else False,
            "scene_revision": session.scene_revision if session else 0,
            "created_at": session.created_at if session else "",
            "last_activity": session.last_activity if session else "",
            "stored_status": session.status if session else ("running" if self._group_chat_running else "idle"),
            "message_count": len(session.messages) if session else len(recent_messages),
        }

    def start_group_chat(
        self,
        account_ids: list[str],
        chat_id: int,
        topic: str,
        role_overrides: dict[str, dict] | None = None,
        activity_weights: dict[str, float] | None = None,
        account_schedules: dict[str, list[dict[str, Any]]] | None = None,
        friendships: dict[str, list[str]] | None = None,
        extra_context: str = "",
        reset_context_on_apply: bool = False,
        debug_fast_mode: bool = False,
        chat_title: str = "",
    ) -> tuple[bool, str]:
        with self._lock:
            if self._group_chat_running:
                return False, "Групповой чат уже запущен"
            if len(account_ids) < 2:
                return False, "Выберите минимум 2 аккаунта"
            if not chat_id:
                return False, "Выберите общий чат"
            if not self.config.telegram_api_id or not self.config.telegram_api_hash:
                return False, "Укажите Telegram API ID и Hash"
            if not self.config.llm_configured():
                info = provider_info(self.config.llm_provider)
                return False, f"Укажите API-ключ для {info.name}"

            sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
            session_ids = {s.account_id for s in sessions}
            missing = [a for a in account_ids if a not in session_ids]
            if missing:
                return False, f"Аккаунты не найдены: {', '.join(missing[:3])}"

            ids = set(account_ids)
            if self._running:
                overlap = ids & self._get_outreach_account_ids()
                if overlap:
                    return False, f"Аккаунты заняты рассылкой: {', '.join(sorted(overlap))}"
            if self._agent_running:
                overlap = ids & self._running_agent_ids
                if overlap:
                    return False, f"Аккаунты заняты секретарём: {', '.join(sorted(overlap))}"

            normalized_schedules = self._normalize_group_account_schedules(
                account_ids,
                account_schedules,
            )
            normalized_friendships = self._normalize_group_friendships(
                account_ids,
                friendships,
            )
            self._group_chat_running = True
            self._group_chat_account_ids = set(account_ids)
            self._group_chat_stats = GroupChatStats(
                running=True,
                chat_id=int(chat_id),
                chat_title=chat_title,
                topic=topic,
                account_ids=list(account_ids),
            )

        self.group_chat_engine = GroupChatEngine(
            self.config,
            self.base_dir,
            log=self.log,
            on_stats=lambda st: setattr(self, "_group_chat_stats", st),
        )

        def run_async() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self.group_chat_engine.run(
                        account_ids=list(account_ids),
                        chat_id=int(chat_id),
                        topic=topic,
                        role_overrides=role_overrides or {},
                        activity_weights=activity_weights or {},
                        account_schedules=normalized_schedules,
                        friendships=normalized_friendships,
                        extra_context=extra_context,
                        reset_context_on_apply=bool(reset_context_on_apply),
                        debug_fast_mode=bool(debug_fast_mode),
                        chat_title=chat_title,
                    )
                )
            finally:
                loop.close()
                with self._lock:
                    self._group_chat_running = False
                    self._group_chat_account_ids = set()
                self.log("■ Групповой чат завершён")

        self.group_chat_thread = threading.Thread(target=run_async, daemon=True)
        self.group_chat_thread.start()
        self.log(f"▶ Групповой чат: {', '.join(account_ids)} → {chat_title or chat_id}")
        return True, "OK"

    def apply_group_chat_scene(
        self,
        account_ids: list[str],
        chat_id: int,
        topic: str,
        role_overrides: dict[str, dict] | None = None,
        activity_weights: dict[str, float] | None = None,
        account_schedules: dict[str, list[dict[str, Any]]] | None = None,
        friendships: dict[str, list[str]] | None = None,
        extra_context: str = "",
        reset_context_on_apply: bool = False,
        debug_fast_mode: bool = False,
        chat_title: str = "",
    ) -> tuple[bool, str]:
        with self._lock:
            if not self._group_chat_running:
                return False, "Групповой чат не запущен"
            if len(account_ids) < 2:
                return False, "Выберите минимум 2 аккаунта"
            if not chat_id:
                return False, "Выберите общий чат"

            sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
            session_ids = {s.account_id for s in sessions}
            missing = [a for a in account_ids if a not in session_ids]
            if missing:
                return False, f"Аккаунты не найдены: {', '.join(missing[:3])}"

            requested_ids = set(account_ids)
            running_ids = set(self._group_chat_account_ids)
            missing_running = [aid for aid in account_ids if aid not in running_ids]
            if missing_running:
                return False, (
                    "Нельзя добавить новые аккаунты в уже запущенную сцену: "
                    f"{', '.join(missing_running[:3])}. Остановите сцену и запустите заново."
                )

            roles = RolesConfig.load(self.base_dir / self.config.roles_file)
            overrides = role_overrides or {}
            weights_input = activity_weights or {}
            normalized_schedules = self._normalize_group_account_schedules(
                account_ids,
                account_schedules,
            )
            normalized_friendships = self._normalize_group_friendships(
                account_ids,
                friendships,
            )
            role_prompts: dict[str, str] = {}
            role_names: dict[str, str] = {}
            weights: dict[str, float] = {}

            for aid in account_ids:
                override = overrides.get(aid) or {}
                prompt = str(override.get("role_prompt") or "").strip() or roles.prompt_for_account(aid)
                name = (
                    str(override.get("role_name") or "").strip()
                    or roles.role_name_for_account(aid)
                    or "участник"
                )
                role_prompts[aid] = prompt
                role_names[aid] = name
                weights[aid] = float(weights_input.get(aid, 1.0) or 1.0)

            current = self.state_store.group_session
            should_reset_context = bool(reset_context_on_apply)
            next_scene_revision = (current.scene_revision if current else 0) + 1
            session = GroupSessionRecord(
                chat_id=int(chat_id),
                topic=topic.strip(),
                chat_title=chat_title.strip(),
                account_ids=list(account_ids),
                role_prompts=role_prompts,
                role_names=role_names,
                activity_weights=weights,
                account_schedules=normalized_schedules,
                friendships=normalized_friendships,
                extra_context=extra_context.strip(),
                status="active",
                created_at=current.created_at if current else "",
                last_activity="" if should_reset_context else (current.last_activity if current else ""),
                messages=[] if should_reset_context else (list(current.messages) if current else []),
                session_counts={
                    aid: (current.session_counts.get(aid, 0) if current else 0)
                    for aid in account_ids
                },
                day_counts={
                    aid: (current.day_counts.get(aid, 0) if current else 0)
                    for aid in account_ids
                },
                day_key=current.day_key if current else "",
                group_day_count=current.group_day_count if current else 0,
                reset_context_on_apply=should_reset_context,
                debug_fast_mode=bool(debug_fast_mode),
                scene_revision=next_scene_revision,
            )
            self.state_store.upsert_group_session(session)
            self._group_chat_account_ids = requested_ids
            self._group_chat_stats.chat_id = session.chat_id
            self._group_chat_stats.chat_title = session.chat_title
            self._group_chat_stats.topic = session.topic
            self._group_chat_stats.account_ids = list(account_ids)
            self._group_chat_stats.session_counts = dict(session.session_counts)
            self._group_chat_stats.day_counts = dict(session.day_counts)
            self._group_chat_stats.group_day_count = session.group_day_count
            self._group_chat_stats.recent_messages = [
                message.to_dict() for message in session.messages[-12:]
            ]
            self._group_chat_stats.status_text = "сцена обновлена"

        self.log(
            f"↻ Групповой чат обновлён: {', '.join(account_ids)} → "
            f"{chat_title.strip() or chat_id} / {topic.strip() or '—'}"
        )
        return True, "Сцена обновлена"

    def stop_group_chat(self) -> None:
        if self.group_chat_engine:
            self.group_chat_engine.stop()
            self.log("■ Останавливаем групповой чат...")
