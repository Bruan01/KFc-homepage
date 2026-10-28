(function () {
  "use strict";

  if (window.__kflowAnnouncementLoaded) return;
  window.__kflowAnnouncementLoaded = true;

  const SEEN_KEY = "kflow-announcement-seen";
  const DAY_MS = 24 * 60 * 60 * 1000;
  // 页面直接引用时带 ?v=<内容指纹>；header.js 动态插入时没有，靠服务端 no-cache 兜底。
  const VERSION = (() => {
    try {
      return new URL(document.currentScript?.src || "", location.href).searchParams.get("v") || "";
    } catch {
      return "";
    }
  })();
  const SUFFIX = VERSION ? `?v=${VERSION}` : "";
  const ART_CORNER = `/static/xiaok/announce-ornament-corner.webp${SUFFIX}`;
  const ICON =
    '<svg class="site-announce-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11v2a1 1 0 0 0 1 1h2l4 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15 8a4 4 0 0 1 0 8"/><path d="M18 5a8 8 0 0 1 0 14"/></svg>';

  function ensureStyles() {
    if (document.querySelector("link[data-site-announce]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `/announcement.css${SUFFIX}`;
    link.dataset.siteAnnounce = "1";
    document.head.appendChild(link);
  }

  function iconNode() {
    const span = document.createElement("span");
    span.innerHTML = ICON;
    return span.firstElementChild;
  }

  function artNode(className, src) {
    const image = document.createElement("img");
    image.className = className;
    image.src = src;
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    image.loading = "lazy";
    image.decoding = "async";
    return image;
  }

  function formatTime(value) {
    const date = new Date(value || "");
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function readSeen() {
    try {
      const raw = window.localStorage.getItem(SEEN_KEY);
      if (!raw) return null;
      const record = JSON.parse(raw);
      return record && typeof record === "object" ? record : null;
    } catch {
      return null;
    }
  }

  function markSeen(item) {
    try {
      window.localStorage.setItem(SEEN_KEY, JSON.stringify({
        id: item.id,
        updated_at: item.updated_at || item.created_at || "",
        seen_at: Date.now(),
      }));
    } catch {
      /* 隐私模式下写不了存储，忽略：本次打开仍然显示，下次会再弹 */
    }
  }

  function shouldPopup(item, record) {
    if (!record) return true;
    if (record.id !== item.id) return true;
    if ((record.updated_at || "") !== (item.updated_at || item.created_at || "")) return true;
    const days = Number(item.popup_days);
    if (!Number.isInteger(days) || days <= 0) return false;
    const elapsed = Date.now() - Number(record.seen_at || 0);
    return !(elapsed >= 0 && elapsed < days * DAY_MS);
  }

  function forcedId() {
    try {
      const value = new URLSearchParams(window.location.search).get("announcement");
      return value ? Number(value) : 0;
    } catch {
      return 0;
    }
  }

  function mount(item) {
    ensureStyles();
    const wrapper = document.createElement("div");
    wrapper.className = "site-announce";
    wrapper.hidden = true;

    const entry = document.createElement("button");
    entry.type = "button";
    entry.className = "site-announce-entry";
    entry.setAttribute("aria-haspopup", "dialog");
    entry.setAttribute("aria-label", `查看公告：${item.content}`);
    entry.appendChild(iconNode());

    const label = document.createElement("span");
    label.className = "site-announce-label";
    label.textContent = "公告";
    entry.appendChild(label);

    const text = document.createElement("span");
    text.className = "site-announce-text";
    text.textContent = item.content;
    entry.appendChild(text);

    const more = document.createElement("span");
    more.className = "site-announce-more";
    more.textContent = "查看";
    entry.appendChild(more);
    wrapper.appendChild(entry);

    const header = document.querySelector("header.navbar, header.topbar, body > header");
    if (header && header.parentNode) header.after(wrapper);
    else document.body.prepend(wrapper);
    wrapper.hidden = false;

    let modal = null;
    let previousOverflow = "";
    let lastFocused = null;

    function close() {
      if (!modal) return;
      modal.hidden = true;
      document.body.style.overflow = previousOverflow;
      if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
    }

    function buildModal() {
      modal = document.createElement("div");
      modal.className = "site-announce-modal";
      modal.hidden = true;

      const dialog = document.createElement("div");
      dialog.className = "site-announce-dialog";
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");
      dialog.setAttribute("aria-label", "群公告");

      const time = formatTime(item.updated_at || item.created_at);
      const head = document.createElement("div");
      head.className = "site-announce-head";
      const title = document.createElement("div");
      title.className = "site-announce-title";
      title.appendChild(iconNode());
      const titleText = document.createElement("span");
      titleText.textContent = "群公告";
      title.appendChild(titleText);
      const sub = document.createElement("div");
      sub.className = "site-announce-sub";
      sub.textContent = [item.author ? `发布人 ${item.author}` : "", time].filter(Boolean).join(" · ");
      head.append(title, sub);

      const body = document.createElement("div");
      body.className = "site-announce-body";
      const paragraph = document.createElement("p");
      paragraph.className = "site-announce-content";
      paragraph.textContent = item.content;
      body.appendChild(paragraph);
      const images = Array.isArray(item.images) && item.images.length
        ? item.images.map((image) => image.url).filter(Boolean)
        : (item.image_url ? [item.image_url] : []);
      images.forEach((src) => {
        const image = document.createElement("img");
        image.className = "site-announce-image";
        image.src = src;
        image.alt = "公告配图";
        image.loading = "lazy";
        body.appendChild(image);
      });

      const foot = document.createElement("div");
      foot.className = "site-announce-foot";
      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "site-announce-close";
      closeBtn.textContent = "知道了";
      closeBtn.addEventListener("click", close);
      foot.append(closeBtn);

      dialog.append(artNode("site-announce-art-modal", ART_CORNER), head, body, foot);
      modal.appendChild(dialog);
      modal.addEventListener("click", (event) => {
        if (event.target === modal) close();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !modal.hidden) close();
      });
      document.body.appendChild(modal);
      entry._closeButton = closeBtn;
    }

    function open() {
      if (!modal) buildModal();
      markSeen(item);
      lastFocused = document.activeElement;
      previousOverflow = document.body.style.overflow;
      modal.hidden = false;
      document.body.style.overflow = "hidden";
      entry._closeButton?.focus();
    }

    entry.addEventListener("click", () => open());

    const forced = forcedId() === Number(item.id);
    if (forced || shouldPopup(item, readSeen())) {
      open();
    }
  }

  async function load() {
    try {
      const response = await fetch("/api/announcements/current", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!response.ok) return;
      const data = await response.json();
      const item = data && data.item;
      if (item && item.content) mount(item);
    } catch {
      /* 公告加载失败不影响页面 */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
