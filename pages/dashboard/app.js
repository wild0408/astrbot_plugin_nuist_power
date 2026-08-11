// NUIST Power Dashboard - SSE real-time
const bridge = window.AstrBotPluginPage;
let chart = null;
let allAccounts = [];
let currentGroup = "raw";
let sseSubId = null;

await bridge.ready();

function applyTheme() {
  const c = bridge.getContext();
  document.documentElement.setAttribute("data-theme", c?.isDark ? "dark" : "light");
}
applyTheme();
bridge.onContext(() => { applyTheme(); if (chart) updateChartColors(); });

// ---- SSE ----
async function connectSSE() {
  if (sseSubId) await bridge.unsubscribeSSE(sseSubId);
  sseSubId = await bridge.subscribeSSE("dashboard/stream", {
    onOpen() { console.log("SSE connected"); hideError(); },
    onMessage(event) {
      try {
        const data = event.parsed;
        if (!data || !data.accounts) return;
        allAccounts = data.accounts;
        renderSummary(data.accounts);
        renderAccountTable(data.accounts);
        if (!document.getElementById("account-selector").dataset.init) {
          populateAccountSelector(data.accounts);
          document.getElementById("account-selector").dataset.init = "1";
          loadChartData();
        }
        showEmpty(data.accounts.length === 0);
        showContent(data.accounts.length > 0);
        showLoading(false);
      } catch (e) { console.error("SSE parse error:", e); }
    },
    onError() { console.warn("SSE error, will retry"); },
  });
  console.log("SSE subscribed:", sseSubId);
}

// ---- Chart Data (still REST for group switching) ----
async function loadChartData() {
  const sel = document.getElementById("account-selector");
  const accountId = parseInt(sel.value);
  if (!accountId) return;
  try {
    const histData = await bridge.apiGet("dashboard/history_grouped", { account_id: accountId, group: currentGroup });
    renderChart(histData.history, histData.group);
  } catch (e) {
    document.getElementById("chart-empty").classList.remove("hidden");
    document.getElementById("chart").style.display = "none";
  }
}

function setupGroupToggle() {
  document.querySelectorAll(".group-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".group-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentGroup = btn.dataset.group;
      await loadChartData();
    });
  });
}

// ---- Render ----
function renderSummary(accounts) {
  const container = document.getElementById("summary-cards");
  let totalSubs = 0, totalAlerts = 0;
  accounts.forEach(acc => {
    totalSubs += (acc.subscriptions || []).filter(s => s.enabled).length;
    (acc.subscriptions || []).forEach(s => {
      if (s.enabled && acc.latest_balance !== null && acc.latest_balance < s.threshold) totalAlerts++;
    });
  });
  const cards = [
    { label: "绑定账号", value: accounts.length, unit: "个", icon: "👤" },
    { label: "活跃订阅", value: totalSubs, unit: "个", icon: "📬" },
    { label: "低电量告警", value: totalAlerts, unit: "个", icon: totalAlerts > 0 ? "🚨" : "✅" },
    { label: "Token 有效", value: accounts.filter(a => a.token_valid).length, unit: `/${accounts.length}`, icon: "🔑" },
  ];
  container.innerHTML = cards.map(c => `
    <div class="card ${c.label === "低电量告警" && c.value > 0 ? "card-alert" : ""}">
      <div class="card-icon">${c.icon}</div>
      <div class="card-value">${c.value}<span class="card-unit">${c.unit}</span></div>
      <div class="card-label">${c.label}</div>
    </div>`).join("");
}

function populateAccountSelector(accounts) {
  const sel = document.getElementById("account-selector");
  sel.innerHTML = accounts.map(a => `<option value="${a.id}">${a.building} ${a.room}号房 (${a.student_id})</option>`).join("");
  sel.onchange = () => loadChartData();
  setupGroupToggle();
}

