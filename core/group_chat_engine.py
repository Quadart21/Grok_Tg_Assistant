from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from telethon.errors import FloodWaitError

from core.config import AppConfig, ProxyConfig, RolesConfig
from core.group_chat_settings import GroupChatSettings
from core.llm_client import create_llm_client
from core.proxy_manager import load_proxies
from core.proxy_pool import load_pool, pool_path, resolve_pool_proxy
from core.session_manager import discover_sessions, read_twofa_password
from core.state_store import GroupSessionRecord, StateStore
from core.telegram_client import TelegramAccountClient, format_telegram_error


@dataclass
class GroupChatStats:
    running: bool = False
    paused_schedule: bool = False
    chat_id: int = 0
    chat_title: str = ""
    topic: str = ""
    account_ids: list[str] = field(default_factory=list)
    messages_sent: int = 0
    last_speaker: str = ""
    last_message: str = ""
    status_text: str = ""
    session_counts: dict[str, int] = field(default_factory=dict)
    day_counts: dict[str, int] = field(default_factory=dict)
    group_day_count: int = 0
    recent_messages: list[dict] = field(default_factory=list)
    pending_external_replies: int = 0
    last_external_trigger: str = ""


LogCallback = Callable[[str], None]
StatsCallback = Callable[[GroupChatStats], None]


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = (value or "00:00").strip().split(":")
    hour = int(parts[0]) if parts else 0
    minute = int(parts[1]) if len(parts) > 1 else 0
    return hour, minute


