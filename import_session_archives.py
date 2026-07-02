"""Распаковать RAR/ZIP с сессиями в папку sessions/."""

from __future__ import annotations

import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

import rarfile

BASE = Path(__file__).resolve().parent
SESSIONS = BASE / "sessions"


def sanitize_account_id(name: str) -> str:
    stem = Path(name).stem.strip()
    stem = re.sub(r"\s+", "_", stem)
    stem = re.sub(r"[^\w\-+]", "", stem, flags=re.UNICODE)
    return stem or "account"


def extract_tdata_zip(data: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            rel = member.filename.replace("\\", "/").lstrip("/")
            if rel.startswith("tdata/"):
                rel = rel[len("tdata/") :]
            if not rel or rel.endswith("/"):
                continue
            target = dest / "tdata" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))


def import_rar(archive: Path) -> list[str]:
    imported: list[str] = []
    used_ids: dict[str, int] = {}

    with rarfile.RarFile(archive) as rf:
        inner_zips = [i for i in rf.infolist() if i.filename.lower().endswith(".zip")]

        for item in inner_zips:
            account_id = sanitize_account_id(item.filename)
            if account_id in used_ids:
                used_ids[account_id] += 1
                account_id = f"{account_id}_{used_ids[account_id]}"
            else:
                used_ids[account_id] = 0

            account_dir = SESSIONS / account_id
            tdata_dir = account_dir / "tdata"
            if tdata_dir.is_dir() and any(tdata_dir.iterdir()):
                print(f"↷ Пропуск (уже есть): {account_id}")
                continue

            if account_dir.exists():
                shutil.rmtree(account_dir)
            account_dir.mkdir(parents=True, exist_ok=True)

            data = rf.read(item)
            extract_tdata_zip(data, account_dir)
            imported.append(account_id)
            print(f"✓ {account_id} ← {item.filename}")

    return imported


def main() -> int:
    archives = list(BASE.glob("*.rar")) + list(BASE.glob("*.zip"))
    archives = [a for a in archives if a.name != "cryptorocessing.zip"]
    if not archives:
        print("Архивы .rar / .zip в корне проекта не найдены")
        return 1

    SESSIONS.mkdir(parents=True, exist_ok=True)
    total: list[str] = []

    for archive in archives:
        if archive.suffix.lower() == ".rar":
            print(f"=== {archive.name} ===")
            total.extend(import_rar(archive))
        elif archive.suffix.lower() == ".zip":
            print(f"=== {archive.name} ===")
            # одиночный zip с tdata
            account_id = sanitize_account_id(archive.name)
            account_dir = SESSIONS / account_id
            account_dir.mkdir(parents=True, exist_ok=True)
            extract_tdata_zip(archive.read_bytes(), account_dir)
            total.append(account_id)
            print(f"✓ {account_id}")

    print(f"\nГотово: {len(total)} сессий в {SESSIONS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
