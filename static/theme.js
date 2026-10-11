// 主题切换：light / dark，记忆在 localStorage
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
  }

  function toggleTheme() {
    const current = getCurrent();
    const next = nextTheme(current);
    // 主题切换瞬间的整体淡出-淡入动画
    const overlay = document.createElement("div");
    const overlayColor = next === "light" ? "#f5f5f7" : next === "glass" ? "#07141d" : "#000";
    overlay.style.cssText = "position:fixed;inset:0;z-index:99999;background:" + overlayColor + ";opacity:0;transition:opacity .25s ease;pointer-events:none;";
    document.body.appendChild(overlay);
    requestAnimationFrame(() => { overlay.style.opacity = "0.7"; });
    setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, next); } catch (_) {}
      applyTheme(next);
      overlay.style.opacity = "0";
      setTimeout(() => overlay.remove(), 260);
    }, 220);
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
