const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let selectedAccount = null;
let selectedForRun = new Set();
let accountsCache = [];
let proxyPoolCache = [];
let selectedProxies = new Set();
let proxyViewFilters = new Set();
let proxyFiltersInited = false;
let selectedAgents = new Set();
let selectedGroupChatAccounts = new Set();
let groupChatCommonCache = [];
let logOffset = 0;

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function syncPageHeader(name) {
  const panel = $(`#panel-${name}`);
  const title = panel?.querySelector(".page-header h2")?.textContent?.trim() || "Панель";
  const lead = panel?.querySelector(".page-header .lead")?.textContent?.trim() || "";
  const titleEl = $("#pageTitle");
  const leadEl = $("#pageLead");
  if (titleEl) titleEl.textContent = title;
  if (leadEl) leadEl.textContent = lead;
}

function showTab(name) {
  $$("#tabNav [data-tab]").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  syncPageHeader(name);
  try {
    localStorage.setItem("panel.activeTab", name);
  } catch (_) {}
}

function initNavigation() {
  $$("#tabNav [data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  let initialTab = "outreach";
  try {
    initialTab = localStorage.getItem("panel.activeTab") || initialTab;
  } catch (_) {}
  showTab(initialTab);
}

let llmProviders = [];

async function refreshStatus() {
  const s = await api("/api/status");
  const parts = [];
  parts.push(s.telegram_ok ? "✓ Telegram" : "✗ Telegram");
  const aiLabel = s.llm_provider_name || "AI";
  parts.push(s.llm_ok ? `✓ ${aiLabel}` : `✗ ${aiLabel}`);
  if (s.llm_model) parts.push(s.llm_model);
  parts.push(`аккаунтов: ${s.accounts_count}`);
  parts.push(`прокси: ${s.proxies_count}/${s.accounts_count}`);
  if (s.paused_dialogs) parts.push(`на паузе: ${s.paused_dialogs}`);
  if (s.agents_count) parts.push(`агентов: ${s.agents_count}`);
  $("#statusBar").textContent = parts.join(" · ");
  $("#sessionsPath").textContent = s.sessions_path;
  const badge = $("#runBadge");
  const running = s.running || s.agent_running || s.group_chat_running;
  if (s.group_chat_running && (s.running || s.agent_running)) badge.textContent = "несколько режимов";
  else if (s.running && s.agent_running) badge.textContent = "рассылка + секретарь";
  else if (s.running) badge.textContent = "рассылка";
  else if (s.agent_running) badge.textContent = "секретарь";
  else if (s.group_chat_running) badge.textContent = "групповой чат";
  else badge.textContent = "остановлено";
  badge.classList.toggle("running", running);
  $("#btnStop").disabled = !s.running;
  $("#btnStart").disabled = s.running;
  $("#btnResume").disabled = s.running;
  $("#btnStopAgents").disabled = !s.agent_running;
  $("#btnStartAgents").disabled = s.agent_running;
  const btnStopGc = $("#btnStopGroupChat");
  const btnStartGc = $("#btnStartGroupChat");
  if (btnStopGc) btnStopGc.disabled = !s.group_chat_running;
  if (btnStartGc) btnStartGc.disabled = !!s.group_chat_running;
}

async function refreshEngine() {
  const e = await api("/api/engine");
  if (e.running) {
    $("#engineStats").textContent =
      `Первых: ${e.success}/${e.total} · Ответов: ${e.replies_sent} · Ошибок: ${e.failed} · Диалогов: ${e.active_dialogs}`;
  }
  try {
    const a = await api("/api/agents/stats");
    const el = $("#agentStats");
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
    await refreshGroupChatStatus();
  } catch (_) {}
}

async function refreshLogs() {
  const { lines, total } = await api(`/api/logs?offset=${logOffset}`);
  if (lines.length) {
    const box = $("#logBox");
    box.textContent += lines.join("\n") + "\n";
    box.scrollTop = box.scrollHeight;
    logOffset = total;
  }
}

function updateLlmHint(live) {
  const p = llmProviders.find((x) => x.id === $("#llmProvider").value);
  if (!p) return;
  const src = live ? "список загружен с API провайдера" : "список по умолчанию — вставьте ключ и нажмите ↻";
  $("#llmModelHint").innerHTML = `${src} · <a href="${p.docs_url}" target="_blank">получить ключ</a>`;
}

function renderLlmModelSelect(models, selected) {
  const sel = $("#llmModel");
  if (!models.length) {
    sel.innerHTML = `<option value="">— нет моделей —</option>`;
    return;
  }
  const opts = models.map((m) =>
    `<option value="${escapeHtml(m)}" ${m === selected ? "selected" : ""}>${escapeHtml(m)}</option>`);
  if (selected && !models.includes(selected)) {
    opts.unshift(`<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)} (сохранённая)</option>`);
  }
  sel.innerHTML = opts.join("");
}

async function loadLlmModels(provider, selected) {
  const data = await api(`/api/llm/models?provider=${encodeURIComponent(provider)}`);
  renderLlmModelSelect(data.models || [], selected || data.selected_model || "");
  updateLlmHint(data.live);
  return data;
}

async function loadLlmProviders() {
  llmProviders = await api("/api/llm/providers");
  const sel = $("#llmProvider");
  sel.innerHTML = llmProviders.map((p) =>
    `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join("");
  sel.onchange = async () => {
    await loadLlmModels(sel.value);
  };
}

function syncLocalLlmUi() {
  const isLocal = $("#llmProvider").value === "local";
  const box = $("#localLlmBox");
  if (box) box.classList.toggle("hidden", !isLocal);
}

async function loadConfig() {
  if (!llmProviders.length) await loadLlmProviders();
  const c = await api("/api/config");
  $("#apiId").value = c.telegram_api_id || "";
  $("#apiHash").value = c.telegram_api_hash || "";
  $("#llmProvider").value = c.llm_provider || "grok";
  $("#grokKey").value = c.grok_api_key || "";
  $("#grokModel").value = c.grok_model || "grok-3-mini";
  $("#openaiKey").value = c.openai_api_key || "";
  $("#geminiKey").value = c.gemini_api_key || "";
  $("#anthropicKey").value = c.anthropic_api_key || "";
  $("#deepseekKey").value = c.deepseek_api_key || "";
  $("#openrouterKey").value = c.openrouter_api_key || "";
  $("#localKey").value = c.local_api_key || "";
  $("#localBaseUrl").value = c.local_base_url || "http://127.0.0.1:8000/v1";
  syncLocalLlmUi();
  const savedModel = c.llm_model || c.grok_model || "grok-3-mini";
  await loadLlmModels(c.llm_provider || "grok", savedModel);
  $("#delayMsg").value = c.delay_between_messages_sec;
  $("#concurrent").value = c.max_concurrent_accounts;
  $("#replyMin").value = c.reply_delay_min_sec;
  $("#replyMax").value = c.reply_delay_max_sec;
  $("#language").value = c.message_language;
  $("#telegram2fa").value = c.telegram_2fa_password || "";
}

$("#llmProvider")?.addEventListener("change", async () => {
  syncLocalLlmUi();
  try {
    await loadLlmModels($("#llmProvider").value, $("#llmModel").value);
  } catch (_) {}
});

$("#btnRefreshModels").onclick = async () => {
  try {
    if ($("#llmProvider").value === "local") {
      await api("/api/config", {
        method: "POST",
        body: JSON.stringify({
          telegram_api_id: parseInt($("#apiId").value) || 0,
          telegram_api_hash: $("#apiHash").value,
          llm_provider: "local",
          llm_model: $("#llmModel").value || "mistral-24b-ru-uncensored",
          grok_api_key: $("#grokKey").value,
          grok_model: $("#grokModel").value || "grok-3-mini",
          openai_api_key: $("#openaiKey").value,
          gemini_api_key: $("#geminiKey").value,
          anthropic_api_key: $("#anthropicKey").value,
          deepseek_api_key: $("#deepseekKey").value,
          openrouter_api_key: $("#openrouterKey").value,
          local_api_key: $("#localKey").value,
          local_base_url: $("#localBaseUrl").value,
          delay_between_messages_sec: parseInt($("#delayMsg").value) || 30,
          max_concurrent_accounts: parseInt($("#concurrent").value) || 5,
          reply_delay_min_sec: parseInt($("#replyMin").value) || 5,
          reply_delay_max_sec: parseInt($("#replyMax").value) || 25,
          message_language: $("#language").value || "ru",
          telegram_2fa_password: $("#telegram2fa").value || "",
        }),
      });
    }
    await loadLlmModels($("#llmProvider").value, $("#llmModel").value);
    $("#configMsg").textContent = "Список моделей обновлён";
  } catch (e) {
    $("#configMsg").textContent = e.message;
  }
};

$("#btnSaveConfig").addEventListener("click", async () => {
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        telegram_api_id: parseInt($("#apiId").value) || 0,
        telegram_api_hash: $("#apiHash").value,
        llm_provider: $("#llmProvider").value,
        llm_model: $("#llmModel").value,
        grok_api_key: $("#grokKey").value,
        grok_model: $("#llmProvider").value === "grok" ? ($("#llmModel").value || "grok-3-mini") : ($("#grokModel").value || "grok-3-mini"),
        openai_api_key: $("#openaiKey").value,
        gemini_api_key: $("#geminiKey").value,
        anthropic_api_key: $("#anthropicKey").value,
        deepseek_api_key: $("#deepseekKey").value,
        openrouter_api_key: $("#openrouterKey").value,
        local_api_key: $("#localKey").value,
        local_base_url: $("#localBaseUrl").value,
        delay_between_messages_sec: parseInt($("#delayMsg").value) || 30,
        max_concurrent_accounts: parseInt($("#concurrent").value) || 5,
        message_language: $("#language").value,
        reply_delay_min_sec: parseInt($("#replyMin").value) || 5,
        reply_delay_max_sec: parseInt($("#replyMax").value) || 25,
        telegram_2fa_password: $("#telegram2fa").value,
      }),
    });
    $("#configMsg").textContent = "Сохранено";
    await loadLlmModels($("#llmProvider").value, $("#llmModel").value);
    refreshStatus();
  } catch (e) {
    $("#configMsg").textContent = e.message;
  }
});

const PROXY_FILTERS = [
  { id: "ok", label: "Рабочие", test: (p) => p.status === "ok" },
  { id: "dead", label: "Мёртвые", test: (p) => p.status === "dead" },
  { id: "unknown", label: "Не проверены", test: (p) => p.status === "unknown" },
  { id: "free", label: "Свободные", test: (p) => !p.accounts_count },
  { id: "used", label: "Привязанные", test: (p) => p.accounts_count > 0 },
];

function proxiesMatchingView(proxies) {
  if (!proxyViewFilters.size) return proxies;
  return proxies.filter((p) => {
    for (const fid of proxyViewFilters) {
      const f = PROXY_FILTERS.find((x) => x.id === fid);
      if (f && !f.test(p)) return false;
    }
    return true;
  });
}

function initProxyFilterUi() {
  if (proxyFiltersInited) return;
  proxyFiltersInited = true;
  const chips = $("#proxySelectChips");
  const views = $("#proxyViewFilters");
  if (!chips || !views) return;

  PROXY_FILTERS.forEach((f) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "filter-chip";
    btn.dataset.filter = f.id;
    btn.addEventListener("click", () => selectProxiesByFilter(f.id));
    chips.appendChild(btn);

    const label = document.createElement("label");
    label.className = "filter-check inline-check";
    const inp = document.createElement("input");
    inp.type = "checkbox";
    inp.dataset.viewFilter = f.id;
    inp.addEventListener("change", () => {
      if (inp.checked) proxyViewFilters.add(f.id);
      else proxyViewFilters.delete(f.id);
      renderProxyPoolTable();
    });
    label.append(inp, ` ${f.label}`);
    views.appendChild(label);
  });
}

function selectProxiesByFilter(filterId) {
  const f = PROXY_FILTERS.find((x) => x.id === filterId);
  if (!f) return;
  const ids = proxyPoolCache.filter(f.test).map((p) => p.id);
  if (!ids.length) return;
  selectedProxies = new Set(ids);
  renderProxyPoolTable();
}

function updateProxySelectionUi() {
  const visible = proxiesMatchingView(proxyPoolCache);
  const visTotal = visible.length;
  const selected = selectedProxies.size;
  const visSelected = visible.filter((p) => selectedProxies.has(p.id)).length;
  const hint = $("#proxySelectedHint");
  if (hint) {
    hint.textContent = selected
      ? `Выбрано: ${selected}${visTotal ? ` · в таблице ${visSelected}/${visTotal}` : ""}`
      : (visTotal ? `В таблице: ${visTotal} из ${proxyPoolCache.length}` : "");
  }
  const master = $("#chkSelectAllProxies");
  if (master) {
    master.indeterminate = visSelected > 0 && visSelected < visTotal;
    master.checked = visTotal > 0 && visSelected === visTotal;
  }
  PROXY_FILTERS.forEach((f) => {
    const matched = proxyPoolCache.filter(f.test);
    const n = matched.length;
    const sel = matched.filter((p) => selectedProxies.has(p.id)).length;
    const btn = document.querySelector(`.filter-chip[data-filter="${f.id}"]`);
    if (!btn || !btn.closest("#proxySelectChips")) return;
    btn.disabled = n === 0;
    btn.classList.toggle("active", n > 0 && sel === n);
    btn.textContent = n > 0 && sel === n ? `${f.label} (${n}) ✓` : `${f.label} (${n})`;
  });
}

function getSelectedProxyIdsOrAlert() {
  const ids = [...selectedProxies];
  if (!ids.length) {
    alert("Отметьте прокси в таблице пула или нажмите chip-фильтр");
    return null;
  }
  return ids;
}

function proxyStatusChip(status) {
  if (status === "ok") return '<span class="chip ok">рабочий</span>';
  if (status === "dead") return '<span class="chip danger">мёртвый</span>';
  return '<span class="chip warn">не проверен</span>';
}

function proxyPoolSelectable(p) {
  return p.status !== "dead";
}

function proxySelectOptions(selectedId) {
  const opts = ['<option value="">— не выбран —</option>'];
  proxyPoolCache.filter(proxyPoolSelectable).forEach((p) => {
    const sel = p.id === selectedId ? " selected" : "";
    const used = p.accounts_count > 0 ? ` (${p.accounts_count})` : "";
    const country = p.country_label ? `${p.country_label} · ` : "";
    opts.push(`<option value="${escapeHtml(p.id)}"${sel}>${country}${escapeHtml(p.label || `${p.host}:${p.port}`)}${used}</option>`);
  });
  return opts.join("");
}

function fillProxyPoolSelect(selectedId) {
  const sel = $("#proxyPoolSelect");
  if (!sel) return;
  sel.innerHTML = proxySelectOptions(selectedId);
  sel.disabled = !selectedAccount;
  $("#btnBindProxy").disabled = !selectedAccount;
  $("#btnClearProxy").disabled = !selectedAccount;
  $("#btnSaveProxy").disabled = !selectedAccount;
}

async function loadProxyPool() {
  initProxyFilterUi();
  const data = await api("/api/proxy-pool");
  proxyPoolCache = data.items || [];
  renderProxyPoolTable();
  if (selectedAccount) {
    const acc = accountsCache.find((a) => a.id === selectedAccount);
    fillProxyPoolSelect(acc?.proxy_id || "");
  } else {
    fillProxyPoolSelect("");
  }
}

function renderProxyPoolTable() {
  const tbody = $("#proxyPoolTable");
  if (!tbody) return;
  const visible = proxiesMatchingView(proxyPoolCache);
  if (!visible.length) {
    const msg = proxyViewFilters.size
      ? "Нет прокси по выбранным фильтрам"
      : "Пул пуст — вставьте список прокси выше";
    tbody.innerHTML = `<tr><td colspan="7" class="hint">${msg}</td></tr>`;
    updateProxySelectionUi();
    return;
  }
  tbody.innerHTML = visible.map((p) => {
    const accounts = (p.accounts || []).map((a) => escapeHtml(a)).join(", ");
    const ping = p.latency_ms ? `${p.latency_ms} ms` : "—";
    const checked = selectedProxies.has(p.id) ? "checked" : "";
    return `<tr class="${p.status === "dead" ? "row-inactive" : ""}${selectedProxies.has(p.id) ? " selected" : ""}">
      <td><input type="checkbox" class="proxy-chk" data-id="${escapeHtml(p.id)}" ${checked}></td>
      <td><strong>${escapeHtml(p.label || `${p.host}:${p.port}`)}</strong><br><span class="hint">${escapeHtml(p.type)} · ${escapeHtml(p.exit_ip || "—")}</span></td>
      <td>${p.country_label ? escapeHtml(p.country_label) : '<span class="chip muted">?</span>'}${p.country ? `<br><span class="hint">${escapeHtml(p.country)}</span>` : ""}</td>
      <td>${proxyStatusChip(p.status)}${p.last_error ? `<br><span class="hint">${escapeHtml(p.last_error)}</span>` : ""}</td>
      <td>${ping}</td>
      <td>${p.accounts_count ? `<span class="chip ok">${p.accounts_count}</span> ${accounts}` : '<span class="chip muted">0</span>'}</td>
      <td>
        <button type="button" class="btn btn-sm ghost proxy-pool-recheck" data-id="${escapeHtml(p.id)}" title="Перепроверить">↻</button>
        <button type="button" class="btn btn-sm danger proxy-pool-del" data-id="${escapeHtml(p.id)}">✕</button>
      </td>
    </tr>`;
  }).join("");

  tbody.querySelectorAll(".proxy-chk").forEach((el) => {
    el.onchange = (ev) => {
      const id = el.dataset.id;
      if (ev.target.checked) selectedProxies.add(id);
      else selectedProxies.delete(id);
      updateProxySelectionUi();
      el.closest("tr")?.classList.toggle("selected", ev.target.checked);
    };
  });

  tbody.querySelectorAll(".proxy-pool-recheck").forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      btn.disabled = true;
      try {
        await api(`/api/proxy-pool/${encodeURIComponent(btn.dataset.id)}/recheck`, { method: "POST" });
        await loadProxyPool();
        loadAccounts();
        refreshStatus();
      } catch (e) { alert(e.message); }
      btn.disabled = false;
    };
  });
  tbody.querySelectorAll(".proxy-pool-del").forEach((btn) => {
    btn.onclick = async (ev) => {
      ev.stopPropagation();
      const id = btn.dataset.id;
      const item = proxyPoolCache.find((p) => p.id === id);
      const force = item?.accounts_count
        ? confirm(`Прокси привязан к ${item.accounts_count} акк. Удалить и отвязать?`)
        : confirm("Удалить прокси из пула?");
      if (!force) return;
      try {
        await api(`/api/proxy-pool/${encodeURIComponent(id)}?unbind=true`, { method: "DELETE" });
        selectedProxies.delete(id);
        await loadProxyPool();
        loadAccounts();
        refreshStatus();
      } catch (e) { alert(e.message); }
    };
  });
  updateProxySelectionUi();
}

async function bindAccountProxy(accountId, proxyId) {
  await api(`/api/accounts/${encodeURIComponent(accountId)}/proxy/bind`, {
    method: "POST",
    body: JSON.stringify({ proxy_id: proxyId || null }),
  });
  await loadProxyPool();
  loadAccounts();
  refreshStatus();
}

async function loadAccounts() {
  if (!proxyPoolCache.length) {
    try { await loadProxyPool(); } catch (_) {}
  }
  const rows = await api("/api/accounts");
  accountsCache = rows;
  initAccountFilterUi();
  const visible = accountsMatchingView(rows);
  const tbody = $("#accountsTable");
  tbody.innerHTML = "";
  if (!visible.length) {
    const msg = accountViewFilters.size
      ? "Нет аккаунтов по выбранным фильтрам показа"
      : "Нет аккаунтов в папке sessions";
    tbody.innerHTML = `<tr><td colspan="6" class="hint">${msg}</td></tr>`;
    updateAccountsSelectionUi();
    return;
  }
  visible.forEach((a) => {
    const tr = document.createElement("tr");
    if (a.id === selectedAccount) tr.classList.add("selected");
    if (!a.is_active) tr.classList.add("row-inactive");
    if (a.is_assistant) tr.classList.add("row-assistant");
    const checked = selectedForRun.has(a.id) ? "checked" : "";
    const canSelect = a.outreach_eligible;
    const twofaHint = a.twofa_file ? ` · 2FA: ${a.twofa_file}` : "";
    const typeChip = a.format === "tdata"
      ? '<span class="chip warn">tdata</span>'
      : '<span class="chip">session</span>';
    const sessionChip = a.session_ready
      ? `<span class="chip ok">${escapeHtml(a.session_file || "готов")}</span>`
      : (a.format === "tdata" ? '<span class="chip warn">нет</span>' : '<span class="chip muted">—</span>');
    const dupHint = a.is_duplicate ? ' <span class="chip warn">дубль</span>' : "";
    const assistantChip = a.is_assistant
      ? `<span class="chip violet" title="Только AI-агент">ассистент${a.assistant_name ? `: ${escapeHtml(a.assistant_name)}` : ""}</span>`
      : "";
    const inactiveChip = !a.is_active ? '<span class="chip danger">неактивен</span>' : "";
    const proxyCell = proxyPoolCache.length
      ? `<select class="proxy-bind-select assign-select" data-id="${escapeHtml(a.id)}" onclick="event.stopPropagation()">${proxySelectOptions(a.proxy_id || "")}</select>`
      : (a.proxy ? `<span class="chip">${escapeHtml(a.proxy)}</span>` : '<span class="chip muted">—</span>');
    tr.innerHTML = `
      <td><input type="checkbox" class="acc-chk" data-id="${escapeHtml(a.id)}" ${checked} ${canSelect ? "" : "disabled"} onclick="event.stopPropagation()"></td>
      <td><strong>${escapeHtml(a.id)}</strong> ${assistantChip} ${inactiveChip} ${dupHint}${twofaHint ? `<span class="hint">${escapeHtml(twofaHint)}</span>` : ""}</td>
      <td>${typeChip}</td>
      <td>${sessionChip}</td>
      <td>${proxyCell}</td>
      <td>${a.role ? escapeHtml(a.role) : '<span class="chip muted">—</span>'}</td>`;
    tr.onclick = () => selectAccount(a.id);
    tbody.appendChild(tr);
    const proxySel = tr.querySelector(".proxy-bind-select");
    if (proxySel) {
      proxySel.onchange = async (ev) => {
        ev.stopPropagation();
        try {
          await bindAccountProxy(a.id, ev.target.value || null);
        } catch (e) {
          alert(e.message);
          loadAccounts();
        }
      };
    }
    tr.querySelector("input").onchange = (ev) => {
      if (ev.target.checked) selectedForRun.add(a.id);
      else selectedForRun.delete(a.id);
      updateAccountsSelectionUi();
    };
  });
  purgeIneligibleSelection();
  updateAccountsSelectionUi();
  try { renderGroupChatAccounts(); } catch (_) {}
}

function purgeIneligibleSelection() {
  [...selectedForRun].forEach((id) => {
    const a = accountsCache.find((x) => x.id === id);
    if (!a || !a.outreach_eligible) selectedForRun.delete(id);
  });
}

const ACCOUNT_FILTERS = [
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

let accountViewFilters = new Set(["outreach_eligible"]);
let accountFiltersInited = false;

function accountsMatchingView(accounts) {
  if (!accountViewFilters.size) return accounts;
  return accounts.filter((a) => {
    for (const fid of accountViewFilters) {
      const f = ACCOUNT_FILTERS.find((x) => x.id === fid);
      if (f && !f.test(a)) return false;
    }
    return true;
  });
}

function initAccountFilterUi() {
  if (accountFiltersInited) return;
  accountFiltersInited = true;
  const chips = $("#accountSelectChips");
  const views = $("#accountViewFilters");
  if (!chips || !views) return;

  ACCOUNT_FILTERS.forEach((f) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "filter-chip";
    btn.dataset.filter = f.id;
    btn.addEventListener("click", () => selectByAccountFilter(f.id));
    chips.appendChild(btn);

    const label = document.createElement("label");
    label.className = "filter-check inline-check";
    const inp = document.createElement("input");
    inp.type = "checkbox";
    inp.dataset.viewFilter = f.id;
    if (f.id === "outreach_eligible") inp.checked = true;
    inp.addEventListener("change", () => {
      if (inp.checked) accountViewFilters.add(f.id);
      else accountViewFilters.delete(f.id);
      loadAccounts();
    });
    label.append(inp, ` ${f.label}`);
    views.appendChild(label);
  });

  $("#btnResetViewFilters")?.addEventListener("click", () => {
    accountViewFilters.clear();
    accountViewFilters.add("outreach_eligible");
    views.querySelectorAll("input[type=checkbox]").forEach((i) => {
      i.checked = i.dataset.viewFilter === "outreach_eligible";
    });
    loadAccounts();
  });
}

function selectByAccountFilter(filterId) {
  const f = ACCOUNT_FILTERS.find((x) => x.id === filterId);
  if (!f) return;
  const ids = accountsCache.filter((a) => f.test(a) && a.outreach_eligible).map((a) => a.id);
  if (!ids.length) return;
  const additive = Boolean($("#chkSelectAdditive")?.checked);
  if (additive) {
    ids.forEach((id) => selectedForRun.add(id));
  } else {
    selectedForRun = new Set(ids);
  }
  document.querySelectorAll(".acc-chk").forEach((el) => {
    el.checked = selectedForRun.has(el.dataset.id);
  });
  updateAccountsSelectionUi();
}

function updateAccountFilterCounts() {
  ACCOUNT_FILTERS.forEach((f) => {
    const matched = accountsCache.filter(f.test);
    const n = matched.length;
    const selected = matched.filter((a) => selectedForRun.has(a.id)).length;
    const btn = document.querySelector(`.filter-chip[data-filter="${f.id}"]`);
    if (!btn) return;
    btn.disabled = n === 0;
    btn.classList.toggle("active", n > 0 && selected === n);
    btn.textContent = n > 0 && selected === n ? `${f.label} (${n}) ✓` : `${f.label} (${n})`;
  });
}

function updateAccountsSelectionUi() {
  const total = accountsCache.length;
  const visible = accountsMatchingView(accountsCache);
  const visTotal = visible.length;
  const selected = selectedForRun.size;
  const visSelected = visible.filter((a) => selectedForRun.has(a.id)).length;

  const hint = $("#accountsSelectedHint");
  if (hint) {
    if (!selected) {
      hint.textContent = accountViewFilters.size ? `В таблице: ${visTotal} из ${total}` : "";
    } else {
      hint.textContent = `Выбрано: ${selected}${total ? ` · в таблице ${visSelected}/${visTotal}` : ""}`;
    }
  }

  const master = $("#chkSelectAllAccounts");
  if (master) {
    master.indeterminate = visSelected > 0 && visSelected < visTotal;
    master.checked = visTotal > 0 && visSelected === visTotal;
  }

  updateAccountFilterCounts();
}

function setAccountSelection(ids) {
  selectedForRun = new Set(ids);
  document.querySelectorAll(".acc-chk").forEach((el) => {
    el.checked = selectedForRun.has(el.dataset.id);
  });
  updateAccountsSelectionUi();
}

$("#chkSelectAllAccounts")?.addEventListener("change", (ev) => {
  const visible = accountsMatchingView(accountsCache).filter((a) => a.outreach_eligible);
  if (ev.target.checked) {
    setAccountSelection(visible.map((a) => a.id));
  } else {
    setAccountSelection([]);
  }
});

$("#btnClearAccountSelection")?.addEventListener("click", () => {
  setAccountSelection([]);
});

async function selectAccount(id) {
  selectedAccount = id;
  $("#proxyAccountLabel").textContent = `Аккаунт: ${id}`;
  const acc = accountsCache.find((a) => a.id === id);
  fillProxyPoolSelect(acc?.proxy_id || "");
  loadAccounts();
  try {
    const p = await api(`/api/accounts/${encodeURIComponent(id)}/proxy`);
    if ($("#proxyPoolSelect") && p.proxy_id) $("#proxyPoolSelect").value = p.proxy_id;
    $("#proxyType").value = p.type || "socks5";
    $("#proxyHost").value = p.host || "";
    $("#proxyPort").value = p.port || "";
    $("#proxyUser").value = p.username || "";
    $("#proxyPass").value = p.password || "";
  } catch (_) {}
}

$("#btnRefreshAccounts").onclick = () => { loadAccounts(); refreshStatus(); };

async function convertTdata(accountIds) {
  $("#convertMsg").textContent = "Конвертация...";
  try {
    const r = await api("/api/sessions/convert", {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds || [] }),
    });
    const lines = (r.results || []).map(
      (x) => `${x.success ? "✓" : "✗"} ${x.account_id}: ${x.message || x.output_path || ""}`
    );
    $("#convertMsg").textContent = `Готово: ${r.ok} успешно, ${r.failed} ошибок`;
    if (lines.length) alert(lines.join("\n"));
    loadAccounts();
    refreshStatus();
  } catch (e) {
    $("#convertMsg").textContent = e.message;
    alert(e.message);
  }
}

$("#btnConvertSelected").onclick = async () => {
  const rows = accountsCache.length ? accountsCache : await api("/api/accounts");
  if (!selectedForRun.size) {
    alert("Отметьте аккаунты галочками или нажмите «Без .session»");
    return;
  }
  const tdataIds = [...selectedForRun].filter(
    (id) => rows.find((a) => a.id === id && a.format === "tdata")
  );
  if (!tdataIds.length) return alert("Среди выбранных нет tdata");
  await convertTdata(tdataIds);
};

$("#btnConvertAll").onclick = async () => {
  const rows = await api("/api/accounts");
  const tdataIds = rows.filter((a) => a.format === "tdata").map((a) => a.id);
  if (!tdataIds.length) return alert("Нет tdata в папке sessions");
  await convertTdata(tdataIds);
};

async function bulkUpdateProfile() {
  if (!selectedForRun.size) {
    alert("Отметьте аккаунты галочками в таблице");
    return;
  }
  const generateMode = $("#profileGenerateMode")?.value || "manual";
  const changeFirst = generateMode !== "manual" ? true : $("#profileChangeFirst")?.checked;
  const changeLast = generateMode === "names" || generateMode === "nicks"
    ? true
    : $("#profileChangeLast")?.checked;
  const changeUsername = generateMode !== "manual"
    ? Boolean($("#profileWithUsername")?.checked)
    : $("#profileChangeUsername")?.checked;
  if (generateMode === "manual" && !changeFirst && !changeLast && !changeUsername) {
    alert("Включите хотя бы одно поле: имя, фамилию или username");
    return;
  }
  const accountIds = [...selectedForRun];
  const readyCount = accountIds.filter(
    (id) => accountsCache.find((a) => a.id === id && a.session_ready)
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

  $("#profileMsg").textContent = "Обновление профилей...";
  try {
    const r = await api("/api/accounts/bulk-profile", {
      method: "POST",
      body: JSON.stringify({
        account_ids: accountIds,
        generate_mode: generateMode,
        lang: $("#profileLang")?.value || "ru",
        with_username: Boolean($("#profileWithUsername")?.checked),
        change_first_name: changeFirst,
        change_last_name: changeLast,
        change_username: changeUsername,
        first_name: $("#profileFirstName")?.value || "",
        last_name: $("#profileLastName")?.value || "",
        username: $("#profileUsername")?.value || "",
        delay_sec: parseInt($("#profileDelay")?.value, 10) || 3,
      }),
    });
    const lines = (r.results || []).map(
      (x) => `${x.success ? "✓" : "✗"} ${x.account_id}: ${x.message || ""}`
    );
    $("#profileMsg").textContent = r.message || "Готово";
    if (lines.length) alert(lines.join("\n"));
    refreshStatus();
  } catch (e) {
    $("#profileMsg").textContent = e.message;
    alert(e.message);
  }
}

function syncProfileModeUi() {
  const mode = $("#profileGenerateMode")?.value || "manual";
  const manual = mode === "manual";
  $("#profileManualBlock")?.classList.toggle("hidden", !manual);
  $("#profileGenerateBlock")?.classList.toggle("hidden", manual);
}

async function previewProfileGeneration() {
  const mode = $("#profileGenerateMode")?.value;
  if (mode === "manual") return;
  try {
    const r = await api("/api/accounts/profile-preview", {
      method: "POST",
      body: JSON.stringify({
        generate_mode: mode,
        lang: $("#profileLang")?.value || "ru",
        with_username: Boolean($("#profileWithUsername")?.checked),
        count: 5,
      }),
    });
    const lines = (r.samples || []).map((s, i) => {
      const name = `${s.first_name || ""} ${s.last_name || ""}`.trim();
      const user = s.username ? ` @${s.username}` : "";
      return `${i + 1}. ${name}${user}`;
    });
    const box = $("#profilePreviewBox");
    if (box) {
      box.textContent = lines.join("\n") || "Нет примеров";
      box.classList.remove("hidden");
    }
  } catch (e) {
    alert(e.message);
  }
}

$("#profileGenerateMode")?.addEventListener("change", syncProfileModeUi);
$("#btnProfilePreview")?.addEventListener("click", previewProfileGeneration);
$("#btnBulkProfile")?.addEventListener("click", bulkUpdateProfile);
syncProfileModeUi();

$("#btnSaveProxy").onclick = async () => {
  if (!selectedAccount) return alert("Выберите аккаунт");
  try {
    await api(`/api/accounts/${encodeURIComponent(selectedAccount)}/proxy`, {
      method: "POST",
      body: JSON.stringify({
        type: $("#proxyType").value,
        host: $("#proxyHost").value,
        port: parseInt($("#proxyPort").value) || 0,
        username: $("#proxyUser").value,
        password: $("#proxyPass").value,
      }),
    });
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
    alert("Прокси добавлен в пул и привязан");
  } catch (e) { alert(e.message); }
};

$("#btnBindProxy").onclick = async () => {
  if (!selectedAccount) return;
  try {
    await bindAccountProxy(selectedAccount, $("#proxyPoolSelect").value || null);
  } catch (e) { alert(e.message); }
};

$("#btnClearProxy").onclick = async () => {
  if (!selectedAccount) return;
  try {
    await bindAccountProxy(selectedAccount, null);
    fillProxyPoolSelect("");
  } catch (e) { alert(e.message); }
};

$("#btnImportProxyPool").onclick = async () => {
  const lines = $("#proxyPoolImport")?.value?.trim();
  if (!lines) return alert("Вставьте список прокси");
  $("#proxyPoolMsg").textContent = "Проверка прокси (страна, пинг)...";
  $("#btnImportProxyPool").disabled = true;
  try {
    const r = await api("/api/proxy-pool/import", {
      method: "POST",
      body: JSON.stringify({ lines, type: $("#proxyPoolType")?.value || "socks5" }),
    });
    const parts = [
      `добавлено: ${r.added}`,
      `дублей: ${r.skipped_duplicate}`,
      `мёртвых: ${r.skipped_dead}`,
    ];
    if (r.skipped_parse) parts.push(`ошибок строк: ${r.skipped_parse}`);
    parts.push(`всего в пуле: ${r.total}`);
    $("#proxyPoolMsg").textContent = parts.join(" · ");
    $("#proxyPoolImport").value = "";
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
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
    $("#proxyPoolMsg").textContent = e.message;
    alert(e.message);
  }
  $("#btnImportProxyPool").disabled = false;
};

$("#btnRecheckProxyPool").onclick = async () => {
  $("#proxyPoolMsg").textContent = "Перепроверка всего пула...";
  $("#btnRecheckProxyPool").disabled = true;
  try {
    const r = await api("/api/proxy-pool/recheck", { method: "POST", body: JSON.stringify({ proxy_ids: [] }) });
    $("#proxyPoolMsg").textContent = `ok: ${r.added} · мёртвых: ${r.skipped_dead} · дублей: ${r.skipped_duplicate}`;
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
  } catch (e) {
    $("#proxyPoolMsg").textContent = e.message;
    alert(e.message);
  }
  $("#btnRecheckProxyPool").disabled = false;
};

$("#chkSelectAllProxies")?.addEventListener("change", (ev) => {
  const visible = proxiesMatchingView(proxyPoolCache);
  if (ev.target.checked) visible.forEach((p) => selectedProxies.add(p.id));
  else visible.forEach((p) => selectedProxies.delete(p.id));
  renderProxyPoolTable();
});

$("#btnClearProxySelection")?.addEventListener("click", () => {
  selectedProxies.clear();
  renderProxyPoolTable();
});

$("#btnProxyRecheckSelected")?.addEventListener("click", async () => {
  const ids = getSelectedProxyIdsOrAlert();
  if (!ids) return;
  $("#proxyPoolMsg").textContent = `Перепроверка ${ids.length} прокси...`;
  try {
    const r = await api("/api/proxy-pool/recheck", {
      method: "POST",
      body: JSON.stringify({ proxy_ids: ids }),
    });
    $("#proxyPoolMsg").textContent = `ok: ${r.added} · мёртвых: ${r.skipped_dead}`;
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
  } catch (e) {
    $("#proxyPoolMsg").textContent = e.message;
    alert(e.message);
  }
});

$("#btnProxyDeleteSelected")?.addEventListener("click", async () => {
  const ids = getSelectedProxyIdsOrAlert();
  if (!ids) return;
  const bound = ids.filter((id) => proxyPoolCache.find((p) => p.id === id)?.accounts_count);
  const msg = bound.length
    ? `Удалить ${ids.length} прокси? ${bound.length} привязаны к аккаунтам — отвязка автоматически.`
    : `Удалить ${ids.length} прокси из пула?`;
  if (!confirm(msg)) return;
  try {
    const r = await api("/api/proxy-pool/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ proxy_ids: ids, unbind: true }),
    });
    selectedProxies.clear();
    $("#proxyPoolMsg").textContent = `Удалено: ${r.deleted}`;
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
  } catch (e) {
    alert(e.message);
  }
});

$("#btnProxyPurgeDead")?.addEventListener("click", async () => {
  const dead = proxyPoolCache.filter((p) => p.status === "dead").length;
  if (!dead) return alert("Мёртвых прокси нет");
  if (!confirm(`Удалить все мёртвые прокси (${dead})?`)) return;
  try {
    const r = await api("/api/proxy-pool/purge-dead?unbind=true", { method: "POST" });
    selectedProxies.clear();
    $("#proxyPoolMsg").textContent = `Удалено мёртвых: ${r.deleted}`;
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
  } catch (e) {
    alert(e.message);
  }
});

$("#btnProxyAutoBind")?.addEventListener("click", async () => {
  const accountIds = selectedForRun.size ? [...selectedForRun] : [];
  const proxyIds = selectedProxies.size ? [...selectedProxies] : [];
  const accHint = accountIds.length
    ? `${accountIds.length} выбранных аккаунтов`
    : "аккаунтов без прокси";
  const proxyHint = proxyIds.length
    ? `${proxyIds.length} выбранных прокси`
    : "свободных рабочих прокси";
  if (!confirm(`Привязать ${proxyHint} к ${accHint} (1:1 по порядку)?`)) return;
  try {
    const r = await api("/api/proxy-pool/auto-bind", {
      method: "POST",
      body: JSON.stringify({ account_ids: accountIds, proxy_ids: proxyIds }),
    });
    $("#proxyPoolMsg").textContent = `Привязано пар: ${r.paired}`;
    if (r.paired) alert(`Привязано ${r.paired} пар`);
    else alert("Не удалось привязать — проверьте свободные прокси и аккаунты без прокси");
    await loadProxyPool();
    loadAccounts();
    refreshStatus();
  } catch (e) {
    alert(e.message);
  }
});

$("#btnRefreshProxyPool").onclick = async () => {
  await loadProxyPool();
  loadAccounts();
};

let roleGroupsData = [];
let roleAssignments = {};
let roleGroupNames = [];

async function loadRoles() {
  const r = await api("/api/roles");
  $("#defaultRole").value = r.default_role || "";
  if (r.master_prompt) {
    $("#masterEnabled").checked = r.master_prompt.enabled !== false;
    $("#masterPrompt").value = r.master_prompt.text || "";
  }
  roleGroupsData = r.groups || [];
  roleAssignments = r.assignments || {};
  roleGroupNames = roleGroupsData.map((g) => g.name);
  renderRoleGroups();
  renderRoleAssignments(r.all_accounts || []);
}

function renderRoleGroups() {
  const box = $("#roleGroups");
  box.innerHTML = "";
  if (!roleGroupsData.length) {
    box.innerHTML = '<p class="hint">Нажмите «+ Добавить роль», чтобы создать первую роль</p>';
    return;
  }
  roleGroupsData.forEach((g, i) => {
    const div = document.createElement("div");
    div.className = "role-group";
    div.innerHTML = `
      <input type="text" class="rg-name" data-i="${i}" value="${escapeHtml(g.name || "")}" placeholder="Название роли">
      <label class="label">Текст роли для Grok (слой поверх мастера)</label>
      <textarea class="rg-prompt" data-i="${i}" rows="3">${escapeHtml(g.role_prompt || "")}</textarea>
      <button type="button" class="btn btn-sm danger btn-del-g" data-i="${i}">Удалить</button>`;
    box.appendChild(div);
  });
  box.querySelectorAll(".btn-del-g").forEach((b) => {
    b.onclick = () => {
      const idx = +b.dataset.i;
      const removed = roleGroupsData[idx]?.name;
      roleGroupsData.splice(idx, 1);
      if (removed) {
        Object.keys(roleAssignments).forEach((acc) => {
          if (roleAssignments[acc] === removed) roleAssignments[acc] = "";
        });
      }
      syncGroupNamesFromDom();
      renderRoleGroups();
      renderRoleAssignments(Object.keys(roleAssignments));
    };
  });
  box.querySelectorAll(".rg-name").forEach((inp) => {
    inp.addEventListener("change", () => {
      const idx = +inp.dataset.i;
      const oldName = roleGroupsData[idx]?.name;
      const newName = inp.value.trim();
      roleGroupsData[idx].name = newName;
      if (oldName && oldName !== newName) {
        Object.keys(roleAssignments).forEach((acc) => {
          if (roleAssignments[acc] === oldName) roleAssignments[acc] = newName;
        });
      }
      syncGroupNamesFromDom();
      renderRoleAssignments(Object.keys(roleAssignments));
    });
  });
}

function syncGroupNamesFromDom() {
  roleGroupNames = [];
  document.querySelectorAll(".rg-name").forEach((inp, i) => {
    const name = inp.value.trim() || `Роль ${i + 1}`;
    if (roleGroupsData[i]) roleGroupsData[i].name = name;
    roleGroupNames.push(name);
  });
}

function buildRoleOptions(selected) {
  let html = `<option value="" ${!selected ? "selected" : ""}>— По умолчанию —</option>`;
  roleGroupNames.forEach((name) => {
    if (!name) return;
    html += `<option value="${escapeHtml(name)}" ${selected === name ? "selected" : ""}>${escapeHtml(name)}</option>`;
  });
  return html;
}

function renderRoleAssignments(allAccounts) {
  syncGroupNamesFromDom();
  const tbody = $("#roleAssignTable");
  tbody.innerHTML = "";
  if (!allAccounts.length) {
    tbody.innerHTML = '<tr><td colspan="2" class="hint">Нет готовых аккаунтов — сначала сконвертируйте tdata во вкладке «3. Аккаунты»</td></tr>';
    return;
  }
  allAccounts.forEach((accId) => {
    if (!(accId in roleAssignments)) roleAssignments[accId] = "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(accId)}</strong></td>
      <td><select class="assign-select" data-acc="${escapeHtml(accId)}">${buildRoleOptions(roleAssignments[accId] || "")}</select></td>`;
    tbody.appendChild(tr);
    tr.querySelector("select").addEventListener("change", (ev) => {
      roleAssignments[accId] = ev.target.value;
    });
  });
}

