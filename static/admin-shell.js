(() => {
  // This script is also referenced by shared public/admin HTML pages.
  if (!location.pathname.startsWith('/admin/')) return;
  for (const href of ['/styles.css', '/admin-shell.css']) {
    if (document.querySelector(`link[rel="stylesheet"][href="${href}"]`)) continue;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = href;
    document.head.append(stylesheet);
  }
  const script = document.currentScript;
  const title = script?.dataset.title || "管理工作台";
  const active = script?.dataset.active || "";
  const main = document.querySelector("body > main");
  if (!main) return;

  const links = [
    ["overview", "/admin", "总览", "OV"],
    ["products", "/admin/products", "产品管理", "PM"],
    ["reviews", "/admin/reviews", "审批中心", "RV"],
    ["points", "/admin/points", "积分管理", "KP"],
    ["store", "/admin/store", "K 士多", "KS"],
    ["listings", "/admin/listings", "创作者货架", "CL"],
    ["imaging", "/admin/imaging", "显影配置", "IM"],
    ["personality", "/admin/personality", "心映", "XY"],
    ["forum", "/admin/forum", "论坛治理", "FM"],
    ["murmurs", "/admin/murmurs", "碎碎念治理", "SS"],
    ["users", "/admin/users", "用户管理", "US"],
  ];

  const topbar = document.createElement("header");
  topbar.className = "topbar admin-topbar";
  const topbarInner = document.createElement("div");
  topbarInner.className = "container topbar-inner";
  const brand = document.createElement("a");
  brand.className = "brand admin-brand";
  brand.href = "/admin";
  const logo = document.createElement("img");
  logo.className = "brand-badge";
  logo.src = "/brand-k.png";
  logo.alt = "";
  const brandCopy = document.createElement("span");
  brandCopy.textContent = "KFlow";
  const adminLabel = document.createElement("span");
  adminLabel.className = "brand-sub";
  adminLabel.textContent = "Admin Console";
  const userInfo = document.createElement("span");
  userInfo.className = "brand-sub";
  userInfo.style.display = "block";
  userInfo.style.marginTop = "2px";
  userInfo.textContent = "正在读取管理员信息…";
  brandCopy.append(adminLabel, userInfo);
  brand.append(logo, brandCopy);
  const topbarMain = document.createElement("div");
  topbarMain.className = "admin-topbar-main";
  const context = document.createElement("div");
  context.className = "admin-topbar-context";
  const breadcrumb = document.createElement("span");
  breadcrumb.className = "admin-breadcrumb";
  breadcrumb.textContent = `控制面 / ${title}`;
  const environment = document.createElement("span");
  environment.className = "admin-environment";
  environment.textContent = "PRODUCTION";
  context.append(breadcrumb, environment);
  const nav = document.createElement("nav");
  nav.className = "nav";
  const preview = document.createElement("a");
  preview.href = "/";
  preview.target = "_blank";
  preview.rel = "noreferrer";
  preview.textContent = "预览官网";
  nav.append(preview);
  topbarMain.append(context, nav);
  topbarInner.append(brand, topbarMain);
  topbar.append(topbarInner);

  const layout = document.createElement("div");
  layout.className = "container admin-shell";
  const sidebar = document.createElement("aside");
  sidebar.className = "admin-sidebar";
  sidebar.setAttribute("aria-label", "后台管理导航");
  const sidebarHeader = document.createElement("div");
  sidebarHeader.className = "admin-sidebar-header";
  const topline = document.createElement("div");
  topline.className = "admin-sidebar-topline";
  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "后台管理";
  const toggle = document.createElement("button");
  toggle.className = "admin-sidebar-toggle";
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "true");
  toggle.innerHTML = '<span class="admin-toggle-icon" aria-hidden="true">‹</span><span class="admin-toggle-label">收起导航</span>';
  toggle.addEventListener("click", () => {
    const collapsed = layout.classList.toggle("is-collapsed");
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.querySelector(".admin-toggle-label").textContent = collapsed ? "展开导航" : "收起导航";
  });
  topline.append(eyebrow, toggle);
  const heading = document.createElement("h2");
  heading.textContent = "管理工作台";
  const intro = document.createElement("p");
  intro.textContent = "按业务域拆分工作区，当前页面只加载对应的数据与操作。";
  sidebarHeader.append(topline, heading, intro);
  sidebar.append(sidebarHeader);

  const pageGroup = document.createElement("div");
  pageGroup.className = "admin-side-group";
  const pageTitle = document.createElement("span");
  pageTitle.className = "admin-side-title";
  pageTitle.textContent = "页面导航";
  const bigscreen = document.createElement("a");
  bigscreen.className = "admin-side-link";
  bigscreen.dataset.short = "DB";
  bigscreen.href = "/admin/bigscreen";
  bigscreen.textContent = "数据大屏";
  pageGroup.append(pageTitle, bigscreen);
  sidebar.append(pageGroup);

  const business = document.createElement("div");
  business.className = "admin-side-group";
  const businessTitle = document.createElement("span");
  businessTitle.className = "admin-side-title";
  businessTitle.textContent = "业务导航";
  business.append(businessTitle);
  for (const [key, href, label, short] of links) {
    const link = document.createElement("a");
    link.className = "admin-side-link";
    link.href = href;
    link.dataset.short = short;
    link.dataset.adminKey = key;
    link.textContent = label;
    if (key === active) link.classList.add("is-active");
    business.append(link);
  }
  sidebar.append(business);

  const system = document.createElement("div");
  system.className = "admin-side-group";
  const systemTitle = document.createElement("span");
  systemTitle.className = "admin-side-title";
  systemTitle.textContent = "系统";
  const settings = document.createElement("a");
  settings.className = "admin-side-link";
  settings.dataset.short = "ST";
  settings.dataset.adminKey = "settings";
  settings.href = "/admin/settings";
  settings.textContent = "系统设置";
  system.append(systemTitle, settings);
  sidebar.append(system);
  const footer = document.createElement("div");
  footer.className = "admin-sidebar-footer";
  footer.innerHTML = '<span class="admin-online-dot"></span><div><strong>控制面在线</strong><span>Django service · SQLite</span></div>';
  sidebar.append(footer);

  const content = document.createElement("div");
  content.className = "admin-content admin-migrated-content";
  content.append(main);
  layout.append(sidebar, content);
  document.body.classList.add("admin-page", "admin-migrated-page");
  document.querySelector("body > header")?.remove();
  document.body.prepend(topbar, layout);
  document.title = `${title} · KFlow Admin Console`;

  function applyPermissions(me) {
    userInfo.textContent = `当前用户：${me.username || "--"} · ${me.isSuper ? "主管理员" : `lv${Number(me.adminLevel || 1)}`}`;
    const level = Number(me.adminLevel || 1);
    const rules = {
      points: me.isSuper,
      store: me.isSuper,
      listings: me.isSuper,
      imaging: me.isSuper,
      forum: me.isSuper || level >= 2,
      murmurs: me.isSuper || level >= 2,
      personality: me.isSuper || level >= 3,
      operations: me.isSuper,
      settings: me.isSuper || level >= 3,
    };
    document.querySelectorAll("[data-admin-key]").forEach((link) => {
      const allowed = rules[link.dataset.adminKey];
      if (allowed !== undefined) link.hidden = !allowed;
    });
  }

  fetch("/api/admin/me", { credentials: "same-origin" })
    .then((response) => response.json())
    .then((me) => { if (me.loggedIn) applyPermissions(me); })
    .catch(() => { userInfo.textContent = "管理员会话已验证"; });
})();
