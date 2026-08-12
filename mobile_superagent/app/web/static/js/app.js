const API = {
  async get(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async post(url, body = {}) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async patch(url, body = {}) {
    const res = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  async del(url) {
    const res = await fetch(url, { method: "DELETE" });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};

function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden", "error");
  if (isError) el.classList.add("error");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
}

function statusClass(status) {
  switch (status) {
    case "done":
      return "ok";
    case "failed":
    case "cancelled":
      return "danger";
    case "need_user":
      return "warn";
    case "running":
    case "queued":
      return "run";
    default:
      return "";
  }
}

function setPill(el, status) {
  if (!el) return;
  el.textContent = status || "-";
  el.className = `pill ${statusClass(status)}`;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadDevicesIntoSelect(selectEl) {
  const devices = await API.get("/api/devices");
  selectEl.innerHTML = "";
  if (!devices.length) {
    selectEl.innerHTML = `<option value="">暂无在线设备</option>`;
    return devices;
  }
  for (const d of devices) {
    const opt = document.createElement("option");
    opt.value = d.id;
    opt.textContent = `${d.name || d.serial} (${d.status})`;
    selectEl.appendChild(opt);
  }
  return devices;
}

/* ---------------- Home ---------------- */
const HomePage = {
  async init() {
    this.deviceSelect = document.getElementById("device-id");
    this.goalInput = document.getElementById("goal");
    this.skillSelect = document.getElementById("skill-hint");
    this.taskList = document.getElementById("task-list");
    this.deviceSummary = document.getElementById("device-summary");

    document.getElementById("task-form").addEventListener("submit", (e) => {
      e.preventDefault();
      this.createTask();
    });
    document.getElementById("btn-refresh-devices").addEventListener("click", () => this.refreshDevices());
    document.getElementById("btn-reload-tasks").addEventListener("click", () => this.loadTasks());

    document.querySelectorAll("#examples .chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        this.goalInput.value = btn.dataset.goal || "";
      });
    });

    await this.refreshDevices();
    await this.loadTasks();
    this.timer = setInterval(() => this.loadTasks(), 5000);
  },

  async refreshDevices() {
    try {
      await API.post("/api/devices/refresh", {});
      const devices = await loadDevicesIntoSelect(this.deviceSelect);
      this.renderDeviceSummary(devices);
      toast("设备已刷新");
    } catch (e) {
      toast(e.message || "刷新设备失败", true);
    }
  },

  renderDeviceSummary(devices) {
    if (!devices.length) {
      this.deviceSummary.innerHTML = `<div class="muted">没有发现 adb 设备。请先连接手机并开启调试。</div>`;
      return;
    }
    this.deviceSummary.innerHTML = devices
      .map(
        (d) => `
      <div class="list-item" style="cursor:default;">
        <div class="row-between">
          <div class="list-title">${escapeHtml(d.name || d.serial)}</div>
          <span class="pill ${d.status === "online" ? "ok" : "danger"}">${escapeHtml(d.status)}</span>
        </div>
        <div class="list-sub">serial: ${escapeHtml(d.serial)}</div>
      </div>`
      )
      .join("");
  },

  async loadTasks() {
    try {
      const tasks = await API.get("/api/tasks?limit=20");
      if (!tasks.length) {
        this.taskList.innerHTML = `<div class="muted">暂无任务</div>`;
        return;
      }
      this.taskList.innerHTML = tasks
        .map(
          (t) => `
        <a class="list-item" href="/tasks/${encodeURIComponent(t.id)}">
          <div class="row-between">
            <div class="list-title">${escapeHtml((t.user_goal || "").slice(0, 42))}</div>
            <span class="pill ${statusClass(t.status)}">${escapeHtml(t.status)}</span>
          </div>
          <div class="list-sub">#${escapeHtml(t.id)} · step ${t.current_step ?? 0}</div>
        </a>`
        )
        .join("");
    } catch (e) {
      this.taskList.innerHTML = `<div class="muted">加载失败：${escapeHtml(e.message)}</div>`;
    }
  },

  async createTask() {
    const goal = this.goalInput.value.trim();
    const deviceId = this.deviceSelect.value;
    const skill = this.skillSelect.value || null;
    if (!goal || !deviceId) {
      toast("请填写任务并选择设备", true);
      return;
    }
    const btn = document.getElementById("btn-run");
    btn.disabled = true;
    try {
      const task = await API.post("/api/tasks", {
        goal,
        device_id: deviceId,
        skill_hint: skill,
      });
      toast("任务已创建");
      window.location.href = `/tasks/${encodeURIComponent(task.id)}`;
    } catch (e) {
      toast(e.message || "创建失败", true);
    } finally {
      btn.disabled = false;
    }
  },
};