function collectMasterPayload() {
  return {
    enabled: $("#masterEnabled").checked,
    text: $("#masterPrompt").value,
  };
}

async function saveMasterPromptData() {
  const master = collectMasterPayload();
  try {
    await api("/api/master-prompt", { method: "POST", body: JSON.stringify(master) });
    return;
  } catch (e) {
    if (!String(e.message).includes("Not Found")) throw e;
  }
  await api("/api/roles", {
    method: "POST",
    body: JSON.stringify({ master_prompt: master }),
  });
}

async function loadMasterPrompt() {
  try {
    const m = await api("/api/master-prompt");
    $("#masterEnabled").checked = m.enabled !== false;
    $("#masterPrompt").value = m.text || "";
  } catch (_) {
    /* loadRoles заполнит master_prompt из /api/roles */
  }
}

$("#btnSaveMaster").onclick = async () => {
  try {
    await saveMasterPromptData();
    $("#masterMsg").textContent = "Сохранено";
  } catch (e) {
    $("#masterMsg").textContent = e.message.includes("Not Found")
      ? "Перезапустите start.bat и попробуйте снова"
      : e.message;
  }
};

$("#btnAddGroup").onclick = () => {
  roleGroupsData.push({ name: `Роль ${roleGroupsData.length + 1}`, role_prompt: "Вы вежливый собеседник." });
  syncGroupNamesFromDom();
  renderRoleGroups();
  api("/api/roles").then((r) => renderRoleAssignments(r.all_accounts || Object.keys(roleAssignments)));
};

