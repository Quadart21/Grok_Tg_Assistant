/* Kot_Teamlead */
(function () {
  const P = window.Panel = window.Panel || {};
  P.$ = (sel) => document.querySelector(sel);
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

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);


P.escapeHtml = function(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

P.api = async function(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

P.syncPageHeader = function(name) {
  const panel = P.$(`#panel-${name}`);
  const title = panel?.querySelector(".page-header h2")?.textContent?.trim() || "Панель";
  const lead = panel?.querySelector(".page-header .lead")?.textContent?.trim() || "";
  const titleEl = P.$("#pageTitle");
  const leadEl = P.$("#pageLead");
  if (titleEl) titleEl.textContent = title;
  if (leadEl) leadEl.textContent = lead;
}

P.showTab = function(name) {
  P.$$("#tabNav [data-tab]").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  P.$$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  P.syncPageHeader(name);
  try {
    localStorage.setItem("panel.activeTab", name);
  } catch (_) {}
}

P.initNavigation = function() {
  P.$$("#tabNav [data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => P.showTab(btn.dataset.tab));
  });
  let initialTab = "outreach";
  try {
    initialTab = localStorage.getItem("panel.activeTab") || initialTab;
  } catch (_) {}
  P.showTab(initialTab);
}


P.refreshStatus = async function() {
  const s = await P.api("/api/status");
  const parts = [];
  parts.push(s.telegram_ok ? "✓ Telegram" : "✗ Telegram");
  const aiLabel = s.llm_provider_name || "AI";
  parts.push(s.llm_ok ? `✓ ${aiLabel}` : `✗ ${aiLabel}`);
  if (s.llm_model) parts.push(s.llm_model);
  parts.push(`аккаунтов: ${s.accounts_count}`);
  parts.push(`прокси: ${s.proxies_count}/${s.accounts_count}`);
  if (s.paused_dialogs) parts.push(`на паузе: ${s.paused_dialogs}`);
  if (s.agents_count) parts.push(`агентов: ${s.agents_count}`);
  P.$("#statusBar").textContent = parts.join(" · ");
  P.$("#sessionsPath").textContent = s.sessions_path;
  const badge = P.$("#runBadge");
  const running = s.running || s.agent_running || s.group_chat_running;
  if (s.group_chat_running && (s.running || s.agent_running)) badge.textContent = "несколько режимов";
  else if (s.running && s.agent_running) badge.textContent = "рассылка + секретарь";
  else if (s.running) badge.textContent = "рассылка";
  else if (s.agent_running) badge.textContent = "секретарь";
  else if (s.group_chat_running) badge.textContent = "групповой чат";
  else badge.textContent = "остановлено";
  badge.classList.toggle("running", running);
  P.$("#btnStop").disabled = !s.running;
  P.$("#btnStart").disabled = s.running;
  P.$("#btnResume").disabled = s.running;
  P.$("#btnStopAgents").disabled = !s.agent_running;
  P.$("#btnStartAgents").disabled = s.agent_running;
  const btnStopGc = P.$("#btnStopGroupChat");
  const btnStartGc = P.$("#btnStartGroupChat");
  if (btnStopGc) btnStopGc.disabled = !s.group_chat_running;
  if (btnStartGc) btnStartGc.disabled = !!s.group_chat_running;
}

P.refreshEngine = async function() {
  const e = await P.api("/api/engine");
  if (e.running) {
    P.$("#engineStats").textContent =
      `Первых: ${e.success}/${e.total} · Ответов: ${e.replies_sent} · Ошибок: ${e.failed} · Диалогов: ${e.active_dialogs}`;
  }
  try {
    const a = await P.api("/api/agents/stats");
    const el = P.$("#agentStats");
    if (el) {
      if (a.running) {
        el.className = "chip ok";
        el.textContent = `Онлайн: ${a.active_accounts} · Диалогов: ${a.active_dialogs} · Ответов: ${a.replies_sent}`;
      } else {
        el.className = "chip muted";
        el.textContent = "Остановлен";
      }
    }
  } catch (_) {}
  try {
    await P.refreshGroupChatStatus();
  } catch (_) {}
}

P.refreshLogs = async function() {
  const { lines, total } = await P.api(`/api/logs?offset=${P.state.logOffset}`);
  if (lines.length) {
    const box = P.$("#logBox");
    box.textContent += lines.join("\n") + "\n";
    box.scrollTop = box.scrollHeight;
    P.state.logOffset = total;
  }
}

P.updateLlmHint = function(live) {
  const p = P.state.llmProviders.find((x) => x.id === P.$("#llmProvider").value);
  if (!p) return;
  const src = live ? "список загружен с API провайдера" : "список по умолчанию — вставьте ключ и нажмите ↻";
  P.$("#llmModelHint").innerHTML = `${src} · <a href="${p.docs_url}" target="_blank">получить ключ</a>`;
}

P.renderLlmModelSelect = function(models, selected) {
  const sel = P.$("#llmModel");
  if (!models.length) {
    sel.innerHTML = `<option value="">— нет моделей —</option>`;
    return;
  }
  const opts = models.map((m) =>
    `<option value="${P.escapeHtml(m)}" ${m === selected ? "selected" : ""}>${P.escapeHtml(m)}</option>`);
  if (selected && !models.includes(selected)) {
    opts.unshift(`<option value="${P.escapeHtml(selected)}" selected>${P.escapeHtml(selected)} (сохранённая)</option>`);
  }
  sel.innerHTML = opts.join("");
}

P.loadLlmModels = async function(provider, selected) {
  const data = await P.api(`/api/llm/models?provider=${encodeURIComponent(provider)}`);
  P.renderLlmModelSelect(data.models || [], selected || data.selected_model || "");
  P.updateLlmHint(data.live);
  return data;
}

P.loadLlmProviders = async function() {
  P.state.llmProviders = await P.api("/api/llm/providers");
  const sel = P.$("#llmProvider");
  sel.innerHTML = P.state.llmProviders.map((p) =>
    `<option value="${P.escapeHtml(p.id)}">${P.escapeHtml(p.name)}</option>`).join("");
  sel.onchange = async () => {
    await P.loadLlmModels(sel.value);
  };
}

P.syncLocalLlmUi = function() {
  const isLocal = P.$("#llmProvider").value === "local";
  const box = P.$("#localLlmBox");
  if (box) box.classList.toggle("hidden", !isLocal);
}

P.loadConfig = async function() {
  if (!P.state.llmProviders.length) await P.loadLlmProviders();
  const c = await P.api("/api/config");
  P.$("#apiId").value = c.telegram_api_id || "";
  P.$("#apiHash").value = c.telegram_api_hash || "";
  P.$("#llmProvider").value = c.llm_provider || "grok";
  P.$("#grokKey").value = c.grok_api_key || "";
  P.$("#grokModel").value = c.grok_model || "grok-3-mini";
  P.$("#openaiKey").value = c.openai_api_key || "";
  P.$("#geminiKey").value = c.gemini_api_key || "";
  P.$("#anthropicKey").value = c.anthropic_api_key || "";
  P.$("#deepseekKey").value = c.deepseek_api_key || "";
  P.$("#openrouterKey").value = c.openrouter_api_key || "";
  P.$("#localKey").value = c.local_api_key || "";
  P.$("#localBaseUrl").value = c.local_base_url || "http://127.0.0.1:8000/v1";
  P.syncLocalLlmUi();
  const savedModel = c.llm_model || c.grok_model || "grok-3-mini";
  await P.loadLlmModels(c.llm_provider || "grok", savedModel);
  P.$("#delayMsg").value = c.delay_between_messages_sec;
  P.$("#concurrent").value = c.max_concurrent_accounts;
  P.$("#replyMin").value = c.reply_delay_min_sec;
  P.$("#replyMax").value = c.reply_delay_max_sec;
  P.$("#language").value = c.message_language;
  P.$("#telegram2fa").value = c.telegram_2fa_password || "";
}

P.$("#llmProvider")?.addEventListener("change", async () => {
  P.syncLocalLlmUi();
  try {
    await P.loadLlmModels(P.$("#llmProvider").value, P.$("#llmModel").value);
  } catch (_) {}
});

P.$("#btnRefreshModels").onclick = async () => {
  try {
    if (P.$("#llmProvider").value === "local") {
      await P.api("/api/config", {
        method: "POST",
        body: JSON.stringify({
          telegram_api_id: parseInt(P.$("#apiId").value) || 0,
          telegram_api_hash: P.$("#apiHash").value,
          llm_provider: "local",
          llm_model: P.$("#llmModel").value || "mistral-24b-ru-uncensored",
          grok_api_key: P.$("#grokKey").value,
          grok_model: P.$("#grokModel").value || "grok-3-mini",
          openai_api_key: P.$("#openaiKey").value,
          gemini_api_key: P.$("#geminiKey").value,
          anthropic_api_key: P.$("#anthropicKey").value,
          deepseek_api_key: P.$("#deepseekKey").value,
          openrouter_api_key: P.$("#openrouterKey").value,
          local_api_key: P.$("#localKey").value,
          local_base_url: P.$("#localBaseUrl").value,
          delay_between_messages_sec: parseInt(P.$("#delayMsg").value) || 30,
          max_concurrent_accounts: parseInt(P.$("#concurrent").value) || 5,
          reply_delay_min_sec: parseInt(P.$("#replyMin").value) || 5,
          reply_delay_max_sec: parseInt(P.$("#replyMax").value) || 25,
          message_language: P.$("#language").value || "ru",
          telegram_2fa_password: P.$("#telegram2fa").value || "",
        }),
      });
    }
    await P.loadLlmModels(P.$("#llmProvider").value, P.$("#llmModel").value);
    P.$("#configMsg").textContent = "Список моделей обновлён";
  } catch (e) {
    P.$("#configMsg").textContent = e.message;
  }
};

P.$("#btnSaveConfig").addEventListener("click", async () => {
  try {
    await P.api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        telegram_api_id: parseInt(P.$("#apiId").value) || 0,
        telegram_api_hash: P.$("#apiHash").value,
        llm_provider: P.$("#llmProvider").value,
        llm_model: P.$("#llmModel").value,
        grok_api_key: P.$("#grokKey").value,
        grok_model: P.$("#llmProvider").value === "grok" ? (P.$("#llmModel").value || "grok-3-mini") : (P.$("#grokModel").value || "grok-3-mini"),
        openai_api_key: P.$("#openaiKey").value,
        gemini_api_key: P.$("#geminiKey").value,
        anthropic_api_key: P.$("#anthropicKey").value,
        deepseek_api_key: P.$("#deepseekKey").value,
        openrouter_api_key: P.$("#openrouterKey").value,
        local_api_key: P.$("#localKey").value,
        local_base_url: P.$("#localBaseUrl").value,
        delay_between_messages_sec: parseInt(P.$("#delayMsg").value) || 30,
        max_concurrent_accounts: parseInt(P.$("#concurrent").value) || 5,
        message_language: P.$("#language").value,
        reply_delay_min_sec: parseInt(P.$("#replyMin").value) || 5,
        reply_delay_max_sec: parseInt(P.$("#replyMax").value) || 25,
        telegram_2fa_password: P.$("#telegram2fa").value,
      }),
    });
    P.$("#configMsg").textContent = "Сохранено";
    await P.loadLlmModels(P.$("#llmProvider").value, P.$("#llmModel").value);
    P.refreshStatus();
  } catch (e) {
    P.$("#configMsg").textContent = e.message;
  }
});

