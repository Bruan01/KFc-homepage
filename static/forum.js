(() => {
  // ── state ────────────────────────────────────────────────────────────────
  const state = {
    view: "latest", // latest | hot | featured
    category: "all", // "all" or category slug
    query: "",
    page: 1,
    pageSize: 10, // 超过 10 条就翻页，不再无限加载
    total: 0,
    topics: [],
    categories: [],
    stats: {},
    loading: false,
    loadingMore: false,
    topicRequestId: 0,
    detailRequestId: 0,
    error: "",
    currentUser: null, // { username, role } or null
  };

  // ── DOM refs (set after DOMContentLoaded) ─────────────────────────────────
  let els = {};
  let topicAbortController;

  // ── helpers ───────────────────────────────────────────────────────────────
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "className") node.className = v;
      else if (k === "textContent") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v === false || v == null) continue; // boolean false / null / undefined 不设置
      else if (v === true) node.setAttribute(k, "");
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
    const headers = new Headers(opts.headers || {});
    // Let the browser add the multipart boundary for image uploads. Supplying
    // application/json here makes Django receive an empty request.FILES.
    if (!(opts.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const res = await fetch(url, {
      credentials: "same-origin",
      ...opts,
      headers,
    });
    return res;
  }

  function showToast(msg, type = "info") {
    const toast = document.querySelector("#forum-toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `forum-toast show ${type}`;
    if (type === "success") window.KflowXiaok?.decorateToast(toast);
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      toast.className = "forum-toast";
    }, 3200);
  }

  function getCsrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  // ── Markdown 渲染管线 ────────────────────────────────────────────────────────
  // marked(GFM) 解析 → DOMPurify 消毒 → 后处理（代码块外壳 / 表格滚动容器 / @提及）
  // → Prism 按需懒加载高亮。
  //
  // 依赖本地化在 /static/vendor/markdown/：CDN 在国内不可达，且能复用 pages.py 的
  // ?v=<hash> + immutable 缓存。marked + DOMPurify 常驻（合计 gzip 约 19KB）；
  // Prism 只在正文真的出现代码块时才下载，没有代码的页面不用为它付 26KB。
  const MD_VENDOR = "/static/vendor/markdown/";
  const MD_MODE_KEY = "kflow.forum.md.mode";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  /** 只放行 https 与站内图片接口，挡掉 javascript: / data: / 协议相对地址。 */
  function safeMarkdownUrl(url) {
    const value = String(url ?? "").trim();
    if (!value) return "";
    if (/^[a-z][a-z0-9+.\-]*:/i.test(value)) {
      return /^https?:\/\//i.test(value) ? value : "";
    }
    if (value.startsWith("//")) return "";
    if (value.startsWith("/")) {
      return value.startsWith("/api/forum/images/") ? value : "";
    }
    return "";
  }

  // 三个依赖都不进首屏 <script>：帖子列表渲染的是纯文本摘要，用不到 Markdown。
  // 页面空闲时预热，真要渲染正文时再兜底加载（最多一次往返，且已预热过基本命中缓存）。
  const MD_LIBS = ["marked.min.js", "purify.min.js", "marked-footnote.min.js"];
  let markdownLibs = null;

  function ensureMarkdownLibs() {
    if (window.marked && window.DOMPurify) return Promise.resolve();
    if (markdownLibs) return markdownLibs;
    markdownLibs = MD_LIBS.reduce(
      (chain, file) =>
        chain.then(
          () =>
            new Promise((resolve) => {
              const script = document.createElement("script");
              script.src = MD_VENDOR + file;
              script.async = false; // 动态插脚本时保证按插入顺序执行
              script.onload = resolve;
              script.onerror = resolve; // 单个失败不拖住其余，渲染层会退化
              document.head.appendChild(script);
            }),
        ),
      Promise.resolve(),
    );
    return markdownLibs;
  }

  function warmMarkdownLibs() {
    const run = () => ensureMarkdownLibs().catch(() => {});
    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(run, { timeout: 3000 });
    } else {
      window.setTimeout(run, 800);
    }
  }

  function markdownEngine() {
    const marked = window.marked;
    if (!marked) return null;
    if (marked.__kflowReady) return marked;
    marked.setOptions({ gfm: true, breaks: true });
    // 脚注不在 GFM 规范里，靠扩展补（[^1] / [^1]: 说明）
    if (typeof window.markedFootnote === "function") {
      marked.use(window.markedFootnote());
    }
    marked.use({
      renderer: {
        // 裸 HTML 一律转义成文本：正文来源不可信，不需要任何标签能力
        html(html) {
          return escapeHtml(html);
        },
        link(href, title, text) {
          const url = safeMarkdownUrl(href);
          if (!url) return String(text ?? "");
          const external = /^https?:\/\//i.test(url);
          return `<a href="${escapeHtml(url)}"${title ? ` title="${escapeHtml(title)}"` : ""}${external ? ' target="_blank" rel="noopener noreferrer nofollow"' : ""}>${text}</a>`;
        },
        image(href, title, text) {
          const url = safeMarkdownUrl(href);
          if (!url) return escapeHtml(text || "");
          return `<img src="${escapeHtml(url)}" alt="${escapeHtml(text || "")}"${title ? ` title="${escapeHtml(title)}"` : ""} loading="lazy" decoding="async">`;
        },
        code(code, infostring) {
          const lang = String(infostring || "").trim().split(/\s+/)[0];
          const cls = /^[\w+#.\-]+$/.test(lang) ? ` class="language-${lang}"` : "";
          return `<pre><code${cls}>${escapeHtml(String(code ?? ""))}</code></pre>\n`;
        },
      },
    });
    marked.__kflowReady = true;
    return marked;
  }

  let prismPromise = null;
  function ensurePrism() {
    if (window.Prism && window.Prism.highlightElement) return Promise.resolve(window.Prism);
    if (prismPromise) return prismPromise;
    // 手动模式：禁止 Prism 加载完就扫描整个文档，高亮时机由我们自己控制
    window.Prism = window.Prism || {};
    window.Prism.manual = true;
    prismPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = MD_VENDOR + "prism.min.js";
      script.async = true;
      script.onload = () => resolve(window.Prism);
      script.onerror = () => {
        prismPromise = null;
        reject(new Error("Prism 加载失败"));
      };
      document.head.appendChild(script);
    });
    return prismPromise;
  }

  // 站内图片的宽高缓存：渲染时写出 width/height，图片加载完不再把正文顶下去（CLS）
  const IMAGE_SIZE_CACHE = new Map();

  function rememberImageSizes(images) {
    for (const image of images || []) {
      if (!image || !image.url || !image.width || !image.height) continue;
      const match = String(image.url).match(/\/api\/forum\/images\/(\d+)/);
      if (match) IMAGE_SIZE_CACHE.set(match[1], { width: image.width, height: image.height });
    }
  }

  function applyImageSizes(root) {
    for (const img of root.querySelectorAll("img")) {
      const match = String(img.getAttribute("src") || "").match(/\/api\/forum\/images\/(\d+)/);
      if (!match) continue;
      const size = IMAGE_SIZE_CACHE.get(match[1]);
      if (!size) continue;
      img.width = size.width;
      img.height = size.height;
      img.style.aspectRatio = `${size.width} / ${size.height}`;
    }
  }

  const MENTION_RE = /(^|[^\w\u4e00-\u9fa5@])@([A-Za-z0-9_\-\u4e00-\u9fa5]{2,32})/g;

  function linkifyMentions(root) { window.KflowEditor?.linkify(root, root._mentionNames || []); }

  function decorateMarkdown(root) {
    for (const code of root.querySelectorAll("pre > code")) {
      const pre = code.parentElement;
      if (!pre || pre.parentElement?.classList.contains("forum-code-block")) continue;
      const lang = (String(code.className).match(/language-([\w+#.\-]+)/) || [])[1] || "";
      const wrap = document.createElement("div");
      wrap.className = "forum-code-block";
      const bar = document.createElement("div");
      bar.className = "forum-code-bar";
      if (lang) {
        const label = document.createElement("div");
        label.className = "forum-code-label";
        label.textContent = lang;
        bar.append(label);
      }
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "forum-code-copy";
      copy.textContent = "复制";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(code.textContent || "");
          copy.textContent = "已复制";
        } catch {
          copy.textContent = "复制失败";
        }
        setTimeout(() => {
          copy.textContent = "复制";
        }, 1600);
      });
      bar.append(copy);
      wrap.append(bar);
      pre.replaceWith(wrap);
      wrap.append(pre);
    }
    for (const table of root.querySelectorAll("table")) {
      if (table.parentElement?.classList.contains("forum-table-wrap")) continue;
      const wrap = document.createElement("div");
      wrap.className = "forum-table-wrap";
      table.replaceWith(wrap);
      wrap.append(table);
    }
    linkifyMentions(root);
    applyImageSizes(root);

    const blocks = root.querySelectorAll("pre > code[class*='language-']");
    if (blocks.length) {
      ensurePrism()
        .then((Prism) => {
          for (const block of blocks) {
            const lang = (String(block.className).match(/language-([\w+#.\-]+)/) || [])[1];
            if (lang && !Prism.languages[lang]) continue; // 未打包的语言，保持纯文本
            Prism.highlightElement(block);
          }
        })
        .catch(() => {});
    }
    return root;
  }

  function renderMarkdown(value) {
    const source = String(value ?? "");
    if (!source.trim()) return "<p></p>";
    const marked = markdownEngine();
    const plain = `<p>${escapeHtml(source).replaceAll("\n", "<br>")}</p>`;
    // 依赖没加载出来就退化成纯文本，绝不把未渲染的源码当 HTML 塞进页面
    if (!marked) return plain;
    let html;
    try {
      html = marked.parse(source);
    } catch {
      html = `<pre>${escapeHtml(source)}</pre>`;
    }

    if (!window.DOMPurify || !window.DOMPurify.sanitize) return plain;
    return window.DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      // target 不在 html profile 的默认属性表里（rel 在），外链要新开标签页得显式放行
      ADD_ATTR: ["target", "loading", "decoding"],
      FORBID_TAGS: ["style", "form", "iframe", "object", "embed", "base"],
      ALLOW_DATA_ATTR: false,
    });
  }

  // ── 线性图标（复用全局 kflowIcons）──

  function avatarEl(profile, size) {
    const span = el("span", { className: "row-user-avatar" });
    const initial = (profile?.display_name || profile?.username || "?").slice(0, 1).toUpperCase();
    span.textContent = initial;
    if (profile?.avatar_url) {
      const img = document.createElement("img");
      img.alt = "";
      img.style.display = "none";
      img.addEventListener("load", () => {
        if (img.naturalWidth >= 24 && img.naturalHeight >= 24) {
          span.replaceChildren(img);
          img.style.display = "";
        }
      });
      img.addEventListener("error", () => {
        // 加载失败，保留 initials
      });
      img.src = profile.avatar_url;
    }
    return span;
  }
  function iconEl(name, size) {
    return window.kflowIcons ? window.kflowIcons.el(name, size) : document.createElement("span");
  }
  const MD_PENDING_SOURCE = new WeakMap();

  function setRenderedMarkdown(container, value, mentions) {
    if (mentions !== undefined) container._mentionNames = mentions;
    // 依赖还在路上时先渲染纯文本占位，加载完再自动升级成完整 Markdown
    if (!(window.marked && window.DOMPurify)) {
      container.dataset.mdPending = "1";
      MD_PENDING_SOURCE.set(container, value);
      ensureMarkdownLibs().then(() => {
        const pending = MD_PENDING_SOURCE.get(container);
        MD_PENDING_SOURCE.delete(container);
        container.dataset.mdPending = "";
        if (pending != null && container.isConnected) setRenderedMarkdown(container, pending);
      });
    } else {
      container.dataset.mdPending = "";
      MD_PENDING_SOURCE.delete(container);
    }

    const parsed = document.createElement("template");
    parsed.innerHTML = renderMarkdown(value);
    parsed.content._mentionNames = container._mentionNames || [];
    // 代码块外壳 / 表格滚动容器 / Prism 高亮都在模板里做完，再交给 reconcile，
    // 这样后处理每次都作用于全新节点，不会在增量更新时被重复包裹。
    decorateMarkdown(parsed.content);
    // Keep unchanged blocks (including loaded images) in place while typing.
    // Only HTML produced by the escaped Markdown renderer enters this tree.
    function reconcile(target, source) {
      let current = target.firstChild;
      for (const next of Array.from(source.childNodes)) {
        const following = current?.nextSibling;
        if (!current) {
          target.append(next);
        } else if (current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) {
          current.replaceWith(next);
        } else if (!current.isEqualNode(next)) {
          if (current.nodeType === Node.TEXT_NODE) {
            current.nodeValue = next.nodeValue;
          } else {
            for (const attr of Array.from(current.attributes)) {
              if (!next.hasAttribute(attr.name)) current.removeAttribute(attr.name);
            }
            for (const attr of next.attributes) {
              if (current.getAttribute(attr.name) !== attr.value) current.setAttribute(attr.name, attr.value);
            }
            reconcile(current, next);
          }
        }
        current = following;
      }
      while (current) {
        const following = current.nextSibling;
        current.remove();
        current = following;
      }
    }
    reconcile(container, parsed.content);
  }

  function insertMarkdownAtCursor(textarea, text) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? textarea.value.length;
    const prefix = textarea.value.slice(0, start);
    const suffix = textarea.value.slice(end);
    const paddingBefore = prefix && !prefix.endsWith("\n") ? "\n" : "";
    const paddingAfter = suffix && !suffix.startsWith("\n") ? "\n" : "";
    textarea.value = `${prefix}${paddingBefore}${text}${paddingAfter}${suffix}`;
    const cursor = (prefix + paddingBefore + text).length;
    textarea.setSelectionRange(cursor, cursor);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  async function insertMarkdownImage(editor, file) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      showToast("图片不能超过 5MB", "error");
      return;
    }
    const textarea = editor.querySelector("textarea");
    if (!textarea) return;
    const button = editor.querySelector("[data-markdown-image]");
    if (button) button.disabled = true;
    try {
      const image = await uploadTopicImage(file);
      const alt = (file.name || "图片").replace(/[\[\]\r\n]/g, "").slice(0, 80) || "图片";
      insertMarkdownAtCursor(textarea, `![${alt}](${image.url})`);
      showToast("图片已插入正文", "success");
    } catch (error) {
      showToast(error.message || "图片上传失败，请重试", "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  // ── Markdown 编辑工具条 ──────────────────────────────────────────────────────

  const MD_TOOLBAR = [
    { action: "bold", label: "B", title: "加粗 (Ctrl+B)", style: "font-weight:700" },
    { action: "italic", label: "I", title: "斜体 (Ctrl+I)", style: "font-style:italic" },
    { action: "strike", label: "S", title: "删除线", style: "text-decoration:line-through" },
    { action: "h", label: "H3", title: "三级标题" },
    { action: "quote", label: "引用", title: "引用块" },
    { action: "ul", label: "列表", title: "无序列表" },
    { action: "ol", label: "编号", title: "有序列表" },
    { action: "code", label: "行内码", title: "行内代码" },
    { action: "fence", label: "代码块", title: "代码块" },
    { action: "link", label: "链接", title: "插入链接" },
    { action: "table", label: "表格", title: "插入表格" },
  ];

  function buildMarkdownToolbar(editor, textarea) {
    const host = editor.querySelector("[data-markdown-toolbar]");
    if (!host || host.childElementCount) return;
    for (const item of MD_TOOLBAR) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "markdown-tool";
      button.textContent = item.label;
      button.title = item.title;
      button.dataset.markdownAction = item.action;
      if (item.style) button.style.cssText = item.style;
      button.addEventListener("click", () => applyMarkdownAction(textarea, item.action));
      host.append(button);
    }
  }

  function commitTextarea(textarea) {
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function applyMarkdownAction(textarea, action) {
    const value = textarea.value;
    const start = textarea.selectionStart ?? value.length;
    const end = textarea.selectionEnd ?? value.length;
    const selected = value.slice(start, end);

    const wrap = (before, after, placeholder) => {
      const text = selected || placeholder;
      textarea.value = value.slice(0, start) + before + text + after + value.slice(end);
      const inner = start + before.length;
      textarea.focus();
      textarea.setSelectionRange(inner, inner + text.length);
      commitTextarea(textarea);
    };

    const togglePrefix = (prefix, pattern) => {
      const lineStart = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
      const nextBreak = value.indexOf("\n", end);
      const lineEnd = nextBreak === -1 ? value.length : nextBreak;
      const lines = (value.slice(lineStart, lineEnd) || "").split("\n");
      const on = lines.every((line) => !line.trim() || pattern.test(line));
      const next = lines
        .map((line, index) => {
          if (!line.trim()) return line;
          if (on) return line.replace(pattern, "");
          return typeof prefix === "function" ? prefix(index + 1, line) : prefix + line;
        })
        .join("\n");
      textarea.value = value.slice(0, lineStart) + next + value.slice(lineEnd);
      textarea.focus();
      textarea.setSelectionRange(lineStart, lineStart + next.length);
      commitTextarea(textarea);
    };

    const insertBlock = (text) => {
      const before = value.slice(0, start);
      const after = value.slice(end);
      const lead = before && !before.endsWith("\n") ? "\n" : "";
      const tail = after && !after.startsWith("\n") ? "\n" : "";
      textarea.value = `${before}${lead}${text}${tail}${after}`;
      const cursor = (before + lead + text).length;
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
      commitTextarea(textarea);
    };

    switch (action) {
      case "bold": return wrap("**", "**", "加粗");
      case "italic": return wrap("*", "*", "斜体");
      case "strike": return wrap("~~", "~~", "删除线");
      case "code": return wrap("`", "`", "code");
      case "link": return wrap("[", "](https://)", "链接文字");
      case "h": return togglePrefix("### ", /^#{1,6}\s+/);
      case "quote": return togglePrefix("> ", /^>\s?/);
      case "ul": return togglePrefix("- ", /^\s*[-*+]\s+/);
      case "ol": return togglePrefix((index, line) => `${index}. ${line}`, /^\s*\d+[.)]\s+/);
      case "fence": return insertBlock("```js\n\n```");
      case "table": return insertBlock("| 列 A | 列 B |\n| --- | --- |\n|  |  |");
      default: return;
    }
  }

  // 双栏需要横向空间：窄屏一律降级成「编辑 / 预览」单栏切换
  function isNarrow() {
    return Boolean(window.matchMedia?.("(max-width: 860px)").matches);
  }

  function defaultEditorMode() {
    let saved = "";
    try {
      saved = localStorage.getItem(MD_MODE_KEY) || "";
    } catch {}
    const mode = ["edit", "preview", "split"].includes(saved) ? saved : "split";
    return isNarrow() && mode === "split" ? "edit" : mode;
  }

  function setupMarkdownEditors(scope = document) {
    const editors = [];
    if (scope.matches?.("[data-markdown-editor]")) editors.push(scope);
    editors.push(...scope.querySelectorAll("[data-markdown-editor]"));
    for (const editor of editors) {
      if (editor.dataset.markdownEditorReady === "true") continue;
      const textarea = editor.querySelector("textarea");
      const preview = editor.querySelector("[data-markdown-preview]");
      const toggle = editor.querySelector("[data-markdown-toggle]");
      if (editor.hasAttribute("data-article-editor") && textarea && preview) {
        setupArticleEditor(editor, textarea, preview);
        continue;
      }
      if (!textarea || !preview || !toggle) continue;

      editor.dataset.markdownEditorReady = "true";

      // 结构保证：textarea 与 preview 必须同处一个 grid 容器，双栏时才能并排
      let body = editor.querySelector(".markdown-editor-body");
      if (!body) {
        body = document.createElement("div");
        body.className = "markdown-editor-body";
        editor.insertBefore(body, textarea);
        body.append(textarea, preview);
      }

      buildMarkdownToolbar(editor, textarea);

      let frame = 0;
      const render = () => {
        if (frame) return;
        frame = requestAnimationFrame(() => {
          frame = 0;
          setRenderedMarkdown(preview, textarea.value);
        });
      };

      // 发帖/编辑弹窗默认 600px 宽，双栏塞进去两边都会被挤扁，开启双栏时放宽它
      const modalBox = editor.closest(".modal-box");

      let mode = defaultEditorMode();
      const applyMode = (next) => {
        mode = next;
        editor.classList.toggle("is-split", next === "split");
        editor.classList.toggle("is-preview", next === "preview");
        modalBox?.classList.toggle("md-wide", next === "split");
        for (const button of editor.querySelectorAll("[data-markdown-mode]")) {
          const active = button.dataset.markdownMode === next;
          button.setAttribute("aria-pressed", String(active));
          button.classList.toggle("is-active", active);
        }
        if (next !== "edit") render();
      };

      for (const button of editor.querySelectorAll("[data-markdown-mode]")) {
        button.addEventListener("click", () => {
          const wanted = mode === button.dataset.markdownMode ? "edit" : button.dataset.markdownMode;
          applyMode(isNarrow() && wanted === "split" ? "preview" : wanted);
          try {
            localStorage.setItem(MD_MODE_KEY, mode);
          } catch {}
        });
      }

      // 实时预览：输入即渲染，合并到一帧内，长文也不会卡顿
      textarea.addEventListener("input", () => {
        if (mode !== "edit") render();
      });

      // 双栏滚动同步：按滚动比例映射，rAF 解锁避免双向互相触发抖动
      let locked = false;
      const syncScroll = (from, to) => {
        if (locked) return;
        locked = true;
        const fromMax = from.scrollHeight - from.clientHeight;
        const toMax = to.scrollHeight - to.clientHeight;
        if (fromMax > 1 && toMax > 1) to.scrollTop = (from.scrollTop / fromMax) * toMax;
        requestAnimationFrame(() => {
          locked = false;
        });
      };
      textarea.addEventListener("scroll", () => {
        if (mode === "split") syncScroll(textarea, preview);
      });
      preview.addEventListener("scroll", () => {
        if (mode === "split") syncScroll(preview, textarea);
      });

      const imageButton = editor.querySelector("[data-markdown-image]");
      const imageInput = editor.querySelector("[data-markdown-image-input]");
      if (imageButton && imageInput) {
        imageButton.addEventListener("click", () => imageInput.click());
        imageInput.addEventListener("change", () => {
          const [file] = imageInput.files || [];
          imageInput.value = "";
          insertMarkdownImage(editor, file);
        });
      }

      applyMode(mode);
    }
  }

  // Article editing and published content share setRenderedMarkdown and
  // .forum-markdown so preview formatting stays consistent with the article.
  function setupArticleEditor(editor, textarea, preview) {
    editor.dataset.markdownEditorReady = "true";
    editor.classList.add("article-editor");
    textarea.maxLength = 20000;
    textarea.spellcheck = false;
    preview.setAttribute("role", "region");
    preview.setAttribute("aria-label", "文章效果预览");
    preview.setAttribute("aria-live", "off");

    const modes = el("div", { className: "article-editor-modes", "aria-label": "编辑器显示模式" });
    const modeButtons = [];
    const formatBar = el("div", { className: "article-format-bar", role: "group", "aria-label": "正文格式" });
    const sourcePane = el("div", { className: "article-source-pane" },
      el("div", { className: "article-pane-heading", textContent: "Markdown 原文" }), textarea);
    const previewPane = el("div", { className: "article-preview-pane" },
      el("div", { className: "article-pane-heading", textContent: "文章效果 · 实时预览" }), preview);
    const panes = el("div", { className: "article-editor-panes" }, sourcePane, previewPane);
    const count = el("span", { className: "article-editor-count" });
    const syncInput = el("input", { type: "checkbox", checked: true });
    const syncLabel = el("label", { className: "article-sync-label" }, syncInput, "同步滚动");
    const footer = el("div", { className: "article-editor-status" }, count, syncLabel);
    const imageButton = editor.querySelector("[data-markdown-image]");
    const imageInput = editor.querySelector("[data-markdown-image-input]");

    let previewTimer;
    let composing = false;
    let lastPreviewValue;
    const modal = editor.closest(".modal-backdrop");
    const updateCount = () => {
      count.textContent = `${textarea.value.length.toLocaleString()} / 20,000 字符 · ${textarea.value.split("\n").length} 行`;
    };
    const cancelPreview = () => clearTimeout(previewTimer);
    const updatePreview = () => {
      cancelPreview();
      if (composing || editor.dataset.mode === "edit" || !editor.isConnected) return;
      if (modal && !modal.classList.contains("open")) return;
      const value = textarea.value;
      if (value === lastPreviewValue) return;
      const scrollTop = preview.scrollTop;
      setRenderedMarkdown(preview, value);
      preview.classList.toggle("is-empty", !value.trim());
      preview.scrollTop = scrollTop;
      lastPreviewValue = value;
    };
    const handleInput = (event) => {
      updateCount();
      cancelPreview();
      if (composing || event?.isComposing || editor.dataset.mode === "edit") return;
      previewTimer = setTimeout(updatePreview, 150);
    };
    const setMode = (mode) => {
      cancelPreview();
      editor.dataset.mode = mode;
      for (const button of modeButtons) {
        button.setAttribute("aria-pressed", String(button.dataset.editorMode === mode));
      }
      sourcePane.hidden = mode === "preview";
      previewPane.hidden = mode === "edit";
      formatBar.hidden = mode === "preview";
      syncLabel.hidden = mode !== "split";
      if (mode !== "edit") updatePreview();
    };
    for (const [mode, label] of [["edit", "Markdown"], ["split", "比对"], ["preview", "预览"]]) {
      const button = el("button", {
        type: "button", textContent: label, "data-editor-mode": mode,
        "aria-pressed": "false", onclick: () => setMode(mode),
      });
      modeButtons.push(button);
      modes.append(button);
    }

    function replaceText(start, end, text, selectionStart = start + text.length, selectionEnd = selectionStart) {
      if (textarea.value.length - (end - start) + text.length > textarea.maxLength) {
        showToast("正文不能超过 20,000 字符", "warn");
        return false;
      }
      textarea.focus();
      textarea.setRangeText(text, start, end, "end");
      textarea.setSelectionRange(selectionStart, selectionEnd);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }

    function cursorContext() {
      const lines = textarea.value.split("\n");
      const lineIndex = textarea.value.slice(0, textarea.selectionStart).split("\n").length - 1;
      const offset = lines.slice(0, lineIndex).reduce((sum, line) => sum + line.length + 1, 0);
      // Code samples must keep their literal list and table syntax.
      const inCode = lines.slice(0, lineIndex).filter(line => /^\s*```/.test(line)).length % 2 === 1;
      return { lines, lineIndex, offset, inCode };
    }

    function handleEnter(event) {
      const context = cursorContext();
      if (context.inCode) return;
      const { lines, lineIndex, offset } = context;
      const line = lines[lineIndex];
      if (textarea.selectionEnd > offset + line.length) return;
      if (textarea.selectionStart === textarea.selectionEnd && textarea.selectionStart === offset + line.length && /^\s*\|.*\|\s*$/.test(line)) {
        let first = lineIndex;
        while (first > 0 && /^\s*\|.*\|\s*$/.test(lines[first - 1])) first--;
        if (lineIndex > first && /^\|[\s\-:|]+\|$/.test(lines[first + 1].trim())) {
          const columns = lines[first].trim().slice(1, -1).split("|").length;
          const indent = line.match(/^\s*/)[0];
          const row = `\n${indent}| ${Array(columns).fill("内容").join(" | ")} |`;
          event.preventDefault();
          replaceText(textarea.selectionStart, textarea.selectionEnd, row);
          return;
        }
      }
      const match = line.match(/^(\s*)(?:(\d{1,9})([.)])|([-*]))([ \t]+)(.*)$/);
      if (!match) return;
      const [, indent, number, delimiter, bullet, spacing, text] = match;
      const markerLength = line.length - text.length;
      if (textarea.selectionStart < offset + markerLength) return;
      const next = number == null ? bullet : Number(number) + 1;
      if (text.trim() && number != null && next > 999999999) return;
      event.preventDefault();
      if (!text.trim()) {
        replaceText(offset, offset + line.length, "");
        return;
      }
      const start = textarea.selectionStart;
      const prefix = `\n${indent}${next}${number == null ? "" : delimiter}${spacing}`;
      const tail = textarea.value.slice(textarea.selectionEnd).split("\n");
      if (number != null) {
        // Inserting in the middle of a list shifts the subsequent sibling items.
        let followingNumber = next + 1;
        for (let i = 1; i < tail.length; i++) {
          const item = tail[i].match(/^(\s*)(\d{1,9})([.)])([ \t]+)(.*)$/);
          if (!item || item[1] !== indent || item[3] !== delimiter || followingNumber > 999999999) break;
          tail[i] = `${indent}${followingNumber++}${delimiter}${item[4]}${item[5]}`;
        }
      }
      replaceText(start, textarea.value.length, prefix + tail.join("\n"), start + prefix.length);
    }

    function formatSelection(action) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const selection = textarea.value.slice(start, end);
      let before = "", after = "", content = selection;
      switch (action) {
        case "bold": before = "**"; after = "**"; content ||= "加粗文字"; break;
        case "italic": before = "*"; after = "*"; content ||= "斜体文字"; break;
        case "strike": before = "~~"; after = "~~"; content ||= "删除文字"; break;
        case "heading": before = "## "; content ||= "小标题"; break;
        case "quote": before = "> "; content = (content || "引用内容").replace(/\n/g, "\n> "); break;
        case "list": before = "- "; content = (content || "列表内容").replace(/\n/g, "\n- "); break;
        case "ordered": before = "1. "; content = (content || "列表内容").split("\n").map((line, i) => i ? `${i + 1}. ${line}` : line).join("\n"); break;
        case "code": before = "```text\n"; after = "\n```"; content ||= "在这里输入代码"; break;
        case "link": before = "["; after = "](https://example.com)"; content ||= "链接文字"; break;
        case "table": content = "| 标题 | 标题 |\n| --- | --- |\n| 内容 | 内容 |"; break;
        default: return;
      }
      if (["heading", "quote", "list", "ordered", "code", "table"].includes(action)) {
        if (start && textarea.value[start - 1] !== "\n") before = "\n" + before;
        if (end < textarea.value.length && textarea.value[end] !== "\n") after += "\n";
      }
      const replacement = before + content + after;
      if (action === "table") replaceText(start, end, replacement);
      else replaceText(start, end, replacement, start + before.length, start + before.length + content.length);
    }
    for (const [action, label, title] of [
      ["bold", "B", "加粗（Ctrl / ⌘ + B）"], ["italic", "I", "斜体（Ctrl / ⌘ + I）"],
      ["heading", "H", "二级标题"], ["strike", "S", "删除线"],
      ["list", "无序列表", "无序列表"], ["ordered", "有序列表", "有序列表"],
      ["quote", "引用", "引用"], ["code", "代码块", "代码块"],
      ["link", "链接", "插入链接（Ctrl / ⌘ + K）"], ["table", "表格", "插入表格"],
    ]) {
      const button = el("button", {
        type: "button", textContent: label, title, "aria-label": title,
        "data-format": action, onclick: () => formatSelection(action),
      });
      formatBar.append(button);
    }
    if (imageButton && imageInput) {
      formatBar.append(imageButton, imageInput);
      imageButton.addEventListener("click", () => imageInput.click());
      imageInput.addEventListener("change", () => {
        const [file] = imageInput.files || [];
        imageInput.value = "";
        insertMarkdownImage(editor, file);
      });
    }
    editor.replaceChildren(
      el("div", { className: "article-editor-toolbar" }, modes,
        el("span", { className: "article-editor-hint", textContent: "边写边看，所见即所得" })),
      formatBar, panes, footer,
    );
    textarea.addEventListener("input", handleInput);
    textarea.addEventListener("compositionstart", () => {
      composing = true;
      cancelPreview();
    });
    textarea.addEventListener("compositionend", () => {
      composing = false;
      handleInput();
    });
    editor.addEventListener("article-editor:resume", updatePreview);
    editor.addEventListener("article-editor:pause", cancelPreview);
    textarea.addEventListener("invalid", () => {
      if (editor.dataset.mode === "preview") setMode("edit");
    });
    textarea.addEventListener("keydown", (event) => {
      if (event.isComposing || event.keyCode === 229) return;
      if (!event.ctrlKey && !event.metaKey && !event.altKey) {
        if (event.key === "Enter" && !event.shiftKey) handleEnter(event);
      }
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      const action = { b: "bold", i: "italic", k: "link" }[event.key.toLowerCase()];
      if (action) {
        event.preventDefault();
        formatSelection(action);
      }
    });
    // Reset events fire before the browser restores textarea values.
    textarea.form?.addEventListener("reset", () => {
      cancelPreview();
      requestAnimationFrame(() => {
        composing = false;
        updateCount();
        setMode("split");
      });
    });
    let syncing = false;
    function syncScroll(source, target) {
      if (syncing || !syncInput.checked || editor.dataset.mode !== "split") return;
      const range = source.scrollHeight - source.clientHeight;
      if (range <= 0) return;
      syncing = true;
      target.scrollTop = source.scrollTop / range * (target.scrollHeight - target.clientHeight);
      requestAnimationFrame(() => { syncing = false; });
    }
    textarea.addEventListener("scroll", () => syncScroll(textarea, preview));
    preview.addEventListener("scroll", () => syncScroll(preview, textarea));
    updateCount();
    setMode("split");
  }

  // ── fetch current user ────────────────────────────────────────────────────
  async function fetchUser() {
    try {
      const res = await apiFetch("/api/account/me");
      if (!res.ok) return null;
      const data = await res.json();
      if (!data.loggedIn) return null;
      return {
        username: data.username,
        role: data.role || "user",
        adminLevel: Number(data.adminLevel || 0),
        isSuper: Boolean(data.isSuper),
      };
    } catch {
      return null;
    }
  }

  async function resolveInitialUser() {
    // header.js 已经发起了同一个请求时，复用它的结果，避免并发请求
    // 互相覆盖 state.currentUser。
    if (window.kflowAuthReady && typeof window.kflowAuthReady.then === "function") {
      return window.kflowAuthReady;
    }
    return fetchUser();
  }

  function renderAccount() {
    // 头部账户区由共享的 header.js 统一渲染，这里仅维护 state.currentUser
  }

  function renderReplyAuthState(container = document.querySelector("#topicDetailInline")) {
    if (!container) return;
    const replyForm = container.querySelector(".reply-form");
    if (replyForm) replyForm.style.display = state.currentUser ? "" : "none";
    const loginHint = container.querySelector(".reply-login-hint");
    if (loginHint) loginHint.style.display = state.currentUser ? "none" : "";
  }

  window.addEventListener("kflow:auth-changed", (event) => {
    state.currentUser = event.detail || null;
    renderReplyAuthState();
  });

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
  async function fetchTopics({ view, category, query, page, pageSize, signal }) {
    const params = new URLSearchParams({
      view,
      page,
      page_size: pageSize,
    });
    if (category && category !== "all") params.set("category", category);
    if (query) params.set("q", query);
    const res = await apiFetch(`/api/forum/topics?${params}`, { signal });
    if (!res.ok) {
      const error = new Error("fetch topics failed");
      error.status = res.status;
      throw error;
    }
    return await res.json();
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
      const on = btn.dataset.view === activeView;
      btn.classList.toggle("active", on);
      // daisyUI 的 tabs 组件用 .tab-active 表示选中态，两个类名要同步
      btn.classList.toggle("tab-active", on);
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
      renderPager(); // 页码越界时仍留一条回到其它页的路
      if (emptyEl) {
        emptyEl.style.display = "";
        const message = emptyEl.querySelector("p");
        if (message) message.textContent = state.error || "没有找到符合条件的话题";
        const reset = emptyEl.querySelector("button");
        if (reset) {
          reset.style.display = "";
          reset.textContent = state.error ? "重新加载" : "清除筛选条件";
          reset.onclick = state.error
            ? () => {
                state.page = 1;
                loadTopics();
              }
            : () => {
                state.error = "";
                handleClearFilter();
              };
        }
      }
      return;
    }
    if (emptyEl) {
      emptyEl.style.display = "none";
      const reset = emptyEl.querySelector("button");
      if (reset) {
        reset.style.display = "";
        reset.textContent = "清除筛选条件";
      }
    }

    feed.replaceChildren(...topics.map((topic, index) => {
      const card = buildTopicCard(topic);
      card.style.animationDelay = `${Math.min(index * 40, 400)}ms`;
      return card;
    }));

    renderPager();
  }

  // ── 分页器（每页 10 条，超过一页才显示） ──────────────────────────────────
  function totalPages() {
    return Math.max(1, Math.ceil((state.total || 0) / state.pageSize));
  }

  function pageNumbers() {
    const last = totalPages();
    const current = Math.min(Math.max(1, state.page), last);
    if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1);
    const pages = new Set([1, last, current]);
    if (current - 1 > 1) pages.add(current - 1);
    if (current + 1 < last) pages.add(current + 1);
    if (current <= 3) [2, 3, 4].forEach((n) => pages.add(n));
    if (current >= last - 2) [last - 3, last - 2, last - 1].forEach((n) => pages.add(n));
    const sorted = [...pages].filter((n) => n >= 1 && n <= last).sort((a, b) => a - b);
    const out = [];
    let prev = 0;
    for (const n of sorted) {
      if (prev && n - prev > 1) out.push("…");
      out.push(n);
      prev = n;
    }
    return out;
  }

  function renderPager() {
    const pager = els.pager;
    if (!pager) return;
    const last = totalPages();
    const current = Math.min(Math.max(1, state.page), last);
    if (!state.total || last <= 1 || state.error) {
      pager.hidden = true;
      pager.replaceChildren();
      return;
    }
    pager.hidden = false;

    const btn = (label, { page, disabled, active, ellipsis, aria }) => {
      if (ellipsis) return el("span", { className: "pager-ellipsis", textContent: "…" });
      const classes = ["btn", "btn-sm", "pager-btn"];
      if (active) classes.push("pager-btn-active");
      else classes.push("btn-ghost");
      if (disabled) classes.push("pager-btn-disabled");
      const node = el("button", {
        type: "button",
        className: classes.join(" "),
        textContent: label,
        disabled: disabled || undefined,
        "aria-label": aria || label,
        onclick: () => goToPage(page),
      });
      if (active) node.setAttribute("aria-current", "page");
      return node;
    };

    const children = [
      btn("上一页", { page: current - 1, disabled: current <= 1, aria: "上一页" }),
      ...pageNumbers().map((n) =>
        typeof n === "number"
          ? btn(String(n), { page: n, active: n === current, aria: `第 ${n} 页` })
          : btn("", { ellipsis: true }),
      ),
      btn("下一页", { page: current + 1, disabled: current >= last, aria: "下一页" }),
      el("span", {
        className: "pager-summary",
        textContent: `第 ${current} / ${last} 页 · 共 ${state.total} 个话题`,
      }),
    ];
    pager.replaceChildren(...children);
  }

  function goToPage(page) {
    const last = totalPages();
    const next = Math.min(Math.max(1, Number(page) || 1), last);
    if (next === state.page) return;
    state.page = next;
    syncPageToUrl(next);
    loadTopics();
    scrollToFeed();
  }

  function scrollToFeed() {
    const feed = els.topicFeed;
    if (!feed) return;
    const top = feed.getBoundingClientRect().top + window.scrollY - 72;
    window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
  }

  function syncPageToUrl(page) {
    try {
      const url = new URL(window.location.href);
      if (page > 1) url.searchParams.set("page", String(page));
      else url.searchParams.delete("page");
      window.history.replaceState(null, "", url);
    } catch {
      /* 忽略 URL 同步失败（不影响分页） */
    }
  }

  function initialPageFromUrl() {
    try {
      const raw = Number(new URL(window.location.href).searchParams.get("page"));
      return Number.isFinite(raw) && raw > 1 ? Math.floor(raw) : 1;
    } catch {
      return 1;
    }
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
        href: `/forum?topic=${topic.id}`,
        target: "_blank",
        rel: "noopener noreferrer",
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

  function openTopicDetail(topic, replyPage = 1) {
    const requestId = ++state.detailRequestId;
    const targetComment = new URLSearchParams(location.search).get("comment");
    const query = replyPage > 1 ? `?reply_page=${replyPage}&reply_page_size=30` : /^\d+$/.test(targetComment || "") ? `?comment=${targetComment}` : "";
    apiFetch(`/api/forum/topics/${topic.id}${query}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (requestId !== state.detailRequestId) return;
        const full = data.topic || topic;
        if (replyPage > 1) {
          full.replies_detail = [...(topic.replies_detail || []), ...(full.replies_detail || [])];
        }
        showDetailModal(full);
      })
      .catch((err) => {
        if (requestId === state.detailRequestId) {
          console.error("[topic detail] load failed:", err);
          showToast(`详情加载失败：${err?.message || err}`, "error");
        }
      });
  }

  function canManage(username) {
    return Boolean(
      state.currentUser &&
      (
        state.currentUser.username === username
        || (state.currentUser.role === "admin" && (state.currentUser.isSuper || state.currentUser.adminLevel >= 2))
      ),
    );
  }

  function canManageTopic(topic) {
    return Boolean(topic?.can_manage || canManage(topic?.author));
  }

  function topicPinButton(container, topic) {
    const user = state.currentUser;
    if (!user || user.role !== "admin" || !(user.isSuper || user.adminLevel >= 2)) return null;
    const control = el("button", {
      type: "button",
      className: "detail-moderation-button",
      textContent: topic.pinned ? "取消置顶" : "置顶",
      "aria-pressed": String(Boolean(topic.pinned)),
      onclick: async () => {
        control.disabled = true;
        try {
          const response = await apiFetch(`/api/forum/topics/${topic.id}/pin`, {
            method: "POST",
            body: JSON.stringify({ pinned: !topic.pinned }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.error || "置顶操作失败");
          topic.pinned = data.pinned;
          control.textContent = topic.pinned ? "取消置顶" : "置顶";
          control.setAttribute("aria-pressed", String(topic.pinned));
          syncTopicPinBadge(container, topic);
          showToast(topic.pinned ? "帖子已置顶" : "已取消置顶", "success");
          loadTopics();
        } catch (error) {
          showToast(error.message || "置顶操作失败，请重试", "error");
        } finally {
          control.disabled = false;
        }
      },
    });
    return control;
  }

  function syncTopicPinBadge(container, topic) {
    const meta = container.querySelector(".detail-meta");
    if (!meta) return;
    meta.querySelector(".detail-pin-badge")?.remove();
    if (topic.pinned) meta.append(el("span", {
      className: "detail-pin-badge",
      textContent: "置顶",
    }));
  }

  function openTopicEditor(container, topic) {
    const body = container.querySelector(".modal-body");
    if (!body || body.querySelector(".topic-edit-form")) return;

    const form = el("form", { className: "topic-edit-form" });
    const title = el("input", {
      type: "text",
      maxlength: "256",
      required: true,
      value: topic.title || "",
      "aria-label": "标题",
    });
    const tags = el("input", {
      type: "text",
      maxlength: "100",
      value: Array.isArray(topic.tags) ? topic.tags.join(", ") : (topic.tags || ""),
      placeholder: "标签，用逗号分隔（最多 5 个）",
      "aria-label": "标签",
    });
    const textarea = el("textarea", {
      className: "markdown-input",
      rows: "12",
      required: true,
      "aria-label": "正文",
    });
    textarea.value = topic.content || "";
    const imageButton = el("button", {
      type: "button",
      className: "markdown-image-button",
      textContent: "插入图片",
      "data-markdown-image": true,
    });
    const imageInput = el("input", {
      type: "file",
      className: "markdown-image-input",
      accept: "image/jpeg,image/png,image/webp,image/gif",
      "data-markdown-image-input": true,
    });
    const splitToggle = el("button", {
      type: "button",
      className: "markdown-toggle",
      textContent: "双栏",
      "data-markdown-mode": "split",
      "aria-pressed": "false",
    });
    const previewToggle = el("button", {
      type: "button",
      className: "markdown-toggle",
      textContent: "预览",
      "data-markdown-mode": "preview",
      "aria-pressed": "false",
    });
    const editor = el("div", { className: "markdown-editor", "data-markdown-editor": true, "data-article-editor": true },
      el("div", { className: "markdown-editor-toolbar" },
        el("span", { className: "markdown-toolbar", "data-markdown-toolbar": true }),
        el("span", { className: "markdown-editor-tools" }, imageButton, imageInput, splitToggle, previewToggle),
      ),
      el("div", { className: "markdown-editor-body" },
        textarea,
        el("div", { className: "forum-markdown markdown-preview", "data-markdown-preview": true, "aria-live": "polite" }),
      ),
    );
    const cancel = el("button", {
      type: "button",
      className: "btn-secondary",
      textContent: "取消",
      onclick: () => {
        form.remove();
        body.classList.remove("is-editing");
      },
    });
    const save = el("button", { type: "submit", className: "btn-primary", textContent: "保存修改" });
    form.append(
      el("label", { textContent: "标题" }), title,
      el("label", { textContent: "正文" }), editor,
      el("label", { textContent: "标签（可选）" }), tags,
      el("div", { className: "topic-edit-actions" }, cancel, save),
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        const response = await apiFetch(`/api/forum/topics/${topic.id}/manage`, {
          method: "PATCH",
          headers: { "X-CSRFToken": getCsrf() },
          body: JSON.stringify({ title: title.value, content: textarea.value, tags: tags.value }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "保存失败");
        showToast("文章已更新", "success");
        openTopicDetail({ id: topic.id });
      } catch (error) {
        showToast(error.message || "保存失败，请重试", "error");
        save.disabled = false;
      }
    });
    body.classList.add("is-editing");
    body.prepend(form);
    setupMarkdownEditors(form);
    title.focus();
  }

  async function reportForumTarget(targetType, targetId) {
    const reason = (window.prompt("举报原因：spam / abuse / copyright / other", "other") || "").trim().toLowerCase();
    if (!reason) return;
    if (!["spam", "abuse", "copyright", "other"].includes(reason)) {
      showToast("举报原因不合法", "warn");
      return;
    }
    const details = window.prompt("补充说明（可选，最多 500 字）", "") || "";
    try {
      const path = targetType === "topic"
        ? `/api/forum/topics/${targetId}/report`
        : `/api/forum/replies/${targetId}/report`;
      const response = await apiFetch(path, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrf() },
        body: JSON.stringify({ reason, details: details.slice(0, 500) }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "举报失败");
      showToast(data.duplicate ? "你已经举报过这条内容" : "举报已提交，感谢反馈", "success");
    } catch (error) {
      showToast(error.message || "举报失败，请重试", "error");
    }
  }

  function renderTopicActions(modal, topic) {
    const actions = modal.querySelector("#detailModerationActions");
    if (!actions) return;
    actions.replaceChildren();
    if (!state.currentUser) return;
    const pinControl = topicPinButton(modal, topic);
    if (pinControl) actions.append(pinControl);
    if (canManageTopic(topic)) {
      actions.append(
        el("button", {
          type: "button",
          className: "detail-moderation-button",
          textContent: "编辑",
          onclick: () => openTopicEditor(modal, topic),
        }),
        el("button", {
          type: "button",
          className: "detail-moderation-button danger",
          textContent: "删除",
          onclick: async () => {
            if (!window.confirm("确定删除这条话题吗？删除后将从社区隐藏。")) return;
            try {
              const response = await apiFetch(`/api/forum/topics/${topic.id}/manage`, {
                method: "DELETE",
                headers: { "X-CSRFToken": getCsrf() },
              });
              const data = await response.json().catch(() => ({}));
              if (!response.ok) throw new Error(data.error || "删除失败");
              state.topics = state.topics.filter((item) => item.id !== topic.id);
              state.total = Math.max(0, state.total - 1);
              closeDetailModal();
              renderTopics(state.topics, state.total);
              showToast("话题已删除", "success");
            } catch (error) {
              showToast(error.message || "删除失败，请重试", "error");
            }
          },
        }),
      );
    } else {
      actions.append(el("button", {
        type: "button",
        className: "detail-moderation-button",
        textContent: "举报",
        onclick: () => reportForumTarget("topic", topic.id),
      }));
    }
  }

  function showDetailModal(topic) {
    try {
      // 把 modal 内容克隆到 inline 详情区，替换弹出窗体验
      const sourceBox = els.detailModal?.querySelector(".modal-detail");
      if (!sourceBox) {
        console.warn("[topic detail] #detailModal/.modal-detail not found");
        return;
      }
      const inline = document.querySelector("#topicDetailInline");
      if (!inline) {
        console.warn("[topic detail] #topicDetailInline not found");
        return;
      }

      // 把 modal 内部克隆一份
      inline.replaceChildren(sourceBox.cloneNode(true));
      inline.hidden = false;

      // 现在 inline 里就是 modal-box 内容，再给它一个 inline 渲染的 wrapper
      inline.classList.add("active");
      inline.scrollIntoView({ behavior: "smooth", block: "start" });

      // 同步 URL（让浏览器后退按钮能回到列表）
      const url = new URL(window.location.href);
      url.searchParams.set("topic", String(topic.id));
      if (window.location.href !== url.toString()) {
        history.pushState({ topic: topic.id }, "", url.toString());
      }

      // 重新渲染到克隆出的 inline DOM 中（modal 中的 .modal-box 是被克隆对象）
      renderInlineDetail(inline, topic);
    } catch (err) {
      console.error("[topic detail] render failed:", err);
      showToast(`详情渲染失败：${err?.message || err}`, "error");
    }
  }

  function renderInlineDetail(container, topic) {
    // header
    const titleEl = container.querySelector(".detail-title");
    if (titleEl) titleEl.textContent = topic.title;

    // 专注模式：插入返回按钮和面包屑
    const inFocusMode = document.body.classList.contains("focus-mode");
    if (inFocusMode) {
      const headerActions = container.querySelector(".detail-header-actions");
      if (headerActions && !headerActions.querySelector(".focus-back-btn")) {
        const backBtn = el("a", {
          className: "focus-back-btn",
          href: "/forum",
          textContent: "← 返回列表",
        });
        headerActions.prepend(backBtn);
      }
    }

    // 关闭按钮：回到列表（focus 模式下跳转到 /forum）
    const closeBtn = container.querySelector("#closeDetailModal");
    if (closeBtn) {
      closeBtn.onclick = (e) => {
        e.preventDefault();
        if (inFocusMode) {
          window.location.href = "/forum";
          return;
        }
        container.hidden = true;
        container.replaceChildren();
        container.classList.remove("active");
        // 清掉 URL 上的 ?topic= 参数
        const url = new URL(window.location.href);
        if (url.searchParams.has("topic")) {
          url.searchParams.delete("topic");
          history.pushState({}, "", url.toString());
        }
      };
    }

    renderTopicActionsInline(container, topic);

    const metaEl = container.querySelector(".detail-meta");
    const identity = topic.author_profile || {
      display_name: topic.author,
      username: topic.author,
    };
    if (metaEl) {
      const authorName = identity.display_name || topic.author;
      const authorLink = el("a", {
        className: "detail-author-link",
        href: `/forum/user/${encodeURIComponent(identity.username || topic.author)}`,
        "aria-label": `查看 ${authorName} 的个人主页`,
      }, avatarEl(identity), el("span", {
        className: "detail-author-name",
        textContent: authorName,
      }));
      metaEl.replaceChildren(authorLink, el("span", {
        className: "detail-topic-info",
        textContent: `· ${topic.category} · ${topic.active}${topic.boosted ? " · 加热中" : ""}`,
      }));
    }
    syncTopicPinBadge(container, topic);

    // share button
    const shareBtn = container.querySelector("#detailShareBtn");
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

    // 加热按钮（仅作者可加热）
    const boostToggle = container.querySelector("#detailBoostToggle");
    const boostDropdown = container.querySelector("#detailBoostDropdown");
    if (boostToggle && boostDropdown) {
      const canBoost = state.currentUser
        && state.currentUser.username === topic.author
        && topic.status === "open";
      boostToggle.hidden = !canBoost;
      if (canBoost) {
        boostToggle.onclick = async (e) => {
          e.preventDefault();
          e.stopPropagation();
          const willOpen = boostDropdown.hidden;
          if (willOpen) {
            // 打开面板：拉余额 + 拉档位
            await renderBoostDropdown(boostDropdown, topic);
            boostDropdown.hidden = false;
            // 触发下滑动画
            requestAnimationFrame(() => {
              boostDropdown.classList.add("open");
            });
          } else {
            boostDropdown.classList.remove("open");
            setTimeout(() => { boostDropdown.hidden = true; }, 260);
          }
        };
      }
    }

    // project links
    const linksEl = container.querySelector("#detailLinks");
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
    const imagesEl = container.querySelector("#detailImages");
    if (imagesEl) {
      imagesEl.replaceChildren();
      rememberImageSizes(topic.images);
      for (const image of topic.images || []) {
        const img = el("img", {
          src: image.url,
          alt: "作品截图",
          loading: "lazy",
        });
        if (image.width && image.height) {
          img.width = image.width;
          img.height = image.height;
        }
        img.addEventListener("click", () => window.open(image.url, "_blank", "noopener"));
        imagesEl.append(img);
      }
    }

    // boost panel (author only) — 改为头部按钮触发，新代码无 inline boost panel
    // renderBoostPanelInline 不再调用，避免 ReferenceError

    const bodyEl = container.querySelector(".detail-body");
    if (bodyEl) {
      setRenderedMarkdown(bodyEl, topic.content || "", topic.mention_usernames || []);
    }

    // replies
    const repliesEl = container.querySelector(".detail-replies");
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
          const row = el("div", { className: "reply-row", id: `forum-reply-${r.id}` });
          const ava = el("div", { className: "reply-avatar" });
          const initials = r.initials || "?";
          const avatarUrl = r.author_profile?.avatar_url;
          ava.textContent = initials;
          if (avatarUrl) {
            const probe = document.createElement("img");
            probe.alt = "";
            probe.style.display = "none";
            probe.addEventListener("load", () => {
              if (probe.naturalWidth >= 24 && probe.naturalHeight >= 24) {
                ava.replaceChildren(probe);
                probe.style.display = "";
              }
            });
            probe.addEventListener("error", () => {});
            probe.src = avatarUrl;
          }
          const rBody = el("div", { className: "reply-body" });
          const identity2 = r.author_profile || {
            display_name: r.author,
            username: r.author,
            initials: r.initials || "?",
          };
          const authorLink = el("a", {
            className: "reply-author",
            href: `/forum/user/${encodeURIComponent(identity2.username || r.author)}`,
            textContent: identity2.display_name || r.author,
          });
          const showcase = identity2.showcase;
          const showcaseChip = showcase
            ? (() => {
                const chip = el("span", {
                  className: `showcase-chip tier-${showcase.tier}`,
                  title: `佩戴勋章：${showcase.name}`,
                });
                chip.append(iconEl(showcase.icon, 10), el("span", { textContent: showcase.name }));
                return chip;
              })()
            : null;
          const rTime = el("span", {
            className: "reply-time",
            textContent: r.created_at
              ? new Date(r.created_at).toLocaleString("zh-CN")
              : "",
          });
          const rContent = el("div", {
            className: "reply-content forum-markdown",
          });
          setRenderedMarkdown(rContent, r.content || "", r.mention_usernames || []);
          let replyImages = null;
          if (r.images?.length) { replyImages = el("div", {className:"forum-reply-images"}); for (const image of r.images) replyImages.append(el("a",{href:image.url,target:"_blank",rel:"noopener"},el("img",{src:image.url,alt:"评论图片",loading:"lazy"}))); }

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
          if (state.currentUser) {
            if (canManage(r.author)) {
              rFoot.append(
                el("button", {
                  type: "button",
                  className: "reply-moderation-button",
                  textContent: "编辑",
                  onclick: async () => {
                    const content = window.prompt("修改回复", r.content || "");
                    if (content == null) return;
                    try {
                      const response = await apiFetch(`/api/forum/replies/${r.id}/manage`, {
                        method: "PATCH",
                        headers: { "X-CSRFToken": getCsrf() },
                        body: JSON.stringify({ content }),
                      });
                      const data = await response.json().catch(() => ({}));
                      if (!response.ok) throw new Error(data.error || "保存失败");
                      showToast("回复已更新", "success");
                      openTopicDetail({ id: topic.id });
                    } catch (error) {
                      showToast(error.message || "保存失败，请重试", "error");
                    }
                  },
                }),
                el("button", {
                  type: "button",
                  className: "reply-moderation-button danger",
                  textContent: "删除",
                  onclick: async () => {
                    if (!window.confirm("确定删除这条回复吗？")) return;
                    try {
                      const response = await apiFetch(`/api/forum/replies/${r.id}/manage`, {
                        method: "DELETE",
                        headers: { "X-CSRFToken": getCsrf() },
                      });
                      const data = await response.json().catch(() => ({}));
                      if (!response.ok) throw new Error(data.error || "删除失败");
                      showToast("回复已删除", "success");
                      openTopicDetail({ id: topic.id });
                    } catch (error) {
                      showToast(error.message || "删除失败，请重试", "error");
                    }
                  },
                }),
              );
            } else {
              rFoot.append(el("button", {
                type: "button",
                className: "reply-moderation-button",
                textContent: "举报",
                onclick: () => reportForumTarget("reply", r.id),
              }));
            }
          }

          // 头部行：作者名 + 展示成就 chip + 时间戳（chip 紧贴作者右侧）
          const headRow = el("div", { className: "reply-head-row" });
          headRow.append(authorLink);
          if (showcaseChip) headRow.append(showcaseChip);
          headRow.append(rTime);
          rBody.append(headRow, rContent, ...(replyImages ? [replyImages] : []), rFoot);
          row.append(ava, rBody);
          repliesEl.append(row);
        }
      }
    }

    const repliesMore = container.querySelector("#detailRepliesMore");
    if (repliesMore) {
      repliesMore.hidden = !topic.reply_has_next;
      repliesMore.disabled = false;
      repliesMore.onclick = () => {
        if (repliesMore.disabled) return;
        repliesMore.disabled = true;
        openTopicDetail(topic, (Number(topic.reply_page) || 1) + 1);
      };
    }

    // reply form visibility
    renderReplyAuthState(container);

    // 重新绑定回复表单提交事件（cloneNode 不会带事件）
    const replyFormEl = container.querySelector("#replyForm");
    if (replyFormEl) {
      replyFormEl.onsubmit = async (e) => {
        e.preventDefault();
        const textarea = replyFormEl.querySelector("#replyTextarea");
        const content = (textarea?.value || "").trim();
        if (!content) return;
        try {
          const response = await apiFetch(`/api/forum/topics/${topic.id}/replies`, {
            method: "POST",
            headers: { "X-CSRFToken": getCsrf() },
            body: JSON.stringify({ content }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.error || "发表失败");
          if (textarea) textarea.value = "";
          showToast("回复已发布", "success");
          openTopicDetail({ id: topic.id });
        } catch (error) {
          showToast(error.message || "发表失败，请重试", "error");
        }
      };
    }

    // The inline detail is cloned at runtime, so it needs its own editor wiring.
    setupMarkdownEditors(container);

    window.KflowForumExtras?.render(container, topic, {currentUser: state.currentUser, onSent: () => openTopicDetail({id:topic.id}), toast:showToast});
    container.dataset.topicId = topic.id;
  }

  function renderTopicActionsInline(container, topic) {
    const actions = container.querySelector("#detailModerationActions");
    if (!actions) return;
    actions.replaceChildren();
    if (!state.currentUser) return;
    const pinControl = topicPinButton(container, topic);
    if (pinControl) actions.append(pinControl);
    if (canManageTopic(topic)) {
      actions.append(
        el("button", {
          type: "button",
          className: "detail-moderation-button",
          textContent: "编辑",
          onclick: () => openTopicEditor(container, topic),
        }),
        el("button", {
          type: "button",
          className: "detail-moderation-button danger",
          textContent: "删除",
          onclick: async () => {
            if (!window.confirm("确定删除这个话题吗？")) return;
            try {
              const response = await apiFetch(`/api/forum/topics/${topic.id}/manage`, {
                method: "DELETE",
                headers: { "X-CSRFToken": getCsrf() },
              });
              const data = await response.json().catch(() => ({}));
              if (!response.ok) throw new Error(data.error || "删除失败");
              showToast("话题已删除", "success");
              container.hidden = true;
              container.replaceChildren();
              container.classList.remove("active");
              // 清掉 URL 上的 ?topic= 参数
              const delUrl = new URL(window.location.href);
              if (delUrl.searchParams.has("topic")) {
                delUrl.searchParams.delete("topic");
                history.pushState({}, "", delUrl.toString());
              }
              loadTopics(true);
            } catch (error) {
              showToast(error.message || "删除失败，请重试", "error");
            }
          },
        }),
      );
    } else {
      actions.append(el("button", {
        type: "button",
        className: "detail-moderation-button",
        textContent: "举报",
        onclick: () => reportForumTarget("topic", topic.id),
      }));
    }
  }

  // 兼容保留旧函数名，但直接重定向到 inline
  function showDetailModal_old(topic) {
    showDetailModal(topic);
  }

  // ── boost dropdown (作者点击加热按钮时的下滑面板) ──────────────────────────
  async function renderBoostDropdown(panel, topic) {
    const balanceEl = panel.querySelector("#boostBalance");
    const tierListEl = panel.querySelector("#boostTierList");
    if (!tierListEl) return;

    // 1. 拉余额
    let balance = null;
    try {
      const res = await apiFetch("/api/points/me");
      const data = await res.json().catch(() => ({}));
      balance = data.balance ?? null;
    } catch {
      balance = null;
    }
    if (balanceEl) balanceEl.textContent = balance == null ? "--" : Math.floor(balance);

    // 2. 拉档位
    // API 返回 tiers 是对象 {small:{...}, medium:{...}, large:{...}}
    let tiers = [];
    try {
      const res = await apiFetch("/api/forum/boosts/tiers");
      const data = await res.json().catch(() => ({}));
      const raw = data.tiers || {};
      // 兼容对象或数组
      if (Array.isArray(raw)) {
        tiers = raw;
      } else if (typeof raw === "object") {
        // 保留档位大小顺序：small < medium < large
        const order = ["small", "medium", "large"];
        tiers = order
          .filter((code) => raw[code])
          .map((code) => ({ code, ...raw[code] }));
      }
    } catch {
      tiers = [];
    }

    tierListEl.replaceChildren();
    if (tiers.length === 0) {
      tierListEl.append(el("div", { className: "muted small", textContent: "暂无可用档位" }));
      return;
    }
    const row = el("div", { className: "boost-tier-row" });
    for (const tier of tiers) {
      const cost = tier.points_cost ?? tier.cost ?? 0;
      const cannotAfford = balance !== null && balance < cost;
      const viewBonus = tier.view_bonus || 0;
      const btn = el("button", {
        type: "button",
        className: "boost-tier-btn" + (cannotAfford ? " is-disabled" : ""),
        disabled: cannotAfford,
        onclick: async () => {
          if (cannotAfford) {
            showToast(`余额不足：需要 ${cost} K，当前 ${Math.floor(balance || 0)} K`, "error");
            return;
          }
          if (!window.confirm(`确认花费 ${cost} K 积分加热「${tier.label || tier.name || tier.code}」？\n将立即增加 ${viewBonus} 浏览量。`)) return;
          const idempotency = `boost-${topic.id}-${tier.code}-${Date.now()}`;
          try {
            const response = await apiFetch(`/api/forum/topics/${topic.id}/boost`, {
              method: "POST",
              headers: { "X-CSRFToken": getCsrf(), "X-Idempotency-Key": idempotency },
              body: JSON.stringify({ tier: tier.code, idempotency_key: idempotency }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || "加热失败");
            const vb = Number(data.view_bonus || viewBonus || 0);
            showToast(`加热成功：${tier.label || tier.name || tier.code}，浏览量 +${vb}`, "success");
            // 关闭面板 + 重新拉详情（更新视图数 + boost 状态）
            const dropdown = panel;
            dropdown.classList.remove("open");
            setTimeout(() => { dropdown.hidden = true; }, 260);
            openTopicDetail({ id: topic.id });
          } catch (error) {
            showToast(error.message || "加热失败，请重试", "error");
          }
        },
      });
      const items = [
        el("div", { className: "boost-tier-name", textContent: tier.label || tier.name || tier.code }),
        el("div", { className: "boost-tier-cost", textContent: `${cost} K` }),
        el("div", { className: "boost-tier-bonus", textContent: `+${viewBonus} 浏览` }),
      ];
      if (cannotAfford) {
        items.push(el("div", { className: "boost-tier-poor", textContent: "余额不足" }));
      }
      btn.append(...items);
      row.append(btn);
    }
    tierListEl.append(row);
  }

  // ── boost panel ───────────────────────────────────────────────────────────
  async function renderBoostPanel(modal, topic, requestId) {
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
    if (requestId !== state.detailRequestId || modal.dataset.topicId !== String(topic.id)) return;

    let tiers;
    try {
      const res = await apiFetch("/api/forum/boosts/tiers");
      tiers = (await res.json()).tiers || {};
    } catch {
      return;
    }
    if (requestId !== state.detailRequestId || modal.dataset.topicId !== String(topic.id)) return;

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
          const idempotencyKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          try {
            const res = await apiFetch(`/api/forum/topics/${topic.id}/boost`, {
              method: "POST",
              headers: { "X-CSRFToken": getCsrf() },
              body: JSON.stringify({ tier: key, idempotency_key: idempotencyKey }),
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
      // 游客：光弹一句 toast 不够。站内 12 个页面的「发帖晒作品」都是
      // `location.href='/forum?compose=1'`，游客点过来只看到一个转瞬即逝的
      // 提示，跟「点了没反应」没区别。直接送去登录，登录后按 next 回来自动开编辑器。
      location.href = "/login?next=" + encodeURIComponent("/forum?compose=1");
      return;
    }
    const modal = els.newTopicModal;
    if (!modal) return;
    modal.classList.add("open");
    modal.querySelectorAll("[data-article-editor]").forEach((editor) => {
      editor.dispatchEvent(new Event("article-editor:resume"));
    });
    document.body.style.overflow = "hidden";
  }

  function closeNewTopicModal() {
    const modal = els.newTopicModal;
    if (!modal) return;
    modal.classList.remove("open");
    modal.querySelectorAll("[data-article-editor]").forEach((editor) => {
      editor.dispatchEvent(new Event("article-editor:pause"));
    });
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
    rememberImageSizes([data.image]);
    return data.image; // { id, url, width, height }
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
          poll: window.KflowForumExtras?.collectPoll() || null,
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
  async function loadTopics(retried = false) {
    const requestId = ++state.topicRequestId;
    topicAbortController?.abort();
    const controller = new AbortController();
    topicAbortController = controller;
    const request = {
      view: state.view,
      category: state.category,
      query: state.query,
      page: state.page,
      pageSize: state.pageSize,
    };
    syncPageToUrl(request.page);
    state.loading = true;
    if (els.topicFeed) els.topicFeed.classList.add("loading");
    try {
      const data = await fetchTopics({ ...request, signal: controller.signal });
      if (requestId !== state.topicRequestId) return;
      const items = data.items || [];
      const total = data.total || 0;
      const lastPage = Math.max(1, Math.ceil(total / state.pageSize));
      // ?page=N 越界（比如链接过期、筛选后变少）时回到最后一页，别停在空列表
      if (!retried && !items.length && total > 0 && request.page > lastPage) {
        state.page = lastPage;
        return loadTopics(true);
      }
      state.error = "";
      state.topics = items;
      state.total = total;
      state.page = Number(data.page) || request.page;
      renderTopics(state.topics, state.total);
    } catch {
      if (requestId !== state.topicRequestId) return;
      state.error = "话题加载失败，请点击重试";
      state.topics = [];
      state.total = 0;
      renderTopics(state.topics, state.total);
    } finally {
      if (requestId === state.topicRequestId) {
        topicAbortController = null;
        state.loading = false;
        if (els.topicFeed) els.topicFeed.classList.remove("loading");
      }
    }
  }

  async function loadAll({ detailTopicId = 0, compose = false } = {}) {
    // Auth is needed for personalised likes and edit controls. Categories and
    // stats load independently, so a slow sidebar cannot delay the main view.
    const userReady = resolveInitialUser().then((user) => {
      state.currentUser = user;
      renderAccount(user);
      if (els.newTopicBtn) els.newTopicBtn.style.display = "";
      if (detailTopicId > 0) openTopicDetail({ id: detailTopicId });
      else if (compose) openNewTopic();
    });
    const sel = document.querySelector("[name=category]");
    const categoriesReady = fetchCategories().then((cats) => {
      state.categories = cats;
      renderCategories(cats, state.category);
      if (sel) {
        // Do not reset a user's selection if categories finish loading again.
        const selected = sel.value;
        sel.replaceChildren(el("option", { value: "", textContent: "选择分类…" }));
        for (const cat of cats) {
          sel.append(el("option", { value: cat.slug, textContent: cat.name }));
        }
        sel.value = cats.some((cat) => cat.slug === selected) ? selected : "";
      }
    });
    const statsReady = fetchStats().then((data) => {
      state.stats = data;
      renderStats(data);
    });
    // Detail links never need the hidden topic list. Compose links open while
    // the background list is loading, keeping the form usable on slow networks.
    const topicsReady = detailTopicId > 0 ? Promise.resolve() : userReady.then(async () => {
      await loadTopics();
      renderCategories(state.categories, state.category);
    });
    await Promise.all([userReady, categoriesReady, statsReady, topicsReady]);
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
      pager: document.querySelector("#topicPager"),
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

    // 分页由 renderPager() 渲染的按钮驱动（goToPage），这里只需支持键盘左右翻页
    document.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || e.target?.isContentEditable) return;
      if (document.querySelector("#topicDetailInline:not([hidden])")) return;
      if (els.detailModal?.classList.contains("open")) return;
      if (els.newTopicModal?.classList.contains("open")) return;
      if (e.key === "ArrowLeft" && state.page > 1) goToPage(state.page - 1);
      else if (e.key === "ArrowRight" && state.page < totalPages()) goToPage(state.page + 1);
    });

    // 支持从 URL 的 ?page=N 直接进入某一页
    const urlPage = initialPageFromUrl();
    if (urlPage > 1) state.page = urlPage;

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
    const shouldCompose = Boolean(params.get("compose"));
    if (deepTopicId > 0) {
      // 进入专注模式：隐藏列表/工具栏/侧边栏/分类栏，只显示详情
      document.body.classList.add("focus-mode");
    }
    const deepQuery = params.get("q");
    if (deepQuery && els.searchInput) {
      els.searchInput.value = deepQuery;
      state.query = deepQuery;
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
    // Markdown 依赖不进首屏：列表只渲染纯文本摘要，空闲时预热，真要渲染正文再兜底加载
    warmMarkdownLibs();
    loadAll({ detailTopicId: deepTopicId, compose: shouldCompose });

    // 监听浏览器后退按钮：URL 上的 ?topic= 没了就关闭 inline 详情
    window.addEventListener("popstate", () => {
      const params = new URLSearchParams(location.search);
      const t = Number(params.get("topic"));
      const inline = document.querySelector("#topicDetailInline");
      if (!t && inline && !inline.hidden) {
        inline.hidden = true;
        inline.replaceChildren();
        inline.classList.remove("active");
      }
    });
  });
})();