$("#btnRefreshRoleAssign").onclick = async () => {
  document.querySelectorAll(".rg-prompt").forEach((ta) => {
    const i = +ta.dataset.i;
    if (roleGroupsData[i]) roleGroupsData[i].role_prompt = ta.value;
  });
  syncGroupNamesFromDom();
  const r = await api("/api/roles");
  renderRoleAssignments(r.all_accounts || []);
};

$("#btnSaveRoles").onclick = async () => {
  syncGroupNamesFromDom();
  const groups = [];
  document.querySelectorAll(".role-group").forEach((el, i) => {
    groups.push({
      name: el.querySelector(".rg-name")?.value.trim() || `Роль ${i + 1}`,
      role_prompt: el.querySelector(".rg-prompt")?.value || "",
    });
  });
  document.querySelectorAll(".assign-select").forEach((sel) => {
    roleAssignments[sel.dataset.acc] = sel.value;
  });
  try {
    await api("/api/roles", {
      method: "POST",
      body: JSON.stringify({
        default_role: $("#defaultRole").value,
        groups,
        assignments: roleAssignments,
        master_prompt: collectMasterPayload(),
      }),
    });
    $("#rolesMsg").textContent = "Сохранено";
    loadRoles();
    loadAccounts();
  } catch (e) {
    $("#rolesMsg").textContent = e.message;
  }
};

