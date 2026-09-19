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

  const SOURCE_LABEL = { kaiyuanbang: "开源榜" };

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
    // Switch the OL into the kaiyuanbang-style card layout.
    list.className = "kb-repo-list";
    list.replaceChildren(kbEmpty("加载中…"));
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
        list.append(kbEmpty(emptyReason(state.externalSource, sourceStatus)));
        return;
      }
      items.forEach((p, i) => list.append(renderKbCard(p, i + 1)));
    } catch {
      list.replaceChildren(kbEmpty("榜单加载失败，请稍后重试"));
    }
  }

  function kbEmpty(text) {
    return el("li", { className: "kb-empty", textContent: text });
  }

  function kbAvatar(p, idx) {
    const wrap = el("div", { className: "kb-avatar" });
    const initial =
      (p.title || p.author || "?").trim().slice(0, 1).toUpperCase();
    wrap.textContent = initial;
    return wrap;
  }

  function kbStats(p) {
    const stats = el("div", { className: "kb-stats" });
    const stars = Number(p.stars || 0);
    const forks = Number(p.forks || 0);
    const growth = Number(p.growth_30d || 0);
    stats.append(
      kbStat(iconEl("star", 13), formatInt(stars), "Stars"),
    );
    stats.append(
      kbStat(iconEl("fork", 13), formatInt(forks), "Forks"),
    );
    const growthCls = growth > 0 ? "kb-stat-up" : "";
    stats.append(
      kbStat(
        el("span", { textContent: growth > 0 ? "↗" : "—" }),
        formatInt(Math.abs(growth)),
        "30 日增长",
        growthCls,
      ),
    );
    return stats;
  }

  function kbStat(icon, value, label, valueCls = "") {
    return el(
      "div",
      { className: "kb-stat" },
      el(
        "span",
        { className: "kb-stat-value " + valueCls },
        icon,
        el("span", { textContent: value }),
      ),
      el("span", { className: "kb-stat-label", textContent: label }),
    );
  }

  function renderKbCard(p, idx) {
    const card = el("article", { className: "kb-repo" });

    // 排名
    const rankCls = `kb-rank${idx <= 3 ? ` kb-rank-${idx}` : ""}`;
    card.append(el("div", { className: rankCls, textContent: String(idx) }));

    // 头像
    card.append(kbAvatar(p, idx));

    // 主内容
    const main = el("div", { className: "kb-main" });
    const title = el("a", {
      className: "kb-title",
      href: `/rankings/project/${p.id}`,
      textContent: p.title || p.author || "未命名项目",
    });
    main.append(title);

    // owner/repo
    if (p.author) {
      main.append(el("div", { className: "kb-owner" }, el("bdi", { textContent: p.author })));
    }

    // 描述
    const descText = p.summary || p.description || "";
    if (descText) {
      main.append(el("p", { className: "kb-desc", textContent: descText }));
    }

    // 标签栏：来源 / 主题 / 语言 / 本地解读 / 趋势徽章
    const meta = el("div", { className: "kb-meta" });
    if (p.source) {
      meta.append(el("span", { className: "kb-pill kb-pill-source", textContent: SOURCE_LABEL[p.source] || p.source }));
    }
    if (p.topic) {
      meta.append(el("span", { className: "kb-pill kb-pill-topic", textContent: p.topic }));
    }
    if (p.language) {
      meta.append(el("span", { className: "kb-pill kb-pill-lang", textContent: p.language }));
    }
    if (p.analyzed) {
      meta.append(el("span", { className: "kb-pill kb-pill-ready", textContent: "本地解读" }));
    } else {
      meta.append(el("span", { className: "kb-pill", textContent: "暂无解读" }));
    }
    if (p.trend && TREND_LABEL[p.trend]) {
      meta.append(el("span", { className: `rank-trend-badge trend-${p.trend}`, textContent: TREND_LABEL[p.trend] }));
    }
    for (const tag of (p.tags || []).slice(0, 3)) {
      meta.append(el("span", { className: "kb-pill", textContent: `# ${tag}` }));
    }
    main.append(meta);
    card.append(main);

    // 右侧统计
    card.append(kbStats(p));

    // 创意赞
    const voteBtn = el("button", {
      className: "kb-vote" + (p.voted ? " voted" : ""),
      type: "button",
      textContent: p.voted ? `已赞 ${p.votes}` : `创意赞 ${p.votes || 0}`,
      onclick: () => handleVote(p, voteBtn),
    });
    card.append(voteBtn);

    // 让整个卡片都可点击（除了按钮）
    card.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
      window.location.href = `/rankings/project/${p.id}`;
    });

    return card;
  }

  function formatInt(n) {
    n = Number(n) || 0;
    return n.toLocaleString("en-US");
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
