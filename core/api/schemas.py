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
    local_api_key: str = ""
    local_base_url: str = "http://127.0.0.1:8000/v1"
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


class GroupChatAccountsBody(BaseModel):
    account_ids: list[str] = []


class GroupChatJoinLinkBody(BaseModel):
    account_ids: list[str] = []
    link: str = ""


class GroupChatRoleOverride(BaseModel):
    role_name: str = ""
    role_prompt: str = ""


class GroupChatStartBody(BaseModel):
    account_ids: list[str] = []
    chat_id: int = 0
    chat_title: str = ""
    topic: str = ""
    extra_context: str = ""
    role_overrides: dict[str, GroupChatRoleOverride] = {}
    activity_weights: dict[str, float] = {}


class GroupChatSettingsBody(BaseModel):
    use_schedule: bool = True
    timezone_offset_hours: float | None = None
    activity_windows: list[dict] = []
    online_probability: float = 0.55
    quiet_break_min_min: int = 15
    quiet_break_max_min: int = 90
    quiet_break_chance: float = 0.12
    resume_next_day: bool = True
    max_messages_per_account_session: int = 40
    max_messages_per_account_hour: int = 12
    max_messages_per_account_day: int = 30
    max_messages_group_day: int = 80
    burst_min: int = 1
    burst_max: int = 3
    max_consecutive_same_speaker: int = 3
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
    language: str = "ru"
    history_limit: int = 40
    temperature: float = 0.9
    max_tokens: int = 250
    reply_style: str = "mixed"
    stop_keywords: list[str] | str = []
    sync_history_every_sec: int = 45
