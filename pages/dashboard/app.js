// NUIST Power Dashboard
var B = window.AstrBotPluginPage;
var chart = null, group = "raw", timer = null;

await B.ready();
(function t() {
  document.documentElement.setAttribute("data-theme", B.getContext()?.isDark ? "dark" : "light");
})();
B.onContext(function () {
  document.documentElement.setAttribute("data-theme", B.getContext()?.isDark ? "dark" : "light");
  if (chart) updateChartColors();
});
document.getElementById("loading").classList.add("hidden");

// sidebar
document.querySelectorAll(".nav-item").forEach(function (i) {
  i.addEventListener("click", function () {
    document.querySelectorAll(".nav-item").forEach(function (j) { j.classList.remove("active"); });
    i.classList.add("active");
    document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.add("hidden"); });
    document.getElementById("tab-" + i.dataset.tab).classList.remove("hidden");
  });
});

// load data
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
      { l: "绑定账号", v: accounts.length },
      { l: "活跃订阅", v: subs },
      { l: "低电量告警", v: alerts, alert: alerts > 0 },
      { l: "Token有效", v: accounts.filter(function (a) { return a.token_valid; }).length }
    ].map(function (c) { return '<div class="card' + (c.alert ? " card-alert" : "") + '"><div class="card-value">' + c.v + '</div><div class="card-label">' + c.l + '</div></div>'; }).join("");
    document.getElementById("user-tbody").innerHTML = accounts.map(function (a) {
      var s = (a.subscriptions || []).filter(function (s) { return s.enabled; }).map(function (s) { return s.interval_minutes + "分钟/" + s.threshold + "度"; }).join(",") || "-";
      var b = a.latest_balance != null ? a.latest_balance.toFixed(2) + " 度" : "-";
      return "<tr><td>" + a.student_id + "</td><td>" + a.user_id.split("@")[0] + "</td><td>" + a.campus + "</td><td>" + a.building + "</td><td>" + a.room + "</td><td>" + (a.token_valid ? "有效" : "过期") + "</td><td>" + s + "</td><td>" + b + "</td></tr>";
    }).join("");
    var sel = document.getElementById("account-selector");
    if (!sel.dataset.init) {
      sel.innerHTML = accounts.map(function (a) { return '<option value="' + a.id + '">' + a.building + " " + a.room + "号房 (" + a.student_id + ")</option>"; }).join("");
      sel.onchange = loadChart;
      sel.dataset.init = "1";
      loadChart();
    }
    document.getElementById("empty").classList.toggle("hidden", accounts.length > 0);
    document.getElementById("content").classList.toggle("hidden", accounts.length === 0);
    document.getElementById("error").classList.add("hidden");
  } catch (e) {
    var er = document.getElementById("error");
    er.textContent = "错误: " + (e.message || e);
    er.classList.remove("hidden");
  }
}

async function loadChart() {
  var id = parseInt(document.getElementById("account-selector").value);
  if (!id) return;
  try {
    var d = await B.apiGet("dashboard/history_grouped", { account_id: id, group: group });
    renderChart(d.history);
  } catch (e) {
    document.getElementById("chart-empty").classList.remove("hidden");
    document.getElementById("chart").style.display = "none";
  }
}

document.querySelectorAll(".group-btn").forEach(function (b) {
  b.addEventListener("click", async function () {
    document.querySelectorAll(".group-btn").forEach(function (x) { x.classList.remove("active"); });
    b.classList.add("active");
    group = b.dataset.group;
    await loadChart();
  });
});

function renderChart(h) {
  var ce = document.getElementById("chart-empty"), cv = document.getElementById("chart");
  if (!h || h.length < 2) { ce.classList.remove("hidden"); cv.style.display = "none"; if (chart) { chart.destroy(); chart = null; } return; }
  ce.classList.add("hidden"); cv.style.display = "";
  var dark = B.getContext()?.isDark || false;
  var gc = dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)", tc = dark ? "#aaa" : "#666";
  var labels = h.map(function (p) { var d = new Date(p.time + "Z"); return (d.getMonth() + 1) + "/" + d.getDate(); });
  var vals = h.map(function (p) { return p.balance; });
  if (chart) chart.destroy();
  chart = new Chart(cv, {
    type: "line", data: { labels: labels, datasets: [{ label: "电量(度)", data: vals, borderColor: "#4f9cf5", backgroundColor: dark ? "rgba(79,156,245,0.15)" : "rgba(79,156,245,0.08)", fill: true, tension: 0.3, pointRadius: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: tc } } }, scales: { x: { ticks: { color: tc }, grid: { color: gc } }, y: { ticks: { color: tc }, grid: { color: gc } } } }
  });
}

function updateChartColors() {
  if (!chart) return;
  var dark = B.getContext()?.isDark || false;
  var gc = dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)", tc = dark ? "#aaa" : "#666";
  chart.options.scales.x.ticks.color = tc; chart.options.scales.x.grid.color = gc;
  chart.options.scales.y.ticks.color = tc; chart.options.scales.y.grid.color = gc;
  chart.options.plugins.legend.labels.color = tc;
  chart.data.datasets[0].backgroundColor = dark ? "rgba(79,156,245,0.15)" : "rgba(79,156,245,0.08)";
  chart.update();
}

loadOverview();
timer = setInterval(loadOverview, 30000);
window.addEventListener("beforeunload", function () { if (timer) clearInterval(timer); if (chart) chart.destroy(); });
