from __future__ import annotations

import json
from pathlib import Path

from core.config import ProxyConfig


def proxies_path(base_dir: Path, config_proxies_file: str = "config/proxies.json") -> Path:
    path = base_dir / config_proxies_file
    if path.suffix == ".txt":
        json_path = path.with_suffix(".json")
        if json_path.exists():
            return json_path
    return path


def load_proxies(proxies_file: Path) -> dict[str, ProxyConfig]:
    if proxies_file.suffix == ".json":
        return _load_json(proxies_file)
    if proxies_file.exists():
        return _load_txt(proxies_file)
    json_alt = proxies_file.with_suffix(".json")
    if json_alt.exists():
        return _load_json(json_alt)
    return {}


def _load_json(path: Path) -> dict[str, ProxyConfig]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    proxies: dict[str, ProxyConfig] = {}
    for account_id, item in data.get("proxies", {}).items():
        proxies[account_id] = ProxyConfig(
            account_id=account_id,
            proxy_type=str(item.get("type", "socks5")),
            host=str(item.get("host", "")),
            port=int(item.get("port", 0)),
            username=str(item.get("username", "")),
            password=str(item.get("password", "")),
        )
    return proxies


def _load_txt(path: Path) -> dict[str, ProxyConfig]:
    proxies: dict[str, ProxyConfig] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        account_id, proxy_type, host, port = parts[0], parts[1], parts[2], parts[3]
        username = parts[4] if len(parts) > 4 else ""
        password = parts[5] if len(parts) > 5 else ""
        proxies[account_id] = ProxyConfig(
            account_id=account_id,
            proxy_type=proxy_type,
            host=host,
            port=int(port),
            username=username,
            password=password,
        )
    return proxies


def save_proxies(proxies_file: Path, proxies: dict[str, ProxyConfig]) -> None:
    if proxies_file.suffix != ".json":
        proxies_file = proxies_file.with_suffix(".json")
    proxies_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "proxies": {
            account_id: {
                "type": p.proxy_type,
                "host": p.host,
                "port": p.port,
                "username": p.username,
                "password": p.password,
            }
            for account_id, p in sorted(proxies.items(), key=lambda x: x[0].lower())
        }
    }
    proxies_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
