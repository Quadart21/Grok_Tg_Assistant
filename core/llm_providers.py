from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMProviderInfo:
    id: str
    name: str
    default_model: str
    models_hint: str
    docs_url: str
    key_field: str
    api_style: str  # openai | anthropic


LLM_PROVIDERS: dict[str, LLMProviderInfo] = {
    "grok": LLMProviderInfo(
        id="grok",
        name="Grok (xAI)",
        default_model="grok-3-mini",
        models_hint="grok-3-mini, grok-2-latest, grok-4",
        docs_url="https://console.x.ai/",
        key_field="grok_api_key",
        api_style="openai",
    ),
    "openai": LLMProviderInfo(
        id="openai",
        name="OpenAI",
        default_model="gpt-4o-mini",
        models_hint="gpt-4o-mini, gpt-4o, gpt-4.1-mini",
        docs_url="https://platform.openai.com/api-keys",
        key_field="openai_api_key",
        api_style="openai",
    ),
    "gemini": LLMProviderInfo(
        id="gemini",
        name="Google Gemini",
        default_model="gemini-2.0-flash",
        models_hint="gemini-2.0-flash, gemini-2.5-flash-preview, gemini-1.5-pro",
        docs_url="https://aistudio.google.com/apikey",
        key_field="gemini_api_key",
        api_style="openai",
    ),
    "anthropic": LLMProviderInfo(
        id="anthropic",
        name="Anthropic Claude",
        default_model="claude-3-5-haiku-latest",
        models_hint="claude-3-5-haiku-latest, claude-3-5-sonnet-latest, claude-sonnet-4-20250514",
        docs_url="https://console.anthropic.com/",
        key_field="anthropic_api_key",
        api_style="anthropic",
    ),
    "deepseek": LLMProviderInfo(
        id="deepseek",
        name="DeepSeek",
        default_model="deepseek-chat",
        models_hint="deepseek-chat, deepseek-reasoner",
        docs_url="https://platform.deepseek.com/",
        key_field="deepseek_api_key",
        api_style="openai",
    ),
    "openrouter": LLMProviderInfo(
        id="openrouter",
        name="OpenRouter",
        default_model="openai/gpt-4o-mini",
        models_hint="openai/gpt-4o-mini, anthropic/claude-3.5-haiku, google/gemini-2.0-flash",
        docs_url="https://openrouter.ai/keys",
        key_field="openrouter_api_key",
        api_style="openai",
    ),
}

OPENAI_COMPAT_URLS: dict[str, str] = {
    "grok": "https://api.x.ai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}

DEFAULT_PROVIDER = "grok"


def provider_info(provider_id: str) -> LLMProviderInfo:
    return LLM_PROVIDERS.get(provider_id, LLM_PROVIDERS[DEFAULT_PROVIDER])


def list_providers_dict() -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "default_model": p.default_model,
            "models_hint": p.models_hint,
            "docs_url": p.docs_url,
            "key_field": p.key_field,
        }
        for p in LLM_PROVIDERS.values()
    ]
