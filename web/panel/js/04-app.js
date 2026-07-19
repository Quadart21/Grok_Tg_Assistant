/* Kot_Teamlead */
(function () {
  const P = window.Panel = window.Panel || {};


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

})();