P.PROXY_FILTERS = [
  { id: "ok", label: "Рабочие", test: (p) => p.status === "ok" },
  { id: "dead", label: "Мёртвые", test: (p) => p.status === "dead" },
  { id: "unknown", label: "Не проверены", test: (p) => p.status === "unknown" },
  { id: "free", label: "Свободные", test: (p) => !p.accounts_count },
  { id: "used", label: "Привязанные", test: (p) => p.accounts_count > 0 },
];

P.proxiesMatchingView = function(proxies) {
  if (!P.state.proxyViewFilters.size) return proxies;
  return proxies.filter((p) => {
    for (const fid of P.state.proxyViewFilters) {
      const f = P.PROXY_FILTERS.find((x) => x.id === fid);
      if (f && !f.test(p)) return false;
    }
    return true;
  });
}

P.initProxyFilterUi = function() {
  if (P.state.proxyFiltersInited) return;
  P.state.proxyFiltersInited = true;
  const chips = P.$("#proxySelectChips");
  const views = P.$("#proxyViewFilters");
  if (!chips || !views) return;

  P.PROXY_FILTERS.forEach((f) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "filter-chip";
    btn.dataset.filter = f.id;
    btn.addEventListener("click", () => P.selectProxiesByFilter(f.id));
    chips.appendChild(btn);

    const label = document.createElement("label");
    label.className = "filter-check inline-check";
    const inp = document.createElement("input");
    inp.type = "checkbox";
    inp.dataset.viewFilter = f.id;
    inp.addEventListener("change", () => {
      if (inp.checked) P.state.proxyViewFilters.add(f.id);
      else P.state.proxyViewFilters.delete(f.id);
      P.renderProxyPoolTable();
    });
    label.append(inp, ` ${f.label}`);
    views.appendChild(label);
  });
}

P.selectProxiesByFilter = function(filterId) {
  const f = P.PROXY_FILTERS.find((x) => x.id === filterId);
  if (!f) return;
  const ids = P.state.proxyPoolCache.filter(f.test).map((p) => p.id);
  if (!ids.length) return;
  P.state.selectedProxies = new Set(ids);
  P.renderProxyPoolTable();
}

P.updateProxySelectionUi = function() {
  const visible = P.proxiesMatchingView(P.state.proxyPoolCache);
  const visTotal = visible.length;
  const selected = P.state.selectedProxies.size;
  const visSelected = visible.filter((p) => P.state.selectedProxies.has(p.id)).length;
  const hint = P.$("#proxySelectedHint");
  if (hint) {
    hint.textContent = selected
      ? `Выбрано: ${selected}${visTotal ? ` · в таблице ${visSelected}/${visTotal}` : ""}`
      : (visTotal ? `В таблице: ${visTotal} из ${P.state.proxyPoolCache.length}` : "");
  }
  const master = P.$("#chkSelectAllProxies");
  if (master) {
    master.indeterminate = visSelected > 0 && visSelected < visTotal;
    master.checked = visTotal > 0 && visSelected === visTotal;
  }
  P.PROXY_FILTERS.forEach((f) => {
    const matched = P.state.proxyPoolCache.filter(f.test);
    const n = matched.length;
    const sel = matched.filter((p) => P.state.selectedProxies.has(p.id)).length;
    const btn = document.querySelector(`.filter-chip[data-filter="${f.id}"]`);
    if (!btn || !btn.closest("#proxySelectChips")) return;
    btn.disabled = n === 0;
    btn.classList.toggle("active", n > 0 && sel === n);
    btn.textContent = n > 0 && sel === n ? `${f.label} (${n}) ✓` : `${f.label} (${n})`;
  });
}

P.getSelectedProxyIdsOrAlert = function() {
  const ids = [...P.state.selectedProxies];
  if (!ids.length) {
    alert("Отметьте прокси в таблице пула или нажмите chip-фильтр");
    return null;
  }
  return ids;
}

P.proxyStatusChip = function(status) {
  if (status === "ok") return '<span class="chip ok">рабочий</span>';
  if (status === "dead") return '<span class="chip danger">мёртвый</span>';
  return '<span class="chip warn">не проверен</span>';
}

P.proxyPoolSelectable = function(p) {
  return p.status !== "dead";
}

P.proxySelectOptions = function(selectedId) {
  const opts = ['<option value="">— не выбран —</option>'];
  P.state.proxyPoolCache.filter(P.proxyPoolSelectable).forEach((p) => {
    const sel = p.id === selectedId ? " selected" : "";
    const used = p.accounts_count > 0 ? ` (${p.accounts_count})` : "";
    const country = p.country_label ? `${p.country_label} · ` : "";
    opts.push(`<option value="${P.escapeHtml(p.id)}"${sel}>${country}${P.escapeHtml(p.label || `${p.host}:${p.port}`)}${used}</option>`);
  });
  return opts.join("");
}

P.fillProxyPoolSelect = function(selectedId) {
  const sel = P.$("#proxyPoolSelect");
  if (!sel) return;
  sel.innerHTML = P.proxySelectOptions(selectedId);
  sel.disabled = !P.state.selectedAccount;
  P.$("#btnBindProxy").disabled = !P.state.selectedAccount;
  P.$("#btnClearProxy").disabled = !P.state.selectedAccount;
  P.$("#btnSaveProxy").disabled = !P.state.selectedAccount;
}

P.loadProxyPool = async function() {
  P.initProxyFilterUi();
  const data = await P.api("/api/proxy-pool");
  P.state.proxyPoolCache = data.items || [];
  P.renderProxyPoolTable();
  if (P.state.selectedAccount) {
    const acc = P.state.accountsCache.find((a) => a.id === P.state.selectedAccount);
    P.fillProxyPoolSelect(acc?.proxy_id || "");
  } else {
    P.fillProxyPoolSelect("");
  }
}

P.renderProxyPoolTable = function() {
  const tbody = P.$("#proxyPoolTable");
  if (!tbody) return;
  const visible = P.proxiesMatchingView(P.state.proxyPoolCache);
  if (!visible.length) {
    const msg = P.state.proxyViewFilters.size
      ? "Нет прокси по выбранным фильтрам"
      : "Пул пуст — вставьте список прокси выше";
    tbody.innerHTML = `<tr><td colspan="7" class="hint">${msg}</td></tr>`;
    P.updateProxySelectionUi();
    return;
  }
  tbody.innerHTML = visible.map((p) => {
    const accounts = (p.accounts || []).map((a) => P.escapeHtml(a)).join(", ");
    const ping = p.latency_ms ? `${p.latency_ms} ms` : "—";
    const checked = P.state.selectedProxies.has(p.id) ? "checked" : "";
    return `<tr class="${p.status === "dead" ? "row-inactive" : ""}${P.state.selectedProxies.has(p.id) ? " selected" : ""}">
      <td><input type="checkbox" class="proxy-chk" data-id="${P.escapeHtml(p.id)}" ${checked}></td>
      <td><strong>${P.escapeHtml(p.label || `${p.host}:${p.port}`)}</strong><br><span class="hint">${P.escapeHtml(p.type)} · ${P.escapeHtml(p.exit_ip || "—")}</span></td>
      <td>${p.country_label ? P.escapeHtml(p.country_label) : '<span class="chip muted">?</span>'}${p.country ? `<br><span class="hint">${P.escapeHtml(p.country)}</span>` : ""}</td>
      <td>${P.proxyStatusChip(p.status)}${p.last_error ? `<br><span class="hint">${P.escapeHtml(p.last_error)}</span>` : ""}</td>
      <td>${ping}</td>
      <td>${p.accounts_count ? `<span class="chip ok">${p.accounts_count}</span> ${accounts}` : '<span class="chip muted">0</span>'}</td>
      <td>
        <button type="button" class="btn btn-sm ghost proxy-pool-recheck" data-id="${P.escapeHtml(p.id)}" title="Перепроверить">↻</button>
        <button type="button" class="btn btn-sm danger proxy-pool-del" data-id="${P.escapeHtml(p.id)}">✕</button>
      </td>
    </tr>`;
  }).join("");

  tbody.querySelectorAll(".proxy-chk").forEach((el) => {
    el.onchange = (ev) => {
      const id = el.dataset.id;
      if (ev.target.checked) P.state.selectedProxies.add(id);
      else P.state.selectedProxies.delete(id);
      P.updateProxySelectionUi();
      el.closest("tr")?.classList.toggle("selected", ev.target.checked);
    };
  });

  tbody.querySelectorAll(".proxy-pool-recheck").forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      btn.disabled = true;
      try {
        await P.api(`/api/proxy-pool/${encodeURIComponent(btn.dataset.id)}/recheck`, { method: "POST" });
        await P.loadProxyPool();
        P.loadAccounts();
        P.refreshStatus();
      } catch (e) { alert(e.message); }
      btn.disabled = false;
    };
  });
  tbody.querySelectorAll(".proxy-pool-del").forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const id = btn.dataset.id;
      const item = P.state.proxyPoolCache.find((p) => p.id === id);
      const force = item?.accounts_count
        ? confirm(`Прокси привязан к ${item.accounts_count} акк. Удалить и отвязать?`)
        : confirm("Удалить прокси из пула?");
      if (!force) return;
      try {
        await P.api(`/api/proxy-pool/${encodeURIComponent(id)}?unbind=true`, { method: "DELETE" });
        P.state.selectedProxies.delete(id);
        await P.loadProxyPool();
        P.loadAccounts();
        P.refreshStatus();
      } catch (e) { alert(e.message); }
    };
  });
  P.updateProxySelectionUi();
}

