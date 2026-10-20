// 主题切换：light / dark / vibrancy（macOS 毛玻璃）/ comic（漫画风格），记忆在 localStorage
(function () {
  "use strict";
  const STORAGE_KEY = "kflow-theme";
  const VALID = ["light", "dark", "vibrancy", "comic"];
  const CYCLE = ["light", "dark", "vibrancy", "comic"];
  // 第三个主题原先叫 glass（液态玻璃），已整体换成 macOS Vibrancy。
  // 老用户 localStorage 里还存着 "glass"，读到这里直接迁移，不要回落到 light。
  const LEGACY = { glass: "vibrancy" };

  function normalize(mode) {
    const mapped = LEGACY[mode] || mode;
    return VALID.includes(mapped) ? mapped : "light";
  }

  function getPreferred() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      // 只认已知值（含待迁移的旧值），其它一律当作没选过、继续看系统偏好
      if (saved && (VALID.includes(saved) || LEGACY[saved])) return normalize(saved);
    } catch (_) {}
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }
    return "light";
  }

  function getCurrent() {
    const current = document.documentElement.getAttribute("data-theme");
    return normalize(current || "light");
  }

  function nextTheme(mode) {
    return CYCLE[(CYCLE.indexOf(normalize(mode)) + 1) % CYCLE.length];
  }

  function themeLabel(mode) {
    return {
      light: "白天",
      dark: "黑夜",
      vibrancy: "毛玻璃",
      comic: "漫画",
    }[mode];
  }

  function themeIcon(mode) {
    if (mode === "comic") {
      // 漫画对话气泡：方框 + 指向左下的尾巴 + 两行台词
      return '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 12.5h5"/>';
    }
    if (mode === "vibrancy") {
      // macOS 窗口：圆角矩形 + 标题栏分隔线 + 三个交通灯圆点
      return '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M6.5 6.5h.01M9.5 6.5h.01M12.5 6.5h.01"/>';
    }
    if (mode === "dark") {
      return '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';
    }
    return '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
  }

  function applyTheme(mode) {
    mode = normalize(mode);
    const root = document.documentElement;
    // 白天模式必须显式写 data-theme="light"，不能靠"移除属性"表示。
    // 构建产物里 daisyUI 自带一条：
    //   @media (prefers-color-scheme:dark){ :root:not([data-theme]){ ...深色变量... } }
    // 一旦操作系统是深色模式，html 上没有 data-theme 就会命中它 ——
    // 用户明明切到了「白天」，拿到的却是一整套深色底。
    root.setAttribute("data-theme", mode);
    // 漫画主题是浅底（纸黄），浏览器 UI（滚动条、表单控件）要按浅色渲染
    root.style.colorScheme = mode === "dark" || mode === "vibrancy" ? "dark" : "light";
    // 同步所有按钮状态和图标
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      const next = nextTheme(mode);
      btn.setAttribute(
        "aria-pressed",
        mode === "dark" ? "true" : mode === "light" ? "false" : "mixed",
      );
      btn.setAttribute("data-theme-current", mode);
      btn.setAttribute("aria-label", `当前主题：${themeLabel(mode)}，点击切换到${themeLabel(next)}`);
      btn.setAttribute("title", `当前：${themeLabel(mode)} · 点击切换到${themeLabel(next)}`);
      const svg = btn.querySelector("svg");
      if (svg) svg.innerHTML = themeIcon(mode);
      const label = btn.querySelector("[data-theme-label]");
      if (label) label.textContent = themeLabel(mode);
    });
    document.dispatchEvent(new CustomEvent("kflow:themechange", {
      detail: { theme: mode },
    }));
  }

  let isTransitioning = false;

  function prefersReducedMotion() {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  }

  function themeBackground(mode) {
    return {
      light: "#f5f5f7",
      dark: "#111318",
      vibrancy: "#1c1c1e",
      comic: "#fffef0",
    }[mode];
  }

  function getTransitionOrigin(event) {
    const target = event?.currentTarget;
    const rect = target?.getBoundingClientRect?.();
    const fallbackX = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
    const fallbackY = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
    const x = Number.isFinite(event?.clientX) && event.clientX > 0 ? event.clientX : fallbackX;
    const y = Number.isFinite(event?.clientY) && event.clientY > 0 ? event.clientY : fallbackY;
    const safeX = Math.max(0, Math.min(window.innerWidth, x));
    const safeY = Math.max(0, Math.min(window.innerHeight, y));
    return {
      x: safeX,
      y: safeY,
      radius: Math.hypot(
        Math.max(safeX, window.innerWidth - safeX),
        Math.max(safeY, window.innerHeight - safeY),
      ),
    };
  }

  function persistAndApply(mode) {
    try { localStorage.setItem(STORAGE_KEY, mode); } catch (_) {}
    applyTheme(mode);
  }

  function runFallbackReveal(next, origin) {
    const overlay = document.createElement("div");
    overlay.className = "kflow-theme-fallback";
    overlay.style.backgroundColor = themeBackground(getCurrent());
    overlay.style.setProperty("--kflow-theme-x", `${origin.x}px`);
    overlay.style.setProperty("--kflow-theme-y", `${origin.y}px`);
    overlay.style.setProperty("--kflow-theme-radius", `${origin.radius}px`);
    overlay.style.clipPath = `circle(${origin.radius}px at ${origin.x}px ${origin.y}px)`;
    document.body.appendChild(overlay);
    persistAndApply(next);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => overlay.classList.add("is-revealing"));
    });
    window.setTimeout(() => overlay.remove(), 620);
  }

  function runViewTransition(next, origin) {
    const root = document.documentElement;
    root.classList.add("theme-transitioning");
    root.style.setProperty("--kflow-theme-x", `${origin.x}px`);
    root.style.setProperty("--kflow-theme-y", `${origin.y}px`);
    root.style.setProperty("--kflow-theme-radius", `${origin.radius}px`);

    let transition;
    try {
      // 基于 MDN 的 View Transition circular reveal 示例，避免引入重量级动画库。
      transition = document.startViewTransition(() => persistAndApply(next));
    } catch (_) {
      root.classList.remove("theme-transitioning");
      root.style.removeProperty("--kflow-theme-x");
      root.style.removeProperty("--kflow-theme-y");
      root.style.removeProperty("--kflow-theme-radius");
      runFallbackReveal(next, origin);
      return;
    }

    transition.ready?.then(() => {
      root.animate(
        {
          clipPath: [
            `circle(0 at ${origin.x}px ${origin.y}px)`,
            `circle(${origin.radius}px at ${origin.x}px ${origin.y}px)`,
          ],
        },
        {
          duration: 560,
          easing: "cubic-bezier(.22,1,.36,1)",
          fill: "both",
          pseudoElement: "::view-transition-new(root)",
        },
      );
    }).catch(() => {});

    Promise.resolve(transition.finished).catch(() => {}).then(() => {
      root.classList.remove("theme-transitioning");
      root.style.removeProperty("--kflow-theme-x");
      root.style.removeProperty("--kflow-theme-y");
      root.style.removeProperty("--kflow-theme-radius");
    });
  }

  function toggleTheme(event) {
    if (isTransitioning) return;
    isTransitioning = true;
    const current = getCurrent();
    const next = nextTheme(current);
    const origin = getTransitionOrigin(event);

    if (prefersReducedMotion()) {
      persistAndApply(next);
      isTransitioning = false;
      return;
    }

    if (typeof document.startViewTransition === "function") {
      runViewTransition(next, origin);
      window.setTimeout(() => { isTransitioning = false; }, 620);
      return;
    }

    runFallbackReveal(next, origin);
    window.setTimeout(() => { isTransitioning = false; }, 620);
  }

  // 1. 立即应用（避免闪烁）
  applyTheme(getPreferred());

  // 2. 绑定按钮
  function ensureThemeButton() {
    if (document.querySelector("[data-theme-toggle]")) return;
    const header = document.querySelector("header");
    if (!header) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "theme-toggle-btn";
    button.setAttribute("data-theme-toggle", "");
    button.setAttribute("aria-label", "切换主题");
    button.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"></svg>';
    const search = header.querySelector(".header-search");
    if (search) search.before(button);
    else {
      const host = header.querySelector("nav, .topbar-inner, .header-actions") || header;
      host.append(button);
    }
  }

  function bindButtons() {
    ensureThemeButton();
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.classList.add("theme-toggle-btn");
      btn.classList.remove("btn", "btn-ghost", "btn-sm", "btn-square");
      btn.addEventListener("click", toggleTheme);
    });
    applyTheme(getPreferred()); // 刷新按钮状态
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindButtons);
  } else {
    bindButtons();
  }
})();
