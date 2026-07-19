from __future__ import annotations

import httpx

from core.llm_providers import LLM_PROVIDERS, normalize_openai_base_url, provider_info

# Актуальные модели (fallback, если API недоступен или нет ключа)
STATIC_MODELS: dict[str, list[str]] = {
    "grok": [
        "grok-4",
        "grok-4-fast",
        "grok-4-fast-reasoning",
        "grok-4-reasoning",
        "grok-3",
        "grok-3-mini",
        "grok-3-fast",
        "grok-2-latest",
        "grok-2-vision-1212",
        "grok-beta",
    ],
    "openai": [
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4o-2024-11-20",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "o1",
        "o1-mini",
        "o1-preview",
        "o3-mini",
        "o4-mini",
        "chatgpt-4o-latest",
    ],
    "gemini": [
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-flash-preview",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-thinking-exp",
        "gemini-1.5-pro",
        "gemini-1.5-pro-latest",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ],
    "anthropic": [
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
        "claude-3-haiku-20240307",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "openrouter": [
        "openai/gpt-4.1-mini",
        "openai/gpt-4.1",
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        "anthropic/claude-sonnet-4",
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3.5-haiku",
        "google/gemini-2.5-flash-preview",
        "google/gemini-2.0-flash-001",
        "deepseek/deepseek-chat",
        "deepseek/deepseek-r1",
        "meta-llama/llama-3.3-70b-instruct",
        "mistralai/mistral-large-2411",
        "x-ai/grok-3-mini",
    ],
    "local": [
        "mistral-24b-ru-uncensored",
    ],
}

MODELS_LIST_URLS: dict[str, str] = {
    "grok": "https://api.x.ai/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}

OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt")


def static_models(provider_id: str) -> list[str]:
    info = provider_info(provider_id)
    models = list(STATIC_MODELS.get(provider_id, []))
    if info.default_model and info.default_model not in models:
        models.insert(0, info.default_model)
    return models


def _merge_models(provider_id: str, fetched: list[str]) -> list[str]:
    base = static_models(provider_id)
    combined: list[str] = []
    seen: set[str] = set()
    for mid in fetched + base:
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        combined.append(mid)
    default = provider_info(provider_id).default_model
    if default in combined:
        combined.remove(default)
        combined.insert(0, default)
    return combined


async def fetch_models_live(
    provider_id: str, api_key: str, local_base_url: str = ""
) -> list[str]:
    if not api_key.strip() and provider_id != "local":
        return static_models(provider_id)

    provider_id = provider_id if provider_id in LLM_PROVIDERS else "grok"

    try:
        if provider_id == "gemini":
            return await _fetch_gemini_models(api_key)
        if provider_id == "anthropic":
            return await _fetch_anthropic_models(api_key)
        if provider_id == "local":
            return await _fetch_local_models(api_key, local_base_url)
        if provider_id in MODELS_LIST_URLS:
            return await _fetch_openai_style_models(provider_id, api_key)
    except Exception:
        pass

    return static_models(provider_id)


async def _fetch_local_models(api_key: str, local_base_url: str) -> list[str]:
    base = normalize_openai_base_url(local_base_url)
    if not base:
        return static_models("local")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key.strip() else {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base}/models", headers=headers)
        response.raise_for_status()
        data = response.json()
    ids: list[str] = []
    for item in data.get("data") or []:
        mid = str(item.get("id") or "")
        if mid:
            ids.append(mid)
    ids.sort()
    return _merge_models("local", ids)


async def _fetch_openai_style_models(provider_id: str, api_key: str) -> list[str]:
    url = MODELS_LIST_URLS[provider_id]
    headers = {"Authorization": f"Bearer {api_key}"}
    if provider_id == "openrouter":
        headers["HTTP-Referer"] = "http://127.0.0.1:8787"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    items = data.get("data") or []
    ids: list[str] = []

    if provider_id == "openrouter":
        for item in items:
            mid = str(item.get("id") or "")
            if mid and "/" in mid:
                ids.append(mid)
    elif provider_id == "openai":
        for item in items:
            mid = str(item.get("id") or "")
            if any(mid.startswith(p) for p in OPENAI_MODEL_PREFIXES):
                ids.append(mid)
    else:
        for item in items:
            mid = str(item.get("id") or "")
            if mid:
                ids.append(mid)

    ids.sort()
    return _merge_models(provider_id, ids)


async def _fetch_gemini_models(api_key: str) -> list[str]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params={"key": api_key})
        response.raise_for_status()
        data = response.json()

    ids: list[str] = []
    for item in data.get("models") or []:
        name = str(item.get("name") or "")
        if not name.startswith("models/"):
            continue
        mid = name.removeprefix("models/")
        methods = item.get("supportedGenerationMethods") or []
        if methods and "generateContent" not in methods:
            continue
        ids.append(mid)

    ids.sort()
    return _merge_models("gemini", ids)


async def _fetch_anthropic_models(api_key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        response.raise_for_status()
        data = response.json()

    ids = [str(item.get("id") or "") for item in data.get("data") or [] if item.get("id")]
    ids.sort()
    return _merge_models("anthropic", ids)


async def resolve_models(
    provider_id: str, api_key: str, current_model: str = "", local_base_url: str = ""
) -> dict:
    models = await fetch_models_live(provider_id, api_key, local_base_url)
    if current_model and current_model not in models:
        models.insert(0, current_model)
    default = provider_info(provider_id).default_model
    selected = current_model or default
    if selected not in models and models:
        selected = models[0]
    return {
        "provider": provider_id,
        "models": models,
        "default_model": default,
        "selected_model": selected,
        "live": bool(api_key.strip()) or (provider_id == "local" and bool(local_base_url.strip())),
    }
