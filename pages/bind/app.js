// NUIST Power Bind Page
const bridge = window.AstrBotPluginPage;
let tempToken = null;

await bridge.ready();

// Apply theme
function applyTheme() {
  const c = bridge.getContext();
  document.documentElement.setAttribute("data-theme", c?.isDark ? "dark" : "light");
}
applyTheme();
bridge.onContext(applyTheme);

// Elements
const $ = (id) => document.getElementById(id);
const el = {
  error: $("error"), success: $("success"),
  stepLogin: $("step-login"), stepSelect: $("step-select"),
  studentId: $("student-id"), password: $("password"),
  btnLogin: $("btn-login"), loginSpinner: $("login-spinner"),
  selCampus: $("sel-campus"), selBuilding: $("sel-building"), selRoom: $("sel-room"),
  btnBind: $("btn-bind"), btnReset: $("btn-reset"), bindSpinner: $("bind-spinner"),
};

function showError(msg) { el.error.textContent = "❌ " + msg; el.error.classList.remove("hidden"); el.success.classList.add("hidden"); }
function showSuccess(msg) { el.success.textContent = "✅ " + msg; el.success.classList.remove("hidden"); el.error.classList.add("hidden"); }
function hideMessages() { el.error.classList.add("hidden"); el.success.classList.add("hidden"); }

// ---- Step 1: Login ----
el.btnLogin.addEventListener("click", async () => {
  const sid = el.studentId.value.trim();
  const pwd = el.password.value;
  if (!sid || !pwd) { showError("请填写学号和密码"); return; }
  hideMessages();
  el.btnLogin.disabled = true;
  el.loginSpinner.classList.remove("hidden");
  try {
    const resp = await bridge.apiGet("bind/init", { student_id: sid, password: pwd });
    if (resp.error) { showError(resp.error); return; }
    tempToken = resp.token;
    populateSelect(el.selCampus, resp.campuses, "name", "name");
    el.selCampus.disabled = false;
    el.stepLogin.classList.add("hidden");
    el.stepSelect.classList.remove("hidden");
    el.btnBind.disabled = true;
  } catch (e) {
    showError("登录失败: " + (e.message || JSON.stringify(e)));
  } finally {
    el.btnLogin.disabled = false;
    el.loginSpinner.classList.add("hidden");
  }
});

// ---- Cascading ----
el.selCampus.addEventListener("change", async () => {
  const campus = el.selCampus.value;
  el.selBuilding.innerHTML = '<option value="">加载中...</option>';
  el.selBuilding.disabled = true;
  el.selRoom.innerHTML = '<option value="">-- 请先选楼栋 --</option>';
  el.selRoom.disabled = true;
  el.btnBind.disabled = true;
  if (!campus) { el.selBuilding.innerHTML = '<option value="">-- 请先选校区 --</option>'; return; }
  try {
    const resp = await bridge.apiGet("bind/buildings", { token: tempToken, campus });
    if (resp.error) { showError(resp.error); return; }
    populateSelect(el.selBuilding, resp.buildings, "name", "name");
    el.selBuilding.disabled = false;
  } catch (e) { showError("加载楼栋失败: " + (e.message || JSON.stringify(e))); }
});

el.selBuilding.addEventListener("change", async () => {
  const campus = el.selCampus.value;
  const building = el.selBuilding.value;
  el.selRoom.innerHTML = '<option value="">加载中...</option>';
  el.selRoom.disabled = true;
  el.btnBind.disabled = true;
  if (!building) { el.selRoom.innerHTML = '<option value="">-- 请先选楼栋 --</option>'; return; }
  try {
    const resp = await bridge.apiGet("bind/rooms", { token: tempToken, campus, building });
    if (resp.error) { showError(resp.error); return; }
    populateSelect(el.selRoom, resp.rooms, "name", "name");
    el.selRoom.disabled = false;
    el.btnBind.disabled = false;
  } catch (e) { showError("加载房间失败: " + (e.message || JSON.stringify(e))); }
});

// ---- Step 3: Bind ----
el.btnBind.addEventListener("click", async () => {
  const sid = el.studentId.value.trim();
  const pwd = el.password.value;
  const campus = el.selCampus.value;
  const building = el.selBuilding.value;
  const room = el.selRoom.value;
  if (!campus || !building || !room) { showError("请完整选择校区、楼栋和房间号"); return; }
  hideMessages();
  el.btnBind.disabled = true;
  el.bindSpinner.classList.remove("hidden");
  try {
    const resp = await bridge.apiPost("bind/execute", {
      student_id: sid, password: pwd,
      campus, building, room,
    });
    if (resp.error) { showError(resp.error); return; }
    showSuccess("绑定成功！" + resp.message);
    el.btnBind.disabled = true;
  } catch (e) {
    showError("绑定失败: " + (e.message || JSON.stringify(e)));
  } finally {
    el.bindSpinner.classList.add("hidden");
  }
});

// ---- Reset ----
el.btnReset.addEventListener("click", () => {
  tempToken = null;
  el.stepLogin.classList.remove("hidden");
  el.stepSelect.classList.add("hidden");
  el.selCampus.disabled = true;
  el.selBuilding.disabled = true;
  el.selRoom.disabled = true;
  el.btnBind.disabled = true;
  hideMessages();
});

// ---- Helpers ----
function populateSelect(sel, items, valueKey, textKey) {
  sel.innerHTML = '<option value="">-- 请选择 --</option>';
  items.forEach(item => {
    const opt = document.createElement("option");
    opt.value = item[valueKey];
    opt.textContent = item[textKey];
    sel.appendChild(opt);
  });
}