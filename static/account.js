/* 个人中心（/account）逻辑：资料设置、头像上传、积分、成就。 */
(() => {
  let currentUser = null;
  let profile = null;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child == null) continue;
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function showToast(msg, type = "info") {
    const toast = document.querySelector("#forum-toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `forum-toast show ${type}`;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
  }

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  async function api(url, opts = {}) {
    return fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...opts.headers },
      ...opts,
    });
  }

  function renderAvatar(url, fallbackInitial) {
    const avatar = document.querySelector("#accountAvatar");
    avatar.replaceChildren();
    if (url) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = "头像";
      img.addEventListener("error", () => {
        avatar.replaceChildren(fallbackInitial || "?");
      });
      avatar.append(img);
    } else {
      avatar.textContent = fallbackInitial || "?";
    }
  }

  function renderCover(url) {
    const hero = document.querySelector(".account-hero");
    const backdrop = document.querySelector("#accountHeroBackdrop");
    const image = document.querySelector("#accountHeroBackdropImage");
    if (!hero || !backdrop || !image) return;
    image.onload = () => {
      backdrop.hidden = false;
      hero.classList.add("account-hero-has-cover");
    };
    image.onerror = () => {
      backdrop.hidden = true;
      hero.classList.remove("account-hero-has-cover");
    };
    if (url) {
      image.src = url;
    } else {
      image.removeAttribute("src");
      backdrop.hidden = true;
      hero.classList.remove("account-hero-has-cover");
    }
  }

  // ── 资料卡 ──
  function renderHero(profile) {
    const initial = (profile.display_name || "?").slice(0, 1).toUpperCase();
    renderAvatar(profile.avatar_url, initial);
    renderCover(profile.background_url);
    document.querySelector("#accountDisplayName").textContent = profile.display_name || profile.username;
    document.querySelector("#accountUsername").textContent = `@${profile.username}`;
    const emailEl = document.querySelector("#accountEmail");
    emailEl.textContent = profile.email || "";
    emailEl.style.display = profile.email ? "" : "none";
    const level = profile.points?.reputationLevel ?? 0;
    document.querySelector("#accountLevel").textContent = `LV${level}`;
    document.querySelector("#accountBio").textContent = profile.bio || "还没有简介，写一个吧。";
    document.querySelector("#accountProfileLink").href = `/forum/user/${encodeURIComponent(profile.username)}`;

    const quick = document.querySelector("#accountQuickStats");
    quick.replaceChildren();
    const points = profile.points || {};
    const items = [
      { label: "K 积分", value: points.balance ?? "—" },
      { label: "贡献分", value: points.contributionScore ?? "—" },
      { label: "作品帖", value: profile.topic_count ?? 0 },
      { label: "勋章", value: profile.badges ? profile.badges.length : 0 },
    ];
    for (const item of items) {
      quick.append(
        el("div", { className: "account-quick-stat" },
          el("strong", { textContent: String(item.value) }),
          el("span", { textContent: item.label }),
        ),
      );
    }
  }

  // ── 资料设置 ──
  function renderProfileForm(profile) {
    document.querySelector("#inputDisplayName").value =
      profile.display_name === profile.username ? "" : profile.display_name || "";
    document.querySelector("#inputAvatar").value = profile.avatar_url || "";
    document.querySelector("#inputBackground").value = profile.background_url || "";
    document.querySelector("#inputBio").value = profile.bio || "";
  }

  async function uploadImage(file) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/forum/images", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf() },
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "图片上传失败");
    return data.image.url;
  }

  async function uploadCover(file) {
    return uploadImage(file);
  }

  function bindAvatarUpload() {
    const button = document.querySelector("#avatarButton");
    const input = document.querySelector("#avatarFile");
    button.addEventListener("click", () => input.click());
    input.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) return showToast("头像图片不能超过 5MB", "error");
      showToast("正在上传头像…");
      try {
        const url = await uploadImage(file);
        document.querySelector("#inputAvatar").value = url;
        renderAvatar(url, "?");
        // 直接保存，让头像立即生效
        await saveProfile({ silent: true });
        showToast("头像已更新", "success");
      } catch (err) {
        showToast(err.message || "头像上传失败", "error");
      }
    });
  }

  function bindCoverUpload() {
    const button = document.querySelector("#coverButton");
    const input = document.querySelector("#coverFile");
    button.addEventListener("click", () => input.click());
    input.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) return showToast("背景图片不能超过 5MB", "error");
      showToast("正在上传背景墙…");
      try {
        const url = await uploadCover(file);
        document.querySelector("#inputBackground").value = url;
        renderCover(url);
        await saveProfile({ silent: true });
        showToast("背景墙已更新", "success");
      } catch (err) {
        showToast(err.message || "背景墙上传失败", "error");
      }
    });
  }

  function bindCoverReset() {
    const button = document.querySelector("#coverResetButton");
    button.addEventListener("click", async () => {
      if (!document.querySelector("#inputBackground").value.trim()) return;
      button.disabled = true;
      document.querySelector("#inputBackground").value = "";
      renderCover("");
      try {
        await saveProfile({ silent: true });
        showToast("已恢复默认背景", "success");
      } catch (err) {
        showToast(err.message || "恢复默认背景失败", "error");
      } finally {
        button.disabled = false;
      }
    });
  }

  async function saveProfile({ silent = false } = {}) {
    const status = document.querySelector("#profileStatus");
    const body = {
      display_name: document.querySelector("#inputDisplayName").value.trim(),
      avatar_url: document.querySelector("#inputAvatar").value.trim(),
      background_url: document.querySelector("#inputBackground").value.trim(),
      bio: document.querySelector("#inputBio").value.trim(),
    };
    const res = await api("/api/forum/users/me/profile/update", {
      method: "PATCH",
      headers: { "X-CSRFToken": csrf() },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "保存失败");
    profile = data.profile;
    renderHero(profile);
    if (!silent) {
      status.textContent = "已保存";
      setTimeout(() => (status.textContent = ""), 2200);
      showToast("资料已保存", "success");
    }
    return profile;
  }

  function bindProfileForm() {
    document.querySelector("#profileForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const button = e.currentTarget.querySelector("[type=submit]");
      button.disabled = true;
      try {
        await saveProfile();
      } catch (err) {
        showToast(err.message || "保存失败", "error");
      } finally {
        button.disabled = false;
      }
    });
    bindAvatarUpload();
    bindCoverUpload();
    bindCoverReset();
    // 头像地址手输时预览
    document.querySelector("#inputAvatar").addEventListener("change", (e) => {
      const url = e.target.value.trim();
      if (url) renderAvatar(url, "?");
    });
    document.querySelector("#inputBackground").addEventListener("change", (e) => {
      renderCover(e.target.value.trim());
    });
  }

  // ── 积分 ──
  async function renderPoints() {
    const cards = document.querySelector("#pointsCards");
    const ledger = document.querySelector("#pointsLedger");
    try {
      const [pointsRes, levelsRes] = await Promise.all([
        api("/api/points/me"),
        api("/api/levels"),
      ]);
      const points = await pointsRes.json();
      const levelsData = await levelsRes.json();
      cards.replaceChildren();
      const my = levelsData.my;
      const items = [
        { label: "K 积分余额", value: points.balance ?? 0 },
        { label: "累计获得", value: points.totalEarned ?? 0 },
        { label: "累计消费", value: points.totalSpent ?? 0 },
        { label: "贡献分", value: points.contributionScore ?? 0 },
      ];
      for (const item of items) {
        cards.append(
          el("article", { className: "profile-points-card" },
            el("small", { textContent: item.label }),
            el("strong", { className: "profile-points-number", textContent: String(item.value) }),
          ),
        );
      }
      // 等级进度条（复用 levels 页数据）
      if (my && my.progress) {
        const box = el("div", { className: "profile-points-card", style: "grid-column: 1 / -1;" },
          el("small", { textContent: `距离 LV${my.progress.nextLevel} ${my.progress.nextName}` }),
        );
        const bars = el("div", { className: "level-progress", style: "margin-top:10px" });
        for (const part of my.progress.parts) {
          const pct = Math.min(100, Math.round((part.value / Math.max(1, part.threshold)) * 100));
          bars.append(
            el("div", { className: "level-progress-row" },
              el("span", { className: "level-progress-label", textContent: part.key === "contribution" ? "贡献分" : { active_days: "活跃天数", topics: "发帖数", replies: "评论数", likes_received: "获赞数" }[part.key] || part.key }),
              el("div", { className: "level-progress-track" },
                el("div", { className: "level-progress-fill", style: `width:${pct}%` })),
              el("span", { className: "level-progress-num" + (part.done ? " done" : ""),
                textContent: part.done ? "已完成" : `${part.value} / ${part.threshold}` }),
            ),
          );
        }
        box.append(bars);
        cards.append(box);
      }
    } catch {
      cards.replaceChildren(el("p", { className: "profile-empty", textContent: "积分信息加载失败。" }));
    }

    ledger.replaceChildren(el("p", { className: "profile-empty", textContent: "加载中…" }));
    try {
      const res = await api("/api/points/ledger?pageSize=20");
      const data = await res.json();
      ledger.replaceChildren();
      const rows = data.items || [];
      if (!rows.length) {
        ledger.append(el("p", { className: "profile-empty", textContent: "暂无流水。发帖、评论、被点赞都会获得积分。" }));
        return;
      }
      for (const row of rows) {
        const positive = Number(row.delta) >= 0;
        ledger.append(
          el("div", { className: "profile-ledger-row" },
            el("div", { className: "profile-ledger-main" },
              el("strong", { textContent: row.description || row.eventType }),
              el("span", { textContent: `${(row.createdAt || "").slice(0, 16).replace("T", " ")} · ${row.eventType}` }),
            ),
            el("span", {
              className: `profile-ledger-delta ${positive ? "plus" : "minus"}`,
              textContent: `${positive ? "+" : ""}${row.delta} K`,
            }),
          ),
        );
      }
    } catch {
      ledger.replaceChildren(el("p", { className: "profile-empty", textContent: "流水加载失败。" }));
    }
  }

  // ── 成就 ──
  async function renderBadges() {
    const wall = document.querySelector("#badgesWall");
    const countLabel = document.querySelector("#badgeCountLabel");
    const levelBox = document.querySelector("#levelProgressBox");
    try {
      const [achRes, levelsRes] = await Promise.all([
        api("/api/achievements"),
        api("/api/levels"),
      ]);
      const data = await achRes.json();
      const levelsData = await levelsRes.json();
      countLabel.textContent = `已获得 ${data.earned} / ${data.total}`;
      wall.replaceChildren();
      const mine = new Map((data.mine || []).map((b) => [b.code, b]));
      if (!data.total) {
        wall.append(el("p", { className: "profile-empty", textContent: "勋章整理中。" }));
        return;
      }
      const showcaseCode = data.showcaseCode || "";
      for (const item of data.items) {
        const earned = mine.get(item.code);
        const wrapItem = el("span", { className: "badge-mini-wrap" });
        wrapItem.append(
          el("span", {
            className: `badge-mini tier-${item.tier}` + (earned ? "" : " locked") + (showcaseCode === item.code ? " showcasing" : ""),
            title: earned ? `获得于 ${new Date(earned.grantedAt).toLocaleDateString("zh-CN")}` : item.description,
            textContent: earned ? item.name : `${item.name}（未达成）`,
          }),
        );
        if (earned) {
          wrapItem.append(
            el("button", {
              className: "badge-showcase-btn" + (showcaseCode === item.code ? " active" : ""),
              type: "button",
              textContent: showcaseCode === item.code ? "取消展示" : "设为展示",
              onclick: async () => {
                const cancel = showcaseCode === item.code;
                const res = await api("/api/achievements/showcase", {
                  method: "POST",
                  headers: { "X-CSRFToken": csrf() },
                  body: JSON.stringify({ code: cancel ? "" : item.code }),
                });
                const d = await res.json().catch(() => ({}));
                if (!res.ok) return showToast(d.error || "操作失败", "error");
                showToast(cancel ? "已取消展示" : `已将「${item.name}」设为展示勋章，发帖时会显示`, "success");
                renderBadges();
              },
            }),
          );
        }
        wall.append(wrapItem);
      }
      // 等级进度
      const my = levelsData.my;
      levelBox.replaceChildren();
      if (my && my.progress) {
        const card = el("div", { className: "profile-points-card" },
          el("small", { textContent: "LEVEL PROGRESS" }),
          el("h3", { textContent: `距离 LV${my.progress.nextLevel} ${my.progress.nextName}` }),
        );
        const bars = el("div", { className: "level-progress", style: "margin-top:10px" });
        for (const part of my.progress.parts) {
          const pct = Math.min(100, Math.round((part.value / Math.max(1, part.threshold)) * 100));
          bars.append(
            el("div", { className: "level-progress-row" },
              el("span", { className: "level-progress-label", textContent: part.key === "contribution" ? "贡献分" : { active_days: "活跃天数", topics: "发帖数", replies: "评论数", likes_received: "获赞数" }[part.key] || part.key }),
              el("div", { className: "level-progress-track" },
                el("div", { className: "level-progress-fill", style: `width:${pct}%` })),
              el("span", { className: "level-progress-num" + (part.done ? " done" : ""),
                textContent: part.done ? "已完成" : `${part.value} / ${part.threshold}` }),
            ),
          );
        }
        card.append(bars);
        levelBox.append(card);
      }
    } catch {
      wall.replaceChildren(el("p", { className: "profile-empty", textContent: "成就加载失败。" }));
    }
  }

  // ── 我的作品（与个人主页合并后的内容）──
  async function renderWorks() {
    const topics = document.querySelector("#worksTopics");
    const replies = document.querySelector("#worksReplies");
    if (!profile) return;
    topics.replaceChildren(el("p", { className: "profile-empty", textContent: "加载中…" }));
    try {
      const res = await api(`/api/forum/users/${encodeURIComponent(profile.username)}`);
      const data = await res.json();
      const p = data.profile || {};
      document.querySelector("#worksTopicCount").textContent = `${(p.topics || []).length} 条`;
      document.querySelector("#worksReplyCount").textContent = `${(p.replies || []).length} 条`;
      topics.replaceChildren();
      if (!(p.topics || []).length) {
        topics.append(el("p", { className: "profile-empty", textContent: "还没有发布过作品，去社区发第一帖吧。" }));
      } else {
        for (const topic of p.topics) {
          topics.append(
            el("a", { className: "profile-topic-card", href: `/forum?topic=${topic.id}` },
              el("div", { className: "profile-topic-top" },
                el("span", { className: "profile-topic-category", textContent: topic.category }),
                el("time", { textContent: topic.created_at ? new Date(topic.created_at).toLocaleDateString("zh-CN") : "" }),
              ),
              el("h3", { textContent: topic.title }),
              el("p", { textContent: topic.excerpt }),
              el("span", { className: "profile-topic-stats", textContent: `${topic.replies} 条回复 · ${topic.views} 次浏览` }),
            ),
          );
        }
      }
      replies.replaceChildren();
      if (!(p.replies || []).length) {
        replies.append(el("p", { className: "profile-empty", textContent: "还没有发表过回复。" }));
      } else {
        for (const reply of p.replies) {
          replies.append(
            el("a", { className: "profile-reply-card", href: `/forum?topic=${reply.topic_id}` },
              el("strong", { textContent: reply.topic_title }),
              el("p", { textContent: reply.content }),
              el("time", { textContent: reply.created_at ? new Date(reply.created_at).toLocaleDateString("zh-CN") : "" }),
            ),
          );
        }
      }
    } catch {
      topics.replaceChildren(el("p", { className: "profile-empty", textContent: "作品加载失败。" }));
      replies.replaceChildren();
    }
  }

  // ── tabs ──
  function bindTabs() {
    document.querySelectorAll("#accountTabs .profile-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#accountTabs .profile-tab").forEach((b) => b.classList.toggle("active", b === btn));
        const key = btn.dataset.tab;
        document.querySelectorAll(".account-panel").forEach((panel) => {
          panel.style.display = panel.id === `tab-${key}` ? "" : "none";
        });
        if (key === "points") renderPoints();
        if (key === "badges") renderBadges();
        if (key === "works") renderWorks();
      });
    });
  }

  async function init() {
    bindTabs();
    try {
      const meRes = await api("/api/account/me");
      const me = await meRes.json();
      if (!me.loggedIn) throw new Error("guest");
      currentUser = me;
    } catch {
      document.querySelector("#accountLoginHint").style.display = "";
      document.querySelector("#accountRoot").style.display = "none";
      return;
    }
    document.querySelector("#accountRoot").style.display = "";
    try {
      const profileRes = await api("/api/forum/users/me/profile");
      profile = (await profileRes.json()).profile;
      renderHero(profile);
      renderProfileForm(profile);
      bindProfileForm();
    } catch {
      showToast("资料加载失败", "error");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
