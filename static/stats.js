(() => {
  const state = { period: "weekly" };

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

  const OVERVIEW_ITEMS = [
    { key: "members", label: "社区成员", icon: "person" },
    { key: "topics", label: "作品帖", icon: "pencil" },
    { key: "replies", label: "评论", icon: "bubble" },
    { key: "likes", label: "点赞互动", icon: "heart" },
    { key: "badgesGranted", label: "勋章已发放", icon: "trophy" },
  ];

  async function loadOverview() {
    const wrap = document.querySelector("#overviewCards");
    try {
      const res = await fetch("/api/stats/overview", { credentials: "same-origin" });
      const data = await res.json();
      wrap.replaceChildren();
      for (const item of OVERVIEW_ITEMS) {
        const card = el("div", { className: "stats-card" });
        card.append(
          el("div", { className: "stats-card-icon" }, window.kflowIcons.el(item.icon, 18)),
          el("strong", { className: "stats-card-num", textContent: Number(data[item.key] || 0).toLocaleString() }),
          el("span", { className: "stats-card-label", textContent: item.label }),
        );
        wrap.append(card);
      }
    } catch {
      wrap.replaceChildren();
    }
  }

  async function loadBoard() {
    const body = document.querySelector("#statsBody");
    body.replaceChildren();
    body.append(el("tr", {}, el("td", { colSpan: "9", className: "rankings-empty", textContent: "加载中…" })));
    try {
      const res = await fetch(`/api/stats/contributors?period=${state.period}&limit=30`, { credentials: "same-origin" });
      const data = await res.json();
      body.replaceChildren();
      const items = data.items || [];
      if (!items.length) {
        if (state.period !== "all") {
          state.period = "all";
          document.querySelectorAll("#periodTabs .view-tab").forEach((b) =>
            b.classList.toggle("active", b.dataset.period === "all"));
          body.replaceChildren();
          body.append(el("tr", {}, el("td", { colSpan: "9", className: "rankings-empty",
            textContent: "近期暂无贡献数据，已为你切换到总榜…" })));
          return loadBoard();
        }
        body.append(el("tr", {}, el("td", { colSpan: "9", className: "rankings-empty",
          textContent: "还没有贡献数据。发第一帖，点亮整个榜单。" })));
        return;
      }
      for (const row of items) {
        const tr = el("tr");
        tr.append(el("td", {}, el("span", { className: "stats-rank" + (row.rank <= 3 ? ` top${row.rank}` : ""),
          textContent: String(row.rank) })));
        const userCell = el("td");
        const userWrap = el("a", { className: "stats-user", href: `/forum/user/${encodeURIComponent(row.username)}` });
        const avatar = el("span", { className: "stats-avatar" },
          el("strong", { textContent: (row.displayName || "?").slice(0, 1).toUpperCase() }));
        if (row.avatarUrl) {
          const img = document.createElement("img");
          img.src = row.avatarUrl;
          avatar.replaceChildren(img);
        }
        userWrap.append(
          avatar,
          el("span", { className: "stats-user-name" },
            el("strong", { textContent: row.displayName }),
            el("small", { textContent: `@${row.username}` }),
          ),
        );
        userCell.append(userWrap);
        tr.append(userCell);
        tr.append(el("td", { textContent: String(row.topics) }));
        tr.append(el("td", { textContent: String(row.replies) }));
        tr.append(el("td", { textContent: String(row.likes) }));
        tr.append(el("td", { textContent: String(row.contribution) }));
        tr.append(el("td", {}, el("span", { className: "stats-level", textContent: `LV${row.level}` })));
        tr.append(el("td", { textContent: String(row.badges) }));
        tr.append(el("td", {}, el("strong", { className: "stats-score", textContent: String(row.score) })));
        body.append(tr);
      }
    } catch {
      body.replaceChildren();
      body.append(el("tr", {}, el("td", { colSpan: "9", className: "rankings-empty", textContent: "加载失败，请稍后重试。" })));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("#periodTabs .view-tab").forEach((btn) =>
      btn.addEventListener("click", () => {
        document.querySelectorAll("#periodTabs .view-tab").forEach((b) => b.classList.toggle("active", b === btn));
        state.period = btn.dataset.period;
        loadBoard();
      }));
    loadOverview();
    loadBoard();
  });
})();
