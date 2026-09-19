/* KFlow 成就勋章馆:卡片栅格 + hover 浮窗检视 */
(() => {
  const TIER_META = {
    gold: { label: "金牌成就", desc: "社区顶尖贡献的象征" },
    silver: { label: "银牌成就", desc: "持续活跃与高质量互动" },
    bronze: { label: "铜牌成就", desc: "迈出第一步就有收获" },
  };
  const TIER_ORDER = ["gold", "silver", "bronze"];
  const METRIC_LABEL = {
    topics: "主题帖",
    replies: "回复",
    likes_given: "送出点赞",
    likes_received: "主题获赞",
    reply_likes_received: "回复获赞",
    likes_total: "累计获赞",
    active_days: "活跃天数",
    max_topic_likes: "单篇最高赞",
    tutorials_completed: "完成教程",
    terms_completed: "掌握术语",
    boosts_bought: "购买加热",
    votes_cast: "投出票数",
    listings_sold: "售出商品",
    contribution: "贡献分",
  };

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
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

  // ── 浮窗检视 ──────────────────────────────────────────────
  let inspectOverlay = null;

  function buildInspect(item, earnedAt, isShowcasing) {
    const root = el("div", { className: "badge-inspect" });
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", item.name);

    const closeBtn = el("button", {
      className: "badge-inspect-close", type: "button",
      "aria-label": "关闭", textContent: "×",
    });
    closeBtn.addEventListener("click", closeInspect);

    const inner = el("div", { className: "badge-inspect-inner" });

    // 左侧(主):勋章本体
    const left = el("section", { className: "badge-inspect-left" });
    const medal = el("div", { className: `badge-inspect-medal tier-${item.tier}` },
      badgeIcon(item.icon, 38));
    left.append(medal);
    left.append(el("h2", { className: "badge-inspect-name", textContent: item.name }));
    const tags = el("div", { className: "badge-inspect-tags" });
    const tierText = { gold: "金牌", silver: "银牌", bronze: "铜牌" }[item.tier] || item.tier;
    tags.append(el("span", { className: `kb-pill kb-pill-tier tier-${item.tier}`, textContent: tierText }));
    const categoryText = { creation: "创作", interaction: "互动", activity: "活跃", business: "商务" }[item.category] || item.category;
    if (categoryText) tags.append(el("span", { className: "kb-pill", textContent: categoryText }));
    if (earnedAt) {
      tags.append(el("span", { className: "kb-pill kb-pill-ready", textContent: "已获得" }));
    } else if (item.threshold) {
      tags.append(el("span", { className: "kb-pill", textContent: "待解锁" }));
    }
    if (isShowcasing) {
      tags.append(el("span", { className: "kb-pill kb-pill-ready", textContent: "展示中" }));
    }
    left.append(tags);
    left.append(el("p", { className: "badge-inspect-desc", textContent: item.description || "" }));
    if (earnedAt) {
      left.append(el("div", { className: "badge-inspect-meta" },
        el("span", { textContent: `获得于 ${new Date(earnedAt).toLocaleDateString("zh-CN")}` }),
        el("span", { textContent: `${item.holderCount || 0} 人获得` }),
      ));
    } else {
      left.append(el("div", { className: "badge-inspect-meta" },
        el("span", { textContent: `${item.holderCount || 0} 人已获得` }),
      ));
    }
    if (earnedAt && window.kflowCelebrate) {
      const btn = el("button", {
        className: "kb-btn kb-btn-ghost badge-inspect-showcase",
        type: "button",
        textContent: isShowcasing ? "取消展示" : "设为展示",
      });
      btn.addEventListener("click", () => setShowcase(item, isShowcasing));
      left.append(btn);
    }

    // 右侧(达成要求 + 进度)
    const right = el("section", { className: "badge-inspect-right" });
    right.append(el("h3", { className: "badge-inspect-right-title" }, "达成要求"));
    right.append(el("p", { className: "badge-inspect-req-text", textContent: item.requirement || "由管理员人工授予" }));

    if (item.metricKey && item.threshold) {
      const metricLabel = METRIC_LABEL[item.metricKey] || item.metricKey;
      const current = Number(item.currentValue || 0);
      const target = Number(item.threshold || 0);
      const ratio = target > 0 ? Math.min(1, current / target) : 0;
      const pct = Math.round(ratio * 100);
      const done = Boolean(item.done);

      const progress = el("div", { className: "badge-progress" });
      const header = el("div", { className: "badge-progress-head" });
      header.append(el("span", { className: "badge-progress-label", textContent: metricLabel }));
      header.append(el("span", {
        className: "badge-progress-numbers",
        textContent: `${current.toLocaleString()} / ${target.toLocaleString()}`,
      }));
      progress.append(header);

      const bar = el("div", { className: "badge-progress-bar" + (done ? " done" : "") });
      const fill = el("div", { className: "badge-progress-fill", style: `width:${pct}%` });
      bar.append(fill);
      progress.append(bar);

      progress.append(el("div", { className: "badge-progress-foot" },
        el("span", { className: "badge-progress-pct", textContent: `${pct}%` }),
        el("span", {
          className: done ? "badge-progress-state done" : "badge-progress-state",
          textContent: done ? "✓ 已达成" : "未达成",
        }),
      ));
      right.append(progress);
    } else {
      right.append(el("div", { className: "badge-progress" },
        el("p", { className: "small", textContent: "此勋章由社区管理员人工授予,无法通过行为自动解锁。" }),
      ));
    }

    // 右侧附加信息(同步给前端展示)
    right.append(el("div", { className: "badge-inspect-stat" },
      el("span", { textContent: `当前持有 ${item.holderCount || 0} 人` }),
      el("span", { textContent: `代码 ${item.code}` }),
    ));

    inner.append(left, right);
    root.append(closeBtn, inner);

    // 点击遮罩关闭
    root.addEventListener("click", (e) => {
      if (e.target === root) closeInspect();
    });
    return root;
  }

  function openInspect(item) {
    closeInspect();
    const earnedAt = item.earnedAt || "";
    const isShowcasing = currentShowcase === item.code;
    inspectOverlay = buildInspect(item, earnedAt, isShowcasing);
    document.body.appendChild(inspectOverlay);
    requestAnimationFrame(() => inspectOverlay.classList.add("open"));
    document.addEventListener("keydown", escClose);
  }

  function closeInspect() {
    document.removeEventListener("keydown", escClose);
    if (inspectOverlay && inspectOverlay.parentNode) {
      inspectOverlay.classList.remove("open");
      const overlay = inspectOverlay;
      setTimeout(() => overlay.parentNode?.removeChild(overlay), 180);
      inspectOverlay = null;
    }
  }

  function escClose(e) { if (e.key === "Escape") closeInspect(); }

  function badgeCard(item, earnedMap, showcasedCode, onShowcaseChange) {
    const earned = Boolean(earnedMap[item.code]);
    const card = el("article", {
      className: "badge-card" + (earned ? " earned" : "") + ` tier-${item.tier}`,
      "data-code": item.code,
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
    card.append(medal, body);

    // gacha 抽卡效果:鼠标位置 → 倾斜跟随
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const mx = (e.clientX - rect.left) / rect.width;
      const my = (e.clientY - rect.top) / rect.height;
      card.style.setProperty("--mx", mx.toFixed(3));
      card.style.setProperty("--my", my.toFixed(3));
    });
    card.addEventListener("mouseleave", () => {
      card.style.setProperty("--mx", 0.5);
      card.style.setProperty("--my", 0.5);
    });

    card.addEventListener("click", (e) => {
      if (e.target.closest(".badge-showcase-btn")) return;
      openInspect(item);
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openInspect(item);
      }
    });
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `查看「${item.name}」勋章详情`);
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
      currentShowcase = data.showcaseCode || null;
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