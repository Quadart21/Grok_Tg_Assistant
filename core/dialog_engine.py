from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from telethon.errors import FloodWaitError

from core.agent_config import AgentsConfig
from core.config import AppConfig, ProxyConfig, RolesConfig
from core.dialog_settings import DialogSettings
from core.llm_client import LLMClient, create_llm_client
from core.proxy_manager import load_proxies
from core.session_manager import SessionInfo, discover_sessions, read_twofa_password
from core.state_store import DialogRecord, StateStore
from core.telegram_client import TELEGRAM_ERRORS, TelegramAccountClient


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class OutreachTask:
    account_id: str
    target_username: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = ""
    error: str = ""


@dataclass
class EngineStats:
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    replies_sent: int = 0
    active_dialogs: int = 0


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[OutreachTask], None]
StatsCallback = Callable[[EngineStats], None]


class DialogEngine:
    """Рассылка первых сообщений + онлайн-диалоги с памятью между запусками."""

    def __init__(
        self,
        config: AppConfig,
        roles: RolesConfig,
        base_dir: Path,
        log: LogCallback | None = None,
        on_task: ProgressCallback | None = None,
        on_stats: StatsCallback | None = None,
    ) -> None:
        self.config = config
        self.roles = roles
        self.base_dir = base_dir
        self.log = log or (lambda _msg: None)
        self.on_task = on_task or (lambda _task: None)
        self.on_stats = on_stats or (lambda _stats: None)
        self._stop = asyncio.Event()
        self.stats = EngineStats()
        self.state = StateStore(base_dir / config.state_file)
        self._clients: dict[str, TelegramAccountClient] = {}
        self._reply_locks: dict[str, asyncio.Lock] = {}
        self._pending_replies: dict[str, asyncio.Task] = {}
        self._hourly_replies: list[float] = []
        self.dialog_settings = DialogSettings.load(base_dir / "config" / "dialog_settings.json")

    def stop(self) -> None:
        self._stop.set()

    def reset_stop(self) -> None:
        self._stop.clear()

    def _resolve_proxy(self, account_id: str, proxies: dict[str, ProxyConfig]) -> ProxyConfig | None:
        binding = self.state.get_account_binding(account_id)
        if binding:
            saved = binding.to_proxy()
            if saved:
                return saved
        return proxies.get(account_id)

    def _resolve_role(self, account_id: str) -> tuple[str, str]:
        self.roles = RolesConfig.load(self.base_dir / self.config.roles_file)
        prompt = self.roles.prompt_for_account(account_id)
        group_name = self.roles.role_name_for_account(account_id)
        return prompt, group_name

    def _save_account_memory(self, account_id: str, role_prompt: str, proxy: ProxyConfig | None, group_name: str) -> None:
        self.state.save_account_binding(account_id, role_prompt, proxy, group_name)
        if proxy and proxy.host:
            from core.proxy_manager import save_proxies

            proxies = load_proxies(self.base_dir / self.config.proxies_file)
            proxies[account_id] = proxy
            save_proxies(self.base_dir / self.config.proxies_file, proxies)

    async def run(
        self,
        target_usernames: list[str] | None = None,
        account_ids: list[str] | None = None,
        extra_context: str = "",
        enable_dialog: bool = True,
        resume_existing: bool = True,
    ) -> list[OutreachTask]:
        self.reset_stop()
        self.stats = EngineStats()
        self.dialog_settings = DialogSettings.load(self.base_dir / "config" / "dialog_settings.json")
        self.roles = RolesConfig.load(self.base_dir / self.config.roles_file)

        sessions_dir = self.base_dir / self.config.sessions_dir
        proxies_file = self.base_dir / self.config.proxies_file
        sessions = discover_sessions(sessions_dir)
        proxies = load_proxies(proxies_file)

        agent_ids = {
            a.account_id
            for a in AgentsConfig.load(self.base_dir / "config" / "agents.json").agents
            if a.enabled
        }
        if agent_ids:
            sessions = [s for s in sessions if s.account_id not in agent_ids]

        if account_ids:
            allowed = set(account_ids)
            sessions = [s for s in sessions if s.account_id in allowed]

        if not sessions:
            self.log("❌ Аккаунты не найдены в папке sessions/")
            return []

        new_targets = [u.strip().lstrip("@") for u in (target_usernames or []) if u.strip()]
        paused_dialogs = self.state.list_all_dialogs({"paused", "active"}) if resume_existing else []

        accounts_with_dialogs = {d.account_id for d in paused_dialogs}
        if not new_targets and not accounts_with_dialogs:
            self.log("❌ Нет новых username и нет сохранённых диалогов для продолжения")
            return []

        outreach_tasks: list[OutreachTask] = []
        if new_targets:
            for session in sessions:
                for target in new_targets:
                    existing = self.state.get_dialog(session.account_id, target)
                    if existing and existing.status in {"active", "paused"}:
                        continue
                    outreach_tasks.append(
                        OutreachTask(account_id=session.account_id, target_username=target)
                    )

        self.stats.total = len(outreach_tasks)
        self._emit_stats()

        llm = create_llm_client(self.config, self.dialog_settings, self.roles.master_prompt)
        session_map = {s.account_id: s for s in sessions}
        accounts_to_run = set(session_map.keys())
        if resume_existing:
            accounts_to_run |= accounts_with_dialogs
        accounts_to_run &= set(session_map.keys())

        for account_id in accounts_to_run:
            if self._stop.is_set():
                break
            session = session_map[account_id]
            role_prompt, group_name = self._resolve_role(account_id)
            proxy = self._resolve_proxy(account_id, proxies)

            client = TelegramAccountClient(
                session,
                self.config.telegram_api_id,
                self.config.telegram_api_hash,
                proxy,
                two_fa_password=read_twofa_password(session, self.config.telegram_2fa_password),
            )
            try:
                tg_name = await client.connect()
                self._clients[account_id] = client
                self._save_account_memory(account_id, role_prompt, proxy, group_name)
                self.log(f"✓ Онлайн: {account_id} ({tg_name}) — стиль: {group_name}")

                account_dialogs = self.state.list_dialogs_for_account(
                    account_id, {"active", "paused"} if resume_existing else {"active"}
                )
                for dialog in account_dialogs:
                    if resume_existing:
                        self.state.set_dialog_status(dialog, "active")
                    if self.dialog_settings.sync_history_on_resume:
                        await self._sync_missed_messages(client, dialog)

                if enable_dialog:
                    user_ids = set()
                    for dialog in self.state.list_dialogs_for_account(account_id, {"active"}):
                        if dialog.target_user_id:
                            user_ids.add(dialog.target_user_id)
                        else:
                            try:
                                dialog.target_user_id = await client.resolve_user_id(dialog.target_username)
                                user_ids.add(dialog.target_user_id)
                                self.state.upsert_dialog(dialog)
                            except Exception as exc:
                                self.log(f"⚠ {account_id}: не найден @{dialog.target_username} — {exc}")

                    client.set_incoming_handler(self._make_incoming_handler(account_id, llm))
                    client.track_users(user_ids)

            except Exception as exc:
                self.log(f"✗ Не удалось подключить {account_id}: {self._format_error(exc)}")
                await client.disconnect()

        for task in outreach_tasks:
            if self._stop.is_set():
                task.status = TaskStatus.SKIPPED
                task.error = "Остановлено"
                self.stats.skipped += 1
                self._emit_task(task)
                continue

            client = self._clients.get(task.account_id)
            if not client:
                task.status = TaskStatus.FAILED
                task.error = "Аккаунт не подключён"
                self.stats.failed += 1
                self._emit_task(task)
                continue

            task.status = TaskStatus.RUNNING
            self._emit_task(task)
            role_prompt, _ = self._resolve_role(task.account_id)

            try:
                text = await llm.generate_first_message(
                    role_prompt,
                    task.target_username,
                    self.config.message_language,
                    extra_context,
                )
                if self.dialog_settings.first_message_max_chars:
                    text = text[: self.dialog_settings.first_message_max_chars]
                task.message = text
                msg_id = await client.send_first_message(task.target_username, text)
                user_id = await client.resolve_user_id(task.target_username)

                dialog = DialogRecord(
                    account_id=task.account_id,
                    target_username=task.target_username,
                    role_prompt=role_prompt,
                    extra_context=extra_context,
                    language=self.config.message_language,
                    target_user_id=user_id,
                    status="active" if enable_dialog else "paused",
                    auto_reply=enable_dialog,
                )
                self.state.upsert_dialog(dialog)
                self.state.add_message(
                    dialog, "assistant", text, msg_id, self.dialog_settings.max_stored_messages
                )

                if enable_dialog and client:
                    tracked = set()
                    for d in self.state.list_dialogs_for_account(task.account_id, {"active"}):
                        if d.target_user_id:
                            tracked.add(d.target_user_id)
                    client.track_users(tracked)

                task.status = TaskStatus.SUCCESS
                self.stats.success += 1
                self.log(f"✓ Первое сообщение: {task.account_id} → @{task.target_username}")

            except FloodWaitError as exc:
                task.status = TaskStatus.FAILED
                task.error = f"Flood wait {exc.seconds} сек"
                self.stats.failed += 1
                self.log(f"⏳ {task.account_id}: пауза {exc.seconds} сек")
                await asyncio.sleep(min(exc.seconds, 300))
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = self._format_error(exc)
                self.stats.failed += 1
                self.log(f"✗ {task.account_id} → @{task.target_username}: {task.error}")

            self._emit_task(task)
            self._emit_stats()

            delay = self.config.delay_between_messages_sec
            if delay > 0:
                await asyncio.sleep(delay + random.uniform(0, delay * 0.3))

        self.stats.active_dialogs = len(self.state.list_all_dialogs({"active"}))
        self._emit_stats()

        if enable_dialog and self._clients:
            self.log("💬 Диалоги активны — жду сообщения (можно остановить и продолжить позже)")
            while not self._stop.is_set():
                self.stats.active_dialogs = len(self.state.list_all_dialogs({"active"}))
                self._emit_stats()
                await asyncio.sleep(1)
            await self._shutdown_clients(pause_dialogs=True)
            self.log(
                f"■ Остановлено. Отправлено: {self.stats.success}, ответов: {self.stats.replies_sent}. "
                "Диалоги сохранены — нажмите «Продолжить» для возобновления."
            )
        else:
            await self._shutdown_clients(pause_dialogs=False)
            self.log(
                f"Готово: отправлено {self.stats.success}, ошибок {self.stats.failed}, "
                f"пропущено {self.stats.skipped}"
            )

        return outreach_tasks

    def _make_incoming_handler(self, account_id: str, llm: LLMClient):
        async def handler(user_id: int, text: str, msg_id: int, username: str = "") -> None:
            if self._stop.is_set():
                return
            dialog = self._find_dialog(account_id, user_id)
            if not dialog or dialog.status != "active":
                return
            if not dialog.auto_reply:
                self.state.add_message(
                    dialog, "user", text, msg_id, self.dialog_settings.max_stored_messages
                )
                self.log(f"📩 @{dialog.target_username} (авто-ответ выкл): {text[:60]}")
                return

            if self.dialog_settings.should_ignore_message(text):
                self.state.add_message(
                    dialog, "user", text, msg_id, self.dialog_settings.max_stored_messages
                )
                self.log(f"⏸ @{dialog.target_username}: стоп-слово, авто-ответ пропущен")
                return

            self.state.add_message(
                dialog, "user", text, msg_id, self.dialog_settings.max_stored_messages
            )
            self.log(f"📩 @{dialog.target_username} → {account_id}: {text[:80]}")

            pending_key = f"{account_id}:{user_id}"
            old = self._pending_replies.pop(pending_key, None)
            if old and not old.done():
                old.cancel()

            async def delayed_reply() -> None:
                try:
                    await asyncio.sleep(self.dialog_settings.batch_messages_sec)
                    await self._send_auto_reply(account_id, user_id, llm)
                except asyncio.CancelledError:
                    pass

            self._pending_replies[pending_key] = asyncio.create_task(delayed_reply())

        return handler

    async def _send_auto_reply(self, account_id: str, user_id: int, llm: LLMClient) -> None:
        lock = self._reply_locks.setdefault(f"{account_id}:{user_id}", asyncio.Lock())
        async with lock:
            if self._stop.is_set():
                return
            dialog = self._find_dialog(account_id, user_id)
            if not dialog or dialog.status != "active" or not dialog.auto_reply:
                return

            max_dialog = dialog.max_replies or self.dialog_settings.max_replies_per_dialog
            if max_dialog > 0 and dialog.replies_count >= max_dialog:
                self.log(f"⏸ @{dialog.target_username}: лимит ответов ({max_dialog})")
                return

            if not self._check_hourly_limit():
                self.log(f"⏸ {account_id}: лимит ответов в час")
                return

            try:
                delay = random.uniform(
                    self.dialog_settings.reply_delay_min_sec,
                    self.dialog_settings.reply_delay_max_sec,
                )
                await asyncio.sleep(delay)
                if self.dialog_settings.typing_delay_sec > 0:
                    await asyncio.sleep(self.dialog_settings.typing_delay_sec)
                if self._stop.is_set():
                    return

                fresh = self.state.get_dialog(account_id, dialog.target_username)
                if not fresh:
                    return

                combined_context = fresh.extra_context
                if fresh.dialog_extra_context:
                    combined_context = f"{combined_context}\n{fresh.dialog_extra_context}".strip()

                if fresh.dialog_mode == "agent":
                    role_prompt = fresh.role_prompt
                else:
                    role_prompt, _ = self._resolve_role(account_id)

                reply = await llm.generate_reply(
                    role_prompt,
                    fresh.target_username,
                    fresh.messages,
                    fresh.language,
                    combined_context,
                    fresh.goal,
                )

                client = self._clients.get(account_id)
                if not client:
                    return

                parts = self._split_reply(reply)
                for part in parts:
                    reply_id = await client.send_message(fresh.target_username, part)
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
                self.log(f"📤 {account_id} → @{fresh.target_username}: {reply[:80]}")
            except FloodWaitError as exc:
                self.log(f"⏳ {account_id}: flood wait {exc.seconds} сек")
                await asyncio.sleep(min(exc.seconds, 300))
            except Exception as exc:
                self.log(f"✗ Ошибка ответа {account_id}: {self._format_error(exc)}")

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
        return None

    async def _sync_missed_messages(self, client: TelegramAccountClient, dialog: DialogRecord) -> None:
        known_ids = {m.msg_id for m in dialog.messages if m.msg_id is not None}
        try:
            missed = await client.sync_recent_messages(
                dialog.target_username, known_ids, self.dialog_settings.sync_history_limit
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

        if missed:
            self.log(f"↻ Подтянуто {len(missed)} сообщ. для @{dialog.target_username}")
            incoming_ids = [msg_id for msg_id, is_out, _ in missed if not is_out]
            if incoming_ids:
                user_id = dialog.target_user_id
                if user_id is None:
                    try:
                        user_id = await client.resolve_user_id(dialog.target_username)
                        dialog.target_user_id = user_id
                        self.state.upsert_dialog(dialog)
                    except Exception:
                        user_id = None
                if user_id:
                    await client.mark_read(user_id, max(incoming_ids))

        if dialog.target_user_id is None and missed:
            try:
                dialog.target_user_id = await client.resolve_user_id(dialog.target_username)
                self.state.upsert_dialog(dialog)
            except Exception:
                pass

    async def _shutdown_clients(self, pause_dialogs: bool) -> None:
        if pause_dialogs:
            self.state.pause_all_active()
        for account_id, client in list(self._clients.items()):
            try:
                await client.disconnect()
            except Exception:
                pass
            self._clients.pop(account_id, None)

    def _format_error(self, exc: Exception) -> str:
        for err_type, msg in TELEGRAM_ERRORS.items():
            if isinstance(exc, err_type):
                if isinstance(exc, FloodWaitError):
                    return f"{msg}: {exc.seconds} сек"
                return msg
        return str(exc)[:200]

    def _emit_task(self, task: OutreachTask) -> None:
        self.on_task(task)

    def _emit_stats(self) -> None:
        self.on_stats(self.stats)


OutreachEngine = DialogEngine
OutreachStats = EngineStats
