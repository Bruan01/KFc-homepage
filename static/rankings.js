/* KFlow rankings page: site / external / creators boards. */
(() => {
  const state = { tab: "site", sitePeriod: "weekly", externalSource: "all" };
  let loggedIn = false;

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


  function iconEl(name, size) {
    return window.kflowIcons ? window.kflowIcons.el(name, size) : document.createElement("span");
  }
  function showToast(msg, type = "info") {
    const toast = document.querySelector("#forum-toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `forum-toast show ${type}`;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
  }

  async function apiFetch(url, opts = {}) {
    return fetch(url, { credentials: "same-origin", headers: { "Content-Type": "application/json", ...opts.headers }, ...opts });
  }

  function formatNum(n) {
    n = Number(n) || 0;
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  const SOURCE_LABEL = { github: "GitHub", producthunt: "PH", cn_community: "中文社区" };

  function empty(text) {
    return el("li", { className: "rankings-empty", textContent: text });
  }

  async function loadSite() {
    const list = document.querySelector("#siteList");
    list.replaceChildren(empty("加载中…"));
    try {
      const res = await apiFetch(`/api/rankings/site?period=${state.sitePeriod}&limit=50`);
      const data = await res.json();
      list.replaceChildren();
      const items = data.items || [];
      if (!items.length) {
        if (state.sitePeriod !== "all") {
          // selected window has no works yet — fall back to the all-time board
          state.sitePeriod = "all";
          document.querySelectorAll("#sitePeriods .subtab").forEach((b) =>
            b.classList.toggle("active", b.dataset.period === "all"));
          list.replaceChildren(empty("近期暂无新作品，已为你切换到总榜…"));
          return loadSite();
        }
        list.append(empty("还没有作品上榜。去社区发第一帖，你就是第一名。"));
        return;
      }
      for (const t of items) {
        const li = el("li");
        if (t.cover) {
          li.append(el("img", { className: "rank-cover", src: t.cover, alt: "", loading: "lazy" }));
        }
        const main = el("div", { className: "rank-main" });
        main.append(el("a", { className: "rank-title", href: `/forum?topic=${t.id}`, textContent: t.title }));
        main.append(el("span", { className: "rank-desc", textContent: `@${t.author} · ${t.category}` }));
        li.append(main);
        const metrics = el("div", { className: "rank-metrics" });
        metrics.append(el("span", { className: "metric-hot" }, iconEl("flame", 12), ` ${formatNum(t.hot_score)}`));
        metrics.append(el("span", { className: "rank-m" }, iconEl("heart", 12), ` ${formatNum(t.likes)}`));
        metrics.append(el("span", { className: "rank-m" }, iconEl("bubble", 12), ` ${formatNum(t.replies)}`));
        metrics.append(el("span", { className: "rank-m" }, iconEl("eye", 12), ` ${formatNum(t.views)}`));
        li.append(metrics);
        list.append(li);
      }
    } catch {
      list.replaceChildren(empty("榜单加载失败，请稍后重试"));
    }
  }

  const TREND_LABEL = { hot: "爆发", rising: "上升", steady: "平稳", cooling: "降温", fresh: "新上榜" };

  async function loadTrends() {
    const host = document.querySelector("#trendsCard");
    if (!host) return;
    try {
      const res = await apiFetch("/api/rankings/trends?days=7");
      const data = await res.json();
      host.replaceChildren();
      if (!data.tags?.length) {
        host.style.display = "none";
        return;
      }
      host.append(el("div", { className: "trend-hot-head" }, iconEl("flame", 14), " 热点趋势（近 7 天标签热度增量）"));
      const tagRow = el("div", { className: "trend-hot-tags" });
      for (const t of data.tags.slice(0, 8)) {
        const deltaText = t.delta > 0 ? `+${formatNum(t.delta)}` : formatNum(t.delta);
        tagRow.append(el("span", { className: "trend-hot-tag" },
          `# ${t.tag}`,
          el("span", { className: "delta", textContent: deltaText }),
        ));
      }
      host.append(tagRow);
      if (data.prediction) {
        host.append(el("p", { className: "trend-prediction", textContent: data.prediction }));
      }
      host.style.display = "";
    } catch {
      host.style.display = "none";
    }
  }

  async function loadExternal() {
    const list = document.querySelector("#externalList");
    list.replaceChildren(empty("加载中…"));
    try {
      const res = await apiFetch(`/api/rankings/external?source=${state.externalSource}&limit=50`);
      const data = await res.json();
      list.replaceChildren();
      const items = data.items || [];
      const sourceStatus = {};
      for (const s of data.sources || []) sourceStatus[s.source] = s;
      if (data.updated_at) {
        document.querySelector("#externalUpdated").textContent =
          `数据更新于 ${new Date(data.updated_at).toLocaleString("zh-CN")} · 抓取任务每日运行 · 点击标题查看概括与剖析`;
      }
      if (!items.length) {
        list.append(empty(emptyReason(state.externalSource, sourceStatus)));
        return;
      }
      for (const p of items) {
        const li = el("li");
        const main = el("div", { className: "rank-main" });
        main.append(el("a", { className: "rank-title", href: `/rankings/project/${p.id}`, textContent: p.title }));
        if (p.summary) {
          main.append(el("span", { className: "rank-desc", textContent: p.summary }));
        } else if (p.description) {
          main.append(el("span", { className: "rank-desc", textContent: p.description }));
        }
        // 标签 + 趋势徽章
        if ((p.tags || []).length || p.trend) {
          const tagRow = el("div", { className: "rank-row-tags" });
          if (p.trend && TREND_LABEL[p.trend]) {
            tagRow.append(el("span", { className: `rank-trend-badge trend-${p.trend}`, textContent: TREND_LABEL[p.trend] }));
          }
          for (const tag of (p.tags || []).slice(0, 4)) {
            tagRow.append(el("span", { className: "rank-row-tag", textContent: `# ${tag}` }));
          }
          main.append(tagRow);
        }
        li.append(main);
        li.append(el("span", { className: "rank-source", textContent: SOURCE_LABEL[p.source] || p.source }));
        const metrics = el("div", { className: "rank-metrics" });
        if (p.metrics?.stars != null) metrics.append(el("span", { className: "rank-m" }, iconEl("star", 12), ` ${formatNum(p.metrics.stars)}`));
        if (p.metrics?.forks != null) metrics.append(el("span", { className: "rank-m" }, iconEl("fork", 12), ` ${formatNum(p.metrics.forks)}`));
        if (p.metrics?.upvotes != null) metrics.append(el("span", { className: "rank-m" }, iconEl("up", 12), ` ${formatNum(p.metrics.upvotes)}`));
        if (p.metrics?.replies != null) metrics.append(el("span", { className: "rank-m" }, iconEl("bubble", 12), ` ${formatNum(p.metrics.replies)}`));
        metrics.append(el("span", { className: "metric-hot" }, iconEl("flame", 12), ` ${formatNum(p.heat_score)}`));
        li.append(metrics);
        const voteBtn = el("button", {
          className: "vote-btn" + (p.voted ? " voted" : ""),
          type: "button",
          textContent: p.voted ? `已赞 ${p.votes}` : `创意赞 ${p.votes}`,
          onclick: () => handleVote(p, voteBtn),
        });
        li.append(voteBtn);
        list.append(li);
      }
    } catch {
      list.replaceChildren(empty("榜单加载失败，请稍后重试"));
    }
  }

  function emptyReason(source, statusMap) {
    if (source === "all") {
      return "暂无数据。全网榜由抓取任务每日自动更新，首次运行前为空。";
    }
    const status = statusMap[source];
    if (!status || status.status === "never") {
      return "该数据源还没有运行过抓取任务（抓取任务每日自动运行，也可在服务器手动执行 manage.py crawl_external）。";
    }
    if (status.status === "failed") {
      return `该数据源上次抓取失败：${status.message || "未知原因"}。会保留上次成功数据，失败时为空说明从未成功过。`;
    }
    if (status.message && /未配置|跳过/.test(status.message)) {
      return `该数据源已跳过：${status.message}`;
    }
    if (status.status === "success" && status.count === 0) {
      return "该数据源抓取成功但没有返回条目，可能接口结构变化或内容为空。";
    }
    return "该数据源暂无上榜数据。";
  }

  async function handleVote(project, btn) {
    if (!loggedIn) {
      showToast("请先登录后再投票", "warn");
      return;
    }
    if (btn.classList.contains("voted")) return;
    try {
      const res = await apiFetch(`/api/rankings/external/${project.id}/vote`, {
        method: "POST",
        headers: { "X-CSRFToken": csrf() },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.error || "投票失败", "error");
        return;
      }
      btn.classList.add("voted");
      btn.textContent = `已赞 ${data.votes}`;
      showToast("已为该项目投出创意赞", "success");
      if (data.newBadges?.length && window.kflowCelebrate) window.kflowCelebrate.badges(data.newBadges);
    } catch {
      showToast("网络错误，请重试", "error");
    }
  }

  async function loadCreators() {
    const list = document.querySelector("#creatorList");
    list.replaceChildren(empty("加载中…"));
    try {
      const res = await apiFetch("/api/rankings/creators?limit=50");
      const data = await res.json();
      list.replaceChildren();
      const items = data.items || [];
      if (!items.length) {
        list.append(empty("还没有创作者上榜。发帖、点赞、评论即可积累贡献分。"));
        return;
      }
      for (const u of items) {
        const li = el("li");
        const avatar = el("span", { className: "rank-creator", textContent: (u.display_name || "?").slice(0, 1).toUpperCase() });
        if (u.avatar_url) {
          const img = el("img", { src: u.avatar_url, alt: "" });
          avatar.replaceChildren(img);
        }
        li.append(avatar);
        const main = el("div", { className: "rank-main" });
        main.append(el("a", { className: "rank-title", href: `/forum/user/${encodeURIComponent(u.username)}`, textContent: u.display_name }));
        main.append(el("span", { className: "rank-desc", textContent: `@${u.username} · ${u.topic_count} 个作品` }));
        li.append(main);
        const metrics = el("div", { className: "rank-metrics" });
        metrics.append(el("span", { textContent: `LV${u.reputation_level}` }));
        metrics.append(el("span", { className: "metric-hot", textContent: `${formatNum(u.contribution_score)} 贡献分` }));
        li.append(metrics);
        list.append(li);
      }
    } catch {
      list.replaceChildren(empty("榜单加载失败，请稍后重试"));
    }
  }

  function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".rankings-tabs .view-tab").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === tab));
    for (const name of ["site", "external", "creators"]) {
      document.querySelector(`#panel-${name}`).style.display = name === tab ? "" : "none";
    }
    if (tab === "site") loadSite();
    if (tab === "external") { loadExternal(); loadTrends(); }
    if (tab === "creators") loadCreators();
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document.querySelectorAll(".rankings-tabs .view-tab").forEach((btn) =>
      btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
    document.querySelectorAll("#sitePeriods .subtab").forEach((btn) =>
      btn.addEventListener("click", () => {
        document.querySelectorAll("#sitePeriods .subtab").forEach((b) => b.classList.toggle("active", b === btn));
        state.sitePeriod = btn.dataset.period;
        loadSite();
      }));
    document.querySelectorAll("#externalSources .subtab").forEach((btn) =>
      btn.addEventListener("click", () => {
        document.querySelectorAll("#externalSources .subtab").forEach((b) => b.classList.toggle("active", b === btn));
        state.externalSource = btn.dataset.source;
        loadExternal();
      }));

    try {
      const res = await apiFetch("/api/account/me");
      const data = await res.json();
      loggedIn = Boolean(data.loggedIn);
    } catch { loggedIn = false; }

    // sync the default period with whichever pill is marked active in HTML
    const activePeriod = document.querySelector("#sitePeriods .subtab.active");
    if (activePeriod) state.sitePeriod = activePeriod.dataset.period;

    const params = new URLSearchParams(location.search);
    const tab = params.get("tab");
    switchTab(["site", "external", "creators"].includes(tab) ? tab : "site");
  });
})();