P.bindAccountProxy = async function(accountId, proxyId) {
  await P.api(`/api/accounts/${encodeURIComponent(accountId)}/proxy/bind`, {
    method: "POST",
    body: JSON.stringify({ proxy_id: proxyId || null }),
  });
  await P.loadProxyPool();
  P.loadAccounts();
  P.refreshStatus();
}

P.loadAccounts = async function() {
  if (!P.state.proxyPoolCache.length) {
    try { await P.loadProxyPool(); } catch (_) {}
  }
  const rows = await P.api("/api/accounts");
  P.state.accountsCache = rows;
  P.initAccountFilterUi();
  const visible = P.accountsMatchingView(rows);
  const tbody = P.$("#accountsTable");
  tbody.innerHTML = "";
  if (!visible.length) {
    const msg = P.state.accountViewFilters.size
      ? "Нет аккаунтов по выбранным фильтрам показа"
      : "Нет аккаунтов в папке sessions";
    tbody.innerHTML = `<tr><td colspan="6" class="hint">${msg}</td></tr>`;
    P.updateAccountsSelectionUi();
    return;
  }
  visible.forEach((a) => {
    const tr = document.createElement("tr");
    if (a.id === P.state.selectedAccount) tr.classList.add("selected");
    if (!a.is_active) tr.classList.add("row-inactive");
    if (a.is_assistant) tr.classList.add("row-assistant");
    const checked = P.state.selectedForRun.has(a.id) ? "checked" : "";
    const canSelect = a.outreach_eligible;
    const twofaHint = a.twofa_file ? ` · 2FA: ${a.twofa_file}` : "";
    const typeChip = a.format === "tdata"
      ? '<span class="chip warn">tdata</span>'
      : '<span class="chip">session</span>';
    const sessionChip = a.session_ready
      ? `<span class="chip ok">${P.escapeHtml(a.session_file || "готов")}</span>`
      : (a.format === "tdata" ? '<span class="chip warn">нет</span>' : '<span class="chip muted">—</span>');
    const dupHint = a.is_duplicate ? ' <span class="chip warn">дубль</span>' : "";
    const assistantChip = a.is_assistant
      ? `<span class="chip violet" title="Только AI-агент">ассистент${a.assistant_name ? `: ${P.escapeHtml(a.assistant_name)}` : ""}</span>`
      : "";
    const inactiveChip = !a.is_active ? '<span class="chip danger">неактивен</span>' : "";
    const proxyCell = P.state.proxyPoolCache.length
      ? `<select class="proxy-bind-select assign-select" data-id="${P.escapeHtml(a.id)}" onclick="event.stopPropagation()">${P.proxySelectOptions(a.proxy_id || "")}</select>`
      : (a.proxy ? `<span class="chip">${P.escapeHtml(a.proxy)}</span>` : '<span class="chip muted">—</span>');
    tr.innerHTML = `
      <td><input type="checkbox" class="acc-chk" data-id="${P.escapeHtml(a.id)}" ${checked} ${canSelect ? "" : "disabled"} onclick="event.stopPropagation()"></td>
      <td><strong>${P.escapeHtml(a.id)}</strong> ${assistantChip} ${inactiveChip} ${dupHint}${twofaHint ? `<span class="hint">${P.escapeHtml(twofaHint)}</span>` : ""}</td>
      <td>${typeChip}</td>
      <td>${sessionChip}</td>
      <td>${proxyCell}</td>
      <td>${a.role ? P.escapeHtml(a.role) : '<span class="chip muted">—</span>'}</td>`;
    tr.onclick = () => P.selectAccount(a.id);
    tbody.appendChild(tr);
    const proxySel = tr.querySelector(".proxy-bind-select");
    if (proxySel) {
      proxySel.onchange = async (ev) => {
        ev.stopPropagation();
        try {
          await P.bindAccountProxy(a.id, ev.target.value || null);
        } catch (e) {
          alert(e.message);
          P.loadAccounts();
        }
      };
    }
    tr.querySelector("input").onchange = (ev) => {
      if (ev.target.checked) P.state.selectedForRun.add(a.id);
      else P.state.selectedForRun.delete(a.id);
      P.updateAccountsSelectionUi();
    };
  });
  P.purgeIneligibleSelection();
  P.updateAccountsSelectionUi();
  try { P.renderGroupChatAccounts(); } catch (_) {}
}

P.purgeIneligibleSelection = function() {
  [...P.state.selectedForRun].forEach((id) => {
    const a = P.state.accountsCache.find((x) => x.id === id);
    if (!a || !a.outreach_eligible) P.state.selectedForRun.delete(id);
  });
}

P.ACCOUNT_FILTERS = [
  { id: "outreach_eligible", label: "Для рассылки", test: (a) => a.outreach_eligible },
  { id: "inactive", label: "Неактивные", test: (a) => !a.is_active },
  { id: "assistants", label: "Ассистенты", test: (a) => a.is_assistant },
  { id: "not_assistant", label: "Не ассистент", test: (a) => !a.is_assistant },
  { id: "ready", label: "С .session", test: (a) => a.session_ready },
  { id: "unconverted", label: "Без .session", test: (a) => a.format === "tdata" && !a.session_ready },
  { id: "tdata", label: "tdata", test: (a) => a.format === "tdata" },
  { id: "native_session", label: "Файл .session", test: (a) => a.format === "session" },
  { id: "has_proxy", label: "С прокси", test: (a) => Boolean(a.proxy) },
  { id: "no_proxy", label: "Без прокси", test: (a) => !a.proxy },
  { id: "has_2fa", label: "С 2FA", test: (a) => Boolean(a.twofa_file) },
  { id: "no_2fa", label: "Без 2FA", test: (a) => !a.twofa_file },
  { id: "duplicates", label: "Дубли _1", test: (a) => a.is_duplicate },
  { id: "no_duplicates", label: "Без дублей", test: (a) => !a.is_duplicate },
  { id: "tg_import", label: "TG_*", test: (a) => a.id.startsWith("TG_") },
  { id: "phone", label: "Телефон", test: (a) => /^\d{10,15}$/.test(a.id) },
  { id: "has_role", label: "Со стилем", test: (a) => Boolean(a.role) },
  { id: "no_role", label: "Без стиля", test: (a) => !a.role },
];


P.accountsMatchingView = function(accounts) {
  if (!P.state.accountViewFilters.size) return accounts;
  return accounts.filter((a) => {
    for (const fid of P.state.accountViewFilters) {
      const f = P.ACCOUNT_FILTERS.find((x) => x.id === fid);
      if (f && !f.test(a)) return false;
    }
    return true;
  });
}

P.initAccountFilterUi = function() {
  if (P.state.accountFiltersInited) return;
  P.state.accountFiltersInited = true;
  const chips = P.$("#accountSelectChips");
  const views = P.$("#accountViewFilters");
  if (!chips || !views) return;

  P.ACCOUNT_FILTERS.forEach((f) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "filter-chip";
    btn.dataset.filter = f.id;
    btn.addEventListener("click", () => P.selectByAccountFilter(f.id));
    chips.appendChild(btn);

    const label = document.createElement("label");
    label.className = "filter-check inline-check";
    const inp = document.createElement("input");
    inp.type = "checkbox";
    inp.dataset.viewFilter = f.id;
    if (f.id === "outreach_eligible") inp.checked = true;
    inp.addEventListener("change", () => {
      if (inp.checked) P.state.accountViewFilters.add(f.id);
      else P.state.accountViewFilters.delete(f.id);
      P.loadAccounts();
    });
    label.append(inp, ` ${f.label}`);
    views.appendChild(label);
  });

  P.$("#btnResetViewFilters")?.addEventListener("click", () => {
    P.state.accountViewFilters.clear();
    P.state.accountViewFilters.add("outreach_eligible");
    views.querySelectorAll("input[type=checkbox]").forEach((i) => {
      i.checked = i.dataset.viewFilter === "outreach_eligible";
    });
    P.loadAccounts();
  });
}

P.selectByAccountFilter = function(filterId) {
  const f = P.ACCOUNT_FILTERS.find((x) => x.id === filterId);
  if (!f) return;
  const ids = P.state.accountsCache.filter((a) => f.test(a) && a.outreach_eligible).map((a) => a.id);
  if (!ids.length) return;
  const additive = Boolean(P.$("#chkSelectAdditive")?.checked);
  if (additive) {
    ids.forEach((id) => P.state.selectedForRun.add(id));
  } else {
    P.state.selectedForRun = new Set(ids);
  }
  document.querySelectorAll(".acc-chk").forEach((el) => {
    el.checked = P.state.selectedForRun.has(el.dataset.id);
  });
  P.updateAccountsSelectionUi();
}

