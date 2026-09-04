(() => {
  // ── state ────────────────────────────────────────────────────────────────
  const state = {
    view: "latest", // latest | hot | featured
    category: "all", // "all" or category slug
    query: "",
    page: 1,
    pageSize: 20,
    total: 0,
    topics: [],
    categories: [],
    stats: {},
    loading: false,
    currentUser: null, // { username, role } or null
  };

  // ── DOM refs (set after DOMContentLoaded) ─────────────────────────────────
  let els = {};

  // ── helpers ───────────────────────────────────────────────────────────────
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "className") node.className = v;
      else if (k === "textContent") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const child of children) {
      if (child == null) continue;
      node.append(
        typeof child === "string" ? document.createTextNode(child) : child,
      );
    }
    return node;
  }

  async function apiFetch(url, opts = {}) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...opts.headers },
      ...opts,
    });
    return res;
  }

  function showToast(msg, type = "info") {
    const toast = document.querySelector("#forum-toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `forum-toast show ${type}`;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      toast.className = "forum-toast";
    }, 3200);
  }

  function getCsrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  // ── fetch current user ────────────────────────────────────────────────────
  async function fetchUser() {
    try {
      const res = await apiFetch("/api/account/me");
      if (!res.ok) return null;
      const data = await res.json();
      if (!data.loggedIn) return null;
      return { username: data.username, role: data.role || "user" };
    } catch {
      return null;
    }
  }

  function renderAccount(user) {
    const accountName = els.accountName;
    const loginLink = els.loginLink;
    const accountLink = els.accountLink;
    const logoutBtn = els.logoutBtn;
    if (!accountName || !accountLink || !loginLink || !logoutBtn) return;

    const loggedIn = Boolean(user);
    accountName.textContent = loggedIn
      ? `${user.role === "admin" ? "管理员" : "用户"}：${user.username}`
      : "";
    accountName.style.display = loggedIn ? "inline-flex" : "none";
    accountLink.textContent = loggedIn
      ? user.role === "admin"
        ? "后台管理"
        : "个人中心"
      : "";
    accountLink.href = user?.role === "admin" ? "/admin" : "/account";
    accountLink.style.display = loggedIn ? "inline-flex" : "none";
    loginLink.style.display = loggedIn ? "none" : "inline-flex";
    logoutBtn.style.display = loggedIn ? "inline-flex" : "none";
    logoutBtn.title = loggedIn ? `${user.username} · 点击退出登录` : "退出登录";
  }

  async function refreshUser() {
    const user = await fetchUser();
    state.currentUser = user;
    renderAccount(user);
    return user;
  }

  async function logout() {
    try {
      const res = await apiFetch("/api/user/logout", { method: "POST" });
      if (!res.ok) throw new Error("logout failed");
      state.currentUser = null;
      renderAccount(null);
      showToast("已退出登录", "info");
    } catch {
      showToast("退出登录失败，请重试", "error");
    }
  }

  // ── fetch categories ──────────────────────────────────────────────────────
  async function fetchCategories() {
    try {
      const res = await apiFetch("/api/forum/categories");
      const data = await res.json();
      return data.categories || [];
    } catch {
      return [];
    }
  }

  // ── fetch stats ───────────────────────────────────────────────────────────
  async function fetchStats() {
    try {
      const res = await apiFetch("/api/forum/stats");
      const data = await res.json();
      return data;
    } catch {
      return {};
    }
  }

  // ── fetch topics ──────────────────────────────────────────────────────────
  async function fetchTopics({ view, category, query, page, pageSize }) {
    const params = new URLSearchParams({
      view,
      page,
      page_size: pageSize,
    });
    if (category && category !== "all") params.set("category", category);
    if (query) params.set("q", query);
    try {
      const res = await apiFetch(`/api/forum/topics?${params}`);
      if (!res.ok) throw new Error("fetch failed");
      return await res.json();
    } catch {
      return { items: [], total: 0, page: 1, has_next: false };
    }
  }

  // ── render categories sidebar ─────────────────────────────────────────────
  function renderCategories(categories, active) {
    const list = els.categoryList;
    if (!list) return;
    list.replaceChildren();

    const allBtn = el("button", {
      className: "category-item" + (active === "all" ? " active" : ""),
      onclick: () => handleCategoryClick("all"),
    });
    const allIcon = el("span", { className: "cat-icon" });
    allIcon.style.background = "#d9232e";
    allIcon.textContent = "全";
    const allLabel = el("span", {
      className: "cat-label",
      textContent: "全部话题",
    });
    const allCount = el("span", {
      className: "cat-count",
      textContent: state.total,
    });
    allBtn.append(allIcon, allLabel, allCount);
    list.append(allBtn);

    for (const cat of categories) {
      const btn = el("button", {
        className: "category-item" + (active === cat.slug ? " active" : ""),
        onclick: () => handleCategoryClick(cat.slug),
      });
      const icon = el("span", { className: "cat-icon" });
      icon.style.background = cat.color || "#657080";
      icon.textContent = cat.icon || "💬";
      const label = el("span", {
        className: "cat-label",
        textContent: cat.name,
      });
      const count = el("span", {
        className: "cat-count",
        textContent: cat.topic_count ?? 0,
      });
      btn.append(icon, label, count);
      list.append(btn);
    }

    // also update mobile horizontal tabs
    renderMobileCategoryTabs(categories, active);
  }

  function renderMobileCategoryTabs(categories, active) {
    const bar = els.mobileCategoryBar;
    if (!bar) return;
    bar.replaceChildren();

    const items = [
      { slug: "all", name: "全部", topic_count: state.total },
      ...categories,
    ];
    for (const cat of items) {
      const btn = el("button", {
        className: "mobile-cat-tab" + (active === cat.slug ? " active" : ""),
        textContent: cat.name,
        onclick: () => handleCategoryClick(cat.slug),
      });
      bar.append(btn);
    }
  }

  // ── render view tabs ──────────────────────────────────────────────────────
  function renderViewTabs(activeView) {
    document.querySelectorAll(".view-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === activeView);
    });
  }

  // ── render topic cards ────────────────────────────────────────────────────
  function renderTopics(topics, total) {
    const feed = els.topicFeed;
    const countEl = els.topicCount;
    const emptyEl = els.emptyState;
    const clearBtn = els.clearFilter;
    if (!feed) return;

    if (countEl) countEl.textContent = `${total} 个话题`;
    const hasFilter =
      state.query || state.category !== "all" || state.view !== "latest";
    if (clearBtn) clearBtn.style.display = hasFilter ? "inline-flex" : "none";

    if (!topics.length) {
      feed.replaceChildren();
      if (emptyEl) emptyEl.style.display = "";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    feed.replaceChildren(...topics.map(buildTopicCard));

    // update load-more button
    const loadMore = els.loadMore;
    if (loadMore)
      loadMore.style.display =
        state.total > state.page * state.pageSize ? "" : "none";
  }

  function buildTopicCard(topic) {
    const card = el("article", { className: "topic-card" });
    if (topic.pinned) card.classList.add("pinned");

    // avatar
    const avatar = el("div", { className: "topic-avatar" });
    avatar.style.background = `linear-gradient(135deg, ${topic.category_color || "#d9232e"}, #333)`;
    avatar.textContent = topic.initials || "?";

    // body
    const body = el("div", { className: "topic-body" });

    // badges row
    const badges = el("div", { className: "topic-badges" });
    if (topic.pinned)
      badges.append(
        el("span", { className: "badge badge-pinned", textContent: "置顶" }),
      );
    if (topic.featured)
      badges.append(
        el("span", { className: "badge badge-featured", textContent: "精华" }),
      );
    badges.append(
      el("span", {
        className: "badge badge-category",
        textContent: topic.category,
      }),
    );

    // title
    const titleEl = el("h3", { className: "topic-title" });
    const titleLink = el("a", {
      className: "topic-title-link",
      href: "#",
      textContent: topic.title,
      onclick: (e) => {
        e.preventDefault();
        openTopicDetail(topic);
      },
    });
    titleEl.append(titleLink);

    // excerpt
    const excerpt = el("p", {
      className: "topic-excerpt",
      textContent: topic.excerpt,
    });

    // meta row
    const meta = el("div", { className: "topic-meta" });
    const authorSpan = el("span", { className: "topic-author" });
    const authorLink = el("a", {
      href: "#",
      textContent: topic.author,
      onclick: (e) => {
        e.preventDefault();
        showToast("用户主页功能即将开放 🚧", "info");
      },
    });
    authorSpan.append(authorLink);

    // tags
    const tagsSpan = el("span", { className: "topic-tags" });
    for (const tag of topic.tags || []) {
      tagsSpan.append(el("span", { className: "tag", textContent: `#${tag}` }));
    }

    const timeSpan = el("span", {
      className: "topic-time",
      textContent: topic.active,
    });
    meta.append(authorSpan, tagsSpan, timeSpan);

    body.append(badges, titleEl, excerpt, meta);

    // stats
    const stats = el("div", { className: "topic-stats" });
    const replyDiv = el("div", { className: "stat-item" });
    replyDiv.append(
      el("span", { className: "stat-num", textContent: topic.replies }),
    );
    replyDiv.append(
      el("span", { className: "stat-label", textContent: "回复" }),
    );

    const viewDiv = el("div", { className: "stat-item" });
    viewDiv.append(
      el("span", {
        className: "stat-num",
        textContent: formatNum(topic.views),
      }),
    );
    viewDiv.append(
      el("span", { className: "stat-label", textContent: "浏览" }),
    );

    // like button
    const likeBtn = el("button", {
      className: "like-btn" + (topic.liked ? " liked" : ""),
      "data-topic-id": topic.id,
      onclick: (e) => handleLike(e, topic),
    });
    const likeCount = el("span", {
      className: "like-count",
      textContent: topic.likes || 0,
    });
    likeBtn.append(
      el("span", { className: "like-icon", textContent: "♥" }),
      likeCount,
    );

    stats.append(replyDiv, viewDiv, likeBtn);
    card.append(avatar, body, stats);
    return card;
  }

  function formatNum(n) {
    n = Number(n) || 0;
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  // ── render stats panel ────────────────────────────────────────────────────
  function renderStats(stats) {
    const memberEl = els.statMembers;
    const topicEl = els.statTopics;
    const replyEl = els.statReplies;
    if (memberEl) memberEl.textContent = formatNum(stats.members ?? 0);
    if (topicEl) topicEl.textContent = formatNum(stats.topics ?? 0);
    if (replyEl) replyEl.textContent = formatNum(stats.replies ?? 0);
  }

  // ── topic detail modal ────────────────────────────────────────────────────
  function openTopicDetail(topic) {
    // fetch full detail (replies) from API
    apiFetch(`/api/forum/topics/${topic.id}`)
      .then((r) => {
        if (!r.ok) throw new Error("fetch failed");
        return r.json();
      })
      .then((data) => {
        const full = data.topic || topic;
        showDetailModal(full);
      })
      .catch(() => showDetailModal(topic));
  }

  function showDetailModal(topic) {
    const modal = els.detailModal;
    if (!modal) return;

    // header
    const titleEl = modal.querySelector(".detail-title");
    if (titleEl) titleEl.textContent = topic.title;

    const metaEl = modal.querySelector(".detail-meta");
    if (metaEl)
      metaEl.textContent = `${topic.author} · ${topic.category} · ${topic.active}`;

    const bodyEl = modal.querySelector(".detail-body");
    if (bodyEl) bodyEl.textContent = topic.content;

    // replies
    const repliesEl = modal.querySelector(".detail-replies");
    if (repliesEl) {
      repliesEl.replaceChildren();
      const replies = topic.replies_detail || [];
      if (replies.length === 0) {
        repliesEl.append(
          el("p", {
            className: "no-replies",
            textContent: "暂无回复，来第一个发言吧！",
          }),
        );
      } else {
        for (const r of replies) {
          const row = el("div", { className: "reply-row" });
          const ava = el("div", {
            className: "reply-avatar",
            textContent: r.initials || "?",
          });
          const rBody = el("div", { className: "reply-body" });
          const rAuthor = el("span", {
            className: "reply-author",
            textContent: r.author,
          });
          const rTime = el("span", {
            className: "reply-time",
            textContent: r.created_at
              ? new Date(r.created_at).toLocaleString("zh-CN")
              : "",
          });
          const rContent = el("p", {
            className: "reply-content",
            textContent: r.content,
          });
          rBody.append(rAuthor, rTime, rContent);
          row.append(ava, rBody);
          repliesEl.append(row);
        }
      }
    }

    // reply form visibility
    const replyForm = modal.querySelector(".reply-form");
    if (replyForm) {
      replyForm.style.display = state.currentUser ? "" : "none";
    }
    const loginHint = modal.querySelector(".reply-login-hint");
    if (loginHint) {
      loginHint.style.display = state.currentUser ? "none" : "";
    }

    modal.dataset.topicId = topic.id;
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeDetailModal() {
    const modal = els.detailModal;
    if (!modal) return;
    modal.classList.remove("open");
    document.body.style.overflow = "";
  }

  // ── new topic modal ───────────────────────────────────────────────────────
  function openNewTopic() {
    if (!state.currentUser) {
      showToast("请先登录后再发帖 🔑", "warn");
      return;
    }
    const modal = els.newTopicModal;
    if (!modal) return;
    modal.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeNewTopicModal() {
    const modal = els.newTopicModal;
    if (!modal) return;
    modal.classList.remove("open");
    document.body.style.overflow = "";
  }

  // ── handle like ───────────────────────────────────────────────────────────
  async function handleLike(e, topic) {
    e.stopPropagation();
    if (!state.currentUser) {
      showToast("请先登录后再点赞 🔑", "warn");
      return;
    }
    const btn = e.currentTarget;
    const countEl = btn.querySelector(".like-count");
    const liked = btn.classList.contains("liked");
    const method = liked ? "DELETE" : "POST";
    try {
      const res = await apiFetch(`/api/forum/topics/${topic.id}/like`, {
        method,
        headers: { "X-CSRFToken": getCsrf() },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) {
          state.currentUser = await refreshUser();
          showToast("登录状态已过期，请重新登录", "warn");
          return;
        }
        showToast(data.error || "操作失败，请重试", "error");
        return;
      }
      const data = await res.json();
      btn.classList.toggle("liked", data.liked);
      if (countEl) countEl.textContent = data.likes;
    } catch {
      showToast("网络错误，请重试", "error");
    }
  }

  // ── submit new topic ──────────────────────────────────────────────────────
  async function submitNewTopic(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const title = form.querySelector("[name=title]")?.value.trim() || "";
    const content = form.querySelector("[name=content]")?.value.trim() || "";
    const categorySlug = form.querySelector("[name=category]")?.value || "";
    const tags = form.querySelector("[name=tags]")?.value.trim() || "";

    if (!title) {
      showToast("标题不能为空", "warn");
      return;
    }
    if (!content) {
      showToast("内容不能为空", "warn");
      return;
    }
    if (!categorySlug) {
      showToast("请选择分类", "warn");
      return;
    }

    const btn = form.querySelector("[type=submit]");
    if (btn) btn.disabled = true;

    try {
      const res = await apiFetch("/api/forum/topics/create", {
        method: "POST",
        headers: { "X-CSRFToken": getCsrf() },
        body: JSON.stringify({ title, content, category: categorySlug, tags }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 401) {
          showToast(data.error || "请先登录后再发帖 🔑", "warn");
          state.currentUser = null;
          return;
        }
        showToast(data.error || "发帖失败，请重试", "error");
        return;
      }
      showToast("发帖成功！🎉", "success");
      closeNewTopicModal();
      form.reset();
      await loadAll();
    } catch {
      showToast("网络错误，请重试", "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ── submit reply ──────────────────────────────────────────────────────────
  async function submitReply(e) {
    e.preventDefault();
    const modal = els.detailModal;
    if (!modal) return;
    const topicId = modal.dataset.topicId;
    const textarea = modal.querySelector(".reply-textarea");
    const content = textarea?.value.trim() || "";
    if (!content) {
      showToast("回复内容不能为空", "warn");
      return;
    }

    const btn = modal.querySelector(".reply-submit");
    if (btn) btn.disabled = true;

    try {
      const res = await apiFetch(`/api/forum/topics/${topicId}/replies`, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrf() },
        body: JSON.stringify({ content }),
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 401) {
          state.currentUser = await refreshUser();
          showToast("登录状态已过期，请重新登录", "warn");
          return;
        }
        showToast(data.error || "回复失败，请重试", "error");
        return;
      }
      showToast("回复成功！✅", "success");
      if (textarea) textarea.value = "";
      // refresh detail
      const topicRes = await apiFetch(`/api/forum/topics/${topicId}`);
      if (!topicRes.ok) throw new Error("detail refresh failed");
      const full = await topicRes.json();
      if (full.topic) showDetailModal(full.topic);
    } catch {
      showToast("网络错误，请重试", "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ── event handlers ────────────────────────────────────────────────────────
  function handleCategoryClick(slug) {
    state.category = slug;
    state.page = 1;
    loadTopics();
    renderCategories(state.categories, slug);
  }

  function handleViewChange(view) {
    state.view = view;
    state.page = 1;
    loadTopics();
    renderViewTabs(view);
  }

  function handleSearch(query) {
    state.query = query;
    state.page = 1;
    clearTimeout(handleSearch._t);
    handleSearch._t = setTimeout(loadTopics, 320);
  }

  function handleClearFilter() {
    state.query = "";
    state.category = "all";
    state.view = "latest";
    state.page = 1;
    if (els.searchInput) els.searchInput.value = "";
    renderViewTabs("latest");
    renderCategories(state.categories, "all");
    loadTopics();
  }

  // ── load / refresh ────────────────────────────────────────────────────────
  async function loadTopics() {
    if (state.loading) return;
    state.loading = true;
    if (els.topicFeed) els.topicFeed.classList.add("loading");

    const data = await fetchTopics({
      view: state.view,
      category: state.category,
      query: state.query,
      page: state.page,
      pageSize: state.pageSize,
    });

    state.topics = data.items || [];
    state.total = data.total || 0;
    renderTopics(state.topics, state.total);
    state.loading = false;
    if (els.topicFeed) els.topicFeed.classList.remove("loading");
  }

  async function loadAll() {
    const [user, cats, statsData] = await Promise.all([
      fetchUser(),
      fetchCategories(),
      fetchStats(),
    ]);
    state.currentUser = user;
    renderAccount(user);
    state.stats = statsData;

    renderStats(statsData);
    await loadTopics();
    // render categories after we know total
    renderCategories(cats, state.category);

    // show/hide new-topic button
    if (els.newTopicBtn) {
      els.newTopicBtn.style.display = "";
    }

    // populate category dropdown in new-topic form
    const sel = document.querySelector("[name=category]");
    if (sel && cats.length) {
      sel.replaceChildren(
        el("option", { value: "", textContent: "选择分类…" }),
      );
      for (const cat of cats) {
        sel.append(el("option", { value: cat.slug, textContent: cat.name }));
      }
    }
  }

  // ── initialise ────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    els = {
      categoryList: document.querySelector("#categoryList"),
      mobileCategoryBar: document.querySelector("#mobileCategoryBar"),
      topicFeed: document.querySelector("#topicFeed"),
      topicCount: document.querySelector("#topicCount"),
      emptyState: document.querySelector("#emptyState"),
      clearFilter: document.querySelector("#clearFilter"),
      searchInput: document.querySelector("#searchInput"),
      loadMore: document.querySelector("#loadMore"),
      newTopicBtn: document.querySelector("#newTopicBtn"),
      loginLink: document.querySelector("#loginLink"),
      accountLink: document.querySelector("#forumAccountLink"),
      logoutBtn: document.querySelector("#forumLogoutBtn"),
      accountName: document.querySelector("#forumAccountName"),
      detailModal: document.querySelector("#topicDetailModal"),
      newTopicModal: document.querySelector("#newTopicModal"),
      statMembers: document.querySelector("#statMembers"),
      statTopics: document.querySelector("#statTopics"),
      statReplies: document.querySelector("#statReplies"),
    };

    // view tabs
    document.querySelectorAll(".view-tab").forEach((btn) => {
      btn.addEventListener("click", () => handleViewChange(btn.dataset.view));
    });

    // search
    if (els.searchInput) {
      els.searchInput.addEventListener("input", (e) =>
        handleSearch(e.target.value.trim()),
      );
    }

    // clear filter
    if (els.clearFilter) {
      els.clearFilter.addEventListener("click", handleClearFilter);
    }

    // account actions
    if (els.logoutBtn) els.logoutBtn.addEventListener("click", logout);

    // new topic button
    if (els.newTopicBtn) {
      els.newTopicBtn.addEventListener("click", openNewTopic);
    }

    // load more
    if (els.loadMore) {
      els.loadMore.addEventListener("click", async () => {
        state.page += 1;
        const data = await fetchTopics({
          view: state.view,
          category: state.category,
          query: state.query,
          page: state.page,
          pageSize: state.pageSize,
        });
        const newTopics = data.items || [];
        state.topics.push(...newTopics);
        state.total = data.total || state.total;
        const feed = els.topicFeed;
        if (feed) feed.append(...newTopics.map(buildTopicCard));
        if (els.loadMore) {
          els.loadMore.style.display =
            state.total > state.page * state.pageSize ? "" : "none";
        }
      });
    }

    // detail modal close
    const closeDetail = document.querySelector("#closeDetailModal");
    if (closeDetail) closeDetail.addEventListener("click", closeDetailModal);
    if (els.detailModal) {
      els.detailModal.addEventListener("click", (e) => {
        if (e.target === els.detailModal) closeDetailModal();
      });
    }

    // reply form
    const replyForm = document.querySelector("#replyForm");
    if (replyForm) replyForm.addEventListener("submit", submitReply);

    // new topic modal close
    const closeNew = document.querySelector("#closeNewTopicModal");
    if (closeNew) closeNew.addEventListener("click", closeNewTopicModal);
    if (els.newTopicModal) {
      els.newTopicModal.addEventListener("click", (e) => {
        if (e.target === els.newTopicModal) closeNewTopicModal();
      });
    }

    // new topic form submit
    const newTopicForm = document.querySelector("#newTopicForm");
    if (newTopicForm) newTopicForm.addEventListener("submit", submitNewTopic);

    // keyboard: / to focus search, Esc to close modals
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (els.detailModal?.classList.contains("open")) {
          closeDetailModal();
          return;
        }
        if (els.newTopicModal?.classList.contains("open")) {
          closeNewTopicModal();
          return;
        }
      }
      if (
        e.key === "/" &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA"
      ) {
        e.preventDefault();
        els.searchInput?.focus();
      }
    });

    loadAll();
  });
})();
