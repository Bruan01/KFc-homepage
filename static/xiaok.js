/* Xiao K's shared illustrations and optional public community entry. */
(() => {
  const ASSETS = Object.freeze({ welcome: "/static/xiaok/chibi-welcome-v2.png", done: "/static/xiaok/chibi-done-v2.png" });

  function illustration(kind = "welcome") {
    const image = document.createElement("img");
    image.src = ASSETS[kind] || ASSETS.welcome;
    image.alt = "";
    image.width = 128;
    image.height = 128;
    image.loading = "lazy";
    image.decoding = "async";
    image.className = "xiaok-state-image";
    image.setAttribute("aria-hidden", "true");
    image.addEventListener("error", () => image.remove(), { once: true });
    return image;
  }

  function decorateToast(node) {
    if (!node) return;
    const text = document.createElement("span");
    text.textContent = node.textContent;
    node.replaceChildren(illustration("done"), text);
    node.classList.add("xiaok-toast");
  }

  function empty(title, description) {
    const root = document.createElement("div");
    root.className = "xiaok-empty";
    const heading = document.createElement("h3");
    heading.textContent = title;
    const copy = document.createElement("p");
    copy.textContent = description;
    root.append(illustration(), heading, copy);
    return root;
  }

  async function init() {
    if (location.pathname.startsWith("/admin") || location.pathname === "/login") return;
    const header = document.querySelector("header");
    if (!header) return;
    let hidden = false;
    try { hidden = sessionStorage.getItem("kflow:xiaok:hidden:v1") === "1"; } catch { /* Browsing remains available. */ }
    if (!document.getElementById("xiaokCompanion")) {
      const companion = document.createElement("aside");
      companion.id = "xiaokCompanion";
      companion.className = "xiaok-companion";
      companion.setAttribute("aria-label", "小 K 社区向导");
      const close = document.createElement("button");
      close.type = "button";
      close.className = "xiaok-companion-close";
      close.textContent = "×";
      close.setAttribute("aria-label", "收起小 K，可点击右下角按钮恢复");
      close.addEventListener("click", () => {
        setExpanded(false);
        restore.focus({ preventScroll: true });
      });
      const profile = document.createElement("a");
      profile.className = "xiaok-companion-link";
      profile.href = "/guide";
      profile.dataset.xiaokOfficial = "";
      profile.setAttribute("aria-label", "跟小 K 认识社区");
      const label = document.createElement("span");
      label.textContent = "认识社区";
      profile.append(illustration(), label);
      const guide = document.createElement("button");
      guide.type = "button";
      guide.className = "xiaok-companion-guide";
      guide.textContent = "新手引导";
      guide.addEventListener("click", () => {
        if (window.KflowGuide?.openWelcome) window.KflowGuide.openWelcome();
        else location.href = "/guide";
      });
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "xiaok-companion-restore";
      restore.textContent = "小 K";
      restore.setAttribute("aria-label", "展开小 K 社区向导");
      restore.addEventListener("click", () => {
        setExpanded(true);
        profile.focus({ preventScroll: true });
      });
      function setExpanded(expanded) {
        close.hidden = profile.hidden = guide.hidden = !expanded;
        restore.hidden = expanded;
        restore.setAttribute("aria-expanded", String(expanded));
        companion.classList.toggle("is-collapsed", !expanded);
        try { sessionStorage.setItem("kflow:xiaok:hidden:v1", expanded ? "0" : "1"); } catch { /* The toggle still works for this page. */ }
      }
      setExpanded(!hidden);
      companion.append(close, profile, guide, restore);
      document.body.append(companion);
    }
    try {
      const response = await fetch("/api/community/official", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) return;
      const { account } = await response.json();
      if (!account || typeof account.username !== "string" || !account.username) return;
      // Build the path locally from a username; do not trust a provider URL.
      const href = `/forum/user/${encodeURIComponent(account.username)}`;
      document.querySelectorAll("[data-xiaok-official]").forEach((link) => {
        link.href = href;
        link.setAttribute("aria-label", `小 K 官方主页：${account.display_name || account.username}`);
        const label = link.querySelector("span");
        if (label) label.textContent = "官方主页";
        else link.textContent = "官方主页";
      });
    } catch { /* Keep the guide fallback available if official identity cannot load. */ }
  }

  window.KflowXiaok = Object.freeze({ illustration, decorateToast, empty });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
