(() => {
  const root = document.querySelector("#profileRoot");
  const toast = document.querySelector("#forum-toast");
  const username = decodeURIComponent(
    location.pathname.split("/").filter(Boolean).pop() || "",
  );
  let currentUser = null;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else if (key === "value") node.value = value;
      else if (key === "onclick") node.addEventListener("click", value);
      else node.setAttribute(key, value);
    }
    node.append(...children.filter(Boolean));
    return node;
  }

  function showToast(message, type = "info") {
    if (!toast) return;
    toast.textContent = message;
    toast.className = `forum-toast show ${type}`;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => {
      toast.className = "forum-toast";
    }, 3000);
  }

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  async function api(url, options = {}) {
    return fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
  }

  function date(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
      ? value
      : parsed.toLocaleDateString("zh-CN");
  }

  function avatar(profile, className = "profile-avatar") {
    const wrap = el("div", { className });
    const fallback = el("span", { textContent: profile.initials || "?" });
    if (profile.avatar_url) {
      const image = el("img", { alt: `${profile.display_name} 的头像` });
      image.addEventListener("error", () => {
        image.replaceWith(fallback);
      });
      image.src = profile.avatar_url;
      wrap.append(image);
    } else wrap.append(fallback);
    return wrap;
  }

  function topicCard(topic) {
    const link = el("a", {
      className: "profile-topic-card",
      href: `/forum#topic-${encodeURIComponent(topic.id)}`,
    });
    link.append(
      el(
        "div",
        { className: "profile-topic-top" },
        el("span", {
          className: "profile-topic-category",
          textContent: topic.category,
        }),
        el("time", { textContent: date(topic.created_at) }),
      ),
      el("h3", { textContent: topic.title }),
      el("p", { textContent: topic.excerpt }),
      el("span", {
        className: "profile-topic-stats",
        textContent: `${topic.replies} 条回复 · ${topic.views} 次浏览`,
      }),
    );
    return link;
  }

  function replyCard(reply) {
    const link = el("a", {
      className: "profile-reply-card",
      href: `/forum#topic-${encodeURIComponent(reply.topic_id)}`,
    });
    link.append(
      el("strong", { textContent: reply.topic_title }),
      el("p", { textContent: reply.content }),
      el("time", { textContent: date(reply.created_at) }),
    );
    return link;
  }

  function render(profile) {
    const editable = currentUser && currentUser.username === profile.username;
    root.replaceChildren();

    const heroChildren = [];
    if (profile.background_url) {
      const backdrop = el("div", {
        className: "profile-hero-backdrop",
        "aria-hidden": "true",
      });
      const image = el("img", { alt: "" });
      image.addEventListener("error", () => backdrop.remove());
      image.src = profile.background_url;
      backdrop.append(image);
      heroChildren.push(backdrop);
    }
    heroChildren.push(el("div", { className: "profile-hero-shade", "aria-hidden": "true" }));
    heroChildren.push(avatar(profile));
    heroChildren.push(
      el(
        "div",
        { className: "profile-identity" },
        el("span", {
          className: "profile-kicker",
          textContent: "COMMUNITY MEMBER",
        }),
        el("h1", { textContent: profile.display_name }),
        el("p", {
          className: "profile-username",
          textContent: `@${profile.username}`,
        }),
        el("p", {
          className: "profile-bio",
          textContent: profile.bio || "这个人还没有写个人简介。",
        }),
      ),
    );
    if (editable) {
      heroChildren.push(el("button", {
        className: "profile-edit-button",
        type: "button",
        textContent: "编辑资料",
        onclick: () => showEditor(profile),
      }));
    }

    const hero = el(
      "section",
      { className: "profile-hero" },
      ...heroChildren,
    );
    const points = profile.points || {};
    const stats = el(
      "div",
      { className: "profile-stats" },
      el(
        "div",
        {},
        el("strong", { textContent: profile.topic_count }),
        el("span", { textContent: "发布话题" }),
      ),
      el(
        "div",
        {},
        el("strong", { textContent: profile.reply_count }),
        el("span", { textContent: "发表回复" }),
      ),
      el(
        "div",
        {},
        el("strong", { textContent: points.balance ?? "—" }),
        el("span", { textContent: "K 积分" }),
      ),
      el(
        "div",
        {},
        el("strong", { textContent: `LV${points.reputationLevel ?? 0}` }),
        el("span", { textContent: "信誉等级" }),
      ),
    );

    // ── tabs ──
    const tabs = editable
      ? [
          { key: "works", label: "作品与互动" },
          { key: "points", label: "积分与声望" },
          { key: "redemptions", label: "兑换记录" },
        ]
      : [{ key: "works", label: "作品与互动" }];
    const tabBar = el("div", { className: "profile-tabs" });
    const panel = el("div", { className: "profile-tab-panel" });

    const selectTab = async (key) => {
      tabBar.querySelectorAll("button").forEach((btn) =>
        btn.classList.toggle("active", btn.dataset.tab === key),
      );
      if (key === "works") renderWorksTab(panel, profile);
      else if (key === "points") await renderPointsTab(panel, profile, editable);
      else if (key === "redemptions") await renderRedemptionsTab(panel);
    };
    for (const tab of tabs) {
      tabBar.append(
        el("button", {
          className: "profile-tab",
          type: "button",
          "data-tab": tab.key,
          textContent: tab.label,
          onclick: () => selectTab(tab.key),
        }),
      );
    }
    root.append(hero, stats);
    if (profile.badges && profile.badges.length) {
      const wall = el("div", { className: "profile-badges" },
        el("span", { className: "profile-badges-label", textContent: "勋章" }),
        ...profile.badges.map((b) =>
          el("span", { className: `badge-mini tier-${b.tier}`, textContent: b.name, title: `获得于 ${date(b.grantedAt)}` }),
        ),
        el("a", { className: "profile-badges-more", href: "/achievements", textContent: "全部 →" }),
      );
      root.append(wall);
    }
    root.append(tabBar, panel);
    selectTab("works");
  }

  function renderWorksTab(panel, profile) {
    panel.replaceChildren();
    const topics = el(
      "section",
      { className: "profile-section" },
      el(
        "div",
        { className: "profile-section-heading" },
        el("h2", { textContent: "发布的话题" }),
        el("span", { textContent: `${profile.topics.length} 条` }),
      ),
    );
    const topicList = el("div", { className: "profile-topic-list" });
    if (profile.topics.length)
      topicList.append(...profile.topics.map(topicCard));
    else
      topicList.append(
        el("p", {
          className: "profile-empty",
          textContent: "还没有发布过话题。",
        }),
      );
    topics.append(topicList);

    const replies = el(
      "section",
      { className: "profile-section" },
      el(
        "div",
        { className: "profile-section-heading" },
        el("h2", { textContent: "最近回复" }),
        el("span", { textContent: `${profile.replies.length} 条` }),
      ),
    );
    const replyList = el("div", { className: "profile-reply-list" });
    if (profile.replies.length)
      replyList.append(...profile.replies.map(replyCard));
    else
      replyList.append(
        el("p", {
          className: "profile-empty",
          textContent: "还没有发表过回复。",
        }),
      );
    replies.append(replyList);

    panel.append(topics, replies);
  }

  async function renderPointsTab(panel, profile, isSelf) {
    panel.replaceChildren();
    const points = profile.points || {};
    const cards = el(
      "div",
      { className: "profile-points-grid" },
      el("article", { className: "profile-points-card" },
        el("small", { textContent: "SPENDABLE" }),
        el("h3", { textContent: "K 积分余额" }),
        el("strong", { className: "profile-points-number", textContent: points.balance ?? "—" })),
      el("article", { className: "profile-points-card" },
        el("small", { textContent: "LIFETIME" }),
        el("h3", { textContent: "累计贡献值" }),
        el("strong", { className: "profile-points-number", textContent: points.contributionScore ?? "—" })),
      el("article", { className: "profile-points-card" },
        el("small", { textContent: "TRUST" }),
        el("h3", { textContent: "信誉等级" }),
        el("strong", { className: "profile-points-number", textContent: `LV${points.reputationLevel ?? 0}` })),
    );
    panel.append(cards);

    if (!isSelf) {
      panel.append(
        el("p", {
          className: "profile-empty",
          textContent: "积分流水仅本人可见。",
        }),
      );
      return;
    }
    const section = el(
      "section",
      { className: "profile-section" },
      el(
        "div",
        { className: "profile-section-heading" },
        el("h2", { textContent: "最近积分流水" }),
      ),
    );
    const list = el("div", { className: "profile-ledger-list" });
    list.append(el("p", { className: "profile-empty", textContent: "加载中…" }));
    section.append(list);
    panel.append(section);
    try {
      const response = await api("/api/points/ledger?pageSize=20");
      const data = await response.json();
      const rows = data.items || [];
      list.replaceChildren();
      if (!rows.length) {
        list.append(el("p", { className: "profile-empty", textContent: "暂无流水记录。" }));
        return;
      }
      for (const row of rows) {
        const positive = Number(row.delta) >= 0;
        list.append(
          el(
            "div",
            { className: "profile-ledger-row" },
            el("div", { className: "profile-ledger-main" },
              el("strong", { textContent: row.description || row.eventType }),
              el("span", { textContent: `${row.createdAt?.slice(0, 16).replace("T", " ") || ""} · ${row.eventType}` }),
            ),
            el("span", {
              className: `profile-ledger-delta ${positive ? "plus" : "minus"}`,
              textContent: `${positive ? "+" : ""}${row.delta} K`,
            }),
          ),
        );
      }
    } catch {
      list.replaceChildren(el("p", { className: "profile-empty", textContent: "流水加载失败。" }));
    }
  }

  async function renderRedemptionsTab(panel) {
    panel.replaceChildren();
    const section = el(
      "section",
      { className: "profile-section" },
      el(
        "div",
        { className: "profile-section-heading" },
        el("h2", { textContent: "kflowstore 兑换记录" }),
      ),
    );
    const list = el("div", {});
    list.append(el("p", { className: "profile-empty", textContent: "加载中…" }));
    section.append(list);
    panel.append(section);
    try {
      const [official, purchases] = await Promise.all([
        api("/api/store/redemptions").then((r) => (r.ok ? r.json() : { items: [] })),
        api("/api/store/purchases").then((r) => (r.ok ? r.json() : { items: [] })),
      ]);
      list.replaceChildren();
      const officialItems = official.items || [];
      const purchaseItems = purchases.items || [];
      if (!officialItems.length && !purchaseItems.length) {
        list.append(
          el("p", {
            className: "profile-empty",
            textContent: "暂无兑换记录。去 kflowstore 逛逛吧！",
          }),
        );
        return;
      }
      if (officialItems.length) {
        list.append(el("h3", { className: "profile-section-heading", textContent: "官方货架（K 士多）" }));
        for (const item of officialItems) {
          list.append(
            el("div", { className: "profile-ledger-row" },
              el("div", { className: "profile-ledger-main" },
                el("strong", { textContent: item.productName }),
                el("span", { textContent: `${item.pointsCost} K · ${item.createdAt?.slice(0, 16).replace("T", " ") || ""}` }),
              ),
            ),
          );
        }
      }
      if (purchaseItems.length) {
        list.append(el("h3", { className: "profile-section-heading", textContent: "创作者货架" }));
        for (const item of purchaseItems) {
          list.append(
            el("div", { className: "profile-ledger-row" },
              el("div", { className: "profile-ledger-main" },
                el("strong", { textContent: item.title }),
                el("span", { textContent: `${item.pointsPaid} K · ${item.createdAt?.slice(0, 16).replace("T", " ") || ""}` }),
              ),
            ),
          );
        }
      }
    } catch {
      list.replaceChildren(el("p", { className: "profile-empty", textContent: "兑换记录加载失败。" }));
    }
  }

  function showEditor(profile) {
    const form = el("form", { className: "profile-editor" });
    const display = el("input", {
      name: "display_name",
      maxlength: "100",
      placeholder: "昵称（可选）",
    });
    display.value =
      profile.display_name === profile.username ? "" : profile.display_name;
    const avatarInput = el("input", {
      name: "avatar_url",
      maxlength: "500",
      placeholder: "头像 HTTPS 地址或本站路径（可选）",
    });
    avatarInput.value = profile.avatar_url;
    const backgroundInput = el("input", {
      name: "background_url",
      maxlength: "500",
      placeholder: "背景墙 HTTPS 地址或本站路径（可选）",
    });
    backgroundInput.value = profile.background_url || "";
    const bio = el("textarea", {
      name: "bio",
      maxlength: "1000",
      rows: "4",
      placeholder: "介绍一下自己（可选）",
    });
    bio.value = profile.bio;
    form.append(
      el("h2", { textContent: "编辑资料" }),
      el("label", {}, "昵称", display),
      el("label", {}, "头像地址", avatarInput),
      el("label", {}, "背景墙地址", backgroundInput),
      el("label", {}, "个人简介", bio),
      el(
        "div",
        { className: "profile-editor-actions" },
        el("button", {
          type: "button",
          className: "btn-secondary",
          textContent: "取消",
          onclick: () => render(profile),
        }),
        el("button", {
          type: "submit",
          className: "btn-primary",
          textContent: "保存资料",
        }),
      ),
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = form.querySelector("[type=submit]");
      submit.disabled = true;
      try {
        const response = await api("/api/forum/users/me/profile/update", {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf(),
          },
          body: JSON.stringify({
            display_name: display.value.trim(),
            avatar_url: avatarInput.value.trim(),
            background_url: backgroundInput.value.trim(),
            bio: bio.value.trim(),
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "保存失败");
        render(data.profile);
        showToast("资料已更新", "success");
      } catch (error) {
        showToast(error.message || "保存失败", "error");
        submit.disabled = false;
      }
    });
    root.replaceChildren(form);
  }

  async function init() {
    if (!username) return;
    try {
      const [profileResponse, meResponse] = await Promise.all([
        api(`/api/forum/users/${encodeURIComponent(username)}`),
        api("/api/account/me"),
      ]);
      if (!profileResponse.ok) throw new Error("用户不存在");
      const profileData = await profileResponse.json();
      const meData = await meResponse.json();
      currentUser = meData.loggedIn ? { username: meData.username } : null;
      // 个人主页与个人中心已合并：访问自己的主页直接进入个人中心
      if (currentUser && profileData.profile.username === currentUser.username) {
        location.replace("/account");
        return;
      }
      render(profileData.profile);
    } catch (error) {
      root.replaceChildren(
        el(
          "div",
          { className: "profile-error" },
          el("h1", { textContent: "找不到这个用户" }),
          el("p", { textContent: error.message || "请返回社区重试。" }),
          el("a", { href: "/forum", textContent: "返回社区" }),
        ),
      );
    }
  }
  init();
})();