/* ---------------- Task Detail ---------------- */
const TaskPage = {
  init(taskId) {
    this.taskId = taskId;
    this.shot = document.getElementById("screenshot");
    this.shotEmpty = document.getElementById("screenshot-empty");
    this.needBox = document.getElementById("need-user-box");

    document.getElementById("btn-continue").addEventListener("click", () => this.continueTask());
    document.getElementById("btn-cancel").addEventListener("click", () => this.cancelTask());
    document.getElementById("btn-reload-steps").addEventListener("click", () => this.refresh());

    this.refresh();
    this.timer = setInterval(() => this.refresh(), 2000);
  },

  async refresh() {
    try {
      const [task, steps] = await Promise.all([
        API.get(`/api/tasks/${encodeURIComponent(this.taskId)}`),
        API.get(`/api/tasks/${encodeURIComponent(this.taskId)}/steps`),
      ]);
      this.renderTask(task);
      this.renderSteps(steps || []);
      this.renderShot(steps || []);

      if (["done", "failed", "cancelled"].includes(task.status)) {
        clearInterval(this.timer);
      }
    } catch (e) {
      toast(e.message || "刷新失败", true);
    }
  },

  renderTask(task) {
    setPill(document.getElementById("task-status"), task.status);
    document.getElementById("task-goal").textContent = task.user_goal || "-";
    document.getElementById("task-step").textContent = task.current_step ?? 0;
    document.getElementById("task-result").textContent =
      task.result_message || task.need_user_reason || "-";

    if (task.status === "need_user") {
      this.needBox.classList.remove("hidden");
      document.getElementById("need-user-reason").textContent = task.need_user_reason || "需要人工处理";
      document.getElementById("need-user-instruction").textContent =
        task.need_user_instruction || "请在手机上完成后点击继续";
    } else {
      this.needBox.classList.add("hidden");
    }

    const gs = document.getElementById("global-status");
    setPill(gs, task.status);
  },

  renderSteps(steps) {
    const box = document.getElementById("step-list");
    if (!steps.length) {
      box.innerHTML = `<div class="muted">暂无步骤</div>`;
      return;
    }
    const sorted = [...steps].sort((a, b) => (b.step_no ?? 0) - (a.step_no ?? 0));
    box.innerHTML = sorted
      .map((s) => {
        const action = typeof s.action_json === "string" ? s.action_json : JSON.stringify(s.action || s.action_json || {}, null, 2);
        return `
        <div class="step">
          <div class="step-head">
            <div class="step-no">#${escapeHtml(s.step_no)}</div>
            <div class="meta">${escapeHtml(s.skill || "")} · ${escapeHtml(s.foreground_package || "")}</div>
          </div>
          <div class="meta">observe: ${escapeHtml(s.observe || "")}</div>
          <div class="meta">plan: ${escapeHtml(s.plan || "")}</div>
          <pre>${escapeHtml(action)}</pre>
        </div>`;
      })
      .join("");
  },

  renderShot(steps) {
    if (!steps.length) {
      this.shot.classList.add("hidden");
      this.shotEmpty.classList.remove("hidden");
      document.getElementById("shot-meta").textContent = "暂无";
      return;
    }
    // 取最后一个确实有截图路径的步骤（respond_to_user 等终态步骤不截图）
    const withShot = [...steps]
      .filter((s) => s.screenshot_path || s.screenshot_url)
      .sort((a, b) => (a.step_no ?? 0) - (b.step_no ?? 0));
    const last = withShot.length ? withShot.at(-1) : null;

    const url =
      last?.screenshot_url ||
      (last?.screenshot_path
        ? `/api/tasks/${encodeURIComponent(this.taskId)}/screenshots/${last.step_no}`
        : null);

    if (!url) {
      this.shot.classList.add("hidden");
      this.shotEmpty.classList.remove("hidden");
      return;
    }
    this.shotEmpty.classList.add("hidden");
    this.shot.classList.remove("hidden");
    // 防缓存
    this.shot.src = `${url}?t=${Date.now()}`;
    document.getElementById("shot-meta").textContent = `step ${last.step_no}`;
  },

  async continueTask() {
    const message = document.getElementById("continue-message").value || "";
    try {
      await API.post(`/api/tasks/${encodeURIComponent(this.taskId)}/continue`, { message });
      toast("已继续执行");
      this.timer = setInterval(() => this.refresh(), 2000);
      this.refresh();
    } catch (e) {
      toast(e.message || "继续失败", true);
    }
  },

  async cancelTask() {
    if (!confirm("确认取消该任务？")) return;
    try {
      await API.post(`/api/tasks/${encodeURIComponent(this.taskId)}/cancel`, {});
      toast("任务已取消");
      this.refresh();
    } catch (e) {
      toast(e.message || "取消失败", true);
    }
  },
};

