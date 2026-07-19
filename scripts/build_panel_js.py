#!/usr/bin/env python3
"""Build panel JS modules with window.Panel namespace."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "panel" / "app.js"
OUT = ROOT / "web" / "panel" / "js"

STATE_VARS = [
    "selectedAccount", "selectedForRun", "accountsCache", "proxyPoolCache",
    "selectedProxies", "proxyViewFilters", "proxyFiltersInited", "selectedAgents",
    "selectedGroupChatAccounts", "groupChatCommonCache",
    "logOffset", "llmProviders", "roleGroupsData", "roleAssignments", "roleGroupNames",
    "editingDialogKey", "editingAgentId", "currentDialogKey", "accountViewFilters", "accountFiltersInited",
]

CORE_HEAD = """  P.$ = (sel) => document.querySelector(sel);
  P.$$ = (sel) => document.querySelectorAll(sel);
  P.escapeHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  P.api = async (path, opts = {}) => {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText);
    return data;
  };
  P.state = P.state || {
    selectedAccount: null,
    selectedForRun: new Set(),
    accountsCache: [],
    proxyPoolCache: [],
    selectedProxies: new Set(),
    proxyViewFilters: new Set(),
    proxyFiltersInited: false,
    selectedAgents: new Set(),
    selectedGroupChatAccounts: new Set(),
    groupChatCommonCache: [],
    logOffset: 0,
    llmProviders: [],
    roleGroupsData: [],
    roleAssignments: {},
    roleGroupNames: [],
    editingDialogKey: null,
    editingAgentId: null,
    currentDialogKey: null,
    accountViewFilters: new Set(['outreach_eligible']),
    accountFiltersInited: false,
  };
"""

PANEL_FNS = []  # legacy; all names collected from app.js

ALL_FN_NAMES: set[str] = set()


BARE_FN_SKIP = frozenset({"api", "escapeHtml"})


def transform(body: str, fn_names: set[str] | None = None) -> str:
    names = fn_names or ALL_FN_NAMES
    for var in STATE_VARS:
        body = re.sub(rf"^let {var}.*\n", "", body, flags=re.MULTILINE)

    body = re.sub(r"^async function (\w+)", r"P.\1 = async function", body, flags=re.MULTILINE)
    body = re.sub(r"^function (\w+)", r"P.\1 = function", body, flags=re.MULTILINE)
    body = re.sub(
        r"^const (ACCOUNT_FILTERS|PROXY_FILTERS|DIALOG_SETTING_FIELDS|GROUP_CHAT_SETTING_FIELDS) =",
        r"P.\1 =",
        body,
        flags=re.MULTILINE,
    )

    # Не трогаем id в селекторах: $("#accountViewFilters")
    for var in STATE_VARS:
        body = re.sub(rf"(?<!#)\b{re.escape(var)}\b", f"P.state.{var}", body)

    # $$ before $ — иначе P.$$ ломается в P.$P.$
    body = re.sub(r"(?<![.\w$])\$\$\(", "P.$$(", body)
    body = re.sub(r"(?<![.\w$])\$\(", "P.$(", body)
    body = re.sub(r"(?<!P\.)api\(", "P.api(", body)
    body = re.sub(r"(?<!P\.)escapeHtml\(", "P.escapeHtml(", body)

    for fn in sorted(names, key=len, reverse=True):
        body = re.sub(rf"(?<!P\.)\b{re.escape(fn)}\(", f"P.{fn}(", body)
        if fn not in BARE_FN_SKIP:
            body = re.sub(rf"(?<!P\.)\b{re.escape(fn)}\b(?!\s*=)", f"P.{fn}", body)

    for const in ("ACCOUNT_FILTERS", "PROXY_FILTERS", "DIALOG_SETTING_FIELDS", "GROUP_CHAT_SETTING_FIELDS"):
        body = re.sub(rf"(?<!P\.)\b{const}\b", f"P.{const}", body)

    return body


def wrap(body: str, head: str = "") -> str:
    return (
        f"/* Kot_Teamlead */\n(function () {{\n"
        f"  const P = window.Panel = window.Panel || {{}};\n"
        f"{head}\n{transform(body)}\n}})();\n"
    )


BOOT_JS = """/* Kot_Teamlead boot */
(function () {
  const P = window.Panel = window.Panel || {};
  P.$$("#tabNav .nav-item").forEach((btn) => {
    btn.addEventListener("click", () => P.showTab(btn.dataset.tab));
  });
  P.loadConfig();
  P.loadProxyPool();
  P.loadAccounts();
  P.loadRoles();
  P.loadDialogSettings();
  P.loadDialogs();
  P.loadAgents();
  P.loadGroupChat();
  P.refreshStatus();
  setInterval(async () => {
    await P.refreshStatus();
    await P.refreshEngine();
    await P.refreshLogs();
  }, 1500);
})();
"""


def main() -> None:
    global ALL_FN_NAMES
    src = SRC.read_text(encoding="utf-8")
    ALL_FN_NAMES = set(re.findall(r"^(?:async )?function (\w+)", src, re.MULTILINE))
    lines = src.splitlines(keepends=True)

    def sl(a: int, b: int) -> str:
        return "".join(lines[a - 1 : b])

    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "01-core.js": (sl(31, 34) + sl(40, 253), CORE_HEAD),
        "02-proxies.js": (sl(255, 477) + sl(869, 1057), ""),
        "03-accounts.js": (sl(478, 867), ""),
        "04-app.js": (sl(1059, 1778), ""),
    }
    for name, (body, head) in files.items():
        (OUT / name).write_text(wrap(body, head), encoding="utf-8")

    (OUT / "99-boot.js").write_text(BOOT_JS, encoding="utf-8")

    bundle = "".join((OUT / n).read_text(encoding="utf-8") for n in sorted(OUT.glob("*.js")))
    (ROOT / "web" / "panel" / "app.bundle.js").write_text(bundle, encoding="utf-8")
    print("OK")


if __name__ == "__main__":
    main()
