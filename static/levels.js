(() => {
  const METRIC_LABEL = {
    active_days: "活跃天数",
    topics: "发帖数",
    replies: "评论数",
    likes_received: "获赞数",
    contribution: "贡献分",
  };

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

  function renderMyCard(my) {
    const card = document.querySelector("#myLevelCard");
    if (!my) {
      card.style.display = "none";
      return;
    }
    card.style.display = "";
    card.replaceChildren();
    const left = el("div", { className: "level-my-left" });
    const medal = el("div", { className: "level-my-medal" }, el("strong", { textContent: `LV${my.level}` }));
    left.append(medal);
    const right = el("div", { className: "level-my-right" });
    right.append(
      el("div", { className: "level-my-title" },
        el("h2", { textContent: my.name }),
        el("span", { className: "level-my-contrib", textContent: `贡献分 ${my.contribution}` }),
      ),
    );
    if (my.progress) {
      const bars = el("div", { className: "level-progress" });
      for (const part of my.progress.parts) {
        const pct = Math.min(100, Math.round((part.value / Math.max(1, part.threshold)) * 100));
        const row = el("div", { className: "level-progress-row" });
        row.append(
          el("span", { className: "level-progress-label", textContent: METRIC_LABEL[part.key] || part.key }),
          el("div", { className: "level-progress-track" },
            el("div", { className: "level-progress-fill", style: `width:${pct}%` }),
          ),
          el("span", { className: "level-progress-num" + (part.done ? " done" : ""),
            textContent: part.done ? "已完成" : `${part.value} / ${part.threshold}` }),
        );
        bars.append(row);
      }
      right.append(el("p", { className: "level-progress-title",
        textContent: `距离 LV${my.progress.nextLevel} ${my.progress.nextName}` }), bars);
    } else {
      right.append(el("p", { className: "level-progress-title", textContent: "已是最高等级，感谢你对社区的贡献。" }));
    }
    card.append(left, right);
  }

  function renderLadder(levels, myLevel) {
    const ladder = document.querySelector("#levelLadder");
    ladder.replaceChildren(
      el("div", { className: "profile-section-heading" },
        el("h2", { textContent: "等级阶梯" }),
        el("span", { textContent: "每小时自动重算，只升不降" }),
      ),
    );
    const list = el("div", { className: "level-ladder-list" });
    for (const entry of levels) {
      const isCurrent = myLevel != null && entry.level === myLevel;
      const row = el("article", { className: "level-row" + (isCurrent ? " current" : "") });
      row.append(el("div", { className: "level-row-badge" }, el("strong", { textContent: `LV${entry.level}` })));
      const body = el("div", { className: "level-row-body" });
      body.append(
        el("div", { className: "level-row-head" },
          el("h3", { textContent: entry.name }),
          isCurrent ? el("span", { className: "badge-earned-chip", textContent: "当前等级" }) : null,
        ),
        el("p", { className: "level-row-req", textContent: `升级条件：${entry.requirements_text}` }),
      );
      const perks = el("ul", { className: "level-row-perks" });
      for (const perk of entry.perks || []) perks.append(el("li", { textContent: perk }));
      body.append(perks);
      row.append(body);
      list.append(row);
    }
    ladder.append(list);
  }

  async function init() {
    try {
      const res = await fetch("/api/levels", { credentials: "same-origin" });
      const data = await res.json();
      renderMyCard(data.my);
      renderLadder(data.levels || [], data.my ? data.my.level : null);
    } catch {
      document.querySelector("#levelLadder").replaceChildren(
        el("p", { className: "rankings-empty", textContent: "等级数据加载失败，请稍后重试。" }),
      );
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
