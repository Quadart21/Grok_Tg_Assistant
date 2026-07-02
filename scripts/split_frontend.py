#!/usr/bin/env python3
"""One-off: split web/panel/app.js into ES modules."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "panel" / "app.js"
OUT = ROOT / "web" / "panel" / "js"

HEADER = '''/** Kot_Teamlead panel module */\n'''

def wrap_exports(content: str, exports: list[str]) -> str:
    lines = content.rstrip().splitlines()
    body = "\n".join(lines)
    exp = "\n".join(f"export {{ {name} }};" for name in exports)
    return HEADER + body + "\n\n" + exp + "\n"

def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    def slice_(start: int, end: int) -> str:
        return "".join(lines[start - 1 : end])

    # core
    (OUT / "core" / "dom.js").write_text(
        HEADER
        + "export const $ = (sel) => document.querySelector(sel);\n"
        + "export const $$ = (sel) => document.querySelectorAll(sel);\n"
        + "export function escapeHtml(s) {\n"
        + "  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');\n"
        + "}\n",
        encoding="utf-8",
    )
    (OUT / "core" / "api.js").write_text(
        HEADER
        + "export async function api(path, opts = {}) {\n"
        + "  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });\n"
        + "  const data = await r.json().catch(() => ({}));\n"
        + "  if (!r.ok) throw new Error(data.detail || r.statusText);\n"
        + "  return data;\n"
        + "}\n",
        encoding="utf-8",
    )
    (OUT / "core" / "state.js").write_text(
        HEADER
        + """export const state = {
  selectedAccount: null,
  selectedForRun: new Set(),
  accountsCache: [],
  proxyPoolCache: [],
  selectedProxies: new Set(),
  proxyViewFilters: new Set(),
  proxyFiltersInited: false,
  selectedAgents: new Set(),
  logOffset: 0,
  llmProviders: [],
  roleGroupsData: [],
  roleAssignments: {},
  roleGroupNames: [],
  editingDialogKey: null,
  editingAgentId: null,
  accountViewFilters: new Set(['outreach_eligible']),
  accountFiltersInited: false,
};
""",
        encoding="utf-8",
    )
    (OUT / "core" / "tabs.js").write_text(
        HEADER
        + "import { $, $$ } from './dom.js';\n\n"
        + slice_(29, 36)
        + "\nexport function initTabs() {\n"
        + "  $$('#tabNav .nav-item').forEach((btn) => {\n"
        + "    btn.addEventListener('click', () => showTab(btn.dataset.tab));\n"
        + "  });\n"
        + "}\n\nexport { showTab };\n",
        encoding="utf-8",
    )

    modules = {
        "status.js": (40, 95, ["refreshStatus", "refreshEngine", "refreshLogs"]),
        "config.js": (97, 197, ["loadConfig", "loadLlmProviders", "loadLlmModels", "initConfig"]),
        "proxies.js": (199, 1003, ["loadProxyPool", "bindAccountProxy", "initProxies", "proxySelectOptions"]),
        "accounts.js": (422, 810, ["loadAccounts", "selectAccount", "initAccounts"]),
        "roles.js": (1006, 1195, ["loadRoles", "initRoles"]),
        "dialogs.js": (1197, 1343, ["loadDialogs", "loadDialogSettings", "initDialogs"]),
        "agents.js": (1347, 1471, ["loadAgents", "initAgents"]),
        "outreach.js": (1473, 1502, ["initOutreach"]),
    }

    for fname, (start, end, exports) in modules.items():
        body = slice_(start, end)
        body = body.replace("let selectedAccount", "// selectedAccount in state")
        body = body.replace("let selectedForRun", "// selectedForRun in state")
        body = body.replace("let accountsCache", "// accountsCache in state")
        body = body.replace("let proxyPoolCache", "// proxyPoolCache in state")
        body = body.replace("let selectedProxies", "// selectedProxies in state")
        body = body.replace("let proxyViewFilters", "// proxyViewFilters in state")
        body = body.replace("let proxyFiltersInited", "// proxyFiltersInited in state")
        body = body.replace("let selectedAgents", "// selectedAgents in state")
        body = body.replace("let logOffset", "// logOffset in state")
        body = body.replace("let llmProviders", "// llmProviders in state")
        body = body.replace("let roleGroupsData", "// roleGroupsData in state")
        body = body.replace("let roleAssignments", "// roleAssignments in state")
        body = body.replace("let roleGroupNames", "// roleGroupNames in state")
        body = body.replace("let accountViewFilters", "// accountViewFilters in state")
        body = body.replace("let accountFiltersInited", "// accountFiltersInited in state")
        body = body.replace("let editingDialogKey", "// editingDialogKey in state")
        body = body.replace("let editingAgentId", "// editingAgentId in state")
        content = (
            HEADER
            + "import { $, $$, escapeHtml } from '../core/dom.js';\n"
            + "import { api } from '../core/api.js';\n"
            + "import { state } from '../core/state.js';\n"
        )
        if fname != "status.js":
            content += "import { refreshStatus } from './status.js';\n"
        if fname in ("proxies.js", "accounts.js", "agents.js", "outreach.js"):
            content += "import { loadProxyPool, proxySelectOptions } from './proxies.js';\n" if fname == "accounts.js" else ""
        content += "\n" + body + "\n"
        if fname == "config.js":
            content += "\nexport function initConfig() {\n  loadConfig();\n  $('#btnRefreshModels').onclick = async () => { await loadLlmModels($('#llmProvider').value); };\n}\n"
        elif fname == "proxies.js":
            content += "\nexport function initProxies() { /* listeners in module body */ }\n"
        elif fname == "accounts.js":
            content += "\nexport function initAccounts() { $('#btnRefreshAccounts').onclick = () => { loadAccounts(); refreshStatus(); }; }\n"
        elif fname == "roles.js":
            content += "\nexport function initRoles() {}\n"
        elif fname == "dialogs.js":
            content += "\nexport function initDialogs() {}\n"
        elif fname == "agents.js":
            content += "\nexport function initAgents() {}\n"
        elif fname == "outreach.js":
            content += "\nexport function initOutreach() {}\n"
        (OUT / "modules" / fname).write_text(content, encoding="utf-8")

    main = HEADER + """import { initTabs } from './core/tabs.js';
import { loadConfig, initConfig } from './modules/config.js';
import { loadProxyPool, initProxies } from './modules/proxies.js';
import { loadAccounts, initAccounts } from './modules/accounts.js';
import { loadRoles, initRoles } from './modules/roles.js';
import { loadDialogSettings, loadDialogs, initDialogs } from './modules/dialogs.js';
import { loadAgents, initAgents } from './modules/agents.js';
import { initOutreach } from './modules/outreach.js';
import { refreshStatus, refreshEngine, refreshLogs } from './modules/status.js';

async function tick() {
  await refreshStatus();
  await refreshEngine();
  await refreshLogs();
}

function boot() {
  initTabs();
  initConfig();
  initProxies();
  initAccounts();
  initRoles();
  initDialogs();
  initAgents();
  initOutreach();
  loadConfig();
  loadProxyPool();
  loadAccounts();
  loadRoles();
  loadDialogSettings();
  loadDialogs();
  loadAgents();
  refreshStatus();
  setInterval(tick, 1500);
}

boot();
"""
    (OUT / "main.js").write_text(main, encoding="utf-8")
    print("Wrote modules to", OUT)

if __name__ == "__main__":
    main()
