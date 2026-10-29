/* Optional guide invitation: browser memory for guests, account memory after registration. */
(() => {
  const VISITED = "kflow:guide:visited:v1";
  const WELCOME = "kflow:guide:welcome:v1";
  const PROGRESS = "kflow:guide:progress:v1";
  const ENDPOINT = "/api/user/guide-onboarding";

  function stored(key) {
    for (const name of ["localStorage", "sessionStorage"]) {
      try { if (window[name].getItem(key) === "1") return true; } catch { /* Continue without browser storage. */ }
    }
    return false;
  }

  function remember(key) {
    for (const name of ["localStorage", "sessionStorage"]) {
      try { window[name].setItem(key, "1"); } catch { /* The guide remains available. */ }
    }
  }

  function hasVisited() {
    if (stored(VISITED)) return true;
    try {
      const progress = JSON.parse(window.localStorage.getItem(PROGRESS) || "null");
      return !!(progress && (typeof progress.current === "string" || progress.completed?.length));
    } catch { return false; }
  }

  async function accountState(action) {
    const response = await fetch(ENDPOINT, {
      credentials: "same-origin",
      cache: "no-store",
      ...(action ? {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json", "X-CSRFToken": document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || "" },
        body: JSON.stringify({ action }),
      } : {}),
    });
    if (!response.ok) throw new Error("Guide state unavailable");
    return response.json();
  }

  function invite(user) {
    const header = document.querySelector("header");
    if (!header || document.querySelector("#guideWelcome")) return false;
    const modal = document.createElement("dialog");
    modal.id = "guideWelcome";
    modal.className = "guide-welcome-modal";
    modal.setAttribute("aria-labelledby", "guideWelcomeTitle");
    modal.setAttribute("aria-describedby", "guideWelcomeDescription");
    const previousFocus = document.activeElement;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "guide-welcome-close";
    close.setAttribute("aria-label", "关闭欢迎弹窗");
    close.textContent = "×";
    const mark = document.createElement("div");
    mark.className = "guide-welcome-figure";
    const character = document.createElement("img");
    character.src = "/static/xiaok/chibi-cheer-full-v1.png";
    character.alt = "";
    character.width = 160;
    character.height = 213;
    character.decoding = "async";
    character.setAttribute("aria-hidden", "true");
    character.addEventListener("error", () => { mark.textContent = "小 K"; });
    mark.append(character);
    const copy = document.createElement("div");
    copy.className = "guide-welcome-copy";
    const title = document.createElement("h2");
    title.id = "guideWelcomeTitle";
    title.textContent = user ? "欢迎加入 KFlow，\n我们一起创造吧。" : "嗨，我是小 K，\n欢迎来到 KFlow。";
    const description = document.createElement("p");
    description.id = "guideWelcomeDescription";
    description.textContent = "跟我认识一下社区，晒晒作品、聊聊日常，找到你的第一步。";
    copy.append(title, description);
    const topics = document.createElement("ul");
    topics.className = "guide-welcome-topics";
    for (const text of ["分享你的作品", "记录日常想法", "了解积分玩法"]) {
      const item = document.createElement("li");
      item.textContent = text;
      topics.append(item);
    }
    const actions = document.createElement("div");
    actions.className = "guide-welcome-actions";
    const read = document.createElement("a");
    read.href = "/guide";
    read.className = "guide-welcome-read";
    read.textContent = "阅读指南";
    read.autofocus = true;
    const skip = document.createElement("button");
    skip.type = "button";
    skip.className = "guide-welcome-skip";
    skip.textContent = "先逛逛";
    let finished = false;
    function finish() {
      if (finished) return;
      finished = true;
      if (user) {
        remember(`${WELCOME}:user:${user.username}`);
        accountState("dismissed").catch(() => {});
      } else remember(WELCOME);
      document.body.classList.remove("guide-welcome-open");
      modal.remove();
      const target = previousFocus?.isConnected && previousFocus !== document.body ? previousFocus : header.querySelector('a[href="/guide"]') || header.querySelector("a");
      target?.focus({ preventScroll: true });
    }
    function dismiss() {
      if (modal.open) modal.close();
      finish();
    }
    skip.addEventListener("click", dismiss);
    close.addEventListener("click", dismiss);
    read.addEventListener("click", dismiss);
    modal.addEventListener("close", finish);
    modal.addEventListener("cancel", (event) => { event.preventDefault(); dismiss(); });
    modal.addEventListener("click", (event) => {
      if (event.target !== modal) return;
      const rect = modal.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dismiss();
    });
    actions.append(read, skip);
    const note = document.createElement("p");
    note.className = "guide-welcome-note-text";
    note.textContent = "随时从「发现 → 新手指南」再次打开";
    modal.append(close, mark, copy, topics, actions, note);
    document.body.append(modal);
    try {
      // Native modal behavior contains keyboard focus and makes the background inert.
      modal.showModal();
      document.body.classList.add("guide-welcome-open");
      return true;
    } catch {
      modal.remove();
      return false;
    }
  }

  async function init() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    if (path.startsWith("/admin") || path === "/login") return;
    const guide = path === "/guide";
    // Record actual arrival, not a guide link click (which can be cancelled).
    if (guide) { remember(VISITED); remember(WELCOME); }
    const user = await window.kflowAuthReady;
    if (!user) {
      if (path === "/" && !hasVisited() && !stored(WELCOME)) {
        if (invite(null)) remember(WELCOME);
      }
      return;
    }
    try {
      if (guide || hasVisited()) {
        const synced = `${VISITED}:user:${user.username}`;
        if (!stored(synced)) { await accountState("visited"); remember(synced); }
        return;
      }
      if (user.role === "admin") return;
      if (stored(`${WELCOME}:user:${user.username}`)) {
        await accountState("dismissed");
        return;
      }
      const status = await accountState();
      if (!status.should_prompt) return;
      const claimed = await accountState("shown");
      if (!claimed.claimed || claimed.state === "visited") return;
      remember(`${WELCOME}:user:${user.username}`);
      invite(user);
    } catch { /* Do not interrupt browsing when account state cannot be reached. */ }
  }

  window.KflowGuide = Object.freeze({ openWelcome: async () => invite(await window.kflowAuthReady) });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
