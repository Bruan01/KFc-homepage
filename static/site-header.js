(() => {
  const host = document.querySelector("[data-site-header]");
  if (!host) return;

  const products = {
    personality: { name: "心映", description: "动漫人格探索", href: "/personality" },
    imaging: { name: "显影", description: "AI 图像生成工坊", href: "/imaging" },
  };
  const product = products[host.dataset.product] || products.personality;
  const showCredit = host.dataset.showCredit === "true";
  const showTheme = host.dataset.themeSwitch === "true";

  const icon = (path, className = "i") => `<svg class="${className}" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const chevron = icon('<path d="M6 9.5l6 6 6-6"/>', "i chev").replace('width="15" height="15"', 'width="10" height="10"').replace('stroke-width="1.7"', 'stroke-width="2.4"');
  const dropdownLink = (href, title, description, path, nav = "") => `<a href="${href}"${nav ? ` data-nav="${nav}"` : ""}><span class="dd-icon">${icon(path)}</span><span class="dd-text"><strong>${title}</strong><small>${description}</small></span></a>`;
  const group = (label, links) => `<div class="nav-group"><button type="button" class="nav-group-btn" aria-haspopup="true">${label}${chevron}</button><div class="nav-dropdown">${links}</div></div>`;

  const discovery = [
    dropdownLink("/guide", "新手指南", "第一次来，从这里开始", '<path d="M5 4.5h14v15H5zM8 8h8M8 12h5M8 16h8"/>'),
    dropdownLink("/rankings", "排行榜", "全网与站内热榜", '<path d="M8 4h8v6a4 4 0 0 1-8 0V4zM8 5H4.8a3.2 3.2 0 0 0 3.4 4.8M16 5h3.2a3.2 3.2 0 0 1-3.4 4.8M12 14v4M8.5 21h7M12 18c-1 0-2 .6-2.4 1.5h4.8C14 18.6 13 18 12 18z"/>'),
    dropdownLink("/stats", "贡献统计", "社区健康度与贡献排行", '<path d="M4 20h16M6.5 20v-7M11.5 20V5M16.5 20v-4.5"/>'),
    dropdownLink("/achievements", "成就勋章", "金银铜成就体系", '<path d="M12 3.3l2.6 5.4 5.9.8-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.5l5.9-.8L12 3.3z"/>'),
  ].join("");
  const learning = [
    dropdownLink("/tutorials", "教程", "手把手教程与开发范式", '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5H6.5A2.5 2.5 0 0 0 4 21V5.5zM4 18.5A2.5 2.5 0 0 1 6.5 16H20M8 7h8"/>'),
    dropdownLink("/glossary", "术语表", "Vibecoding 核心概念", '<path d="M5 7V4.5h14V7M12 4.5V19.5M9 19.5h6"/>'),
  ].join("");
  const benefits = [
    dropdownLink("/store", "kflowstore", "积分兑换与创作者货架", '<path d="M6.3 8h11.4l1 12.5H5.3L6.3 8zM9 10V6.5a3 3 0 0 1 6 0V10"/>'),
    dropdownLink("/points", "K 积分", "赚积分规则与明细", '<path d="M3.5 8A2.5 2.5 0 0 1 6 5.5h12A2.5 2.5 0 0 1 20.5 8v8a2.5 2.5 0 0 1-2.5 2.5H6A2.5 2.5 0 0 1 3.5 16V8zM3.5 10h17M7 15.5h4"/>'),
  ].join("");
  const productLinks = [
    dropdownLink("/personality", "心映", "动漫人格探索", '<path d="M12 20S3 15 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 7-9 12-9 12Z"/>', "personality"),
    dropdownLink("/imaging", "显影", "AI 图像生成工坊", '<path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM3.5 12l1.4-2.8 3.1-.4 1.6-2.7h4.8l1.6 2.7 3.1.4L20.5 12l-1.4 2.8-3.1.4-1.6 2.7H9.6L8 15.2l-3.1-.4z"/>', "imaging"),
    dropdownLink("/products", "产品站", "下载、更新与案例", '<path d="M20.5 8.2 12 3.5 3.5 8.2v7.6L12 20.5l8.5-4.7V8.2zM3.7 8.3 12 13l8.3-4.7M12 13v7.3"/>'),
    dropdownLink("/terminal", "桌面终端", "书桌上的小屏，只看你的数据", '<path d="M3.5 5.5h17v10.5h-17zM9.5 20h5M12 16v4"/>', "terminal"),
    dropdownLink("/service-status", "服务状态", "API 中转站实时状态", '<path d="M4.5 12.5 9.5 17.5 19.5 6.5"/>'),
  ].join("");

  const template = document.createElement("template");
  template.innerHTML = `
    <header class="forum-header site-header site-header--${host.dataset.product === "imaging" ? "imaging" : "personality"}">
      <div class="forum-header-inner site-header-inner">
        <a class="community-brand site-header-brand" href="/" aria-label="KFlow 社区首页">
          <img class="community-mark" src="/brand-k.png" alt="" aria-hidden="true" width="30" height="30">
          <span class="community-brand-copy"><strong>KFlow</strong><small>vibecoding 社区</small></span>
        </a>
        <a class="site-header-product" href="${product.href}" aria-label="${product.name}首页"><strong>${product.name}</strong><small>${product.description}</small></a>
        <nav class="community-nav" aria-label="站点导航">
          <a href="/forum" data-nav="forum">论坛</a>
          <a href="/murmurs" data-nav="murmurs">碎碎念</a>
          <a href="/feeds" data-nav="feeds">AI 电讯</a>
          ${group("发现", discovery)}
          ${group("学习", learning)}
          ${group("权益", benefits)}
          ${group("产品", productLinks)}
        </nav>
        <form class="header-search site-header-search" action="/forum" method="get" role="search">
          ${icon('<path d="M21 21l-4.35-4.35m2.35-5.65a8 8 0 1 1-16 0 8 8 0 0 1 16 0z"/>')}
          <input type="search" name="q" placeholder="搜索作品、话题或标签" autocomplete="off">
        </form>
        <div class="header-actions site-header-actions">
          ${showCredit ? '<a class="site-header-credit" href="/points">积分 <strong id="balance">—</strong></a>' : ""}
          ${showTheme ? `<button type="button" class="site-header-icon-button" data-theme-toggle aria-label="切换主题" title="切换主题">${icon('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>')}</button>` : ""}
          <div class="notif-wrap">
            <button class="notif-bell" id="notifBell" type="button" aria-label="站内通知" aria-expanded="false" aria-controls="notifPanel">
              ${icon('<path d="M18 8.5a6 6 0 1 0-12 0c0 6.5-2.5 7.5-2.5 7.5h17S18 15 18 8.5zM10 19.5a2.2 2.2 0 0 0 4 0"/>')}
              <span class="notif-badge" id="notifBadge" hidden></span>
            </button>
            <div class="notif-panel" id="notifPanel" hidden>
              <div class="notif-panel-head"><strong>通知</strong><button type="button" id="notifMarkAll">全部已读</button></div>
              <div class="notif-list" id="notifList"></div>
            </div>
          </div>
          <a class="login-link" id="siteLoginLink" href="/login">登录</a>
          <div class="user-menu-wrap" id="userMenuWrap" style="display:none">
            <button class="user-menu-btn" id="userMenuBtn" type="button" aria-label="我的账户" aria-haspopup="menu" aria-expanded="false">
              <span class="user-menu-avatar" id="userMenuAvatar">?</span><span class="user-menu-name" id="userMenuName"></span>${chevron}
            </button>
            <div class="user-menu-panel" id="userMenuPanel" role="menu" hidden>
              <a href="/account" id="menuAccount" role="menuitem">个人中心</a>
              <a href="/admin" id="menuAdmin" role="menuitem" style="display:none">后台管理</a>
              <div class="user-menu-sep"></div>
              <button type="button" id="menuLogout" role="menuitem">退出登录</button>
            </div>
          </div>
        </div>
      </div>
    </header>`;
  host.replaceWith(template.content.firstElementChild);
})();
