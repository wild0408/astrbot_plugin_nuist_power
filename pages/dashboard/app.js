// NUIST Power Dashboard v1.2.6
var B = window.AstrBotPluginPage;
var chart = null, group = "raw", timer = null;

function fmt(v) { return (v != null) ? Number(v).toFixed(2) : "—"; }
function fmtInt(v) { return (v != null) ? Math.round(v) : "—"; }
function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function escAttr(s) { return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;"); }

await B.ready();

(function applyTheme() {
  document.documentElement.setAttribute("data-theme", B.getContext()?.isDark ? "dark" : "light");
})();
B.onContext(function () {
  document.documentElement.setAttribute("data-theme", B.getContext()?.isDark ? "dark" : "light");
  if (chart) updateChartColors();
});

document.getElementById("loading").classList.add("hidden");

// ---- Sidebar tabs ----
document.querySelectorAll(".nav-item").forEach(function (item) {
  item.addEventListener("click", function () {
    document.querySelectorAll(".nav-item").forEach(function (j) { j.classList.remove("active"); });
    item.classList.add("active");
    document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.add("hidden"); });
    document.getElementById("tab-" + item.dataset.tab).classList.remove("hidden");
    if (item.dataset.tab === "users") loadUsers();
  });
});

// ---- Confirm Dialog (replaces window.confirm) ----
var confirmCb = null;
document.getElementById("confirm-cancel").addEventListener("click", function () {
  document.getElementById("confirm-dialog").classList.add("hidden"); confirmCb = null;
});
document.getElementById("confirm-ok").addEventListener("click", function () {
  document.getElementById("confirm-dialog").classList.add("hidden");
  if (confirmCb) { var cb = confirmCb; confirmCb = null; cb(); }
});
function showConfirm(msg, onOk) {
  document.getElementById("confirm-msg").textContent = msg;
  document.getElementById("confirm-dialog").classList.remove("hidden");
  confirmCb = onOk;
}

// ---- Action handlers (event delegation) ----
document.addEventListener("click", function (e) {
  var btn = e.target.closest("button");
  if (!btn) return;

  if (btn.classList.contains("btn-unbind")) {
    var id = parseInt(btn.getAttribute("data-account-id"));
    var label = btn.getAttribute("data-label") || "";
    if (!id) return;
    showConfirm("确认解绑账号 " + label + "？\n此操作不可撤销，订阅和历史记录也会一并删除。", function () {
      B.apiPost("dashboard/unbind", { account_id: id }).then(function (r) {
        if (r && r.success) { loadUsers(); loadOverview(); }
        else { showError((r && r.message) || "解绑失败"); }
      }).catch(function (e) { showError("解绑失败: " + (e.message || e)); });
    });
  }

  if (btn.classList.contains("btn-edit")) {
    var raw = btn.getAttribute("data-account");
    if (!raw) return;
    try { openModal(JSON.parse(raw)); } catch (ex) { console.error("[NUIST] parse error:", ex); }
  }
});

// ---- Edit Modal ----
var editModal = document.getElementById("edit-modal");
document.getElementById("modal-close").addEventListener("click", function () { editModal.classList.add("hidden"); });
document.getElementById("modal-cancel").addEventListener("click", function () { editModal.classList.add("hidden"); });
editModal.addEventListener("click", function (e) { if (e.target === editModal) editModal.classList.add("hidden"); });
document.getElementById("modal-save").addEventListener("click", saveEdit);

function openModal(account) {
  document.getElementById("edit-account-id").value = account.id || "";
  document.getElementById("edit-student-id").value = account.student_id || "";
  document.getElementById("edit-password").value = "";
  document.getElementById("edit-xiaoqu-id").value = account.xiaoqu_id || "";
  document.getElementById("edit-loudong-id").value = account.loudong_id || "";
  document.getElementById("edit-room-id").value = account.room_id || "";
  // Subscription fields
  var sub = (account.subscriptions || []).find(function (s) { return s.enabled; });
  document.getElementById("edit-interval").value = (sub && sub.interval_minutes) || 60;
  document.getElementById("edit-threshold").value = (sub && sub.threshold) || 10;
  document.getElementById("edit-critical").value = (sub && sub.critical_threshold) || 5;
  document.getElementById("edit-sub-enabled").checked = !!(sub && sub.enabled);
  editModal.classList.remove("hidden");
}

async function saveEdit() {
  var id = parseInt(document.getElementById("edit-account-id").value);
  if (!id) return;
  var body = { account_id: id };
  var pw = document.getElementById("edit-password").value.trim();
  if (pw) body.password = pw;
  body.student_id = document.getElementById("edit-student-id").value.trim();
  body.xiaoqu_id = document.getElementById("edit-xiaoqu-id").value.trim();
  body.loudong_id = document.getElementById("edit-loudong-id").value.trim();
  body.room_id = document.getElementById("edit-room-id").value.trim();
  // Subscription fields
  body.interval_minutes = parseInt(document.getElementById("edit-interval").value) || 60;
  body.threshold = parseFloat(document.getElementById("edit-threshold").value) || 10;
  body.critical_threshold = parseFloat(document.getElementById("edit-critical").value) || 5;
  body.enabled = document.getElementById("edit-sub-enabled").checked;
  try {
    var r = await B.apiPost("dashboard/edit", body);
    if (r && r.success) { editModal.classList.add("hidden"); loadUsers(); loadOverview(); }
    else { showError((r && r.message) || "保存失败"); }
  } catch (e) { showError("保存失败: " + (e.message || e)); }
}

