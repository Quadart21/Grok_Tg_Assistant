from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.json_store import read_json, write_json_atomic


@dataclass
class ActivityWindow:
    """Окно активности в локальном времени: дни 0=Пн … 6=Вс, время HH:MM."""

    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    start: str = "10:00"
    end: str = "23:00"

    def to_dict(self) -> dict[str, Any]:
        return {"days": list(self.days), "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActivityWindow:
        days = data.get("days", [0, 1, 2, 3, 4])
        return cls(
            days=[int(d) for d in days],
            start=str(data.get("start", "10:00")),
            end=str(data.get("end", "23:00")),
        )


@dataclass
class GroupChatSettings:
    """Настройки живой групповой переписки между своими аккаунтами."""

    # Расписание
    use_schedule: bool = True
    timezone_offset_hours: float | None = None  # None = локальное время ПК
    activity_windows: list[ActivityWindow] = field(
        default_factory=lambda: [
            ActivityWindow(days=[0, 1, 2, 3, 4], start="10:00", end="14:00"),
            ActivityWindow(days=[0, 1, 2, 3, 4], start="18:00", end="23:00"),
            ActivityWindow(days=[5, 6], start="12:00", end="22:00"),
        ]
    )
    online_probability: float = 0.55  # шанс «выйти в онлайн» при проверке окна
    quiet_break_min_min: int = 15
    quiet_break_max_min: int = 90
    quiet_break_chance: float = 0.12
    resume_next_day: bool = True

    # Квоты
    max_messages_per_account_session: int = 40
    max_messages_per_account_hour: int = 12
    max_messages_per_account_day: int = 30
    max_messages_group_day: int = 80
    burst_min: int = 1
    burst_max: int = 3
    max_consecutive_same_speaker: int = 3

    # Тайминги
    delay_between_speakers_min_sec: int = 25
    delay_between_speakers_max_sec: int = 120
    delay_within_burst_min_sec: int = 3
    delay_within_burst_max_sec: int = 12
    typing_base_sec: float = 1.5
    typing_per_char_sec: float = 0.04
    typing_max_sec: float = 8.0
    read_and_wait_chance: float = 0.25
    read_and_wait_min_sec: int = 20
    read_and_wait_max_sec: int = 90
    short_reply_chance: float = 0.35
    reply_to_humans_enabled: bool = True
    reply_to_humans_only_on_quote: bool = True
    reply_to_humans_chance: float = 0.85
    reply_to_humans_cooldown_min_sec: int = 45
    reply_to_humans_cooldown_max_sec: int = 150
    split_long_messages: bool = True
    split_at_chars: int = 280
    split_parts_max: int = 3
    dedupe_recent_messages_window: int = 16
    dedupe_similarity_threshold: float = 0.9
    dedupe_retry_attempts: int = 3

    # Контент / LLM
    language: str = "ru"
    history_limit: int = 40
    temperature: float = 0.9
    max_tokens: int = 250
    reply_style: str = "mixed"  # short | medium | mixed
    stop_keywords: list[str] = field(default_factory=lambda: ["стоп боты", "stop bots"])

    # Периодичность опроса чужих сообщений
    sync_history_every_sec: int = 45

    @classmethod
    def load(cls, path: Path) -> GroupChatSettings:
        if not path.exists():
            return cls()
        data = read_json(path, {})
        return cls.from_dict(data)

    def save(self, path: Path) -> None:
        write_json_atomic(path, self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "use_schedule": self.use_schedule,
            "timezone_offset_hours": self.timezone_offset_hours,
            "activity_windows": [w.to_dict() for w in self.activity_windows],
            "online_probability": self.online_probability,
            "quiet_break_min_min": self.quiet_break_min_min,
            "quiet_break_max_min": self.quiet_break_max_min,
            "quiet_break_chance": self.quiet_break_chance,
            "resume_next_day": self.resume_next_day,
            "max_messages_per_account_session": self.max_messages_per_account_session,
            "max_messages_per_account_hour": self.max_messages_per_account_hour,
            "max_messages_per_account_day": self.max_messages_per_account_day,
            "max_messages_group_day": self.max_messages_group_day,
            "burst_min": self.burst_min,
            "burst_max": self.burst_max,
            "max_consecutive_same_speaker": self.max_consecutive_same_speaker,
            "delay_between_speakers_min_sec": self.delay_between_speakers_min_sec,
            "delay_between_speakers_max_sec": self.delay_between_speakers_max_sec,
            "delay_within_burst_min_sec": self.delay_within_burst_min_sec,
            "delay_within_burst_max_sec": self.delay_within_burst_max_sec,
            "typing_base_sec": self.typing_base_sec,
            "typing_per_char_sec": self.typing_per_char_sec,
            "typing_max_sec": self.typing_max_sec,
            "read_and_wait_chance": self.read_and_wait_chance,
            "read_and_wait_min_sec": self.read_and_wait_min_sec,
            "read_and_wait_max_sec": self.read_and_wait_max_sec,
            "short_reply_chance": self.short_reply_chance,
            "reply_to_humans_enabled": self.reply_to_humans_enabled,
            "reply_to_humans_only_on_quote": self.reply_to_humans_only_on_quote,
            "reply_to_humans_chance": self.reply_to_humans_chance,
            "reply_to_humans_cooldown_min_sec": self.reply_to_humans_cooldown_min_sec,
            "reply_to_humans_cooldown_max_sec": self.reply_to_humans_cooldown_max_sec,
            "split_long_messages": self.split_long_messages,
            "split_at_chars": self.split_at_chars,
            "split_parts_max": self.split_parts_max,
            "dedupe_recent_messages_window": self.dedupe_recent_messages_window,
            "dedupe_similarity_threshold": self.dedupe_similarity_threshold,
            "dedupe_retry_attempts": self.dedupe_retry_attempts,
            "language": self.language,
            "history_limit": self.history_limit,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reply_style": self.reply_style,
            "stop_keywords": list(self.stop_keywords),
            "sync_history_every_sec": self.sync_history_every_sec,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupChatSettings:
        windows_raw = data.get("activity_windows")
        if isinstance(windows_raw, list) and windows_raw:
            windows = [ActivityWindow.from_dict(w) for w in windows_raw if isinstance(w, dict)]
        else:
            windows = cls().activity_windows
        stop = data.get("stop_keywords", ["стоп боты", "stop bots"])
        if isinstance(stop, str):
            stop = [x.strip() for x in stop.split(",") if x.strip()]
        tz = data.get("timezone_offset_hours", None)
        return cls(
            use_schedule=bool(data.get("use_schedule", True)),
            timezone_offset_hours=None if tz is None or tz == "" else float(tz),
            activity_windows=windows,
            online_probability=float(data.get("online_probability", 0.55)),
            quiet_break_min_min=int(data.get("quiet_break_min_min", 15)),
            quiet_break_max_min=int(data.get("quiet_break_max_min", 90)),
            quiet_break_chance=float(data.get("quiet_break_chance", 0.12)),
            resume_next_day=bool(data.get("resume_next_day", True)),
            max_messages_per_account_session=int(data.get("max_messages_per_account_session", 40)),
            max_messages_per_account_hour=int(data.get("max_messages_per_account_hour", 12)),
            max_messages_per_account_day=int(data.get("max_messages_per_account_day", 30)),
            max_messages_group_day=int(data.get("max_messages_group_day", 80)),
            burst_min=int(data.get("burst_min", 1)),
            burst_max=int(data.get("burst_max", 3)),
            max_consecutive_same_speaker=int(data.get("max_consecutive_same_speaker", 3)),
            delay_between_speakers_min_sec=int(data.get("delay_between_speakers_min_sec", 25)),
            delay_between_speakers_max_sec=int(data.get("delay_between_speakers_max_sec", 120)),
            delay_within_burst_min_sec=int(data.get("delay_within_burst_min_sec", 3)),
            delay_within_burst_max_sec=int(data.get("delay_within_burst_max_sec", 12)),
            typing_base_sec=float(data.get("typing_base_sec", 1.5)),
            typing_per_char_sec=float(data.get("typing_per_char_sec", 0.04)),
            typing_max_sec=float(data.get("typing_max_sec", 8.0)),
            read_and_wait_chance=float(data.get("read_and_wait_chance", 0.25)),
            read_and_wait_min_sec=int(data.get("read_and_wait_min_sec", 20)),
            read_and_wait_max_sec=int(data.get("read_and_wait_max_sec", 90)),
            short_reply_chance=float(data.get("short_reply_chance", 0.35)),
            reply_to_humans_enabled=bool(data.get("reply_to_humans_enabled", True)),
            reply_to_humans_only_on_quote=bool(data.get("reply_to_humans_only_on_quote", True)),
            reply_to_humans_chance=float(data.get("reply_to_humans_chance", 0.85)),
            reply_to_humans_cooldown_min_sec=int(data.get("reply_to_humans_cooldown_min_sec", 45)),
            reply_to_humans_cooldown_max_sec=int(data.get("reply_to_humans_cooldown_max_sec", 150)),
            split_long_messages=bool(data.get("split_long_messages", True)),
            split_at_chars=int(data.get("split_at_chars", 280)),
            split_parts_max=int(data.get("split_parts_max", 3)),
            dedupe_recent_messages_window=int(data.get("dedupe_recent_messages_window", 16)),
            dedupe_similarity_threshold=float(data.get("dedupe_similarity_threshold", 0.9)),
            dedupe_retry_attempts=int(data.get("dedupe_retry_attempts", 3)),
            language=str(data.get("language", "ru")),
            history_limit=int(data.get("history_limit", 40)),
            temperature=float(data.get("temperature", 0.9)),
            max_tokens=int(data.get("max_tokens", 250)),
            reply_style=str(data.get("reply_style", "mixed")),
            stop_keywords=list(stop),
            sync_history_every_sec=int(data.get("sync_history_every_sec", 45)),
        )