async function loadDialogs() {
  const rows = await api("/api/dialogs");
  const statusChip = (s) => {
    if (s === "активен") return '<span class="chip ok">активен</span>';
    if (s === "на паузе") return '<span class="chip warn">пауза</span>';
    return `<span class="chip muted">${escapeHtml(s)}</span>`;
  };
  $("#dialogsTable").innerHTML = rows.map((d) => `
    <tr>
      <td>${escapeHtml(d.account_id)}</td>
      <td>@${escapeHtml(d.target)}</td>
      <td><span class="chip">${d.dialog_mode === "agent" ? "агент" : "рассылка"}</span></td>
      <td>${statusChip(d.status_label)}</td>
      <td>${d.auto_reply ? '<span class="chip ok">✓</span>' : '<span class="chip muted">—</span>'}</td>
      <td>${d.replies_count}${d.max_replies ? "/" + d.max_replies : ""}</td>
      <td>${d.messages_count}</td>
      <td>${d.last_activity || "—"}</td>
      <td class="btn-row">
        <button class="btn btn-sm ghost open-dlg" data-key="${escapeHtml(d.key)}">Открыть</button>
        <button class="btn btn-sm danger clear-dlg" data-key="${escapeHtml(d.key)}" title="Стереть память">🗑</button>
      </td>
    </tr>`).join("") || "<tr><td colspan='9' class='hint'>Нет диалогов</td></tr>";
  document.querySelectorAll(".open-dlg").forEach((btn) => {
    btn.onclick = () => openDialogModal(btn.dataset.key);
  });
  document.querySelectorAll(".clear-dlg").forEach((btn) => {
    btn.onclick = () => clearDialogMemory(btn.dataset.key);
  });
}

