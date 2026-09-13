(() => {
  const TIER_META = {
    gold: { label: "金牌成就", desc: "社区顶尖贡献的象征" },
    silver: { label: "银牌成就", desc: "持续活跃与高质量互动" },
    bronze: { label: "铜牌成就", desc: "迈出第一步就有收获" },
  };
  const TIER_ORDER = ["gold", "silver", "bronze"];

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child == null) continue;
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function showToast(msg, type = "info") {
    const toast = document.querySelector("#forum-toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `forum-toast show ${type}`;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
  }

  function badgeIcon(name, size) {
    if (window.kflowIcons) return window.kflowIcons.el(name, size || 22);
    return document.createElement("span");
  }

  function badgeCard(item, earnedMap, showcasedCode, onShowcaseChange) {
    const earned = Boolean(earnedMap[item.code]);
    const card = el("article", {
      className: "badge-card" + (earned ? " earned" : ""),
    });
    const medal = el("div", { className: `badge-medal tier-${item.tier}` }, badgeIcon(item.icon, 22));
    const body = el("div", { className: "badge-body" });
    const titleRow = el("div", { className: "badge-title-row" });
    titleRow.append(el("h3", { textContent: item.name }));
    if (earned) {
      titleRow.append(el("span", { className: "badge-earned-chip" }, "已获得"));
    }
    if (showcasedCode === item.code) {
      titleRow.append(el("span", { className: "badge-earned-chip showcasing", textContent: "展示中" }));
    }
    body.append(
      titleRow,
      el("p", { className: "badge-desc", textContent: item.description || "" }),
    );
    const meta = el("div", { className: "badge-meta" });
    meta.append(
      el("span", { className: `badge-tier tier-text-${item.tier}`, textContent: { gold: "金", silver: "银", bronze: "铜" }[item.tier] || item.tier }),
    );
    meta.append(el("span", { className: "badge-holders", textContent: `${item.holderCount || 0} 人获得` }));
    if (earned && earnedMap[item.code]) {
      meta.append(el("span", { className: "badge-date", textContent: new Date(earnedMap[item.code]).toLocaleDateString("zh-CN") }));
    }
    body.append(meta);
    // 展示切换（仅已获得的勋章）
    if (earned && onShowcaseChange) {
      const isShowcasing = showcasedCode === item.code;
      body.append(
        el("button", {
          className: "badge-showcase-btn" + (isShowcasing ? " active" : ""),
          type: "button",
          textContent: isShowcasing ? "取消展示" : "设为展示",
          onclick: () => onShowcaseChange(item, isShowcasing),
        }),
      );
    }
    card.append(medal, body);
    return card;
  }

  let currentShowcase = null;

  async function setShowcase(item, cancel) {
    try {
      const res = await fetch("/api/achievements/showcase", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "" },
        body: JSON.stringify({ code: cancel ? "" : item.code }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "操作失败");
      currentShowcase = data.showcase?.code || null;
      showToast(cancel ? "已取消展示" : `已将「${item.name}」设为展示勋章，发帖时会显示`, "success");
      init();
    } catch (err) {
      showToast(err.message || "操作失败", "error");
    }
  }

  async function init() {
    const groups = document.querySelector("#tierGroups");
    try {
      const res = await fetch("/api/achievements", { credentials: "same-origin" });
      const data = await res.json();
      document.querySelector("#badgeTotal").textContent = data.total ?? 0;
      document.querySelector("#myEarned").textContent = data.earned ?? 0;
      const earnedMap = {};
      for (const b of data.mine || []) earnedMap[b.code] = b.grantedAt;
      groups.replaceChildren();
      for (const tier of TIER_ORDER) {
        const items = (data.items || []).filter((a) => a.tier === tier);
        if (!items.length) continue;
        const section = el("section", { className: "badge-tier-section" });
        section.append(
          el("div", { className: "badge-tier-heading" },
            el("h2", { textContent: TIER_META[tier].label }),
            el("span", { textContent: TIER_META[tier].desc }),
          ),
        );
        const grid = el("div", { className: "badge-grid" });
        for (const item of items) grid.append(badgeCard(item, earnedMap, currentShowcase, setShowcase));
        section.append(grid);
        groups.append(section);
      }
    } catch {
      groups.replaceChildren(el("p", { className: "rankings-empty", textContent: "勋章加载失败，请稍后重试。" }));
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
