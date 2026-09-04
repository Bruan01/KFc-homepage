(() => {
  const categories = [
    { name: "全部话题", icon: "全", color: "#d9232e" },
    { name: "产品动态", icon: "新", color: "#d9232e" },
    { name: "技术交流", icon: "码", color: "#2563a8" },
    { name: "使用帮助", icon: "?", color: "#a66713" },
    { name: "资源分享", icon: "享", color: "#16805b" },
    { name: "项目展示", icon: "作", color: "#7254b8" },
    { name: "闲聊广场", icon: "聊", color: "#657080" },
  ];

  const topics = [
    {
      id: 1,
      title: "KFlow Community 正式开放：一起建立更好的产品交流空间",
      excerpt: "从产品动态到技术实践，我们希望每一次公开讨论都能沉淀为下一位创造者的起点。",
      author: "KFlow 团队",
      initials: "KF",
      avatar: "linear-gradient(145deg, #d9232e, #8c121b)",
      category: "产品动态",
      tags: ["公告", "社区"],
      replies: 48,
      views: 1286,
      heat: 99,
      active: "12 分钟前",
      order: 100,
      pinned: true,
      featured: true,
    },
    {
      id: 2,
      title: "显影功能的图像压缩与缓存策略，现在是怎样工作的？",
      excerpt: "整理一份从生成、压缩、缓存到下载的完整链路，也欢迎大家分享真实使用中的速度体验。",
      author: "河川",
      initials: "HC",
      avatar: "linear-gradient(145deg, #24679b, #173650)",
      category: "技术交流",
      tags: ["显影", "缓存"],
      replies: 32,
      views: 864,
      heat: 92,
      active: "25 分钟前",
      order: 96,
      featured: true,
    },
    {
      id: 3,
      title: "新人指南：从注册账号到完成第一次产品下载",
      excerpt: "一份面向新用户的快速指南，包含积分、下载权限和常见问题的处理方式。",
      author: "木棉",
      initials: "MM",
      avatar: "linear-gradient(145deg, #dc8a35, #8f4e1c)",
      category: "使用帮助",
      tags: ["入门", "下载"],
      replies: 19,
      views: 742,
      heat: 80,
      active: "48 分钟前",
      order: 92,
      pinned: true,
      featured: false,
    },
    {
      id: 4,
      title: "分享一个适合 KFlow 发布流程的版本号规范",
      excerpt: "结合语义化版本与内部构建编号，避免测试包、候选包和正式版本之间出现歧义。",
      author: "Lambda",
      initials: "Lλ",
      avatar: "linear-gradient(145deg, #40745d, #1c4936)",
      category: "资源分享",
      tags: ["版本管理", "规范"],
      replies: 27,
      views: 593,
      heat: 84,
      active: "1 小时前",
      order: 88,
      featured: true,
    },
    {
      id: 5,
      title: "项目展示：CodexHub 多服务器管理控制台",
      excerpt: "用于 Codex App SSH 工作流的多服务器控制台，分享目前的架构、交互和下一阶段计划。",
      author: "Jurio",
      initials: "JR",
      avatar: "linear-gradient(145deg, #8061be, #46336d)",
      category: "项目展示",
      tags: ["开源", "CodexHub"],
      replies: 41,
      views: 1034,
      heat: 96,
      active: "2 小时前",
      order: 84,
      featured: true,
    },
    {
      id: 6,
      title: "如何为一个产品配置多个系统和架构的安装包？",
      excerpt: "Windows、macOS 与 Linux 包同时发布时，后台排序和默认包选择有哪些推荐做法？",
      author: "未央",
      initials: "WY",
      avatar: "linear-gradient(145deg, #b05c71, #713242)",
      category: "使用帮助",
      tags: ["产品包", "后台"],
      replies: 13,
      views: 356,
      heat: 64,
      active: "3 小时前",
      order: 80,
      featured: false,
    },
    {
      id: 7,
      title: "Django + SQLite WAL 模式在小型交付平台中的实践笔记",
      excerpt: "讨论备份一致性、在线迁移和并发写入边界，以及为什么小规模业务仍可以认真使用 SQLite。",
      author: "北屿",
      initials: "BY",
      avatar: "linear-gradient(145deg, #334f73, #17283e)",
      category: "技术交流",
      tags: ["Django", "SQLite"],
      replies: 36,
      views: 917,
      heat: 94,
      active: "5 小时前",
      order: 76,
      featured: true,
    },
    {
      id: 8,
      title: "本周产品更新汇总：下载体验与移动端页面调整",
      excerpt: "集中记录本周上线的细节优化，并收集下一轮迭代最值得优先处理的问题。",
      author: "KFlow 产品组",
      initials: "KP",
      avatar: "linear-gradient(145deg, #df4149, #9d1721)",
      category: "产品动态",
      tags: ["周报", "更新"],
      replies: 22,
      views: 511,
      heat: 76,
      active: "昨天",
      order: 72,
      featured: false,
    },
    {
      id: 9,
      title: "你们会怎样保存一个项目从想法到上线的过程？",
      excerpt: "除了 Git 提交，还有哪些轻量方式可以保留设计决策、失败尝试和迭代依据？",
      author: "一页",
      initials: "YY",
      avatar: "linear-gradient(145deg, #66727f, #343d48)",
      category: "闲聊广场",
      tags: ["工作流", "记录"],
      replies: 58,
      views: 1205,
      heat: 97,
      active: "昨天",
      order: 68,
      featured: false,
    },
    {
      id: 10,
      title: "资源整理：产品发布前值得检查的 24 个细节",
      excerpt: "覆盖版本说明、安装包、权限、回滚、截图和通知，一份可直接复制使用的发布检查单。",
      author: "柚子",
      initials: "YZ",
      avatar: "linear-gradient(145deg, #399272, #1a5942)",
      category: "资源分享",
      tags: ["清单", "发布"],
      replies: 29,
      views: 688,
      heat: 87,
      active: "2 天前",
      order: 64,
      featured: true,
    },
    {
      id: 11,
      title: "展示一个为硬件团队制作的内部交付看板",
      excerpt: "如何让研发、测试和业务同时看到当前版本、审核状态与客户可下载范围。",
      author: "石墨",
      initials: "SM",
      avatar: "linear-gradient(145deg, #8c68bf, #4c3770)",
      category: "项目展示",
      tags: ["看板", "硬件"],
      replies: 17,
      views: 429,
      heat: 70,
      active: "3 天前",
      order: 60,
      featured: false,
    },
    {
      id: 12,
      title: "你最希望 KFlow 下一步增加什么能力？",
      excerpt: "欢迎分享真实工作流中的阻力：通知、协作、下载、审批或其他任何问题。",
      author: "红杉",
      initials: "HS",
      avatar: "linear-gradient(145deg, #aa6262, #663333)",
      category: "闲聊广场",
      tags: ["建议", "共创"],
      replies: 73,
      views: 1490,
      heat: 100,
      active: "4 天前",
      order: 56,
      featured: false,
    },
  ];

  const categoryList = document.getElementById("categoryList");
  const mobileCategories = document.getElementById("mobileCategories");
  const topicList = document.getElementById("topicList");
  const searchInput = document.getElementById("forumSearch");
  const viewTabs = document.getElementById("viewTabs");
  const resultSummary = document.getElementById("resultSummary");
  const resetFilters = document.getElementById("resetFilters");
  const topicsHeading = document.getElementById("topicsHeading");
  const trendingList = document.getElementById("trendingList");
  const contributorList = document.getElementById("contributorList");
  const toast = document.getElementById("forumToast");
  const toastMessage = document.getElementById("toastMessage");
  const closeToast = document.getElementById("closeToast");

  if (!categoryList || !mobileCategories || !topicList || !searchInput || !viewTabs) return;

  let selectedCategory = "全部话题";
  let selectedView = "latest";
  let toastTimer;

  const formatNumber = (value) => value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : String(value);
  const categoryColor = (name) => categories.find((category) => category.name === name)?.color || "#657080";
  const categoryCount = (name) => name === "全部话题" ? topics.length : topics.filter((topic) => topic.category === name).length;

  function showToast(action) {
    if (!toast || !toastMessage) return;
    window.clearTimeout(toastTimer);
    toastMessage.textContent = `${action}将在社区后续版本中提供。`;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 3600);
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function categoryButton(category, mobile = false) {
    const button = createElement("button", mobile ? "mobile-category" : "category-button");
    button.type = "button";
    button.dataset.category = category.name;
    button.setAttribute("aria-pressed", String(selectedCategory === category.name));
    if (mobile) {
      button.textContent = `${category.name} · ${categoryCount(category.name)}`;
      return button;
    }
    button.style.setProperty("--category-color", category.color);
    const icon = createElement("span", "category-icon", category.icon);
    icon.setAttribute("aria-hidden", "true");
    button.append(icon, createElement("span", "category-name", category.name), createElement("span", "category-count", categoryCount(category.name)));
    return button;
  }

  function renderCategories() {
    categoryList.replaceChildren(...categories.map((category) => categoryButton(category)));
    mobileCategories.replaceChildren(...categories.map((category) => categoryButton(category, true)));
  }

  function getVisibleTopics() {
    const query = searchInput.value.trim().toLocaleLowerCase("zh-CN");
    let visible = topics.filter((topic) => selectedCategory === "全部话题" || topic.category === selectedCategory);
    if (selectedView === "featured") visible = visible.filter((topic) => topic.featured);
    if (query) {
      visible = visible.filter((topic) => [topic.title, topic.excerpt, topic.author, topic.category, ...topic.tags]
        .join(" ").toLocaleLowerCase("zh-CN").includes(query));
    }
    return visible.sort((a, b) => selectedView === "popular" ? b.heat - a.heat : b.order - a.order);
  }

  function topicCard(topic, index) {
    const card = createElement("article", `topic-card${topic.pinned ? " is-pinned" : ""}`);
    card.tabIndex = 0;
    card.setAttribute("role", "link");
    card.dataset.topicId = topic.id;
    card.style.animationDelay = `${Math.min(index * 35, 245)}ms`;

    const avatar = createElement("div", "topic-avatar", topic.initials);
    avatar.setAttribute("aria-hidden", "true");
    avatar.style.setProperty("--avatar-bg", topic.avatar);

    const main = createElement("div", "topic-main");
    const flags = createElement("div", "topic-flags");
    if (topic.pinned) flags.append(createElement("span", "topic-flag pinned", "置顶"));
    if (topic.featured) flags.append(createElement("span", "topic-flag featured", "精华"));
    const title = createElement("h3", "", topic.title);
    const excerpt = createElement("p", "", topic.excerpt);
    const meta = createElement("div", "topic-meta");
    meta.append(createElement("span", "topic-author", topic.author));
    const category = createElement("span", "topic-category", topic.category);
    category.style.setProperty("--category-color", categoryColor(topic.category));
    meta.append(category, createElement("span", "", topic.active));
    const tags = createElement("span", "topic-tags");
    tags.append(...topic.tags.map((tag) => createElement("span", "topic-tag", tag)));
    meta.append(tags);
    main.append(flags, title, excerpt, meta);

    const stats = createElement("div", "topic-stats");
    stats.setAttribute("aria-label", `${topic.replies} 个回复，${topic.views} 次浏览`);
    [[formatNumber(topic.replies), "回复"], [formatNumber(topic.views), "浏览"]].forEach(([value, label]) => {
      const stat = createElement("span", "topic-stat");
      stat.append(createElement("strong", "", value), createElement("span", "", label));
      stats.append(stat);
    });
    card.append(avatar, main, stats);
    return card;
  }

  function emptyState() {
    const state = createElement("div", "empty-state");
    const mark = createElement("div", "empty-mark", "KF");
    mark.setAttribute("aria-hidden", "true");
    const button = createElement("button", "", "查看全部话题");
    button.type = "button";
    button.dataset.resetEmpty = "";
    state.append(mark, createElement("h3", "", "没有找到匹配的话题"), createElement("p", "", "换一个关键词，或清除当前分类与视图筛选。"), button);
    return state;
  }

  function renderTopics() {
    const visible = getVisibleTopics();
    const query = searchInput.value.trim();
    topicsHeading.textContent = selectedView === "featured" ? "社区精华" : selectedCategory;
    const parts = [`${visible.length} 个话题`];
    if (selectedCategory !== "全部话题") parts.push(selectedCategory);
    if (query) parts.push(`搜索“${query}”`);
    resultSummary.textContent = parts.join(" · ");
    resetFilters.hidden = selectedCategory === "全部话题" && selectedView === "latest" && !query;
    topicList.replaceChildren(...(visible.length ? visible.map(topicCard) : [emptyState()]));
  }

  function renderSideContent() {
    if (trendingList) {
      const items = [...topics].sort((a, b) => b.heat - a.heat).slice(0, 5).map((topic, index) => {
        const item = createElement("li", "trending-item");
        item.tabIndex = 0;
        item.setAttribute("role", "link");
        item.dataset.topicId = topic.id;
        const copy = createElement("span");
        copy.append(createElement("strong", "", topic.title), createElement("small", "", `${topic.replies} 回复 · ${formatNumber(topic.views)} 浏览`));
        item.append(createElement("span", "trending-rank", String(index + 1).padStart(2, "0")), copy);
        return item;
      });
      trendingList.replaceChildren(...items);
    }
    if (contributorList) {
      const contributors = [
        ["Jurio", "JR", "项目创造者", "+186", "linear-gradient(145deg,#8061be,#46336d)"],
        ["北屿", "BY", "技术贡献者", "+142", "linear-gradient(145deg,#334f73,#17283e)"],
        ["Lambda", "Lλ", "资源分享者", "+118", "linear-gradient(145deg,#40745d,#1c4936)"],
        ["木棉", "MM", "热心解答者", "+96", "linear-gradient(145deg,#dc8a35,#8f4e1c)"],
      ];
      const contributorsNodes = contributors.map(([name, initials, role, score, background]) => {
        const contributor = createElement("div", "contributor");
        const avatar = createElement("span", "contributor-avatar", initials);
        avatar.setAttribute("aria-hidden", "true");
        avatar.style.setProperty("--avatar-bg", background);
        const copy = createElement("div");
        copy.append(createElement("strong", "", name), createElement("small", "", role));
        contributor.append(avatar, copy, createElement("span", "contributor-score", score));
        return contributor;
      });
      contributorList.replaceChildren(...contributorsNodes);
    }
  }

  function chooseCategory(name) {
    selectedCategory = name;
    renderCategories();
    renderTopics();
    document.querySelector(`[data-category="${CSS.escape(name)}"]`)?.scrollIntoView({ block: "nearest", inline: "center" });
  }

  function chooseView(view) {
    selectedView = view;
    viewTabs.querySelectorAll("[data-view]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.view === view));
    });
    renderTopics();
  }

  function resetAll() {
    selectedCategory = "全部话题";
    selectedView = "latest";
    searchInput.value = "";
    renderCategories();
    chooseView("latest");
  }

  document.addEventListener("click", (event) => {
    const category = event.target.closest("[data-category]");
    if (category) chooseCategory(category.dataset.category);

    const view = event.target.closest("[data-view]");
    if (view) chooseView(view.dataset.view);

    const shortcut = event.target.closest("[data-view-shortcut]");
    if (shortcut) {
      chooseView(shortcut.dataset.viewShortcut);
      document.getElementById("topics")?.scrollIntoView({ behavior: "smooth" });
    }

    if (event.target.closest("[data-focus-categories]")) {
      const target = window.matchMedia("(max-width: 840px)").matches ? mobileCategories : categoryList;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    const comingSoon = event.target.closest("[data-coming-soon]");
    if (comingSoon) showToast(comingSoon.dataset.comingSoon);

    const topic = event.target.closest("[data-topic-id]");
    if (topic) showToast("帖子详情与回复");

    if (event.target.closest("[data-reset-empty]") || event.target === resetFilters) resetAll();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== searchInput) {
      event.preventDefault();
      searchInput.focus();
    }
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-topic-id]")) {
      event.preventDefault();
      showToast("帖子详情与回复");
    }
    if (event.key === "Escape" && toast && !toast.hidden) toast.hidden = true;
  });

  searchInput.addEventListener("input", renderTopics);
  closeToast?.addEventListener("click", () => { toast.hidden = true; });
  document.getElementById("forumYear").textContent = new Date().getFullYear();

  renderCategories();
  renderTopics();
  renderSideContent();
})();