async function clearDialogMemory(key, closeModal = false) {
  if (!key) return;
  if (!confirm("Стереть память этого диалога? История удалится, при запуске он не возобновится.")) return;
  await api(`/api/dialogs/${encodeURIComponent(key)}/clear-memory`, { method: "POST" });
  if (closeModal) $("#dialogModal").classList.add("hidden");
  loadDialogs();
}

let currentDialogKey = null;

const DIALOG_SETTING_FIELDS = [
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

async function loadDialogSettings() {
  const s = await api("/api/dialog-settings");
  const form = $("#dialogSettingsForm");
  form.innerHTML = DIALOG_SETTING_FIELDS.map(([key, label, type, step]) => `
    <div><label class="label">${label}</label>
    <input type="${type}" id="ds_${key}" value="${s[key] ?? ""}" ${step ? `step="${step}"` : ""}></div>`).join("");
  form.innerHTML += `
    <div><label class="label"><input type="checkbox" id="ds_split_long_messages" ${s.split_long_messages ? "checked" : ""}> Делить длинные ответы</label></div>
    <div><label class="label"><input type="checkbox" id="ds_sync_history_on_resume" ${s.sync_history_on_resume ? "checked" : ""}> Синхронизировать историю при возобновлении</label></div>`;
  $("#ignoreKeywords").value = Array.isArray(s.ignore_keywords) ? s.ignore_keywords.join(", ") : s.ignore_keywords;
  $("#globalExtraPrompt").value = s.global_extra_prompt || "";
}

$("#btnSaveDialogSettings").onclick = async () => {
  const payload = {};
  DIALOG_SETTING_FIELDS.forEach(([key, , type]) => {
    const el = document.getElementById(`ds_${key}`);
    payload[key] = type === "number" ? parseFloat(el.value) || 0 : el.value;
  });
  payload.split_long_messages = $("#ds_split_long_messages")?.checked || false;
  payload.sync_history_on_resume = $("#ds_sync_history_on_resume")?.checked ?? true;
  payload.ignore_keywords = $("#ignoreKeywords").value.split(",").map((x) => x.trim()).filter(Boolean);
  payload.global_extra_prompt = $("#globalExtraPrompt").value;
  try {
    await api("/api/dialog-settings", { method: "POST", body: JSON.stringify(payload) });
    $("#dialogSettingsMsg").textContent = "Сохранено";
  } catch (e) { $("#dialogSettingsMsg").textContent = e.message; }
};

async function openDialogModal(key) {
  currentDialogKey = key;
  const d = await api(`/api/dialogs/${encodeURIComponent(key)}`);
  $("#modalTitle").textContent = `${d.account_id} → @${d.target}`;
  $("#dlgStatus").value = d.status;
  $("#dlgAutoReply").checked = d.auto_reply;
  $("#dlgMaxReplies").value = d.max_replies || 0;
  $("#dlgRepliesCount").value = d.replies_count || 0;
  $("#dlgGoal").value = d.goal || "";
  $("#dlgExtra").value = d.dialog_extra_context || "";
  $("#dlgNotes").value = d.notes || "";
  $("#dlgHistory").innerHTML = d.messages.map((m) =>
    `<div class="${m.role === "user" ? "msg-user" : "msg-bot"}">
      <span class="msg-meta">${m.role === "user" ? "Они" : "Мы"} · ${m.ts}</span><br>${escapeHtml(m.content)}
    </div>`).join("") || "<p class='hint'>Нет сообщений</p>";
  $("#dialogModal").classList.remove("hidden");
}

$("#btnCloseModal").onclick = () => $("#dialogModal").classList.add("hidden");

$("#btnSaveDialog").onclick = async () => {
  if (!currentDialogKey) return;
  await api(`/api/dialogs/${encodeURIComponent(currentDialogKey)}`, {
    method: "PATCH",
    body: JSON.stringify({
      status: $("#dlgStatus").value,
      auto_reply: $("#dlgAutoReply").checked,
      max_replies: parseInt($("#dlgMaxReplies").value) || 0,
      replies_count: parseInt($("#dlgRepliesCount").value) || 0,
      goal: $("#dlgGoal").value,
      dialog_extra_context: $("#dlgExtra").value,
      notes: $("#dlgNotes").value,
    }),
  });
  loadDialogs();
  alert("Сохранено");
};

$("#btnClearDialogMemory").onclick = async () => {
  if (!currentDialogKey) return;
  await clearDialogMemory(currentDialogKey, true);
};

$("#btnDeleteDialog").onclick = async () => {
  if (!currentDialogKey || !confirm("Удалить диалог полностью из списка?")) return;
  await api(`/api/dialogs/${encodeURIComponent(currentDialogKey)}`, { method: "DELETE" });
  $("#dialogModal").classList.add("hidden");
  loadDialogs();
};

$("#btnClearAllDialogs").onclick = async () => {
  if (!confirm("Удалить память ВСЕХ диалогов? Это нельзя отменить.")) return;
  const r = await api("/api/dialogs/clear-all", {
    method: "POST",
    body: JSON.stringify({ delete_completely: true }),
  });
  alert(`Очищено диалогов: ${r.cleared ?? 0}`);
  loadDialogs();
};

$("#btnRefreshDialogs").onclick = loadDialogs;

let editingAgentId = null;

async function loadAgents() {
  const rows = await api("/api/agents");
  const tbody = $("#agentsTable");
  tbody.innerHTML = "";
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="hint">Нажмите «+ Добавить агента»</td></tr>';
    return;
  }
  if (!selectedAgents.size) {
    rows.filter((a) => a.enabled).forEach((a) => selectedAgents.add(a.account_id));
  }
  rows.forEach((a) => {
    const tr = document.createElement("tr");
    const checked = selectedAgents.has(a.account_id) ? "checked" : "";
    const statusHtml = a.running
      ? '<span class="chip ok">онлайн</span>'
      : a.enabled
        ? '<span class="chip">готов</span>'
        : '<span class="chip muted">выкл</span>';
    const warn = !a.account_exists ? ' <span class="chip warn">нет сессии</span>' : "";
    tr.innerHTML = `
      <td><input type="checkbox" data-id="${escapeHtml(a.account_id)}" ${checked}></td>
      <td><strong>${escapeHtml(a.account_id)}</strong>${warn}</td>
      <td>${escapeHtml(a.name || "Секретарь")}</td>
      <td><span class="chip">${escapeHtml(a.language || "ru")}</span></td>
      <td>${statusHtml}</td>
      <td><button class="btn btn-sm ghost edit-agent" data-id="${escapeHtml(a.account_id)}">Настроить</button></td>`;
    tbody.appendChild(tr);
    tr.querySelector("input").onchange = (ev) => {
      if (ev.target.checked) selectedAgents.add(a.account_id);
      else selectedAgents.delete(a.account_id);
    };
    tr.querySelector(".edit-agent").onclick = () => openAgentModal(a.account_id, rows);
  });
}

