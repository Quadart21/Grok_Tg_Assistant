from __future__ import annotations

import asyncio
from collections import Counter
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Sequence

from telethon.errors import FloodWaitError

from core.config import AppConfig, ProxyConfig, RolesConfig
from core.group_chat_settings import ActivityWindow, GroupChatSettings
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

    _LOW_SIGNAL_TOKENS = {
        "вообще",
        "вроде",
        "всякое",
        "грязи",
        "грязь",
        "just",
        "really",
        "that",
        "this",
        "very",
        "когда",
        "клей",
        "который",
        "которая",
        "которые",
        "нужно",
        "опять",
        "просто",
        "прям",
        "снова",
        "такой",
        "такая",
        "такие",
        "тоже",
        "только",
        "эта",
        "это",
        "этого",
        "этой",
        "этому",
        "этот",
    }

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
        self._account_online: dict[str, bool] = {}
        self._account_resume_pending: dict[str, bool] = {}
        self._friendships: dict[str, set[str]] = {}
        self._scene_revision_seen: int = 0
        self._history_refresh_required: bool = False

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
        scene_reset_requested = (
            self._scene_revision_seen > 0
            and int(session.scene_revision or 0) != self._scene_revision_seen
            and bool(session.reset_context_on_apply)
        )
        if chat_switched or scene_reset_requested:
            if chat_switched:
                self.log(
                    f"↻ Переключаем сцену на чат "
                    f"{session.chat_title or session.chat_id} / {session.topic or '—'}"
                )
            else:
                self.log("↻ Сцена обновлена: сбрасываем память и перечитываем свежую историю")
            self._known_msg_ids = set()
            self._pending_external_replies = []
            self._handled_external_msg_ids = set()
            self._next_external_reply_after = 0.0
            self._last_speakers = []
            self._in_quiet_until = 0.0
            self._history_refresh_required = True
        elif self._active_chat_id == 0:
            self._history_refresh_required = True

        self._active_chat_id = int(session.chat_id)
        self._scene_revision_seen = int(session.scene_revision or 0)
        self._friendships = self._normalize_session_friendships(session)
        self._account_online = {
            account_id: self._account_online.get(account_id, True)
            for account_id in session.account_ids
        }
        self._account_resume_pending = {
            account_id: self._account_resume_pending.get(account_id, False)
            for account_id in session.account_ids
        }
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

    def _normalize_session_friendships(
        self, session: GroupSessionRecord
    ) -> dict[str, set[str]]:
        links: dict[str, set[str]] = {account_id: set() for account_id in session.account_ids}
        for account_id, friends in (session.friendships or {}).items():
            if account_id not in links:
                continue
            for friend_id in friends or []:
                if friend_id not in links or friend_id == account_id:
                    continue
                links[account_id].add(friend_id)
                links[friend_id].add(account_id)
        return links

    @staticmethod
    def _window_matches(window: ActivityWindow, now: datetime) -> bool:
        weekday = now.weekday()
        minutes = now.hour * 60 + now.minute
        if weekday not in window.days:
            return False
        sh, sm = _parse_hhmm(window.start)
        eh, em = _parse_hhmm(window.end)
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        if start_m <= end_m:
            return start_m <= minutes < end_m
        return minutes >= start_m or minutes < end_m

    def _windows_from_session(self, session: GroupSessionRecord, account_id: str) -> list[ActivityWindow]:
        windows: list[ActivityWindow] = []
        for item in (session.account_schedules or {}).get(account_id, []):
            if not isinstance(item, dict):
                continue
            start = str(item.get("start") or "").strip()
            end = str(item.get("end") or "").strip()
            if not start or not end:
                continue
            raw_days = item.get("days")
            if isinstance(raw_days, list):
                days = [int(day) for day in raw_days if isinstance(day, int) or str(day).isdigit()]
            else:
                days = list(range(7))
            windows.append(ActivityWindow(start=start, end=end, days=days or list(range(7))))
        return windows

    def _is_account_scheduled_online(
        self,
        session: GroupSessionRecord,
        account_id: str,
        now: datetime | None = None,
    ) -> bool:
        if not self.settings.use_schedule:
            return True
        now = now or self._now_local()
        if not self._in_activity_window(now):
            return False
        windows = self._windows_from_session(session, account_id)
        if not windows:
            return True
        return any(self._window_matches(window, now) for window in windows)

    def online_accounts(self) -> dict[str, bool]:
        return dict(self._account_online)

    def _speaker_friend_context(self, session: GroupSessionRecord, speaker: str) -> str:
        friend_ids = self._friendships.get(speaker, set())
        if not friend_ids:
            return ""
        friend_labels = [
            self._display_names.get(friend_id, session.role_names.get(friend_id, friend_id))
            for friend_id in sorted(friend_ids)
        ]
        return (
            "В чате у тебя давние приятельские отношения с: "
            + ", ".join(friend_labels)
            + ". С ними можно звучать чуть теплее, подхватывать их шутки и говорить естественно, "
            "но не проговаривать это напрямую."
        )

    def _resume_context(self, limit: int) -> str:
        return (
            f"Ты только что вернулся в чат после паузы. Внимательно опирайся на последние {limit} сообщений "
            "и продолжай текущую линию разговора без приветствия и без фразы, что ты что-то пропустил."
        )

    def _compose_speaker_context(
        self,
        session: GroupSessionRecord,
        speaker: str,
        base_context: str = "",
        reply_target: dict[str, Any] | None = None,
    ) -> str:
        parts: list[str] = []
        if base_context.strip():
            parts.append(base_context.strip())
        friend_context = self._speaker_friend_context(session, speaker)
        if friend_context:
            parts.append(friend_context)
        theme_context = self._theme_fatigue_context(session, reply_target=reply_target)
        if theme_context:
            parts.append(theme_context)
        if self._account_resume_pending.get(speaker):
            limit = max(self.settings.history_limit, self.settings.reconnect_history_limit)
            parts.append(self._resume_context(limit))
        return "\n".join(parts)

    async def _refresh_account_presence(
        self,
        session: GroupSessionRecord,
        client: TelegramAccountClient,
    ) -> GroupSessionRecord:
        now = self._now_local()
        history_refresh_needed = False
        for account_id in session.account_ids:
            scheduled_online = self._is_account_scheduled_online(session, account_id, now)
            was_online = self._account_online.get(account_id)
            if was_online is None:
                self._account_online[account_id] = scheduled_online
                self._account_resume_pending.setdefault(account_id, False)
                continue
            if scheduled_online and not was_online:
                self._account_online[account_id] = True
                self._account_resume_pending[account_id] = True
                history_refresh_needed = True
                self.log(f"↺ {account_id}: вернулся онлайн по расписанию")
            elif not scheduled_online and was_online:
                self._account_online[account_id] = False
                self.log(f"⏸ {account_id}: ушёл оффлайн по расписанию")
        if history_refresh_needed:
            await self._sync_history(
                session,
                client,
                limit=max(self.settings.history_limit, self.settings.reconnect_history_limit),
            )
            session = self.state.group_session or session
        return session

    @staticmethod
    def _find_message_record_by_id(session: GroupSessionRecord, msg_id: int | None) -> Any | None:
        if not msg_id:
            return None
        for message in reversed(session.messages):
            if int(message.msg_id) == int(msg_id):
                return message
        return None

    @classmethod
    def _find_message_by_id(cls, session: GroupSessionRecord, msg_id: int | None) -> dict[str, Any] | None:
        message = cls._find_message_record_by_id(session, msg_id)
        if message is None:
            return None
        return message.to_dict()

    @staticmethod
    def _message_preview(text: str, limit: int = 180) -> str:
        preview = (text or "").strip().replace("\n", " ")
        if len(preview) <= limit:
            return preview
        return preview[: limit - 1].rstrip() + "…"

    def _analysis_history_limit(self) -> int:
        return max(
            1,
            int(
                max(
                    self.settings.history_limit,
                    self.settings.reconnect_history_limit,
                    self.settings.dedupe_recent_messages_window,
                    self.settings.theme_fatigue_window,
                )
            ),
        )

    def _recent_messages_for_analysis(
        self,
        session: GroupSessionRecord,
        limit: int | None = None,
    ) -> list[Any]:
        history_limit = max(1, int(limit or self._analysis_history_limit()))
        return session.messages[-history_limit:]

    def _thread_root_id(
        self,
        session: GroupSessionRecord,
        message_or_id: Any,
        cache: dict[int, int] | None = None,
    ) -> int:
        msg_id = int(getattr(message_or_id, "msg_id", message_or_id) or 0)
        if not msg_id:
            return 0
        if cache is not None and msg_id in cache:
            return cache[msg_id]

        visited: set[int] = set()
        current = self._find_message_record_by_id(session, msg_id)
        root_id = msg_id
        while current is not None:
            parent_id = int(current.reply_to_msg_id or 0)
            if not parent_id or parent_id in visited:
                break
            visited.add(root_id)
            root_id = parent_id
            current = self._find_message_record_by_id(session, parent_id)

        if cache is not None:
            cache[msg_id] = root_id
            for visited_id in visited:
                cache[visited_id] = root_id
        return root_id

    def _theme_fatigue_markers(
        self,
        messages: Sequence[Any],
    ) -> tuple[list[str], list[str]]:
        token_counts: Counter[str] = Counter()
        phrase_counts: Counter[str] = Counter()
        for message in messages:
            token_counts.update(self._content_tokens(message.text))
            phrase_counts.update(self._phrase_ngrams(self._message_tokens(message.text), 2))

        hot_tokens = [
            token
            for token, count in token_counts.most_common()
            if count >= max(2, int(self.settings.theme_fatigue_token_repeat or 0))
        ][:6]
        hot_phrases = [
            phrase
            for phrase, count in phrase_counts.most_common()
            if count >= max(2, int(self.settings.theme_fatigue_phrase_repeat or 0))
        ][:4]
        return hot_tokens, hot_phrases

    def _theme_fatigue_context(
        self,
        session: GroupSessionRecord,
        reply_target: dict[str, Any] | None = None,
    ) -> str:
        messages = self._recent_messages_for_analysis(
            session,
            limit=max(
                int(self.settings.theme_fatigue_window or 0),
                int(self.settings.dedupe_recent_messages_window or 0),
            ),
        )
        if len(messages) < 4:
            return ""

        hot_tokens, hot_phrases = self._theme_fatigue_markers(messages)
        if not hot_tokens and not hot_phrases:
            return ""

        parts = ["В последних сообщениях уже начали повторяться одни и те же мотивы."]
        if hot_phrases:
            parts.append("Не возвращайся к оборотам и образам: " + ", ".join(hot_phrases))
        if hot_tokens:
            parts.append("Не крутись вокруг одних и тех же смысловых опор: " + ", ".join(hot_tokens))
        if reply_target and reply_target.get("speaker_name"):
            parts.append(
                f"Если отвечаешь {reply_target.get('speaker_name')}, не перефразируй уже сказанное в этой ветке; сдвинь разговор дальше."
            )
        else:
            parts.append("Сдвинь разговор дальше: новый факт, вопрос, контраргумент, уточнение или смена фокуса.")
        return "\n".join(parts)

    def _find_stale_theme_duplicate(
        self,
        session: GroupSessionRecord,
        text: str,
    ) -> dict[str, Any] | None:
        messages = self._recent_messages_for_analysis(
            session,
            limit=max(
                int(self.settings.theme_fatigue_window or 0),
                int(self.settings.dedupe_recent_messages_window or 0),
            ),
        )
        if len(messages) < 4:
            return None

        hot_tokens, hot_phrases = self._theme_fatigue_markers(messages)
        candidate_tokens = self._content_tokens(text)
        candidate_phrases = self._phrase_ngrams(self._message_tokens(text), 2)
        shared_tokens = sorted(candidate_tokens & set(hot_tokens))
        shared_phrases = sorted(candidate_phrases & set(hot_phrases))
        token_ratio = len(shared_tokens) / max(1, len(candidate_tokens))
        phrase_ratio = len(shared_phrases) / max(1, len(candidate_phrases)) if candidate_phrases else 0.0
        if not shared_phrases and (len(shared_tokens) < 2 or token_ratio < 0.6):
            return None

        anchor = next(
            (
                message
                for message in reversed(messages)
                if (self._content_tokens(message.text) & set(shared_tokens))
                or (self._phrase_ngrams(self._message_tokens(message.text), 2) & set(shared_phrases))
            ),
            messages[-1],
        )
        return {
            "message": anchor,
            "reason": "stale_theme",
            "similarity": max(token_ratio, phrase_ratio),
            "shared_tokens": shared_tokens,
            "shared_phrase": shared_phrases[0] if shared_phrases else "",
        }

    def _duplicate_reason_label(self, duplicate: dict[str, Any]) -> str:
        reason = str(duplicate.get("reason") or "")
        similarity = float(duplicate.get("similarity") or 0.0)
        if reason == "similar":
            return f"слишком похоже ({similarity:.2f})"
        if reason == "stale_theme":
            return "заезженный мотив/тезис"
        if reason in {"phrase", "phrase_overlap"}:
            phrase = str(duplicate.get("shared_phrase") or "").strip()
            return f"повтор образа/оборота: {phrase}" if phrase else "повтор образа/оборота"
        if reason == "content":
            return "слишком близкий набор смысловых слов"
        return "дословный повтор"

    def _count_direct_replies(self, session: GroupSessionRecord, msg_id: int) -> int:
        if not msg_id:
            return 0
        return sum(1 for message in session.messages if int(message.reply_to_msg_id or 0) == int(msg_id))

    def _pick_reply_target(self, session: GroupSessionRecord, speaker: str) -> dict[str, Any] | None:
        recent_messages = self._recent_messages_for_analysis(session)
        if not recent_messages:
            return None

        replied_targets = {
            int(message.reply_to_msg_id)
            for message in recent_messages
            if message.speaker_account_id == speaker and message.reply_to_msg_id
        }
        friend_ids = self._friendships.get(speaker, set())
        thread_cache: dict[int, int] = {}
        thread_sizes: Counter[int] = Counter()
        interaction_counts: Counter[tuple[str, str]] = Counter()
        speaker_recent_counts: Counter[str] = Counter()
        for message in recent_messages:
            msg_id = int(message.msg_id or 0)
            if msg_id:
                thread_sizes[self._thread_root_id(session, msg_id, cache=thread_cache)] += 1
            if message.speaker_account_id:
                speaker_recent_counts[message.speaker_account_id] += 1
            if message.reply_to_speaker_account_id and message.speaker_account_id:
                interaction_counts[(message.speaker_account_id, message.reply_to_speaker_account_id)] += 1

        best_score = float("-inf")
        best_message: Any | None = None
        for offset, message in enumerate(reversed(recent_messages), start=1):
            msg_id = int(message.msg_id or 0)
            if not msg_id or message.speaker_account_id == speaker:
                continue

            score = max(0.0, 60.0 - offset * 3.5)
            if offset == 1:
                score += 10.0
            if message.external:
                score += 14.0
            if message.speaker_account_id in friend_ids:
                score += 5.0
            if message.reply_to_speaker_account_id == speaker:
                score += 8.0
            if msg_id in replied_targets:
                score -= 16.0

            direct_replies = self._count_direct_replies(session, msg_id)
            if direct_replies == 0:
                score += 4.0
            score -= min(direct_replies, 4) * 2.5
            root_id = self._thread_root_id(session, msg_id, cache=thread_cache)
            score -= max(0, thread_sizes.get(root_id, 0) - 2) * 1.8
            score -= interaction_counts.get((speaker, message.speaker_account_id), 0) * 4.0
            score -= max(0, speaker_recent_counts.get(message.speaker_account_id, 0) - 2) * 1.2

            if score > best_score:
                best_score = score
                best_message = message

        if best_message is None or best_score < 1.0:
            return None
        return best_message.to_dict()

    def _pick_reply_speaker(
        self, session: GroupSessionRecord, preferred_account_id: str = ""
    ) -> str | None:
        if (
            preferred_account_id
            and preferred_account_id in session.account_ids
            and preferred_account_id in self._clients
            and self._account_online.get(preferred_account_id, True)
            and self._quota_ok(session, preferred_account_id)
        ):
            return preferred_account_id
        return self._pick_speaker(session)

    def _reply_target_context(
        self,
        session: GroupSessionRecord,
        target: dict[str, Any] | None,
    ) -> str:
        if not target:
            return ""

        target_name = (
            str(target.get("speaker_name") or "")
            or self._display_names.get(str(target.get("speaker_account_id") or ""), "")
            or str(target.get("speaker_account_id") or "собеседник")
        )
        target_text = self._message_preview(str(target.get("text") or ""))
        if not target_text:
            return ""

        parts = [
            "Сообщение будет отправлено как reply/цитата в Telegram.",
            f"Ответь именно на реплику {target_name}: {target_text}",
            "Сохраняй нить разговора: помни, кто кому отвечает, и не путай адресатов.",
        ]

        parent = self._find_message_by_id(session, int(target.get("reply_to_msg_id") or 0) or None)
        if parent:
            parent_name = (
                str(parent.get("speaker_name") or "")
                or str(parent.get("speaker_account_id") or "собеседник")
            )
            parent_text = self._message_preview(str(parent.get("text") or ""))
            if parent_text:
                parts.append(
                    f"Эта реплика сама была ответом на {parent_name}: {parent_text}"
                )

        return "\n".join(parts)

    def _build_transcript(
        self, session: GroupSessionRecord, limit: int | None = None
    ) -> list[dict[str, Any]]:
        history_limit = max(1, int(limit or self.settings.history_limit))
        transcript: list[dict[str, Any]] = []
        for message in session.messages[-history_limit:]:
            item: dict[str, Any] = {
                "speaker_name": message.speaker_name,
                "text": message.text,
                "speaker": message.speaker_account_id,
                "msg_id": message.msg_id,
                "external": message.external,
            }
            if message.reply_to_msg_id:
                item["reply_to_msg_id"] = message.reply_to_msg_id
                item["reply_to_external"] = message.reply_to_external
                replied = self._find_message_by_id(session, message.reply_to_msg_id)
                reply_name = ""
                reply_text = ""
                if replied:
                    reply_name = str(replied.get("speaker_name") or replied.get("speaker_account_id") or "")
                    reply_text = str(replied.get("text") or "")
                elif message.reply_to_speaker_account_id:
                    reply_name = self._display_names.get(
                        message.reply_to_speaker_account_id,
                        message.reply_to_speaker_account_id,
                    )
                item["reply_to_speaker"] = reply_name
                if reply_text:
                    item["reply_to_text"] = reply_text
            transcript.append(item)
        return transcript

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

    @staticmethod
    def _normalize_message(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        normalized = re.sub(r"[^\w\s]+", "", normalized, flags=re.UNICODE)
        return normalized.strip()

    @classmethod
    def _message_tokens(cls, text: str) -> list[str]:
        normalized = cls._normalize_message(text)
        if not normalized:
            return []
        return [token for token in normalized.split() if token]

    @classmethod
    def _content_tokens(cls, text: str) -> set[str]:
        return {
            token
            for token in cls._message_tokens(text)
            if (len(token) >= 4 or any(ch.isdigit() for ch in token))
            and token not in cls._LOW_SIGNAL_TOKENS
        }

    @staticmethod
    def _phrase_ngrams(tokens: list[str], size: int) -> set[str]:
        if size <= 0 or len(tokens) < size:
            return set()
        return {" ".join(tokens[idx : idx + size]) for idx in range(len(tokens) - size + 1)}

    def _find_recent_duplicate(
        self, session: GroupSessionRecord, text: str
    ) -> dict[str, Any] | None:
        candidate = self._normalize_message(text)
        if not candidate:
            return None

        candidate_tokens = self._message_tokens(text)
        candidate_content = self._content_tokens(text)
        candidate_bigrams = self._phrase_ngrams(candidate_tokens, 2)
        candidate_trigrams = self._phrase_ngrams(candidate_tokens, 3)

        window = max(1, int(self.settings.dedupe_recent_messages_window or 1))
        threshold = min(
            0.99,
            max(0.0, float(self.settings.dedupe_similarity_threshold or 0.0)),
        )
        for message in reversed(session.messages[-window:]):
            existing = self._normalize_message(message.text)
            if not existing:
                continue
            if candidate == existing:
                return {"message": message, "reason": "exact", "similarity": 1.0}

            existing_tokens = self._message_tokens(message.text)
            if candidate_trigrams and existing_tokens:
                shared_trigrams = candidate_trigrams & self._phrase_ngrams(existing_tokens, 3)
                if shared_trigrams:
                    return {
                        "message": message,
                        "reason": "phrase",
                        "similarity": 1.0,
                        "shared_phrase": sorted(shared_trigrams)[0],
                    }

            if len(candidate) < 12 or len(existing) < 12:
                continue

            similarity = SequenceMatcher(None, candidate, existing).ratio()
            if similarity >= threshold:
                return {
                    "message": message,
                    "reason": "similar",
                    "similarity": similarity,
                }

            existing_content = self._content_tokens(message.text)
            shared_content = candidate_content & existing_content
            if shared_content:
                overlap = len(shared_content) / max(1, min(len(candidate_content), len(existing_content)))
                if len(shared_content) >= 4 and overlap >= 0.8:
                    return {
                        "message": message,
                        "reason": "content",
                        "similarity": overlap,
                        "shared_tokens": sorted(shared_content),
                    }

            if candidate_bigrams and existing_tokens:
                existing_bigrams = self._phrase_ngrams(existing_tokens, 2)
                shared_bigrams = candidate_bigrams & existing_bigrams
                if len(shared_bigrams) >= 2:
                    return {
                        "message": message,
                        "reason": "phrase_overlap",
                        "similarity": len(shared_bigrams)
                        / max(1, min(len(candidate_bigrams), len(existing_bigrams))),
                        "shared_phrase": sorted(shared_bigrams)[0],
                    }
        stale_theme = self._find_stale_theme_duplicate(session, text)
        if stale_theme:
            return stale_theme
        return None

    def _build_retry_context_v2(
        self,
        session: GroupSessionRecord,
        duplicate: dict[str, Any] | None,
        base_context: str = "",
    ) -> str:
        parts: list[str] = []
        if base_context.strip():
            parts.append(base_context.strip())
        if not duplicate:
            return "\n".join(parts)

        message = duplicate["message"]
        quoted = (message.text or "").strip().replace("\n", " ")
        quoted = quoted[:220]
        speaker_name = message.speaker_name or message.speaker_account_id or "participant"
        if session.topic.strip():
            parts.append(f"Stay on the chat topic: {session.topic.strip()}")
        parts.append(f"Anti-repeat retry: do not reuse the recent line from {speaker_name}: {quoted}")
        if duplicate.get("shared_phrase"):
            parts.append(f"Do not repeat this phrase or analogy: {duplicate['shared_phrase']}")
        if duplicate.get("shared_tokens"):
            tokens = ", ".join(str(token) for token in duplicate["shared_tokens"][:6])
            parts.append(f"Do not keep the same semantic anchors: {tokens}")
        if duplicate.get("reason") == "stale_theme":
            parts.append("This thesis is already exhausted in the chat. Change direction, not just wording.")
        parts.append(
            "Do not repeat the same thesis, comparison, joke, or conclusion even in different words."
        )
        parts.append(
            "Write the next reply from a new angle: another argument, question, clarification, example, or focus."
        )
        return "\n".join(parts)

    def _anti_repeat_context(
        self,
        session: GroupSessionRecord,
        duplicate: dict[str, Any] | None,
        base_context: str = "",
    ) -> str:
        parts: list[str] = []
        if base_context.strip():
            parts.append(base_context.strip())
        if not duplicate:
            return "\n".join(parts)

        message = duplicate["message"]
        quoted = (message.text or "").strip().replace("\n", " ")
        quoted = quoted[:220]
        speaker_name = message.speaker_name or message.speaker_account_id or "участник"
        if session.topic.strip():
            parts.append(f"Держись темы разговора: {session.topic.strip()}")
        parts.append(f"Антидубль: не повторяй недавнюю реплику {speaker_name}: {quoted}")
        parts.append(
            "Сформулируй следующую мысль по-другому: новый угол, другие слова, без близкого перефраза."
        )
        return "\n".join(parts)

    def _build_retry_context(
        self,
        session: GroupSessionRecord,
        duplicate: dict[str, Any] | None,
        base_context: str = "",
    ) -> str:
        parts: list[str] = []
        if base_context.strip():
            parts.append(base_context.strip())
        if not duplicate:
            return "\n".join(parts)

        message = duplicate["message"]
        quoted = (message.text or "").strip().replace("\n", " ")
        quoted = quoted[:220]
        speaker_name = message.speaker_name or message.speaker_account_id or "участник"
        if session.topic.strip():
            parts.append(f"Держись темы разговора: {session.topic.strip()}")
        parts.append(f"Антидубль: не повторяй недавнюю реплику {speaker_name}: {quoted}")
        if duplicate.get("shared_phrase"):
            parts.append(f"Не повторяй оборот или аналогию: {duplicate['shared_phrase']}")
        parts.append(
            "Не повторяй тот же тезис, сравнение, шутку или вывод даже другими словами."
        )
        parts.append(
            "Сделай следующую реплику с новым углом: другой аргумент, вопрос, уточнение, пример или смена фокуса."
        )
        return "\n".join(parts)

    async def _generate_unique_group_message(
        self,
        llm: Any,
        session: GroupSessionRecord,
        speaker: str,
        short_reply: bool,
        extra_context: str = "",
        transcript_limit: int | None = None,
    ) -> str:
        retries = max(0, int(self.settings.dedupe_retry_attempts or 0))
        retry_context = extra_context.strip()

        for attempt in range(retries + 1):
            text = await llm.generate_group_message(
                role_prompt=session.role_prompts.get(speaker, ""),
                topic=session.topic,
                transcript=self._build_transcript(session, limit=transcript_limit),
                speaker_label=self._speaker_label(session, speaker),
                participants=self._participants_labels(session),
                language=self.settings.language,
                extra_context=retry_context,
                short_reply=short_reply,
                temperature=self.settings.temperature,
                max_tokens=self.settings.max_tokens,
            )
            text = (text or "").strip()
            if not text:
                return ""

            duplicate = self._find_recent_duplicate(session, text)
            if not duplicate:
                return text

            reason = "дословный повтор"
            if duplicate["reason"] == "similar":
                reason = f"слишком похоже ({duplicate['similarity']:.2f})"
            self.log(
                f"↻ {self._display_names.get(speaker, speaker)}: антидубль, "
                f"попытка {attempt + 1}/{retries + 1} ({reason})"
            )
            if attempt >= retries:
                self.log(
                    f"■ {self._display_names.get(speaker, speaker)}: реплика отброшена антидублем"
                )
                return ""
            retry_context = self._build_retry_context_v2(session, duplicate, extra_context)

        return ""

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
            duplicate = self._find_recent_duplicate(session, part)
            if duplicate:
                similarity = float(duplicate.get("similarity") or 0.0)
                reason = "дословный повтор"
                if duplicate.get("reason") == "similar":
                    reason = f"слишком похоже ({similarity:.2f})"
                self.log(
                    f"■ {self._display_names.get(speaker, speaker)}: часть сообщения пропущена антидублем ({reason})"
                )
                continue
            typing_sec = self._typing_seconds_for_session(session, part)
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
                pause = self._within_burst_delay(session)
                if await self._sleep_interruptible(pause):
                    break
        if sent_any:
            self._account_resume_pending[speaker] = False
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
        eligible = [
            account_id
            for account_id in session.account_ids
            if account_id in self._clients
            and self._account_online.get(account_id, True)
            and self._quota_ok(session, account_id)
        ]
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
            last_speaker = self._last_speakers[-1] if self._last_speakers else ""
            if last_speaker and aid in self._friendships.get(last_speaker, set()):
                w *= 1.35
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

    def _debug_fast_mode_enabled(self, session: GroupSessionRecord | None) -> bool:
        return bool(session and session.debug_fast_mode)

    def _typing_seconds_for_session(self, session: GroupSessionRecord | None, text: str) -> float:
        if self._debug_fast_mode_enabled(session):
            sec = 0.35 + len(text) * 0.01
            return max(0.35, min(1.5, sec))
        return self._typing_seconds(text)

    def _between_speakers_delay(self, session: GroupSessionRecord | None) -> float:
        if self._debug_fast_mode_enabled(session):
            return random.uniform(5.0, 10.0)
        return random.uniform(
            self.settings.delay_between_speakers_min_sec,
            self.settings.delay_between_speakers_max_sec,
        )

    def _within_burst_delay(self, session: GroupSessionRecord | None) -> float:
        if self._debug_fast_mode_enabled(session):
            return random.uniform(5.0, 10.0)
        return random.uniform(
            self.settings.delay_within_burst_min_sec,
            self.settings.delay_within_burst_max_sec,
        )

    def _external_reply_cooldown(self, session: GroupSessionRecord | None) -> float:
        if self._debug_fast_mode_enabled(session):
            return random.uniform(5.0, 10.0)
        return random.uniform(
            self.settings.reply_to_humans_cooldown_min_sec,
            max(
                self.settings.reply_to_humans_cooldown_min_sec,
                self.settings.reply_to_humans_cooldown_max_sec,
            ),
        )

    async def _sleep_interruptible(self, seconds: float) -> bool:
        """True если остановлены."""
        end = asyncio.get_event_loop().time() + max(0.0, seconds)
        while asyncio.get_event_loop().time() < end:
            if self._stop.is_set():
                return True
            await asyncio.sleep(min(1.0, end - asyncio.get_event_loop().time()))
        return self._stop.is_set()

    async def _sync_history(
        self,
        session: GroupSessionRecord,
        client: TelegramAccountClient,
        limit: int | None = None,
    ) -> None:
        try:
            history = await client.get_chat_history(
                session.chat_id,
                limit=max(1, int(limit or self.settings.history_limit)),
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
        account_schedules: dict[str, list[dict[str, Any]]] | None = None,
        friendships: dict[str, list[str]] | None = None,
        reset_context_on_apply: bool = False,
        extra_context: str = "",
        debug_fast_mode: bool = False,
        chat_title: str = "",
    ) -> None:
        self.reset_stop()
        self.settings = GroupChatSettings.load(self._settings_path())
        self.state.load()
        self._pending_external_replies = []
        self._handled_external_msg_ids = set()
        self._next_external_reply_after = 0.0
        self._account_online = {}
        self._account_resume_pending = {}
        self._friendships = {}
        self._scene_revision_seen = 0
        self._history_refresh_required = False
        roles = RolesConfig.load(self.base_dir / self.config.roles_file)
        role_overrides = role_overrides or {}
        activity_weights = activity_weights or {}
        account_schedules = account_schedules or {}
        friendships = friendships or {}

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
            account_schedules=account_schedules,
            friendships=friendships,
            reset_context_on_apply=bool(reset_context_on_apply),
            debug_fast_mode=bool(debug_fast_mode),
            scene_revision=1,
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
            session = await self._refresh_account_presence(session, primary)
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
                session = await self._refresh_account_presence(session, primary)
                self._ensure_day_counters(session)

                now_mono = asyncio.get_event_loop().time()
                if self._history_refresh_required:
                    history_limit = max(
                        int(self.settings.history_limit),
                        int(self.settings.reconnect_history_limit),
                    )
                    await self._sync_history(session, primary, limit=history_limit)
                    self._history_refresh_required = False
                    last_sync = now_mono
                    session = self.state.group_session or session
                    session = self._apply_runtime_session(session)
                    session = await self._refresh_account_presence(session, primary)
                    if self._stop.is_set():
                        break
                if now_mono - last_sync >= self.settings.sync_history_every_sec:
                    await self._sync_history(session, primary)
                    last_sync = now_mono
                    session = self.state.group_session or session
                    session = self._apply_runtime_session(session)
                    session = await self._refresh_account_presence(session, primary)
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
                    resume_limit = max(
                        self.settings.history_limit,
                        self.settings.reconnect_history_limit,
                    )
                    transcript_limit = (
                        resume_limit if self._account_resume_pending.get(speaker) else None
                    )
                    context_parts = [
                        self._compose_speaker_context(
                            session,
                            speaker,
                            session.extra_context,
                        )
                    ]
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
                        text = await self._generate_unique_group_message(
                            llm,
                            session,
                            speaker,
                            True,
                            "\n".join(part for part in context_parts if part),
                            transcript_limit=transcript_limit,
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
                        cooldown = self._external_reply_cooldown(session)
                        self._next_external_reply_after = asyncio.get_event_loop().time() + cooldown
                    else:
                        if await self._sleep_interruptible(10):
                            break
                    continue

                if not self._debug_fast_mode_enabled(session) and random.random() < self.settings.quiet_break_chance:
                    mins = random.randint(
                        self.settings.quiet_break_min_min,
                        max(self.settings.quiet_break_min_min, self.settings.quiet_break_max_min),
                    )
                    self._in_quiet_until = now_mono + mins * 60
                    self.log(f"⏸ Тихая пауза {mins} мин")
                    continue

                if not self._debug_fast_mode_enabled(session) and random.random() > self.settings.online_probability:
                    self.stats.status_text = "ожидание (вероятность онлайна)"
                    self._emit()
                    if await self._sleep_interruptible(random.uniform(20, 60)):
                        break
                    continue

                speaker = self._pick_speaker(session)
                if not speaker:
                    self.stats.status_text = "нет доступных участников"
                    self._emit()
                    self.log("■ Сейчас нет доступных участников")
                    break

                client = self._clients.get(speaker)
                if not client:
                    continue

                if not self._debug_fast_mode_enabled(session) and random.random() < self.settings.read_and_wait_chance:
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
                    resume_limit = max(
                        self.settings.history_limit,
                        self.settings.reconnect_history_limit,
                    )
                    transcript_limit = (
                        resume_limit if self._account_resume_pending.get(speaker) else None
                    )
                    reply_target = self._pick_reply_target(session, speaker)
                    speaker_context = self._compose_speaker_context(
                        session,
                        speaker,
                        session.extra_context,
                        reply_target=reply_target,
                    )
                    reply_context = self._reply_target_context(session, reply_target)
                    if reply_context:
                        speaker_context = "\n".join(
                            part for part in (speaker_context, reply_context) if part
                        )
                    text = await self._generate_unique_group_message(
                        llm,
                        session,
                        speaker,
                        short,
                        speaker_context,
                        transcript_limit=transcript_limit,
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
                reply_to_msg_id = None
                reply_to_speaker_account_id = ""
                reply_to_external = False
                if reply_target:
                    reply_msg_id = int(reply_target.get("msg_id") or 0)
                    reply_to_msg_id = reply_msg_id or None
                    reply_to_speaker_account_id = str(
                        reply_target.get("speaker_account_id") or ""
                    )
                    reply_to_external = bool(reply_target.get("external", False))

                session, _sent = await self._send_generated_parts(
                    session,
                    speaker,
                    client,
                    parts,
                    reply_to_msg_id=reply_to_msg_id,
                    reply_to_speaker_account_id=reply_to_speaker_account_id,
                    reply_to_external=reply_to_external,
                )

                between = self._between_speakers_delay(session)
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
