/* Kot_Teamlead */
(function () {
  const P = window.Panel = window.Panel || {};

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

})();
