from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PeerFloodError,
    SessionPasswordNeededError,
    UserPrivacyRestrictedError,
    UsernameInvalidError,
    UsernameNotModifiedError,
    UsernameNotOccupiedError,
    UsernameOccupiedError,
)
from telethon import functions, password as pwd_mod

from core.config import ProxyConfig
from core.session_manager import SessionFormat, SessionInfo
from core.tdata_converter import convert_tdata_to_session, session_output_path


IncomingHandler = Callable[[int, str, int, str], Awaitable[None]]
OutgoingHandler = Callable[[int, str, int, str], Awaitable[None]]


class TelegramAccountClient:
    def __init__(
        self,
        session: SessionInfo,
        api_id: int,
        api_hash: str,
        proxy: ProxyConfig | None = None,
        two_fa_password: str = "",
    ) -> None:
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.proxy = proxy
        self.two_fa_password = (two_fa_password or "").strip()
        self._client: TelegramClient | None = None
        self._my_id: int | None = None
        self._tracked_user_ids: set[int] = set()
        self._incoming_handler: IncomingHandler | None = None
        self._outgoing_handler: OutgoingHandler | None = None
        self._listen_all_private = False
        self._handler_registered = False

    @property
    def account_id(self) -> str:
        return self.session.account_id

    @property
    def raw(self) -> TelegramClient:
        if not self._client:
            raise RuntimeError("Клиент не подключён")
        return self._client

    async def connect(self) -> str:
        session_path = await self._resolve_session_path()
        proxy = self.proxy.to_telethon_proxy() if self.proxy else None
        self._client = TelegramClient(
            str(session_path.with_suffix("")),
            self.api_id,
            self.api_hash,
            proxy=proxy,
        )
        await self._client.connect()
        await self._ensure_authorized()
        me = await self._client.get_me()
        self._my_id = me.id
        return me.username or me.first_name or str(me.id)

    async def _ensure_authorized(self) -> None:
        if not self._client:
            raise RuntimeError("Клиент не подключён")
        if await self._client.is_user_authorized():
            return
        if not self.two_fa_password:
            raise RuntimeError(
                f"Сессия {self.session.account_id} не авторизована. "
                "Положите twoFA.txt в папку сессии или укажите пароль 2FA во вкладке «Подключение»."
            )
        try:
            pwd = await self._client(functions.account.GetPasswordRequest())
            await self._client(
                functions.auth.CheckPasswordRequest(pwd_mod.compute_check(pwd, self.two_fa_password))
            )
        except PasswordHashInvalidError as exc:
            raise RuntimeError(
                f"Неверный пароль 2FA для {self.session.account_id}. Проверьте поле во вкладке «Подключение»."
            ) from exc
        except SessionPasswordNeededError as exc:
            raise RuntimeError(
                f"Для {self.session.account_id} нужен пароль 2FA — укажите его во вкладке «Подключение»."
            ) from exc
        if not await self._client.is_user_authorized():
            raise RuntimeError(f"Сессия {self.session.account_id} не авторизована")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()
            self._client = None
            self._my_id = None

    def set_incoming_handler(
        self,
        handler: IncomingHandler | None,
        listen_all_private: bool = False,
        outgoing_handler: OutgoingHandler | None = None,
    ) -> None:
        self._incoming_handler = handler
        self._outgoing_handler = outgoing_handler
        self._listen_all_private = listen_all_private
        self._register_message_handlers()

    def track_users(self, user_ids: set[int]) -> None:
        self._tracked_user_ids = set(user_ids)
        self._register_message_handlers()

    def _register_message_handlers(self) -> None:
        if not self._client or self._handler_registered or not self._incoming_handler:
            return
        self._handler_registered = True

        @self._client.on(events.NewMessage(incoming=True))
        async def _on_incoming(event: events.NewMessage.Event) -> None:
            if not event.is_private or not self._incoming_handler:
                return
            sender = await event.get_sender()
            if not sender:
                return
            if not self._listen_all_private and sender.id not in self._tracked_user_ids:
                return
            if event.message.out:
                return
            text = event.message.message or ""
            if not text.strip():
                return
            try:
                await self._client.send_read_acknowledge(event.chat_id, max_id=event.message.id)
            except Exception:
                pass
            username = sender.username or f"id_{sender.id}"
            await self._incoming_handler(sender.id, text.strip(), event.message.id, username)

        if self._listen_all_private and self._outgoing_handler:

            @self._client.on(events.NewMessage(outgoing=True))
            async def _on_outgoing(event: events.NewMessage.Event) -> None:
                if not event.is_private or not self._outgoing_handler:
                    return
                chat = await event.get_chat()
                if not chat or getattr(chat, "bot", False):
                    return
                text = event.message.message or ""
                if not text.strip():
                    return
                username = getattr(chat, "username", None) or f"id_{chat.id}"
                await self._outgoing_handler(chat.id, text.strip(), event.message.id, username)

    async def send_message(self, username: str, text: str) -> int:
        if not self._client:
            raise RuntimeError("Клиент не подключён")
        username = username.lstrip("@")
        entity = await self._client.get_entity(username)
        msg = await self._client.send_message(entity, text)
        return msg.id

    async def send_message_to_user(self, user_id: int, text: str) -> int:
        if not self._client:
            raise RuntimeError("Клиент не подключён")
        entity = await self._client.get_entity(user_id)
        msg = await self._client.send_message(entity, text)
        return msg.id

    async def show_typing(self, user_id: int, seconds: float = 2.0) -> None:
        if not self._client or seconds <= 0:
            return
        entity = await self._client.get_entity(user_id)
        async with self._client.action(entity, "typing"):
            await asyncio.sleep(seconds)

    async def mark_read(self, user_id: int, max_message_id: int | None = None) -> None:
        """Отметить сообщения прочитанными — у собеседника появятся двойные галочки."""
        if not self._client:
            return
        try:
            entity = await self._client.get_entity(user_id)
            if max_message_id:
                await self._client.send_read_acknowledge(entity, max_id=max_message_id)
            else:
                await self._client.send_read_acknowledge(entity)
        except Exception:
            pass

    async def send_first_message(self, username: str, text: str) -> int:
        return await self.send_message(username, text)

    async def resolve_user_id(self, username: str) -> int:
        entity = await self.raw.get_entity(username.lstrip("@"))
        return entity.id

    async def sync_recent_messages(self, username: str, known_msg_ids: set[int], limit: int = 30) -> list[tuple[int, bool, str]]:
        entity = await self.raw.get_entity(username.lstrip("@"))
        return await self._collect_missed_messages(entity, known_msg_ids, limit)

    async def sync_recent_messages_for_user(
        self, user_id: int, known_msg_ids: set[int], limit: int = 30
    ) -> list[tuple[int, bool, str]]:
        entity = await self.raw.get_entity(user_id)
        return await self._collect_missed_messages(entity, known_msg_ids, limit)

    async def _collect_missed_messages(
        self, entity, known_msg_ids: set[int], limit: int
    ) -> list[tuple[int, bool, str]]:
        tg_messages = await self.raw.get_messages(entity, limit=limit)
        result: list[tuple[int, bool, str]] = []
        for msg in reversed(tg_messages):
            if not msg.message or not msg.message.strip():
                continue
            if msg.id in known_msg_ids:
                continue
            result.append((msg.id, bool(msg.out), msg.message.strip()))
        return result

    async def update_profile(
        self,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
    ) -> dict[str, str]:
        if not self._client:
            raise RuntimeError("Клиент не подключён")
        if first_name is not None or last_name is not None:
            await self._client(
                functions.account.UpdateProfileRequest(
                    first_name=first_name,
                    last_name=last_name,
                )
            )
        if username is not None:
            await self._client(
                functions.account.UpdateUsernameRequest(username=username.lstrip("@").strip())
            )
        me = await self._client.get_me()
        return {
            "first_name": me.first_name or "",
            "last_name": me.last_name or "",
            "username": me.username or "",
        }

    async def get_profile(self) -> dict[str, str]:
        if not self._client:
            raise RuntimeError("Клиент не подключён")
        me = await self._client.get_me()
        return {
            "first_name": me.first_name or "",
            "last_name": me.last_name or "",
            "username": me.username or "",
        }

    async def _resolve_session_path(self) -> Path:
        if self.session.format == SessionFormat.TELEthon:
            return self.session.path

        converted = session_output_path(self.session)
        if converted.exists():
            return converted

        result = await convert_tdata_to_session(self.session, self.two_fa_password, converted)
        if not result.success:
            raise RuntimeError(result.error)
        return Path(result.output_path)


TELEGRAM_ERRORS = {
    UsernameInvalidError: "Неверный username",
    UsernameNotOccupiedError: "Username не существует",
    UsernameOccupiedError: "Username уже занят",
    UsernameNotModifiedError: "Username не изменился",
    UserPrivacyRestrictedError: "Пользователь запретил сообщения",
    PeerFloodError: "Peer flood — аккаунт ограничен",
    FloodWaitError: "Flood wait",
    SessionPasswordNeededError: "Нужен пароль 2FA",
    PasswordHashInvalidError: "Неверный пароль 2FA",
}


def format_telegram_error(exc: Exception) -> str:
    for err_cls, message in TELEGRAM_ERRORS.items():
        if isinstance(exc, err_cls):
            wait = getattr(exc, "seconds", None)
            if isinstance(exc, FloodWaitError) and wait:
                return f"Flood wait — подождите {wait} сек"
            return message
    text = str(exc).strip()
    return text[:200] if text else exc.__class__.__name__
