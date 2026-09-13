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

  // ── Markdown renderer ─────────────────────────────────────────────────────
  // Raw HTML is escaped before Markdown formatting is applied. Links only
  // accept HTTPS URLs so user-authored content cannot inject scripts.
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderInlineMarkdown(value) {
    const segments = String(value ?? "").split(/(`[^`\n]+`)/g);
    return segments
      .map((segment) => {
        if (/^`[^`\n]+`$/.test(segment)) {
          return `<code>${escapeHtml(segment.slice(1, -1))}</code>`;
        }
        return escapeHtml(segment)
          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/\*(.+?)\*/g, "<em>$1</em>")
          .replace(/~~(.+?)~~/g, "<del>$1</del>")
          .replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
          );
      })
      .join("");
  }

  function renderMarkdown(value) {
    const lines = String(value ?? "")
      .replace(/\r/g, "")
      .split("\n");
    const output = [];
    let paragraph = [];
    let listType = "";
    let listItems = [];
    let codeLines = [];
    let codeLanguage = "";
    let inCode = false;

    function flushParagraph() {
      if (!paragraph.length) return;
      output.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
      paragraph = [];
    }

    function flushList() {
      if (!listType || !listItems.length) return;
      output.push(
        `<${listType}>${listItems
          .map((item) => `<li>${renderInlineMarkdown(item)}</li>`)
          .join("")}</${listType}>`,
      );
      listType = "";
      listItems = [];
    }

    function flushCode() {
      if (!codeLines.length) return;
      const language = escapeHtml(codeLanguage || "text");
      output.push(
        `<div class="forum-code-block"><div class="forum-code-label">${language}</div><pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre></div>`,
      );
      codeLines = [];
      codeLanguage = "";
    }

    function tableCells(line) {
      return line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim());
    }

    function renderTable(header, rows) {
      const head = header
        .map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`)
        .join("");
      const body = rows
        .map(
          (row) =>
            `<tr>${header
              .map(
                (_, index) =>
                  `<td>${renderInlineMarkdown(row[index] || "")}</td>`,
              )
              .join("")}</tr>`,
        )
        .join("");
      output.push(
        `<div class="forum-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`,
      );
    }

    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (line.startsWith("```")) {
        if (inCode) flushCode();
        else {
          flushParagraph();
          flushList();
          codeLanguage = line.slice(3).trim();
        }
        inCode = !inCode;
        index += 1;
        continue;
      }
      if (inCode) {
        codeLines.push(line);
        index += 1;
        continue;
      }

      const nextLine = lines[index + 1] || "";
      if (
        line.trim().startsWith("|") &&
        line.trim().endsWith("|") &&
        /^\|[\s\-:|]+\|$/.test(nextLine.trim())
      ) {
        flushParagraph();
        flushList();
        const header = tableCells(line);
        const rows = [];
        index += 2;
        while (index < lines.length) {
          const row = lines[index];
          if (!(row.trim().startsWith("|") && row.trim().endsWith("|"))) break;
          rows.push(tableCells(row));
          index += 1;
        }
        renderTable(header, rows);
        continue;
      }

      const unordered = line.match(/^\s*[-*]\s+(.+)/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.+)/);
      if (unordered || ordered) {
        flushParagraph();
        const nextType = unordered ? "ul" : "ol";
        if (listType && listType !== nextType) flushList();
        listType = nextType;
        listItems.push((unordered || ordered)[1]);
        index += 1;
        continue;
      }
      flushList();

      const heading = line.match(/^(#{1,6})\s+(.+)/);
      if (heading) {
        flushParagraph();
        const level = Math.min(6, heading[1].length);
        output.push(
          `<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`,
        );
        index += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        flushParagraph();
        output.push(
          `<blockquote>${renderInlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`,
        );
        index += 1;
        continue;
      }
      if (/^[-*_]{3,}\s*$/.test(line)) {
        flushParagraph();
        output.push("<hr>");
        index += 1;
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        index += 1;
        continue;
      }
      paragraph.push(line);
      index += 1;
    }

    flushParagraph();
    flushList();
    if (inCode) flushCode();
    return output.join("") || "<p></p>";
  }


  // ── 线性图标（复用全局 kflowIcons）──

  function avatarEl(profile, size) {
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
  function setRenderedMarkdown(container, value) {
    container.replaceChildren();
    const parsed = new DOMParser().parseFromString(
      renderMarkdown(value),
      "text/html",
    );
    while (parsed.body.firstElementChild) {
      container.append(parsed.body.firstElementChild);
    }
  }

  function setupMarkdownEditors() {
    for (const editor of document.querySelectorAll("[data-markdown-editor]")) {
      const textarea = editor.querySelector("textarea");
      const preview = editor.querySelector("[data-markdown-preview]");
      const toggle = editor.querySelector("[data-markdown-toggle]");
      if (!textarea || !preview || !toggle) continue;

      const updatePreview = () => {
        setRenderedMarkdown(preview, textarea.value);
      };
      toggle.addEventListener("click", () => {
        const isPreview = editor.classList.toggle("is-preview");
        toggle.textContent = isPreview ? "编辑" : "预览";
        toggle.setAttribute("aria-pressed", String(isPreview));
        if (isPreview) updatePreview();
      });
      textarea.addEventListener("input", () => {
        if (editor.classList.contains("is-preview")) updatePreview();
      });
    }
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

  function renderAccount() {
    // 头部账户区由共享的 header.js 统一渲染，这里仅维护 state.currentUser
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
      icon.textContent = cat.icon || "";
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

    feed.replaceChildren(...topics.map((topic, index) => {
      const card = buildTopicCard(topic);
      card.style.animationDelay = `${Math.min(index * 40, 400)}ms`;
      return card;
    }));

    // update load-more button
    const loadMore = els.loadMore;
    if (loadMore)
      loadMore.style.display =
        state.total > state.page * state.pageSize ? "" : "none";
  }

  const LINK_BADGE = { github: "GitHub", gitee: "Gitee", live: "在线体验", other: "链接" };

  function buildTopicCard(topic) {
    const row = el("article", {
      className: "topic-row" + (topic.pinned ? " pinned" : ""),
    });

    // ── main column: title + meta ──
    const main = el("div", { className: "row-main" });

    const titleLine = el("div", { className: "row-title-line" });
    if (topic.pinned) {
      const pin = iconEl("pin", 13);
      pin.setAttribute("title", "置顶");
      titleLine.append(el("span", { className: "row-pin" }, pin));
    }
    titleLine.append(
      el("a", {
        className: "row-title",
        href: "#",
        textContent: topic.title,
        onclick: (e) => {
          e.preventDefault();
          openTopicDetail(topic);
        },
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
    // category chip with colored square (Discourse style)
    const catChip = el("a", {
      className: "cat-chip",
      href: "#",
      textContent: topic.category,
      title: `浏览 ${topic.category} 分类`,
      onclick: (e) => {
        e.preventDefault();
        handleCategoryClick(topic.category_slug);
      },
    });
    const catDot = el("span", { className: "cat-icon" });
    catDot.style.background = topic.category_color || "#8b9199";
    catChip.prepend(catDot);
    meta.append(catChip);
    // tags
    for (const tag of (topic.tags || []).slice(0, 4)) {
      meta.append(
        el("a", {
          className: "tag-chip",
          href: "#",
          textContent: tag,
          onclick: (e) => {
            e.preventDefault();
            if (els.searchInput) {
              els.searchInput.value = tag;
              handleSearch(tag);
            }
          },
        }),
      );
    }
    // project links
    for (const link of (topic.links || []).slice(0, 3)) {
      meta.append(
        el("a", {
          className: `row-link link-${link.type}`,
          href: link.url,
          target: "_blank",
          rel: "noopener nofollow",
          textContent: `↗ ${link.name || LINK_BADGE[link.type] || "链接"}`,
          onclick: (e) => e.stopPropagation(),
        }),
      );
    }
    if ((topic.images || []).length) {
      meta.append(
        el("span", { className: "tag-chip" }, iconEl("camera", 11), ` ${topic.images.length}`),
      );
    }

    const authorLine = el("div", { className: "row-author" });
    const identity = topic.author_profile || {
      display_name: topic.author,
      username: topic.author,
    };
    authorLine.append(
      avatarEl(identity),
      el("a", {
        href: `/forum/user/${encodeURIComponent(identity.username || topic.author)}`,
        textContent: identity.display_name || topic.author,
      }),
    );
    if (identity.showcase) {
      const chip = el("a", {
        className: `showcase-chip tier-${identity.showcase.tier}`,
        href: "/achievements",
        title: `佩戴勋章：${identity.showcase.name}`,
      });
      chip.append(iconEl(identity.showcase.icon, 10), el("span", { textContent: identity.showcase.name }));
      authorLine.append(chip);
    }
    authorLine.append(
      el("span", { className: "time", textContent: `· ${topic.active}` }),
    );

    main.append(titleLine, meta, authorLine);

    // ── numeric columns: 赞 / 回复 / 浏览 / 活动 ──
    const likeBtn = el("button", {
      className: "like-btn" + (topic.liked ? " liked" : ""),
      type: "button",
      "data-topic-id": topic.id,
      title: "点赞",
      onclick: (e) => handleLike(e, topic),
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
    const identity = topic.author_profile || {
      display_name: topic.author,
      username: topic.author,
    };
    if (metaEl)
      metaEl.textContent = `${identity.display_name || topic.author} · ${topic.category} · ${topic.active}${topic.boosted ? " · 加热中" : ""}`;

    // share button
    const shareBtn = modal.querySelector("#detailShareBtn");
    if (shareBtn) {
      shareBtn.onclick = async () => {
        const shareUrl = `${location.origin}/t/${topic.id}`;
        try {
          await navigator.clipboard.writeText(shareUrl);
          showToast("分享链接已复制", "success");
        } catch {
          showToast(`分享链接：${shareUrl}`, "info");
        }
      };
    }

    // project links
    const linksEl = modal.querySelector("#detailLinks");
    if (linksEl) {
      linksEl.replaceChildren();
      for (const link of topic.links || []) {
        linksEl.append(
          el("a", {
            className: `topic-link-badge link-${link.type}`,
            href: link.url,
            target: "_blank",
            rel: "noopener nofollow",
            textContent: `↗ ${link.name || LINK_BADGE[link.type] || "链接"}`,
          }),
        );
      }
    }

    // image gallery
    const imagesEl = modal.querySelector("#detailImages");
    if (imagesEl) {
      imagesEl.replaceChildren();
      for (const image of topic.images || []) {
        const img = el("img", {
          src: image.url,
          alt: "作品截图",
          loading: "lazy",
        });
        img.addEventListener("click", () => window.open(image.url, "_blank", "noopener"));
        imagesEl.append(img);
      }
    }

    // boost panel (author only)
    renderBoostPanel(modal, topic);

    const bodyEl = modal.querySelector(".detail-body");
    if (bodyEl) {
      setRenderedMarkdown(bodyEl, topic.content || "");
    }

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
          const ava = el("div", { className: "reply-avatar" });
          if (r.author_profile?.avatar_url) {
            const img = document.createElement("img");
            img.src = r.author_profile.avatar_url;
            img.alt = "";
            img.addEventListener("error", () => {
              ava.replaceChildren(r.initials || "?");
            });
            ava.append(img);
          } else {
            ava.textContent = r.initials || "?";
          }
          const rBody = el("div", { className: "reply-body" });
          const identity = r.author_profile || {
            display_name: r.author,
            username: r.author,
            initials: r.initials || "?",
          };
          const authorLink = el("a", {
            className: "reply-author",
            href: `/forum/user/${encodeURIComponent(identity.username || r.author)}`,
            textContent: identity.display_name || r.author,
          });
          const rTime = el("span", {
            className: "reply-time",
            textContent: r.created_at
              ? new Date(r.created_at).toLocaleString("zh-CN")
              : "",
          });
          const rContent = el("div", {
            className: "reply-content forum-markdown",
          });
          setRenderedMarkdown(rContent, r.content || "");

          const rFoot = el("div", { className: "reply-foot" });
          const rLike = el("button", {
            className: "like-btn reply-like-btn" + (r.liked ? " liked" : ""),
            type: "button",
            onclick: (e) => handleReplyLike(e, r),
          });
          rLike.append(
            iconEl("heart", 13),
            el("span", { className: "like-count", textContent: r.likes || 0 }),
          );
          rFoot.append(rLike);

          rBody.append(authorLink, rTime, rContent, rFoot);
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

  // ── boost panel ───────────────────────────────────────────────────────────
  async function renderBoostPanel(modal, topic) {
    const panel = modal.querySelector("#detailBoost");
    if (!panel) return;
    panel.replaceChildren();
    const isAuthor =
      state.currentUser && state.currentUser.username === topic.author;
    const show = isAuthor && topic.status === "open";
    panel.style.display = show ? "" : "none";
    if (!show) return;

    panel.append(
      el("div", { className: "boost-heading" }, iconEl("flame", 14), " 给帖子加热（消耗积分，提升热度与曝光）"),
    );

    // 当前积分余额：真实扣费可见化
    let balance = null;
    try {
      const res = await apiFetch("/api/points/me");
      balance = (await res.json()).balance ?? null;
    } catch {
      balance = null;
    }

    let tiers;
    try {
      const res = await apiFetch("/api/forum/boosts/tiers");
      tiers = (await res.json()).tiers || {};
    } catch {
      return;
    }

    const balanceLine = el("div", { className: "boost-balance" });
    const renderBalance = () => {
      balanceLine.replaceChildren();
      if (balance == null) {
        balanceLine.append(el("span", { textContent: "积分余额加载失败" }));
        return;
      }
      balanceLine.append(
        el("span", { textContent: "当前余额 " }),
        el("strong", { textContent: `${balance} 积分` }),
        el("a", { className: "boost-earn-link", href: "/points", textContent: "怎么赚积分？" }),
      );
    };
    renderBalance();
    panel.append(balanceLine);

    const row = el("div", { className: "boost-tier-row" });
    for (const [key, tier] of Object.entries(tiers)) {
      const cannotAfford = balance != null && balance < tier.cost;
      const btn = el("button", {
        type: "button",
        className: "boost-tier-btn" + (cannotAfford ? " disabled" : ""),
        disabled: cannotAfford,
        onclick: async (e) => {
          const btn = e.currentTarget;
          if (btn.classList.contains("disabled")) {
            showToast("积分不足这一档，先去赚积分吧", "warn");
            return;
          }
          if (!window.confirm(`确认花费 ${tier.cost} 积分为帖子加热（+${tier.score} 热度 / ${tier.hours} 小时）？加热不可退款。`)) return;
          btn.disabled = true;
          try {
            const res = await apiFetch(`/api/forum/topics/${topic.id}/boost`, {
              method: "POST",
              headers: { "X-CSRFToken": getCsrf() },
              body: JSON.stringify({ tier: key }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              showToast(data.error || "加热失败", "error");
              btn.disabled = false;
              return;
            }
            // 真实扣分反馈：余额即时更新
            if (typeof data.balance === "number") {
              balance = data.balance;
              renderBalance();
            }
            showToast(`加热成功，扣除 ${tier.cost} 积分${data.balance != null ? `，余额 ${data.balance}` : ""}`, "success");
            if (data.newBadges?.length && window.kflowCelebrate) window.kflowCelebrate.badges(data.newBadges);
            btn.disabled = false;
            openTopicDetail({ id: topic.id });
          } catch {
            showToast("网络错误，请重试", "error");
            btn.disabled = false;
          }
        },
      });
      btn.append(
        el("span", { className: "boost-tier-label", textContent: tier.label }),
        el("span", { className: "boost-tier-cost", textContent: `${tier.cost} 积分` }),
        el("span", { className: "boost-tier-effect", textContent: `+${tier.score} 热度 · ${tier.hours}h` }),
        cannotAfford ? el("span", { className: "boost-tier-poor", textContent: "余额不足" }) : null,
      );
      row.append(btn);
    }
    panel.append(row);
  }

  // ── reply likes ───────────────────────────────────────────────────────────
  async function handleReplyLike(e, reply) {
    e.stopPropagation();
    if (!state.currentUser) {
      showToast("请先登录后再点赞", "warn");
      return;
    }
    const btn = e.currentTarget;
    const liked = btn.classList.contains("liked");
    try {
      const res = await apiFetch(`/api/forum/replies/${reply.id}/like`, {
        method: liked ? "DELETE" : "POST",
        headers: { "X-CSRFToken": getCsrf() },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 401) {
          state.currentUser = await refreshUser();
          showToast("登录状态已过期，请重新登录", "warn");
          return;
        }
        showToast(data.error || "操作失败，请重试", "error");
        return;
      }
      btn.classList.toggle("liked", data.liked);
      const countEl = btn.querySelector(".like-count");
      if (countEl) countEl.textContent = data.likes;
    } catch {
      showToast("网络错误，请重试", "error");
    }
  }

  function closeDetailModal() {
    const modal = els.detailModal;
    if (!modal) return;
    modal.classList.remove("open");
    document.body.style.overflow = "";
  }

  // ── new topic modal ───────────────────────────────────────────────────────
  const newTopicImages = { ids: [] }; // uploaded image ids awaiting topic creation

  function openNewTopic() {
    if (!state.currentUser) {
      showToast("请先登录后再发帖", "warn");
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

  // ── topic image uploads ───────────────────────────────────────────────────
  async function uploadTopicImage(file) {
    const form = new FormData();
    form.append("file", file);
    const res = await apiFetch("/api/forum/images", {
      method: "POST",
      headers: { "X-CSRFToken": getCsrf() },
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "图片上传失败");
    return data.image; // { id, url }
  }

  function renderImagePreviews() {
    const wrap = document.querySelector("#topicImagePreviews");
    if (!wrap) return;
    wrap.replaceChildren();
    newTopicImages.ids.forEach((id, index) => {
      const chip = el("span", { className: "topic-image-chip" });
      const img = el("img", { src: `/api/forum/images/${id}`, alt: `截图 ${index + 1}` });
      const remove = el("button", {
        type: "button",
        className: "topic-image-remove",
        textContent: "×",
        "aria-label": "移除这张图",
        onclick: () => {
          newTopicImages.ids.splice(index, 1);
          renderImagePreviews();
        },
      });
      if (index === 0) chip.title = "首张将作为封面";
      chip.append(img, remove);
      wrap.append(chip);
    });
  }

  async function handleImageSelection(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    const remaining = 9 - newTopicImages.ids.length;
    if (remaining <= 0) {
      showToast("最多上传 9 张图片", "warn");
      return;
    }
    const accepted = files.slice(0, remaining);
    if (files.length > remaining) showToast(`最多 9 张，已忽略多余 ${files.length - remaining} 张`, "warn");
    for (const file of accepted) {
      if (file.size > 5 * 1024 * 1024) {
        showToast(`「${file.name}」超过 5MB，已跳过`, "error");
        continue;
      }
      try {
        const image = await uploadTopicImage(file);
        newTopicImages.ids.push(image.id);
        renderImagePreviews();
      } catch (err) {
        showToast(err.message || "图片上传失败", "error");
      }
    }
  }

  function collectLinks() {
    const links = [];
    for (const name of ["link1", "link2", "link3"]) {
      const input = els.newTopicModal?.querySelector(`[name=${name}]`);
      const url = (input?.value || "").trim();
      if (url) links.push({ url, name: "" });
    }
    return links;
  }

  // ── handle like ───────────────────────────────────────────────────────────
  async function handleLike(e, topic) {
    e.stopPropagation();
    if (!state.currentUser) {
      showToast("请先登录后再点赞", "warn");
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
      if (data.liked) {
        btn.classList.remove("pop");
        void btn.offsetWidth;
        btn.classList.add("pop");
      }
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
        body: JSON.stringify({
          title,
          content,
          category: categorySlug,
          tags,
          images: newTopicImages.ids,
          links: collectLinks(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 401) {
          showToast(data.error || "请先登录后再发帖", "warn");
          state.currentUser = null;
          return;
        }
        showToast(data.error || "发帖失败，请重试", "error");
        return;
      }
      showToast("发帖成功！积分 +10", "success");
      if (data.newBadges?.length && window.kflowCelebrate) window.kflowCelebrate.badges(data.newBadges);;
      closeNewTopicModal();
      form.reset();
      newTopicImages.ids = [];
      renderImagePreviews();
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
      showToast("回复成功", "success");
      if (data.newBadges?.length && window.kflowCelebrate) window.kflowCelebrate.badges(data.newBadges);
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
    state.categories = cats;
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

    // topic image picker
    const imageInput = document.querySelector("#topicImages");
    if (imageInput) imageInput.addEventListener("change", handleImageSelection);

    // deep links: /forum?topic=<id> opens detail; /forum?compose=1 opens composer
    const params = new URLSearchParams(location.search);
    const deepTopicId = Number(params.get("topic"));
    if (deepTopicId > 0) {
      openTopicDetail({ id: deepTopicId });
    } else if (params.get("compose")) {
      openNewTopic();
    }
    const deepQuery = params.get("q");
    if (deepQuery && els.searchInput) {
      els.searchInput.value = deepQuery;
      handleSearch(deepQuery);
    }

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

    setupMarkdownEditors();
    loadAll();
  });
})();
