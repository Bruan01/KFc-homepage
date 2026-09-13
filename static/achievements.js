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

  function badgeIcon(name, size) {
    if (window.kflowIcons) return window.kflowIcons.el(name, size || 22);
    return document.createElement("span");
  }

  function badgeCard(item, earnedMap) {
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
    card.append(medal, body);
    return card;
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
        for (const item of items) grid.append(badgeCard(item, earnedMap));
        section.append(grid);
        groups.append(section);
      }
    } catch {
      groups.replaceChildren(el("p", { className: "rankings-empty", textContent: "勋章加载失败，请稍后重试。" }));
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
