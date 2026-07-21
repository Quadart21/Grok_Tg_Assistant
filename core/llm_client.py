from __future__ import annotations

import httpx

from core.dialog_settings import DialogSettings
from core.llm_providers import chat_completions_url, provider_info
from core.master_prompt import MasterPromptConfig
from core.state_store import ChatMessage


class LLMClient:
    """Генерация текста через Grok, OpenAI, Gemini, Claude, DeepSeek, OpenRouter, Local."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        settings: DialogSettings | None = None,
        master_prompt: MasterPromptConfig | None = None,
        base_url: str = "",
    ) -> None:
        self.provider = provider
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or provider_info(provider).default_model
        self.settings = settings or DialogSettings()
        self.master = master_prompt or MasterPromptConfig()
        self._info = provider_info(provider)
        self.base_url = (base_url or "").strip()

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

    async def generate_group_message(
        self,
        role_prompt: str,
        topic: str,
        transcript: list[dict],
        speaker_label: str,
        participants: list[str],
        language: str = "ru",
        extra_context: str = "",
        short_reply: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Реплика аккаунта в общем чате по теме и роли."""
        extra = self._build_extra(extra_context)
        style_hint = (
            "Напиши короткую реплику (1 фраза или 1–2 коротких предложения)."
            if short_reply
            else "Напиши естественную реплику средней длины, как в живом чате."
        )
        others = ", ".join(p for p in participants if p != speaker_label) or "другие участники"
        system = (
            f"{self._layered_prompt(role_prompt, 'Роль в чате')}\n\n"
            "Режим: вы участник группового Telegram-чата. Пишете от своего имени.\n"
            "Правила:\n"
            "- Не упоминайте, что вы бот, ИИ, скрипт или автоматизация.\n"
            "- Не копируйте чужие формулировки дословно.\n"
            "- Не повторяйте ту же мысль, аналогию, шутку или вывод даже в перефразе.\n"
            "- Если похожая мысль уже прозвучала, выбирайте новый угол: вопрос, пример, возражение, уточнение или следующий шаг разговора.\n"
            "- Учитывайте тему и последние сообщения.\n"
            "- Можно соглашаться, спорить мягко, шутить, задавать вопросы — по роли.\n"
            "- Не здоровайтесь заново, если диалог уже идёт.\n"
            "- Только текст одного сообщения, без кавычек и пояснений.\n"
            f"- {style_hint}"
        )
        if topic.strip():
            system += f"\n\nТема разговора: {topic.strip()}"
        if extra:
            system += f"\n\n{extra}"

        limit = self.settings.history_for_grok
        lines: list[str] = []
        for item in transcript[-limit:]:
            name = item.get("speaker_name") or item.get("speaker") or "?"
            text = (item.get("text") or item.get("content") or "").strip()
            if text:
                lines.append(f"{name}: {text}")
        history_block = "\n".join(lines) if lines else "(чат пока пустой или тихий)"

        user = (
            f"Вы пишете как: {speaker_label}\n"
            f"Другие «свои» участники сценария: {others}\n"
            f"Язык: {language}\n\n"
            f"Последние сообщения чата:\n{history_block}\n\n"
            "Напишите следующую реплику от своего имени."
        )
        return await self._complete(
            system,
            [{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _complete(
        self,
        system: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError(f"Не указан API-ключ для {self._info.name}")
        temp = self.settings.grok_temperature if temperature is None else temperature
        tokens = self.settings.grok_max_tokens if max_tokens is None else max_tokens
        if self._info.api_style == "anthropic":
            return await self._complete_anthropic(system, messages, temp, tokens)
        return await self._complete_openai(system, messages, temp, tokens)

    async def _complete_openai(
        self, system: str, messages: list[dict], temperature: float, max_tokens: int
    ) -> str:
        url = chat_completions_url(self.provider, self.base_url)
        if not url:
            raise RuntimeError(
                f"Провайдер {self.provider} не поддерживается"
                + (" — укажите Local Base URL" if self.provider == "local" else "")
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "http://127.0.0.1:8787"
            headers["X-Title"] = "tg-grok-outreach"

        timeout = 300.0 if self.provider == "local" else 90.0
        payload_messages = [{"role": "system", "content": system}, *messages]
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": payload_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            if response.status_code >= 400:
                detail = response.text[:300]
                raise RuntimeError(f"{self._info.name}: {response.status_code} — {detail}")
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return self._strip_quotes(content)

    async def _complete_anthropic(
        self, system: str, messages: list[dict], temperature: float, max_tokens: int
    ) -> str:
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
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": anthropic_messages,
                    "temperature": temperature,
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
        base_url=getattr(config, "local_base_url", "") or "",
    )
