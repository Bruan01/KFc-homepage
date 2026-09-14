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

  async function apiFetch(url, options = {}) {
    return fetch(url, { credentials: "same-origin", ...options });
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
        output.push(`<${listType}>${listItems.map((item) => {
          const task = item.match(/^\[([ xX])\]\s+(.+)/);
          if (task) return `<li class="task-item"><input type="checkbox" disabled ${task[1].toLowerCase() === "x" ? "checked" : ""} /><span>${renderInline(task[2])}</span></li>`;
          return `<li>${renderInline(item)}</li>`;
        }).join("")}</${listType}>`);
      }
      listType = "";
      listItems = [];
    };
    const isTableSeparator = (line) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
    const tableCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (line.startsWith("```")) {
        if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        inCode = !inCode;
        codeLines = [];
        continue;
      }
      if (inCode) { codeLines.push(line); continue; }
      const nextLine = lines[index + 1] || "";
      if (line.includes("|") && isTableSeparator(nextLine)) {
        flushParagraph();
        flushList();
        const headers = tableCells(line);
        const rows = [];
        index += 2;
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          rows.push(tableCells(lines[index]));
          index += 1;
        }
        index -= 1;
        output.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${renderInline(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${renderInline(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
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
        continue;
      }
      flushList();
      const heading = line.match(/^(#{1,6})\s+(.+)/);
      if (heading) {
        flushParagraph();
        const level = Math.min(6, heading[1].length);
        output.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        continue;
      }
      if (/^\s*(---+|___+)\s*$/.test(line)) {
        flushParagraph();
        output.push("<hr />");
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

  // ── Vibecoding 电子书阅读器 ──
  async function initBookReader() {
    const root = document.querySelector("#bookReader");
    if (!root) return;
    const toc = document.querySelector("#bookToc");
    const tocContent = document.querySelector("#bookTocContent");
    const tocProgress = document.querySelector("#bookTocProgress");
    const pageLeft = document.querySelector("#bookPageLeft");
    const pageRight = document.querySelector("#bookPageRight");
    const spread = document.querySelector("#bookSpread");
    const pageEdgeLeft = document.querySelector("#bookPageEdgeLeft");
    const pageEdgeRight = document.querySelector("#bookPageEdgeRight");
    const indicator = document.querySelector("#bookPageIndicator");
    const breadcrumb = document.querySelector("#bookBreadcrumb");
    const previousButton = document.querySelector("#bookPrevious");
    const nextButton = document.querySelector("#bookNext");
    const tocButton = document.querySelector("#bookTocButton");
    const immersiveButton = document.querySelector("#bookImmersiveButton");
    const resumeButton = document.querySelector("#bookResumeButton");
    const reduceMotionButton = document.querySelector("#bookReduceMotion");
    const completeHost = document.querySelector("#learnCompleteHost");
    const storageKey = "kflow:learn:book-progress:v1";
    const uiStorageKey = "kflow:learn:book-ui:v1";
    const cache = new Map();
    let book = null;
    let activeTutorial = null;
    let pageIndex = -1;
    let reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;
    let tocCollapsed = false;
    let immersiveMode = false;

    try {
      const preferences = JSON.parse(localStorage.getItem(uiStorageKey) || "null");
      tocCollapsed = Boolean(preferences?.tocCollapsed);
      immersiveMode = Boolean(preferences?.immersiveMode);
    } catch { /* UI preferences are optional */ }

    const isMobile = () => window.matchMedia?.("(max-width: 860px)").matches || false;
    const savedProgress = () => {
      try { return JSON.parse(localStorage.getItem(storageKey) || "null"); } catch { return null; }
    };
    const saveProgress = () => {
      if (!activeTutorial || pageIndex < 0) return;
      try { localStorage.setItem(storageKey, JSON.stringify({ slug: activeTutorial.slug, page: pageIndex })); } catch { /* storage is optional */ }
    };
    const saveUiPreferences = () => {
      try { localStorage.setItem(uiStorageKey, JSON.stringify({ tocCollapsed, immersiveMode })); } catch { /* storage is optional */ }
    };
    const chapterNumber = (tutorial) => tutorial?.chapter_number || tutorial?.sort_order || "";
    const pageCountFor = (tutorial) => tutorial?.pages?.length || tutorial?.page_count || 1;
    const chapterLabel = (tutorial) => `第 ${chapterNumber(tutorial)} 章 · ${tutorial.title}`;
    const partLabel = (tutorial) => tutorial?.series || "Vibecoding 开发者手册";

    function setTocCollapsed(collapsed) {
      tocCollapsed = collapsed;
      root.classList.toggle("is-toc-collapsed", collapsed);
      toc.classList.toggle("is-collapsed", collapsed);
      tocButton?.setAttribute("aria-expanded", String(!collapsed));
      toc?.setAttribute("aria-hidden", String(collapsed));
      if (tocButton) tocButton.textContent = collapsed ? "展开目录" : "收起目录";
      saveUiPreferences();
    }

    function setImmersiveMode(enabled) {
      immersiveMode = enabled;
      document.body.classList.toggle("book-immersive", enabled);
      immersiveButton?.setAttribute("aria-pressed", String(enabled));
      if (immersiveButton) immersiveButton.textContent = enabled ? "退出沉浸" : "沉浸阅读";
      saveUiPreferences();
    }

    function renderCover() {
      activeTutorial = null;
      pageIndex = -1;
      breadcrumb.textContent = "书封 · 开始阅读";
      indicator.textContent = `${book?.chapter_count || 0} 章 · ${book?.page_count || 0} 页`;
      pageLeft.className = "book-page book-page-left book-cover-page";
      pageRight.className = "book-page book-page-right book-cover-page book-cover-back";
      pageLeft.innerHTML = `<div class="book-cover-art"><span>FIELD GUIDE</span><strong>${escapeHtml(book?.title || "Vibecoding 开发者手册")}</strong><em>${escapeHtml(book?.subtitle || "从灵感原型到可维护产品")}</em><small>第 ${escapeHtml(book?.edition || "2026.09")} 版</small></div>`;
      pageRight.innerHTML = `<div class="book-cover-note"><span class="book-page-eyebrow">READING NOTE</span><h2>先定义结果，再让 AI 动手。</h2><p>${escapeHtml(book?.description || "一套覆盖需求、智能体协作、全栈实现、质量交付与持续演进的实战方法。")}</p><button class="book-start-button" type="button" id="bookStartButton">从第一页开始 →</button></div>`;
      pageRight.querySelector("#bookStartButton")?.addEventListener("click", () => openChapter(book?.parts?.[0]?.chapters?.[0]?.slug));
      previousButton.disabled = true;
      nextButton.disabled = !(book?.parts || []).length;
      completeHost.replaceChildren();
      spread.classList.remove("is-turning", "turn-back");
    }

    function buildToc() {
      tocContent.replaceChildren();
      if (!book?.parts?.length) {
        tocContent.append(el("p", { className: "book-toc-empty", textContent: "目录整理中…" }));
        return;
      }
      tocProgress.textContent = `${book.chapter_count} 章 · ${book.page_count} 页 · 约 ${book.reading_minutes} 分钟`;
      for (const part of book.parts) {
        const partElement = el("section", { className: "book-toc-part" },
          el("div", { className: "book-toc-part-heading" },
            el("span", { className: "book-part-number", textContent: String(part.number).padStart(2, "0") }),
            el("div", {}, el("strong", { textContent: part.title }), el("small", { textContent: part.summary || "" })),
          ),
          el("ol", { className: "book-toc-list" }, ...part.chapters.map((chapter) => {
            const button = el("button", { type: "button", className: "book-toc-item" },
              el("span", { className: "book-toc-number", textContent: String(chapter.chapter_number || "").padStart(2, "0") }),
              el("span", { className: "book-toc-title", textContent: chapter.title }),
              el("span", { className: "book-toc-pages", textContent: `${chapter.page_count || 1}p` }),
            );
            button.dataset.slug = chapter.slug;
            button.addEventListener("click", () => openChapter(chapter.slug));
            return el("li", {}, button);
          })),
        );
        tocContent.append(partElement);
      }
    }

    function syncTocActive() {
      tocContent.querySelectorAll(".book-toc-item").forEach((button) => {
        button.classList.toggle("active", button.dataset.slug === activeTutorial?.slug);
      });
    }

    function animateTurn(direction) {
      if (reducedMotion) return;
      spread.classList.remove("is-turning", "turn-back");
      void spread.offsetWidth;
      if (direction < 0) spread.classList.add("turn-back");
      spread.classList.add("is-turning");
      window.setTimeout(() => spread.classList.remove("is-turning", "turn-back"), 420);
    }

    function renderPage(pageElement, page, position, total, pageNumber) {
      pageElement.className = `book-page book-page-${position}`;
      if (!page) {
        pageElement.classList.add("book-page-blank");
        pageElement.innerHTML = "<span>·</span>";
        return;
      }
      const markdown = typeof page === "string" ? page : (page.content_md || page.contentMd || "");
      pageElement.innerHTML = `<div class="book-page-topline"><span>${escapeHtml(partLabel(activeTutorial))}</span><span>${chapterNumber(activeTutorial)} / ${escapeHtml(String(book.chapter_count || ""))}</span></div><div class="book-page-body forum-markdown">${renderMarkdown(markdown)}</div><div class="book-page-footer"><span>${String(pageNumber + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}</span><span>KFlow · Vibecoding Field Guide</span></div>`;
    }

    function updateUrl() {
      if (!activeTutorial) return;
      const target = `/tutorials/${encodeURIComponent(activeTutorial.slug)}#page=${Math.max(0, pageIndex)}`;
      history.replaceState({}, "", target);
    }

    function renderSpread(direction = 1) {
      if (!activeTutorial) { renderCover(); return; }
      const pages = activeTutorial.pages || [];
      const mobile = isMobile();
      const leftIndex = Math.max(0, pageIndex);
      const rightIndex = mobile ? -1 : leftIndex + 1;
      renderPage(pageLeft, pages[leftIndex], "left", pages.length, leftIndex);
      renderPage(pageRight, mobile ? null : pages[rightIndex], "right", pages.length, rightIndex);
      pageLeft.classList.toggle("book-page-mobile", mobile);
      pageRight.hidden = mobile;
      breadcrumb.textContent = `${partLabel(activeTutorial)} / ${chapterLabel(activeTutorial)}`;
      const shown = mobile ? `${leftIndex + 1}` : `${leftIndex + 1}${rightIndex < pages.length ? `–${rightIndex + 1}` : ""}`;
      indicator.textContent = `第 ${chapterNumber(activeTutorial)} 章 · ${shown} / ${pages.length} 页`;
      previousButton.disabled = pageIndex <= 0 && !activeTutorial.previous_chapter;
      nextButton.disabled = pageIndex >= pages.length - (mobile ? 1 : 2) && !activeTutorial.next_chapter;
      completeHost.replaceChildren();
      injectCompleteButton(completeHost, "tutorial", activeTutorial.slug);
      syncTocActive();
      saveProgress();
      updateUrl();
      animateTurn(direction);
    }

    async function openChapter(slug, requestedPage = 0, direction = 1) {
      if (!slug) return;
      try {
        let tutorial = cache.get(slug);
        if (!tutorial) {
          const res = await apiFetch(`/api/learn/tutorials/${encodeURIComponent(slug)}`);
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "教程不存在");
          tutorial = data.tutorial;
          cache.set(slug, tutorial);
        }
        activeTutorial = tutorial;
        const maxPage = Math.max(0, pageCountFor(tutorial) - (isMobile() ? 1 : 2));
        pageIndex = Math.min(Math.max(0, Number(requestedPage) || 0), maxPage);
        document.title = `${tutorial.title} | Vibecoding 开发者手册`;
        renderSpread(direction);
        window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
      } catch (error) {
        pageLeft.innerHTML = `<div class="book-error"><h2>这一章暂时打不开</h2><p>${escapeHtml(error.message || "教程加载失败，请稍后重试。")}</p></div>`;
        pageRight.innerHTML = "";
      }
    }

    function changePage(step) {
      if (!activeTutorial) {
        const first = book?.parts?.[0]?.chapters?.[0];
        if (step > 0 && first) openChapter(first.slug);
        return;
      }
      const pages = activeTutorial.pages || [];
      const increment = isMobile() ? 1 : 2;
      const nextIndex = pageIndex + step * increment;
      if (nextIndex < 0) {
        if (activeTutorial.previous_chapter) openChapter(activeTutorial.previous_chapter.slug, Number.MAX_SAFE_INTEGER, -1);
        else renderCover();
        return;
      }
      if (nextIndex >= pages.length) {
        if (activeTutorial.next_chapter) openChapter(activeTutorial.next_chapter.slug, 0, 1);
        return;
      }
      pageIndex = nextIndex;
      renderSpread(step);
    }

    tocButton?.addEventListener("click", () => setTocCollapsed(!tocCollapsed));
    immersiveButton?.addEventListener("click", () => setImmersiveMode(!immersiveMode));
    previousButton?.addEventListener("click", () => changePage(-1));
    nextButton?.addEventListener("click", () => changePage(1));
    pageEdgeLeft?.addEventListener("click", () => changePage(-1));
    pageEdgeRight?.addEventListener("click", () => changePage(1));
    pageLeft?.addEventListener("click", (event) => {
      if (event.target?.closest?.("a, button, input, textarea, select, summary")) return;
      if (isMobile()) {
        const bounds = pageLeft.getBoundingClientRect();
        changePage(event.clientX < bounds.left + bounds.width / 2 ? -1 : 1);
      } else {
        changePage(-1);
      }
    });
    pageRight?.addEventListener("click", (event) => {
      if (event.target?.closest?.("a, button, input, textarea, select, summary")) return;
      changePage(1);
    });
    resumeButton?.addEventListener("click", () => {
      const saved = savedProgress();
      if (saved?.slug) openChapter(saved.slug, saved.page || 0);
    });
    reduceMotionButton?.addEventListener("click", () => {
      reducedMotion = !reducedMotion;
      reduceMotionButton.setAttribute("aria-pressed", String(reducedMotion));
      reduceMotionButton.textContent = reducedMotion ? "静止" : "动效";
    });
    window.addEventListener("resize", () => { if (activeTutorial) renderSpread(0); });
    window.addEventListener("keydown", (event) => {
      if (event.target.matches("input, textarea, select, button")) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); changePage(-1); }
      if (event.key === "ArrowRight" || event.key === " ") { event.preventDefault(); changePage(1); }
      if (event.key === "Home" && activeTutorial) { event.preventDefault(); pageIndex = 0; renderSpread(-1); }
      if (event.key === "End" && activeTutorial) { event.preventDefault(); pageIndex = Math.max(0, pageCountFor(activeTutorial) - (isMobile() ? 1 : 2)); renderSpread(1); }
      if (event.key === "Escape" && immersiveMode) { event.preventDefault(); setImmersiveMode(false); }
    });

    setTocCollapsed(tocCollapsed);
    setImmersiveMode(immersiveMode);

    try {
      const res = await apiFetch("/api/learn/tutorials");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "目录加载失败");
      book = data.book || { parts: [], chapter_count: 0, page_count: 0 };
      buildToc();
      const pathSlug = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
      const saved = savedProgress();
      const initialSlug = root.dataset.initialSlug || (pathSlug && pathSlug !== "tutorials" ? pathSlug : "");
      if (saved?.slug) {
        resumeButton.hidden = false;
        resumeButton.textContent = `继续阅读 · 第 ${saved.page + 1} 页`;
      }
      if (initialSlug) {
        const hashPage = new URLSearchParams(location.hash.replace(/^#/, "")).get("page");
        await openChapter(initialSlug, hashPage || 0);
      } else {
        renderCover();
      }
    } catch (error) {
      tocProgress.textContent = "目录加载失败";
      pageLeft.innerHTML = `<div class="book-error"><h2>手册暂时无法加载</h2><p>${escapeHtml(error.message || "请稍后重试。")}</p></div>`;
      pageRight.innerHTML = "";
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
        const res = await apiFetch("/api/learn/complete", {
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
    initBookReader();
    initGlossaryDetail();
  });
})();
