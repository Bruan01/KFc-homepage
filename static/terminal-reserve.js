/* KFlow 硬件小 K 预约页：领取排队码 + 状态展示 + 取消。 */
(function () {
  "use strict";

  const reserveArea = document.getElementById("reserveArea");
  const statLine = document.getElementById("statLine");
  const msg = document.getElementById("msg");

  function say(text, kind) {
    msg.textContent = text || "";
    msg.className = "msg" + (kind ? " " + kind : "");
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[ch]);
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

  function renderStats(stats) {
    if (!stats) return;
    const left = stats.free_slots_left;
    statLine.textContent =
      "已预约 " + stats.total + " 人 · 前 " + stats.free_quota + " 名免费得硬件" +
      (left > 0 ? " · 剩余 " + left + " 个名额" : " · 名额已满");
  }

  function renderReserved(me) {
    const badge = me.in_free_quota
      ? '<span class="tp-badge tp-badge-gold">前 10 名 · 年终支付邮费免费得硬件</span>'
      : "";
    const granted = me.granted
      ? '<span class="tp-badge tp-badge-gold">硬件已发放，留意站内通知</span>'
      : "";
    const statusText = me.status === "cancelled"
      ? '<span class="tp-cancelled-note">你的排队码已取消，重新预约将沿用原号。</span>'
      : "";
    const actions = me.status === "reserved"
      ? '<div class="tp-actions"><button class="tp-btn tp-btn-ghost" id="cancelBtn" type="button">取消预约</button></div>'
      : "";
    reserveArea.innerHTML =
      '<div class="tp-queue">' +
        '<div class="tp-queue-code">' + escapeHtml(me.code) + "</div>" +
        '<div class="tp-queue-meta">第 <strong>' + Number(me.queue_no) + "</strong> 位 · " +
          (me.status === "cancelled" ? "已取消" : "已预约") + "</div>" +
        badge + granted + statusText + actions +
      "</div>";
    const cancelBtn = document.getElementById("cancelBtn");
    if (cancelBtn) cancelBtn.addEventListener("click", cancelReservation);
  }

  function renderGuest() {
    reserveArea.innerHTML =
      '<div class="tp-queue">' +
        '<p class="tp-hint">预约需要登录，排队码与账号绑定。</p>' +
        '<div class="tp-actions"><a class="tp-btn" href="/login?next=/terminal/reserve">登录后预约</a></div>' +
      "</div>";
  }

  function renderAnonymousReady(stats) {
    reserveArea.innerHTML =
      '<div class="tp-queue">' +
        '<p class="tp-hint">登录后即可领取排队码，先到先得。</p>' +
        '<div class="tp-actions"><a class="tp-btn" href="/login?next=/terminal/reserve">登录领取排队码</a></div>' +
      "</div>";
    renderStats(stats);
  }

  function renderNewcomer(stats) {
    reserveArea.innerHTML =
      '<div class="tp-queue">' +
        '<p class="tp-hint">还没有排队码。领取后号码全局递增，前 ' +
        Number(stats.free_quota) + " 名年终免费得硬件（支付邮费）。</p>" +
        '<div class="tp-actions"><button class="tp-btn" id="reserveBtn" type="button">立即预约，领取排队码</button></div>' +
      "</div>";
    const btn = document.getElementById("reserveBtn");
    if (btn) btn.addEventListener("click", createReservation);
    renderStats(stats);
  }

  async function loadStatus() {
    const result = await api("/api/terminal/reserve/status");
    if (!result.ok) {
      reserveArea.innerHTML = '<span class="empty">预约状态加载失败，请稍后重试。</span>';
      return;
    }
    const data = result.data;
    renderStats(data);
    if (!("me" in data)) {
      renderAnonymousReady(data);
      return;
    }
    if (data.me) {
      renderReserved(data.me);
    } else {
      renderNewcomer(data);
    }
  }

  async function createReservation() {
    const btn = document.getElementById("reserveBtn");
    if (btn) btn.disabled = true;
    say("正在领取排队码…");
    const result = await api("/api/terminal/reserve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    if (btn) btn.disabled = false;
    if (result.ok) {
      say("预约成功！排队码已通过站内通知同步。", "ok");
      loadStatus();
      return;
    }
    if (result.status === 401 || result.status === 403) {
      say("登录状态已失效，请重新登录后再试。", "err");
      return;
    }
    say(result.data.error || "预约失败，请重试。", "err");
  }

  async function cancelReservation() {
    if (!window.confirm("取消后重新预约会沿用原排队码，确定取消？")) return;
    const btn = document.getElementById("cancelBtn");
    if (btn) btn.disabled = true;
    const result = await api("/api/terminal/reserve/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    if (result.ok) {
      say("已取消预约。重新预约将沿用原排队码。", "ok");
    } else {
      if (btn) btn.disabled = false;
      say(result.data.error || "取消失败，请重试。", "err");
    }
    loadStatus();
  }

  loadStatus();
})();