P.updateAccountFilterCounts = function() {
  P.ACCOUNT_FILTERS.forEach((f) => {
    const matched = P.state.accountsCache.filter(f.test);
    const n = matched.length;
    const selected = matched.filter((a) => P.state.selectedForRun.has(a.id)).length;
    const btn = document.querySelector(`.filter-chip[data-filter="${f.id}"]`);
    if (!btn) return;
    btn.disabled = n === 0;
    btn.classList.toggle("active", n > 0 && selected === n);
    btn.textContent = n > 0 && selected === n ? `${f.label} (${n}) ✓` : `${f.label} (${n})`;
  });
}

P.updateAccountsSelectionUi = function() {
  const total = P.state.accountsCache.length;
  const visible = P.accountsMatchingView(P.state.accountsCache);
  const visTotal = visible.length;
  const selected = P.state.selectedForRun.size;
  const visSelected = visible.filter((a) => P.state.selectedForRun.has(a.id)).length;

  const hint = P.$("#accountsSelectedHint");
  if (hint) {
    if (!selected) {
      hint.textContent = P.state.accountViewFilters.size ? `В таблице: ${visTotal} из ${total}` : "";
    } else {
      hint.textContent = `Выбрано: ${selected}${total ? ` · в таблице ${visSelected}/${visTotal}` : ""}`;
    }
  }

  const master = P.$("#chkSelectAllAccounts");
  if (master) {
    master.indeterminate = visSelected > 0 && visSelected < visTotal;
    master.checked = visTotal > 0 && visSelected === visTotal;
  }

  P.updateAccountFilterCounts();
}

P.setAccountSelection = function(ids) {
  P.state.selectedForRun = new Set(ids);
  document.querySelectorAll(".acc-chk").forEach((el) => {
    el.checked = P.state.selectedForRun.has(el.dataset.id);
  });
  P.updateAccountsSelectionUi();
}

P.$("#chkSelectAllAccounts")?.addEventListener("change", (ev) => {
  const visible = P.accountsMatchingView(P.state.accountsCache).filter((a) => a.outreach_eligible);
  if (ev.target.checked) {
    P.setAccountSelection(visible.map((a) => a.id));
  } else {
    P.setAccountSelection([]);
  }
});

P.$("#btnClearAccountSelection")?.addEventListener("click", () => {
  P.setAccountSelection([]);
});

P.selectAccount = async function(id) {
  P.state.selectedAccount = id;
  P.$("#proxyAccountLabel").textContent = `Аккаунт: ${id}`;
  const acc = P.state.accountsCache.find((a) => a.id === id);
  P.fillProxyPoolSelect(acc?.proxy_id || "");
  P.loadAccounts();
  try {
    const p = await P.api(`/api/accounts/${encodeURIComponent(id)}/proxy`);
    if (P.$("#proxyPoolSelect") && p.proxy_id) P.$("#proxyPoolSelect").value = p.proxy_id;
    P.$("#proxyType").value = p.type || "socks5";
    P.$("#proxyHost").value = p.host || "";
    P.$("#proxyPort").value = p.port || "";
    P.$("#proxyUser").value = p.username || "";
    P.$("#proxyPass").value = p.password || "";
  } catch (_) {}
}

P.$("#btnRefreshAccounts").onclick = () => { P.loadAccounts(); P.refreshStatus(); };

P.convertTdata = async function(accountIds) {
  P.$("#convertMsg").textContent = "Конвертация...";
  try {
    const r = await P.api("/api/sessions/convert", {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds || [] }),
    });
    const lines = (r.results || []).map(
      (x) => `${x.success ? "✓" : "✗"} ${x.account_id}: ${x.message || x.output_path || ""}`
    );
    P.$("#convertMsg").textContent = `Готово: ${r.ok} успешно, ${r.failed} ошибок`;
    if (lines.length) alert(lines.join("\n"));
    P.loadAccounts();
    P.refreshStatus();
  } catch (e) {
    P.$("#convertMsg").textContent = e.message;
    alert(e.message);
  }
}

P.$("#btnConvertSelected").onclick = async () => {
  const rows = P.state.accountsCache.length ? P.state.accountsCache : await P.api("/api/accounts");
  if (!P.state.selectedForRun.size) {
    alert("Отметьте аккаунты галочками или нажмите «Без .session»");
    return;
  }
  const tdataIds = [...P.state.selectedForRun].filter(
    (id) => rows.find((a) => a.id === id && a.format === "tdata")
  );
  if (!tdataIds.length) return alert("Среди выбранных нет tdata");
  await P.convertTdata(tdataIds);
};

P.$("#btnConvertAll").onclick = async () => {
  const rows = await P.api("/api/accounts");
  const tdataIds = rows.filter((a) => a.format === "tdata").map((a) => a.id);
  if (!tdataIds.length) return alert("Нет tdata в папке sessions");
  await P.convertTdata(tdataIds);
};

P.bulkUpdateProfile = async function() {
  if (!P.state.selectedForRun.size) {
    alert("Отметьте аккаунты галочками в таблице");
    return;
  }
  const generateMode = P.$("#profileGenerateMode")?.value || "manual";
  const changeFirst = generateMode !== "manual" ? true : P.$("#profileChangeFirst")?.checked;
  const changeLast = generateMode === "names" || generateMode === "nicks"
    ? true
    : P.$("#profileChangeLast")?.checked;
  const changeUsername = generateMode !== "manual"
    ? Boolean(P.$("#profileWithUsername")?.checked)
    : P.$("#profileChangeUsername")?.checked;
  if (generateMode === "manual" && !changeFirst && !changeLast && !changeUsername) {
    alert("Включите хотя бы одно поле: имя, фамилию или username");
    return;
  }
  const accountIds = [...P.state.selectedForRun];
  const readyCount = accountIds.filter(
    (id) => P.state.accountsCache.find((a) => a.id === id && a.session_ready)
  ).length;
  if (!readyCount) {
    alert("Среди выбранных нет аккаунтов с рабочим .session");
    return;
  }
  const modeLabel = generateMode === "names"
    ? "случайные имя+фамилия"
    : generateMode === "nicks"
      ? "случайные ники"
      : "шаблоны";
  if (!confirm(`Сменить профиль у ${readyCount} аккаунт(ов)? Режим: ${modeLabel}`)) return;

  P.$("#profileMsg").textContent = "Обновление профилей...";
  try {
    const r = await P.api("/api/accounts/bulk-profile", {
      method: "POST",
      body: JSON.stringify({
        account_ids: accountIds,
        generate_mode: generateMode,
        lang: P.$("#profileLang")?.value || "ru",
        with_username: Boolean(P.$("#profileWithUsername")?.checked),
        change_first_name: changeFirst,
        change_last_name: changeLast,
        change_username: changeUsername,
        first_name: P.$("#profileFirstName")?.value || "",
        last_name: P.$("#profileLastName")?.value || "",
        username: P.$("#profileUsername")?.value || "",
        delay_sec: parseInt(P.$("#profileDelay")?.value, 10) || 3,
      }),
    });
    const lines = (r.results || []).map(
      (x) => `${x.success ? "✓" : "✗"} ${x.account_id}: ${x.message || ""}`
    );
    P.$("#profileMsg").textContent = r.message || "Готово";
    if (lines.length) alert(lines.join("\n"));
    P.refreshStatus();
  } catch (e) {
    P.$("#profileMsg").textContent = e.message;
    alert(e.message);
  }
}

P.syncProfileModeUi = function() {
  const mode = P.$("#profileGenerateMode")?.value || "manual";
  const manual = mode === "manual";
  P.$("#profileManualBlock")?.classList.toggle("hidden", !manual);
  P.$("#profileGenerateBlock")?.classList.toggle("hidden", manual);
}

P.previewProfileGeneration = async function() {
  const mode = P.$("#profileGenerateMode")?.value;
  if (mode === "manual") return;
  try {
    const r = await P.api("/api/accounts/profile-preview", {
      method: "POST",
      body: JSON.stringify({
        generate_mode: mode,
        lang: P.$("#profileLang")?.value || "ru",
        with_username: Boolean(P.$("#profileWithUsername")?.checked),
        count: 5,
      }),
    });
    const lines = (r.samples || []).map((s, i) => {
      const name = `${s.first_name || ""} ${s.last_name || ""}`.trim();
      const user = s.username ? ` @${s.username}` : "";
      return `${i + 1}. ${name}${user}`;
    });
    const box = P.$("#profilePreviewBox");
    if (box) {
      box.textContent = lines.join("\n") || "Нет примеров";
      box.classList.remove("hidden");
    }
  } catch (e) {
    alert(e.message);
  }
}

P.$("#profileGenerateMode")?.addEventListener("change", P.syncProfileModeUi);
P.$("#btnProfilePreview")?.addEventListener("click", P.previewProfileGeneration);
P.$("#btnBulkProfile")?.addEventListener("click", P.bulkUpdateProfile);
P.syncProfileModeUi();

P.$("#btnSaveProxy").onclick = async () => {
  if (!P.state.selectedAccount) return alert("Выберите аккаунт");
  try {
    await P.api(`/api/accounts/${encodeURIComponent(P.state.selectedAccount)}/proxy`, {
      method: "POST",
      body: JSON.stringify({
        type: P.$("#proxyType").value,
        host: P.$("#proxyHost").value,
        port: parseInt(P.$("#proxyPort").value) || 0,
        username: P.$("#proxyUser").value,
        password: P.$("#proxyPass").value,
      }),
    });
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
    alert("Прокси добавлен в пул и привязан");
  } catch (e) { alert(e.message); }
};

P.$("#btnBindProxy").onclick = async () => {
  if (!P.state.selectedAccount) return;
  try {
    await P.bindAccountProxy(P.state.selectedAccount, P.$("#proxyPoolSelect").value || null);
  } catch (e) { alert(e.message); }
};

P.$("#btnClearProxy").onclick = async () => {
  if (!P.state.selectedAccount) return;
  try {
    await P.bindAccountProxy(P.state.selectedAccount, null);
    P.fillProxyPoolSelect("");
  } catch (e) { alert(e.message); }
};

