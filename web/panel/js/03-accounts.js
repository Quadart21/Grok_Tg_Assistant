/* Kot_Teamlead */
(function () {
  const P = window.Panel = window.Panel || {};

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

})();