async function openAgentModal(accountId, cachedRows) {
  editingAgentId = accountId || null;
  const accounts = await api("/api/accounts");
  const rows = cachedRows || await api("/api/agents");
  const agent = accountId ? rows.find((a) => a.account_id === accountId) : null;
  const candidates = accounts.filter((a) => {
    if (agent && a.id === agent.account_id) return true;
    return a.is_active && !a.is_assistant;
  });
  const select = $("#agentAccount");
  if (!candidates.length) {
    alert("Нет свободных активных аккаунтов. Сконвертируйте .session или снимите другого ассистента.");
    return;
  }
  select.innerHTML = candidates.map((a) =>
    `<option value="${escapeHtml(a.id)}">${escapeHtml(a.id)}</option>`).join("");
  $("#agentModalTitle").textContent = agent ? `Агент: ${agent.account_id}` : "Новый AI-агент";
  select.value = agent?.account_id || candidates[0].id;
  select.disabled = !!agent;
  $("#agentName").value = agent?.name || "Секретарь";
  $("#agentPrompt").value = agent?.prompt || "";
  $("#agentGoal").value = agent?.goal || "";
  $("#agentLanguage").value = agent?.language || "ru";
  $("#agentExtra").value = agent?.extra_context || "";
  $("#agentAllowed").value = Array.isArray(agent?.allowed_users) ? agent.allowed_users.join(", ") : "";
  $("#agentBlocked").value = Array.isArray(agent?.blocked_users) ? agent.blocked_users.join(", ") : "";
  $("#agentEnabled").checked = agent?.enabled !== false;
  $("#btnDeleteAgent").style.display = agent ? "" : "none";
  $("#agentModal").classList.remove("hidden");
}