P.$("#btnImportProxyPool").onclick = async () => {
  const lines = P.$("#proxyPoolImport")?.value?.trim();
  if (!lines) return alert("Вставьте список прокси");
  P.$("#proxyPoolMsg").textContent = "Проверка прокси (страна, пинг)...";
  P.$("#btnImportProxyPool").disabled = true;
  try {
    const r = await P.api("/api/proxy-pool/import", {
      method: "POST",
      body: JSON.stringify({ lines, type: P.$("#proxyPoolType")?.value || "socks5" }),
    });
    const parts = [
      `добавлено: ${r.added}`,
      `дублей: ${r.skipped_duplicate}`,
      `мёртвых: ${r.skipped_dead}`,
    ];
    if (r.skipped_parse) parts.push(`ошибок строк: ${r.skipped_parse}`);
    parts.push(`всего в пуле: ${r.total}`);
    P.$("#proxyPoolMsg").textContent = parts.join(" · ");
    P.$("#proxyPoolImport").value = "";
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
    const added = (r.details || []).filter((d) => d.status === "added");
    if (added.length) {
      const sample = added.slice(0, 8).map((d) =>
        `✓ ${d.country_code || "?"} ${d.exit_ip || ""} (${d.latency_ms || "?"} ms)`
      ).join("\n");
      alert(`Добавлено ${r.added}:\n${sample}${added.length > 8 ? "\n..." : ""}`);
    } else if (!r.added) {
      alert("Ни один прокси не добавлен — проверьте список или дубликаты");
    }
  } catch (e) {
    P.$("#proxyPoolMsg").textContent = e.message;
    alert(e.message);
  }
  P.$("#btnImportProxyPool").disabled = false;
};

P.$("#btnRecheckProxyPool").onclick = async () => {
  P.$("#proxyPoolMsg").textContent = "Перепроверка всего пула...";
  P.$("#btnRecheckProxyPool").disabled = true;
  try {
    const r = await P.api("/api/proxy-pool/recheck", { method: "POST", body: JSON.stringify({ proxy_ids: [] }) });
    P.$("#proxyPoolMsg").textContent = `ok: ${r.added} · мёртвых: ${r.skipped_dead} · дублей: ${r.skipped_duplicate}`;
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
  } catch (e) {
    P.$("#proxyPoolMsg").textContent = e.message;
    alert(e.message);
  }
  P.$("#btnRecheckProxyPool").disabled = false;
};

P.$("#chkSelectAllProxies")?.addEventListener("change", (ev) => {
  const visible = P.proxiesMatchingView(P.state.proxyPoolCache);
  if (ev.target.checked) visible.forEach((p) => P.state.selectedProxies.add(p.id));
  else visible.forEach((p) => P.state.selectedProxies.delete(p.id));
  P.renderProxyPoolTable();
});

P.$("#btnClearProxySelection")?.addEventListener("click", () => {
  P.state.selectedProxies.clear();
  P.renderProxyPoolTable();
});

P.$("#btnProxyRecheckSelected")?.addEventListener("click", async () => {
  const ids = P.getSelectedProxyIdsOrAlert();
  if (!ids) return;
  P.$("#proxyPoolMsg").textContent = `Перепроверка ${ids.length} прокси...`;
  try {
    const r = await P.api("/api/proxy-pool/recheck", {
      method: "POST",
      body: JSON.stringify({ proxy_ids: ids }),
    });
    P.$("#proxyPoolMsg").textContent = `ok: ${r.added} · мёртвых: ${r.skipped_dead}`;
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
  } catch (e) {
    P.$("#proxyPoolMsg").textContent = e.message;
    alert(e.message);
  }
});

P.$("#btnProxyDeleteSelected")?.addEventListener("click", async () => {
  const ids = P.getSelectedProxyIdsOrAlert();
  if (!ids) return;
  const bound = ids.filter((id) => P.state.proxyPoolCache.find((p) => p.id === id)?.accounts_count);
  const msg = bound.length
    ? `Удалить ${ids.length} прокси? ${bound.length} привязаны к аккаунтам — отвязка автоматически.`
    : `Удалить ${ids.length} прокси из пула?`;
  if (!confirm(msg)) return;
  try {
    const r = await P.api("/api/proxy-pool/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ proxy_ids: ids, unbind: true }),
    });
    P.state.selectedProxies.clear();
    P.$("#proxyPoolMsg").textContent = `Удалено: ${r.deleted}`;
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
  } catch (e) {
    alert(e.message);
  }
});

P.$("#btnProxyPurgeDead")?.addEventListener("click", async () => {
  const dead = P.state.proxyPoolCache.filter((p) => p.status === "dead").length;
  if (!dead) return alert("Мёртвых прокси нет");
  if (!confirm(`Удалить все мёртвые прокси (${dead})?`)) return;
  try {
    const r = await P.api("/api/proxy-pool/purge-dead?unbind=true", { method: "POST" });
    P.state.selectedProxies.clear();
    P.$("#proxyPoolMsg").textContent = `Удалено мёртвых: ${r.deleted}`;
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
  } catch (e) {
    alert(e.message);
  }
});

P.$("#btnProxyAutoBind")?.addEventListener("click", async () => {
  const accountIds = P.state.selectedForRun.size ? [...P.state.selectedForRun] : [];
  const proxyIds = P.state.selectedProxies.size ? [...P.state.selectedProxies] : [];
  const accHint = accountIds.length
    ? `${accountIds.length} выбранных аккаунтов`
    : "аккаунтов без прокси";
  const proxyHint = proxyIds.length
    ? `${proxyIds.length} выбранных прокси`
    : "свободных рабочих прокси";
  if (!confirm(`Привязать ${proxyHint} к ${accHint} (1:1 по порядку)?`)) return;
  try {
    const r = await P.api("/api/proxy-pool/auto-bind", {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds, proxy_ids: proxyIds }),
    });
    P.$("#proxyPoolMsg").textContent = `Привязано пар: ${r.paired}`;
    if (r.paired) alert(`Привязано ${r.paired} пар`);
    else alert("Не удалось привязать — проверьте свободные прокси и аккаунты без прокси");
    await P.loadProxyPool();
    P.loadAccounts();
    P.refreshStatus();
  } catch (e) {
    alert(e.message);
  }
});

P.$("#btnRefreshProxyPool").onclick = async () => {
  await P.loadProxyPool();
  P.loadAccounts();
};


P.loadRoles = async function() {
  const r = await P.api("/api/roles");
  P.$("#defaultRole").value = r.default_role || "";
  if (r.master_prompt) {
    P.$("#masterEnabled").checked = r.master_prompt.enabled !== false;
    P.$("#masterPrompt").value = r.master_prompt.text || "";
  }
  P.state.roleGroupsData = r.groups || [];
  P.state.roleAssignments = r.assignments || {};
  P.state.roleGroupNames = P.state.roleGroupsData.map((g) => g.name);
  P.renderRoleGroups();
  P.renderRoleAssignments(r.all_accounts || []);
}

P.renderRoleGroups = function() {
  const box = P.$("#roleGroups");
  box.innerHTML = "";
  if (!P.state.roleGroupsData.length) {
    box.innerHTML = '<p class="hint">Нажмите «+ Добавить роль», чтобы создать первую роль</p>';
    return;
  }
  P.state.roleGroupsData.forEach((g, i) => {
    const div = document.createElement("div");
    div.className = "role-group";
    div.innerHTML = `
      <input type="text" class="rg-name" data-i="${i}" value="${P.escapeHtml(g.name || "")}" placeholder="Название роли">
      <label class="label">Текст роли для Grok (слой поверх мастера)</label>
      <textarea class="rg-prompt" data-i="${i}" rows="3">${P.escapeHtml(g.role_prompt || "")}</textarea>
      <button type="button" class="btn btn-sm danger btn-del-g" data-i="${i}">Удалить</button>`;
    box.appendChild(div);
  });
  box.querySelectorAll(".btn-del-g").forEach((b) => {
    b.onclick = () => {
      const idx = +b.dataset.i;
      const removed = P.state.roleGroupsData[idx]?.name;
      P.state.roleGroupsData.splice(idx, 1);
      if (removed) {
        Object.keys(P.state.roleAssignments).forEach((acc) => {
          if (P.state.roleAssignments[acc] === removed) P.state.roleAssignments[acc] = "";
        });
      }
      P.syncGroupNamesFromDom();
      P.renderRoleGroups();
      P.renderRoleAssignments(Object.keys(P.state.roleAssignments));
    };
  });
  box.querySelectorAll(".rg-name").forEach((inp) => {
    inp.addEventListener("change", () => {
      const idx = +inp.dataset.i;
      const oldName = P.state.roleGroupsData[idx]?.name;
      const newName = inp.value.trim();
      P.state.roleGroupsData[idx].name = newName;
      if (oldName && oldName !== newName) {
        Object.keys(P.state.roleAssignments).forEach((acc) => {
          if (P.state.roleAssignments[acc] === oldName) P.state.roleAssignments[acc] = newName;
        });
      }
      P.syncGroupNamesFromDom();
      P.renderRoleAssignments(Object.keys(P.state.roleAssignments));
    });
  });
}

P.syncGroupNamesFromDom = function() {
  P.state.roleGroupNames = [];
  document.querySelectorAll(".rg-name").forEach((inp, i) => {
    const name = inp.value.trim() || `Роль ${i + 1}`;
    if (P.state.roleGroupsData[i]) P.state.roleGroupsData[i].name = name;
    P.state.roleGroupNames.push(name);
  });
}

P.buildRoleOptions = function(selected) {
  let html = `<option value="" ${!selected ? "selected" : ""}>— По умолчанию —</option>`;
  P.state.roleGroupNames.forEach((name) => {
    if (!name) return;
    html += `<option value="${P.escapeHtml(name)}" ${selected === name ? "selected" : ""}>${P.escapeHtml(name)}</option>`;
  });
  return html;
}

