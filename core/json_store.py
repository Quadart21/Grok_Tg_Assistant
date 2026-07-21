from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import threading
import time
from typing import Any

_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _get_path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    lock = _get_path_lock(path)
    tmp_path: Path | None = None
    with lock:
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)
            last_error: PermissionError | None = None
            for attempt in range(8):
                try:
                    os.replace(tmp_path, path)
                    tmp_path = None
                    return
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise last_error
        finally:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
