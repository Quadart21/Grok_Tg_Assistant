#!/usr/bin/env python3
"""Конвертация tdata → .session из командной строки."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import AppConfig
from core.session_manager import SessionFormat, discover_sessions, read_twofa_password
from core.tdata_converter import convert_tdata_to_session, has_converted_session, session_output_path


async def main() -> int:
    parser = argparse.ArgumentParser(description="Конвертер tdata → Telethon .session")
    parser.add_argument(
        "--sessions-dir",
        default="sessions",
        help="Папка с tdata (по умолчанию sessions/)",
    )
    parser.add_argument(
        "--config",
        default="config/settings.json",
        help="Файл настроек с паролем 2FA",
    )
    parser.add_argument(
        "accounts",
        nargs="*",
        help="ID аккаунтов (пусто = все tdata)",
    )
    args = parser.parse_args()

    config_path = ROOT / args.config
    password = ""
    if config_path.exists():
        password = AppConfig.load(config_path).telegram_2fa_password

    sessions_dir = ROOT / args.sessions_dir
    sessions = discover_sessions(sessions_dir)
    targets = [s for s in sessions if s.format == SessionFormat.TDATA]
    if args.accounts:
        allowed = set(args.accounts)
        targets = [s for s in targets if s.account_id in allowed]

    if not targets:
        print("Нет tdata для конвертации.")
        return 1

    ok = 0
    for session in targets:
        out = session_output_path(session)
        if has_converted_session(session) and out.exists():
            print(f"↷ {session.account_id}: уже есть {out.name}")
            ok += 1
            continue
        pwd = read_twofa_password(session, password)
        result = await convert_tdata_to_session(session, pwd)
        if result.success:
            print(f"✓ {session.account_id} → {result.output_path} ({result.error})")
            ok += 1
        else:
            print(f"✗ {session.account_id}: {result.error}")

    print(f"\nИтого: {ok}/{len(targets)}")
    return 0 if ok == len(targets) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