P.renderRoleAssignments = function(allAccounts) {
  P.syncGroupNamesFromDom();
  const tbody = P.$("#roleAssignTable");
  tbody.innerHTML = "";
  if (!allAccounts.length) {
    tbody.innerHTML = '<tr><td colspan="2" class="hint">Нет готовых аккаунтов — сначала сконвертируйте tdata во вкладке «3. Аккаунты»</td></tr>';
    return;
  }
  allAccounts.forEach((accId) => {
    if (!(accId in P.state.roleAssignments)) P.state.roleAssignments[accId] = "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${P.escapeHtml(accId)}</strong></td>
      <td><select class="assign-select" data-acc="${P.escapeHtml(accId)}">${P.buildRoleOptions(P.state.roleAssignments[accId] || "")}</select></td>`;
    tbody.appendChild(tr);
    tr.querySelector("select").addEventListener("change", (ev) => {
      P.state.roleAssignments[accId] = ev.target.value;
    });
  });
}

P.collectMasterPayload = function() {
  return {
    enabled: P.$("#masterEnabled").checked,
    text: P.$("#masterPrompt").value,
  };
}

P.saveMasterPromptData = async function() {
  const master = P.collectMasterPayload();
  try {
    await P.api("/api/master-prompt", { method: "POST", body: JSON.stringify(master) });
    return;
  } catch (e) {
    if (!String(e.message).includes("Not Found")) throw e;
  }
  await P.api("/api/roles", {
    method: "POST",
    body: JSON.stringify({ master_prompt: master }),
  });
}

P.loadMasterPrompt = async function() {
  try {
    const m = await P.api("/api/master-prompt");
    P.$("#masterEnabled").checked = m.enabled !== false;
    P.$("#masterPrompt").value = m.text || "";
  } catch (_) {
    /* P.loadRoles заполнит master_prompt из /api/roles */
  }
}

P.$("#btnSaveMaster").onclick = async () => {
  try {
    await P.saveMasterPromptData();
    P.$("#masterMsg").textContent = "Сохранено";
  } catch (e) {
    P.$("#masterMsg").textContent = e.message.includes("Not Found")
      ? "Перезапустите start.bat и попробуйте снова"
      : e.message;
  }
};

P.$("#btnAddGroup").onclick = () => {
  P.state.roleGroupsData.push({ name: `Роль ${P.state.roleGroupsData.length + 1}`, role_prompt: "Вы вежливый собеседник." });
  P.syncGroupNamesFromDom();
  P.renderRoleGroups();
  P.api("/api/roles").then((r) => P.renderRoleAssignments(r.all_accounts || Object.keys(P.state.roleAssignments)));
};

P.$("#btnRefreshRoleAssign").onclick = async () => {
  document.querySelectorAll(".rg-prompt").forEach((ta) => {
    const i = +ta.dataset.i;
    if (P.state.roleGroupsData[i]) P.state.roleGroupsData[i].role_prompt = ta.value;
  });
  P.syncGroupNamesFromDom();
  const r = await P.api("/api/roles");
  P.renderRoleAssignments(r.all_accounts || []);
};

P.$("#btnSaveRoles").onclick = async () => {
  P.syncGroupNamesFromDom();
  const groups = [];
  document.querySelectorAll(".role-group").forEach((el, i) => {
    groups.push({
      name: el.querySelector(".rg-name")?.value.trim() || `Роль ${i + 1}`,
      role_prompt: el.querySelector(".rg-prompt")?.value || "",
    });
  });
  document.querySelectorAll(".assign-select").forEach((sel) => {
    P.state.roleAssignments[sel.dataset.acc] = sel.value;
  });
  try {
    await P.api("/api/roles", {
      method: "POST",
      body: JSON.stringify({
        default_role: P.$("#defaultRole").value,
        groups,
        assignments: P.state.roleAssignments,
        master_prompt: P.collectMasterPayload(),
      }),
    });
    P.$("#rolesMsg").textContent = "Сохранено";
    P.loadRoles();
    P.loadAccounts();
  } catch (e) {
    P.$("#rolesMsg").textContent = e.message;
  }
};

P.loadDialogs = async function() {
  const rows = await P.api("/api/dialogs");
  const statusChip = (s) => {
    if (s === "активен") return '<span class="chip ok">активен</span>';
    if (s === "на паузе") return '<span class="chip warn">пауза</span>';
    return `<span class="chip muted">${P.escapeHtml(s)}</span>`;
  };
  P.$("#dialogsTable").innerHTML = rows.map((d) => `
    <tr>
      <td>${P.escapeHtml(d.account_id)}</td>
      <td>@${P.escapeHtml(d.target)}</td>
      <td><span class="chip">${d.dialog_mode === "agent" ? "агент" : "рассылка"}</span></td>
      <td>${statusChip(d.status_label)}</td>
      <td>${d.auto_reply ? '<span class="chip ok">✓</span>' : '<span class="chip muted">—</span>'}</td>
      <td>${d.replies_count}${d.max_replies ? "/" + d.max_replies : ""}</td>
      <td>${d.messages_count}</td>
      <td>${d.last_activity || "—"}</td>
      <td class="btn-row">
        <button class="btn btn-sm ghost open-dlg" data-key="${P.escapeHtml(d.key)}">Открыть</button>
        <button class="btn btn-sm danger clear-dlg" data-key="${P.escapeHtml(d.key)}" title="Стереть память">🗑</button>
      </td>
    </tr>`).join("") || "<tr><td colspan='9' class='hint'>Нет диалогов</td></tr>";
  document.querySelectorAll(".open-dlg").forEach((btn) => {
    btn.onclick = () => P.openDialogModal(btn.dataset.key);
  });
  document.querySelectorAll(".clear-dlg").forEach((btn) => {
    btn.onclick = () => P.clearDialogMemory(btn.dataset.key);
  });
}

P.clearDialogMemory = async function(key, closeModal = false) {
  if (!key) return;
  if (!confirm("Стереть память этого диалога? История удалится, при запуске он не возобновится.")) return;
  await P.api(`/api/dialogs/${encodeURIComponent(key)}/clear-memory`, { method: "POST" });
  if (closeModal) P.$("#dialogModal").classList.add("hidden");
  P.loadDialogs();
}


P.DIALOG_SETTING_FIELDS = [
  ["history_for_grok", "Сообщений истории для AI", "number"],
  ["max_stored_messages", "Хранить сообщений в памяти", "number"],
  ["grok_temperature", "Креативность AI (0–1)", "number", "0.1"],
  ["grok_max_tokens", "Макс. длина ответа (токены)", "number"],
  ["reply_delay_min_sec", "Пауза ответа, от (сек)", "number"],
  ["reply_delay_max_sec", "Пауза ответа, до (сек)", "number"],
  ["typing_delay_sec", "Доп. пауза «печатает» (сек)", "number"],
  ["batch_messages_sec", "Ждать сообщения (сек)", "number"],
  ["min_user_message_chars", "Мин. длина сообщения пользователя", "number"],
  ["max_replies_per_dialog", "Лимит ответов на диалог (0=∞)", "number"],
  ["max_replies_per_hour", "Лимит ответов в час на аккаунт", "number"],
  ["first_message_max_chars", "Макс. длина первого сообщения", "number"],
  ["sync_history_limit", "Подтягивать сообщений при возобновлении", "number"],
  ["split_at_chars", "Делить длинные ответы после символов", "number"],
];

P.loadDialogSettings = async function() {
  const s = await P.api("/api/dialog-settings");
  const form = P.$("#dialogSettingsForm");
  form.innerHTML = P.DIALOG_SETTING_FIELDS.map(([key, label, type, step]) => `
    <div><label class="label">${label}</label>
    <input type="${type}" id="ds_${key}" value="${s[key] ?? ""}" ${step ? `step="${step}"` : ""}></div>`).join("");
  form.innerHTML += `
    <div><label class="label"><input type="checkbox" id="ds_split_long_messages" ${s.split_long_messages ? "checked" : ""}> Делить длинные ответы</label></div>
    <div><label class="label"><input type="checkbox" id="ds_sync_history_on_resume" ${s.sync_history_on_resume ? "checked" : ""}> Синхронизировать историю при возобновлении</label></div>`;
  P.$("#ignoreKeywords").value = Array.isArray(s.ignore_keywords) ? s.ignore_keywords.join(", ") : s.ignore_keywords;
  P.$("#globalExtraPrompt").value = s.global_extra_prompt || "";
}

P.$("#btnSaveDialogSettings").onclick = async () => {
  const payload = {};
  P.DIALOG_SETTING_FIELDS.forEach(([key, , type]) => {
    const el = document.getElementById(`ds_${key}`);
    payload[key] = type === "number" ? parseFloat(el.value) || 0 : el.value;
  });
  payload.split_long_messages = P.$("#ds_split_long_messages")?.checked || false;
  payload.sync_history_on_resume = P.$("#ds_sync_history_on_resume")?.checked ?? true;
  payload.ignore_keywords = P.$("#ignoreKeywords").value.split(",").map((x) => x.trim()).filter(Boolean);
  payload.global_extra_prompt = P.$("#globalExtraPrompt").value;
  try {
    await P.api("/api/dialog-settings", { method: "POST", body: JSON.stringify(payload) });
    P.$("#dialogSettingsMsg").textContent = "Сохранено";
  } catch (e) { P.$("#dialogSettingsMsg").textContent = e.message; }
};

P.openDialogModal = async function(key) {
  P.state.currentDialogKey = key;
  const d = await P.api(`/api/dialogs/${encodeURIComponent(key)}`);
  P.$("#modalTitle").textContent = `${d.account_id} → @${d.target}`;
  P.$("#dlgStatus").value = d.status;
  P.$("#dlgAutoReply").checked = d.auto_reply;
  P.$("#dlgMaxReplies").value = d.max_replies || 0;
  P.$("#dlgRepliesCount").value = d.replies_count || 0;
  P.$("#dlgGoal").value = d.goal || "";
  P.$("#dlgExtra").value = d.dialog_extra_context || "";
  P.$("#dlgNotes").value = d.notes || "";
  P.$("#dlgHistory").innerHTML = d.messages.map((m) =>
    `<div class="${m.role === "user" ? "msg-user" : "msg-bot"}">
      <span class="msg-meta">${m.role === "user" ? "Они" : "Мы"} · ${m.ts}</span><br>${P.escapeHtml(m.content)}
    </div>`).join("") || "<p class='hint'>Нет сообщений</p>";
  P.$("#dialogModal").classList.remove("hidden");
}

P.$("#btnCloseModal").onclick = () => P.$("#dialogModal").classList.add("hidden");

P.$("#btnSaveDialog").onclick = async () => {
  if (!P.state.currentDialogKey) return;
  await P.api(`/api/dialogs/${encodeURIComponent(P.state.currentDialogKey)}`, {
    method: "PATCH",
    body: JSON.stringify({
      status: P.$("#dlgStatus").value,
      auto_reply: P.$("#dlgAutoReply").checked,
      max_replies: parseInt(P.$("#dlgMaxReplies").value) || 0,
      replies_count: parseInt(P.$("#dlgRepliesCount").value) || 0,
      goal: P.$("#dlgGoal").value,
      dialog_extra_context: P.$("#dlgExtra").value,
      notes: P.$("#dlgNotes").value,
    }),
  });
  P.loadDialogs();
  alert("Сохранено");
};

P.$("#btnClearDialogMemory").onclick = async () => {
  if (!P.state.currentDialogKey) return;
  await P.clearDialogMemory(P.state.currentDialogKey, true);
};

P.$("#btnDeleteDialog").onclick = async () => {
  if (!P.state.currentDialogKey || !confirm("Удалить диалог полностью из списка?")) return;
  await P.api(`/api/dialogs/${encodeURIComponent(P.state.currentDialogKey)}`, { method: "DELETE" });
  P.$("#dialogModal").classList.add("hidden");
  P.loadDialogs();
};

P.$("#btnClearAllDialogs").onclick = async () => {
  if (!confirm("Удалить память ВСЕХ диалогов? Это нельзя отменить.")) return;
  const r = await P.api("/api/dialogs/clear-all", {
    method: "POST",
    body: JSON.stringify({ delete_completely: true }),
  });
  alert(`Очищено диалогов: ${r.cleared ?? 0}`);
  P.loadDialogs();
};

P.$("#btnRefreshDialogs").onclick = P.loadDialogs;


P.loadAgents = async function() {
  const rows = await P.api("/api/agents");
  const tbody = P.$("#agentsTable");
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="hint">Нажмите «+ Добавить агента»</td></tr>';
    return;
  }
  if (!P.state.selectedAgents.size) {
    rows.filter((a) => a.enabled).forEach((a) => P.state.selectedAgents.add(a.account_id));
  }
  rows.forEach((a) => {
    const tr = document.createElement("tr");
    const checked = P.state.selectedAgents.has(a.account_id) ? "checked" : "";
    const statusHtml = a.running
      ? '<span class="chip ok">онлайн</span>'
      : a.enabled
        ? '<span class="chip">готов</span>'
        : '<span class="chip muted">выкл</span>';
    const warn = !a.account_exists ? ' <span class="chip warn">нет сессии</span>' : "";
    tr.innerHTML = `
      <td><input type="checkbox" data-id="${P.escapeHtml(a.account_id)}" ${checked}></td>
      <td><strong>${P.escapeHtml(a.account_id)}</strong>${warn}</td>
      <td>${P.escapeHtml(a.name || "Секретарь")}</td>
      <td><span class="chip">${P.escapeHtml(a.language || "ru")}</span></td>
      <td>${statusHtml}</td>
      <td><button class="btn btn-sm ghost edit-agent" data-id="${P.escapeHtml(a.account_id)}">Настроить</button></td>`;
    tbody.appendChild(tr);
    tr.querySelector("input").onchange = (ev) => {
      if (ev.target.checked) P.state.selectedAgents.add(a.account_id);
      else P.state.selectedAgents.delete(a.account_id);
    };
    tr.querySelector(".edit-agent").onclick = () => P.openAgentModal(a.account_id, rows);
  });
}

P.openAgentModal = async function(accountId, cachedRows) {
  P.state.editingAgentId = accountId || null;
  const accounts = await P.api("/api/accounts");
  const rows = cachedRows || await P.api("/api/agents");
  const agent = accountId ? rows.find((a) => a.account_id === accountId) : null;
  const candidates = accounts.filter((a) => {
    if (agent && a.id === agent.account_id) return true;
    return a.is_active && !a.is_assistant;
  });
  const select = P.$("#agentAccount");
  if (!candidates.length) {
    alert("Нет свободных активных аккаунтов. Сконвертируйте .session или снимите другого ассистента.");
    return;
  }
  select.innerHTML = candidates.map((a) =>
    `<option value="${P.escapeHtml(a.id)}">${P.escapeHtml(a.id)}</option>`).join("");
  P.$("#agentModalTitle").textContent = agent ? `Агент: ${agent.account_id}` : "Новый AI-агент";
  select.value = agent?.account_id || candidates[0].id;
  select.disabled = !!agent;
  P.$("#agentName").value = agent?.name || "Секретарь";
  P.$("#agentPrompt").value = agent?.prompt || "";
  P.$("#agentGoal").value = agent?.goal || "";
  P.$("#agentLanguage").value = agent?.language || "ru";
  P.$("#agentExtra").value = agent?.extra_context || "";
  P.$("#agentAllowed").value = Array.isArray(agent?.allowed_users) ? agent.allowed_users.join(", ") : "";
  P.$("#agentBlocked").value = Array.isArray(agent?.blocked_users) ? agent.blocked_users.join(", ") : "";
  P.$("#agentEnabled").checked = agent?.enabled !== false;
  P.$("#btnDeleteAgent").style.display = agent ? "" : "none";
  P.$("#agentModal").classList.remove("hidden");
}

P.$("#btnAddAgent").onclick = () => P.openAgentModal(null);
P.$("#btnCloseAgentModal").onclick = () => P.$("#agentModal").classList.add("hidden");
P.$("#btnRefreshAgents").onclick = P.loadAgents;

P.$("#btnSaveAgent").onclick = async () => {
  const payload = {
    account_id: P.$("#agentAccount").value,
    name: P.$("#agentName").value,
    prompt: P.$("#agentPrompt").value,
    goal: P.$("#agentGoal").value,
    language: P.$("#agentLanguage").value,
    extra_context: P.$("#agentExtra").value,
    allowed_users: P.$("#agentAllowed").value.split(",").map((x) => x.trim()).filter(Boolean),
    blocked_users: P.$("#agentBlocked").value.split(",").map((x) => x.trim()).filter(Boolean),
    enabled: P.$("#agentEnabled").checked,
  };
  try {
    await P.api("/api/agents", { method: "POST", body: JSON.stringify(payload) });
    P.$("#agentModal").classList.add("hidden");
    P.state.selectedAgents.add(payload.account_id);
    P.loadAgents();
    P.loadAccounts();
    P.refreshStatus();
    P.$("#agentsMsg").textContent = "Сохранено";
  } catch (e) {
    P.$("#agentsMsg").textContent = e.message;
  }
};

P.$("#btnDeleteAgent").onclick = async () => {
  const id = P.$("#agentAccount").value;
  if (!id || !confirm(`Удалить агента ${id}?`)) return;
  await P.api(`/api/agents/${encodeURIComponent(id)}`, { method: "DELETE" });
  P.state.selectedAgents.delete(id);
  P.$("#agentModal").classList.add("hidden");
  P.loadAgents();
  P.loadAccounts();
  P.refreshStatus();
};

P.$("#btnStartAgents").onclick = async () => {
  const ids = P.state.selectedAgents.size ? [...P.state.selectedAgents] : [];
  if (!ids.length) return alert("Выберите агентов в таблице");
  try {
    await P.api("/api/agents/start", { method: "POST", body: JSON.stringify({ account_ids: ids }) });
    P.refreshStatus();
    P.loadAgents();
    P.$("#agentsMsg").textContent = "Секретарь запущен";
  } catch (e) {
    alert(e.message);
  }
};

P.$("#btnStopAgents").onclick = async () => {
  await P.api("/api/agents/stop", { method: "POST" });
  P.refreshStatus();
  P.loadAgents();
};

P.GROUP_CHAT_SETTING_FIELDS = [
  "use_schedule", "resume_next_day", "online_probability",
  "quiet_break_min_min", "quiet_break_max_min", "quiet_break_chance",
  "max_messages_per_account_session", "max_messages_per_account_hour",
  "max_messages_per_account_day", "max_messages_group_day",
  "burst_min", "burst_max", "max_consecutive_same_speaker",
  "delay_between_speakers_min_sec", "delay_between_speakers_max_sec",
  "delay_within_burst_min_sec", "delay_within_burst_max_sec",
  "read_and_wait_chance", "read_and_wait_min_sec", "read_and_wait_max_sec",
  "short_reply_chance", "reply_style", "language", "temperature", "max_tokens",
  "history_limit", "split_long_messages", "split_at_chars", "split_parts_max",
];

P.renderGroupChatAccounts = function() {
  const tbody = P.$("#groupChatAccountsTable");
  if (!tbody) return;
  tbody.innerHTML = "";
  const rows = (P.state.accountsCache || []).filter((a) => a.is_active !== false);
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="hint">Нет аккаунтов — добавьте сессии</td></tr>';
    return;
  }
  rows.forEach((a) => {
    const role = P.state.roleAssignments[a.id] || "—";
    const checked = P.state.selectedGroupChatAccounts.has(a.id) ? "checked" : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" data-gc-id="${P.escapeHtml(a.id)}" ${checked}></td>
      <td><strong>${P.escapeHtml(a.id)}</strong></td>
      <td><span class="chip">${P.escapeHtml(role)}</span></td>
      <td><input type="number" class="gc-weight" data-gc-id="${P.escapeHtml(a.id)}" value="1" min="0.1" step="0.1" style="width:4.5rem"></td>`;
    tbody.appendChild(tr);
    tr.querySelector("input[type=checkbox]").onchange = (ev) => {
      if (ev.target.checked) P.state.selectedGroupChatAccounts.add(a.id);
      else P.state.selectedGroupChatAccounts.delete(a.id);
      P.renderGroupChatRoleOverrides();
    };
  });
  P.renderGroupChatRoleOverrides();
}

