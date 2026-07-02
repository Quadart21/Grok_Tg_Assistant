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

P.showTab = function(name) {
  P.$$("#tabNav .nav-item").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  P.$$(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
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
  const running = s.running || s.agent_running;
  if (s.running && s.agent_running) badge.textContent = "рассылка + секретарь";
  else if (s.running) badge.textContent = "рассылка";
  else if (s.agent_running) badge.textContent = "секретарь";
  else badge.textContent = "остановлено";
  badge.classList.toggle("running", running);
  P.$("#btnStop").disabled = !s.running;
  P.$("#btnStart").disabled = s.running;
  P.$("#btnResume").disabled = s.running;
  P.$("#btnStopAgents").disabled = !s.agent_running;
  P.$("#btnStartAgents").disabled = s.agent_running;
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
    if (!el) return;
    if (a.running) {
      el.className = "chip ok";
      el.textContent = `Онлайн: ${a.active_accounts} · Диалогов: ${a.active_dialogs} · Ответов: ${a.replies_sent}`;
    } else {
      el.className = "chip muted";
      el.textContent = "Остановлен";
    }
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
  const savedModel = c.llm_model || c.grok_model || "grok-3-mini";
  await P.loadLlmModels(c.llm_provider || "grok", savedModel);
  P.$("#delayMsg").value = c.delay_between_messages_sec;
  P.$("#concurrent").value = c.max_concurrent_accounts;
  P.$("#replyMin").value = c.reply_delay_min_sec;
  P.$("#replyMax").value = c.reply_delay_max_sec;
  P.$("#language").value = c.message_language;
  P.$("#telegram2fa").value = c.telegram_2fa_password || "";
}

P.$("#btnRefreshModels").onclick = async () => {
  try {
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

})();