/* ---------------- Routines ---------------- */
const RoutinesPage = {
  async init() {
    this.listEl = document.getElementById("routine-list");
    this.deviceSelect = document.getElementById("r-device-id");

    await loadDevicesIntoSelect(this.deviceSelect);
    await this.load();

    document.getElementById("routine-form").addEventListener("submit", (e) => {
      e.preventDefault();
      this.create();
    });
    document.getElementById("btn-reload-routines").addEventListener("click", () => this.load());
  },

  buildRRule() {
    const freq = document.getElementById("r-freq").value;
    const hour = Number(document.getElementById("r-hour").value);
    const minute = Number(document.getElementById("r-minute").value);
    if (freq === "WEEKLY") {
      return `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=${hour};BYMINUTE=${minute}`;
    }
    return `RRULE:FREQ=DAILY;BYHOUR=${hour};BYMINUTE=${minute}`;
  },

  async load() {
    try {
      const items = await API.get("/api/routines");
      if (!items.length) {
        this.listEl.innerHTML = `<div class="muted">暂无定时任务</div>`;
        return;
      }
      this.listEl.innerHTML = items
        .map((r) => {
          const enabled = !!r.enabled;
          return `
          <div class="list-item" style="cursor:default;">
            <div class="row-between">
              <div class="list-title">${escapeHtml(r.title)}</div>
              <span class="pill ${enabled ? "ok" : ""}">${enabled ? "启用" : "停用"}</span>
            </div>
            <div class="list-sub">${escapeHtml(r.prompt || "")}</div>
            <div class="list-sub" style="margin-top:6px;">
              ${escapeHtml(r.rrule || "")}<br/>
              时区: ${escapeHtml(r.timezone || "")} · 下次: ${escapeHtml(r.next_run_at || "-")}
            </div>
            <div class="row" style="margin-top:10px;">
              <button class="btn small ghost" onclick="RoutinesPage.toggle('${r.id}', ${enabled ? "false" : "true"})">
                ${enabled ? "停用" : "启用"}
              </button>
              <button class="btn small danger ghost" onclick="RoutinesPage.remove('${r.id}')">删除</button>
            </div>
          </div>`;
        })
        .join("");
    } catch (e) {
      this.listEl.innerHTML = `<div class="muted">加载失败：${escapeHtml(e.message)}</div>`;
    }
  },

  async create() {
    const body = {
      title: document.getElementById("r-title").value.trim(),
      device_id: document.getElementById("r-device-id").value,
      prompt: document.getElementById("r-prompt").value.trim(),
      rrule: this.buildRRule(),
      timezone: document.getElementById("r-timezone").value.trim() || "Asia/Shanghai",
    };
    try {
      await API.post("/api/routines", body);
      toast("定时任务已创建");
      document.getElementById("routine-form").reset();
      document.getElementById("r-timezone").value = "Asia/Shanghai";
      await loadDevicesIntoSelect(this.deviceSelect);
      await this.load();
    } catch (e) {
      toast(e.message || "创建失败", true);
    }
  },

  async toggle(id, enabled) {
    try {
      const url = enabled ? `/api/routines/${id}/enable` : `/api/routines/${id}/disable`;
      await API.post(url, {});
      toast(enabled ? "已启用" : "已停用");
      this.load();
    } catch (e) {
      toast(e.message || "操作失败", true);
    }
  },

  async remove(id) {
    if (!confirm("确认删除该定时任务？")) return;
    try {
      await API.del(`/api/routines/${id}`);
      toast("已删除");
      this.load();
    } catch (e) {
      toast(e.message || "删除失败", true);
    }
  },
};

