/* 站内通知：头部铃铛 + 下拉面板 + 未读轮询（所有页面共享）。 */
(() => {
  let open = false;
  let bell, badge, panel, list, markAllBtn;

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  function timeAgo(iso) {
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return "";
    const diff = Math.max(0, Date.now() - t) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
    return new Date(iso).toLocaleDateString("zh-CN");
  }

  const TYPE_META = {
    badge: { icon: "trophy", cls: "gold", label: "成就" },
    level: { icon: "star", cls: "blue", label: "升级" },
    like: { icon: "heart", cls: "red", label: "点赞" },
    reply: { icon: "bubble", cls: "blue", label: "评论" },
    reply_like: { icon: "heart", cls: "red", label: "赞评论" },
    sale: { icon: "bag", cls: "green", label: "售出" },
    system: { icon: "star", cls: "blue", label: "通知" },
  };

  function iconEl(name, size) {
    return window.kflowIcons ? window.kflowIcons.el(name, size) : document.createElement("span");
  }

  async function api(url, opts = {}) {
    return fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...opts.headers },
      ...opts,
    });
  }

  async function refreshBadge() {
    if (!badge) return;
    try {
      const res = await api("/api/notifications/unread-count");
      const data = await res.json();
      const count = data.unreadCount || 0;
      badge.textContent = count > 99 ? "99+" : String(count);
      badge.hidden = count === 0;
      bell.classList.toggle("has-unread", count > 0);
      if (count > 0) {
        bell.classList.remove("shake");
        void bell.offsetWidth;
        bell.classList.add("shake");
      }
    } catch {
      /* 静默 */
    }
  }

  function renderItem(row) {
    const meta = TYPE_META[row.type] || TYPE_META.system;
    const item = document.createElement("button");
    item.type = "button";
    item.className = "notif-item" + (row.isRead ? "" : " unread");
    const icon = iconEl(meta.icon, 16);
    item.append(
      Object.assign(document.createElement("span"), { className: `notif-item-icon ${meta.cls}` }, icon),
      Object.assign(document.createElement("span"), { className: "notif-item-main" },
        Object.assign(document.createElement("strong"), { textContent: row.title }),
        row.body ? Object.assign(document.createElement("small"), { textContent: row.body }) : null,
        Object.assign(document.createElement("time"), { textContent: timeAgo(row.createdAt) }),
      ),
      row.isRead ? null : Object.assign(document.createElement("span"), { className: "notif-dot" }),
    );
    item.addEventListener("click", async () => {
      try {
        if (!row.isRead) {
          await api("/api/notifications/mark-read", {
            method: "POST",
            headers: { "X-CSRFToken": csrf() },
            body: JSON.stringify({ ids: [row.id] }),
          });
        }
      } catch { /* 忽略，仍然跳转 */ }
      open = false;
      panel.hidden = true;
      if (row.link) window.location.href = row.link;
      else refreshList();
    });
    return item;
  }

  async function refreshList() {
    if (!list) return;
    list.replaceChildren(Object.assign(document.createElement("div"), { className: "notif-empty", textContent: "加载中…" }));
    try {
      const res = await api("/api/notifications?limit=20");
      const data = await res.json();
      list.replaceChildren();
      const items = data.items || [];
      if (!items.length) {
        list.append(Object.assign(document.createElement("div"), {
          className: "notif-empty", textContent: "暂无通知。发帖、点赞、获得勋章都会出现在这里。",
        }));
        return;
      }
      for (const row of items) list.append(renderItem(row));
      refreshBadge();
    } catch {
      list.replaceChildren(Object.assign(document.createElement("div"), { className: "notif-empty", textContent: "通知加载失败。" }));
    }
  }

  function toggle() {
    open = !open;
    panel.hidden = !open;
    if (open) {
      refreshList();
      requestAnimationFrame(() => panel.classList.add("open"));
    } else {
      panel.classList.remove("open");
    }
  }

  function init() {
    bell = document.getElementById("notifBell");
    if (!bell) return;
    badge = document.getElementById("notifBadge");
    panel = document.getElementById("notifPanel");
    list = document.getElementById("notifList");
    markAllBtn = document.getElementById("notifMarkAll");

    bell.addEventListener("click", (e) => {
      e.stopPropagation();
      toggle();
    });
    document.addEventListener("click", (e) => {
      if (open && panel && !panel.contains(e.target) && e.target !== bell) {
        open = false;
        panel.classList.remove("open");
        setTimeout(() => { if (!open && panel) panel.hidden = true; }, 180);
      }
    });
    panel.addEventListener("click", (e) => e.stopPropagation());
    if (markAllBtn) {
      markAllBtn.addEventListener("click", async () => {
        try {
          await api("/api/notifications/mark-all-read", {
            method: "POST",
            headers: { "X-CSRFToken": csrf() },
          });
        } catch { /* ignore */ }
        refreshList();
      });
    }
    refreshBadge();
    setInterval(refreshBadge, 60000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
