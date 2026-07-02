from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from telethon.errors import FloodWaitError

from core.agent_config import AgentsConfig, SecretaryAgent
from core.config import AppConfig, ProxyConfig, RolesConfig
from core.dialog_settings import DialogSettings
from core.llm_client import LLMClient, create_llm_client
from core.proxy_manager import load_proxies
from core.session_manager import discover_sessions, read_twofa_password
from core.state_store import DialogRecord, StateStore
from core.telegram_client import TELEGRAM_ERRORS, TelegramAccountClient


@dataclass
class AgentStats:
    running: bool = False
    active_accounts: int = 0
    replies_sent: int = 0
    messages_received: int = 0
    active_dialogs: int = 0


LogCallback = Callable[[str], None]
StatsCallback = Callable[[AgentStats], None]


class AgentEngine:
    """AI-агент ведёт живые диалоги в личке по промпту, с памятью переписки."""

    def __init__(
        self,
        config: AppConfig,
        base_dir: Path,
        log: LogCallback | None = None,
        on_stats: StatsCallback | None = None,
    ) -> None:
        self.config = config
        self.base_dir = base_dir
        self.log = log or (lambda _msg: None)
        self.on_stats = on_stats or (lambda _stats: None)
        self._stop = asyncio.Event()
        self.stats = AgentStats()
        self.state = StateStore(base_dir / config.state_file)
        self.dialog_settings = DialogSettings.load(base_dir / "config" / "dialog_settings.json")
        self.agents_path = base_dir / "config" / "agents.json"
        self._clients: dict[str, TelegramAccountClient] = {}
        self._reply_locks: dict[str, asyncio.Lock] = {}
        self._pending_replies: dict[str, asyncio.Task] = {}
        self._hourly_replies: list[float] = []
        self._user_labels: dict[str, dict[int, str]] = {}
        self._pending_send_ids: set[str] = set()

    def stop(self) -> None:
        self._stop.set()

    def reset_stop(self) -> None:
        self._stop.clear()

    def _load_agent(self, account_id: str) -> SecretaryAgent | None:
        return AgentsConfig.load(self.agents_path).get(account_id)

    def _resolve_proxy(self, account_id: str, proxies: dict[str, ProxyConfig]) -> ProxyConfig | None:
        binding = self.state.get_account_binding(account_id)
        if binding:
            saved = binding.to_proxy()
            if saved:
                return saved
        return proxies.get(account_id)

    async def run(self, account_ids: list[str]) -> None:
        self.reset_stop()
        self.stats = AgentStats(running=True)
        self.dialog_settings = DialogSettings.load(self.base_dir / "config" / "dialog_settings.json")
        self.state.load()
        self._emit_stats()

        agents_cfg = AgentsConfig.load(self.agents_path)
        roles = RolesConfig.load(self.base_dir / self.config.roles_file)
        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        proxies = load_proxies(self.base_dir / self.config.proxies_file)
        allowed = set(account_ids)
        sessions = [s for s in sessions if s.account_id in allowed]

        if not sessions:
            self.log("❌ Секретарь: аккаунты не найдены")
            self.stats.running = False
            self._emit_stats()
            return

        if not self.config.llm_configured():
            from core.llm_providers import provider_info

            info = provider_info(self.config.llm_provider)
            self.log(f"❌ Секретарь: укажите API-ключ для {info.name}")
            self.stats.running = False
            self._emit_stats()
            return

        llm = create_llm_client(self.config, self.dialog_settings, roles.master_prompt)

        for session in sessions:
            if self._stop.is_set():
                break
            agent = agents_cfg.get(session.account_id)
            if not agent or not agent.enabled:
                self.log(f"⚠ {session.account_id}: агент не настроен или выключен")
                continue

            proxy = self._resolve_proxy(session.account_id, proxies)
            client = TelegramAccountClient(
                session,
                self.config.telegram_api_id,
                self.config.telegram_api_hash,
                proxy,
                two_fa_password=read_twofa_password(session, self.config.telegram_2fa_password),
            )
            try:
                tg_name = await client.connect()
                self._clients[session.account_id] = client
                self._user_labels[session.account_id] = {}
                client.set_incoming_handler(
                    self._make_incoming_handler(session.account_id, llm),
                    listen_all_private=True,
                    outgoing_handler=self._make_outgoing_handler(session.account_id),
                )

                resumed = 0
                for dialog in self.state.list_dialogs_for_account(session.account_id, {"active", "paused"}):
                    if dialog.dialog_mode != "agent":
                        continue
                    if dialog.status == "paused":
                        self.state.set_dialog_status(dialog, "active")
                    if self.dialog_settings.sync_history_on_resume and dialog.target_user_id:
                        await self._sync_dialog_history(client, dialog)
                    resumed += 1

                self.log(
                    f"🤖 Диалог-агент онлайн: {session.account_id} ({tg_name}) — {agent.name}"
                    + (f", возобновлено {resumed} переписок" if resumed else "")
                )
            except Exception as exc:
                self.log(f"✗ Агент {session.account_id}: {self._format_error(exc)}")
                await client.disconnect()

        self.stats.active_accounts = len(self._clients)
        self.stats.active_dialogs = len(
            [d for d in self.state.list_all_dialogs({"active"}) if d.dialog_mode == "agent"]
        )
        self._emit_stats()

        if not self._clients:
            self.log("❌ Ни один агент не подключился")
            self.stats.running = False
            self._emit_stats()
            return

        self.log("💬 Агент ведёт диалоги — отвечает по контексту переписки и промпту")
        while not self._stop.is_set():
            self.stats.active_dialogs = len(
                [d for d in self.state.list_all_dialogs({"active"}) if d.dialog_mode == "agent"]
            )
            self._emit_stats()
            await asyncio.sleep(1)

        await self._shutdown_clients()
        self.stats.running = False
        self.stats.active_accounts = 0
        self.stats.active_dialogs = 0
        self._emit_stats()
        self.log(f"■ Агент остановлен. Сообщений в диалогах: {self.stats.messages_received}, ответов: {self.stats.replies_sent}")

    def _make_incoming_handler(self, account_id: str, llm: LLMClient):
        async def handler(user_id: int, text: str, msg_id: int, username: str = "") -> None:
            if self._stop.is_set():
                return

            agent = self._load_agent(account_id)
            if not agent or not agent.enabled:
                return

            label = username or f"id_{user_id}"
            self._user_labels.setdefault(account_id, {})[user_id] = label

            if not agent.allows_user(label):
                return

            dialog = self._get_or_create_dialog(account_id, user_id, label, agent)
            client = self._clients.get(account_id)
            if client and self.dialog_settings.sync_history_on_resume:
                await self._sync_dialog_history(client, dialog)

            if self.dialog_settings.should_ignore_message(text):
                self.state.add_message(
                    dialog, "user", text, msg_id, self.dialog_settings.max_stored_messages
                )
                self.log(f"⏸ @{label}: стоп-слово, ответ пропущен")
                return

            self.state.add_message(
                dialog, "user", text, msg_id, self.dialog_settings.max_stored_messages
            )
            self.stats.messages_received += 1
            self._emit_stats()
            self.log(f"📩 @{label} → {account_id}: {text[:80]}")

            pending_key = f"{account_id}:{user_id}"
            old = self._pending_replies.pop(pending_key, None)
            if old and not old.done():
                old.cancel()

            async def delayed_reply() -> None:
                try:
                    await asyncio.sleep(self.dialog_settings.batch_messages_sec)
                    await self._send_dialog_reply(account_id, user_id, llm)
                except asyncio.CancelledError:
                    pass

            self._pending_replies[pending_key] = asyncio.create_task(delayed_reply())

        return handler

    def _make_outgoing_handler(self, account_id: str):
        async def handler(user_id: int, text: str, msg_id: int, username: str = "") -> None:
            pending_key = f"{account_id}:{msg_id}"
            if pending_key in self._pending_send_ids:
                self._pending_send_ids.discard(pending_key)
                return

            label = username or f"id_{user_id}"
            dialog = self._find_dialog(account_id, user_id)
            if not dialog or dialog.dialog_mode != "agent":
                return

            self.state.add_message(
                dialog, "assistant", text, msg_id, self.dialog_settings.max_stored_messages
            )
            self.log(f"✍️ {account_id} (вручную) → @{label}: {text[:60]}")

        return handler

    def _get_or_create_dialog(
        self,
        account_id: str,
        user_id: int,
        username: str,
        agent: SecretaryAgent,
    ) -> DialogRecord:
        dialog = self._find_dialog(account_id, user_id)
        if not dialog:
            dialog = self.state.get_dialog(account_id, username)

        if dialog:
            dialog.target_user_id = user_id
            dialog.target_username = username
            dialog.dialog_mode = "agent"
            dialog.status = "active"
            dialog.auto_reply = True
            self._apply_agent_settings(dialog, agent)
            self.state.upsert_dialog(dialog)
            return dialog

        dialog = DialogRecord(
            account_id=account_id,
            target_username=username,
            role_prompt=agent.prompt,
            extra_context=agent.extra_context,
            goal=agent.goal,
            language=agent.language,
            target_user_id=user_id,
            status="active",
            auto_reply=True,
            dialog_mode="agent",
            notes=f"AI-агент: {agent.name}",
        )
        self.state.upsert_dialog(dialog)
        return dialog

    def _apply_agent_settings(self, dialog: DialogRecord, agent: SecretaryAgent) -> None:
        dialog.role_prompt = agent.prompt
        dialog.extra_context = agent.extra_context
        dialog.goal = agent.goal
        dialog.language = agent.language
        if not dialog.notes.startswith("AI-агент:"):
            dialog.notes = f"AI-агент: {agent.name}"

    async def _send_dialog_reply(self, account_id: str, user_id: int, llm: LLMClient) -> None:
        lock = self._reply_locks.setdefault(f"{account_id}:{user_id}", asyncio.Lock())
        async with lock:
            if self._stop.is_set():
                return

            agent = self._load_agent(account_id)
            if not agent or not agent.enabled:
                return

            label = self._user_labels.get(account_id, {}).get(user_id, f"id_{user_id}")
            dialog = self._find_dialog(account_id, user_id)
            if not dialog or not dialog.auto_reply or dialog.status != "active":
                return

            max_dialog = dialog.max_replies or self.dialog_settings.max_replies_per_dialog
            if max_dialog > 0 and dialog.replies_count >= max_dialog:
                self.log(f"⏸ @{label}: лимит ответов ({max_dialog})")
                return

            if not self._check_hourly_limit():
                self.log(f"⏸ {account_id}: лимит ответов в час")
                return

            client = self._clients.get(account_id)
            if not client:
                return

            try:
                delay = random.uniform(
                    self.dialog_settings.reply_delay_min_sec,
                    self.dialog_settings.reply_delay_max_sec,
                )
                await asyncio.sleep(max(0.5, delay - self.dialog_settings.typing_delay_sec))
                if self._stop.is_set():
                    return

                typing_sec = float(self.dialog_settings.typing_delay_sec)
                if typing_sec > 0:
                    await client.show_typing(user_id, typing_sec)

                fresh = self.state.get_dialog(account_id, dialog.target_username)
                if not fresh:
                    return

                self._apply_agent_settings(fresh, agent)
                self.state.upsert_dialog(fresh)

                combined_context = fresh.extra_context
                if fresh.dialog_extra_context:
                    combined_context = f"{combined_context}\n{fresh.dialog_extra_context}".strip()

                reply = await llm.generate_agent_dialog_reply(
                    fresh.role_prompt,
                    fresh.target_username,
                    fresh.messages,
                    fresh.language,
                    combined_context,
                    fresh.goal,
                    agent.name,
                )

                parts = self._split_reply(reply)
                for part in parts:
                    reply_id = await client.send_message_to_user(user_id, part)
                    self._pending_send_ids.add(f"{account_id}:{reply_id}")
                    self.state.add_message(
                        fresh, "assistant", part, reply_id, self.dialog_settings.max_stored_messages
                    )
                    fresh.replies_count += 1
                    self.state.upsert_dialog(fresh)
                    if len(parts) > 1:
                        await asyncio.sleep(random.uniform(1, 3))

                self._hourly_replies.append(asyncio.get_event_loop().time())
                self.stats.replies_sent += 1
                self._emit_stats()
                self.log(f"💬 {account_id} → @{label}: {reply[:80]}")
            except FloodWaitError as exc:
                self.log(f"⏳ {account_id}: flood wait {exc.seconds} сек")
                await asyncio.sleep(min(exc.seconds, 300))
            except Exception as exc:
                self.log(f"✗ Диалог {account_id}: {self._format_error(exc)}")

    async def _sync_dialog_history(self, client: TelegramAccountClient, dialog: DialogRecord) -> None:
        if not dialog.target_user_id:
            return
        known_ids = {m.msg_id for m in dialog.messages if m.msg_id is not None}
        try:
            missed = await client.sync_recent_messages_for_user(
                dialog.target_user_id, known_ids, self.dialog_settings.sync_history_limit
            )
        except Exception as exc:
            self.log(f"⚠ Синхронизация @{dialog.target_username}: {exc}")
            return

        if not missed:
            return

        for msg_id, is_out, text in missed:
            role = "assistant" if is_out else "user"
            self.state.add_message(
                dialog, role, text, msg_id, self.dialog_settings.max_stored_messages
            )

        incoming_ids = [msg_id for msg_id, is_out, _ in missed if not is_out]
        if incoming_ids and dialog.target_user_id:
            await client.mark_read(dialog.target_user_id, max(incoming_ids))

        self.log(f"↻ Подтянуто {len(missed)} сообщ. диалога @{dialog.target_username}")

    def _split_reply(self, text: str) -> list[str]:
        if not self.dialog_settings.split_long_messages:
            return [text]
        limit = self.dialog_settings.split_at_chars
        if len(text) <= limit:
            return [text]
        parts: list[str] = []
        while text:
            if len(text) <= limit:
                parts.append(text)
                break
            cut = text.rfind(" ", 0, limit)
            if cut < limit // 2:
                cut = limit
            parts.append(text[:cut].strip())
            text = text[cut:].strip()
        return [p for p in parts if p]

    def _check_hourly_limit(self) -> bool:
        limit = self.dialog_settings.max_replies_per_hour
        if limit <= 0:
            return True
        now = asyncio.get_event_loop().time()
        self._hourly_replies = [t for t in self._hourly_replies if now - t < 3600]
        return len(self._hourly_replies) < limit

    def _find_dialog(self, account_id: str, user_id: int) -> DialogRecord | None:
        for dialog in self.state.list_dialogs_for_account(account_id):
            if dialog.target_user_id == user_id:
                return dialog
        label = self._user_labels.get(account_id, {}).get(user_id)
        if label:
            return self.state.get_dialog(account_id, label)
        return None

    async def _shutdown_clients(self) -> None:
        for account_id in list(self._clients.keys()):
            client = self._clients.pop(account_id, None)
            if not client:
                continue
            try:
                for dialog in self.state.list_dialogs_for_account(account_id, {"active"}):
                    if dialog.dialog_mode == "agent":
                        self.state.set_dialog_status(dialog, "paused")
                await client.disconnect()
            except Exception:
                pass

    def _format_error(self, exc: Exception) -> str:
        for err_type, msg in TELEGRAM_ERRORS.items():
            if isinstance(exc, err_type):
                if isinstance(exc, FloodWaitError):
                    return f"{msg}: {exc.seconds} сек"
                return msg
        return str(exc)[:200]

    def _emit_stats(self) -> None:
        self.on_stats(self.stats)
