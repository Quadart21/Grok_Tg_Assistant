from __future__ import annotations

import httpx

from core.dialog_settings import DialogSettings
from core.llm_providers import OPENAI_COMPAT_URLS, provider_info
from core.master_prompt import MasterPromptConfig
from core.state_store import ChatMessage


class LLMClient:
    """Генерация текста через Grok, OpenAI, Gemini, Claude, DeepSeek, OpenRouter."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        settings: DialogSettings | None = None,
        master_prompt: MasterPromptConfig | None = None,
    ) -> None:
        self.provider = provider
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or provider_info(provider).default_model
        self.settings = settings or DialogSettings()
        self.master = master_prompt or MasterPromptConfig()
        self._info = provider_info(provider)

    @property
    def provider_name(self) -> str:
        return self._info.name

    def _layered_prompt(self, layer_prompt: str, layer_label: str = "Роль") -> str:
        return self.master.compose_with_layer(layer_prompt, layer_label)

    def _build_extra(self, extra_context: str, goal: str = "") -> str:
        parts = []
        if self.settings.global_extra_prompt.strip():
            parts.append(self.settings.global_extra_prompt.strip())
        if goal.strip():
            parts.append(f"Цель переписки: {goal.strip()}")
        if extra_context.strip():
            parts.append(extra_context.strip())
        return "\n".join(parts)

    async def generate_first_message(
        self,
        role_prompt: str,
        target_username: str,
        language: str = "ru",
        extra_context: str = "",
        goal: str = "",
    ) -> str:
        extra = self._build_extra(extra_context, goal)
        system = (
            f"{self._layered_prompt(role_prompt, 'Стиль аккаунта')}\n\n"
            "Задача: написать ПЕРВОЕ сообщение пользователю в Telegram, с которым ещё не было переписки. "
            "Не упоминай, что вы бот или ИИ. Только текст сообщения, без кавычек и пояснений."
        )
        if self.settings.first_message_max_chars:
            system += f"\nДлина: не более {self.settings.first_message_max_chars} символов."
        user = (
            f"Получатель: @{target_username.lstrip('@')}\n"
            f"Язык сообщения: {language}\n"
        )
        if extra:
            user += f"Контекст:\n{extra}\n"
        return await self._complete(system, [{"role": "user", "content": user}])

    async def generate_reply(
        self,
        role_prompt: str,
        target_username: str,
        history: list[ChatMessage],
        language: str = "ru",
        extra_context: str = "",
        goal: str = "",
    ) -> str:
        extra = self._build_extra(extra_context, goal)
        system = (
            f"{self._layered_prompt(role_prompt, 'Стиль аккаунта')}\n\n"
            "Вы ведёте переписку в Telegram от своего имени. "
            "Отвечайте естественно, по контексту диалога. "
            "Не упоминайте, что вы бот или ИИ. "
            "Только текст ответа, без кавычек и пояснений."
        )
        if extra:
            system += f"\n\n{extra}"

        limit = self.settings.history_for_grok
        messages = [{"role": "user", "content": f"Собеседник: @{target_username.lstrip('@')}, язык: {language}"}]
        for item in history[-limit:]:
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({"role": role, "content": item.content})
        messages.append({"role": "user", "content": "Напиши следующий ответ собеседнику."})
        return await self._complete(system, messages)

    async def generate_agent_dialog_reply(
        self,
        agent_prompt: str,
        contact_label: str,
        history: list[ChatMessage],
        language: str = "ru",
        extra_context: str = "",
        goal: str = "",
        agent_name: str = "Секретарь",
    ) -> str:
        extra = self._build_extra(extra_context, goal)
        system = (
            f"{self._layered_prompt(agent_prompt, f'Агент: {agent_name}')}\n\n"
            f"Режим: живой диалог в Telegram от имени владельца аккаунта.\n"
            "Это продолжение переписки, а не разовый автоответ.\n"
            "Правила:\n"
            "- Опирайтесь на всю историю сообщений ниже.\n"
            "- Мастер-промпт и роль агента действуют вместе: сначала общие правила, затем роль.\n"
            "- Отвечайте естественно: можно уточнять, задавать вопросы, развивать тему.\n"
            "- Не начинайте снова с приветствия, если диалог уже идёт.\n"
            "- Не повторяйте дословно то, что уже говорили.\n"
            "- Не упоминайте, что вы бот или ИИ.\n"
            "- Только текст следующего сообщения, без кавычек и пояснений."
        )
        if extra:
            system += f"\n\n{extra}"

        contact = contact_label.lstrip("@")
        limit = self.settings.history_for_grok
        trimmed = history[-limit:]
        messages: list[dict] = []
        if trimmed:
            messages.append(
                {
                    "role": "user",
                    "content": f"Диалог с @{contact}. Язык общения: {language}. История переписки:",
                }
            )
            for item in trimmed:
                role = "assistant" if item.role == "assistant" else "user"
                messages.append({"role": role, "content": item.content})
        else:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Собеседник @{contact} написал первым. Язык: {language}. "
                        "Начни диалог по своей роли — ответь на его сообщение."
                    ),
                }
            )
        return await self._complete(system, messages)

    async def _complete(self, system: str, messages: list[dict]) -> str:
        if not self.api_key:
            raise RuntimeError(f"Не указан API-ключ для {self._info.name}")
        if self._info.api_style == "anthropic":
            return await self._complete_anthropic(system, messages)
        return await self._complete_openai(system, messages)

    async def _complete_openai(self, system: str, messages: list[dict]) -> str:
        url = OPENAI_COMPAT_URLS.get(self.provider)
        if not url:
            raise RuntimeError(f"Провайдер {self.provider} не поддерживается")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "http://127.0.0.1:8787"
            headers["X-Title"] = "tg-grok-outreach"

        payload_messages = [{"role": "system", "content": system}, *messages]
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": payload_messages,
                    "temperature": self.settings.grok_temperature,
                    "max_tokens": self.settings.grok_max_tokens,
                },
            )
            if response.status_code >= 400:
                detail = response.text[:300]
                raise RuntimeError(f"{self._info.name}: {response.status_code} — {detail}")
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return self._strip_quotes(content)

    async def _complete_anthropic(self, system: str, messages: list[dict]) -> str:
        anthropic_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] in ("user", "assistant")
        ]
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.settings.grok_max_tokens,
                    "system": system,
                    "messages": anthropic_messages,
                    "temperature": self.settings.grok_temperature,
                },
            )
            if response.status_code >= 400:
                detail = response.text[:300]
                raise RuntimeError(f"{self._info.name}: {response.status_code} — {detail}")
            data = response.json()
            parts = data.get("content") or []
            text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            return self._strip_quotes(text)

    @staticmethod
    def _strip_quotes(content: str) -> str:
        if content.startswith('"') and content.endswith('"'):
            return content[1:-1]
        return content


def create_llm_client(
    config,
    settings: DialogSettings | None = None,
    master_prompt: MasterPromptConfig | None = None,
) -> LLMClient:
    return LLMClient(
        provider=config.llm_provider,
        api_key=config.get_llm_api_key(),
        model=config.get_llm_model(),
        settings=settings,
        master_prompt=master_prompt,
    )
