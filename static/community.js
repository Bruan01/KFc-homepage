/* KFlow community portal (new homepage). Reuses forum API payloads. */
(() => {
  const state = {
    view: "latest",
    page: 1,
    pageSize: 10,
    total: 0,
    loading: false,
    currentUser: null,
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



  function avatarEl(profile) {
    const span = el("span", { className: "row-user-avatar" });
    const initial = (profile?.display_name || profile?.username || "?").slice(0, 1).toUpperCase();
    if (profile?.avatar_url) {
      const img = document.createElement("img");
      img.src = profile.avatar_url;
      img.alt = "";
      img.addEventListener("error", () => span.replaceChildren(initial));
      span.append(img);
    } else {
      span.textContent = initial;
    }
    return span;
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

  const LINK_BADGE = { github: "GitHub", gitee: "Gitee", live: "在线体验", other: "链接" };

  function buildTopicCard(topic) {
    const row = el("article", {
      className: "topic-row" + (topic.pinned ? " pinned" : ""),
    });

    const main = el("div", { className: "row-main" });
    const titleLine = el("div", { className: "row-title-line" });
    if (topic.pinned) titleLine.append(el("span", { className: "row-pin" }, iconEl("pin", 13)));
    titleLine.append(
      el("a", {
        className: "row-title",
        href: `/forum?topic=${topic.id}`,
        textContent: topic.title,
      }),
    );
    if (topic.boosted) {
      titleLine.append(
        el("span", { className: "row-badge badge-boost" }, iconEl("flame", 11), "加热"),
      );
    }
    if (topic.featured) {
      titleLine.append(
        el("span", { className: "row-badge badge-featured" }, iconEl("star", 11), "精华"),
      );
    }

    const meta = el("div", { className: "row-meta" });
    const catChip = el("span", { className: "cat-chip", textContent: topic.category });
    const catDot = el("span", { className: "cat-icon" });
    catDot.style.background = topic.category_color || "#8b9199";
    catChip.prepend(catDot);
    meta.append(catChip);
    for (const link of (topic.links || []).slice(0, 3)) {
      meta.append(
        el("a", {
          className: `row-link link-${link.type}`,
          href: link.url,
          target: "_blank",
          rel: "noopener nofollow",
          textContent: `↗ ${link.name || LINK_BADGE[link.type] || "链接"}`,
        }),
      );
    }
    if ((topic.images || []).length) {
      meta.append(
        el("span", { className: "tag-chip" }, iconEl("camera", 11), ` ${topic.images.length}`),
      );
    }

    const authorLine = el("div", { className: "row-author" });
    const identity = topic.author_profile || { display_name: topic.author, username: topic.author };
    authorLine.append(
      avatarEl(identity),
      el("a", {
        href: `/forum/user/${encodeURIComponent(identity.username || topic.author)}`,
        textContent: identity.display_name || topic.author,
      }),
      el("span", { className: "time", textContent: `· ${topic.active}` }),
    );

    main.append(titleLine, meta, authorLine);

    const likeBtn = el("button", {
      className: "like-btn" + (topic.liked ? " liked" : ""),
      type: "button",
      title: "点赞（登录后可用）",
      onclick: (e) => {
        e.stopPropagation();
        window.location.href = `/forum?topic=${topic.id}`;
      },
    });
    likeBtn.append(
      iconEl("heart", 14),
      el("span", { className: "like-count", textContent: topic.likes || 0 }),
    );
    const likeCol = el("div", { className: "row-num like" }, likeBtn);
    const repliesCol = el("div", { className: "row-num replies", title: "回复" },
      iconEl("bubble", 13),
      el("strong", { textContent: topic.replies || 0 }));
    const viewsHot = (topic.views || 0) >= 1000 ? " views-hot" : "";
    const viewsCol = el("div", { className: `row-num views${viewsHot}`, title: "浏览" },
      iconEl("eye", 13),
      el("strong", { textContent: formatNum(topic.views) }));
    const activityCol = el("div", { className: "row-num activity", textContent: topic.active });

    row.append(main, likeCol, repliesCol, viewsCol, activityCol);
    return row;
  }

  async function loadTopics() {
    if (state.loading) return;
    state.loading = true;
    const feed = document.querySelector("#communityFeed");
    feed && feed.classList.add("loading");
    const params = new URLSearchParams({ view: state.view, page: state.page, page_size: state.pageSize });
    try {
      const res = await apiFetch(`/api/forum/topics?${params}`);
      const data = await res.json();
      const items = data.items || [];
      state.total = data.total || 0;
      if (state.page === 1) feed.replaceChildren();
      if (!items.length && state.page === 1) {
        feed.append(el("div", { className: "empty-state", style: "display:block" },
          el("div", { className: "empty-icon" }, iconEl("pencil", 30)),
          el("p", { textContent: "还没有作品，第一帖就是你的了！" })));
      }
      feed.append(...items.map((topic, index) => {
        const card = buildTopicCard(topic);
        card.style.animationDelay = `${Math.min(index * 40, 400)}ms`;
        return card;
      }));
      document.querySelector("#communityLoadMore").style.display =
        state.total > state.page * state.pageSize ? "" : "none";
    } catch {
      /* keep feed quiet */
    } finally {
      state.loading = false;
      feed && feed.classList.remove("loading");
    }
  }

  async function renderRankList(containerId, url, buildItem, emptyText) {
    const list = document.querySelector(containerId);
    try {
      const res = await apiFetch(url);
      const data = await res.json();
      const items = data.items || [];
      list.replaceChildren();
      if (!items.length) {
        list.append(el("li", { className: "rank-empty", textContent: emptyText }));
        return;
      }
      for (const item of items.slice(0, 8)) list.append(buildItem(item));
    } catch {
      list.replaceChildren(el("li", { className: "rank-empty", textContent: "数据加载失败" }));
    }
  }

  function rankItem(text, href, metric) {
    const li = el("li");
    li.append(el("a", { href, textContent: text, title: text }));
    if (metric != null) {
      const span = el("span", { className: "rank-metric" });
      span.append(metric.nodeType ? metric : document.createTextNode(metric));
      li.append(span);
    }
    return li;
  }

  async function loadSidebar() {
    await Promise.all([
      renderRankList("#externalRank", "/api/rankings/external?limit=8",
        (p) => rankItem(p.title, p.url, p.metrics?.stars != null ? `★ ${formatNum(p.metrics.stars)}` : p.metrics?.upvotes != null ? `▲ ${p.metrics.upvotes}` : formatNum(p.heat_score)),
        "暂无数据，等待抓取任务运行。"),
      renderRankList("#siteRank", "/api/rankings/site?period=weekly&limit=8",
        (t) => {
          const wrap = document.createDocumentFragment();
          wrap.append(iconEl("flame", 11), document.createTextNode(` ${formatNum(t.hot_score)}`));
          return rankItem(t.title, `/forum?topic=${t.id}`, wrap);
        },
        "还没有作品，来发第一帖！"),
      renderRankList("#creatorRank", "/api/rankings/creators?limit=8",
        (u) => rankItem(u.display_name, `/forum/user/${encodeURIComponent(u.username)}`, `${formatNum(u.contribution_score)}分`),
        "发帖、点赞、评论即可上榜。"),
      (async () => {
        const list = document.querySelector("#tutorialMini");
        try {
          const res = await apiFetch("/api/learn/tutorials");
          const data = await res.json();
          list.replaceChildren();
          for (const t of (data.items || []).slice(0, 4)) {
            const li = el("li");
            li.append(el("a", { href: `/tutorials/${t.slug}`, textContent: t.title }));
            li.append(el("span", { className: "tut-meta", textContent: `${t.reading_minutes}min` }));
            list.append(li);
          }
          if (!list.children.length) list.append(el("li", { className: "rank-empty", textContent: "教程整理中" }));
        } catch { /* keep placeholder */ }
      })(),
      (async () => {
        const list = document.querySelector("#glossaryMini");
        try {
          const res = await apiFetch("/api/learn/glossary");
          const data = await res.json();
          const items = (data.items || []).sort(() => Math.random() - 0.5).slice(0, 3);
          list.replaceChildren();
          for (const g of items) {
            const li = el("li");
            li.append(el("span", { className: "gloss-term", textContent: g.term }));
            li.append(el("span", { className: "gloss-en", textContent: g.en }));
            li.title = g.definition;
            list.append(li);
          }
          if (!list.children.length) list.append(el("li", { className: "rank-empty", textContent: "术语整理中" }));
        } catch { /* keep placeholder */ }
      })(),
    ]);
  }

  async function loadStats() {
    try {
      const res = await apiFetch("/api/forum/stats");
      const data = await res.json();
      document.querySelector("#statMembers").textContent = formatNum(data.members ?? 0);
      document.querySelector("#statTopics").textContent = formatNum(data.topics ?? 0);
      document.querySelector("#statReplies").textContent = formatNum(data.replies ?? 0);
    } catch { /* ignore */ }
  }

  async function loadUser() {
    // 头部由 header.js 渲染；这里仅同步登录态供交互判断
    try {
      const res = await apiFetch("/api/account/me");
      const data = await res.json();
      state.currentUser = data.loggedIn ? { username: data.username, role: data.role } : null;
    } catch { state.currentUser = null; }
  }

  function bindEvents() {
    document.querySelectorAll(".view-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".view-tab").forEach((b) => b.classList.toggle("active", b === btn));
        state.view = btn.dataset.view;
        state.page = 1;
        loadTopics();
      });
    });
    document.querySelector("#communityLoadMore").addEventListener("click", () => {
      state.page += 1;
      loadTopics();
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    await Promise.all([loadUser(), loadStats()]);
    loadTopics();
    loadSidebar();
  });
})();
