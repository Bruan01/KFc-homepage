// 主题切换：light / dark，记忆在 localStorage
(function () {
  "use strict";
  const STORAGE_KEY = "kflow-theme";
  const VALID = ["light", "dark"];

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

  function applyTheme(mode) {
    const root = document.documentElement;
    if (mode === "dark") root.setAttribute("data-theme", "dark");
    else root.removeAttribute("data-theme");
    // 同步所有按钮状态和图标
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      const isDark = mode === "dark";
      btn.setAttribute("aria-pressed", isDark ? "true" : "false");
      btn.setAttribute("title", isDark ? "切换到浅色模式" : "切换到深色模式");
      // 切换图标：月亮 ↔ 太阳
      const svg = btn.querySelector("svg");
      if (svg) {
        svg.innerHTML = isDark
          ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>'
          : '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
      }
      const label = btn.querySelector("[data-theme-label]");
      if (label) label.textContent = isDark ? "浅色" : "深色";
    });
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";
    // 主题切换瞬间的整体淡出-淡入动画
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;z-index:99999;background:" + (next === "dark" ? "#000" : "#f5f5f7") + ";opacity:0;transition:opacity .25s ease;pointer-events:none;";
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