class GroupChatEngine:
    """Оркестратор живой переписки своих аккаунтов в общем чате."""

    def __init__(
        self,
        config: AppConfig,
        base_dir: Path,
        log: LogCallback | None = None,
        on_stats: StatsCallback | None = None,
    ) -> None:
        self.config = config
        self.base_dir = base_dir
        self.log = log or (lambda _m: None)
        self.on_stats = on_stats or (lambda _s: None)
        self._stop = asyncio.Event()
        self.stats = GroupChatStats()
        self.settings = GroupChatSettings.load(base_dir / "config" / "group_chat.json")
        self.state = StateStore(base_dir / config.state_file)
        self._clients: dict[str, TelegramAccountClient] = {}
        self._display_names: dict[str, str] = {}
        self._user_id_to_account: dict[int, str] = {}
        self._hourly: dict[str, list[float]] = {}
        self._known_msg_ids: set[int] = set()
        self._last_speakers: list[str] = []
        self._in_quiet_until: float = 0.0
        self._pending_external_replies: list[dict[str, Any]] = []
        self._handled_external_msg_ids: set[int] = set()
        self._next_external_reply_after: float = 0.0
        self._active_chat_id: int = 0

    def stop(self) -> None:
        self._stop.set()

    def reset_stop(self) -> None:
        self._stop.clear()

    def _emit(self) -> None:
        self.on_stats(self.stats)

    def _settings_path(self) -> Path:
        return self.base_dir / "config" / "group_chat.json"

    def _refresh_pending_stats(self) -> None:
        self.stats.pending_external_replies = len(self._pending_external_replies)

    def _refresh_runtime_settings(self) -> None:
        self.settings = GroupChatSettings.load(self._settings_path())

    def _apply_runtime_session(self, session: GroupSessionRecord) -> GroupSessionRecord:
        chat_switched = self._active_chat_id and self._active_chat_id != int(session.chat_id)
        if chat_switched:
            self.log(
                f"↻ Переключаем сцену на чат "
                f"{session.chat_title or session.chat_id} / {session.topic or '—'}"
            )
            self._known_msg_ids = set()
            self._pending_external_replies = []
            self._handled_external_msg_ids = set()
            self._next_external_reply_after = 0.0
            self._last_speakers = []
            self._in_quiet_until = 0.0

        self._active_chat_id = int(session.chat_id)
        self.stats.chat_id = session.chat_id
        self.stats.chat_title = session.chat_title
        self.stats.topic = session.topic
        self.stats.account_ids = list(session.account_ids)
        self.stats.session_counts = dict(session.session_counts)
        self.stats.day_counts = dict(session.day_counts)
        self.stats.group_day_count = session.group_day_count
        self.stats.recent_messages = [message.to_dict() for message in session.messages[-12:]]
        self._refresh_pending_stats()
        return session

    @staticmethod
    def _find_message_by_id(session: GroupSessionRecord, msg_id: int | None) -> dict[str, Any] | None:
        if not msg_id:
            return None
        for message in reversed(session.messages):
            if int(message.msg_id) == int(msg_id):
                return message.to_dict()
        return None

    def _pick_reply_speaker(
        self, session: GroupSessionRecord, preferred_account_id: str = ""
    ) -> str | None:
        if (
            preferred_account_id
            and preferred_account_id in session.account_ids
            and preferred_account_id in self._clients
            and self._quota_ok(session, preferred_account_id)
        ):
            return preferred_account_id
        return self._pick_speaker(session)

    def _build_transcript(self, session: GroupSessionRecord) -> list[dict[str, str]]:
        return [
            {
                "speaker_name": message.speaker_name,
                "text": message.text,
                "speaker": message.speaker_account_id,
            }
            for message in session.messages[-self.settings.history_limit :]
        ]

    def _participants_labels(self, session: GroupSessionRecord) -> list[str]:
        return [
            f"{self._display_names.get(account_id, account_id)} ({session.role_names.get(account_id, '')})"
            for account_id in session.account_ids
        ]

    def _speaker_label(self, session: GroupSessionRecord, speaker: str) -> str:
        return (
            f"{self._display_names.get(speaker, speaker)} "
            f"[{session.role_names.get(speaker, 'роль')}]"
        )

    def _queue_external_reply(
        self,
        *,
        msg_id: int,
        speaker_account_id: str,
        speaker_name: str,
        text: str,
        quoted_text: str = "",
        quoted_speaker_account_id: str = "",
        quoted_external: bool = False,
    ) -> None:
        if msg_id in self._handled_external_msg_ids:
            return
        if any(int(item.get("msg_id") or 0) == msg_id for item in self._pending_external_replies):
            return
        self._pending_external_replies.append(
            {
                "msg_id": int(msg_id),
                "speaker_account_id": speaker_account_id,
                "speaker_name": speaker_name,
                "text": text,
                "quoted_text": quoted_text,
                "quoted_speaker_account_id": quoted_speaker_account_id,
                "quoted_external": quoted_external,
            }
        )
        preview = (text or "").strip().replace("\n", " ")
        self.stats.last_external_trigger = f"{speaker_name}: {preview[:120]}" if preview else speaker_name
        self._refresh_pending_stats()
        self._emit()

    async def _send_generated_parts(
        self,
        session: GroupSessionRecord,
        speaker: str,
        client: TelegramAccountClient,
        parts: list[str],
        *,
        reply_to_msg_id: int | None = None,
        reply_to_speaker_account_id: str = "",
        reply_to_external: bool = False,
    ) -> tuple[GroupSessionRecord, bool]:
        sent_any = False
        for idx, part in enumerate(parts):
            if self._stop.is_set():
                break
            if not self._quota_ok(session, speaker):
                break
            typing_sec = self._typing_seconds(part)
            current_reply_to = reply_to_msg_id if idx == 0 else None
            current_reply_account = reply_to_speaker_account_id if idx == 0 else ""
            current_reply_external = bool(reply_to_external and idx == 0)
            try:
                await client.show_typing_in_chat(session.chat_id, typing_sec)
                msg_id = await client.send_message_to_chat(
                    session.chat_id,
                    part,
                    reply_to_msg_id=current_reply_to,
                )
            except FloodWaitError as exc:
                wait = int(getattr(exc, "seconds", 30) or 30)
                self.log(f"⏳ FloodWait {wait}с ({speaker})")
                if await self._sleep_interruptible(wait + 2):
                    break
                continue
            except Exception as exc:
                self.log(f"❌ Отправка {speaker}: {format_telegram_error(exc)}")
                break

            sent_any = True
            self._known_msg_ids.add(msg_id)
            self.state.add_group_message(
                session,
                speaker_account_id=speaker,
                speaker_name=self._display_names.get(speaker, speaker),
                text=part,
                msg_id=msg_id,
                external=False,
                reply_to_msg_id=current_reply_to,
                reply_to_speaker_account_id=current_reply_account,
                reply_to_external=current_reply_external,
            )
            session = self.state.group_session or session
            session.session_counts[speaker] = session.session_counts.get(speaker, 0) + 1
            session.day_counts[speaker] = session.day_counts.get(speaker, 0) + 1
            session.group_day_count += 1
            self.state.upsert_group_session(session)

            now_t = asyncio.get_event_loop().time()
            self._hourly.setdefault(speaker, []).append(now_t)
            self._last_speakers.append(speaker)
            if len(self._last_speakers) > 20:
                self._last_speakers = self._last_speakers[-20:]

            self.stats.messages_sent += 1
            self.stats.last_speaker = speaker
            self.stats.last_message = part[:120]
            self.stats.session_counts = dict(session.session_counts)
            self.stats.day_counts = dict(session.day_counts)
            self.stats.group_day_count = session.group_day_count
            self.stats.recent_messages = [message.to_dict() for message in session.messages[-12:]]
            self._refresh_pending_stats()
            self.stats.status_text = f"{speaker}: отправил"
            self._emit()
            self.log(f"→ {speaker}: {part[:80]}")

            if idx < len(parts) - 1:
                pause = random.uniform(
                    self.settings.delay_within_burst_min_sec,
                    self.settings.delay_within_burst_max_sec,
                )
                if await self._sleep_interruptible(pause):
                    break
        return session, sent_any

    def _resolve_proxy(
        self, account_id: str, proxies: dict[str, ProxyConfig]
    ) -> ProxyConfig | None:
        binding = self.state.get_account_binding(account_id)
        if binding:
            saved = binding.to_proxy()
            if saved:
                return saved
        pool = load_pool(pool_path(self.base_dir))
        pooled = resolve_pool_proxy(pool, account_id)
        if pooled:
            return pooled
        return proxies.get(account_id)

    def _now_local(self) -> datetime:
        if self.settings.timezone_offset_hours is None:
            return datetime.now().astimezone()
        offset = timedelta(hours=float(self.settings.timezone_offset_hours))
        return datetime.now(timezone.utc).astimezone(timezone(offset))

    def _day_key(self) -> str:
        return self._now_local().strftime("%Y-%m-%d")

    def _in_activity_window(self, now: datetime | None = None) -> bool:
        if not self.settings.use_schedule:
            return True
        now = now or self._now_local()
        weekday = now.weekday()
        minutes = now.hour * 60 + now.minute
        for window in self.settings.activity_windows:
            if weekday not in window.days:
                continue
            sh, sm = _parse_hhmm(window.start)
            eh, em = _parse_hhmm(window.end)
            start_m = sh * 60 + sm
            end_m = eh * 60 + em
            if start_m <= end_m:
                if start_m <= minutes < end_m:
                    return True
            else:
                # через полночь
                if minutes >= start_m or minutes < end_m:
                    return True
        return False

    def _seconds_until_next_window(self) -> int:
        now = self._now_local()
        if self._in_activity_window(now):
            return 0
        for hours_ahead in range(0, 24 * 8):
            probe = now + timedelta(hours=hours_ahead)
            for minute_step in (0, 15, 30, 45):
                candidate = probe.replace(minute=minute_step, second=0, microsecond=0)
                if candidate <= now:
                    continue
                if self._in_activity_window(candidate):
                    return max(30, int((candidate - now).total_seconds()))
        return 3600

    def _ensure_day_counters(self, session: GroupSessionRecord) -> None:
        key = self._day_key()
        if session.day_key != key:
            session.day_key = key
            session.day_counts = {aid: 0 for aid in session.account_ids}
            session.group_day_count = 0

    def _quota_ok(self, session: GroupSessionRecord, account_id: str) -> bool:
        self._ensure_day_counters(session)
        s = self.settings
        if session.session_counts.get(account_id, 0) >= s.max_messages_per_account_session:
            return False
        if session.day_counts.get(account_id, 0) >= s.max_messages_per_account_day:
            return False
        if session.group_day_count >= s.max_messages_group_day:
            return False
        now = asyncio.get_event_loop().time()
        stamps = [t for t in self._hourly.get(account_id, []) if now - t < 3600]
        self._hourly[account_id] = stamps
        if len(stamps) >= s.max_messages_per_account_hour:
            return False
        return True

    def _pick_speaker(self, session: GroupSessionRecord) -> str | None:
        eligible = [a for a in session.account_ids if self._quota_ok(session, a)]
        if not eligible:
            return None
        # Не давать одному писать слишком часто подряд
        max_same = max(1, self.settings.max_consecutive_same_speaker)
        if len(self._last_speakers) >= max_same:
            recent = self._last_speakers[-max_same:]
            if len(set(recent)) == 1 and recent[0] in eligible and len(eligible) > 1:
                eligible = [a for a in eligible if a != recent[0]]
        weights = []
        for aid in eligible:
            w = float(session.activity_weights.get(aid, 1.0) or 1.0)
            weights.append(max(0.05, w))
        return random.choices(eligible, weights=weights, k=1)[0]

    def _split_text(self, text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        s = self.settings
        if not s.split_long_messages or len(text) <= s.split_at_chars:
            return [text]
        parts: list[str] = []
        remaining = text
        while remaining and len(parts) < s.split_parts_max:
            if len(remaining) <= s.split_at_chars:
                parts.append(remaining.strip())
                break
            cut = remaining.rfind(" ", 0, s.split_at_chars)
            if cut < 40:
                cut = s.split_at_chars
            parts.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining and len(parts) < s.split_parts_max:
            parts.append(remaining)
        elif remaining and parts:
            parts[-1] = (parts[-1] + " " + remaining).strip()
        return [p for p in parts if p]

    def _typing_seconds(self, text: str) -> float:
        s = self.settings
        sec = s.typing_base_sec + len(text) * s.typing_per_char_sec
        return max(0.5, min(s.typing_max_sec, sec))

    async def _sleep_interruptible(self, seconds: float) -> bool:
        """True если остановлены."""
        end = asyncio.get_event_loop().time() + max(0.0, seconds)
        while asyncio.get_event_loop().time() < end:
            if self._stop.is_set():
                return True
            await asyncio.sleep(min(1.0, end - asyncio.get_event_loop().time()))
        return self._stop.is_set()

    async def _sync_history(self, session: GroupSessionRecord, client: TelegramAccountClient) -> None:
        try:
            history = await client.get_chat_history(
                session.chat_id, limit=self.settings.history_limit
            )
        except Exception as exc:
            self.log(f"⚠ История чата: {format_telegram_error(exc)}")
            return
        for item in history:
            mid = int(item["msg_id"])
            if mid in self._known_msg_ids:
                continue
            self._known_msg_ids.add(mid)
            sender_id = int(item.get("sender_id") or 0)
            account_id = self._user_id_to_account.get(sender_id, "")
            external = account_id == ""
            speaker_name = item.get("sender_name") or (
                self._display_names.get(account_id) if account_id else f"id_{sender_id}"
            )
            if account_id:
                speaker_name = self._display_names.get(account_id, speaker_name)
            reply_to_msg_id = int(item.get("reply_to_msg_id") or 0) or None
            reply_to_sender_id = int(item.get("reply_to_sender_id") or 0)
            reply_to_account_id = self._user_id_to_account.get(reply_to_sender_id, "")
            reply_to_external = False
            quoted_text = str(item.get("reply_to_text") or "").strip()
            replied_message = self._find_message_by_id(session, reply_to_msg_id)
            if replied_message:
                if not reply_to_account_id and not replied_message.get("external"):
                    reply_to_account_id = str(replied_message.get("speaker_account_id") or "")
                reply_to_external = bool(replied_message.get("external", False))
                if not quoted_text:
                    quoted_text = str(replied_message.get("text") or "").strip()
            self.state.add_group_message(
                session,
                speaker_account_id=account_id or f"ext:{sender_id}",
                speaker_name=str(speaker_name),
                text=item["text"],
                msg_id=mid,
                external=external,
                reply_to_msg_id=reply_to_msg_id,
                reply_to_speaker_account_id=reply_to_account_id,
                reply_to_external=reply_to_external,
                max_stored=200,
            )
            session = self.state.group_session or session
            if external and self.settings.reply_to_humans_enabled:
                quoted_our_bot = bool(reply_to_msg_id and reply_to_account_id and not reply_to_external)
                should_consider = quoted_our_bot or not self.settings.reply_to_humans_only_on_quote
                chance = min(1.0, max(0.0, float(self.settings.reply_to_humans_chance or 0.0)))
                if should_consider and random.random() <= chance:
                    self._queue_external_reply(
                        msg_id=mid,
                        speaker_account_id=f"ext:{sender_id}",
                        speaker_name=str(speaker_name),
                        text=item["text"],
                        quoted_text=quoted_text,
                        quoted_speaker_account_id=reply_to_account_id,
                        quoted_external=reply_to_external,
                    )
            low = item["text"].lower()
            for kw in self.settings.stop_keywords:
                if kw and kw.lower() in low:
                    self.log(f"■ Стоп-слово в чате: «{kw}»")
                    self._stop.set()
                    return
        session = self.state.group_session or session
        self.stats.recent_messages = [m.to_dict() for m in session.messages[-12:]]
        self._emit()

    async def run(
        self,
        account_ids: list[str],
        chat_id: int,
        topic: str,
        role_overrides: dict[str, dict] | None = None,
        activity_weights: dict[str, float] | None = None,
        extra_context: str = "",
        chat_title: str = "",
    ) -> None:
        self.reset_stop()
        self.settings = GroupChatSettings.load(self._settings_path())
        self.state.load()
        self._pending_external_replies = []
        self._handled_external_msg_ids = set()
        self._next_external_reply_after = 0.0
        roles = RolesConfig.load(self.base_dir / self.config.roles_file)
        role_overrides = role_overrides or {}
        activity_weights = activity_weights or {}

        sessions = discover_sessions(self.base_dir / self.config.sessions_dir)
        by_id = {s.account_id: s for s in sessions}
        missing = [a for a in account_ids if a not in by_id]
        if missing:
            self.log(f"❌ Аккаунты не найдены: {', '.join(missing)}")
            self.stats.running = False
            self._emit()
            return

        if not self.config.llm_configured():
            self.log("❌ Укажите API-ключ LLM")
            self.stats.running = False
            self._emit()
            return

        proxies = load_proxies(self.base_dir / self.config.proxies_file)
        llm = create_llm_client(self.config, master_prompt=roles.master_prompt)

        role_prompts: dict[str, str] = {}
        role_names: dict[str, str] = {}
        weights: dict[str, float] = {}

        for aid in account_ids:
            override = role_overrides.get(aid) or {}
            prompt = str(override.get("role_prompt") or "").strip()
            name = str(override.get("role_name") or "").strip()
            if not prompt:
                prompt = roles.prompt_for_account(aid)
            if not name:
                name = roles.role_name_for_account(aid) or "участник"
            role_prompts[aid] = prompt
            role_names[aid] = name
            weights[aid] = float(activity_weights.get(aid, 1.0) or 1.0)

        session = GroupSessionRecord(
            chat_id=int(chat_id),
            topic=topic.strip(),
            chat_title=chat_title.strip(),
            account_ids=list(account_ids),
            role_prompts=role_prompts,
            role_names=role_names,
            activity_weights=weights,
            extra_context=extra_context.strip(),
            status="active",
            session_counts={a: 0 for a in account_ids},
            day_counts={a: 0 for a in account_ids},
            day_key=self._day_key(),
            group_day_count=0,
        )
        self.state.upsert_group_session(session)
        self._active_chat_id = session.chat_id

        self.stats = GroupChatStats(
            running=True,
            chat_id=session.chat_id,
            chat_title=session.chat_title,
            topic=session.topic,
            account_ids=list(account_ids),
            status_text="подключение...",
            session_counts=dict(session.session_counts),
            day_counts=dict(session.day_counts),
            pending_external_replies=0,
        )
        self._apply_runtime_session(session)
        self._emit()

        try:
            for aid in account_ids:
                if self._stop.is_set():
                    break
                sess = by_id[aid]
                proxy = self._resolve_proxy(aid, proxies)
                two_fa = read_twofa_password(sess, self.config.telegram_2fa_password)
                client = TelegramAccountClient(
                    sess,
                    self.config.telegram_api_id,
                    self.config.telegram_api_hash,
                    proxy=proxy,
                    two_fa_password=two_fa,
                )
                display = await client.connect()
                self._clients[aid] = client
                self._display_names[aid] = display
                if client.my_user_id:
                    self._user_id_to_account[client.my_user_id] = aid
                self.log(f"✓ {aid} (@{display}) в групповом чате")

            if len(self._clients) < 2:
                self.log("❌ Нужно минимум 2 подключённых аккаунта")
                return

            primary = self._clients[account_ids[0]]
            await self._sync_history(session, primary)
            if not session.chat_title:
                try:
                    dialogs = await primary.list_group_dialogs()
                    for d in dialogs:
                        if d["chat_id"] == session.chat_id:
                            session.chat_title = d["title"]
                            break
                except Exception:
                    pass
                self.state.upsert_group_session(session)
                self.stats.chat_title = session.chat_title
            session = self._apply_runtime_session(session)

            self.log(
                f"▶ Групповой чат «{session.chat_title or session.chat_id}», "
                f"тема: {session.topic or '—'}"
            )
            self.stats.status_text = "работает"
            self._emit()

            last_sync = 0.0
            while not self._stop.is_set():
                self._refresh_runtime_settings()
                session = self.state.group_session or session
                session = self._apply_runtime_session(session)
                self._ensure_day_counters(session)

                now_mono = asyncio.get_event_loop().time()
                if now_mono - last_sync >= self.settings.sync_history_every_sec:
                    await self._sync_history(session, primary)
                    last_sync = now_mono
                    session = self.state.group_session or session
                    session = self._apply_runtime_session(session)
                    if self._stop.is_set():
                        break

                if self.settings.use_schedule and not self._in_activity_window():
                    wait = self._seconds_until_next_window()
                    self.stats.paused_schedule = True
                    self.stats.status_text = f"вне окна активности, пауза ~{wait // 60} мин"
                    self._emit()
                    if not self.settings.resume_next_day:
                        self.log("■ Вне расписания — остановка (resume_next_day выкл.)")
                        break
                    self.log(f"⏸ Вне окна активности, ждём ~{wait // 60} мин")
                    if await self._sleep_interruptible(min(wait, 900)):
                        break
                    continue

                self.stats.paused_schedule = False

                if now_mono < self._in_quiet_until:
                    left = int(self._in_quiet_until - now_mono)
                    self.stats.status_text = f"тихая пауза ~{left // 60} мин"
                    self._emit()
                    if await self._sleep_interruptible(min(60, left)):
                        break
                    continue

                if self._pending_external_replies:
                    self._refresh_pending_stats()
                    if now_mono < self._next_external_reply_after:
                        left = max(1, int(self._next_external_reply_after - now_mono))
                        self.stats.status_text = f"ожидание ответа живому участнику ~{left}с"
                        self._emit()
                        if await self._sleep_interruptible(min(10, left)):
                            break
                        continue

                    payload = self._pending_external_replies[0]
                    preferred_account_id = str(payload.get("quoted_speaker_account_id") or "")
                    speaker = self._pick_reply_speaker(session, preferred_account_id=preferred_account_id)
                    if not speaker:
                        self.stats.status_text = "нет доступного участника для ответа живому"
                        self._emit()
                        if await self._sleep_interruptible(20):
                            break
                        continue

                    client = self._clients.get(speaker)
                    if not client:
                        self._pending_external_replies.pop(0)
                        self._refresh_pending_stats()
                        continue

                    quoted_text = str(payload.get("quoted_text") or "").strip()
                    human_name = str(payload.get("speaker_name") or "участник")
                    human_text = str(payload.get("text") or "").strip()
                    context_parts = []
                    if session.extra_context:
                        context_parts.append(session.extra_context)
                    context_parts.append(
                        "В чате живой участник обратился к одному из ваших аккаунтов. "
                        "Нужен один естественный ответ от имени текущего спикера."
                    )
                    context_parts.append(
                        "Не устраивай цепную реакцию, не призывай остальных аккаунтов отвечать и не раскрывай, "
                        "что аккаунты связаны между собой."
                    )
                    context_parts.append(
                        "Ответ должен быть коротким или средним, по делу, в живом человеческом стиле."
                    )
                    if quoted_text:
                        context_parts.append(f"Цитируемая реплика: {quoted_text}")
                    context_parts.append(f"Сообщение живого участника {human_name}: {human_text}")

                    self.stats.status_text = f"{speaker}: отвечает живому участнику..."
                    self._emit()
                    try:
                        text = await llm.generate_group_message(
                            role_prompt=session.role_prompts.get(speaker, ""),
                            topic=session.topic,
                            transcript=self._build_transcript(session),
                            speaker_label=self._speaker_label(session, speaker),
                            participants=self._participants_labels(session),
                            language=self.settings.language,
                            extra_context="\n".join(part for part in context_parts if part),
                            short_reply=True,
                            temperature=self.settings.temperature,
                            max_tokens=self.settings.max_tokens,
                        )
                    except Exception as exc:
                        self.log(f"❌ LLM {speaker} (ответ живому): {exc}")
                        if await self._sleep_interruptible(15):
                            break
                        continue

                    parts = self._split_text(text)
                    if not parts:
                        self._pending_external_replies.pop(0)
                        self._refresh_pending_stats()
                        continue

                    session, sent = await self._send_generated_parts(
                        session,
                        speaker,
                        client,
                        parts[:1],
                        reply_to_msg_id=int(payload.get("msg_id") or 0) or None,
                        reply_to_speaker_account_id=str(payload.get("speaker_account_id") or ""),
                        reply_to_external=True,
                    )
                    if sent:
                        self._handled_external_msg_ids.add(int(payload.get("msg_id") or 0))
                        self._pending_external_replies.pop(0)
                        self._refresh_pending_stats()
                        cooldown = random.uniform(
                            self.settings.reply_to_humans_cooldown_min_sec,
                            max(
                                self.settings.reply_to_humans_cooldown_min_sec,
                                self.settings.reply_to_humans_cooldown_max_sec,
                            ),
                        )
                        self._next_external_reply_after = asyncio.get_event_loop().time() + cooldown
                    else:
                        if await self._sleep_interruptible(10):
                            break
                    continue

                if random.random() < self.settings.quiet_break_chance:
                    mins = random.randint(
                        self.settings.quiet_break_min_min,
                        max(self.settings.quiet_break_min_min, self.settings.quiet_break_max_min),
                    )
                    self._in_quiet_until = now_mono + mins * 60
                    self.log(f"⏸ Тихая пауза {mins} мин")
                    continue

                if random.random() > self.settings.online_probability:
                    self.stats.status_text = "ожидание (вероятность онлайна)"
                    self._emit()
                    if await self._sleep_interruptible(random.uniform(20, 60)):
                        break
                    continue

                speaker = self._pick_speaker(session)
                if not speaker:
                    self.stats.status_text = "квоты исчерпаны"
                    self._emit()
                    self.log("■ Квоты сообщений исчерпаны")
                    break

                client = self._clients.get(speaker)
                if not client:
                    continue

                if random.random() < self.settings.read_and_wait_chance:
                    wait = random.uniform(
                        self.settings.read_and_wait_min_sec,
                        self.settings.read_and_wait_max_sec,
                    )
                    self.stats.status_text = f"{speaker}: читает чат..."
                    self._emit()
                    if await self._sleep_interruptible(wait):
                        break

                short = False
                if self.settings.reply_style == "short":
                    short = True
                elif self.settings.reply_style == "mixed":
                    short = random.random() < self.settings.short_reply_chance

                self.stats.status_text = f"{speaker}: генерирует..."
                self._emit()
                try:
                    text = await llm.generate_group_message(
                        role_prompt=session.role_prompts.get(speaker, ""),
                        topic=session.topic,
                        transcript=self._build_transcript(session),
                        speaker_label=self._speaker_label(session, speaker),
                        participants=self._participants_labels(session),
                        language=self.settings.language,
                        extra_context=session.extra_context,
                        short_reply=short,
                        temperature=self.settings.temperature,
                        max_tokens=self.settings.max_tokens,
                    )
                except Exception as exc:
                    self.log(f"❌ LLM {speaker}: {exc}")
                    if await self._sleep_interruptible(15):
                        break
                    continue

                parts = self._split_text(text)
                if not parts:
                    continue

                burst_limit = random.randint(
                    self.settings.burst_min,
                    max(self.settings.burst_min, self.settings.burst_max),
                )
                parts = parts[:burst_limit]

                session, _sent = await self._send_generated_parts(
                    session,
                    speaker,
                    client,
                    parts,
                )

                between = random.uniform(
                    self.settings.delay_between_speakers_min_sec,
                    self.settings.delay_between_speakers_max_sec,
                )
                self.stats.status_text = "пауза между репликами"
                self._emit()
                if await self._sleep_interruptible(between):
                    break

        finally:
            for client in self._clients.values():
                try:
                    await client.disconnect()
                except Exception:
                    pass
            self._clients.clear()
            if self.state.group_session:
                self.state.group_session.status = "stopped"
                self.state.upsert_group_session(self.state.group_session)
            self.stats.running = False
            self.stats.status_text = "остановлено"
            self._emit()
            self.log("■ Групповой чат остановлен")
