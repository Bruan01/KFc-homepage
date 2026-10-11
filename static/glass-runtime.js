/* WWDC 2025 Liquid Glass enhancement layer for public pages only. */
(function () {
  "use strict";

  const root = document.documentElement;
  const assetPromises = new Map();
  const surfaceSelector = [
    ".card",
    ".panel",
    ".hero-wrap",
    ".hero-panel",
    ".community-intro",
    ".side-card",
    ".rankings-panel",
    ".store-hero",
    ".store-panel",
    ".store-card",
    ".topic-list-card",
    ".topic-detail-inline",
    ".modal-detail",
    ".reply-row",
    ".stats-board",
    ".stats-table-card",
    ".kb-repo",
    ".glossary-card",
    ".tutorial-card",
    ".rules-section",
    ".rules-card",
    ".book-complete-host",
    ".auth-card",
    ".catalog",
    ".model-grid",
    ".notice-row",
    ".window",
    ".privacy",
    ".cta",
    ".insight",
    ".step",
    ".pitem",
    ".generator",
  ].join(",");
  const menuSelector = [
    ".community-nav a",
    ".nav-group-btn",
    ".view-tab",
    ".store-tab",
    ".btn",
    ".new-topic-button",
    ".theme-toggle-btn",
    ".topic-row",
    ".rankings-list li",
    ".book-toc-item",
    '[role="tab"]',
    ".menu-item",
  ].join(",");

  function currentTheme() {
    return root.getAttribute("data-theme") || "light";
  }

  function loadStylesheet(id, href) {
    if (assetPromises.has(id)) return assetPromises.get(id);
    const existing = document.querySelector(`link[data-glass-asset="${id}"]`);
    if (existing) return Promise.resolve(existing);
    const promise = new Promise((resolve) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.glassAsset = id;
      link.onload = () => resolve(link);
      link.onerror = () => resolve(null);
      document.head.appendChild(link);
    });
    assetPromises.set(id, promise);
    return promise;
  }

  function loadScript(id, src) {
    if (assetPromises.has(id)) return assetPromises.get(id);
    const existing = document.querySelector(`script[data-glass-asset="${id}"]`);
    if (existing) return Promise.resolve(existing);
    const promise = new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.glassAsset = id;
      script.onload = () => resolve(script);
      script.onerror = () => resolve(null);
      document.head.appendChild(script);
    });
    assetPromises.set(id, promise);
    return promise;
  }

  function loadGlassAssets() {
    loadStylesheet(
      "google-fonts",
      "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Poppins:wght@500;600;700&display=swap",
    );
    loadStylesheet(
      "fontawesome5",
      "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css",
    );

    window.tailwind = window.tailwind || {};
    window.tailwind.config = Object.assign({}, window.tailwind.config || {}, {
      corePlugins: Object.assign({}, window.tailwind.config?.corePlugins || {}, { preflight: false }),
      theme: Object.assign({}, window.tailwind.config?.theme || {}, {
        extend: {
          colors: {
            glass: {
              ink: "#f8fbff",
              red: "#ff4d6d",
              orange: "#ff9f43",
              violet: "#b28dff",
            },
          },
        },
      }),
    });
    loadScript("tailwind-v3", "https://cdn.tailwindcss.com");

    const chartHosts = document.querySelectorAll("[data-glass-chart]");
    if (chartHosts.length) {
      loadScript(
        "echarts5",
        "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
      ).then(() => {
        chartHosts.forEach((host) => initializeChart(host));
      });
    }
  }

  function initializeChart(host) {
    if (!window.echarts || host.dataset.glassChartReady === "true") return;
    const rawValues = (host.dataset.values || "")
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value));
    if (!rawValues.length) return;
    host.dataset.glassChartReady = "true";
    const chart = window.echarts.init(host, null, { renderer: "canvas" });
    const accent = host.dataset.accent || "#ff4d6d";
    chart.setOption({
      animationDuration: 900,
      grid: { top: 10, right: 8, bottom: 12, left: 8 },
      xAxis: { type: "category", show: false, data: rawValues.map((_, index) => index + 1) },
      yAxis: { type: "value", show: false, min: 0 },
      series: [{
        type: "line",
        data: rawValues,
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2, color: accent },
        areaStyle: { color: `${accent}22` },
      }],
    });
    window.addEventListener("resize", () => chart.resize(), { passive: true });
  }

  function ensureDistortionFilter() {
    if (document.getElementById("kflow-liquid-distortion")) return;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.id = "kflow-liquid-distortion-defs";
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = '<defs><filter id="kflow-liquid-distortion" x="-12%" y="-12%" width="124%" height="124%"><feTurbulence type="fractalNoise" baseFrequency="0.018 0.028" numOctaves="2" seed="12" result="glassNoise"></feTurbulence><feDisplacementMap in="SourceGraphic" in2="glassNoise" scale="7" xChannelSelector="R" yChannelSelector="B"></feDisplacementMap></filter></defs>';
    document.body.appendChild(svg);
  }

  function decorateSurfaces() {
    document.querySelectorAll(surfaceSelector).forEach((node) => {
      if (!node.classList.contains("glass-surface")) node.dataset.glassSurfaceAdded = "true";
      node.classList.add(
        "glass-surface",
        "backdrop-blur-xl",
        "border",
        "border-white/20",
        "bg-white/10",
        "shadow-2xl",
      );
    });
    document.querySelectorAll(menuSelector).forEach((node) => {
      if (!node.classList.contains("menu-item")) node.dataset.glassMenuAdded = "true";
      node.classList.add("menu-item", "glass-menu-item");
    });
  }

  function addParticleField() {
    if (document.querySelector(".glass-particle-field")) return;
    const field = document.createElement("div");
    field.className = "glass-particle-field";
    field.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 14; index += 1) {
      const particle = document.createElement("span");
      particle.style.setProperty("--particle-index", index);
      particle.style.setProperty("--particle-x", `${8 + ((index * 29) % 86)}%`);
      particle.style.setProperty("--particle-y", `${12 + ((index * 47) % 78)}%`);
      field.appendChild(particle);
    }
    document.body.appendChild(field);
  }

  function bindPointerGlow() {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    if (document.body.dataset.glassPointerBound === "true") return;
    document.body.dataset.glassPointerBound = "true";
    document.addEventListener("pointermove", (event) => {
      root.style.setProperty("--glass-pointer-x", `${event.clientX}px`);
      root.style.setProperty("--glass-pointer-y", `${event.clientY}px`);
    }, { passive: true });
  }

  function enterGlass() {
    if (!document.body) return;
    root.classList.add("glass-runtime-active");
    document.body.classList.add("glass-runtime-active");
    ensureDistortionFilter();
    decorateSurfaces();
    addParticleField();
    bindPointerGlow();
    loadGlassAssets();
  }

  function leaveGlass() {
    root.classList.remove("glass-runtime-active");
    document.body?.classList.remove("glass-runtime-active");
    document.querySelectorAll(".glass-surface, .glass-menu-item").forEach((node) => {
      node.classList.remove(
        "glass-surface",
        "glass-menu-item",
        "backdrop-blur-xl",
        "border",
        "border-white/20",
        "bg-white/10",
        "shadow-2xl",
      );
      if (node.dataset.glassSurfaceAdded === "true") delete node.dataset.glassSurfaceAdded;
      if (node.dataset.glassMenuAdded === "true") {
        node.classList.remove("menu-item");
        delete node.dataset.glassMenuAdded;
      }
    });
    document.querySelector(".glass-particle-field")?.remove();
    document.getElementById("kflow-liquid-distortion-defs")?.remove();
  }

  function syncTheme(mode) {
    if (mode === "glass") enterGlass();
    else leaveGlass();
  }

  document.addEventListener("kflow:themechange", (event) => {
    syncTheme(event.detail?.theme || currentTheme());
  });

  function boot() {
    syncTheme(currentTheme());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