$("#btnAddAgent").onclick = () => openAgentModal(null);
$("#btnCloseAgentModal").onclick = () => $("#agentModal").classList.add("hidden");
$("#btnRefreshAgents").onclick = loadAgents;

$("#btnSaveAgent").onclick = async () => {
  const payload = {
    account_id: $("#agentAccount").value,
    name: $("#agentName").value,
    prompt: $("#agentPrompt").value,
    goal: $("#agentGoal").value,
    language: $("#agentLanguage").value,
    extra_context: $("#agentExtra").value,
    allowed_users: $("#agentAllowed").value.split(",").map((x) => x.trim()).filter(Boolean),
    blocked_users: $("#agentBlocked").value.split(",").map((x) => x.trim()).filter(Boolean),
    enabled: $("#agentEnabled").checked,
  };
  try {
    await api("/api/agents", { method: "POST", body: JSON.stringify(payload) });
    $("#agentModal").classList.add("hidden");
    selectedAgents.add(payload.account_id);
    loadAgents();
    loadAccounts();
    refreshStatus();
    $("#agentsMsg").textContent = "Сохранено";
  } catch (e) {
    $("#agentsMsg").textContent = e.message;
  }
};

$("#btnDeleteAgent").onclick = async () => {
  const id = $("#agentAccount").value;
  if (!id || !confirm(`Удалить агента ${id}?`)) return;
  await api(`/api/agents/${encodeURIComponent(id)}`, { method: "DELETE" });
  selectedAgents.delete(id);
  $("#agentModal").classList.add("hidden");
  loadAgents();
  loadAccounts();
  refreshStatus();
};

$("#btnStartAgents").onclick = async () => {
  const ids = selectedAgents.size ? [...selectedAgents] : [];
  if (!ids.length) return alert("Выберите агентов в таблице");
  try {
    await api("/api/agents/start", { method: "POST", body: JSON.stringify({ account_ids: ids }) });
    refreshStatus();
    loadAgents();
    $("#agentsMsg").textContent = "Секретарь запущен";
  } catch (e) {
    alert(e.message);
  }
};

$("#btnStopAgents").onclick = async () => {
  await api("/api/agents/stop", { method: "POST" });
  refreshStatus();
  loadAgents();
};

