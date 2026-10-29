/* 站内通知：头部铃铛 + 下拉面板 + 未读轮询（所有页面共享）。 */
(() => {
  let open = false;
  let bell, badge, panel, list, markAllBtn, modDot;
  let modCard, modSummary, modReportLink, modReportCount, modAppealLink, modAppealCount, modFeatureLink, modFeatureCount;
  let detailOverlay, detailIcon, detailKicker, detailTime, detailTitle, detailBody, detailNote, detailClose;
  let detailTimer = 0;
  let unreadCount = 0;
  let isModerator = false;
  let moderation = { reports: 0, appeals: 0, features: 0, total: 0 };

  function el(tag, attrs = {}) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else node.setAttribute(key, value);
    }
    return node;
  }

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  function timeAgo(iso) {
    if (!iso) return "";
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
    mention: { icon: "bubble", cls: "blue", label: "@提及" },
    message: { icon: "bubble", cls: "blue", label: "私信" },
    sale: { icon: "bag", cls: "green", label: "售出" },
    imaging: { icon: "sparkle", cls: "blue", label: "显影" },
    system: { icon: "star", cls: "blue", label: "通知" },
  };

  function metaFor(row) {
    const title = row.title || "";
    if (title.includes("举报")) return { icon: "flag", cls: "red", label: "举报" };
    if (title.includes("申诉")) return { icon: "shield", cls: "blue", label: "申诉" };
    return TYPE_META[row.type] || TYPE_META.system;
  }

  function fullTime(iso) {
    if (!iso) return "";
    const value = new Date(iso);
    return Number.isNaN(value.getTime()) ? "" : value.toLocaleString("zh-CN");
  }

  function iconEl(name, size) {
    return window.kflowIcons ? window.kflowIcons.el(name, size) : document.createElement("span");
  }

  /* 有来源用户时用对方头像替代分类图标，一眼看清是谁触发的通知。 */
  function notificationIcon(row, meta, size) {
    const host = document.createElement("span");
    host.className = `notif-item-icon ${meta.cls}`;
    const actor = (row && row.actor) || {};
    const fallback = () => {
      host.classList.remove("has-avatar");
      host.replaceChildren();
      const glyph = iconEl(meta.icon, size);
      if (glyph) host.append(glyph);
    };
    if (actor.avatar_url) {
      host.classList.add("has-avatar");
      const image = document.createElement("img");
      image.alt = "";
      image.loading = "lazy";
      image.src = actor.avatar_url;
      image.addEventListener("error", fallback);
      host.append(image);
    } else {
      fallback();
    }
    return host;
  }

  async function api(url, opts = {}) {
    return fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...opts.headers },
      ...opts,
    });
  }

  function syncBellMeta() {
    if (!bell) return;
    const unread = unreadCount ? `${unreadCount} 条未读通知` : "无未读消息";
    const pending = moderation.total ? `，${moderation.total} 条待处理举报、申诉或精选投稿` : "";
    bell.setAttribute("aria-label", `站内通知，${unread}${pending}`);
    if (moderation.total) bell.title = `${moderation.reports} 条待处理举报，${moderation.appeals} 条待处理申诉，${moderation.features} 条精选投稿待审核`;
    else bell.removeAttribute("title");
  }

  async function refreshBadge() {
    if (!badge) return;
    try {
      const res = await api("/api/notifications/unread-count");
      const data = await res.json();
      unreadCount = Math.max(0, Number(data.unreadCount) || 0);
      badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
      badge.hidden = unreadCount === 0;
      bell.classList.toggle("has-unread", unreadCount > 0);
      syncBellMeta();
    } catch {
      /* 静默 */
    }
  }

  function applyModeration(data) {
    moderation = {
      reports: Math.max(0, Number(data.reports) || 0),
      appeals: Math.max(0, Number(data.appeals) || 0),
      features: Math.max(0, Number(data.features) || 0),
      total: Math.max(0, Number(data.total) || 0),
    };
    if (modDot) {
      modDot.hidden = moderation.total === 0;
      modDot.href = moderation.reports ? "/murmurs?view=reports"
        : moderation.appeals ? "/murmurs?view=reports&mod=appeals"
        : "/murmurs?view=reports&mod=features";
      const label = `待处理：${moderation.reports} 条举报，${moderation.appeals} 条申诉，${moderation.features} 条精选投稿`;
      modDot.setAttribute("aria-label", label);
      modDot.title = label;
    }
    if (modCard) {
      modCard.hidden = moderation.total === 0;
      modSummary.textContent = `共 ${moderation.total} 条待处理`;
      modReportLink.hidden = moderation.reports === 0;
      modReportCount.textContent = String(moderation.reports);
      modAppealLink.hidden = moderation.appeals === 0;
      modAppealCount.textContent = String(moderation.appeals);
      modFeatureLink.hidden = moderation.features === 0;
      modFeatureCount.textContent = String(moderation.features);
    }
    syncBellMeta();
  }

  async function refreshModerationBadge() {
    try {
      const res = await api("/api/admin/murmurs/pending-count");
      if (!res.ok) return;
      applyModeration(await res.json());
    } catch {
      /* 非管理员或网络异常时保持静默 */
    }
  }

  async function watchModeration() {
    const auth = window.kflowAuthReady;
    if (!auth) return;
    let user = null;
    try {
      user = await auth;
    } catch {
      return;
    }
    if (!user || user.role !== "admin") return;
    if (Number(user.adminLevel) < 2 && !user.isSuper) return;
    isModerator = true;
    refreshModerationBadge();
    setInterval(refreshModerationBadge, 60000);
  }

  function buildModerationCard() {
    if (!panel || !list) return;
    modCard = el("section", { className: "notif-mod-card", hidden: "true", "aria-label": "待处理的管理事务" });
    const iconSpan = el("span", { className: "notif-mod-icon" });
    const glyph = iconEl("flag", 15);
    if (glyph) iconSpan.append(glyph);
    modSummary = el("small", { textContent: "暂无待处理事务" });
    const copy = el("div", { className: "notif-mod-copy" });
    copy.append(el("strong", { textContent: "待处理的管理事务" }), modSummary);
    const head = el("div", { className: "notif-mod-head" });
    head.append(iconSpan, copy);

    modReportCount = el("strong", { textContent: "0" });
    modReportLink = el("a", { className: "notif-mod-link", href: "/murmurs?view=reports" });
    modReportLink.append(el("span", { textContent: "举报" }), modReportCount, el("span", { className: "notif-mod-go", textContent: "去处理" }));

    modAppealCount = el("strong", { textContent: "0" });
    modAppealLink = el("a", { className: "notif-mod-link", href: "/murmurs?view=reports&mod=appeals" });
    modAppealLink.append(el("span", { textContent: "申诉" }), modAppealCount, el("span", { className: "notif-mod-go", textContent: "去复核" }));

    modFeatureCount = el("strong", { textContent: "0" });
    modFeatureLink = el("a", { className: "notif-mod-link", href: "/murmurs?view=reports&mod=features" });
    modFeatureLink.append(el("span", { textContent: "精选" }), modFeatureCount, el("span", { className: "notif-mod-go", textContent: "审核" }));

    const links = el("div", { className: "notif-mod-links" });
    links.append(modReportLink, modAppealLink, modFeatureLink);
    modCard.append(head, links);
    panel.insertBefore(modCard, list);
  }

  function detailHint(row) {
    const title = row.title || "";
    if (title.includes("举报")) {
      if (/下线|删除/.test(title)) {
        return "这是你提交举报的处理结果，被举报内容已下线，无法再打开原帖。申诉入口只对内容作者开放：如果你是作者，请从「你的内容被删除」通知进入申诉；举报人不能代为申诉。";
      }
      return "这是你提交举报的处理结果。申诉入口只对内容作者开放，举报人不能代为申诉。";
    }
    return "这条通知没有关联页面，以上是完整内容。";
  }

  function buildDetail() {
    detailOverlay = el("div", { className: "notif-detail-overlay", hidden: "true" });
    const card = el("section", {
      className: "notif-detail",
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "notif-detail-title",
      "aria-describedby": "notif-detail-body",
    });
    const head = el("div", { className: "notif-detail-head" });
    detailIcon = el("span", { className: "notif-item-icon" });
    const meta = el("div", { className: "notif-detail-meta" });
    detailKicker = el("small", { className: "notif-detail-kicker" });
    detailTime = el("time", { className: "notif-detail-time" });
    meta.append(detailKicker, detailTime);
    head.append(detailIcon, meta);
    detailTitle = el("h3", { className: "notif-detail-title", id: "notif-detail-title" });
    detailBody = el("p", { className: "notif-detail-body", id: "notif-detail-body" });
    detailNote = el("p", { className: "notif-detail-note", hidden: "true" });
    const feed = el("a", { className: "notif-detail-link", href: "/murmurs" });
    const glyph = iconEl("bubble", 14);
    if (glyph) feed.append(glyph);
    feed.append(document.createTextNode("前往碎碎念"));
    detailClose = el("button", { type: "button", className: "notif-detail-close", textContent: "关闭" });
    const actions = el("div", { className: "notif-detail-actions" });
    actions.append(feed, detailClose);
    card.append(head, detailTitle, detailBody, detailNote, actions);
    detailOverlay.append(card);
    document.body.append(detailOverlay);
    detailOverlay.addEventListener("click", (event) => {
      if (event.target === detailOverlay) closeDetail();
    });
    detailClose.addEventListener("click", () => closeDetail());
  }

  function closeDetail() {
    if (!detailOverlay || detailOverlay.hidden) return;
    detailOverlay.classList.remove("open");
    window.clearTimeout(detailTimer);
    detailTimer = window.setTimeout(() => {
      if (!detailOverlay.classList.contains("open")) detailOverlay.hidden = true;
    }, 180);
    bell?.focus();
  }

  function openDetail(row) {
    if (!detailOverlay) buildDetail();
    window.clearTimeout(detailTimer);
    open = false;
    bell.setAttribute("aria-expanded", "false");
    panel.classList.remove("open");
    panel.hidden = true;
    const meta = metaFor(row);
    const iconNode = notificationIcon(row, meta, 18);
    detailIcon.className = iconNode.className;
    detailIcon.replaceChildren(...iconNode.childNodes);
    detailKicker.textContent = meta.label === "举报" ? "举报处理结果" : `${meta.label}通知`;
    detailTime.textContent = fullTime(row.createdAt) || timeAgo(row.createdAt);
    detailTime.dateTime = row.createdAt || "";
    detailTitle.textContent = row.title || meta.label || "通知";
    detailBody.textContent = row.body || "这条通知没有附加说明。";
    detailNote.textContent = detailHint(row);
    detailNote.hidden = false;
    detailOverlay.hidden = false;
    void detailOverlay.offsetWidth;
    detailOverlay.classList.add("open");
    detailClose.focus();
  }

  function renderItem(row) {
    if (!row || row.id == null) return null; // 跳过非法数据
    const meta = metaFor(row);
    const item = document.createElement("button");
    item.type = "button";
    item.className = "notif-item" + (row.isRead ? "" : " unread");
    const title = row.title || meta.label || "通知";
    const iconSpan = notificationIcon(row, meta, 16);
    const mainSpan = document.createElement("span");
    mainSpan.className = "notif-item-main";
    mainSpan.append(Object.assign(document.createElement("strong"), { textContent: title }));
    if (row.body) mainSpan.append(Object.assign(document.createElement("small"), { textContent: row.body }));
    mainSpan.append(Object.assign(document.createElement("time"), { textContent: timeAgo(row.createdAt) }));
    item.append(iconSpan, mainSpan);
    if (!row.isRead) item.append(el("span", { className: "notif-dot" }));
    if (row.link) {
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
        bell.setAttribute("aria-expanded", "false");
        panel.hidden = true;
        window.location.href = row.link;
      });
    } else {
      item.setAttribute("aria-haspopup", "dialog");
      const more = el("span", { className: "notif-item-more", "aria-hidden": "true" });
      const chevron = iconEl("chevron", 13);
      if (chevron) more.append(chevron);
      item.append(more);
      item.addEventListener("click", async () => {
        try {
          if (!row.isRead) {
            await api("/api/notifications/mark-read", {
              method: "POST",
              headers: { "X-CSRFToken": csrf() },
              body: JSON.stringify({ ids: [row.id] }),
            });
          }
        } catch { /* 忽略，仍然展示详情 */ }
        openDetail(row);
        refreshBadge();
      });
    }
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
        refreshBadge();
        return;
      }
      for (const row of items) {
        const node = renderItem(row);
        if (node) list.append(node);
      }
      if (!list.children.length) {
        list.append(Object.assign(document.createElement("div"), { className: "notif-empty", textContent: "暂无通知。" }));
      }
      refreshBadge();
    } catch {
      list.replaceChildren(Object.assign(document.createElement("div"), { className: "notif-empty", textContent: "通知加载失败。" }));
    }
  }

  // 窄屏下通知面板是 fixed（见 mobile.css），写死的 top 会跟头部换行错位，
  // 这里按头部真实底边定位。
  function anchorPanel() {
    if (!window.matchMedia("(max-width: 860px)").matches) { panel.style.top = ""; return; }
    const header = panel.closest(".forum-header, .topbar");
    panel.style.top = header ? `${Math.round(header.getBoundingClientRect().bottom) + 6}px` : "";
  }

  function toggle() {
    open = !open;
    bell.setAttribute("aria-expanded", String(open));
    panel.hidden = !open;
    if (open) {
      anchorPanel();
      refreshList();
      if (isModerator) refreshModerationBadge();
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
    if (!panel) return;
    bell.setAttribute("aria-controls", "notifPanel");
    bell.setAttribute("aria-expanded", "false");
    badge?.setAttribute("aria-hidden", "true");
    modDot = el("a", { className: "notif-mod-dot", href: "/murmurs?view=reports", hidden: "true", "aria-label": "待处理的管理事务" });
    (bell.parentElement || bell).appendChild(modDot);

    bell.addEventListener("click", (e) => {
      e.stopPropagation();
      toggle();
    });
    document.addEventListener("click", (e) => {
      if (open && panel && !panel.contains(e.target) && e.target !== bell) {
        open = false;
        bell.setAttribute("aria-expanded", "false");
        panel.classList.remove("open");
        setTimeout(() => { if (!open && panel) panel.hidden = true; }, 180);
      }
    });
    panel.addEventListener("click", (e) => e.stopPropagation());
    window.addEventListener("resize", () => { if (open) anchorPanel(); }, { passive: true });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (detailOverlay && !detailOverlay.hidden) {
        closeDetail();
        return;
      }
      if (open) {
        open = false;
        panel.hidden = true;
        panel.classList.remove("open");
        bell.setAttribute("aria-expanded", "false");
        bell.focus();
      }
    });
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
    buildModerationCard();
    window.addEventListener("kflow:moderation-changed", (event) => applyModeration(event.detail || {}));
    refreshBadge();
    watchModeration();
    setInterval(refreshBadge, 60000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
