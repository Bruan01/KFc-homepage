/* KFlow AI 电讯：AIHOT 全部动态时间流（精选条目带标记）+ 热点榜 + 信源目录。点击回原站。 */
(() => {
  "use strict";

  const PAGE_SIZE = 40;
  const CAT_COLORS = {
    model: "var(--c-model)",
    product: "var(--c-product)",
    industry: "var(--c-industry)",
    paper: "var(--c-paper)",
    tip: "var(--c-tip)",
    opinion: "var(--c-opinion)",
  };
  const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

  const catChips = document.getElementById("catChips");
  const refreshBtn = document.getElementById("refreshBtn");
  const feedTimeline = document.getElementById("feedTimeline");
  const feedEmpty = document.getElementById("feedEmpty");
  const loadMoreBtn = document.getElementById("loadMoreBtn");
  const feedsUpdated = document.getElementById("feedsUpdated");
  const directoryGrid = document.getElementById("directoryGrid");
  const hotList = document.getElementById("hotList");
  const statToday = document.getElementById("statToday");
  const statTotal = document.getElementById("statTotal");
  const statSources = document.getElementById("statSources");
  const statUpdated = document.getElementById("statUpdated");
  const staleBanner = document.getElementById("feedsStale");
  const staleTime = document.getElementById("staleTime");
  const xiaokPush = document.getElementById("xiaokPush");
  const xiaokPushTitle = document.getElementById("xiaokPushTitle");
  const xiaokPushMeta = document.getElementById("xiaokPushMeta");

  let activeCategory = "";
  let selectedOnly = false;
  let offset = 0;
  let hasMore = false;
  let categories = [];
  let loadedItems = [];
  let totalCount = 0;
  let lastLoadedAt = 0;
  let checkingNews = false;

  const NEWS_POLL_INTERVAL = 5 * 60 * 1000;

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);
  }

  function clockTime(iso) {
    const ts = Date.parse(iso);
    if (Number.isNaN(ts)) return "";
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function dayKey(iso) {
    const d = new Date(Date.parse(iso));
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
  }

  function dayParts(iso) {
    const d = new Date(Date.parse(iso));
    const now = new Date();
    const oneDay = 86400000;
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const gap = Math.round((todayStart - dayStart) / oneDay);
    const dateStr = `${d.getMonth() + 1}月${d.getDate()}日`;
    const week = WEEKDAYS[d.getDay()];
    const rel = gap === 0 ? "今天" : gap === 1 ? "昨天" : "";
    return {
      num: d.getDate(),
      label: rel ? `${rel} · ${dateStr} ${week}` : `${dateStr} ${week}`,
    };
  }

  function api(path) {
    return fetch(path, { credentials: "same-origin" }).then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    });
  }

  /* ── 分类 chips + 「仅看精选」切换 ───────────────────── */
  function renderChips() {
    const chips = [{ code: "", label: "全部" }, ...categories];
    const nodes = chips.map(({ code, label }) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "feed-chip" + (code === activeCategory ? " active" : "");
      btn.dataset.cat = code;
      btn.innerHTML = `${code ? '<span class="cat-dot"></span>' : ""}${escapeHtml(label)}`;
      btn.addEventListener("click", () => {
        if (activeCategory === code) return;
        activeCategory = code;
        offset = 0;
        renderChips();
        loadFeed(true);
      });
      return btn;
    });
    const selBtn = document.createElement("button");
    selBtn.type = "button";
    selBtn.className = "feed-chip sel-only" + (selectedOnly ? " active" : "");
    selBtn.title = "只看 AIHOT 编辑精选条目";
    selBtn.innerHTML = '<span class="sel-star" aria-hidden="true">★</span>仅看精选';
    selBtn.addEventListener("click", () => {
      selectedOnly = !selectedOnly;
      offset = 0;
      renderChips();
      loadFeed(true);
    });
    nodes.push(selBtn);
    catChips.replaceChildren(...nodes);
  }

  /* ── 时间流：抽屉柜（悬停拉开 / 点击钉住 / 同轨互斥）── */
  function scoreClass(score) {
    if (score >= 85) return "hot";
    if (score >= 70) return "good";
    return "";
  }

  // 已被用户钉住的日期（跨筛选/加载更多保留）
  const pinnedDays = new Set();

  function renderTimeline() {
    const groups = [];
    const index = new Map();
    for (const item of loadedItems) {
      const key = dayKey(item.published_at);
      if (!key) continue;
      let group = index.get(key);
      if (!group) {
        group = { key, parts: dayParts(item.published_at), items: [] };
        index.set(key, group);
        groups.push(group);
      }
      group.items.push(item);
    }
    const parts = [];
    groups.forEach((group, groupIdx) => {
      const isOpen = groupIdx === 0 || pinnedDays.has(group.key);
      if (isOpen) pinnedDays.add(group.key);
      const rows = group.items
        .map((item, rowIdx) => {
          const catColor = CAT_COLORS[item.category] || "var(--faint)";
          const scorePill = item.score
            ? `<span class="feed-score ${scoreClass(item.score)}">${item.score}</span>`
            : "";
          const selBadge = item.is_selected
            ? '<span class="feed-sel" title="AIHOT 编辑精选"><i aria-hidden="true">★</i>精选</span>'
            : "";
          return `
        <a class="feed-row" style="--cat-color:${catColor}" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
          <div class="feed-row-meta">
            <span class="feed-time">${clockTime(item.published_at)}</span>
            <span class="feed-src" title="${escapeHtml(item.upstream_name)}">${escapeHtml(item.upstream_name || item.source.name)}</span>
            ${selBadge}
            ${item.category ? `<span class="feed-cat" style="--cat-color:${catColor}">${escapeHtml(item.category_label)}</span>` : ""}
            ${scorePill}
            <button type="button" class="feed-share" data-id="${item.id}" data-title="${escapeHtml(item.title)}" data-url="${escapeHtml(item.url)}" title="转发到碎碎念">
              <svg class="i" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3.5 21 7.5l-4 4M21 7.5H8.5A4.5 4.5 0 0 0 4 12v1M7 20.5 3 16.5l4-4M3 16.5h12.5a4.5 4.5 0 0 0 4.5-4.5v-1"/></svg>碎碎念
            </button>
          </div>
          <span class="feed-row-title">${escapeHtml(item.title)}</span>
          ${item.summary ? `<div class="feed-row-summary">${escapeHtml(item.summary)}</div>` : ""}
        </a>`;
        })
        .join("");
      parts.push(`
        <section class="day-group drawer${isOpen ? " open pinned" : ""}" data-day="${group.key}">
          <button type="button" class="drawer-face" aria-expanded="${isOpen}">
            <span class="drawer-handle" aria-hidden="true"><i></i><i></i></span>
            <span class="day-num">${group.parts.num}</span>
            <span class="day-label">${escapeHtml(group.parts.label)}</span>
            <span class="day-count">${group.items.length} 条</span>
            <svg class="drawer-chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9.5l6 6 6-6"/></svg>
          </button>
          <div class="drawer-body"><div class="drawer-body-inner">${rows}</div></div>
        </section>`);
    });
    feedTimeline.innerHTML = parts.join("");
  }

  function setDrawer(drawer, open, pinned) {
    drawer.classList.toggle("open", open);
    drawer.classList.toggle("pinned", Boolean(pinned));
    drawer.querySelector(".drawer-face")?.setAttribute("aria-expanded", String(open));
    const key = drawer.dataset.day;
    if (pinned) pinnedDays.add(key);
    else pinnedDays.delete(key);
  }

  // 点击：抽屉拉开并钉住；再点合上。同轨互斥——拉出一格，其他钉住的自动合拢。
  feedTimeline.addEventListener("click", (event) => {
    const face = event.target.closest(".drawer-face");
    if (!face) return;
    const drawer = face.closest(".drawer");
    const open = drawer.classList.contains("open");
    const pinned = drawer.classList.contains("pinned");
    if (open && pinned) {
      setDrawer(drawer, false, false);
      return;
    }
    feedTimeline.querySelectorAll(".drawer.open").forEach((d) => {
      if (d !== drawer) setDrawer(d, false, false);
    });
    setDrawer(drawer, true, true);
  });

  // 悬停自动拉开（仅支持 hover 的设备）：拉开不钉住，移出后自动合上。
  if (window.matchMedia("(hover: hover)").matches) {
    const HOVER_OPEN_DELAY = 160;
    const HOVER_CLOSE_DELAY = 360;
    let hoverDrawer = null;
    let openTimer = 0;
    let closeTimer = 0;

    feedTimeline.addEventListener("mouseover", (event) => {
      const drawer = event.target.closest(".drawer");
      if (!drawer || drawer === hoverDrawer) return;
      if (hoverDrawer && !hoverDrawer.classList.contains("pinned") && hoverDrawer.isConnected) {
        setDrawer(hoverDrawer, false, false);
      }
      hoverDrawer = drawer;
      clearTimeout(openTimer);
      clearTimeout(closeTimer);
      if (!drawer.classList.contains("open")) {
        openTimer = setTimeout(() => setDrawer(drawer, true, false), HOVER_OPEN_DELAY);
      }
    });

    feedTimeline.addEventListener("mouseout", (event) => {
      const drawer = event.target.closest(".drawer");
      if (!drawer || drawer !== hoverDrawer) return;
      const to = event.relatedTarget && event.relatedTarget.closest ? event.relatedTarget.closest(".drawer") : null;
      if (to === drawer) return;
      clearTimeout(openTimer);
      hoverDrawer = null;
      if (!drawer.classList.contains("pinned")) {
        closeTimer = setTimeout(() => setDrawer(drawer, false, false), HOVER_CLOSE_DELAY);
      }
    });
  }

  /* ── 小K 推送：今日必读（今日精选里评分最高，无精选再退回全部）── */
  function renderXiaokPush() {
    const todayKey = dayKey(new Date().toISOString());
    const pool = loadedItems.filter((i) => dayKey(i.published_at) === todayKey);
    const selectedPool = pool.filter((i) => i.is_selected);
    const candidates = selectedPool.length ? selectedPool : pool.length ? pool : loadedItems;
    const pick = candidates
      .slice()
      .sort((a, b) => (b.score || 0) - (a.score || 0) || Date.parse(b.published_at) - Date.parse(a.published_at))[0];
    if (!pick) {
      xiaokPush.hidden = true;
      return;
    }
    xiaokPush.hidden = false;
    xiaokPushTitle.textContent = pick.title;
    xiaokPushTitle.href = pick.url;
    const metaBits = [
      pick.upstream_name || pick.source.name,
      pick.category ? pick.category_label : "",
      clockTime(pick.published_at),
    ].filter(Boolean);
    xiaokPushMeta.innerHTML = `${metaBits.map((bit) => escapeHtml(bit)).join(' <span style="opacity:.4">·</span> ')}${
      pick.score ? ` <span class="feed-score ${scoreClass(pick.score)}">${pick.score}</span>` : ""
    }`;
  }

  async function loadFeed(reset) {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (activeCategory) params.set("category", activeCategory);
    if (selectedOnly) params.set("selected", "1");
    try {
      const data = await api(`/api/feeds/items?${params}`);
      if (Array.isArray(data.categories) && data.categories.length) {
        categories = data.categories;
        renderChips();
      }
      hasMore = Boolean(data.has_more);
      totalCount = data.total;
      lastLoadedAt = Date.now();
      if (reset) loadedItems = [];
      loadedItems.push(...data.items);
      renderTimeline();
      renderXiaokPush();
      feedEmpty.hidden = loadedItems.length > 0;
      loadMoreBtn.hidden = !hasMore;
      loadMoreBtn.textContent = hasMore ? `加载更多（已显示 ${loadedItems.length}/${totalCount}）` : "加载更多";
      feedsUpdated.textContent = totalCount
        ? `收录 ${totalCount} 条 · 小K 已更新 ${new Date(lastLoadedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} · 后端每 30 分钟抓取`
        : "";
      renderStats(data);
    } catch (err) {
      feedEmpty.hidden = false;
      feedEmpty.textContent = `小K 说：加载失败了（${err.message}），稍后再刷新试试。`;
    }
  }

  function renderStats(data) {
    statTotal.textContent = data.total ? String(data.total) : "–";
    const todayKey = dayKey(new Date().toISOString());
    const todayCount = loadedItems.filter((i) => dayKey(i.published_at) === todayKey).length;
    statToday.textContent = todayCount ? String(todayCount) : "–";
  }

  /* ── 热点榜（AIHOT 热榜代理）────────────────────────── */
  async function loadHot() {
    try {
      const data = await api("/api/feeds/hot");
      if (!data.items.length) {
        hotList.innerHTML = '<li class="aside-note">热点暂不可用</li>';
        return;
      }
      const maxSignal = Math.max(...data.items.map((t) => t.signal_count || 0), 1);
      hotList.innerHTML = data.items
        .map(
          (topic) => `
        <li class="hot-item">
          <span class="hot-index">${topic.rank}</span>
          <span class="hot-body">
            <a class="hot-title" href="${escapeHtml(topic.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(topic.title)}</a>
            <span class="hot-signal"><i class="hot-signal-bar" data-w="${Math.round(((topic.signal_count || 0) / maxSignal) * 100)}"></i>${topic.signal_count || 0} 信号 · ${topic.source_count || 0} 源</span>
          </span>
        </li>`,
        )
        .join("");
      // 热度条入场动画：渲染后下一帧铺开
      requestAnimationFrame(() => {
        hotList.querySelectorAll(".hot-signal-bar").forEach((bar) => {
          bar.style.width = `${bar.dataset.w}%`;
        });
      });
    } catch (err) {
      hotList.innerHTML = '<li class="aside-note">热点加载失败</li>';
    }
  }

  /* ── 信源目录 ────────────────────────────────────────── */
  function renderDirectory(sources) {
    statSources.textContent = String(sources.length);
    const groups = new Map();
    for (const source of sources) {
      if (!groups.has(source.category_label)) groups.set(source.category_label, []);
      groups.get(source.category_label).push(source);
    }
    const parts = [];
    for (const [label, items] of groups) {
      const pills = items
        .map(
          (source) => `
        <a class="dir-pill ${source.slug === "aihot" ? "dir-primary" : ""}" href="${escapeHtml(source.site_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(source.description || source.name)}">
          <span class="dir-pill-icon">${escapeHtml(source.icon || "📰")}</span>${escapeHtml(source.name)}${source.has_feed ? '<span class="dir-live-dot"></span>' : ""}
        </a>`,
        )
        .join("");
      parts.push(`<div class="dir-group"><h4 class="dir-group-title">${escapeHtml(label)}</h4><div class="dir-list">${pills}</div></div>`);
    }
    directoryGrid.innerHTML = parts.join("");
  }

  /* ── 新鲜度：更新于 HH:MM + 超 2 小时停更横幅 ────────── */
  function renderFreshness(freshness) {
    if (!freshness) return;
    if (freshness.last_success_at) {
      const d = new Date(Date.parse(freshness.last_success_at));
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const hm = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
      statUpdated.textContent = sameDay ? hm : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
    } else {
      statUpdated.textContent = "–";
    }
    staleTime.textContent = statUpdated.textContent;
    staleBanner.hidden = !freshness.is_stale;
  }

  /* ── 信源目录 ────────────────────────────────────────── */
  async function loadSources() {
    try {
      const data = await api("/api/feeds/sources");
      renderDirectory(data.items || []);
      renderFreshness(data.freshness);
    } catch (err) {
      directoryGrid.innerHTML = '<p class="aside-note">信源目录加载失败</p>';
    }
  }

  async function init() {
    loadHot();
    await loadSources();
    await loadFeed(true);
  }

  loadMoreBtn.addEventListener("click", () => {
    offset += PAGE_SIZE;
    loadFeed(false);
  });

  /* ── 实时性：新资讯检查 + 刷新 ──────────────────────── */
  async function checkNews() {
    if (checkingNews || !totalCount) return;
    checkingNews = true;
    try {
      const params = new URLSearchParams({ limit: "1" });
      if (activeCategory) params.set("category", activeCategory);
      if (selectedOnly) params.set("selected", "1");
      const data = await api(`/api/feeds/items?${params}`);
      if (data.total > totalCount) {
        refreshBtn.textContent = `↻ 小K：${data.total - totalCount} 条新资讯`;
        refreshBtn.classList.add("has-news");
      } else if (data.total < totalCount) {
        totalCount = data.total;
      }
    } catch (err) {
      /* 轮询失败不打扰阅读 */
    } finally {
      checkingNews = false;
    }
  }

  refreshBtn.addEventListener("click", async () => {
    refreshBtn.textContent = "↻ 小K 刷新中…";
    refreshBtn.classList.remove("has-news");
    offset = 0;
    await Promise.all([loadFeed(true), loadHot(), loadSources()]);
    refreshBtn.textContent = "↻ 刷新";
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - lastLoadedAt > 60000) checkNews();
  });
  setInterval(checkNews, NEWS_POLL_INTERVAL);

  /* ── 问小K：对话式摄入（带引用）──────────────────────── */
  const askInput = document.getElementById("xiaokAskInput");
  const askSend = document.getElementById("xiaokAskSend");
  const askAnswer = document.getElementById("xiaokAskAnswer");
  const askText = document.getElementById("xiaokAskText");
  const askRefs = document.getElementById("xiaokAskRefs");
  const askSugs = document.getElementById("xiaokAskSugs");

  function renderAnswer(answer, refs) {
    const refMap = new Map(refs.map((r) => [r.n, r]));
    // 【n】编号替换为可点击引用，仅保留回答里实际引用的条目
    const cited = new Set();
    const html = escapeHtml(answer).replace(/【(\d+)】/g, (_, num) => {
      const n = Number(num);
      const ref = refMap.get(n);
      if (!ref) return `【${num}】`;
      cited.add(n);
      return `<a class="cite" href="${escapeHtml(ref.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(ref.title)}">[${n}]</a>`;
    });
    askText.innerHTML = html;
    const shown = cited.size
      ? refs.filter((r) => cited.has(r.n))
      : refs.slice(0, 3);
    askRefs.innerHTML = shown
      .map(
        (r) => `<li><a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">
          <span class="ref-n">[${r.n}]</span>
          <span>${escapeHtml(r.title)}<span style="opacity:.6"> · ${escapeHtml(r.source)}</span></span>
        </a></li>`,
      )
      .join("");
    askAnswer.hidden = false;
    askAnswer.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function askXiaok(question) {
    if (!question || askSend.disabled) return;
    askSend.disabled = true;
    askSend.textContent = "小K 想想…";
    try {
      const res = await fetch("/api/feeds/ask", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        location.href = "/login?next=%2Ffeeds";
        return;
      }
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      renderAnswer(data.answer, data.refs || []);
    } catch (err) {
      askText.textContent = `小K 暂时答不上来：${err.message}`;
      askRefs.innerHTML = "";
      askAnswer.hidden = false;
    } finally {
      askSend.disabled = false;
      askSend.textContent = "问小K";
    }
  }

  askSend.addEventListener("click", () => {
    const q = askInput.value.trim();
    if (q) askXiaok(q);
  });
  askInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") askSend.click();
  });
  askSugs.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-q]");
    if (!btn) return;
    askInput.value = btn.dataset.q;
    askXiaok(btn.dataset.q);
  });

  /* ── 转发到碎碎念 ─────────────────────────────────────── */
  const shareMask = document.getElementById("shareMask");
  const shareSrcTitle = document.getElementById("shareSrcTitle");
  const shareInput = document.getElementById("shareInput");
  const shareSubmit = document.getElementById("shareSubmit");
  let shareTarget = null;

  function resetShareButton() {
    shareSubmit.disabled = false;
    shareSubmit.textContent = "发布";
    delete shareSubmit.dataset.loginMode;
    shareInput.disabled = false;
  }

  feedTimeline.addEventListener("click", (event) => {
    const btn = event.target.closest(".feed-share");
    if (!btn || btn.classList.contains("shared")) return;
    event.preventDefault();
    event.stopPropagation();
    shareTarget = btn;
    shareSrcTitle.textContent = btn.dataset.title;
    shareInput.value = "";
    shareMask.hidden = false;
    resetShareButton();
    shareInput.focus();
    // 未登录：发布按钮转为「去登录」，避免点了发布才被 401 弹走
    window.kflowAuthReady?.then((user) => {
      if (shareMask.hidden || shareTarget !== btn) return;
      if (!user) {
        shareSubmit.textContent = "去登录";
        shareSubmit.dataset.loginMode = "1";
        shareInput.disabled = true;
        shareInput.placeholder = "登录后就可以带你的看法转发啦";
      }
    });
  });

  function closeShare() {
    shareMask.hidden = true;
    shareTarget = null;
    resetShareButton();
  }
  document.getElementById("shareCancel").addEventListener("click", closeShare);
  shareMask.addEventListener("click", (event) => {
    if (event.target === shareMask) closeShare();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !shareMask.hidden) closeShare();
  });
  // 登录页返回（bfcache）时强制复位，避免带着禁用按钮的旧对话框卡住
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) closeShare();
  });

  shareSubmit.addEventListener("click", async () => {
    if (shareSubmit.dataset.loginMode) {
      location.href = "/login?next=%2Ffeeds";
      return;
    }
    if (!shareTarget) return;
    shareSubmit.disabled = true;
    const { id, title, url } = shareTarget.dataset;
    const comment = shareInput.value.trim();
    const content = `${comment ? comment + "\n\n" : ""}📰 ${title}\n${url}\n#AI电讯`;
    try {
      const res = await fetch("/api/murmurs", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, client_key: `feed-share-${id}-${Date.now()}` }),
      });
      if (res.status === 401) {
        resetShareButton();
        location.href = "/login?next=%2Ffeeds";
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      shareTarget.classList.add("shared");
      shareTarget.innerHTML = "✓ 已转";
      const toast = document.getElementById("forum-toast");
      if (toast) {
        toast.textContent = "已转发到碎碎念";
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 2200);
      }
      closeShare();
    } catch (err) {
      const toast = document.getElementById("forum-toast");
      if (toast) {
        toast.textContent = `转发失败：${err.message}`;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 2600);
      }
      shareSubmit.disabled = false;
    }
  });

  init();
})();
