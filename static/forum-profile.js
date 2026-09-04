(() => {
  const root = document.querySelector("#profileRoot");
  const toast = document.querySelector("#forum-toast");
  const username = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
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
    showToast.timer = setTimeout(() => { toast.className = "forum-toast"; }, 3000);
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
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("zh-CN");
  }

  function avatar(profile, className = "profile-avatar") {
    const wrap = el("div", { className });
    const fallback = el("span", { textContent: profile.initials || "?" });
    if (profile.avatar_url) {
      const image = el("img", { alt: `${profile.display_name} 的头像` });
      image.addEventListener("error", () => { image.replaceWith(fallback); });
      image.src = profile.avatar_url;
      wrap.append(image);
    } else wrap.append(fallback);
    return wrap;
  }

  function topicCard(topic) {
    const link = el("a", { className: "profile-topic-card", href: `/forum#topic-${encodeURIComponent(topic.id)}` });
    link.append(
      el("div", { className: "profile-topic-top" },
        el("span", { className: "profile-topic-category", textContent: topic.category }),
        el("time", { textContent: date(topic.created_at) }),
      ),
      el("h3", { textContent: topic.title }),
      el("p", { textContent: topic.excerpt }),
      el("span", { className: "profile-topic-stats", textContent: `${topic.replies} 条回复 · ${topic.views} 次浏览` }),
    );
    return link;
  }

  function replyCard(reply) {
    const link = el("a", { className: "profile-reply-card", href: `/forum#topic-${encodeURIComponent(reply.topic_id)}` });
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

    const hero = el("section", { className: "profile-hero" },
      avatar(profile),
      el("div", { className: "profile-identity" },
        el("span", { className: "profile-kicker", textContent: "COMMUNITY MEMBER" }),
        el("h1", { textContent: profile.display_name }),
        el("p", { className: "profile-username", textContent: `@${profile.username}` }),
        el("p", { className: "profile-bio", textContent: profile.bio || "这个人还没有写个人简介。" }),
      ),
      editable ? el("button", { className: "profile-edit-button", type: "button", textContent: "编辑资料", onclick: () => showEditor(profile) }) : null,
    );
    const stats = el("div", { className: "profile-stats" },
      el("div", {}, el("strong", { textContent: profile.topic_count }), el("span", { textContent: "发布话题" })),
      el("div", {}, el("strong", { textContent: profile.reply_count }), el("span", { textContent: "发表回复" })),
      el("div", {}, el("strong", { textContent: date(profile.created_at) }), el("span", { textContent: "加入时间" })),
    );
    const topics = el("section", { className: "profile-section" }, el("div", { className: "profile-section-heading" }, el("h2", { textContent: "发布的话题" }), el("span", { textContent: `${profile.topics.length} 条` })));
    const topicList = el("div", { className: "profile-topic-list" });
    if (profile.topics.length) topicList.append(...profile.topics.map(topicCard));
    else topicList.append(el("p", { className: "profile-empty", textContent: "还没有发布过话题。" }));
    topics.append(topicList);

    const replies = el("section", { className: "profile-section" }, el("div", { className: "profile-section-heading" }, el("h2", { textContent: "最近回复" }), el("span", { textContent: `${profile.replies.length} 条` })));
    const replyList = el("div", { className: "profile-reply-list" });
    if (profile.replies.length) replyList.append(...profile.replies.map(replyCard));
    else replyList.append(el("p", { className: "profile-empty", textContent: "还没有发表过回复。" }));
    replies.append(replyList);

    root.append(hero, stats, topics, replies);
  }

  function showEditor(profile) {
    const form = el("form", { className: "profile-editor" });
    const display = el("input", { name: "display_name", maxlength: "100", placeholder: "昵称（可选）" });
    display.value = profile.display_name === profile.username ? "" : profile.display_name;
    const avatarInput = el("input", { name: "avatar_url", maxlength: "500", placeholder: "头像 HTTPS 地址或本站路径（可选）" });
    avatarInput.value = profile.avatar_url;
    const bio = el("textarea", { name: "bio", maxlength: "1000", rows: "4", placeholder: "介绍一下自己（可选）" });
    bio.value = profile.bio;
    form.append(
      el("h2", { textContent: "编辑资料" }),
      el("label", {}, "昵称", display),
      el("label", {}, "头像地址", avatarInput),
      el("label", {}, "个人简介", bio),
      el("div", { className: "profile-editor-actions" },
        el("button", { type: "button", className: "btn-secondary", textContent: "取消", onclick: () => render(profile) }),
        el("button", { type: "submit", className: "btn-primary", textContent: "保存资料" }),
      ),
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = form.querySelector("[type=submit]");
      submit.disabled = true;
      try {
        const response = await api("/api/forum/users/me/profile/update", {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({ display_name: display.value.trim(), avatar_url: avatarInput.value.trim(), bio: bio.value.trim() }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "保存失败");
        render(data.profile);
        showToast("资料已更新", "success");
      } catch (error) { showToast(error.message || "保存失败", "error"); submit.disabled = false; }
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
      render(profileData.profile);
    } catch (error) { root.replaceChildren(el("div", { className: "profile-error" }, el("h1", { textContent: "找不到这个用户" }), el("p", { textContent: error.message || "请返回社区重试。" }), el("a", { href: "/forum", textContent: "返回社区" }))); }
  }
  init();
})();
