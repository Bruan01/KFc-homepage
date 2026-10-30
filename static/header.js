/* 站点统一头部行为：登录态渲染 + 分组导航高亮 + 下拉菜单（悬停出现，触屏点按切换）。 */
(() => {
  // 本脚本地址上的 ?v=<内容指纹>，注入其它运行时脚本时复用（当前脚本的
  // currentScript 只在执行期有效，DOMContentLoaded 之后就没了）。
  const SELF_VERSION = (() => {
    try {
      return new URL(document.currentScript?.src || "", location.href).searchParams.get("v") || "";
    } catch {
      return "";
    }
  })();

  // 让各页面共享同一次登录态请求，避免页面各自请求时出现竞态，
  // 导致论坛详情先被渲染成“未登录”状态。
  let resolveAuthReady;
  window.kflowAuthReady = new Promise((resolve) => {
    resolveAuthReady = resolve;
  });

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  function pathMatches(href) {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    const target = (href || "").replace(/\/+$/, "");
    if (!target) return false;
    if (target === "/") return path === "/" || path === "/forum";
    return path === target || path.startsWith(target + "/");
  }

  function ensureGuideLink() {
    const discovery = Array.from(document.querySelectorAll(".community-nav .nav-group")).find((group) =>
      group.querySelector(".nav-group-btn")?.textContent.includes("发现"),
    )?.querySelector(".nav-dropdown");
    if (!discovery || discovery.querySelector('a[href="/guide"]')) return;
    const link = document.createElement("a");
    link.href = "/guide";
    link.innerHTML = '<span class="dd-icon"><svg class="i" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4.5h14v15H5zM8 8h8M8 12h5M8 16h8"/></svg></span><span class="dd-text"><strong>新手指南</strong><small>第一次来，从这里开始</small></span>';
    discovery.prepend(link);
  }

  // AI 电讯入口：顶级导航项（不再收进「发现」下拉）。两代头部（旧 .community-nav
  // / 新原生 li+details）都注入，插在碎碎念之后，保持全站顺序一致。
  function ensureFeedsLink() {
    document.querySelectorAll('.community-nav, nav[aria-label="站点导航"]').forEach((nav) => {
      if (nav.querySelector(':scope > a[href="/feeds"], :scope > li > a[href="/feeds"]')) return;
      const link = document.createElement("a");
      link.href = "/feeds";
      link.dataset.nav = "feeds";
      link.textContent = "AI 电讯";
      const murmurs = nav.querySelector(':scope > a[data-nav="murmurs"], :scope > li > a[data-nav="murmurs"]');
      const anchor = murmurs || nav.querySelector(':scope > a, :scope > li > a[data-nav]');
      if (anchor) {
        link.className = anchor.className;
        link.classList.remove("active");
        if (anchor.parentElement.tagName === "LI") {
          const item = document.createElement("li");
          item.append(link);
          anchor.parentElement.after(item);
        } else anchor.after(link);
      } else nav.prepend(link);
    });
    // 兜底：移除旧版收在「发现」下拉里的 AI 资讯项（避免与顶级项重复）。
    document.querySelectorAll(".nav-dropdown a[href='/feeds'], nav[aria-label='站点导航'] details ul a[href='/feeds']")
      .forEach((stale) => stale.closest("li")?.remove() || stale.remove());
  }

  // 显影入口：从顶级移进「产品」下拉组。两代头部都处理。
  function ensureImagingInProducts() {
    const imagingInner =
      '<span class="dd-icon"><svg class="i" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM3.5 12l1.4-2.8 3.1-.4 1.6-2.7h4.8l1.6 2.7 3.1.4L20.5 12l-1.4 2.8-3.1.4-1.6 2.7H9.6L8 15.2l-3.1-.4z"/></svg></span><span class="dd-text"><strong>显影</strong><small>AI 图像生成工坊</small></span>';
    // 旧版：.nav-group（按钮含「产品」）的 .nav-dropdown
    document.querySelectorAll(".community-nav .nav-group").forEach((group) => {
      if (!group.querySelector(".nav-group-btn")?.textContent.includes("产品")) return;
      const dropdown = group.querySelector(".nav-dropdown");
      if (dropdown && !dropdown.querySelector('a[href="/imaging"]')) {
        const link = document.createElement("a");
        link.href = "/imaging";
        link.dataset.nav = "imaging";
        link.innerHTML = imagingInner;
        dropdown.prepend(link);
      }
    });
    // 新版：原生 details（summary 含「产品」）的 ul
    document.querySelectorAll('nav[aria-label="站点导航"] details').forEach((details) => {
      if (!details.querySelector("summary")?.textContent.includes("产品")) return;
      const list = details.querySelector("ul");
      if (list && !list.querySelector('a[href="/imaging"]')) {
        const item = document.createElement("li");
        item.innerHTML = `<a href="/imaging" data-nav="imaging">${imagingInner}</a>`;
        list.prepend(item);
      }
    });
    // 移除顶级显影项（已入「产品」组）
    document.querySelectorAll(".community-nav > a[data-nav='imaging']").forEach((a) => a.remove());
    document.querySelectorAll('nav[aria-label="站点导航"] > li > a[data-nav="imaging"]').forEach((a) => a.closest("li")?.remove());
  }

  // 桌面终端入口：放进「产品」下拉，排在「服务状态」之前。
  // 它是一件硬件产品，不是运维页，所以跟产品站同组而不是独立顶级项。
  // 同样两代头部都处理：旧版 .nav-group + .nav-dropdown，新版 details + ul。
  function ensureTerminalInProducts() {
    const inner =
      '<span class="dd-icon"><svg class="i" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 5.5h17v10.5h-17zM9.5 20h5M12 16v4"/></svg></span><span class="dd-text"><strong>桌面终端</strong><small>书桌上的小屏，只看你的数据</small></span>';

    // 插入位置统一走同一个函数，避免两代头部的顺序不一致。
    const insert = (container, wrapInLi) => {
      if (!container || container.querySelector('a[href="/terminal"]')) return;
      const anchor = container.querySelector('a[href="/service-status"]');
      if (wrapInLi) {
        const item = document.createElement("li");
        item.innerHTML = `<a href="/terminal" data-nav="terminal">${inner}</a>`;
        if (anchor) anchor.closest("li")?.before(item);
        else container.append(item);
      } else {
        const link = document.createElement("a");
        link.href = "/terminal";
        link.dataset.nav = "terminal";
        link.innerHTML = inner;
        if (anchor) anchor.before(link);
        else container.append(link);
      }
    };

    document.querySelectorAll(".community-nav .nav-group").forEach((group) => {
      if (!group.querySelector(".nav-group-btn")?.textContent.includes("产品")) return;
      insert(group.querySelector(".nav-dropdown"), false);
    });
    document.querySelectorAll('nav[aria-label="站点导航"] details').forEach((details) => {
      if (!details.querySelector("summary")?.textContent.includes("产品")) return;
      insert(details.querySelector("ul"), true);
    });
  }

  function ensurePersonalityInProducts() {
    const inner = '<span class="dd-icon"><svg class="i" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M12 20S3 15 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 7-9 12-9 12Z"/></svg></span><span class="dd-text"><strong>心映</strong><small>动漫人格探索</small></span>';
    document.querySelectorAll('.community-nav .nav-group, nav[aria-label="站点导航"] details').forEach(group => {
      if (!(group.querySelector('.nav-group-btn, summary')?.textContent || '').includes('产品')) return;
      const container = group.querySelector('.nav-dropdown, ul');
      if (!container || container.querySelector('a[href="/personality"]')) return;
      const link = document.createElement('a');
      link.href = '/personality'; link.dataset.nav = 'personality'; link.innerHTML = inner;
      if (container.tagName === 'UL') { const item = document.createElement('li'); item.append(link); container.prepend(item); }
      else container.prepend(link);
    });
  }

  function markActiveNav() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    // 直达项（社区 / 产品）
    document.querySelectorAll('.community-nav > a[data-nav], nav[aria-label="站点导航"] > li > a[data-nav]').forEach((a) => {
      a.classList.toggle("active", pathMatches(a.getAttribute("href")));
    });
    // 分组：当前页在组内则整组高亮，组内项单独高亮
    document.querySelectorAll(".community-nav .nav-group").forEach((group) => {
      let groupActive = false;
      group.querySelectorAll(".nav-dropdown a").forEach((a) => {
        let isActive = pathMatches(a.getAttribute("href"));
        // 个人主页项：浏览任何用户主页时都点亮
        if (!isActive && a.id === "navMineProfile" && path.startsWith("/forum/user")) {
          isActive = true;
        }
        a.classList.toggle("active", isActive);
        if (isActive) groupActive = true;
      });
      // 个人中心特殊：/account 及其子路径
      if (group.dataset.navGroup === "mine" && (path.startsWith("/account") || path.startsWith("/forum/user"))) {
        groupActive = true;
      }
      group.classList.toggle("active", groupActive);
    });
  }

  function ensureMurmursLink() {
    document.querySelectorAll('.community-nav, nav[aria-label="站点导航"]').forEach((nav) => {
      if (nav.querySelector('a[href="/murmurs"]')) return;
      const link = document.createElement("a");
      link.href = "/murmurs";
      link.dataset.nav = "murmurs";
      link.textContent = "碎碎念";
      const firstLink = nav.querySelector(':scope > a, :scope > li > a[data-nav="home"]');
      // Keep the same geometry on both legacy and Tailwind-based headers.
      if (firstLink) {
        link.className = firstLink.className;
        link.classList.remove("active");
        if (firstLink.parentElement.tagName === "LI") {
          const item = document.createElement("li");
          item.append(link);
          firstLink.parentElement.after(item);
        } else firstLink.after(link);
      } else nav.prepend(link);
    });
    const userMenu = document.getElementById("userMenuPanel");
    const makeMenuEntry = (href, text) => {
      const link = document.createElement("a");
      link.href = href;
      link.textContent = text;
      if (userMenu.getAttribute("role") === "menu") link.setAttribute("role", "menuitem");
      if (userMenu.tagName !== "UL") return link;
      const item = document.createElement("li");
      item.append(link);
      return item;
    };
    for (const [href,label] of [["/messages","私信"],["/account/settings","设置"]]) {
      if (userMenu && !userMenu.querySelector(`a[href="${href}"]`)) userMenu.prepend(makeMenuEntry(href, label));
    }

    if (userMenu && !userMenu.querySelector('a[href="/murmurs?scope=mine"]')) {
      const mine = makeMenuEntry("/murmurs?scope=mine", "我的碎碎念");
      const account = userMenu.querySelector('a[href="/account"]');
      if (account) (account.closest("li") || account).after(mine);
      else userMenu.prepend(mine);
    }
  }

  const MOBILE_NAV_QUERY = "(max-width: 1100px)";

  function navHeader() {
    return document.querySelector(".forum-header, .navbar, .topbar");
  }

  function openNavMenus() {
    return Array.from(document.querySelectorAll(".community-nav .nav-group.open"))
      .map((group) => group.querySelector(".nav-dropdown"))
      .filter(Boolean)
      .concat(Array.from(document.querySelectorAll('nav[aria-label="站点导航"] details[open]'))
        .map((details) => details.querySelector(":scope > ul"))
        .filter(Boolean));
  }

  function clearMenuPlacement(menu) {
    if (!menu) return;
    ["position", "top", "right", "left", "width", "max-height", "margin-top", "transform"].forEach((name) => menu.style.removeProperty(name));
  }

  // 窄屏头部有 backdrop-filter（会成为 fixed 后代的包含块）且导航条横向滚动，
  // 下拉层因此被裁掉或定位到视口外。打开时由 JS 接管：临时关掉模糊，
  // 解除 overflow，再按头部真实底边把菜单固定在视口里。
  function placeNavMenu(menu, header) {
    if (!menu) return;
    if (!window.matchMedia(MOBILE_NAV_QUERY).matches) {
      clearMenuPlacement(menu);
      return;
    }
    const bottom = Math.round((header ? header.getBoundingClientRect().bottom : 0) + 6);
    menu.style.position = "fixed";
    menu.style.top = `${bottom}px`;
    menu.style.left = "14px";
    menu.style.right = "14px";
    menu.style.width = "auto";
    menu.style.marginTop = "0";
    menu.style.transform = "none";
    menu.style.maxHeight = `${Math.max(160, window.innerHeight - bottom - 16)}px`;
  }

  function syncNavMenus() {
    const header = navHeader();
    const menus = openNavMenus();
    const mobile = window.matchMedia(MOBILE_NAV_QUERY).matches;
    if (header) header.classList.toggle("nav-menu-open", mobile && menus.length > 0);
    if (!mobile) {
      document.querySelectorAll(".nav-dropdown, nav[aria-label='站点导航'] details > ul").forEach(clearMenuPlacement);
      return;
    }
    menus.forEach((menu) => placeNavMenu(menu, header));
    document.querySelectorAll(".nav-dropdown, nav[aria-label='站点导航'] details > ul")
      .forEach((menu) => { if (!menus.includes(menu)) clearMenuPlacement(menu); });
  }

  // 论坛头部导航用的是原生 <details> 下拉（发现/权益/产品）：原生没有互斥，
  // 依次点开会同时挂好几个菜单层叠在页面顶部。这里补上互斥 + 点外部/ESC 收起。
  function bindNativeNavDetails() {
    const all = Array.from(document.querySelectorAll('nav[aria-label="站点导航"] details'));
    if (!all.length) return;
    all.forEach((d) => {
      d.addEventListener("toggle", () => {
        if (d.open) {
          all.forEach((other) => { if (other !== d) other.open = false; });
        }
        syncNavMenus();
      });
    });
    document.addEventListener("click", (event) => {
      if (event.target.closest('nav[aria-label="站点导航"]')) return;
      all.forEach((d) => { d.open = false; });
      syncNavMenus();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      all.forEach((d) => { d.open = false; });
      syncNavMenus();
    });
  }

  function bindDropdowns() {
    const groups = Array.from(document.querySelectorAll(".community-nav .nav-group"));
    function closeAll(except) {
      groups.forEach((g) => {
        if (g !== except) g.classList.remove("open");
      });
    }
    for (const group of groups) {
      const btn = group.querySelector(".nav-group-btn");
      if (!btn) continue;
      // 触屏 / 键盘：点按切换
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const willOpen = !group.classList.contains("open");
        closeAll(group);
        group.classList.toggle("open", willOpen);
        syncNavMenus();
      });
    }
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".nav-group")) {
        closeAll();
        syncNavMenus();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      closeAll();
      syncNavMenus();
    });
  }

  async function renderAccount() {
    const loginEl = document.getElementById("siteLoginLink");
    const wrap = document.getElementById("userMenuWrap");
    const btn = document.getElementById("userMenuBtn");
    const panel = document.getElementById("userMenuPanel");
    const avatarEl = document.getElementById("userMenuAvatar");
    const nameEl = document.getElementById("userMenuName");
    const adminEl = document.getElementById("menuAdmin");
    const logoutEl = document.getElementById("menuLogout");
    const mineProfile = document.getElementById("navMineProfile");
    const mineAccount = document.getElementById("navMineAccount");
    if (loginEl) {
      const next = encodeURIComponent(location.pathname + location.search);
      loginEl.setAttribute("href", `/login?next=${next}`);
    }
    let user = null;
    try {
      const res = await fetch("/api/account/me", { credentials: "same-origin" });
      const data = await res.json();
      if (data.loggedIn) {
        user = {
          username: data.username,
          role: data.role || "user",
          adminLevel: Number(data.adminLevel || 0),
          isSuper: Boolean(data.isSuper),
        };
      }
    } catch {
      user = null;
    }

    window.dispatchEvent(new CustomEvent("kflow:auth-changed", { detail: user }));
    resolveAuthReady?.(user);
    resolveAuthReady = null;

    function closeMenu() {
      if (panel) panel.hidden = true;
      if (btn) {
        btn.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
      }
    }

    if (!user) {
      if (wrap) wrap.style.display = "none";
      if (loginEl) loginEl.style.display = "";
      return;
    }
    if (loginEl) loginEl.style.display = "none";
    if (wrap) wrap.style.display = "inline-flex";

    // 头像：优先用户设置的头像，否则默认首字母圆标
    let avatarUrl = "";
    try {
      const res = await fetch(`/api/forum/users/${encodeURIComponent(user.username)}`, { credentials: "same-origin" });
      if (res.ok) avatarUrl = (await res.json()).profile?.avatar_url || "";
    } catch {
      avatarUrl = "";
    }
    if (avatarEl) {
      avatarEl.replaceChildren();
      if (avatarUrl) {
        const img = document.createElement("img");
        img.src = avatarUrl;
        img.alt = "头像";
        img.addEventListener("error", () => {
          avatarEl.replaceChildren((user.username || "?").slice(0, 1).toUpperCase());
        });
        avatarEl.append(img);
      } else {
        avatarEl.textContent = (user.username || "?").slice(0, 1).toUpperCase();
      }
    }
    if (nameEl) nameEl.textContent = user.username;
    if (adminEl) adminEl.style.display = user.role === "admin" ? "" : "none";
    if (mineProfile) mineProfile.setAttribute("href", `/forum/user/${encodeURIComponent(user.username)}`);
    if (mineAccount) mineAccount.setAttribute("href", "/account");

    if (btn) {
      if (panel) btn.setAttribute("aria-controls", panel.id);
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!panel) return;
        if (panel.hidden) {
          document.querySelectorAll('nav[aria-label="站点导航"] details[open]').forEach((details) => {
            details.open = false;
          });
          document.querySelectorAll(".community-nav .nav-group.open").forEach((group) => {
            group.classList.remove("open");
          });
          syncNavMenus();
        }
        panel.hidden = !panel.hidden;
        btn.classList.toggle("open", !panel.hidden);
        btn.setAttribute("aria-expanded", String(!panel.hidden));
      });
    }
    document.addEventListener("click", (e) => {
      if (panel && !panel.hidden && !e.target.closest(".user-menu-wrap")) closeMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenu();
    });
    if (logoutEl) {
      logoutEl.addEventListener("click", async () => {
        try {
          await fetch("/api/user/logout", {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrf() },
          });
        } catch {
          /* 忽略，仍然跳回 */
        }
        window.location.href = "/";
      });
    }
    markActiveNav();
  }

  function ensureAnnouncement() {
    if (window.__kflowAnnouncementLoaded) return;
    if (document.querySelector("script[data-kflow-announcement]")) return;
    const script = document.createElement("script");
    // 带上页面渲染时给 header.js 的内容指纹：裸路径会被 immutable 缓存钉死。
    script.src = "/announcement.js" + (SELF_VERSION ? `?v=${SELF_VERSION}` : "");
    script.defer = true;
    script.dataset.kflowAnnouncement = "1";
    document.head.appendChild(script);
  }

  function init() {
    ensureGuideLink();
    ensureMurmursLink();
    ensureFeedsLink();
    ensureImagingInProducts();
    ensureTerminalInProducts();
    ensurePersonalityInProducts();
    ensureAnnouncement();
    markActiveNav();
    bindDropdowns();
    bindNativeNavDetails();
    syncNavMenus();
    window.addEventListener("resize", syncNavMenus, { passive: true });
    window.addEventListener("scroll", () => {
      const header = navHeader();
      if (header?.classList.contains("nav-menu-open")) syncNavMenus();
    }, { passive: true });
    renderAccount();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
