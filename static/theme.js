// 主题切换：light / dark / glass，记忆在 localStorage
(function () {
  "use strict";
  const STORAGE_KEY = "kflow-theme";
  const VALID = ["light", "dark", "glass"];
  const CYCLE = ["light", "dark", "glass"];

  function normalize(mode) {
    return VALID.includes(mode) ? mode : "light";
  }

  function getPreferred() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && VALID.includes(saved)) return saved;
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
      glass: "玻璃透明",
    }[mode];
  }

  function themeIcon(mode) {
    if (mode === "glass") {
      return '<path d="M7 3.5h10l3.5 4.2-8.5 12.8L3.5 7.7 7 3.5Z"/><path d="M3.8 7.7h16.4M7 3.5l5 17M17 3.5l-5 17"/>';
    }
    if (mode === "dark") {
      return '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';
    }
    return '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
  }

  function applyTheme(mode) {
    mode = normalize(mode);
    const root = document.documentElement;
    if (mode === "light") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    root.style.colorScheme = mode === "light" ? "light" : "dark";
    // 同步所有按钮状态和图标
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      const next = nextTheme(mode);
      btn.setAttribute("aria-pressed", mode === "glass" ? "mixed" : mode === "dark" ? "true" : "false");
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
      glass: "#07141d",
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
  function bindButtons() {
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
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