function showError(msg) {
  var er = document.getElementById("error");
  er.textContent = "⚠️ " + msg;
  er.classList.remove("hidden");
  setTimeout(function () { er.classList.add("hidden"); }, 4000);
}

// ---- Load overview ----
async function loadOverview() {
  try {
    var d = await B.apiGet("dashboard/overview");
    if (!d || !d.accounts) return;
    var accounts = d.accounts;
    var subs = 0, alerts = 0;
    accounts.forEach(function (a) {
      (a.subscriptions || []).forEach(function (s) {
        if (s.enabled) { subs++; if (a.latest_balance != null && a.latest_balance < s.threshold) alerts++; }
      });
    });
    document.getElementById("summary-cards").innerHTML = [
      { label: "绑定账号", value: accounts.length, icon: "👤", alert: false, success: false },
      { label: "活跃订阅", value: subs, icon: "📬", alert: false, success: false },
      { label: "低电量告警", value: alerts, icon: alerts > 0 ? "🚨" : "✅", alert: alerts > 0, success: alerts === 0 },
      { label: "Token 有效", value: accounts.filter(function (a) { return a.token_valid; }).length, icon: "🔑", alert: false, success: false }
    ].map(function (c) {
      var cls = c.alert ? " card-alert" : (c.success ? " card-success" : "");
      return '<div class="card' + cls + '"><div class="card-icon-wrap">' + c.icon + '</div><div class="card-value">' + c.value + '</div><div class="card-label">' + c.label + '</div></div>';
    }).join("");
    var sel = document.getElementById("account-selector");
    if (!sel.dataset.init) {
      sel.innerHTML = accounts.map(function (a) { return '<option value="' + a.id + '">' + a.building + " " + a.room + "号房 · " + a.student_id + "</option>"; }).join("");
      sel.onchange = loadChart; sel.dataset.init = "1"; loadChart();
    }
    document.getElementById("empty").classList.toggle("hidden", accounts.length > 0);
    document.getElementById("content").classList.toggle("hidden", accounts.length === 0);
    document.getElementById("error").classList.add("hidden");
  } catch (e) { showError("数据加载失败：" + (e.message || String(e))); }
}

// ---- Load users table ----
async function loadUsers() {
  try {
    var d = await B.apiGet("dashboard/overview");
    if (!d || !d.accounts) return;
    var accounts = d.accounts;

    document.getElementById("user-tbody").innerHTML = accounts.map(function (a) {
      var subInfo = (a.subscriptions || []).filter(function (s) { return s.enabled; }).map(function (s) {
        return s.interval_minutes + "分钟 · 阈值" + fmt(s.threshold) + "度";
      }).join("<br>") || '<span style="color:var(--text-muted)">—</span>';

      var balCls = "balance-value";
      if (a.latest_balance != null) {
        var sub = (a.subscriptions || []).find(function (s) { return s.enabled; });
        if (sub && a.latest_balance < sub.threshold) balCls += " balance-low";
      }
      var balHtml = a.latest_balance != null
        ? '<span class="' + balCls + '">' + fmt(a.latest_balance) + '</span> 度'
        : '<span style="color:var(--text-muted)">—</span>';
      if (a.daily_consumption && a.daily_consumption.enough_data) {
        balHtml += '<span class="balance-meta">日耗 ' + fmt(a.daily_consumption.daily) + ' 度 · 预估 ' + fmtInt(a.daily_consumption.days_remaining) + ' 天</span>';
      }

      var label = a.student_id + " (" + a.building + " " + a.room + "号房)";
      var accJson = JSON.stringify({
        id: a.id, student_id: a.student_id,
        xiaoqu_id: a.xiaoqu_id || "", loudong_id: a.loudong_id || "", room_id: a.room_id || ""
      });

      return '<tr>'
        + "<td>" + esc(a.student_id) + "</td>"
        + "<td>" + esc((a.user_id || "").split("@")[0]) + "</td>"
        + "<td>" + esc(a.campus) + "</td>"
        + "<td>" + esc(a.building) + "</td>"
        + "<td>" + esc(a.room) + "</td>"
        + "<td>" + (a.token_valid
          ? '<span class="status status-ok">有效</span>'
          : '<span class="status status-bad">过期</span>') + "</td>"
        + "<td>" + subInfo + "</td>"
        + "<td>" + balHtml + "</td>"
        + '<td>'
        + '<button class="btn btn-sm btn-edit" data-account="' + escAttr(accJson) + '">✏️</button> '
        + '<button class="btn btn-sm btn-danger btn-unbind" data-account-id="' + a.id + '" data-label="' + escAttr(label) + '">🗑️</button>'
        + "</td></tr>";
    }).join("");
  } catch (e) { console.error("loadUsers error:", e); }
}

