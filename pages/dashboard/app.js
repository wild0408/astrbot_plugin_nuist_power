// NUIST Power Dashboard - AstrBot Plugin Page
const bridge = window.AstrBotPluginPage;
let chart = null;
let refreshTimer = null;
let allAccounts = [];

// ---- Init ----
const ctx = await bridge.ready();
console.log("Dashboard context:", ctx);

document.addEventListener("DOMContentLoaded", () => {
  // Actually, in a module script this fires before module runs.
  // Safe to call here as backup.
});

// Apply theme
function applyTheme() {
  const ctx = bridge.getContext();
  const isDark = ctx?.isDark ?? false;
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
}
applyTheme();
bridge.onContext(() => {
  applyTheme();
  if (chart) updateChartColors();
});

// ---- Data Loading ----
async function loadData() {
  showLoading(true);
  hideError();
  try {
    const data = await bridge.apiGet("dashboard/overview");
    if (!data.accounts || data.accounts.length === 0) {
      showEmpty(true);
      showContent(false);
      return;
    }
    showEmpty(false);
    showContent(true);
    allAccounts = data.accounts;
    renderSummary(data.accounts);
    renderAccountTable(data.accounts);
    populateAccountSelector(data.accounts);
    renderChart(data.accounts);
  } catch (e) {
    showError("加载失败: " + (e.message || JSON.stringify(e)));
  } finally {
    showLoading(false);
  }
}

// ---- Render ----
function renderSummary(accounts) {
  const container = document.getElementById("summary-cards");
  let totalSubs = 0;
  let totalAlerts = 0;
  accounts.forEach((acc) => {
    totalSubs += (acc.subscriptions || []).filter((s) => s.enabled).length;
    (acc.subscriptions || []).forEach((s) => {
      if (s.enabled && acc.latest_balance !== null && acc.latest_balance < s.threshold) {
        totalAlerts++;
      }
    });
  });

  const cards = [
    { label: "绑定账号", value: accounts.length, unit: "个", icon: "👤" },
    { label: "活跃订阅", value: totalSubs, unit: "个", icon: "📬" },
    { label: "低电量告警", value: totalAlerts, unit: "个", icon: totalAlerts > 0 ? "🚨" : "✅" },
    { label: "Token 有效", value: accounts.filter((a) => a.token_valid).length, unit: `/${accounts.length}`, icon: "🔑" },
  ];

  container.innerHTML = cards
    .map(
      (c) => `
    <div class="card ${c.label === "低电量告警" && c.value > 0 ? "card-alert" : ""}">
      <div class="card-icon">${c.icon}</div>
      <div class="card-value">${c.value}<span class="card-unit">${c.unit}</span></div>
      <div class="card-label">${c.label}</div>
    </div>`
    )
    .join("");
}

function populateAccountSelector(accounts) {
  const sel = document.getElementById("account-selector");
  sel.innerHTML = accounts
    .map(
      (a, i) =>
        `<option value="${a.id}">${a.building} ${a.room}号房 (${a.student_id})</option>`
    )
    .join("");
  sel.onchange = () => {
    const id = parseInt(sel.value);
    const acc = accounts.find((a) => a.id === id);
    if (acc) renderChartForAccount(acc);
  };
  // Default: first account
  sel.dispatchEvent(new Event("change"));
}

function renderChart(accounts) {
  if (accounts.length > 0) renderChartForAccount(accounts[0]);
}