const GROUP_CHAT_SETTING_FIELDS = [
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

function renderGroupChatAccounts() {
  const tbody = $("#groupChatAccountsTable");
  if (!tbody) return;
  tbody.innerHTML = "";
  const rows = (accountsCache || []).filter((a) => a.is_active !== false);
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="hint">Нет аккаунтов — добавьте сессии</td></tr>';
    return;
  }
  rows.forEach((a) => {
    const role = roleAssignments[a.id] || "—";
    const checked = selectedGroupChatAccounts.has(a.id) ? "checked" : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" data-gc-id="${escapeHtml(a.id)}" ${checked}></td>
      <td><strong>${escapeHtml(a.id)}</strong></td>
      <td><span class="chip">${escapeHtml(role)}</span></td>
      <td><input type="number" class="gc-weight" data-gc-id="${escapeHtml(a.id)}" value="1" min="0.1" step="0.1" style="width:4.5rem"></td>`;
    tbody.appendChild(tr);
    tr.querySelector("input[type=checkbox]").onchange = (ev) => {
      if (ev.target.checked) selectedGroupChatAccounts.add(a.id);
      else selectedGroupChatAccounts.delete(a.id);
      renderGroupChatRoleOverrides();
    };
  });
  renderGroupChatRoleOverrides();
}

function renderGroupChatRoleOverrides() {
  const box = $("#groupChatRolesBox");
  if (!box) return;
  const ids = [...selectedGroupChatAccounts];
  if (ids.length < 2) {
    box.innerHTML = '<p class="hint">Выберите минимум 2 аккаунта, чтобы задать роли.</p>';
    return;
  }
  box.innerHTML = ids.map((id) => {
    const group = roleAssignments[id] || "";
    const g = (roleGroupsData || []).find((x) => x.name === group);
    const prompt = g?.role_prompt || "";
    return `
      <div class="card" style="margin:0.75rem 0;padding:0.75rem" data-gc-role="${escapeHtml(id)}">
        <strong>${escapeHtml(id)}</strong>
        <label class="label">Имя роли</label>
        <input type="text" class="gc-role-name" value="${escapeHtml(group || "участник")}">
        <label class="label">Промпт роли (можно переопределить)</label>
        <textarea class="gc-role-prompt" rows="3">${escapeHtml(prompt)}</textarea>
      </div>`;
  }).join("");
}

async function loadGroupChatSettings() {
  const s = await api("/api/group-chat/settings");
  GROUP_CHAT_SETTING_FIELDS.forEach((key) => {
    const el = $(`#gc_${key}`);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!s[key];
    else el.value = s[key] ?? "";
  });
  const tz = $("#gc_timezone_offset_hours");
  if (tz) tz.value = s.timezone_offset_hours == null ? "" : s.timezone_offset_hours;
  const win = $("#gc_activity_windows");
  if (win) win.value = JSON.stringify(s.activity_windows || [], null, 2);
  const stop = $("#gc_stop_keywords");
  if (stop) stop.value = Array.isArray(s.stop_keywords) ? s.stop_keywords.join(", ") : "";
}

async function saveGroupChatSettings() {
  const payload = {};
  GROUP_CHAT_SETTING_FIELDS.forEach((key) => {
    const el = $(`#gc_${key}`);
    if (!el) return;
    if (el.type === "checkbox") payload[key] = el.checked;
    else if (el.type === "number") payload[key] = el.value === "" ? 0 : Number(el.value);
    else payload[key] = el.value;
  });
  const tz = $("#gc_timezone_offset_hours").value;
  payload.timezone_offset_hours = tz === "" ? null : Number(tz);
  try {
    payload.activity_windows = JSON.parse($("#gc_activity_windows").value || "[]");
  } catch (_) {
    $("#groupChatSettingsMsg").textContent = "Ошибка JSON в окнах активности";
    return;
  }
  payload.stop_keywords = $("#gc_stop_keywords").value.split(",").map((x) => x.trim()).filter(Boolean);
  try {
    await api("/api/group-chat/settings", { method: "POST", body: JSON.stringify(payload) });
    $("#groupChatSettingsMsg").textContent = "Настройки сохранены";
  } catch (e) {
    $("#groupChatSettingsMsg").textContent = e.message;
  }
}

async function findCommonGroupChats() {
  const ids = [...selectedGroupChatAccounts];
  if (ids.length < 2) return alert("Выберите минимум 2 аккаунта");
  $("#groupChatMsg").textContent = "Ищем общие чаты...";
  try {
    const data = await api("/api/group-chat/common-chats", {
      method: "POST",
      body: JSON.stringify({ account_ids: ids }),
    });
    groupChatCommonCache = data.chats || [];
    const sel = $("#groupChatSelect");
    if (!groupChatCommonCache.length) {
      sel.innerHTML = '<option value="">— общих чатов нет —</option>';
      $("#groupChatMsg").textContent = "Общих групп не найдено";
      return;
    }
    sel.innerHTML = groupChatCommonCache.map((c) =>
      `<option value="${c.chat_id}">${escapeHtml(c.title)} (${c.kind}, ${c.chat_id})</option>`
    ).join("");
    $("#groupChatMsg").textContent = `Найдено: ${groupChatCommonCache.length}`;
  } catch (e) {
    $("#groupChatMsg").textContent = e.message;
    alert(e.message);
  }
}

async function refreshGroupChatStatus() {
  const st = await api("/api/group-chat/status");
  const chip = $("#groupChatStats");
  if (chip) {
    if (st.running) {
      chip.className = "chip ok";
      chip.textContent = st.paused_schedule ? "Пауза (расписание)" : "Онлайн";
    } else {
      chip.className = "chip muted";
      chip.textContent = "Остановлен";
    }
  }
  const live = $("#groupChatLiveStats");
  if (live) {
    live.textContent = st.running
      ? `${st.status_text || "работает"} · отправлено: ${st.messages_sent} · день: ${st.group_day_count}`
      : (st.status_text || "Ожидание запуска");
  }
  const log = $("#groupChatLog");
  if (log && Array.isArray(st.recent_messages)) {
    log.textContent = st.recent_messages.map((m) =>
      `${m.speaker_name || m.speaker_account_id}: ${m.text}`
    ).join("\n");
  }
}

async function startGroupChat() {
  const ids = [...selectedGroupChatAccounts];
  if (ids.length < 2) return alert("Выберите минимум 2 аккаунта");
  const chatId = Number($("#groupChatSelect").value || 0);
  if (!chatId) return alert("Выберите общий чат");
  const topic = $("#groupChatTopic").value.trim();
  if (!topic) return alert("Укажите тему");
  const chat = groupChatCommonCache.find((c) => Number(c.chat_id) === chatId);
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
    await saveGroupChatSettings();
    await api("/api/group-chat/start", {
      method: "POST",
      body: JSON.stringify({
        account_ids: ids,
        chat_id: chatId,
        chat_title: chat?.title || "",
        topic,
        extra_context: $("#groupChatExtra").value,
        role_overrides,
        activity_weights,
      }),
    });
    $("#groupChatMsg").textContent = "Запущено";
    refreshStatus();
    refreshGroupChatStatus();
  } catch (e) {
    alert(e.message);
  }
}

async function stopGroupChat() {
  await api("/api/group-chat/stop", { method: "POST" });
  refreshStatus();
  refreshGroupChatStatus();
}

async function loadGroupChat() {
  renderGroupChatAccounts();
  await loadGroupChatSettings();
  await refreshGroupChatStatus();
}

$("#btnFindCommonChats").onclick = findCommonGroupChats;
$("#btnSaveGroupChatSettings").onclick = saveGroupChatSettings;
$("#btnStartGroupChat").onclick = startGroupChat;
$("#btnStopGroupChat").onclick = stopGroupChat;
$("#btnRefreshGroupChat").onclick = () => { renderGroupChatAccounts(); refreshGroupChatStatus(); };

async function startEngine(resumeOnly) {
  try {
    let accountIds = selectedForRun.size ? [...selectedForRun] : [];
    const skipped = accountIds.filter((id) => !accountsCache.find((a) => a.id === id)?.outreach_eligible);
    accountIds = accountIds.filter((id) => accountsCache.find((a) => a.id === id)?.outreach_eligible);
    if (skipped.length) {
      const names = skipped.join(", ");
      if (!accountIds.length && !resumeOnly) {
        alert(`Выбранные аккаунты не подходят для рассылки (ассистент или неактивен): ${names}`);
        return;
      }
    }
    await api("/api/engine/start", {
      method: "POST",
      body: JSON.stringify({
        targets: $("#targets").value,
        account_ids: accountIds,
        extra_context: $("#extraContext").value,
        enable_dialog: $("#enableDialog").checked,
        resume_existing: $("#resumeExisting").checked,
        resume_only: resumeOnly,
      }),
    });
    refreshStatus();
  } catch (e) { alert(e.message); }
}

$("#btnStart").onclick = () => startEngine(false);
$("#btnResume").onclick = () => startEngine(true);
$("#btnStop").onclick = async () => { await api("/api/engine/stop", { method: "POST" }); refreshStatus(); };

async function tick() {
  await refreshStatus();
  await refreshEngine();
  await refreshLogs();
}

async function bootstrap() {
  if (window.__panelBootStarted) return;
  window.__panelBootStarted = true;
  initNavigation();
  await Promise.allSettled([
    loadConfig(),
    loadProxyPool(),
    loadAccounts(),
    loadRoles(),
    loadDialogSettings(),
    loadDialogs(),
    loadAgents(),
    loadGroupChat(),
    refreshStatus(),
  ]);
  if (!window.__panelTickHandle) {
    window.__panelTickHandle = setInterval(() => {
      tick().catch(() => {});
    }, 1500);
  }
}