P.renderGroupChatRoleOverrides = function() {
  const box = P.$("#groupChatRolesBox");
  if (!box) return;
  const ids = [...P.state.selectedGroupChatAccounts];
  if (ids.length < 2) {
    box.innerHTML = '<p class="hint">Выберите минимум 2 аккаунта, чтобы задать роли.</p>';
    return;
  }
  box.innerHTML = ids.map((id) => {
    const group = P.state.roleAssignments[id] || "";
    const g = (P.state.roleGroupsData || []).find((x) => x.name === group);
    const prompt = g?.role_prompt || "";
    return `
      <div class="card" style="margin:0.75rem 0;padding:0.75rem" data-gc-role="${P.escapeHtml(id)}">
        <strong>${P.escapeHtml(id)}</strong>
        <label class="label">Имя роли</label>
        <input type="text" class="gc-role-name" value="${P.escapeHtml(group || "участник")}">
        <label class="label">Промпт роли (можно переопределить)</label>
        <textarea class="gc-role-prompt" rows="3">${P.escapeHtml(prompt)}</textarea>
      </div>`;
  }).join("");
}

P.loadGroupChatSettings = async function() {
  const s = await P.api("/api/group-chat/settings");
  P.GROUP_CHAT_SETTING_FIELDS.forEach((key) => {
    const el = P.$(`#gc_${key}`);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!s[key];
    else el.value = s[key] ?? "";
  });
  const tz = P.$("#gc_timezone_offset_hours");
  if (tz) tz.value = s.timezone_offset_hours == null ? "" : s.timezone_offset_hours;
  const win = P.$("#gc_activity_windows");
  if (win) win.value = JSON.stringify(s.activity_windows || [], null, 2);
  const stop = P.$("#gc_stop_keywords");
  if (stop) stop.value = Array.isArray(s.stop_keywords) ? s.stop_keywords.join(", ") : "";
}

