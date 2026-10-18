/* 沉浸式阅读 —— 全站通用
 *
 * 只做三件事：把正文提到全屏层、把旁支整棵隐藏、给一排可调字号/宽度/色调的按钮。
 * 不移动、不克隆 DOM（论坛详情和教程翻页都是 JS 重渲染的，克隆会失联），
 * 退出时按原样还原，页面自己的 JS 完全感知不到这段过程。
 *
 * 对外接口：window.kflowImmersive = { toggle, enter, exit, isActive }
 * 页面里若已有 #bookImmersiveButton（教程页），learn.js 会把点击转交给这里。
 */
(() => {
  "use strict";

  const STORE_KEY = "kflow-immersive-prefs";
  const ROOT_FLAG = "immersive-active";
  const HIDDEN_ATTR = "data-im-hidden";
  const ARTICLE_ATTR = "data-im-article";

  // 候选正文容器，按「语义精确度」排列：越靠前越像真正的正文。
  // 取第一个文字量达标的，而不是取最长的 —— 取最长会选到 main（整个页面外壳），
  // 把侧栏目录一起拖进沉浸视图。
  const CANDIDATES = [
    "#bookSpread",
    ".book-stage",
    ".book-page-right",
    // 术语页整页优先于内部正文块：只取 detail-body 会把标题弄丢
    ".glossary-detail",
    ".forum-markdown.detail-body",
    "#topicDetailInline",
    ".guide-content",
    "#newTopicModal .modal-body",
    "#topicDetailModal .modal-body",
    "main article",
    "article",
    "main",
  ];

  const WIDTHS = ["36rem", "42rem", "52rem", "68rem"];
  const TONES = ["auto", "cream", "green", "night"];

  const prefs = loadPrefs();
  let active = false;
  let target = null;
  let bar = null;
  let progress = null;
  let entry = null;
  let observer = null;
  let hiddenNodes = [];
  let savedInline = null;

  // ── 偏好存取 ──────────────────────────────────────────────────────────────
  function loadPrefs() {
    const fallback = { font: 18, line: 1.85, width: "42rem", tone: "auto" };
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return fallback;
      return Object.assign(fallback, JSON.parse(raw));
    } catch (_) {
      return fallback;
    }
  }

  function savePrefs() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(prefs));
    } catch (_) {
      /* 存储不可用时静默降级，功能照常 */
    }
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  // ── 正文定位 ──────────────────────────────────────────────────────────────
  function visibleScore(el) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 200 || rect.height < 120) return -1;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return -1;
    return (el.textContent || "").trim().length;
  }

  const MIN_TEXT = 200; // 短于这个的容器不值得进沉浸模式（比如教程书封）

  function findTarget() {
    // 第一轮：按候选顺序，命中即返回
    for (const selector of CANDIDATES) {
      for (const el of document.querySelectorAll(selector)) {
        if (visibleScore(el) >= MIN_TEXT) return el;
      }
    }
    // 第二轮：候选都没达标时退回到「页面上文字最多的一块」
    let best = null;
    let bestScore = MIN_TEXT;
    for (const el of document.querySelectorAll("main, article, section, div")) {
      const score = visibleScore(el);
      if (score > bestScore) {
        best = el;
        bestScore = score;
      }
    }
    return best;
  }

  // ── 隐藏 / 还原 ───────────────────────────────────────────────────────────
  function hideSiblings(node) {
    hiddenNodes = [];
    let current = node;
    // 逐级向上：同一层里只留通往正文的那一个子节点
    while (current && current.parentElement && current.parentElement !== document.body) {
      const parent = current.parentElement;
      for (const child of Array.from(parent.children)) {
        if (child === current) continue;
        child.setAttribute(HIDDEN_ATTR, "1");
        hiddenNodes.push(child);
      }
      current = parent;
    }
    // body 直接子级：不在正文祖先链上的一律隐藏
    const chain = new Set();
    let walk = node;
    while (walk && walk !== document.body) {
      chain.add(walk);
      walk = walk.parentElement;
    }
    for (const child of Array.from(document.body.children)) {
      if (chain.has(child)) continue;
      child.setAttribute(HIDDEN_ATTR, "1");
      hiddenNodes.push(child);
    }
  }

  function restoreHidden() {
    for (const node of hiddenNodes) node.removeAttribute(HIDDEN_ATTR);
    hiddenNodes = [];
  }

  // ── 强制关键样式 ──────────────────────────────────────────────────────────
  // 站点主题里有一批 "!important + 高特异性" 的卡片规则（圆角、阴影、最大宽度），
  // 论坛详情本身的 class 就是 .card .glass-card .rounded-box，CSS 层叠里很难稳定压过。
  // 用内联 !important 是唯一能百分百生效的层级，退出时把原值写回去。
  const FORCE_PROPS = [
    "position",
    "inset",
    "z-index",
    "overflow-y",
    "overflow-x",
    "background",
    "border",
    "border-radius",
    "box-shadow",
    "width",
    "max-width",
    "max-height",
    "margin",
  ];

  const FORCE_VALUES = {
    position: "fixed",
    inset: "0",
    "z-index": "120",
    "overflow-y": "auto",
    "overflow-x": "hidden",
    background: "var(--im-bg)",
    border: "0",
    "border-radius": "0",
    "box-shadow": "none",
    width: "auto",
    "max-width": "none",
    "max-height": "none",
    margin: "0",
  };

  function forceStyles(el) {
    savedInline = {};
    for (const prop of FORCE_PROPS) {
      savedInline[prop] = {
        value: el.style.getPropertyValue(prop),
        priority: el.style.getPropertyPriority(prop),
      };
      el.style.setProperty(prop, FORCE_VALUES[prop], "important");
    }
  }

  function restoreStyles(el) {
    if (!savedInline || !el) return;
    for (const [prop, snapshot] of Object.entries(savedInline)) {
      if (snapshot.value) el.style.setProperty(prop, snapshot.value, snapshot.priority);
      else el.style.removeProperty(prop);
    }
    savedInline = null;
  }

  // ── 控件 ──────────────────────────────────────────────────────────────────
  function button(label, title, onClick) {
    const el = document.createElement("button");
    el.type = "button";
    el.textContent = label;
    el.title = title;
    el.setAttribute("aria-label", title);
    el.addEventListener("click", onClick);
    return el;
  }

  function separator() {
    const el = document.createElement("span");
    el.className = "im-sep";
    el.setAttribute("aria-hidden", "true");
    return el;
  }

  function buildBar() {
    bar = document.createElement("div");
    bar.className = "im-bar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "沉浸式阅读设置");

    bar.append(
      button("A−", "缩小字号（快捷键 -）", () => setFont(prefs.font - 1)),
      button("A+", "放大字号（快捷键 +）", () => setFont(prefs.font + 1)),
      separator(),
      button("宽", "切换栏宽（快捷键 [ 或 ]）", cycleWidth),
      button("高", "切换行距（快捷键 H）", cycleLine),
      button("色", "切换阅读底色（快捷键 T）", cycleTone),
    );

    // 教程页：沉浸后翻页按钮被隐藏了，这里补一对
    const prev = document.querySelector("#bookPrevious");
    const next = document.querySelector("#bookNext");
    if (prev || next) {
      bar.append(separator());
      if (prev) bar.append(button("←", "上一页", () => turnPage(prev)));
      if (next) bar.append(button("→", "下一页", () => turnPage(next)));
    }

    bar.append(separator(), button("✕", "退出沉浸阅读（Esc）", exit));

    progress = document.createElement("div");
    progress.className = "im-progress";
    progress.setAttribute("aria-hidden", "true");

    document.body.append(progress, bar);

    // 面板是 body 直接子元素，进入后才 append，不会被隐藏逻辑扫到
    bar.removeAttribute(HIDDEN_ATTR);
    progress.removeAttribute(HIDDEN_ATTR);
  }

  // 翻页后正文换了内容，滚动位置必须回到顶部：否则新的一页会停在上一次的
  // 阅读位置，进度条也直接顶到 100%。
  function turnPage(control) {
    control.click();
    requestAnimationFrame(() => {
      if (!target) return;
      target.scrollTop = 0;
      updateProgress();
    });
  }

  function destroyBar() {
    if (bar) bar.remove();
    if (progress) progress.remove();
    bar = null;
    progress = null;
  }

  // ── 偏好应用 ──────────────────────────────────────────────────────────────
  function applyPrefs() {
    const root = document.documentElement;
    root.style.setProperty("--im-font", prefs.font + "px");
    root.style.setProperty("--im-line", String(prefs.line));
    root.style.setProperty("--im-width", prefs.width);
    if (prefs.tone && prefs.tone !== "auto") {
      root.setAttribute("data-im-tone", prefs.tone);
    } else {
      root.removeAttribute("data-im-tone");
    }
  }

  function setFont(size) {
    prefs.font = clamp(Math.round(size), 14, 30);
    applyPrefs();
    savePrefs();
  }

  function cycleWidth() {
    const index = WIDTHS.indexOf(prefs.width);
    prefs.width = WIDTHS[(index + 1) % WIDTHS.length];
    applyPrefs();
    savePrefs();
  }

  function cycleLine() {
    const order = [1.6, 1.85, 2.1];
    const index = order.indexOf(prefs.line);
    prefs.line = order[(index + 1) % order.length];
    applyPrefs();
    savePrefs();
  }

  function cycleTone() {
    const index = TONES.indexOf(prefs.tone);
    prefs.tone = TONES[(index + 1) % TONES.length];
    applyPrefs();
    savePrefs();
  }

  // ── 进度条 ────────────────────────────────────────────────────────────────
  function updateProgress() {
    if (!progress || !target) return;
    const max = target.scrollHeight - target.clientHeight;
    // 内容不足一屏时不显示进度条（显示满格会让人以为已经读完）
    if (max <= 8) {
      progress.style.opacity = "0";
      progress.style.width = "0%";
      return;
    }
    progress.style.opacity = "1";
    const ratio = clamp(target.scrollTop / max, 0, 1);
    progress.style.width = (ratio * 100).toFixed(2) + "%";
  }

  // ── 进入 / 退出 ───────────────────────────────────────────────────────────
  function enter(customTarget) {
    if (active) return false;
    const node = customTarget || findTarget();
    if (!node) return false;

    active = true;
    target = node;
    applyPrefs();
    target.setAttribute(ARTICLE_ATTR, "1");
    forceStyles(target);
    document.documentElement.classList.add(ROOT_FLAG);
    hideSiblings(target);
    buildBar();

    // 论坛详情 / 教程翻页会重渲染正文：节点一旦被换掉就自动退出，
    // 否则会留下一个空的全屏层。
    if (typeof MutationObserver === "function") {
      observer = new MutationObserver(() => {
        if (!target || !target.isConnected) exit();
      });
      observer.observe(document.body, { childList: true, subtree: true });
    }

    target.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress);
    updateProgress();
    target.focus?.({ preventScroll: true });
    document.dispatchEvent(new CustomEvent("kflow:immersive", { detail: { active: true } }));
    return true;
  }

  function exit() {
    if (!active) return;
    active = false;
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    if (target) {
      target.removeEventListener("scroll", updateProgress);
      restoreStyles(target);
      target.removeAttribute(ARTICLE_ATTR);
    }
    window.removeEventListener("resize", updateProgress);
    document.documentElement.classList.remove(ROOT_FLAG);
    restoreHidden();
    destroyBar();
    target = null;
    document.dispatchEvent(new CustomEvent("kflow:immersive", { detail: { active: false } }));
  }

  function toggle() {
    return active ? (exit(), false) : enter();
  }

  // ── 键盘 ──────────────────────────────────────────────────────────────────
  function onKeydown(event) {
    if (!active) {
      // 未激活时：i 键进入（输入框里不触发）
      if (event.key === "i" && !isTyping(event.target)) {
        event.preventDefault();
        enter();
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      exit();
      return;
    }
    if (isTyping(event.target)) return;
    switch (event.key) {
      case "+":
      case "=":
        setFont(prefs.font + 1);
        break;
      case "-":
      case "_":
        setFont(prefs.font - 1);
        break;
      case "[":
      case "]":
        cycleWidth();
        break;
      case "h":
      case "H":
        cycleLine();
        break;
      case "t":
      case "T":
        cycleTone();
        break;
      default:
        break;
    }
  }

  function isTyping(node) {
    if (!node) return false;
    const tag = node.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || node.isContentEditable;
  }

  // ── 右下角入口 ────────────────────────────────────────────────────────────
  // 术语 / 教程详情是前端 fetch 后渲染的：DOMContentLoaded 那一刻正文还是空的，
  // 只挂一次会永远挂不上。这里留一组有限次重试（不是轮询：最多 8 次、每次 400ms，
  // 正文一出现就停）。
  let entryTimer = null;
  let entryTries = 0;

  function mountEntry() {
    // 教程页工具栏里已经有原生「沉浸阅读」按钮，不再浮一个
    if (document.querySelector("#bookImmersiveButton")) return;
    if (document.querySelector(".im-entry")) return;
    if (!findTarget()) {
      if (entryTries < 8) {
        entryTries += 1;
        entryTimer = window.setTimeout(() => {
          entryTimer = null;
          mountEntry();
        }, 400);
      }
      return;
    }
    entry = document.createElement("button");
    entry.type = "button";
    entry.className = "im-entry";
    entry.textContent = "沉浸阅读";
    entry.setAttribute("aria-label", "进入沉浸式阅读");
    entry.addEventListener("click", () => enter());
    document.body.append(entry);
  }

  // ── 初始化 ────────────────────────────────────────────────────────────────
  function init() {
    applyPrefs();
    document.addEventListener("keydown", onKeydown);
    mountEntry();

    // 教程页的原生按钮由 learn.js 转交过来；这里兜底再绑一次（幂等，
    // learn.js 那边会先判断 window.kflowImmersive 是否存在）
    const native = document.querySelector("#bookImmersiveButton");
    if (native && !native.dataset.imBound) {
      native.dataset.imBound = "1";
      native.addEventListener("click", () => {
        // learn.js 会在同一按钮上先跑自己的逻辑，这里只负责同步按钮文案
        requestAnimationFrame(syncNativeLabel);
      });
    }
    document.addEventListener("kflow:immersive", syncNativeLabel);
  }

  function syncNativeLabel() {
    const native = document.querySelector("#bookImmersiveButton");
    if (!native) return;
    native.textContent = active ? "退出沉浸" : "沉浸阅读";
    native.setAttribute("aria-pressed", String(active));
  }

  window.kflowImmersive = { toggle, enter, exit, isActive: () => active };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
