"""Pydantic-схемы HTTP API."""

from __future__ import annotations

from pydantic import BaseModel


class ConfigBody(BaseModel):
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    llm_provider: str = "grok"
    llm_model: str = ""
    grok_api_key: str = ""
    grok_model: str = "grok-3-mini"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    openrouter_api_key: str = ""
    delay_between_messages_sec: int = 30
    max_concurrent_accounts: int = 5
    message_language: str = "ru"
    reply_delay_min_sec: int = 5
    reply_delay_max_sec: int = 25
    telegram_2fa_password: str = ""


class ProxyBody(BaseModel):
    type: str = "socks5"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""


class BulkProxyBody(BaseModel):
    lines: str = ""
    type: str = "socks5"


class ProxyBindBody(BaseModel):
    proxy_id: str | None = None


class ProxyPoolImportBody(BaseModel):
    lines: str = ""
    type: str = "socks5"


class ProxyBulkIdsBody(BaseModel):
    proxy_ids: list[str] = []
    unbind: bool = True


class ProxyRecheckBody(BaseModel):
    proxy_ids: list[str] = []


class ProxyAutoBindBody(BaseModel):
    account_ids: list[str] = []
    proxy_ids: list[str] = []


class RolesBody(BaseModel):
    default_role: str = ""
    groups: list[dict] = []
    assignments: dict[str, str] = {}
    master_prompt: dict | None = None


class StartBody(BaseModel):
    targets: str = ""
    account_ids: list[str] = []
    extra_context: str = ""
    enable_dialog: bool = True
    resume_existing: bool = True
    resume_only: bool = False


class DialogUpdateBody(BaseModel):
    status: str | None = None
    auto_reply: bool | None = None
    goal: str | None = None
    dialog_extra_context: str | None = None
    max_replies: int | None = None
    notes: str | None = None
    replies_count: int | None = None


class ClearDialogsBody(BaseModel):
    account_id: str | None = None
    delete_completely: bool = True


class DialogSettingsBody(BaseModel):
    history_for_grok: int = 40
    max_stored_messages: int = 150
    grok_temperature: float = 0.8
    grok_max_tokens: int = 400
    reply_delay_min_sec: int = 5
    reply_delay_max_sec: int = 25
    typing_delay_sec: int = 2
    batch_messages_sec: int = 8
    min_user_message_chars: int = 1
    ignore_keywords: list[str] | str = []
    global_extra_prompt: str = ""
    max_replies_per_dialog: int = 0
    max_replies_per_hour: int = 30
    split_long_messages: bool = False
    split_at_chars: int = 350
    sync_history_on_resume: bool = True
    sync_history_limit: int = 50
    first_message_max_chars: int = 500


class MasterPromptBody(BaseModel):
    enabled: bool = True
    text: str = ""


class AgentBody(BaseModel):
    account_id: str = ""
    name: str = "Секретарь"
    prompt: str = ""
    language: str = "ru"
    extra_context: str = ""
    goal: str = ""
    allowed_users: list[str] | str = []
    blocked_users: list[str] | str = []
    enabled: bool = True


class BulkProfileBody(BaseModel):
    account_ids: list[str] = []
    generate_mode: str = "manual"
    lang: str = "ru"
    with_username: bool = False
    change_first_name: bool = False
    change_last_name: bool = False
    change_username: bool = False
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    delay_sec: int = 3


class ProfilePreviewBody(BaseModel):
    generate_mode: str = "names"
    lang: str = "ru"
    with_username: bool = False
    count: int = 5


class ConvertSessionsBody(BaseModel):
    account_ids: list[str] = []


class AgentStartBody(BaseModel):
    account_ids: list[str] = []