P.saveGroupChatSettings = async function() {
  const payload = {};
  P.GROUP_CHAT_SETTING_FIELDS.forEach((key) => {
    const el = P.$(`#gc_${key}`);
    if (!el) return;
    if (el.type === "checkbox") payload[key] = el.checked;
    else if (el.type === "number") payload[key] = el.value === "" ? 0 : Number(el.value);
    else payload[key] = el.value;
  });
  const tz = P.$("#gc_timezone_offset_hours").value;
  payload.timezone_offset_hours = tz === "" ? null : Number(tz);
  try {
    payload.activity_windows = JSON.parse(P.$("#gc_activity_windows").value || "[]");
  } catch (_) {
    P.$("#groupChatSettingsMsg").textContent = "Ошибка JSON в окнах активности";
    return;
  }
  payload.stop_keywords = P.$("#gc_stop_keywords").value.split(",").map((x) => x.trim()).filter(Boolean);
  try {
    await P.api("/api/group-chat/settings", { method: "POST", body: JSON.stringify(payload) });
    P.$("#groupChatSettingsMsg").textContent = "Настройки сохранены";
  } catch (e) {
    P.$("#groupChatSettingsMsg").textContent = e.message;
  }
}

P.findCommonGroupChats = async function() {
  const ids = [...P.state.selectedGroupChatAccounts];
  if (ids.length < 2) return alert("Выберите минимум 2 аккаунта");
  P.$("#groupChatMsg").textContent = "Ищем общие чаты...";
  try {
    const data = await P.api("/api/group-chat/common-chats", {
      method: "POST",
      body: JSON.stringify({ account_ids: ids }),
    });
    P.state.groupChatCommonCache = data.chats || [];
    const sel = P.$("#groupChatSelect");
    if (!P.state.groupChatCommonCache.length) {
      sel.innerHTML = '<option value="">— общих чатов нет —</option>';
      P.$("#groupChatMsg").textContent = "Общих групп не найдено";
      return;
    }
    sel.innerHTML = P.state.groupChatCommonCache.map((c) =>
      `<option value="${c.chat_id}">${P.escapeHtml(c.title)} (${c.kind}, ${c.chat_id})</option>`
    ).join("");
    P.$("#groupChatMsg").textContent = `Найдено: ${P.state.groupChatCommonCache.length}`;
  } catch (e) {
    P.$("#groupChatMsg").textContent = e.message;
    alert(e.message);
  }
}

P.refreshGroupChatStatus = async function() {
  const st = await P.api("/api/group-chat/status");
  const chip = P.$("#groupChatStats");
  if (chip) {
    if (st.running) {
      chip.className = "chip ok";
      chip.textContent = st.paused_schedule ? "Пауза (расписание)" : "Онлайн";
    } else {
      chip.className = "chip muted";
      chip.textContent = "Остановлен";
    }
  }
  const live = P.$("#groupChatLiveStats");
  if (live) {
    live.textContent = st.running
      ? `${st.status_text || "работает"} · отправлено: ${st.messages_sent} · день: ${st.group_day_count}`
      : (st.status_text || "Ожидание запуска");
  }
  const log = P.$("#groupChatLog");
  if (log && Array.isArray(st.recent_messages)) {
    log.textContent = st.recent_messages.map((m) =>
      `${m.speaker_name || m.speaker_account_id}: ${m.text}`
    ).join("\n");
  }
}

P.startGroupChat = async function() {
  const ids = [...P.state.selectedGroupChatAccounts];
  if (ids.length < 2) return alert("Выберите минимум 2 аккаунта");
  const chatId = Number(P.$("#groupChatSelect").value || 0);
  if (!chatId) return alert("Выберите общий чат");
  const topic = P.$("#groupChatTopic").value.trim();
  if (!topic) return alert("Укажите тему");
  const chat = P.state.groupChatCommonCache.find((c) => Number(c.chat_id) === chatId);
  const role_overrides = {};
  const activity_weights = {};
  ids.forEach((id) => {
    const weightEl = document.querySelector(`.gc-weight[data-gc-id="${CSS.escape(id)}"]`);
    activity_weights[id] = weightEl ? Number(weightEl.value || 1) : 1;
    const box = document.querySelector(`[data-gc-role="${CSS.escape(id)}"]`);
    if (box) {
      role_overrides[id] = {
        role_name: box.querySelector(".gc-role-name")?.value || "",
        role_prompt: box.querySelector(".gc-role-prompt")?.value || "",
      };
    }
  });
  try {
    await P.saveGroupChatSettings();
    await P.api("/api/group-chat/start", {
      method: "POST",
      body: JSON.stringify({
        account_ids: ids,
        chat_id: chatId,
        chat_title: chat?.title || "",
        topic,
        extra_context: P.$("#groupChatExtra").value,
        role_overrides,
        activity_weights,
      }),
    });
    P.$("#groupChatMsg").textContent = "Запущено";
    P.refreshStatus();
    P.refreshGroupChatStatus();
  } catch (e) {
    alert(e.message);
  }
}

P.stopGroupChat = async function() {
  await P.api("/api/group-chat/stop", { method: "POST" });
  P.refreshStatus();
  P.refreshGroupChatStatus();
}

P.loadGroupChat = async function() {
  P.renderGroupChatAccounts();
  await P.loadGroupChatSettings();
  await P.refreshGroupChatStatus();
}

P.$("#btnFindCommonChats").onclick = P.findCommonGroupChats;
P.$("#btnSaveGroupChatSettings").onclick = P.saveGroupChatSettings;
P.$("#btnStartGroupChat").onclick = P.startGroupChat;
P.$("#btnStopGroupChat").onclick = P.stopGroupChat;
P.$("#btnRefreshGroupChat").onclick = () => { P.renderGroupChatAccounts(); P.refreshGroupChatStatus(); };

P.startEngine = async function(resumeOnly) {
  try {
    let accountIds = P.state.selectedForRun.size ? [...P.state.selectedForRun] : [];
    const skipped = accountIds.filter((id) => !P.state.accountsCache.find((a) => a.id === id)?.outreach_eligible);
    accountIds = accountIds.filter((id) => P.state.accountsCache.find((a) => a.id === id)?.outreach_eligible);
    if (skipped.length) {
      const names = skipped.join(", ");
      if (!accountIds.length && !resumeOnly) {
        alert(`Выбранные аккаунты не подходят для рассылки (ассистент или неактивен): ${names}`);
        return;
      }
    }
    await P.api("/api/engine/start", {
      method: "POST",
      body: JSON.stringify({
        targets: P.$("#targets").value,
        account_ids: accountIds,
        extra_context: P.$("#extraContext").value,
        enable_dialog: P.$("#enableDialog").checked,
        resume_existing: P.$("#resumeExisting").checked,
        resume_only: resumeOnly,
      }),
    });
    P.refreshStatus();
  } catch (e) { alert(e.message); }
}

P.$("#btnStart").onclick = () => P.startEngine(false);
P.$("#btnResume").onclick = () => P.startEngine(true);
P.$("#btnStop").onclick = async () => { await P.api("/api/engine/stop", { method: "POST" }); P.refreshStatus(); };

P.tick = async function() {
  await P.refreshStatus();
  await P.refreshEngine();
  await P.refreshLogs();
}

P.bootstrap = async function() {
  if (window.__panelBootStarted) return;
  window.__panelBootStarted = true;
  P.initNavigation();
  await Promise.allSettled([
    P.loadConfig(),
    P.loadProxyPool(),
    P.loadAccounts(),
    P.loadRoles(),
    P.loadDialogSettings(),
    P.loadDialogs(),
    P.loadAgents(),
    P.loadGroupChat(),
    P.refreshStatus(),
  ]);
  if (!window.__panelTickHandle) {
    window.__panelTickHandle = setInterval(() => {
      P.tick().catch(() => {});
    }, 1500);
  }
}

})();
