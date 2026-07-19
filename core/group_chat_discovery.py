from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from core.config import AppConfig, ProxyConfig
from core.proxy_manager import load_proxies
from core.proxy_pool import load_pool, pool_path, resolve_pool_proxy
from core.session_manager import discover_sessions, read_twofa_password
from core.state_store import StateStore
from core.telegram_client import TelegramAccountClient, format_telegram_error


LogCallback = Callable[[str], None]


def _resolve_proxy(
    account_id: str,
    base_dir: Path,
    config: AppConfig,
    state: StateStore,
    proxies: dict[str, ProxyConfig],
) -> ProxyConfig | None:
    binding = state.get_account_binding(account_id)
    if binding:
        saved = binding.to_proxy()
        if saved:
            return saved
    pool = load_pool(pool_path(base_dir))
    pool_proxy = resolve_pool_proxy(pool, account_id)
    if pool_proxy:
        return pool_proxy
    return proxies.get(account_id)


async def discover_common_chats(
    config: AppConfig,
    base_dir: Path,
    account_ids: list[str],
    log: LogCallback | None = None,
) -> list[dict]:
    """Найти чаты, в которых состоят ВСЕ выбранные аккаунты."""
    log = log or (lambda _m: None)
    if len(account_ids) < 2:
        raise ValueError("Выберите минимум 2 аккаунта")

    sessions = discover_sessions(base_dir / config.sessions_dir)
    by_id = {s.account_id: s for s in sessions}
    missing = [a for a in account_ids if a not in by_id]
    if missing:
        raise ValueError(f"Аккаунты не найдены: {', '.join(missing[:5])}")

    if not config.telegram_api_id or not config.telegram_api_hash:
        raise ValueError("Укажите Telegram API ID и Hash")

    state = StateStore(base_dir / config.state_file)
    proxies = load_proxies(base_dir / config.proxies_file)
    clients: list[TelegramAccountClient] = []
    per_account: dict[str, dict[int, dict]] = {}

    try:
        for account_id in account_ids:
            session = by_id[account_id]
            proxy = _resolve_proxy(account_id, base_dir, config, state, proxies)
            two_fa = read_twofa_password(session, config.telegram_2fa_password)
            client = TelegramAccountClient(
                session,
                config.telegram_api_id,
                config.telegram_api_hash,
                proxy=proxy,
                two_fa_password=two_fa,
            )
            try:
                name = await client.connect()
                log(f"✓ {account_id} ({name}): загружаем диалоги...")
                dialogs = await client.list_group_dialogs()
                per_account[account_id] = {d["chat_id"]: d for d in dialogs}
                log(f"  → {len(dialogs)} групп/супергрупп")
                clients.append(client)
            except Exception as exc:
                await client.disconnect()
                raise RuntimeError(
                    f"{account_id}: {format_telegram_error(exc)}"
                ) from exc

        if not per_account:
            return []

        common_ids = set(next(iter(per_account.values())).keys())
        for mapping in list(per_account.values())[1:]:
            common_ids &= set(mapping.keys())

        result: list[dict] = []
        first_map = per_account[account_ids[0]]
        for chat_id in sorted(common_ids, key=lambda cid: (first_map[cid].get("title") or "").lower()):
            info = first_map[chat_id]
            result.append(
                {
                    "chat_id": chat_id,
                    "title": info.get("title") or str(chat_id),
                    "username": info.get("username") or "",
                    "kind": info.get("kind") or "group",
                    "participants_count": info.get("participants_count"),
                    "account_ids": list(account_ids),
                }
            )
        log(f"Найдено общих чатов: {len(result)}")
        return result
    finally:
        await asyncio.gather(*(c.disconnect() for c in clients), return_exceptions=True)
