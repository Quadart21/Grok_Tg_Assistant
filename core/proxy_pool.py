"""Пул прокси: импорт списка и привязка к аккаунтам."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import ProxyConfig
from core.proxy_checker import (
    check_many,
    check_proxy,
    country_flag,
    format_country_label,
    proxy_fingerprint,
)


def pool_path(base_dir: Path) -> Path:
    return base_dir / "config" / "proxy_pool.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PoolProxy:
    id: str
    proxy_type: str
    host: str
    port: int
    username: str = ""
    password: str = ""
    label: str = ""
    country: str = ""
    country_code: str = ""
    exit_ip: str = ""
    status: str = "unknown"
    latency_ms: int = 0
    checked_at: str = ""
    last_error: str = ""

    def fingerprint(self) -> str:
        return proxy_fingerprint(self.proxy_type, self.host, self.port, self.username, self.password)

    def country_label(self) -> str:
        return format_country_label(self.country_code, self.country)

    def display_label(self) -> str:
        if self.label:
            return self.label
        base = f"{self.host}:{self.port}"
        if self.username:
            base = f"{self.username}@{base}"
        if self.country_code or self.country:
            return f"{self.country_label()} · {base}"
        return base

    def to_proxy_config(self, account_id: str) -> ProxyConfig:
        return ProxyConfig(
            account_id=account_id,
            proxy_type=self.proxy_type,
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )

    def apply_check(self, result) -> None:
        self.checked_at = _now_iso()
        if result.ok:
            self.status = "ok"
            self.country = result.country
            self.country_code = result.country_code
            self.exit_ip = result.exit_ip
            self.latency_ms = result.latency_ms
            self.last_error = ""
            flag = country_flag(self.country_code)
            self.label = f"{flag} {self.country_code} · {self.host}:{self.port}".strip()
        else:
            self.status = "dead"
            self.last_error = result.error

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "type": self.proxy_type,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "country": self.country,
            "country_code": self.country_code,
            "exit_ip": self.exit_ip,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PoolProxy:
        return cls(
            id=str(data["id"]),
            proxy_type=str(data.get("type", "socks5")),
            host=str(data.get("host", "")),
            port=int(data.get("port", 0)),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            label=str(data.get("label", "")),
            country=str(data.get("country", "")),
            country_code=str(data.get("country_code", "")).upper(),
            exit_ip=str(data.get("exit_ip", "")),
            status=str(data.get("status", "unknown")),
            latency_ms=int(data.get("latency_ms", 0)),
            checked_at=str(data.get("checked_at", "")),
            last_error=str(data.get("last_error", "")),
        )


@dataclass
class ProxyPool:
    items: list[PoolProxy] = field(default_factory=list)
    bindings: dict[str, str] = field(default_factory=dict)

    def item_by_id(self, proxy_id: str) -> PoolProxy | None:
        for item in self.items:
            if item.id == proxy_id:
                return item
        return None

    def usage_count(self, proxy_id: str) -> int:
        return sum(1 for bound_id in self.bindings.values() if bound_id == proxy_id)

    def accounts_for(self, proxy_id: str) -> list[str]:
        return sorted(aid for aid, pid in self.bindings.items() if pid == proxy_id)

    def dedup_sets(self) -> tuple[set[str], set[str]]:
        fingerprints: set[str] = set()
        exit_ips: set[str] = set()
        for item in self.items:
            fingerprints.add(item.fingerprint())
            if item.exit_ip:
                exit_ips.add(item.exit_ip)
        return fingerprints, exit_ips


@dataclass
class ImportReport:
    added: int = 0
    skipped_duplicate: int = 0
    skipped_dead: int = 0
    skipped_parse: int = 0
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_dead": self.skipped_dead,
            "skipped_parse": self.skipped_parse,
            "details": self.details,
        }


def _new_id() -> str:
    return f"p_{secrets.token_hex(4)}"


def load_pool(path: Path) -> ProxyPool:
    if not path.exists():
        return ProxyPool()
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [PoolProxy.from_dict(x) for x in data.get("items", [])]
    bindings = {str(k): str(v) for k, v in (data.get("bindings") or {}).items()}
    return ProxyPool(items=items, bindings=bindings)


def save_pool(path: Path, pool: ProxyPool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "items": [item.to_dict() for item in pool.items],
        "bindings": dict(sorted(pool.bindings.items(), key=lambda x: x[0].lower())),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_proxy_line(line: str, default_type: str = "socks5") -> tuple[str, str, int, str, str] | None:
    """Разбор строки: host:port, host:port:user:pass, user:pass@host:port."""
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    proxy_type = default_type
    if "://" in raw:
        scheme, _, rest = raw.partition("://")
        proxy_type = scheme.lower() or default_type
        raw = rest

    username = ""
    password = ""
    if "@" in raw:
        auth, _, hostpart = raw.rpartition("@")
        if ":" in auth:
            username, _, password = auth.partition(":")
        else:
            username = auth
        raw = hostpart

    parts = [p.strip() for p in raw.split(":")]
    if len(parts) < 2:
        return None
    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        return None
    if not username and len(parts) > 2:
        username = parts[2]
    if not password and len(parts) > 3:
        password = parts[3]
    if not host or port <= 0:
        return None
    return proxy_type, host, port, username, password


def import_lines(pool: ProxyPool, lines: list[str], default_type: str = "socks5") -> int:
    report = import_lines_verified(pool, lines, default_type)
    return report.added


def import_lines_verified(pool: ProxyPool, lines: list[str], default_type: str = "socks5") -> ImportReport:
    report = ImportReport()
    fingerprints, exit_ips = pool.dedup_sets()
    batch_fps: set[str] = set()
    batch_ips: set[str] = set()
    to_check: list[tuple[str, str, str, int, str, str]] = []

    for line in lines:
        parsed = parse_proxy_line(line, default_type)
        if not parsed:
            report.skipped_parse += 1
            report.details.append({"line": line, "status": "parse_error"})
            continue
        proxy_type, host, port, username, password = parsed
        fp = proxy_fingerprint(proxy_type, host, port, username, password)
        if fp in fingerprints or fp in batch_fps:
            report.skipped_duplicate += 1
            report.details.append({"line": line, "status": "duplicate", "host": host, "port": port})
            continue
        batch_fps.add(fp)
        to_check.append((line, proxy_type, host, port, username, password))

    if not to_check:
        return report

    checked = check_many(to_check)
    for (line, proxy_type, host, port, username, password), result in checked:
        if not result.ok:
            report.skipped_dead += 1
            report.details.append(
                {
                    "line": line,
                    "status": "dead",
                    "host": host,
                    "port": port,
                    "error": result.error,
                }
            )
            continue
        if result.exit_ip and (result.exit_ip in exit_ips or result.exit_ip in batch_ips):
            report.skipped_duplicate += 1
            report.details.append(
                {
                    "line": line,
                    "status": "duplicate_ip",
                    "host": host,
                    "port": port,
                    "exit_ip": result.exit_ip,
                    "country_code": result.country_code,
                }
            )
            continue

        item = PoolProxy(
            id=_new_id(),
            proxy_type=proxy_type,
            host=host,
            port=port,
            username=username,
            password=password,
        )
        item.apply_check(result)
        pool.items.append(item)
        fingerprints.add(item.fingerprint())
        batch_fps.add(item.fingerprint())
        if item.exit_ip:
            exit_ips.add(item.exit_ip)
            batch_ips.add(item.exit_ip)
        report.added += 1
        report.details.append(
            {
                "line": line,
                "status": "added",
                "id": item.id,
                "country": item.country,
                "country_code": item.country_code,
                "exit_ip": item.exit_ip,
                "latency_ms": item.latency_ms,
            }
        )
    return report


def recheck_pool_items(pool: ProxyPool, proxy_ids: list[str] | None = None) -> ImportReport:
    report = ImportReport()
    targets = pool.items if not proxy_ids else [pool.item_by_id(pid) for pid in proxy_ids]
    targets = [t for t in targets if t]
    if not targets:
        return report

    to_check = [
        (item.display_label(), item.proxy_type, item.host, item.port, item.username, item.password)
        for item in targets
    ]
    results = check_many(to_check)

    for item, (_line, result) in zip(targets, results):
        if not result.ok:
            item.apply_check(result)
            report.skipped_dead += 1
            report.details.append({"id": item.id, "status": "dead", "error": result.error})
            continue

        conflict = any(
            other.id != item.id
            and (
                other.fingerprint() == proxy_fingerprint(
                    item.proxy_type, item.host, item.port, item.username, item.password
                )
                or (result.exit_ip and other.exit_ip == result.exit_ip)
            )
            for other in pool.items
        )
        if conflict:
            item.status = "dead"
            item.last_error = "дубликат (тот же IP или реквизиты)"
            item.checked_at = _now_iso()
            report.skipped_duplicate += 1
            report.details.append({"id": item.id, "status": "duplicate"})
            continue

        item.apply_check(result)
        report.added += 1
        report.details.append(
            {
                "id": item.id,
                "status": "ok",
                "country_code": item.country_code,
                "exit_ip": item.exit_ip,
                "latency_ms": item.latency_ms,
            }
        )
    return report


def bind_account(pool: ProxyPool, account_id: str, proxy_id: str | None) -> None:
    if not proxy_id:
        pool.bindings.pop(account_id, None)
        return
    item = pool.item_by_id(proxy_id)
    if not item:
        raise ValueError("Прокси не найден в пуле")
    if item.status == "dead":
        raise ValueError("Прокси нерабочий — выберите другой или перепроверьте пул")
    pool.bindings[account_id] = proxy_id


def create_pool_item(
    proxy_type: str,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
    label: str = "",
) -> PoolProxy:
    item = PoolProxy(
        id=_new_id(),
        proxy_type=proxy_type,
        host=host,
        port=port,
        username=username,
        password=password,
        label=label,
    )
    result = check_proxy(proxy_type, host, port, username, password)
    if not result.ok:
        raise ValueError(f"Прокси не работает: {result.error}")
    item.apply_check(result)
    return item


def delete_pool_item(pool: ProxyPool, proxy_id: str, *, unbind: bool = False) -> tuple[bool, list[str]]:
    item = pool.item_by_id(proxy_id)
    if not item:
        return False, []
    affected = pool.accounts_for(proxy_id)
    if affected and not unbind:
        raise ValueError("Прокси привязан к аккаунтам. Сначала отвяжите или удалите с отвязкой.")
    if unbind:
        for account_id in affected:
            pool.bindings.pop(account_id, None)
    pool.items = [x for x in pool.items if x.id != proxy_id]
    return True, affected


def delete_pool_items(pool: ProxyPool, proxy_ids: list[str], *, unbind: bool = True) -> tuple[int, list[str]]:
    deleted = 0
    all_affected: list[str] = []
    for proxy_id in proxy_ids:
        try:
            ok, affected = delete_pool_item(pool, proxy_id, unbind=unbind)
        except ValueError:
            continue
        if ok:
            deleted += 1
            all_affected.extend(affected)
    return deleted, sorted(set(all_affected))


def purge_dead_pool_items(pool: ProxyPool, *, unbind: bool = True) -> tuple[int, list[str]]:
    dead_ids = [item.id for item in pool.items if item.status == "dead"]
    return delete_pool_items(pool, dead_ids, unbind=unbind)


def resolve_pool_proxy(pool: ProxyPool, account_id: str) -> ProxyConfig | None:
    proxy_id = pool.bindings.get(account_id)
    if not proxy_id:
        return None
    item = pool.item_by_id(proxy_id)
    if not item or not item.host or not item.port or item.status == "dead":
        return None
    return item.to_proxy_config(account_id)


def migrate_legacy_proxies(pool: ProxyPool, legacy: dict[str, ProxyConfig]) -> int:
    """Перенести старые привязки из proxies.json в пул (один раз)."""
    if pool.items or pool.bindings:
        return 0
    if not legacy:
        return 0

    index: dict[str, str] = {}
    migrated = 0
    fingerprints, exit_ips = pool.dedup_sets()

    for account_id, proxy in legacy.items():
        if not proxy.host or not proxy.port:
            continue
        fp = proxy_fingerprint(proxy.proxy_type, proxy.host, proxy.port, proxy.username, proxy.password)
        if fp not in index:
            item = PoolProxy(
                id=_new_id(),
                proxy_type=proxy.proxy_type,
                host=proxy.host,
                port=proxy.port,
                username=proxy.username,
                password=proxy.password,
                status="unknown",
            )
            pool.items.append(item)
            index[fp] = item.id
            fingerprints.add(fp)
        pool.bindings[account_id] = index[fp]
        migrated += 1
    return migrated


def pool_to_api(pool: ProxyPool) -> dict:
    items = []
    for item in pool.items:
        accounts = pool.accounts_for(item.id)
        items.append(
            {
                "id": item.id,
                "label": item.display_label(),
                "type": item.proxy_type,
                "host": item.host,
                "port": item.port,
                "username": item.username,
                "password": item.password,
                "country": item.country,
                "country_code": item.country_code,
                "country_label": item.country_label(),
                "exit_ip": item.exit_ip,
                "status": item.status,
                "latency_ms": item.latency_ms,
                "checked_at": item.checked_at,
                "last_error": item.last_error,
                "accounts_count": len(accounts),
                "accounts": accounts,
            }
        )
    return {"items": items, "bindings": dict(pool.bindings)}
