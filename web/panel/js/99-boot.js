/* Kot_Teamlead boot */
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
