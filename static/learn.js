/* Shared JS for glossary / tutorials / tutorial detail pages. */
(() => {
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

  async function apiFetch(url) {
    return fetch(url, { credentials: "same-origin" });
  }

  // minimal safe Markdown renderer (same rules as forum.js)
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function renderInline(value) {
    const segments = String(value ?? "").split(/(`[^`\n]+`)/g);
    return segments
      .map((segment) => {
        if (/^`[^`\n]+`$/.test(segment)) return `<code>${escapeHtml(segment.slice(1, -1))}</code>`;
        return escapeHtml(segment)
          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/\*(.+?)\*/g, "<em>$1</em>")
          .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g, (match, text, href) => {
          const external = href.startsWith("http");
          return `<a href="${href}"${external ? ' target="_blank" rel="noopener noreferrer"' : ""}>${text}</a>`;
        });
      })
      .join("");
  }

  function renderMarkdown(value) {
    const lines = String(value ?? "").replace(/\r/g, "").split("\n");
    const output = [];
    let paragraph = [];
    let listType = "";
    let listItems = [];
    let inCode = false;
    let codeLines = [];
    const flushParagraph = () => {
      if (paragraph.length) output.push(`<p>${paragraph.map(renderInline).join("<br>")}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (listType && listItems.length) {
        output.push(`<${listType}>${listItems.map((i) => `<li>${renderInline(i)}</li>`).join("")}</${listType}>`);
      }
      listType = "";
      listItems = [];
    };
    for (const line of lines) {
      if (line.startsWith("```")) {
        if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        inCode = !inCode;
        codeLines = [];
        continue;
      }
      if (inCode) { codeLines.push(line); continue; }
      const unordered = line.match(/^\s*[-*]\s+(.+)/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.+)/);
      if (unordered || ordered) {
        flushParagraph();
        const nextType = unordered ? "ul" : "ol";
        if (listType && listType !== nextType) flushList();
        listType = nextType;
        listItems.push((unordered || ordered)[1]);
        continue;
      }
      flushList();
      const heading = line.match(/^(#{1,6})\s+(.+)/);
      if (heading) {
        flushParagraph();
        output.push(`<h${Math.min(6, heading[1].length)}>${renderInline(heading[2])}</h${Math.min(6, heading[1].length)}>`);
        continue;
      }
      if (/^>\s?/.test(line)) {
        flushParagraph();
        output.push(`<blockquote>${renderInline(line.replace(/^>\s?/, ""))}</blockquote>`);
        continue;
      }
      if (!line.trim()) { flushParagraph(); continue; }
      paragraph.push(line);
    }
    flushParagraph();
    flushList();
    if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    return output.join("") || "<p></p>";
  }

  function setRenderedMarkdown(container, value) {
    container.innerHTML = renderMarkdown(value);
  }

  // ── glossary page ──
  async function initGlossary() {
    const grid = document.querySelector("#glossaryGrid");
    const filters = document.querySelector("#glossaryFilters");
    if (!grid) return;
    let items = [];
    let categories = [];
    let active = "";
    try {
      const res = await apiFetch("/api/learn/glossary");
      const data = await res.json();
      items = data.items || [];
      categories = data.categories || [];
    } catch { /* keep empty */ }

    const render = () => {
      grid.replaceChildren();
      const filtered = active ? items.filter((g) => g.category === active) : items;
      if (!filtered.length) {
        grid.append(el("p", { className: "rankings-empty", textContent: "术语整理中，敬请期待。" }));
        return;
      }
      for (const g of filtered) {
        grid.append(
          el("a", { className: "glossary-card", href: `/glossary/${g.slug}` },
            el("h3", {}, g.term,
              el("span", { className: "gloss-open-hint", textContent: "详情 →" })),
            g.en ? el("span", { className: "gloss-en", textContent: g.en }) : null,
            el("p", { textContent: g.definition }),
            el("span", { className: "gloss-cat", textContent: g.category + (g.hasDetail ? " · 有详解" : "") }),
          ),
        );
      }
    };

    filters.replaceChildren(
      el("button", {
        className: "subtab" + (active === "" ? " active" : ""),
        type: "button",
        textContent: "全部",
        onclick: (e) => { active = ""; syncFilters(); render(); },
      }),
      ...categories.map((cat) =>
        el("button", {
          className: "subtab",
          type: "button",
          textContent: cat,
          onclick: () => { active = cat; syncFilters(); render(); },
        }),
      ),
    );
    const syncFilters = () => {
      filters.querySelectorAll(".subtab").forEach((b, index) => {
        b.classList.toggle("active", index === 0 ? active === "" : categories[index - 1] === active);
      });
    };
    render();
  }

  // ── tutorials list page ──
  async function initTutorials() {
    const grid = document.querySelector("#tutorialGrid");
    if (!grid) return;
    let kind = "";
    const load = async () => {
      grid.replaceChildren(el("p", { className: "rankings-empty", textContent: "加载中…" }));
      try {
        const res = await apiFetch(`/api/learn/tutorials${kind ? `?kind=${kind}` : ""}`);
        const data = await res.json();
        grid.replaceChildren();
        const items = data.items || [];
        if (!items.length) {
          grid.append(el("p", { className: "rankings-empty", textContent: "教程整理中，敬请期待。" }));
          return;
        }
        const KIND_LABEL = { tutorial: "手把手教程", paradigm: "开发范式" };
        for (const t of items) {
          grid.append(
            el("article", { className: "tutorial-card" },
              el("span", { className: "tut-kind", textContent: KIND_LABEL[t.kind] || t.kind }),
              el("h3", {}, el("a", { href: `/tutorials/${t.slug}`, textContent: t.title })),
              el("p", { className: "tut-summary", textContent: t.summary || "" }),
              el("div", { className: "tut-meta-row" },
                el("span", { className: `tut-difficulty ${t.difficulty}`, textContent: t.difficulty === "beginner" ? "入门" : "进阶" }),
                el("span", { textContent: `约 ${t.reading_minutes} 分钟` }),
                t.series ? el("span", { textContent: `· ${t.series}` }) : null,
              ),
            ),
          );
        }
      } catch {
        grid.replaceChildren(el("p", { className: "rankings-empty", textContent: "教程加载失败，请稍后重试。" }));
      }
    };
    document.querySelectorAll("#tutorialFilters .subtab").forEach((btn) =>
      btn.addEventListener("click", () => {
        document.querySelectorAll("#tutorialFilters .subtab").forEach((b) => b.classList.toggle("active", b === btn));
        kind = btn.dataset.kind;
        load();
      }));
    load();
  }

  // ── tutorial detail page ──
  async function initTutorialDetail() {
    const root = document.querySelector("#tutorialDetail");
    if (!root) return;
    const slug = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
    if (!slug) return;
    try {
      const res = await apiFetch(`/api/learn/tutorials/${encodeURIComponent(slug)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "教程不存在");
      const t = data.tutorial;
      document.title = `${t.title} | KFlow 社区`;
      root.replaceChildren(
        el("div", { className: "tut-head" },
          el("div", { className: "tut-meta-row" },
            el("span", { textContent: t.kind === "paradigm" ? "开发范式" : "手把手教程" }),
            el("span", { className: `tut-difficulty ${t.difficulty}`, textContent: t.difficulty === "beginner" ? "入门" : "进阶" }),
            el("span", { textContent: `约 ${t.reading_minutes} 分钟` }),
            el("span", { textContent: `${t.views} 次阅读` }),
          ),
          el("h1", { textContent: t.title }),
          t.summary ? el("p", { className: "tut-summary", textContent: t.summary }) : null,
        ),
        el("div", { id: "learnCompleteHost", className: "trend-predict-box" }),
        el("div", { className: "detail-body forum-markdown" }),
        (t.series_items || []).length > 1
          ? el("div", { className: "tut-head" },
              el("h2", { textContent: `系列：${t.series}` }),
              el("ul", {},
                ...t.series_items.map((item) =>
                  el("li", {}, el("a", { href: `/tutorials/${item.slug}`, textContent: item.title })),
                )),
            )
          : null,
        el("div", { className: "tutorial-cta" },
          "用这篇教程做出了东西？",
          el("a", { href: "/forum?compose=1", textContent: "来发帖晒作品 →" }),
        ),
      );
      setRenderedMarkdown(root.querySelector(".detail-body"), t.content_md);
      injectCompleteButton(root.querySelector("#learnCompleteHost"), "tutorial", t.slug);
    } catch (err) {
      root.replaceChildren(
        el("p", { className: "rankings-empty", textContent: err.message || "教程加载失败。" }),
      );
    }
  }


  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  // ── 完成学习按钮（教程/词条详情页）──
  function injectCompleteButton(host, kind, slug) {
    if (!host) return;
    const wrap = el("div", { className: "learn-complete-wrap" });
    const button = el("button", {
      className: "learn-complete-btn",
      type: "button",
      textContent: "我学完了，领取勋章",
    });
    wrap.append(
      el("span", { className: "learn-complete-hint", textContent: "学完这部分内容了吗？" }),
      button,
    );
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const res = await fetch("/api/learn/complete", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({ kind, slug }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) {
          showToast("登录后即可记录学习进度并领取勋章", "warn");
          button.disabled = false;
          return;
        }
        if (!res.ok) {
          showToast(data.error || "操作失败", "error");
          button.disabled = false;
          return;
        }
        if (data.created && window.kflowCelebrate && data.newBadges?.length) {
          window.kflowCelebrate.badges(data.newBadges);
          showToast(`学习进度已记录（${data.completed} 篇），新勋章已到账`, "success");
        } else if (data.created) {
          showToast("学习进度已记录，继续加油", "success");
        } else {
          showToast("这篇你已经学过了", "info");
        }
        button.textContent = "已完成 ✓";
        button.classList.add("done");
      } catch {
        showToast("网络错误，请重试", "error");
        button.disabled = false;
      }
    });
    host.append(wrap);
  }
  // ── 词条详情页 ──
  async function initGlossaryDetail() {
    const root = document.querySelector("#glossaryRoot");
    if (!root) return;
    const slug = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
    if (!slug) return;
    try {
      const res = await apiFetch(`/api/learn/glossary/${encodeURIComponent(slug)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "词条不存在");
      const t = data.term;
      let detailBodyHost = null;
      document.title = `${t.term} ${t.en ? "· " + t.en : ""} | KFlow 社区`;
      root.replaceChildren(
        el("div", { className: "trend-title-row" },
          el("h1", { textContent: t.term }),
          t.en ? el("span", { className: "gloss-en", textContent: t.en }) : null,
          el("span", { className: "gloss-cat", textContent: t.category }),
        ),
        el("div", { className: "gloss-def-quote", textContent: t.definition }),
        el("div", { className: "detail-body forum-markdown" }),
        (t.related || []).length
          ? el("div", { className: "glossary-related" },
              el("h2", { textContent: "相关词条" }),
              el("div", { className: "glossary-related-list" },
                ...t.related.map((r) =>
                  el("a", { href: `/glossary/${r.slug}`, textContent: r.term + (r.en ? ` · ${r.en}` : "") }),
                )),
            )
          : null,
        el("div", { className: "tutorial-cta", style: "margin-top:26px" },
          "学会了？",
          el("a", { href: "/forum?compose=1", textContent: "来发帖讲讲你的理解 →" }),
        ),
      );
      setRenderedMarkdown(root.querySelector(".detail-body"), t.contentMd || t.definition);
      const host2 = el("div", { className: "trend-predict-box", style: "margin-top:16px" });
      detailBodyHost = host2;
      root.querySelector(".detail-body").after(host2);
      injectCompleteButton(host2, "term", t.slug);
    } catch (err) {
      root.replaceChildren(
        el("p", { className: "rankings-empty", textContent: err.message || "词条加载失败。" }),
      );
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initGlossary();
    initTutorials();
    initTutorialDetail();
    initGlossaryDetail();
  });
})();
