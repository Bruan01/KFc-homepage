/* KFlow 桌面终端绑定页：配对码提交 + 设备列表 + 吊销。 */
(function () {
  "use strict";

  const codeInput = document.getElementById("code");
  const nameInput = document.getElementById("name");
  const submitBtn = document.getElementById("submit");
  const msg = document.getElementById("msg");
  const devicesBox = document.getElementById("devices");

  function say(text, kind) {
    msg.textContent = text || "";
    msg.className = "msg" + (kind ? " " + kind : "");
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[ch]);
  }

  function ago(iso) {
    if (!iso) return "从未同步";
    const diff = Date.now() - new Date(iso).getTime();
    if (!Number.isFinite(diff) || diff < 0) return "刚刚";
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "刚刚";
    if (mins < 60) return mins + " 分钟前";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + " 小时前";
    return Math.floor(hours / 24) + " 天前";
  }

  async function api(path, options) {
    const response = await fetch(path, Object.assign({ credentials: "same-origin" }, options || {}));
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    return { ok: response.ok, status: response.status, data: data || {} };
  }

  function renderDevices(devices) {
    if (!devices.length) {
      devicesBox.innerHTML = '<span class="empty">还没有绑定任何终端。屏幕通电后会出现配对码。</span>';
      return;
    }
    devicesBox.innerHTML = devices.map((device) => {
      const revoked = device.status === "revoked";
      const meta = [
        device.hardware || "ESP32",
        "同步 " + (device.sync_count || 0) + " 次",
        ago(device.last_seen_at)
      ].filter(Boolean).join(" · ");
      return (
        '<div class="device" data-id="' + escapeHtml(device.device_id) + '">' +
          "<div>" +
            '<div class="name">' + escapeHtml(device.name || device.device_id) + "</div>" +
            '<div class="meta">' + escapeHtml(meta) + "</div>" +
          "</div>" +
          (revoked
            ? '<span class="meta">已吊销</span>'
            : '<button type="button" data-revoke="' + escapeHtml(device.device_id) + '">吊销</button>') +
        "</div>"
      );
    }).join("");
  }

  async function loadDevices() {
    const result = await api("/api/terminal/devices");
    if (result.status === 401 || result.status === 403) {
      devicesBox.innerHTML = '<span class="empty">请先 <a href="/login?next=/terminal">登录</a> 后再绑定终端。</span>';
      submitBtn.disabled = true;
      return;
    }
    if (!result.ok) {
      devicesBox.innerHTML = '<span class="empty">设备列表加载失败，请稍后重试。</span>';
      return;
    }
    renderDevices(result.data.devices || []);
  }

  async function submitPairing() {
    const code = (codeInput.value || "").trim().toUpperCase();
    if (code.length !== 6) {
      say("配对码是 6 位，请对照屏幕输入。", "err");
      return;
    }
    submitBtn.disabled = true;
    say("正在绑定…");
    const result = await api("/api/terminal/pair/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code, name: (nameInput.value || "").trim() })
    });
    submitBtn.disabled = false;

    if (result.ok) {
      say("绑定成功，终端会在几秒内自动取到令牌并刷新屏幕。", "ok");
      codeInput.value = "";
      nameInput.value = "";
      loadDevices();
      return;
    }
    if (result.status === 401 || result.status === 403) {
      say("登录状态已失效，请重新登录后再试。", "err");
      return;
    }
    const messages = {
      404: "没有找到这个配对码，确认屏幕上的 6 位码是否一致。",
      409: "这块终端已经绑定过账号了。",
      410: "配对码已过期，重启终端让它生成新的。",
      429: "请求太频繁，请稍后再试。"
    };
    say(messages[result.status] || result.data.error || "绑定失败，请重试。", "err");
  }

  codeInput.addEventListener("input", () => {
    codeInput.value = (codeInput.value || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
  });

  codeInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitPairing();
  });

  submitBtn.addEventListener("click", submitPairing);

  devicesBox.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-revoke]");
    if (!button) return;
    const deviceId = button.getAttribute("data-revoke");
    if (!window.confirm("吊销后这块终端立即失效，需要重新配对。继续？")) return;
    button.disabled = true;
    const result = await api("/api/terminal/devices/revoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId })
    });
    if (result.ok) {
      say("已吊销，终端下次刷新会显示未绑定。", "ok");
    } else {
      say("吊销失败，请重试。", "err");
    }
    loadDevices();
  });

  loadDevices();
})();
