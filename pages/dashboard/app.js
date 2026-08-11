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
      { l: "绑定账号", v: accounts.length, icon: "👤" },
      { l: "活跃订阅", v: subs, icon: "📬" },
      { l: "低电量告警", v: alerts, alert: alerts > 0, icon: alerts > 0 ? "🚨" : "✅" },
      { l: "Token 有效", v: accounts.filter(function (a) { return a.token_valid; }).length, icon: "🔑" }
    ].map(function (c) {
      return '<div class="card' + (c.alert ? " card-alert" : "") + '"><div class="card-icon">' + c.icon + '</div><div class="card-value">' + c.v + '</div><div class="card-label">' + c.l + '</div></div>';
    }).join("");
    document.getElementById("user-tbody").innerHTML = accounts.map(function (a) {
      var subInfo = (a.subscriptions || []).filter(function (s) { return s.enabled; }).map(function (s) {
        return s.interval_minutes + "分钟 · 阈值 " + s.threshold + "/" + s.critical_threshold + " 度";
      }).join("<br>") || '<span style="color:var(--text-secondary)">—</span>';
      var bal = a.latest_balance != null
        ? '<span style="font-weight:600;font-size:0.9rem">' + a.latest_balance.toFixed(1) + '</span> 度'
        : '<span style="color:var(--text-secondary)">—</span>';
      if (a.daily_consumption && a.daily_consumption.enough_data) {
        bal += '<br><small style="color:var(--text-secondary)">日耗 ' + a.daily_consumption.daily + ' 度 · 预估 ' + a.daily_consumption.days_remaining + ' 天</small>';
      }
      return "<tr>"
        + "<td>" + a.student_id + "</td>"
        + "<td>" + a.user_id.split("@")[0] + "</td>"
        + "<td>" + a.campus + "</td>"
        + "<td>" + a.building + "</td>"
        + "<td>" + a.room + "</td>"
        + "<td>" + (a.token_valid
          ? '<span class="status status-ok">有效</span>'
          : '<span class="status status-bad">过期</span>') + "</td>"
        + "<td>" + subInfo + "</td>"
        + "<td>" + bal + "</td>"
        + "</tr>";
    }).join("");
    var sel = document.getElementById("account-selector");
    if (!sel.dataset.init) {
      sel.innerHTML = accounts.map(function (a) { return '<option value="' + a.id + '">' + a.building + " " + a.room + "号房 · " + a.student_id + "</option>"; }).join("");
      sel.onchange = loadChart;
      sel.dataset.init = "1";
      loadChart();
    }
    document.getElementById("empty").classList.toggle("hidden", accounts.length > 0);
    document.getElementById("content").classList.toggle("hidden", accounts.length === 0);
    document.getElementById("error").classList.add("hidden");
  } catch (e) {
    var er = document.getElementById("error");
    er.textContent = "❌ " + (e.message || e);
    er.classList.remove("hidden");
  }
}

async function loadChart() {
  var id = parseInt(document.getElementById("account-selector").value);
  if (!id) return;
  try {
    var d = await B.apiGet("dashboard/history_grouped", { account_id: id, group: group });
    renderChart(d.history, d.group);
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

function renderChart(h, g) {
  var ce = document.getElementById("chart-empty"), cv = document.getElementById("chart");
  if (!h || h.length < 2) { ce.classList.remove("hidden"); cv.style.display = "none"; if (chart) { chart.destroy(); chart = null; } return; }
  ce.classList.add("hidden"); cv.style.display = "";
  var dark = B.getContext()?.isDark || false;
  var gc = dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
  var tc = dark ? "#94a3b8" : "#6b7280";
  var lineColor = dark ? "#60a5fa" : "#3b82f6";
  var fillColor = dark ? "rgba(96,165,250,0.12)" : "rgba(59,130,246,0.08)";

  var labels, labelText;
  if (g === "raw") {
    labels = h.map(function (p) { var d = new Date(p.time + "Z"); return (d.getMonth() + 1) + "/" + d.getDate() + " " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); });
    labelText = "电量 (度)";
  } else if (g === "day") {
    labels = h.map(function (p) { return p.time.slice(5); });
    labelText = "日均电量 (度)";
  } else {
    labels = h.map(function (p) { return p.time; });
    labelText = "月均电量 (度)";
  }
  var vals = h.map(function (p) { return p.balance; });

  if (chart) chart.destroy();
  chart = new Chart(cv, {
    type: "line",
    data: {
      labels: labels,
      datasets: [{
        label: labelText,
        data: vals,
        borderColor: lineColor,
        backgroundColor: fillColor,
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: lineColor,
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { labels: { color: tc, usePointStyle: true, padding: 16, font: { size: 11 } } },
        tooltip: {
          backgroundColor: dark ? "#1e293b" : "#fff",
          titleColor: tc,
          bodyColor: tc,
          borderColor: gc,
          borderWidth: 1,
          padding: 10,
          cornerRadius: 8,
        }
      },
      scales: {
        x: {
          ticks: { color: tc, maxTicksLimit: 10, font: { size: 10 }, padding: 8 },
          grid: { color: gc, drawBorder: false },
        },
        y: {
          ticks: { color: tc, font: { size: 10 }, padding: 8, callback: function (v) { return v + " 度"; } },
          grid: { color: gc, drawBorder: false },
          beginAtZero: false,
        }
      }
    }
  });
}

function updateChartColors() {
  if (!chart) return;
  var dark = B.getContext()?.isDark || false;
  var gc = dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
  var tc = dark ? "#94a3b8" : "#6b7280";
  chart.options.scales.x.ticks.color = tc; chart.options.scales.x.grid.color = gc;
  chart.options.scales.y.ticks.color = tc; chart.options.scales.y.grid.color = gc;
  chart.options.plugins.legend.labels.color = tc;
  chart.data.datasets[0].borderColor = dark ? "#60a5fa" : "#3b82f6";
  chart.data.datasets[0].backgroundColor = dark ? "rgba(96,165,250,0.12)" : "rgba(59,130,246,0.08)";
  chart.update();
}

loadOverview();
timer = setInterval(loadOverview, 30000);
window.addEventListener("beforeunload", function () { if (timer) clearInterval(timer); if (chart) chart.destroy(); });
