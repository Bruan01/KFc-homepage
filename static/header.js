/* 站点统一头部行为：登录态渲染 + 分组导航高亮 + 下拉菜单（悬停出现，触屏点按切换）。 */
(() => {
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

  function markActiveNav() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    // 直达项（社区 / 产品）
    document.querySelectorAll(".community-nav > a[data-nav]").forEach((a) => {
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
      });
    }
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
      if (data.loggedIn) user = { username: data.username, role: data.role || "user" };
    } catch {
      user = null;
    }

    function closeMenu() {
      if (panel) panel.hidden = true;
      if (btn) btn.classList.remove("open");
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
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!panel) return;
        panel.hidden = !panel.hidden;
        btn.classList.toggle("open", !panel.hidden);
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
    markActiveNav();
    bindDropdowns();
    renderAccount();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
