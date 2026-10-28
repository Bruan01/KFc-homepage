/* KFlow 展示热度：碎碎念 / 论坛共用的单帖设置弹窗。
 * 只读写「展示值」，不碰真实点赞、浏览与热度排序。 */
(function () {
  "use strict";

  const API = {
    murmur: (id) => `/api/admin/murmurs/${id}/heat`,
    forum: (id) => `/api/admin/forum/topics/${id}/heat`,
  };
  const LABEL = { murmur: "碎碎念", forum: "论坛帖子" };

  let dialog = null;
  let current = null;
  let previewTimer = 0;
  let confirmDialog = null;

  function ensureStyle() {
    if (document.getElementById("kf-heat-style")) return;
    const style = document.createElement("style");
    style.id = "kf-heat-style";
    style.textContent = `
      #kf-heat-dialog, #kf-heat-confirm {
        --kf-bg: #ffffff;
        --kf-ink: #18181b;
        --kf-muted: #71717a;
        --kf-line: #e4e4e7;
        --kf-soft: #f4f4f5;
        --kf-soft-2: #fafafa;
        --kf-accent: #2563eb;
        --kf-accent-2: #7c3aed;
        --kf-danger: #dc2626;
        --kf-ok: #15803d;
        --kf-shadow: 0 32px 80px rgba(15, 23, 42, .28), 0 8px 24px rgba(15, 23, 42, .12);
      }
      :root[data-theme="dark"] #kf-heat-dialog, :root[data-theme="dark"] #kf-heat-confirm {
        --kf-bg: #1c1c1f;
        --kf-ink: #f4f4f5;
        --kf-muted: #a1a1aa;
        --kf-line: #34343a;
        --kf-soft: #26262b;
        --kf-soft-2: #202024;
        --kf-accent: #7aa2ff;
        --kf-accent-2: #b18cff;
        --kf-danger: #f87171;
        --kf-ok: #4ade80;
        --kf-shadow: 0 32px 80px rgba(0, 0, 0, .6), 0 8px 24px rgba(0, 0, 0, .4);
      }
      :root[data-theme="vibrancy"] #kf-heat-dialog, :root[data-theme="vibrancy"] #kf-heat-confirm {
        --kf-bg: rgba(252, 252, 254, .78);
        --kf-shadow: 0 32px 80px rgba(15, 23, 42, .24);
      }
      #kf-heat-dialog[open], #kf-heat-confirm[open] { animation: kf-heat-pop .18s ease-out; }
      @keyframes kf-heat-pop { from { opacity: 0; transform: translateY(8px) scale(.98); } to { opacity: 1; transform: none; } }
      #kf-heat-dialog {
        border: 0; padding: 0; width: min(600px, calc(100vw - 32px)); max-height: min(86vh, 820px); overflow: auto;
        border-radius: 20px; background: var(--kf-bg); color: var(--kf-ink); box-shadow: var(--kf-shadow);
        -webkit-backdrop-filter: blur(24px) saturate(1.3); backdrop-filter: blur(24px) saturate(1.3);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      }
      #kf-heat-confirm {
        border: 0; padding: 0; width: min(420px, calc(100vw - 32px));
        border-radius: 18px; background: var(--kf-bg); color: var(--kf-ink); box-shadow: var(--kf-shadow);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      }
      #kf-heat-dialog::backdrop, #kf-heat-confirm::backdrop {
        background: rgba(9, 9, 11, .55);
        -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px);
      }
      #kf-heat-dialog form { margin: 0; padding: 0; }
      .kf-heat-head { position: relative; padding: 22px 24px 6px; }
      .kf-heat-eyebrow { font-size: 10.5px; font-weight: 700; letter-spacing: .14em; color: var(--kf-accent); text-transform: uppercase; }
      .kf-heat-title { margin: 6px 0 0; font-size: 20px; font-weight: 750; letter-spacing: -.01em; }
      .kf-heat-sub { margin: 6px 0 0; font-size: 12px; line-height: 1.6; color: var(--kf-muted); overflow-wrap: anywhere; padding-right: 40px; }
      .kf-heat-close {
        position: absolute; top: 18px; right: 18px; width: 30px; height: 30px; border-radius: 50%;
        border: 0; background: var(--kf-soft); color: var(--kf-muted); font-size: 17px; line-height: 1;
        cursor: pointer; transition: background .15s ease, color .15s ease;
      }
      .kf-heat-close:hover { background: var(--kf-line); color: var(--kf-ink); }
      .kf-heat-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 14px 24px 0; }
      .kf-heat-stat {
        display: flex; flex-direction: column; gap: 3px; padding: 10px 14px; border-radius: 12px;
        background: var(--kf-soft); border: 1px solid transparent; font-size: 12px;
      }
      .kf-heat-stat:last-child { border-color: color-mix(in srgb, var(--kf-accent) 28%, transparent); background: color-mix(in srgb, var(--kf-accent) 8%, transparent); }
      .kf-heat-stat span { color: var(--kf-muted); font-size: 11px; }
      .kf-heat-stat strong { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
      .kf-heat-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 12px; padding: 16px 24px 4px; }
      .kf-heat-field { display: grid; gap: 6px; align-content: start; }
      .kf-heat-field-wide { grid-column: 1 / -1; }
      .kf-heat-field label { font-size: 12.5px; font-weight: 650; display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
      .kf-heat-field label span { font-weight: 400; font-size: 11px; color: var(--kf-muted); }
      .kf-heat-field input[type="number"], .kf-heat-field input[type="text"] {
        width: 100%; box-sizing: border-box; border: 1px solid var(--kf-line); border-radius: 10px;
        padding: 9px 12px; font-size: 13px; color: var(--kf-ink); background: var(--kf-soft-2); outline: 0;
        transition: border-color .15s ease, box-shadow .15s ease;
      }
      .kf-heat-field input[type="number"]:focus, .kf-heat-field input[type="text"]:focus {
        border-color: var(--kf-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--kf-accent) 18%, transparent); background: var(--kf-bg);
      }
      .kf-heat-chips { display: flex; gap: 6px; flex-wrap: wrap; }
      .kf-heat-chips button {
        border: 1px solid var(--kf-line); background: transparent; color: var(--kf-muted);
        border-radius: 999px; padding: 3px 10px; font-size: 11.5px; cursor: pointer; transition: all .15s ease;
      }
      .kf-heat-chips button:hover { border-color: var(--kf-accent); color: var(--kf-accent); }
      .kf-heat-chips button.is-active { background: var(--kf-accent); border-color: var(--kf-accent); color: #fff; }
      .kf-heat-toggle {
        grid-column: 1 / -1; display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600;
        padding: 10px 12px; border-radius: 12px; background: var(--kf-soft); cursor: pointer;
      }
      .kf-heat-toggle input { position: absolute; opacity: 0; pointer-events: none; }
      .kf-heat-switch {
        position: relative; width: 36px; height: 21px; border-radius: 999px; background: var(--kf-line);
        transition: background .18s ease; flex: none;
      }
      .kf-heat-switch::after {
        content: ""; position: absolute; top: 3px; left: 3px; width: 15px; height: 15px; border-radius: 50%;
        background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, .25); transition: transform .18s ease;
      }
      .kf-heat-toggle input:checked + .kf-heat-switch { background: var(--kf-accent); }
      .kf-heat-toggle input:checked + .kf-heat-switch::after { transform: translateX(15px); }
      .kf-heat-preview { margin: 14px 24px 0; padding: 12px 14px; border-radius: 14px; background: var(--kf-soft); }
      .kf-heat-preview-head { font-size: 11px; font-weight: 700; letter-spacing: .08em; color: var(--kf-muted); text-transform: uppercase; }
      .kf-heat-preview-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 8px; }
      .kf-heat-preview-cell { display: flex; flex-direction: column; gap: 3px; padding: 8px 10px; border-radius: 10px; background: var(--kf-bg); border: 1px solid var(--kf-line); }
      .kf-heat-preview-cell span { font-size: 11px; color: var(--kf-muted); }
      .kf-heat-preview-value { display: flex; align-items: baseline; gap: 4px; flex-wrap: wrap; }
      .kf-heat-preview-value b { font-size: 15px; font-weight: 750; font-variant-numeric: tabular-nums; color: var(--kf-accent); }
      .kf-heat-preview-value em { font-style: normal; font-size: 10.5px; color: var(--kf-muted); }
      .kf-heat-preview-note { margin: 8px 0 0; font-size: 11px; line-height: 1.6; color: var(--kf-muted); }
      .kf-heat-message { margin: 12px 24px 0; padding: 9px 12px; border-radius: 10px; background: color-mix(in srgb, var(--kf-danger) 10%, transparent); color: var(--kf-danger); font-size: 12.5px; line-height: 1.6; }
      .kf-heat-message.ok { background: color-mix(in srgb, var(--kf-ok) 12%, transparent); color: var(--kf-ok); }
      .kf-heat-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 16px 24px 20px; margin-top: 16px; border-top: 1px solid var(--kf-line); }
      .kf-heat-foot button {
        border: 1px solid var(--kf-line); background: transparent; color: var(--kf-ink);
        border-radius: 10px; padding: 8px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer;
        transition: background .15s ease, border-color .15s ease, color .15s ease;
      }
      .kf-heat-foot button:hover { background: var(--kf-soft); }
      .kf-heat-foot button[hidden] { display: none; }
      .kf-heat-foot button[disabled] { opacity: .5; cursor: wait; }
      .kf-heat-foot .kf-heat-primary {
        margin-left: auto; border-color: transparent; color: #fff;
        background: linear-gradient(135deg, var(--kf-accent), var(--kf-accent-2));
        box-shadow: 0 8px 20px color-mix(in srgb, var(--kf-accent) 32%, transparent);
      }
      .kf-heat-foot .kf-heat-primary:hover { filter: brightness(1.06); }
      .kf-heat-foot .kf-heat-danger { border-color: color-mix(in srgb, var(--kf-danger) 45%, transparent); color: var(--kf-danger); }
      .kf-heat-foot .kf-heat-danger:hover { background: color-mix(in srgb, var(--kf-danger) 10%, transparent); }
      .kf-heat-confirm-card { padding: 22px 22px 6px; }
      .kf-heat-confirm-badge {
        width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; font-size: 19px;
        background: color-mix(in srgb, var(--kf-danger) 12%, transparent); color: var(--kf-danger); margin-bottom: 12px;
      }
      .kf-heat-confirm-title { margin: 0 0 8px; font-size: 17px; font-weight: 750; }
      .kf-heat-confirm-text { margin: 0; font-size: 13px; line-height: 1.75; color: var(--kf-muted); overflow-wrap: anywhere; }
      .kf-heat-confirm-card .kf-heat-foot { margin-top: 16px; border-top: 1px solid var(--kf-line); padding: 14px 0 18px; }
      .kf-heat-confirm-card .kf-heat-danger { background: var(--kf-danger); border-color: var(--kf-danger); color: #fff; }
      @media (max-width: 560px) {
        .kf-heat-fields { grid-template-columns: 1fr; }
        .kf-heat-stats { grid-template-columns: 1fr; }
        .kf-heat-preview-grid { grid-template-columns: 1fr; }
      }
    `;
    document.head.append(style);
  }

  function ensureConfirm() {
    if (confirmDialog) return confirmDialog;
    ensureStyle();
    confirmDialog = document.createElement("dialog");
    confirmDialog.id = "kf-heat-confirm";
    confirmDialog.innerHTML = `
      <div class="kf-heat-confirm-card">
        <div class="kf-heat-confirm-badge" aria-hidden="true">⚠</div>
        <h3 class="kf-heat-confirm-title">停止并恢复数字？</h3>
        <p class="kf-heat-confirm-text" id="kf-heat-confirm-text"></p>
        <div class="kf-heat-foot">
          <button type="button" id="kf-heat-confirm-cancel">取消</button>
          <button type="button" id="kf-heat-confirm-ok" class="kf-heat-danger">确认停止并恢复</button>
        </div>
      </div>`;
    document.body.append(confirmDialog);
    return confirmDialog;
  }

  function askConfirm(text) {
    const node = ensureConfirm();
    node.querySelector("#kf-heat-confirm-text").textContent = text;
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        node.close();
        resolve(value);
      };
      node.querySelector("#kf-heat-confirm-ok").onclick = () => finish(true);
      node.querySelector("#kf-heat-confirm-cancel").onclick = () => finish(false);
      node.onclose = () => finish(false);
      node.showModal();
    });
  }

  function ensureDialog() {
    if (dialog) return dialog;
    ensureStyle();
    dialog = document.createElement("dialog");
    dialog.id = "kf-heat-dialog";
    dialog.innerHTML = `
      <form id="kf-heat-form">
        <header class="kf-heat-head">
          <div class="kf-heat-eyebrow">KFLOW · 展示热度</div>
          <h2 class="kf-heat-title">设置展示热度</h2>
          <p class="kf-heat-sub" id="kf-heat-sub"></p>
          <button type="button" class="kf-heat-close" id="kf-heat-close" aria-label="关闭">×</button>
        </header>
        <div class="kf-heat-stats">
          <div class="kf-heat-stat"><span>真实数据</span><strong id="kf-heat-real">–</strong></div>
          <div class="kf-heat-stat"><span>当前展示</span><strong id="kf-heat-display">–</strong></div>
        </div>
        <div class="kf-heat-fields">
          <div class="kf-heat-field">
            <label for="kf-heat-views">目标浏览 <span>0 = 跟随全局</span></label>
            <input id="kf-heat-views" type="number" min="0" max="5000" step="1" inputmode="numeric" />
            <div class="kf-heat-chips" data-for="kf-heat-views">
              <button type="button" data-value="120">120</button>
              <button type="button" data-value="300">300</button>
              <button type="button" data-value="600">600</button>
              <button type="button" data-value="1000">1000</button>
            </div>
          </div>
          <div class="kf-heat-field">
            <label for="kf-heat-days">几天涨到 <span>0 = 跟随全局</span></label>
            <input id="kf-heat-days" type="number" min="0" max="30" step="1" inputmode="numeric" />
            <div class="kf-heat-chips" data-for="kf-heat-days">
              <button type="button" data-value="1">1 天</button>
              <button type="button" data-value="3">3 天</button>
              <button type="button" data-value="7">7 天</button>
              <button type="button" data-value="14">14 天</button>
            </div>
          </div>
          <div class="kf-heat-field kf-heat-field-wide">
            <label for="kf-heat-likes">显示多少赞 <span>0 = 按点赞率自动换算（最多 8%）</span></label>
            <input id="kf-heat-likes" type="number" min="0" max="400" step="1" inputmode="numeric" />
          </div>
          <div class="kf-heat-field kf-heat-field-wide">
            <label for="kf-heat-note">备注 <span>只给自己看</span></label>
            <input id="kf-heat-note" type="text" maxlength="200" placeholder="为什么给这条加热，例如：新功能上线推广" />
          </div>
          <label class="kf-heat-toggle">
            <input id="kf-heat-enabled" type="checkbox" checked />
            <span class="kf-heat-switch" aria-hidden="true"></span>
            <span>启用展示热度</span>
          </label>
        </div>
        <div class="kf-heat-preview">
          <div class="kf-heat-preview-head">预览</div>
          <div class="kf-heat-preview-grid" id="kf-heat-preview">
            <div class="kf-heat-preview-cell"><span>现在</span><div class="kf-heat-preview-value"><b>–</b><em>浏览</em><b>–</b><em>赞</em></div></div>
            <div class="kf-heat-preview-cell"><span>1 天后</span><div class="kf-heat-preview-value"><b>–</b><em>浏览</em><b>–</b><em>赞</em></div></div>
            <div class="kf-heat-preview-cell"><span>几天后</span><div class="kf-heat-preview-value"><b>–</b><em>浏览</em><b>–</b><em>赞</em></div></div>
          </div>
          <p class="kf-heat-preview-note">数字会从真实值慢慢涨到目标值，之后保持不变；真实数据永远独立保存，不写库。</p>
        </div>
        <p class="kf-heat-message" id="kf-heat-message" hidden></p>
        <footer class="kf-heat-foot">
          <button type="button" id="kf-heat-freeze" class="kf-heat-ghost">停用（保留数字）</button>
          <button type="button" id="kf-heat-reset" class="kf-heat-danger">停止并恢复数字</button>
          <button type="button" id="kf-heat-cancel" class="kf-heat-ghost">取消</button>
          <button type="submit" id="kf-heat-save" class="kf-heat-primary">保存</button>
        </footer>
      </form>`;
    document.body.append(dialog);

    dialog.querySelector("#kf-heat-close").addEventListener("click", () => dialog.close());
    dialog.querySelector("#kf-heat-cancel").addEventListener("click", () => dialog.close());
    dialog.querySelector("#kf-heat-form").addEventListener("submit", (event) => {
      event.preventDefault();
      save();
    });
    dialog.querySelector("#kf-heat-freeze").addEventListener("click", freezeOverride);
    dialog.querySelector("#kf-heat-reset").addEventListener("click", restoreOverride);
    for (const id of ["kf-heat-views", "kf-heat-days", "kf-heat-likes"]) {
      dialog.querySelector("#" + id).addEventListener("input", () => {
        syncChips();
        schedulePreview();
      });
    }
    dialog.querySelector("#kf-heat-enabled").addEventListener("change", schedulePreview);
    dialog.querySelectorAll(".kf-heat-chips").forEach((chips) => {
      chips.addEventListener("click", (event) => {
        const btn = event.target.closest("button[data-value]");
        if (!btn) return;
        const input = dialog.querySelector("#" + chips.dataset.for);
        input.value = btn.dataset.value;
        syncChips();
        schedulePreview();
      });
    });
    return dialog;
  }

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  function num(el) {
    const value = Number(el.value);
    return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  }

  function syncChips() {
    if (!dialog) return;
    dialog.querySelectorAll(".kf-heat-chips").forEach((chips) => {
      const input = dialog.querySelector("#" + chips.dataset.for);
      const value = String(num(input));
      chips.querySelectorAll("button[data-value]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.value === value);
      });
    });
  }

  function normalizeItem(kind, item) {
    if (kind === "murmur") {
      return {
        id: Number(item.id),
        excerpt: (item.content || "").slice(0, 80),
        real: item.real || { views: item.view_count, likes: item.like_count },
        display: item.display || { views: item.display_view_count, likes: item.display_like_count },
      };
    }
    return {
      id: Number(item.id),
      excerpt: item.title || (item.content || "").slice(0, 80),
      real: item.real || { views: item.views, likes: item.likes },
      display: item.display || { views: item.display_views, likes: item.display_likes },
    };
  }

  function renderStats(info) {
    const real = dialog.querySelector("#kf-heat-real");
    const display = dialog.querySelector("#kf-heat-display");
    if (real) real.textContent = `${info.real.views} 浏览 · ${info.real.likes} 赞`;
    if (display) display.textContent = `${info.display.views} 浏览 · ${info.display.likes} 赞`;
  }

  function message(text, { ok = false, keep = false } = {}) {
    const node = dialog.querySelector("#kf-heat-message");
    node.textContent = text;
    node.classList.toggle("ok", ok);
    node.hidden = !text;
    if (!text) return;
    if (!keep) {
      clearTimeout(message.timer);
      message.timer = setTimeout(() => { node.hidden = true; }, 6000);
    }
  }

  function showPreview(data) {
    const grid = dialog.querySelector("#kf-heat-preview");
    if (!data || !data.preview) {
      grid.textContent = "预览加载中…";
      return;
    }
    const p = data.preview;
    const grow = Number(p.grow_days) || 7;
    const cells = [...grid.querySelectorAll(".kf-heat-preview-cell")];
    const labels = [`现在`, `1 天后`, `${grow} 天后`];
    cells.forEach((cell, index) => {
      const key = ["now", "day1", "grow"][index];
      const value = p[key] || { views: 0, likes: 0 };
      cell.querySelector("span").textContent = labels[index];
      const strongs = cell.querySelectorAll("b");
      if (strongs.length >= 2) {
        strongs[0].textContent = value.views;
        strongs[1].textContent = value.likes;
      }
    });
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 300);
  }

  async function refreshPreview() {
    if (!current || !dialog.open) return;
    const params = new URLSearchParams({
      target_views: String(num(dialog.querySelector("#kf-heat-views"))),
      grow_days: String(num(dialog.querySelector("#kf-heat-days"))),
      target_likes: String(num(dialog.querySelector("#kf-heat-likes"))),
      enabled: dialog.querySelector("#kf-heat-enabled").checked ? "1" : "0",
    });
    try {
      const res = await fetch(`${API[current.kind](current.id)}?${params}`);
      if (!res.ok) return;
      const data = await res.json();
      showPreview(data);
    } catch {
      /* 预览失败不打扰保存流程 */
    }
  }

  function setStopButtons(override) {
    const freezeBtn = dialog.querySelector("#kf-heat-freeze");
    const resetBtn = dialog.querySelector("#kf-heat-reset");
    const enabled = Boolean(override && override.enabled);
    const frozen = Boolean(override && !override.enabled && override.frozen_at);
    freezeBtn.hidden = !enabled;
    resetBtn.hidden = !(enabled || frozen);
    freezeBtn.disabled = false;
    resetBtn.disabled = false;
  }

  async function open(kind, item, options = {}) {
    if (!item || !item.id) return;
    ensureDialog();
    current = { kind, id: Number(item.id), onSaved: typeof options.onSaved === "function" ? options.onSaved : null };
    const info = normalizeItem(kind, item);
    dialog.querySelector("#kf-heat-sub").textContent = `${LABEL[kind]} · #${current.id} · ${info.excerpt || "（无正文）"}`;
    renderStats(info);
    setStopButtons(null);
    message("");
    dialog.showModal();
    try {
      const res = await fetch(API[kind](current.id));
      if (!res.ok) {
        message("读取设置失败，请刷新后重试。", { keep: true });
        return;
      }
      const data = await res.json();
      const override = data.override;
      dialog.querySelector("#kf-heat-views").value = override ? override.target_views : 0;
      dialog.querySelector("#kf-heat-days").value = override ? override.grow_days : 0;
      dialog.querySelector("#kf-heat-likes").value = override ? override.target_likes : 0;
      dialog.querySelector("#kf-heat-note").value = override ? override.note : "";
      dialog.querySelector("#kf-heat-enabled").checked = override ? override.enabled : true;
      syncChips();
      const merged = {
        real: data.real || info.real,
        display: data.display || info.display,
      };
      renderStats(merged);
      showPreview(data);
      setStopButtons(override);
    } catch {
      message("读取设置失败，请刷新后重试。", { keep: true });
    }
  }

  function finish(ctx, delay) {
    if (!ctx) return;
    if (ctx.onSaved) {
      setTimeout(() => {
        dialog.close();
        ctx.onSaved();
      }, delay);
      return;
    }
    setTimeout(() => location.reload(), delay);
  }

  async function save() {
    if (!current) return;
    const button = dialog.querySelector("#kf-heat-save");
    button.disabled = true;
    message("");
    const body = {
      target_views: num(dialog.querySelector("#kf-heat-views")),
      grow_days: num(dialog.querySelector("#kf-heat-days")),
      target_likes: num(dialog.querySelector("#kf-heat-likes")),
      note: dialog.querySelector("#kf-heat-note").value.trim(),
      enabled: dialog.querySelector("#kf-heat-enabled").checked,
    };
    try {
      let res = await fetch(API[current.kind](current.id), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify(body),
      });
      let data = await res.json().catch(() => ({}));
      if (!res.ok) {
        message(data.error || "保存失败，请稍后重试。", { keep: true });
        return;
      }
      if (data.needs_force) {
        const ok = await askConfirm(data.message || "调低目标会让数字立刻变小，确定继续吗？");
        if (!ok) return;
        body.force = true;
        res = await fetch(API[current.kind](current.id), {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify(body),
        });
        data = await res.json().catch(() => ({}));
        if (!res.ok) {
          message(data.error || "保存失败，请稍后重试。", { keep: true });
          return;
        }
      }
      renderStats({ real: data.real, display: data.display });
      showPreview(data);
      const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
      message(warnings.length ? `已保存。${warnings.join("；")}` : "已保存，页面即将刷新。", { ok: true, keep: true });
      finish(current, warnings.length ? 1600 : 700);
    } catch {
      message("网络中断，请检查后重试。", { keep: true });
    } finally {
      button.disabled = false;
    }
  }

  async function freezeOverride() {
    if (!current) return;
    const button = dialog.querySelector("#kf-heat-freeze");
    button.disabled = true;
    message("");
    try {
      const res = await fetch(API[current.kind](current.id), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ enabled: false }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        message(data.error || "停用失败，请稍后重试。", { keep: true });
        return;
      }
      message("已停用：停止加热，数字保持不变。", { ok: true, keep: true });
      finish(current, 900);
    } catch {
      message("网络中断，请检查后重试。", { keep: true });
    } finally {
      button.disabled = false;
    }
  }

  async function restoreOverride() {
    if (!current) return;
    const ok = await askConfirm("把这条帖子恢复成真实数字：不再按展示热度显示，即使全局开关开着也只显示真实浏览和真实赞。数字会立刻变小，而且不会自动恢复。确定继续吗？");
    if (!ok) return;
    const button = dialog.querySelector("#kf-heat-reset");
    button.disabled = true;
    message("");
    try {
      const res = await fetch(API[current.kind](current.id), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ enabled: false, freeze: false }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        message(data.error || "恢复失败，请稍后重试。", { keep: true });
        return;
      }
      message("已停止加热并恢复真实数字。", { ok: true, keep: true });
      finish(current, 900);
    } catch {
      message("网络中断，请检查后重试。", { keep: true });
    } finally {
      button.disabled = false;
    }
  }

  window.KflowHeatAdmin = { open, askConfirm };
})();
