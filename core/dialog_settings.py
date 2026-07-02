from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DialogSettings:
    """Глобальные настройки поведения переписок."""

    history_for_grok: int = 40
    max_stored_messages: int = 150
    grok_temperature: float = 0.8
    grok_max_tokens: int = 400
    reply_delay_min_sec: int = 5
    reply_delay_max_sec: int = 25
    typing_delay_sec: int = 2
    batch_messages_sec: int = 8
    min_user_message_chars: int = 1
    ignore_keywords: list[str] = field(default_factory=lambda: ["стоп", "stop", "не пиши", "отстань"])
    global_extra_prompt: str = ""
    max_replies_per_dialog: int = 0
    max_replies_per_hour: int = 30
    split_long_messages: bool = False
    split_at_chars: int = 350
    sync_history_on_resume: bool = True
    sync_history_limit: int = 50
    first_message_max_chars: int = 500

    @classmethod
    def load(cls, path: Path) -> DialogSettings:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        ignore = data.get("ignore_keywords", [])
        if isinstance(ignore, str):
            ignore = [x.strip() for x in ignore.split(",") if x.strip()]
        return cls(
            history_for_grok=int(data.get("history_for_grok", 40)),
            max_stored_messages=int(data.get("max_stored_messages", 150)),
            grok_temperature=float(data.get("grok_temperature", 0.8)),
            grok_max_tokens=int(data.get("grok_max_tokens", 400)),
            reply_delay_min_sec=int(data.get("reply_delay_min_sec", 5)),
            reply_delay_max_sec=int(data.get("reply_delay_max_sec", 25)),
            typing_delay_sec=int(data.get("typing_delay_sec", 2)),
            batch_messages_sec=int(data.get("batch_messages_sec", 8)),
            min_user_message_chars=int(data.get("min_user_message_chars", 1)),
            ignore_keywords=list(ignore),
            global_extra_prompt=str(data.get("global_extra_prompt", "")),
            max_replies_per_dialog=int(data.get("max_replies_per_dialog", 0)),
            max_replies_per_hour=int(data.get("max_replies_per_hour", 30)),
            split_long_messages=bool(data.get("split_long_messages", False)),
            split_at_chars=int(data.get("split_at_chars", 350)),
            sync_history_on_resume=bool(data.get("sync_history_on_resume", True)),
            sync_history_limit=int(data.get("sync_history_limit", 50)),
            first_message_max_chars=int(data.get("first_message_max_chars", 500)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "history_for_grok": self.history_for_grok,
                    "max_stored_messages": self.max_stored_messages,
                    "grok_temperature": self.grok_temperature,
                    "grok_max_tokens": self.grok_max_tokens,
                    "reply_delay_min_sec": self.reply_delay_min_sec,
                    "reply_delay_max_sec": self.reply_delay_max_sec,
                    "typing_delay_sec": self.typing_delay_sec,
                    "batch_messages_sec": self.batch_messages_sec,
                    "min_user_message_chars": self.min_user_message_chars,
                    "ignore_keywords": self.ignore_keywords,
                    "global_extra_prompt": self.global_extra_prompt,
                    "max_replies_per_dialog": self.max_replies_per_dialog,
                    "max_replies_per_hour": self.max_replies_per_hour,
                    "split_long_messages": self.split_long_messages,
                    "split_at_chars": self.split_at_chars,
                    "sync_history_on_resume": self.sync_history_on_resume,
                    "sync_history_limit": self.sync_history_limit,
                    "first_message_max_chars": self.first_message_max_chars,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "history_for_grok": self.history_for_grok,
            "max_stored_messages": self.max_stored_messages,
            "grok_temperature": self.grok_temperature,
            "grok_max_tokens": self.grok_max_tokens,
            "reply_delay_min_sec": self.reply_delay_min_sec,
            "reply_delay_max_sec": self.reply_delay_max_sec,
            "typing_delay_sec": self.typing_delay_sec,
            "batch_messages_sec": self.batch_messages_sec,
            "min_user_message_chars": self.min_user_message_chars,
            "ignore_keywords": self.ignore_keywords,
            "global_extra_prompt": self.global_extra_prompt,
            "max_replies_per_dialog": self.max_replies_per_dialog,
            "max_replies_per_hour": self.max_replies_per_hour,
            "split_long_messages": self.split_long_messages,
            "split_at_chars": self.split_at_chars,
            "sync_history_on_resume": self.sync_history_on_resume,
            "sync_history_limit": self.sync_history_limit,
            "first_message_max_chars": self.first_message_max_chars,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DialogSettings:
        ignore = data.get("ignore_keywords", [])
        if isinstance(ignore, str):
            ignore = [x.strip() for x in ignore.split(",") if x.strip()]
        return cls(
            history_for_grok=int(data.get("history_for_grok", 40)),
            max_stored_messages=int(data.get("max_stored_messages", 150)),
            grok_temperature=float(data.get("grok_temperature", 0.8)),
            grok_max_tokens=int(data.get("grok_max_tokens", 400)),
            reply_delay_min_sec=int(data.get("reply_delay_min_sec", 5)),
            reply_delay_max_sec=int(data.get("reply_delay_max_sec", 25)),
            typing_delay_sec=int(data.get("typing_delay_sec", 2)),
            batch_messages_sec=int(data.get("batch_messages_sec", 8)),
            min_user_message_chars=int(data.get("min_user_message_chars", 1)),
            ignore_keywords=list(ignore),
            global_extra_prompt=str(data.get("global_extra_prompt", "")),
            max_replies_per_dialog=int(data.get("max_replies_per_dialog", 0)),
            max_replies_per_hour=int(data.get("max_replies_per_hour", 30)),
            split_long_messages=bool(data.get("split_long_messages", False)),
            split_at_chars=int(data.get("split_at_chars", 350)),
            sync_history_on_resume=bool(data.get("sync_history_on_resume", True)),
            sync_history_limit=int(data.get("sync_history_limit", 50)),
            first_message_max_chars=int(data.get("first_message_max_chars", 500)),
        )

    def should_ignore_message(self, text: str) -> bool:
        low = text.lower().strip()
        if len(low) < self.min_user_message_chars:
            return True
        return any(kw.lower() in low for kw in self.ignore_keywords if kw.strip())
