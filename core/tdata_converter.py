from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, functions, password as pwd_mod
from telethon.errors import (
    AuthKeyUnregisteredError,
    PasswordHashInvalidError,
    SessionPasswordNeededError,
)
from telethon.errors.common import AuthKeyNotFound

from core.session_manager import (
    SessionFormat,
    SessionInfo,
    find_twofa_file,
    read_twofa_password,
    resolve_tdata_base,
    session_account_dir,
)

OPENTELE_HINT = (
    "Конвертация tdata недоступна: не установлен opentele. "
    "Используйте Python 3.10–3.12, перезапустите start.bat "
    "или выполните: pip install -r requirements-tdata.txt"
)


def _load_opentele():
    try:
        from opentele.api import UseCurrentSession
        from opentele.exception import PasswordIncorrect, TDataBadDecryptKey, TFileNotFound
        from opentele.td import TDesktop
    except ImportError as exc:
        raise RuntimeError(OPENTELE_HINT) from exc
    return UseCurrentSession, PasswordIncorrect, TDataBadDecryptKey, TFileNotFound, TDesktop


def opentele_available() -> bool:
    try:
        import opentele  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class ConvertResult:
    account_id: str
    success: bool
    output_path: str = ""
    error: str = ""


def session_output_path(session: SessionInfo) -> Path:
    """Куда сохранить .session для данного tdata."""
    return session_account_dir(session) / f"{session.account_id}.session"


def has_converted_session(session: SessionInfo) -> bool:
    if session.format == SessionFormat.TELEthon:
        return session.path.exists()
    return session_output_path(session).exists()


def remove_session_artifacts(session_path: Path) -> None:
    """Удалить .session и связанные файлы (после неудачной конвертации)."""
    base = session_path.with_suffix("")
    for pattern in (f"{base.name}.session", f"{base.name}.session-journal"):
        path = session_path.parent / pattern
        if path.exists():
            path.unlink(missing_ok=True)


def _format_convert_error(exc: Exception) -> str:
    name = type(exc).__name__
    if isinstance(exc, (AuthKeyUnregisteredError, AuthKeyNotFound)):
        return "Сессия отозвана Telegram — tdata устарел, нужен новый вход в Telegram Desktop"
    if name == "PasswordIncorrect":
        return "Неверный пароль 2FA / локальный пароль"
    if isinstance(exc, (PasswordHashInvalidError, SessionPasswordNeededError)):
        return "Неверный или отсутствует облачный пароль 2FA — twoFA.txt в папке аккаунта"
    text = str(exc).strip()
    if "authorization key" in text.lower():
        return "Сессия отозвана Telegram — tdata устарел, нужен новый вход в Telegram Desktop"
    return text[:200]


async def _try_cloud_2fa(client, password: str) -> bool:
    if not password:
        return False
    try:
        pwd = await client(functions.account.GetPasswordRequest())
        await client(functions.auth.CheckPasswordRequest(pwd_mod.compute_check(pwd, password)))
        return await client.is_user_authorized()
    except (PasswordHashInvalidError, SessionPasswordNeededError):
        return False
    except Exception as exc:
        if type(exc).__name__ == "PasswordIncorrect":
            return False
        raise


def _needs_2fa_message(session: SessionInfo, password: str) -> str:
    if password:
        return "Не удалось войти с паролем 2FA — проверьте twoFA.txt или поле «Подключение»"
    if find_twofa_file(session):
        return "Файл twoFA.txt пустой — укажите облачный пароль 2FA"
    return "Нужен облачный пароль 2FA — создайте twoFA.txt в папке аккаунта или укажите в «Подключение»"


async def verify_converted_session(
    session: SessionInfo,
    api_id: int,
    api_hash: str,
) -> bool:
    """Проверить, что .session реально авторизован (не битый после ошибки)."""
    target = session_output_path(session)
    if not target.exists():
        return False
    client = TelegramClient(str(target.with_suffix("")), api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False
        await client.get_me()
        return True
    except (AuthKeyUnregisteredError, AuthKeyNotFound, OSError, ConnectionError):
        return False
    except Exception:
        return False
    finally:
        if client.is_connected():
            await client.disconnect()


async def convert_tdata_to_session(
    session: SessionInfo,
    two_fa_password: str = "",
    output: Path | None = None,
) -> ConvertResult:
    if session.format != SessionFormat.TDATA:
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error="Это уже .session, конвертация не нужна",
        )

    try:
        UseCurrentSession, PasswordIncorrect, TDataBadDecryptKey, TFileNotFound, TDesktop = _load_opentele()
    except RuntimeError as exc:
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error=str(exc),
        )

    target = output or session_output_path(session)
    password = read_twofa_password(session, two_fa_password)
    tdata_base = str(resolve_tdata_base(session.path))

    try:
        tdesk = TDesktop(tdata_base)
    except TDataBadDecryptKey:
        if not password:
            return ConvertResult(
                account_id=session.account_id,
                success=False,
                error="tdata защищён локальным паролем — укажите его в twoFA.txt или в «Подключение»",
            )
        try:
            tdesk = TDesktop(tdata_base, passcode=password)
        except TDataBadDecryptKey:
            return ConvertResult(
                account_id=session.account_id,
                success=False,
                error="Неверный локальный пароль tdata (не путать с облачным 2FA)",
            )
    except TFileNotFound:
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error="Не найден key_data в tdata — проверьте, что папка tdata полная (есть key_datas)",
        )

    if not tdesk.isLoaded():
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error="Не удалось прочитать tdata (папка повреждена или неполная)",
        )
    if tdesk.accountsCount < 1:
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error="В tdata нет авторизованного аккаунта",
        )

    remove_session_artifacts(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    session_file = str(target.with_suffix(""))

    try:
        client = await tdesk.ToTelethon(
            session=session_file,
            flag=UseCurrentSession,
            password=password,
        )
        await client.connect()
        if not await client.is_user_authorized():
            await _try_cloud_2fa(client, password)
        if not await client.is_user_authorized():
            await client.disconnect()
            remove_session_artifacts(target)
            return ConvertResult(
                account_id=session.account_id,
                success=False,
                error=_needs_2fa_message(session, password),
            )
        me = await client.get_me()
        await client.disconnect()
    except PasswordIncorrect:
        remove_session_artifacts(target)
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error="Неверный пароль 2FA / локальный пароль",
        )
    except Exception as exc:
        remove_session_artifacts(target)
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error=_format_convert_error(exc),
        )

    if not target.exists():
        return ConvertResult(
            account_id=session.account_id,
            success=False,
            error="Файл .session не был создан",
        )

    label = me.username or me.first_name or str(me.id)
    return ConvertResult(
        account_id=session.account_id,
        success=True,
        output_path=str(target),
        error=f"OK: @{label}" if me.username else f"OK: {label}",
    )
