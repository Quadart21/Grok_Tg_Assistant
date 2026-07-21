from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_IMPORT_DUP_SUFFIX = re.compile(r"^(.+)_(\d+)$")
_SESSION_SKIP_SUFFIXES = (".session-journal",)


class SessionFormat(str, Enum):
    TELEthon = "session"
    TDATA = "tdata"


@dataclass
class SessionInfo:
    account_id: str
    path: Path
    format: SessionFormat

    @property
    def display_name(self) -> str:
        return self.account_id


def discover_sessions(sessions_dir: Path) -> list[SessionInfo]:
    if not sessions_dir.exists():
        sessions_dir.mkdir(parents=True, exist_ok=True)
        return []

    found: dict[str, SessionInfo] = {}

    try:
        entries = list(sessions_dir.iterdir())
    except OSError:
        return []

    for item in entries:
        if _should_skip_session_entry(item):
            continue
        if item.is_file() and item.suffix == ".session":
            account_id = item.stem
            found[account_id] = SessionInfo(account_id, item, SessionFormat.TELEthon)
        elif item.is_dir():
            if _is_tdata_folder(item):
                found[item.name] = SessionInfo(item.name, item, SessionFormat.TDATA)
            else:
                try:
                    children = list(item.iterdir())
                except OSError:
                    continue
                for child in children:
                    if _should_skip_session_entry(child):
                        continue
                    if child.is_file() and child.suffix == ".session":
                        account_id = child.stem
                        found[account_id] = SessionInfo(account_id, child, SessionFormat.TELEthon)
                    elif child.is_dir() and _is_tdata_folder(child):
                        found[item.name] = SessionInfo(item.name, child, SessionFormat.TDATA)

    return sorted(found.values(), key=lambda s: s.account_id.lower())


def resolve_tdata_base(path: Path) -> Path:
    """Папка tdata для opentele (basePath — каталог с key_datas)."""
    if path.name.lower() == "tdata":
        return path
    nested = path / "tdata"
    if nested.is_dir():
        return nested
    return path


def session_account_dir(session: SessionInfo) -> Path:
    """Папка аккаунта, где лежат tdata / .session / twoFA."""
    if session.format == SessionFormat.TDATA:
        return resolve_tdata_base(session.path).parent
    return session.path.parent


TWOFAA_FILE_NAMES = ("twoFA.txt", "twoFA", "twofa.txt", "2fa.txt", "2FA.txt")


def find_twofa_file(session: SessionInfo) -> Path | None:
    folder = session_account_dir(session)
    for name in TWOFAA_FILE_NAMES:
        path = folder / name
        if path.is_file():
            return path
    return None


def read_twofa_password(session: SessionInfo, global_password: str = "") -> str:
    """Пароль 2FA: сначала twoFA из папки сессии, иначе общий из настроек."""
    twofa_path = find_twofa_file(session)
    if twofa_path:
        text = twofa_path.read_text(encoding="utf-8-sig").strip()
        if text:
            return text
    return (global_password or "").strip()


def _is_tdata_folder(path: Path) -> bool:
    if path.name.lower() == "tdata":
        return (path / "key_datas").exists() or any(path.glob("D877F783D5D3EF8C*"))
    return (path / "tdata" / "key_datas").exists() or any(path.glob("**/key_datas"))


def _should_skip_session_entry(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(".") or any(name.endswith(suffix) for suffix in _SESSION_SKIP_SUFFIXES)


def import_duplicate_base_id(account_id: str) -> str | None:
    """Базовый id, если имя вида TG_2898_1 (дубль при импорте архива)."""
    match = _IMPORT_DUP_SUFFIX.match(account_id)
    return match.group(1) if match else None


def is_import_duplicate(account_id: str, all_account_ids: set[str]) -> bool:
    base = import_duplicate_base_id(account_id)
    return bool(base and base in all_account_ids)


def filter_accounts_for_roles(accounts: list[dict]) -> list[str]:
    """Аккаунты для назначения ролей: готовые, для рассылки, без дублей _1/_2."""
    by_id = {a["id"]: a for a in accounts}
    ready = [a for a in accounts if a.get("outreach_eligible")]
    ready_ids = {a["id"] for a in ready}
    all_ids = set(by_id)

    result: list[str] = []
    for account in sorted(ready, key=lambda a: a["id"].lower()):
        acc_id = account["id"]
        base = import_duplicate_base_id(acc_id)
        if base and base in all_ids and base in ready_ids:
            continue
        result.append(acc_id)
    return result