function renderChart(history, group) {
  const ce = document.getElementById("chart-empty"), canvas = document.getElementById("chart");
  if (!history || history.length < 2) { ce.classList.remove("hidden"); canvas.style.display = "none"; if (chart) { chart.destroy(); chart = null; } return; }
  ce.classList.add("hidden"); canvas.style.display = "";
  const c = bridge.getContext(); const isDark = c?.isDark ?? false;
  const gc = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
  const tc = isDark ? "#aaa" : "#666";
  let labels, values;
  if (group === "raw") {
    labels = history.map(h => { const d = new Date(h.time+"Z"); return `${String(d.getMonth()+1).padStart(2,"0")}/${String(d.getDate()).padStart(2,"0")} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; });
    values = history.map(h => h.balance);
  } else if (group === "day") {
    labels = history.map(h => h.time.slice(5)); values = history.map(h => h.balance);
  } else {
    labels = history.map(h => h.time); values = history.map(h => h.balance);
  }
  if (chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: { labels, datasets: [{ label: group === "raw" ? "剩余电量 (度)" : `日均电量 (度/${group==="day"?"天":"月"})`, data: values, borderColor: "#4f9cf5", backgroundColor: isDark ? "rgba(79,156,245,0.15)" : "rgba(79,156,245,0.08)", fill: true, tension: 0.3, pointRadius: 2, pointHoverRadius: 5 }] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" }, plugins: { legend: { labels: { color: tc, font: { size: 12 } } } }, scales: { x: { ticks: { color: tc, maxTicksLimit: 12, font: { size: 10 } }, grid: { color: gc } }, y: { ticks: { color: tc, font: { size: 10 } }, grid: { color: gc }, title: { display: true, text: "度", color: tc } } } },
  });
}

function updateChartColors() {
  if (!chart) return;
  const c = bridge.getContext(); const isDark = c?.isDark ?? false;
  const gc = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
  const tc = isDark ? "#aaa" : "#666";
  chart.options.scales.x.ticks.color = tc; chart.options.scales.x.grid.color = gc;
  chart.options.scales.y.ticks.color = tc; chart.options.scales.y.grid.color = gc;
  chart.options.plugins.legend.labels.color = tc;
  if (chart.data.datasets[0]) chart.data.datasets[0].backgroundColor = isDark ? "rgba(79,156,245,0.15)" : "rgba(79,156,245,0.08)";
  chart.update();
}

function renderAccountTable(accounts) {
  document.getElementById("account-tbody").innerHTML = accounts.map(a => {
    const subs = (a.subscriptions || []).filter(s => s.enabled);
    const subText = subs.length > 0 ? subs.map(s => `每${s.interval_minutes}min<br>阈值${s.threshold}/${s.critical_threshold}度`).join("<br>") : "—";
    const balText = a.latest_balance !== null ? `${a.latest_balance.toFixed(2)} 度` : "—";
    const dailyText = a.daily_consumption?.enough_data ? `<br><small>日耗 ${a.daily_consumption.daily} 度 | 约剩 ${a.daily_consumption.days_remaining} 天</small>` : "";
    return `<tr><td>${escapeHtml(a.student_id)}</td><td>${escapeHtml(a.campus)}</td><td>${escapeHtml(a.building)}</td><td>${escapeHtml(a.room)}</td><td><span class="status ${a.token_valid?'status-ok':'status-bad'}">${a.token_valid?"有效":"过期"}</span></td><td>${subText}</td><td>${balText}${dailyText}</td></tr>`;
  }).join("");
}

function showLoading(s) { document.getElementById("loading").classList.toggle("hidden", !s); }
function showError(msg) { const el = document.getElementById("error"); el.textContent = "❌ " + msg; el.classList.remove("hidden"); }
function hideError() { document.getElementById("error").classList.add("hidden"); }
function showContent(s) { document.getElementById("content").classList.toggle("hidden", !s); }
function showEmpty(s) { document.getElementById("empty").classList.toggle("hidden", !s); }
function escapeHtml(t) { return t ? String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;") : ""; }

// ---- Start ----
showLoading(true);
await connectSSE();

window.addEventListener("beforeunload", () => {
  if (sseSubId) bridge.unsubscribeSSE(sseSubId);
  if (chart) chart.destroy();
});