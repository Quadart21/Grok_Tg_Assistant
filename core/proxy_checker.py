"""Проверка прокси: работоспособность, страна, дедупликация."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import quote

from python_socks import ProxyType
from python_socks.sync import Proxy

GEO_HOST = "ip-api.com"
GEO_PATH = "/json/?fields=status,message,country,countryCode,query"
DEFAULT_TIMEOUT = 14
MAX_WORKERS = 10

TYPE_MAP = {
    "socks5": ProxyType.SOCKS5,
    "socks4": ProxyType.SOCKS4,
    "http": ProxyType.HTTP,
}


@dataclass
class ProxyCheckResult:
    ok: bool
    country: str = ""
    country_code: str = ""
    exit_ip: str = ""
    latency_ms: int = 0
    error: str = ""


def proxy_fingerprint(proxy_type: str, host: str, port: int, username: str, password: str) -> str:
    return f"{proxy_type.lower()}|{host.strip().lower()}|{port}|{username}|{password}"


def country_flag(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return chr(0x1F1E6 + ord(code[0]) - ord("A")) + chr(0x1F1E6 + ord(code[1]) - ord("A"))


def format_country_label(country_code: str, country: str = "") -> str:
    code = (country_code or "").upper()
    flag = country_flag(code)
    if flag and code:
        return f"{flag} {code}"
    if country:
        return country
    return "?"


def _http_get_via_socket(sock, host: str, path: str, timeout: int) -> bytes:
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: KotTeamlead-ProxyCheck/1.0\r\n"
        "Connection: close\r\n\r\n"
    )
    sock.settimeout(timeout)
    sock.sendall(request.encode())
    chunks: list[bytes] = []
    while True:
        part = sock.recv(8192)
        if not part:
            break
        chunks.append(part)
    raw = b"".join(chunks)
    if b"\r\n\r\n" not in raw:
        raise OSError("empty HTTP response")
    return raw.split(b"\r\n\r\n", 1)[1]


def check_proxy(
    proxy_type: str,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> ProxyCheckResult:
    ptype = TYPE_MAP.get(proxy_type.lower(), ProxyType.SOCKS5)
    proxy = Proxy.create(
        ptype,
        host,
        port,
        username=username or None,
        password=password or None,
    )
    started = time.monotonic()
    sock = None
    try:
        sock = proxy.connect(GEO_HOST, 80, timeout=timeout)
        body = _http_get_via_socket(sock, GEO_HOST, GEO_PATH, timeout)
        payload = json.loads(body.decode("utf-8", errors="replace"))
        latency_ms = int((time.monotonic() - started) * 1000)
        if payload.get("status") != "success":
            return ProxyCheckResult(ok=False, error=str(payload.get("message") or "geo lookup failed"))
        return ProxyCheckResult(
            ok=True,
            country=str(payload.get("country") or ""),
            country_code=str(payload.get("countryCode") or "").upper(),
            exit_ip=str(payload.get("query") or ""),
            latency_ms=latency_ms,
        )
    except Exception as exc:
        return ProxyCheckResult(ok=False, error=str(exc))
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def check_many(
    items: list[tuple[str, str, str, int, str, str]],
    *,
    max_workers: int = MAX_WORKERS,
) -> list[tuple[tuple[str, str, str, int, str, str], ProxyCheckResult]]:
    """items: (line, proxy_type, host, port, username, password) — порядок сохраняется."""
    if not items:
        return []
    workers = min(max_workers, len(items))
    ordered: list[ProxyCheckResult | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {
            pool.submit(check_proxy, proxy_type, host, port, username, password): idx
            for idx, (_line, proxy_type, host, port, username, password) in enumerate(items)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                ordered[idx] = future.result()
            except Exception as exc:
                ordered[idx] = ProxyCheckResult(ok=False, error=str(exc))
    return [(items[i], ordered[i]) for i in range(len(items)) if ordered[i] is not None]