/* ---------------- Devices ---------------- */
const DevicesPage = {
  async init() {
    this.table = document.getElementById("devices-table");
    this.previewSelect = document.getElementById("preview-device-id");
    this.previewShot = document.getElementById("preview-shot");
    this.previewEmpty = document.getElementById("preview-empty");
    this.previewMeta = document.getElementById("preview-meta");

    document.getElementById("btn-scan").addEventListener("click", () => this.scan());
    document.getElementById("btn-reload-devices-page").addEventListener("click", () => this.load());
    document.getElementById("btn-preview").addEventListener("click", () => this.preview());

    await this.load();
  },

  async scan() {
    try {
      await API.post("/api/devices/refresh", {});
      toast("扫描完成");
      await this.load();
    } catch (e) {
      toast(e.message || "扫描失败", true);
    }
  },

  async load() {
    try {
      const devices = await API.get("/api/devices");
      await loadDevicesIntoSelect(this.previewSelect);
      if (!devices.length) {
        this.table.innerHTML = `<div class="muted">未发现设备</div>`;
        return;
      }
      this.table.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>Serial</th>
              <th>状态</th>
              <th>类型</th>
              <th>最后在线</th>
            </tr>
          </thead>
          <tbody>
            ${devices
              .map(
                (d) => `
              <tr>
                <td>${escapeHtml(d.name || "-")}</td>
                <td><code>${escapeHtml(d.serial)}</code></td>
                <td><span class="pill ${d.status === "online" ? "ok" : "danger"}">${escapeHtml(d.status)}</span></td>
                <td>${escapeHtml(d.connect_type || "-")}</td>
                <td>${escapeHtml(d.last_seen_at || "-")}</td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>`;
    } catch (e) {
      this.table.innerHTML = `<div class="muted">加载失败：${escapeHtml(e.message)}</div>`;
    }
  },

  async preview() {
    const id = this.previewSelect.value;
    if (!id) {
      toast("请选择设备", true);
      return;
    }
    try {
      const state = await API.get(`/api/devices/${encodeURIComponent(id)}/state`);
      if (state.screenshot_url) {
        this.previewShot.src = `${state.screenshot_url}?t=${Date.now()}`;
        this.previewShot.classList.remove("hidden");
        this.previewEmpty.classList.add("hidden");
      }
      this.previewMeta.textContent = JSON.stringify(
        {
          package: state.foreground_package,
          activity: state.foreground_activity,
          serial: state.serial,
        },
        null,
        2
      );
    } catch (e) {
      toast(e.message || "获取截图失败", true);
    }
  },
};

// 导出到全局，供 HTML onclick 使用
window.HomePage = HomePage;
window.TaskPage = TaskPage;
window.RoutinesPage = RoutinesPage;
window.DevicesPage = DevicesPage;