function renderChartForAccount(account) {
  const history = account.history || [];
  const chartEmpty = document.getElementById("chart-empty");
  const canvas = document.getElementById("chart");

  if (history.length < 2) {
    chartEmpty.classList.remove("hidden");
    canvas.style.display = "none";
    if (chart) { chart.destroy(); chart = null; }
    return;
  }
  chartEmpty.classList.add("hidden");
  canvas.style.display = "";

  // Parse dates
  const labels = history.map((h) => {
    const d = new Date(h.time + "Z");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${mm}/${dd} ${hh}:${min}`;
  });
  const values = history.map((h) => h.balance);

  const ctx = bridge.getContext();
  const isDark = ctx?.isDark ?? false;
  const gridColor = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
  const textColor = isDark ? "#aaa" : "#666";

  if (chart) chart.destroy();

  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "剩余电量 (度)",
          data: values,
          borderColor: "#4f9cf5",
          backgroundColor: isDark ? "rgba(79,156,245,0.15)" : "rgba(79,156,245,0.08)",
          fill: true,
          tension: 0.3,
          pointRadius: 2,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { labels: { color: textColor, font: { size: 12 } } },
      },
      scales: {
        x: {
          ticks: { color: textColor, maxTicksLimit: 12, font: { size: 10 } },
          grid: { color: gridColor },
        },
        y: {
          ticks: { color: textColor, font: { size: 10 } },
          grid: { color: gridColor },
          title: { display: true, text: "度", color: textColor },
        },
      },
    },
  });
}

function updateChartColors() {
  if (!chart) return;
  const ctx = bridge.getContext();
  const isDark = ctx?.isDark ?? false;
  const gridColor = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)";
  const textColor = isDark ? "#aaa" : "#666";
  chart.options.scales.x.ticks.color = textColor;
  chart.options.scales.x.grid.color = gridColor;
  chart.options.scales.y.ticks.color = textColor;
  chart.options.scales.y.grid.color = gridColor;
  chart.options.plugins.legend.labels.color = textColor;
  if (chart.data.datasets[0]) {
    chart.data.datasets[0].backgroundColor = isDark
      ? "rgba(79,156,245,0.15)"
      : "rgba(79,156,245,0.08)";
  }
  chart.update();
}

function renderAccountTable(accounts) {
  const tbody = document.getElementById("account-tbody");
  tbody.innerHTML = accounts
    .map((a) => {
      const subs = (a.subscriptions || []).filter((s) => s.enabled);
      const subText =
        subs.length > 0
          ? subs.map((s) => `每${s.interval_minutes}min<br>阈值${s.threshold}/${s.critical_threshold}度`).join("<br>")
          : "—";
      const balText =
        a.latest_balance !== null
          ? `${a.latest_balance.toFixed(2)} 度`
          : "—";
      const dailyText = a.daily_consumption?.enough_data
        ? `<br><small>日耗 ${a.daily_consumption.daily} 度 | 约剩 ${a.daily_consumption.days_remaining} 天</small>`
        : "";
      return `
      <tr>
        <td>${escapeHtml(a.student_id)}</td>
        <td>${escapeHtml(a.campus)}</td>
        <td>${escapeHtml(a.building)}</td>
        <td>${escapeHtml(a.room)}</td>
        <td><span class="status ${a.token_valid ? 'status-ok' : 'status-bad'}">${a.token_valid ? "有效" : "过期"}</span></td>
        <td>${subText}</td>
        <td>${balText}${dailyText}</td>
      </tr>`;
    })
    .join("");
}

// ---- UI helpers ----
function showLoading(show) {
  document.getElementById("loading").classList.toggle("hidden", !show);
}

function showError(msg) {
  const el = document.getElementById("error");
  el.textContent = "❌ " + msg;
  el.classList.remove("hidden");
}

function hideError() {
  document.getElementById("error").classList.add("hidden");
}

function showContent(show) {
  document.getElementById("content").classList.toggle("hidden", !show);
}

function showEmpty(show) {
  document.getElementById("empty").classList.toggle("hidden", !show);
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ---- Refresh ----
function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(loadData, 60000);
}

// ---- Init load ----
await loadData();
startAutoRefresh();

// Cleanup on unload
window.addEventListener("beforeunload", () => {
  if (refreshTimer) clearInterval(refreshTimer);
  if (chart) chart.destroy();
});