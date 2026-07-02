from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MASTER_PROMPT = (
    "Главные правила для всех сообщений и диалогов:\n"
    "- Пиши естественно, как живой человек в Telegram.\n"
    "- Не упоминай, что ты бот, нейросеть или ИИ.\n"
    "- Будь вежливым и по делу.\n"
    "- Следуй роли и инструкциям ниже — они уточняют поведение поверх этих правил."
)


@dataclass
class MasterPromptConfig:
    enabled: bool = True
    text: str = DEFAULT_MASTER_PROMPT

    @classmethod
    def load(cls, path: Path) -> MasterPromptConfig:
        if not path.exists():
            example = path.parent / "master_prompt.example.json"
            if example.exists():
                return cls.from_dict(json.loads(example.read_text(encoding="utf-8")))
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MasterPromptConfig:
        return cls(
            enabled=bool(data.get("enabled", True)),
            text=str(data.get("text") or DEFAULT_MASTER_PROMPT),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"enabled": self.enabled, "text": self.text},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "text": self.text}

    def compose_with_layer(self, layer_prompt: str, layer_label: str = "Роль") -> str:
        parts: list[str] = []
        if self.enabled and self.text.strip():
            parts.append(
                "=== МАСТЕР-ПРОМПТ (главный, базовые правила для всего) ===\n"
                f"{self.text.strip()}"
            )
        layer = layer_prompt.strip()
        if layer:
            parts.append(
                f"=== {layer_label.upper()} (накладывается поверх мастера) ===\n"
                f"{layer}"
            )
        return "\n\n".join(parts)
