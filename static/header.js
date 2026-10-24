/* 站点统一头部行为：登录态渲染 + 分组导航高亮 + 下拉菜单（悬停出现，触屏点按切换）。 */
(() => {
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

  // 论坛头部导航用的是原生 <details> 下拉（发现/权益/产品）：原生没有互斥，
  // 依次点开会同时挂好几个菜单层叠在页面顶部。这里补上互斥 + 点外部/ESC 收起。
  function bindNativeNavDetails() {
    const all = Array.from(document.querySelectorAll('nav[aria-label="站点导航"] details'));
    if (!all.length) return;
    all.forEach((d) => {
      d.addEventListener("toggle", () => {
        if (!d.open) return;
        all.forEach((other) => { if (other !== d) other.open = false; });
      });
    });
    document.addEventListener("click", (event) => {
      if (event.target.closest('nav[aria-label="站点导航"]')) return;
      all.forEach((d) => { d.open = false; });
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") all.forEach((d) => { d.open = false; });
    });
  }

  function bindDropdowns() {
    const groups = Array.from(document.querySelectorAll(".community-nav .nav-group"));
    function closeAll(except) {
      groups.forEach((g) => {
        if (g !== except) g.classList.remove("open");
      });
    }
    // 窄屏下导航条在横向滚动容器里，绝对定位的下拉会被裁掉，所以 CSS 把它改成 fixed。
    // 但头部高度随换行变化，写死的 top 会错位，这里按头部真实底边定位。
    function placeOpenDropdowns() {
      if (!window.matchMedia("(max-width: 860px)").matches) {
        groups.forEach((g) => { const dd = g.querySelector(".nav-dropdown"); if (dd) { dd.style.top = ""; dd.style.maxHeight = ""; } });
        return;
      }
      groups.forEach((g) => {
        if (!g.classList.contains("open")) return;
        const dd = g.querySelector(".nav-dropdown");
        const header = g.closest(".forum-header, .topbar") || document.querySelector(".forum-header, .topbar");
        if (!dd || !header) return;
        const bottom = Math.round(header.getBoundingClientRect().bottom);
        dd.style.top = `${bottom + 6}px`;
        dd.style.maxHeight = `${Math.max(120, window.innerHeight - bottom - 16)}px`;
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
        placeOpenDropdowns();
      });
    }
    window.addEventListener("resize", placeOpenDropdowns, { passive: true });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".nav-group")) closeAll();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAll();
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

  function init() {
    ensureGuideLink();
    ensureMurmursLink();
    markActiveNav();
    bindDropdowns();
    bindNativeNavDetails();
    renderAccount();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