// ---- Chart ----
async function loadChart() {
  var id = parseInt(document.getElementById("account-selector").value);
  if (!id) return;
  try { var d = await B.apiGet("dashboard/history_grouped", { account_id: id, group: group }); renderChart(d.history, d.group); }
  catch (e) { document.getElementById("chart-empty").classList.remove("hidden"); document.getElementById("chart").style.display = "none"; }
}

document.querySelectorAll(".group-btn").forEach(function (b) {
  b.addEventListener("click", async function () {
    document.querySelectorAll(".group-btn").forEach(function (x) { x.classList.remove("active"); });
    b.classList.add("active"); group = b.dataset.group; await loadChart();
  });
});

function renderChart(h, g) {
  var ce = document.getElementById("chart-empty"), cv = document.getElementById("chart");
  if (!h || h.length < 2) { ce.classList.remove("hidden"); cv.style.display = "none"; if (chart) { chart.destroy(); chart = null; } return; }
  ce.classList.add("hidden"); cv.style.display = "";
  var dark = B.getContext()?.isDark || false;
  var gc = dark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.08)";
  var tc = dark ? "#94a3b8" : "#64748b";
  var lc = dark ? "#60a5fa" : "#3b82f6", fc = dark ? "rgba(96,165,250,0.15)" : "rgba(59,130,246,0.1)";
  var labels, labelText;
  if (g === "raw") { labels = h.map(function (p) { var d = new Date(p.time + "Z"); return (d.getMonth()+1)+"/"+d.getDate()+" "+String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0"); }); labelText = "电量 (度)"; }
  else if (g === "day") { labels = h.map(function (p) { return p.time.slice(5); }); labelText = "日均电量 (度)"; }
  else { labels = h.map(function (p) { return p.time; }); labelText = "月均电量 (度)"; }
  if (chart) chart.destroy();
  chart = new Chart(cv, {
    type: "line", data: { labels: labels, datasets: [{ label: labelText, data: h.map(function(p){return p.balance}), borderColor: lc, backgroundColor: fc, fill: true, tension: 0.4, pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: dark?"#93c5fd":"#2563eb", pointHoverBorderColor: "#fff", pointHoverBorderWidth: 2, borderWidth: 2.2 }] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" }, animation: { duration: 600, easing: "easeOutQuart" },
      plugins: { legend: { labels: { color: tc, usePointStyle: true, pointStyleWidth: 8, padding: 20, font: { size: 11, weight: "500" } } }, tooltip: { backgroundColor: dark?"#1e293b":"#fff", titleColor: tc, bodyColor: dark?"#e2e8f0":"#1e293b", borderColor: dark?"rgba(148,163,184,0.15)":"rgba(100,116,139,0.12)", borderWidth: 1, padding: 12, cornerRadius: 10, displayColors: false, callbacks: { label: function(ctx){return ctx.parsed.y.toFixed(2)+" 度";} } } },
      scales: { x: { ticks: { color: tc, maxTicksLimit: 8, font: { size: 10 }, padding: 10 }, grid: { color: gc, drawBorder: false } }, y: { ticks: { color: tc, font: { size: 10 }, padding: 10, callback: function(v){return v.toFixed(1)+" 度";} }, grid: { color: gc, drawBorder: false }, beginAtZero: false } }
    }
  });
}

function updateChartColors() {
  if (!chart) return;
  var dark = B.getContext()?.isDark || false;
  var gc = dark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.08)", tc = dark ? "#94a3b8" : "#64748b";
  chart.options.scales.x.ticks.color = tc; chart.options.scales.x.grid.color = gc;
  chart.options.scales.y.ticks.color = tc; chart.options.scales.y.grid.color = gc;
  chart.options.plugins.legend.labels.color = tc;
  chart.options.plugins.tooltip.backgroundColor = dark ? "#1e293b" : "#fff";
  chart.options.plugins.tooltip.titleColor = tc; chart.options.plugins.tooltip.bodyColor = dark ? "#e2e8f0" : "#1e293b";
  chart.data.datasets[0].borderColor = dark ? "#60a5fa" : "#3b82f6";
  chart.data.datasets[0].backgroundColor = dark ? "rgba(96,165,250,0.15)" : "rgba(59,130,246,0.1)";
  chart.data.datasets[0].pointHoverBackgroundColor = dark ? "#93c5fd" : "#2563eb";
  chart.update("none");
}

loadOverview();
timer = setInterval(loadOverview, 30000);
window.addEventListener("beforeunload", function () { if (timer) clearInterval(timer); if (chart) chart.destroy(); });
