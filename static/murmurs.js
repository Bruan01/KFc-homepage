/* Plain text throughout: user content is only assigned with textContent. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const paths = {
    pin: '<path d="M9.5 3.5h5l-.8 6.2 2.8 2.8H7.5l2.8-2.8-.8-6.2zM12 12.5V20"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    flag: '<path d="M5 21V4c5-4 9 4 14 0v10c-5 4-9-4-14 0"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>',
    pen: '<path d="m14 5 5 5M4 20l5-1L20 8a3.5 3.5 0 0 0-5-5L4 14l-1 7Z"/>',
    heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0l-1 1-1-1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    comment: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/>',
    more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    link: '<path d="m10 13 4-4M8 16l-2 2a3.5 3.5 0 0 1-5-5l5-5a3.5 3.5 0 0 1 5 0M16 8l2-2a3.5 3.5 0 0 1 5 5l-5 5a3.5 3.5 0 0 1-5 0" transform="translate(0 0) scale(.95)"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    "arrow-left": '<path d="m12 5-7 7 7 7M5 12h15"/>',
    "arrow-right": '<path d="m12 5 7 7-7 7M19 12H4"/>',
    "arrow-up-right": '<path d="M6 18 18 6M6 6h12v12"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
    sprout: '<path d="M12 21v-8M12 13C4 13 3 8 3 4c6 0 9 3 9 9Zm0-2c0-5 4-8 9-8 0 6-3 9-9 9"/>',
    spark: '<path d="m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7L12 3Z"/>',
    camera: '<path d="M4 6h3l2-3h6l2 3h3v15H4Z"/><circle cx="12" cy="13" r="4"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    check: '<path d="m4.5 12.5 5 5L19.5 6.5"/>',
    clock: '<path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.2V12l3.2 2"/>',
    smile: '<circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 3 4 3 4-3 4-3M8 9h.01M16 9h.01"/>',
    calendar: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4M16 3v4M4 10h16M8 14h2M14 14h2M8 17h2"/>',
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "mm-icon");
    svg.innerHTML = paths[name] || paths.comment;
    return svg;
  }
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (key === "hidden" || key === "disabled") node[key] = value;
      else node.setAttribute(key, value);
    }
    node.append(...children.filter((child) => child != null));
    return node;
  }
  function button(label, action, className = "mm-secondary", name) {
    return el("button", { type: "button", className, onClick: action }, name ? icon(name) : null, label);
  }
  const params = new URLSearchParams(location.search);
  const state = { profile: null, moderator: false, images: [], commentDrafts: new Map(), publishing: false, loading: false, cursor: null, epoch: 0, key: newKey(),
    view: params.get("view") === "reports" ? "reports" : params.get("scope") === "mine" ? "mine" : "all", author: params.get("author") || "", post: /^\d+$/.test(params.get("post") || "") ? params.get("post") : "",
    appeal: /^(post|comment):\d+$/.test(params.get("appeal") || "") ? params.get("appeal") : "", moderation: params.get("mod") === "appeals" ? "appeals" : "reports",
    from: ["reports", "appeals"].includes(params.get("from")) ? params.get("from") : "" };
  const content = $("mm-content");
  const feed = $("mm-feed");
  const dialog = $("mm-dialog");
  state.page = Math.max(1, Number(params.get("page")) || 1);
  let toastTimer, draftTimer;
  function newKey() { return globalThis.crypto?.randomUUID?.() || `m-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
  function toast(message, success = false) {
    $("mm-toast").textContent = message;
    $("mm-toast").classList.remove("xiaok-toast");
    if (success) window.KflowXiaok?.decorateToast($("mm-toast"));
    $("mm-toast").classList.add("mm-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $("mm-toast").classList.remove("mm-visible"), 3500);
  }
  async function api(url, options = {}) {
    const headers = { ...options.headers };
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (options.method && options.method !== "GET") headers["X-CSRFToken"] = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
    let response;
    try { response = await fetch(url, { ...options, headers, credentials: "same-origin" }); }
    catch { throw new Error("网络连接中断，请检查网络后重试，已输入的内容会保留"); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || (response.status === 403 ? "操作未完成，请刷新页面后重试" : `操作未完成（${response.status}），请重试`));
    return data;
  }
  function loginUrl() { return `/login?next=${encodeURIComponent(location.pathname + location.search)}`; }
  function requireLogin() {
    if (state.profile) return true;
    saveDraft();
    openDialog("登录后，加入这场闲聊", el("p", { text: "登录即可发布碎碎念、点赞和评论。写下的文字会留在这台设备上。" }),
      el("div", { className: "mm-dialog-actions" }, button("先逛逛", closeDialog), el("a", { href: loginUrl(), className: "mm-primary", text: "去登录" })));
    return false;
  }
  function avatar(author, link = true) {
    const node = el(link ? "a" : "span", { className: "mm-avatar", ...(link ? { href: `/forum/user/${encodeURIComponent(author.username)}`, "aria-label": `${author.display_name}的个人主页` } : { "aria-hidden": "true" }) });
    node.textContent = [...(author.display_name || author.username || "?")][0].toUpperCase();
    if (author.avatar_url && /^(\/[^/]|https?:\/\/)/i.test(author.avatar_url)) {
      const img = el("img", { src: author.avatar_url, alt: "", loading: "lazy" });
      img.addEventListener("error", () => img.remove());
      node.append(img);
      // Keep the fallback out of the image's layout.
      node.firstChild.remove();
      img.addEventListener("error", () => { node.textContent = [...author.display_name][0] || "?"; });
    }
    return node;
  }
  function relativeTime(value) {
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "";
    const age = Math.max(0, (Date.now() - date.getTime()) / 1000);
    if (age < 60) return "刚刚";
    if (age < 3600) return `${Math.floor(age / 60)} 分钟前`;
    if (age < 86400) return `${Math.floor(age / 3600)} 小时前`;
    if (age < 604800) return `${Math.floor(age / 86400)} 天前`;
    return date.toLocaleDateString("zh-CN", { month: "long", day: "numeric", ...(date.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) });
  }
  function timestamp(value, href) {
    return el(href ? "a" : "time", { className: "mm-post-time", ...(href ? { href } : { datetime: value }), title: new Date(value).toLocaleString("zh-CN"), text: relativeTime(value) });
  }
  function openDialog(title, ...children) {
    if (dialog.open) dialog.close();
    $("mm-dialog-title").textContent = title;
    $("mm-dialog-body").replaceChildren(...children);
    dialog.showModal();
  }
  function closeDialog() { dialog.close(); }
  function confirmAction(title, message, label, action) {
    const error = el("p", { className: "mm-error", role: "alert", hidden: true });
    const submit = button(label, async () => {
      submit.disabled = true;
      error.hidden = true;
      try { await action(); closeDialog(); }
      catch (e) { error.textContent = e.message; error.hidden = false; }
      finally { submit.disabled = false; }
    }, "mm-primary");
    openDialog(title, el("p", { text: message }), error, el("div", { className: "mm-dialog-actions" }, button("取消", closeDialog), submit));
  }
  function draftName() { return `kflow-murmurs-draft:${state.profile?.username || "guest"}`; }
  function draftChanged() {
    resizeEditor(content);
    state.key = newKey();
    $("mm-counter").textContent = `${[...content.value].length} / 1000`;
    $("mm-counter").classList.toggle("mm-over-limit", [...content.value].length > 1000);
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 300);
  }
  function saveDraft() {
    try {
      if (!content.value && !state.images.length) {
        localStorage.removeItem(draftName());
        $("mm-draft-status").textContent = "";
        return;
      }
      localStorage.setItem(draftName(), JSON.stringify({ content: content.value, key: state.key,
        images: state.images.filter((i) => i.server).map((i) => i.server) }));
      $("mm-draft-status").textContent = "草稿已保存";
    } catch { $("mm-draft-status").textContent = "草稿仅保留在当前页面"; }
  }
  function restoreDraft() {
    try {
      const own = localStorage.getItem(draftName());
      const guest = state.profile ? localStorage.getItem("kflow-murmurs-draft:guest") : null;
      const draft = JSON.parse(own || guest || "null");
      if (!draft || typeof draft.content !== "string") return;
      content.value = draft.content;
      if (Array.isArray(draft.images)) state.images = draft.images.filter((i) => Number.isInteger(i.id) && i.url === `/api/forum/images/${i.id}`).slice(0, 9).map((server) => ({ server, url: server.url, status: "done" }));
      draftChanged();
      if (/^[\w-]{8,64}$/.test(draft.key || "")) state.key = draft.key;
      renderPreviews();
      saveDraft();
      if (!own && guest) localStorage.removeItem("kflow-murmurs-draft:guest");
    } catch { /* Invalid local storage is ignored. */ }
  }
  function renderPreviews() {
    $("mm-previews").replaceChildren(...state.images.map((item, index) => {
      const card = el("figure", { className: "mm-preview" }, el("img", { src: item.url, alt: `待发布图片 ${index + 1}` }));
      const remove = button("", () => {
        if (state.publishing) return;
        state.images = state.images.filter((i) => i !== item);
        if (item.url.startsWith("blob:")) URL.revokeObjectURL(item.url);
        draftChanged(); renderPreviews(); saveDraft();
      }, "", "close");
      remove.setAttribute("aria-label", `移除图片 ${index + 1}`);
      remove.disabled = state.publishing;
      card.append(remove);
      if (item.status === "loading") card.append(el("span", { className: "mm-preview-status", role: "status", text: "正在上传…" }));
      if (item.status === "error") {
        const retry = button("上传失败，点击重试", () => uploadImage(item), "mm-preview-status mm-retry-upload");
        card.append(retry);
      }
      return card;
    }));
    $("mm-publish").disabled = state.publishing || state.images.some((i) => i.status === "loading");
  }
  async function uploadImage(item) {
    item.status = "loading";
    renderPreviews();
    const data = new FormData(); data.append("file", item.file);
    try {
      const result = await api("/api/forum/images", { method: "POST", body: data });
      item.server = result.image; item.status = "done";
    } catch (e) { item.status = "error"; showPublishError(e.message); }
    renderPreviews(); saveDraft();
  }
  async function addImages(files) {
    if (!requireLogin() || state.publishing) return;
    $("mm-publish-error").hidden = true;
    const pending = [];
    for (const file of files) {
      if (state.images.length >= 9) { showPublishError("最多添加 9 张图片"); break; }
      if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) { showPublishError("请选择 JPG、PNG、WebP 或 GIF 图片"); continue; }
      if (file.size > 5 * 1024 * 1024) { showPublishError("每张图片最大 5 MB，请压缩后重试"); continue; }
      const item = { file, url: URL.createObjectURL(file), status: "loading" };
      state.images.push(item); pending.push(item);
    }
    draftChanged(); renderPreviews();
    // Sequential uploads avoid nine simultaneous image encodes on the server.
    for (const item of pending) if (state.images.includes(item)) await uploadImage(item);
  }
  function showPublishError(message) { $("mm-publish-error").textContent = message; $("mm-publish-error").hidden = false; }
  async function publish(event) {
    event.preventDefault();
    if (!requireLogin() || state.publishing) return;
    const value = content.value.trim();
    if (!value && !state.images.length) { showPublishError("写点什么，或分享一张图片吧"); content.focus(); return; }
    if ([...value].length > 1000) { showPublishError("碎碎念最多支持 1000 个字"); content.focus(); return; }
    if (state.images.some((i) => i.status !== "done")) { showPublishError("请等待图片上传完成，或重试上传失败的图片"); return; }
    state.publishing = true; content.disabled = true;
    $("mm-add-images").disabled = true;
    $("mm-publish").textContent = "发布中…"; $("mm-publish-error").hidden = true;
    renderPreviews(); saveDraft();
    try {
      const result = await api("/api/murmurs", { method: "POST", body: JSON.stringify({ content: value, images: state.images.map((i) => i.server.id), client_key: state.key }) });
      state.images.forEach((i) => { if (i.url.startsWith("blob:")) URL.revokeObjectURL(i.url); });
      state.images = []; content.value = ""; draftChanged(); saveDraft();
      toast(result.ai_reply_queued ? "已发布，小 K 会稍后回复你，回复后会有通知" : "已发布，今天又留下了一点记录", true);
      if (state.view === "reports" || state.post || (state.author && state.author !== state.profile.username)) {
        location.href = `/murmurs?post=${result.item.id}`;
      } else await loadFeed(true);
    } catch (e) { showPublishError(e.message); }
    finally {
      state.publishing = false; content.disabled = false; $("mm-add-images").disabled = false;
      $("mm-publish").textContent = "发布"; renderPreviews();
    }
  }
  function focusComposer() {
    if ($("mm-composer").hidden) { location.href = "/murmurs"; return; }
    $("mm-composer").scrollIntoView({ block: "center", behavior: "instant" }); content.focus({ preventScroll: true });
  }
  function imageGrid(images, author) {
    const grid = el("div", { className: `mm-image-grid mm-images-${images.length}` });
    images.forEach((image, index) => {
      const img = el("img", { src: image.url, alt: `${author}分享的图片 ${index + 1}`, loading: "lazy", decoding: "async", ...(image.width && image.height ? { width: image.width, height: image.height } : {}) });
      const item = button("", () => openLightbox(images, index, author), "");
      item.setAttribute("aria-label", `放大查看图片 ${index + 1}`);
      item.append(img); grid.append(item);
    });
    return grid;
  }
  let lightboxState = null;
  function openLightbox(images, index, author) { lightboxState = { images, index, author }; renderLightbox(); $("mm-lightbox").showModal(); }
  function renderLightbox() {
    const { images, index, author } = lightboxState;
    $("mm-lightbox-image").src = images[index].url;
    $("mm-lightbox-image").alt = `${author}分享的图片 ${index + 1}`;
    $("mm-lightbox-count").textContent = `${index + 1} / ${images.length}`;
    document.querySelector(".mm-lightbox-prev").hidden = images.length < 2;
    document.querySelector(".mm-lightbox-next").hidden = images.length < 2;
  }
  function stepImage(step) { if (!lightboxState) return; lightboxState.index = (lightboxState.index + step + lightboxState.images.length) % lightboxState.images.length; renderLightbox(); }
  function openReport(post, comment) {
    if (!requireLogin()) return;
    const reason = el("select", { id: "mm-report-reason" }, ...Object.entries({ spam: "垃圾广告", abuse: "人身攻击或不友善内容", copyright: "侵犯版权", other: "其他问题" }).map(([value, label]) => el("option", { value, text: label })));
    const details = el("textarea", { id: "mm-report-details", rows: "3", maxlength: "500", placeholder: "可以补充具体情况（选填）" });
    const error = el("p", { className: "mm-error", role: "alert", hidden: true });
    const send = button("提交举报", async () => {
      send.disabled = true;
      try {
        const url = comment ? `/api/murmurs/comments/${comment.id}/report` : `/api/murmurs/${post.id}/report`;
        await api(url, { method: "POST", body: JSON.stringify({ reason: reason.value, details: details.value }) });
        closeDialog(); toast("举报已提交，管理员会进行核实");
      } catch (e) { error.hidden = false; error.textContent = e.message; }
      finally { send.disabled = false; }
    }, "mm-primary");
    openDialog(comment ? "举报这条评论" : "举报这条碎碎念", el("label", { for: reason.id, text: "举报原因" }), reason, el("label", { for: details.id, text: "补充说明" }), details, error, el("div", { className: "mm-dialog-actions" }, button("取消", closeDialog), send));
  }
  function postMenu(post, card) {
    const actions = el("div", { className: "mm-menu-actions" });
    if (state.moderator) {
      const pin = button(post.pinned ? "取消置顶" : "置顶这条碎碎念", async () => {
        pin.disabled = true;
        try {
          const data = await api(`/api/murmurs/${post.id}/pin`, { method: "POST", body: JSON.stringify({ pinned: !post.pinned }) });
          post.pinned = data.pinned;
          closeDialog();
          await loadFeed(true);
          toast(post.pinned ? "碎碎念已置顶" : "已取消置顶", true);
        } catch (error) { toast(error.message); }
        finally { pin.disabled = false; }
      }, "mm-menu-item", "pin");
      actions.append(pin);
    }
    if (post.can_delete) actions.append(button("删除这条碎碎念", () => confirmAction("删除碎碎念？", "删除后，这条内容将不再公开显示，且不能恢复。", "确认删除", async () => {
      await api(`/api/murmurs/${post.id}`, { method: "DELETE" }); await loadFeed(true); toast("碎碎念已删除");
      if (!feed.children.length) renderEmpty();
    }), "mm-menu-item", "trash"));
    if (!post.is_own) {
      actions.append(button("举报内容", () => openReport(post), "mm-menu-item", "flag"));
      actions.append(button("不看这个人的碎碎念", () => {
        if (!requireLogin()) return;
        confirmAction("屏蔽这个人？", "他的碎碎念和评论将从你的信息流隐藏。你可以在屏蔽管理中恢复。", "确认屏蔽", async () => {
          await api("/api/murmurs/blocks", { method: "POST", body: JSON.stringify({ username: post.author.username }) });
          await loadFeed(true); toast("已屏蔽，可在屏蔽管理中恢复");
        });
      }, "mm-menu-item", "shield"));
    }
    openDialog("这条碎碎念", actions);
  }
  async function copyPost(post) {
    const url = `${location.origin}/murmurs?post=${post.id}`;
    try { await navigator.clipboard.writeText(url); toast("分享链接已复制", true); }
    catch {
      const input = el("input", { value: url, readonly: "", className: "mm-copy-input", "aria-label": "碎碎念分享链接" });
      openDialog("分享这条碎碎念", el("p", { text: "复制下面的链接，即可分享给朋友。" }), input); input.select();
    }
  }
  function postCard(post) {
    const deleted = Boolean(post.is_deleted);
    const card = el("article", { className: `mm-post${deleted ? " mm-deleted-preview" : ""}`, id: `murmur-${post.id}`, "aria-label": `${post.author.display_name}的碎碎念` });
    if (!state.post && !deleted) {
      card.classList.add("mm-post-navigable");
      card.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        if (event.target.closest("a, button, input, textarea, select, label, summary, [role='button'], [contenteditable], .mm-comments, .mm-image-grid")) return;
        if (window.getSelection()?.toString()) return;
        window.location.assign(`/murmurs?post=${post.id}`);
      });
    }
    const more = deleted ? null : button("", () => postMenu(post, card), "mm-icon-button", "more");
    if (more) more.setAttribute("aria-label", "更多操作");
    card.append(el("div", { className: "mm-post-header" }, avatar(post.author), el("div", { className: "mm-author-meta" }, el("a", { href: `/forum/user/${encodeURIComponent(post.author.username)}`, className: "mm-author-name", text: post.author.display_name }), el("span", { className: "mm-author-handle", text: `@${post.author.username}` }), timestamp(post.created_at, `/murmurs?post=${post.id}`)), more));
    if (post.pinned && !deleted) card.querySelector(".mm-author-meta").append(el("span", { className: "mm-pin-badge" }, icon("pin"), "置顶"));
    if (deleted) {
      const detail = [post.deleted_by ? `操作人 ${post.deleted_by}` : "", post.deleted_at ? timeText(post.deleted_at) : "", post.deletion_reason].filter(Boolean).join(" · ");
      card.append(el("div", { className: "mm-deleted-banner", role: "status" }, icon("shield"),
        el("div", { className: "mm-deleted-banner-copy" },
          el("strong", { text: "管理员预览 · 这条碎碎念已下线" }),
          el("span", { text: detail || "互动与评论已停用，仅管理员可见" }))));
    }
    if (post.content) {
      const long = post.content.length > 260 || post.content.split("\n").length > 6;
      const body = el("p", { className: `mm-post-text${long && !state.post ? " mm-collapsed" : ""}`, id: `mm-text-${post.id}` });
      renderMentionText(body, post.content, post.mention_usernames);
      card.append(body);
      if (long && !state.post) {
        const expand = button("展开全文", () => { const collapsed = body.classList.toggle("mm-collapsed"); expand.textContent = collapsed ? "展开全文" : "收起"; expand.setAttribute("aria-expanded", String(!collapsed)); }, "mm-text-button mm-expand");
        expand.setAttribute("aria-expanded", "false"); expand.setAttribute("aria-controls", body.id); card.append(expand);
      }
    }
    if (post.author.is_official) card.querySelector(".mm-author-meta").prepend(window.KflowSocial.officialBadge());
    if (!post.is_own) card.querySelector(".mm-author-meta").append(window.KflowSocial.followButton(post.author, state.profile?.username, toast));
    if (post.images.length) card.append(imageGrid(post.images, post.author.display_name));
    if (deleted) {
      card.append(el("div", { className: "mm-deleted-foot" },
        el("p", { className: "mm-mod-hint", text: "互动与评论已停用，仅管理员可预览此内容。" }),
        el("a", { className: "mm-mod-btn is-view", href: moderationReturnHref() }, icon("back"), moderationReturnLabel())));
      return card;
    }
    const likes = button("", async () => {
      if (!requireLogin()) return;
      likes.disabled = true;
      try {
        const data = await api(`/api/murmurs/${post.id}/like`, { method: "POST", body: JSON.stringify({ liked: !post.liked }) });
        post.liked = data.liked; post.like_count = data.like_count; updateLikes();
      } catch (e) { toast(e.message); }
      finally { likes.disabled = false; }
    }, "mm-action");
    function updateLikes() {
      likes.replaceChildren(icon("heart"), String(post.like_count || 0));
      likes.setAttribute("aria-pressed", String(post.liked));
      likes.setAttribute("aria-label", `${post.liked ? "取消点赞" : "点赞"}，${post.like_count} 个赞`);
      likes.title = post.liked ? "取消点赞" : "点赞";
    }
    updateLikes();
    const comments = el("div", { className: "mm-comments", id: `mm-comments-${post.id}`, hidden: true });
    let opened = false;
    const commentButton = button("", () => {
      comments.hidden = !comments.hidden; commentButton.setAttribute("aria-expanded", String(!comments.hidden));
      if (!comments.hidden && !opened) { opened = true; renderComments(post, comments, updateComments); }
    }, "mm-action", "comment");
    commentButton.setAttribute("aria-expanded", "false"); commentButton.setAttribute("aria-controls", comments.id);
    function updateComments(count = post.comment_count) {
      post.comment_count = count;
      commentButton.replaceChildren(icon("comment"), String(count || 0));
      commentButton.setAttribute("aria-label", `评论，${count || 0} 条评论`); commentButton.title = "查看评论";
    }
    updateComments();
    const share = button("", () => copyPost(post), "mm-action mm-share", "link");
    share.setAttribute("aria-label", "分享这条碎碎念"); share.title = "复制分享链接";
    const detailLink = !state.post ? el("a", {
      href: `/murmurs?post=${post.id}`,
      className: "mm-action mm-detail-link",
      "aria-label": "查看这条碎碎念的详情",
      text: "查看详情",
    }) : null;
    card.append(el("div", { className: "mm-post-footer" }, likes, commentButton, share, detailLink), comments);
    if (state.post) { comments.hidden = false; commentButton.setAttribute("aria-expanded", "true"); opened = true; renderComments(post, comments, updateComments); }
    return card;
  }
  function renderComments(post, host, updateCount) {
    const list = el("div");
    let composer;
    const status = el("p", { className: "mm-comment-hint", role: "status", text: "正在加载评论…" });
    const more = button("查看更多评论", () => load(false), "mm-text-button"); more.hidden = true;
    let next = null, loading = false, locateTarget = true;
    const showAll = button("查看全部评论", () => { locateTarget = false; showAll.hidden = true; load(true); }, "mm-text-button");
    showAll.hidden = !state.post || !/^\d+$/.test(params.get("comment") || "");
    host.replaceChildren(showAll, list, status, more);
    async function load(reset) {
      if (loading) return;
      loading = true; more.disabled = true;
      if (reset) { list.replaceChildren(); next = null; }
      try {
        const query = new URLSearchParams();
        if (next) query.set("after", next);
        const target = params.get("comment");
        if (locateTarget && state.post && /^\d+$/.test(target || "") && !next) query.set("target", target);
        const data = await api(`/api/murmurs/${post.id}/comments?${query}`);
        for (const item of data.items) if (!list.querySelector(`[data-comment-id="${item.id}"]`)) list.append(commentCard(item));
        next = data.next_cursor; more.hidden = !next; status.hidden = true;
        if (state.profile && data.items.length) api(`/api/murmurs/${post.id}/read`, {method:"POST", body:JSON.stringify({upto:Math.max(...data.items.map(item=>item.id))})}).catch(()=>{});
        if (!list.children.length) { status.textContent = "还没有评论，来接一句吧。"; status.hidden = false; }
        if (query.has("target")) {
          const row = list.querySelector(`[data-comment-id="${target}"]`);
          if (row) requestAnimationFrame(() => { row.classList.add("mm-mentioned-target"); row.tabIndex = -1; row.focus({ preventScroll: true }); row.scrollIntoView({ block: "center", behavior: "instant" }); });
          else { status.textContent = "这条提醒对应的评论已删除或不可见"; status.hidden = false; }
        }
      } catch (e) { status.textContent = e.message; status.hidden = false; more.textContent = "重试加载评论"; more.hidden = false; }
      finally { loading = false; more.disabled = false; }
    }
    function commentCard(item) {
      const row = el("div", { className: "mm-comment", id: `murmur-comment-${item.id}`, "data-comment-id": item.id });
      const menu = button("", () => {
        if (item.can_delete) confirmAction("删除这条评论？", "删除后，这条评论将不再显示。", "确认删除", async () => {
          const data = await api(`/api/murmurs/comments/${item.id}`, { method: "DELETE" }); row.remove(); updateCount(data.comment_count);
          if (state.commentDrafts.get(post.id)?.replyTo?.id === item.id) composer?.clearReply();
          list.querySelectorAll(`[data-reply-parent="${item.id}"]`).forEach((node) => { node.textContent = "原评论已删除或不可见"; node.removeAttribute("title"); });
          toast("评论已删除");
        });
        else openReport(post, item);
      }, "mm-icon-button", "more"); menu.setAttribute("aria-label", item.can_delete ? "删除评论" : "举报评论");
      const main = el("div", { className: "mm-comment-main" }, el("div", { className: "mm-comment-meta" }, el("a", { href: `/forum/user/${encodeURIComponent(item.author.username)}`, text: item.author.display_name }), timestamp(item.created_at)));
      if (item.reply_to) {
        const parent = item.reply_to;
        main.append(el("p", { className: "mm-reply-context", "data-reply-parent": parent.id,
          text: parent.unavailable ? "原评论已删除或不可见" : `回复 @${parent.author.display_name}`,
          ...(parent.unavailable ? {} : { title: parent.content }) }));
      }
      if (item.content) { const body = el("p"); renderMentionText(body, item.content, item.mention_usernames); main.append(body); }
      if (item.images?.length) main.append(imageGrid(item.images, item.author.display_name));
      const reply = button("回复", () => { if (requireLogin()) composer?.replyTo(item); }, "mm-comment-reply");
      if (item.author.is_official) main.querySelector(".mm-comment-meta").append(window.KflowSocial.officialBadge());
      if (item.is_ai_reply) main.querySelector(".mm-comment-meta").append(el("span", { className: "social-official-badge", text: "AI 助手" }));
      reply.setAttribute("aria-label", `回复${item.author.display_name}的评论`); main.append(reply);
      if (!item.is_own) main.querySelector(".mm-comment-meta").append(window.KflowSocial.followButton(item.author, state.profile?.username, toast));
      row.append(avatar(item.author), main, menu);
      return row;
    }
    if (state.profile) {
      composer = commentComposer(post, (data) => {
        if (!list.querySelector(`[data-comment-id="${data.item.id}"]`)) list.append(commentCard(data.item));
        status.hidden = true; updateCount(data.comment_count);
      });
      host.append(composer);
    } else host.append(button("登录后，来说两句", requireLogin, "mm-text-button"));
    load(true);
  }

  const COMMENT_EMOJIS = [
    ["😀", "开心"], ["😂", "笑哭"], ["🤣", "大笑"], ["🥹", "感动"], ["😊", "微笑"], ["😍", "喜欢"], ["🥰", "幸福"], ["😘", "亲亲"],
    ["😎", "酷"], ["🤔", "思考"], ["🫡", "敬礼"], ["🙃", "倒脸"], ["😭", "哭泣"], ["🥲", "含泪微笑"], ["😅", "尴尬"], ["😴", "困了"],
    ["👍", "赞"], ["👎", "踩"], ["👏", "鼓掌"], ["🙌", "欢呼"], ["🙏", "感谢"], ["💪", "加油"], ["🤝", "握手"], ["🫶", "比心"],
    ["❤️", "爱心"], ["💔", "心碎"], ["🔥", "火热"], ["✨", "闪亮"], ["🎉", "庆祝"], ["🚀", "起飞"], ["☕", "咖啡"], ["🐱", "猫咪"],
  ];
  function resizeEditor(input) {
    if (!input.isConnected || !input.getClientRects().length) return;
    input.style.height = "auto";
    const expanded = input === content && $("mm-composer").classList.contains("mm-writing-expanded");
    const minimum = input === content ? 160 : input.closest(".mm-comment-active") ? 80 : 44;
    const maximum = expanded ? Infinity : Math.max(minimum, Math.round(window.innerHeight * (input === content ? .65 : .4)));
    input.style.height = `${Math.min(maximum, Math.max(minimum, input.scrollHeight + 2))}px`;
    input.style.overflowY = input.scrollHeight > maximum ? "auto" : "hidden";
  }
  function renderMentionText(host, value, allowed = []) { window.KflowEditor.plainMentions(host, value, allowed); }
  function emojiPicker(...args) { return window.KflowEditor.emojiPicker(...args); }
  function mentionPicker(...args) { return window.KflowEditor.mentionPicker(...args, () => !!state.profile); }
  function commentComposer(post, onSent) {
    if (!state.commentDrafts.has(post.id)) state.commentDrafts.set(post.id, { content: "", key: newKey(), images: [], sending: false, replyTo: null });
    const draft = state.commentDrafts.get(post.id);
    draft.onSent = onSent;
    const inputId = `mm-reply-${post.id}`;
    const input = el("textarea", { id: inputId, rows: "1", className: "mm-comment-input", placeholder: "说两句……", "aria-describedby": `${inputId}-hint ${inputId}-error` });
    input.value = draft.content;
    const error = el("p", { id: `${inputId}-error`, className: "mm-error", role: "alert", hidden: true });
    const fail = (message) => { draft.error = message; draft.render(); };
    const previews = el("div", { className: "mm-previews mm-comment-previews", "aria-label": "待发送的评论图片" });
    const replyLabel = el("span", { role: "status", "aria-live": "polite" });
    const cancelReply = button("", () => { form.clearReply(); input.focus(); }, "mm-icon-button", "close");
    cancelReply.setAttribute("aria-label", "取消回复，改为直接评论");
    const replyTarget = el("div", { className: "mm-reply-target", hidden: true }, replyLabel, cancelReply);
    const hint = el("p", { id: `${inputId}-hint`, className: "mm-comment-hint", text: "图片 / GIF 最多 4 张，每张 5 MB；支持粘贴图片" });
    const counter = el("span", { className: "mm-counter" });
    const send = el("button", { type: "submit", className: "mm-primary", text: "发送" });
    const files = el("input", { type: "file", accept: "image/jpeg,image/png,image/webp,image/gif", multiple: "", hidden: true });
    const add = button("图片 / 表情包", () => files.click(), "mm-image-button", "image");
    const picker = emojiPicker(input, 500, changed, () => draft.sending, fail);
    const mentions = mentionPicker(input, changed, () => draft.sending, 500, fail);
    const tools = el("div", { className: "mm-comment-tools" }, add, picker, mentions.trigger, counter, send);
    function changed() { draft.content = input.value; draft.key = newKey(); draft.error = ""; render(); }
    input.addEventListener("input", changed);
    let previewSignature = "";
    function render() {
      if (input.value !== draft.content) input.value = draft.content;
      error.textContent = draft.error || ""; error.hidden = !draft.error;
      const active = !!(draft.expanded || draft.content.trim() || draft.images.length || draft.sending || draft.error || draft.replyTo);
      form.classList.toggle("mm-comment-active", active);
      tools.hidden = hint.hidden = !active; previews.hidden = !draft.images.length;
      replyTarget.hidden = !draft.replyTo; cancelReply.disabled = draft.sending;
      replyLabel.textContent = draft.replyTo ? `回复 @${draft.replyTo.author.display_name}` : "";
      input.rows = active ? 2 : 1;
      input.placeholder = draft.replyTo ? `回复 ${draft.replyTo.author.display_name}……` : active ? "说两句，也可以发张表情包……" : "说两句……";
      counter.textContent = `${[...draft.content].length} / 500`;
      counter.classList.toggle("mm-over-limit", [...draft.content].length > 500);
      input.disabled = add.disabled = files.disabled = draft.sending;
      picker.querySelectorAll("button").forEach((node) => { node.disabled = draft.sending; });
      mentions.trigger.disabled = draft.sending;
      const uploading = draft.images.some((item) => item.status === "loading" || item.status === "queued");
      send.disabled = draft.sending || uploading;
      send.textContent = draft.sending ? "发送中…" : uploading ? "图片上传中…" : "发送";
      const signature = draft.images.map(item => `${item.url}:${item.status}`).join("|") + draft.sending;
      if (signature !== previewSignature) {
        previewSignature = signature;
        previews.replaceChildren(...draft.images.map((item, index) => {
        const preview = el("figure", { className: "mm-preview" }, el("img", { src: item.url, alt: `评论图片 ${index + 1}` }));
        const remove = button("", () => {
          if (draft.sending) return;
          draft.images = draft.images.filter((image) => image !== item);
          if (item.url.startsWith("blob:")) URL.revokeObjectURL(item.url);
          draft.key = newKey(); draft.render();
        }, "", "close");
        remove.addEventListener("pointerdown", event => event.preventDefault());
        remove.setAttribute("aria-label", `移除评论图片 ${index + 1}`); remove.disabled = draft.sending; preview.append(remove);
        if (item.status === "loading") preview.append(el("span", { className: "mm-preview-status", role: "status", text: "正在上传…" }));
        if (item.status === "error") preview.append(button("上传失败，点击重试", () => upload(item), "mm-preview-status mm-retry-upload"));
        return preview;
      }));
      }
      resizeEditor(input);
    }
    draft.render = render;
    async function upload(item) {
      if (draft.sending || item.status === "loading") return;
      item.status = "loading"; draft.render();
      const body = new FormData(); body.append("file", item.file);
      try { const result = await api("/api/forum/images", { method: "POST", body }); item.server = result.image; item.status = "done"; }
      catch (e) { item.status = "error"; fail(e.message); }
      draft.render();
    }
    async function addImages(filesToAdd) {
      if (draft.sending) return;
      const pending = [];
      for (const file of filesToAdd) {
        if (draft.images.length >= 4) { fail("每条评论最多添加 4 张图片或表情包"); break; }
        if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) { fail("请选择 JPG、PNG、WebP 或 GIF 图片"); continue; }
        if (file.size > 5 * 1024 * 1024) { fail("每张图片最大 5 MB，请压缩后重试"); continue; }
        const item = { file, url: URL.createObjectURL(file), status: "queued" };
        draft.images.push(item); pending.push(item);
      }
      draft.key = newKey(); draft.render();
      for (const item of pending) if (draft.images.includes(item)) await upload(item);
    }
    files.addEventListener("change", () => { const selected = [...files.files]; files.value = ""; addImages(selected); });
    input.addEventListener("paste", (event) => {
      const images = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith("image/"));
      if (images.length) { event.preventDefault(); addImages(images); }
    });
    const form = el("form", { className: "mm-comment-form", onSubmit: async (event) => {
      event.preventDefault();
      if (draft.sending) return;
      const value = input.value.trim();
      if (!value && !draft.images.length) { fail("写点什么，或发送一张图片、表情包吧"); input.focus(); return; }
      if ([...value].length > 500) { fail("评论最多支持 500 个字"); input.focus(); return; }
      if (draft.images.some((item) => item.status !== "done")) { fail("请等待图片上传完成，或重试上传失败的图片"); return; }
      draft.sending = true; draft.error = ""; picker.open = false; mentions.hide(); draft.render();
      try {
        const data = await api(`/api/murmurs/${post.id}/comments`, { method: "POST", body: JSON.stringify({ content: value, images: draft.images.map((item) => item.server.id), reply_to: draft.replyTo?.id || null, client_key: draft.key }) });
        draft.images.forEach((item) => { if (item.url.startsWith("blob:")) URL.revokeObjectURL(item.url); });
        draft.images = []; draft.content = ""; draft.replyTo = null; draft.key = newKey(); input.value = "";
        draft.onSent(data); toast(data.ai_reply_queued ? "评论已发送，小 K 会稍后回复你，回复后会有通知" : "评论已发送");
      } catch (e) { fail(e.message); }
      finally { draft.sending = false; draft.render(); }
    } }, el("label", { for: inputId, className: "sr-only", text: "评论内容（最多 500 字）" }), replyTarget, input, mentions.panel, previews,
      tools, files, hint, error);
    form.clearReply = () => { if (draft.sending) return; draft.replyTo = null; draft.key = newKey(); draft.error = ""; render(); };
    form.replyTo = (item) => {
      if (draft.sending) return;
      draft.replyTo = { id: item.id, author: item.author }; draft.key = newKey(); draft.error = ""; draft.expanded = true;
      render(); form.scrollIntoView({ block: "nearest", behavior: "instant" }); input.focus({ preventScroll: true });
    };
    form.addEventListener("focusin", () => { draft.expanded = true; render(); });
    form.addEventListener("focusout", (event) => {
      if (!form.contains(event.relatedTarget)) { draft.expanded = false; picker.open = false; mentions.hide(); render(); }
    });
    render(); requestAnimationFrame(() => resizeEditor(input));
    return form;
  }
  function renderEmpty(message) {
    const mine = state.view === "mine";
    const title = message || (mine ? "把今天的第一句话留在这里" : state.author ? "这里还没有留下碎碎念" : "日常的故事，从你开始");
    const empty = window.KflowXiaok?.empty(title, "一句感慨、一张照片，或今天值得记住的小事。") || el("div", { className: "mm-state" }, el("h3", { text: title }));
    empty.append(state.author ? el("a", { href: "/murmurs", className: "mm-secondary", text: "看看大家的碎碎念" }) : button("写一条碎碎念", focusComposer, "mm-primary"));
    feed.replaceChildren(empty);
  }
  function chinaDay(value = new Date()) {
    const parts = new Intl.DateTimeFormat("en", {timeZone:"Asia/Shanghai", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date(value));
    const get = name => parts.find(part => part.type === name).value;
    return `${get("year")}-${get("month")}-${get("day")}`;
  }
  function datePager(data) {
    const host = $("mm-pagination"); host.hidden = state.post || state.view === "reports";
    if (host.hidden) return;
    state.page = data.page || 1;
    const url = new URL(location.href); if (state.page > 1) url.searchParams.set("page", state.page); else url.searchParams.delete("page"); history.replaceState({}, "", url);
    const previous = button("上一页", () => {state.page--; loadFeed(true);}, "mm-secondary"); previous.disabled = state.page <= 1;
    const next = button("下一页", () => {state.page++; loadFeed(true);}, "mm-secondary"); next.disabled = state.page >= data.total_pages;
    host.replaceChildren(previous, el("span", {role:"status", text:`第 ${state.page} / ${data.total_pages || 1} 页 · 共 ${data.total || 0} 条 · 每页 10 条`}), next);
  }
  function initDateFilter() {
    const form = $("mm-date-filter"); form.hidden = !!state.post || state.view === "reports";
    const today = chinaDay(), range = $("mm-range"), custom = $("mm-custom-dates"), toggle = $("mm-custom-toggle");
    const recent = days => {
      const start = new Date(`${today}T12:00:00Z`); start.setUTCDate(start.getUTCDate() - Number(days) + 1);
      return {start:start.toISOString().slice(0,10),end:today};
    };
    state.dateRange = {start:params.get("start") || today,end:params.get("end") || today};
    function restore() { $("mm-start").value = state.dateRange.start; $("mm-end").value = state.dateRange.end; }
    function selectedRange() {
      range.value = [1,3,7,30].find(days => recent(days).start === state.dateRange.start && state.dateRange.end === today) || "custom";
    }
    function expanded(open) {
      custom.hidden = !open; toggle.setAttribute("aria-expanded",String(open));
      toggle.textContent = open ? "收起日期" : "自定义";
    }
    restore(); selectedRange();
    $("mm-unread").checked = !!state.profile && params.get("unread") === "1";
    $("mm-unread").disabled = !state.profile;
    $("mm-unread").title = state.profile ? "查看你发布或参与的碎碎念中的新回复" : "登录后可查看新回复";
    function sync() {
      const unread = $("mm-unread").checked;
      $("mm-start").disabled = $("mm-end").disabled = range.disabled = toggle.disabled = unread;
      if (unread) expanded(false);
      const summary = $("mm-filter-summary");
      summary.hidden = !unread && range.value !== "custom";
      summary.textContent = unread ? "你发布或参与的碎碎念 · 新回复不限日期" : `${state.dateRange.start} 至 ${state.dateRange.end}`;
    }
    sync();
    function apply(event) {
      event?.preventDefault();
      if (!$("mm-unread").checked && (!$("mm-start").value || !$("mm-end").value || $("mm-start").value > $("mm-end").value)) {toast("请选择有效的开始与结束日期");return;}
      if (!$("mm-unread").checked) state.dateRange = {start:$("mm-start").value,end:$("mm-end").value};
      state.page = 1;
      const url = new URL(location.href); url.searchParams.delete("page");
      if ($("mm-unread").checked) {url.searchParams.set("unread","1");url.searchParams.delete("start");url.searchParams.delete("end");}
      else {url.searchParams.delete("unread");url.searchParams.set("start",state.dateRange.start);url.searchParams.set("end",state.dateRange.end);}
      selectedRange(); expanded(false); sync();
      history.replaceState({},"",url); loadFeed(true);
    }
    form.addEventListener("submit",apply);
    $("mm-unread").addEventListener("change",()=>{restore();sync();apply();});
    range.addEventListener("change",()=>{
      if (range.value === "custom") {restore();expanded(true);$("mm-start").focus();return;}
      const value = recent(range.value); $("mm-start").value = value.start; $("mm-end").value = value.end; apply();
    });
    toggle.addEventListener("click",()=>{restore();expanded(custom.hidden);if(!custom.hidden)$("mm-start").focus();else selectedRange();});
    $("mm-custom-cancel").addEventListener("click",()=>{restore();selectedRange();expanded(false);});
  }
  async function loadFeed(reset = false) {
    if (state.loading && !reset) return;
    const epoch = reset ? ++state.epoch : state.epoch;
    state.loading = true; feed.setAttribute("aria-busy", "true"); $("mm-more").disabled = true;
    if (reset) { state.cursor = null; feed.replaceChildren(el("div", { className: "mm-state", role: "status", text: "正在加载碎碎念…" })); $("mm-more").hidden = true; $("mm-feed-end").hidden = true; }
    try {
      if (state.view === "mine" && !state.profile) {
        feed.replaceChildren(el("div", { className: "mm-state" }, icon("user"), el("h3", { text: "登录，看看自己的日常记录" }), el("p", { text: "发布过的碎碎念都会留在这里。" }), el("a", { href: loginUrl(), className: "mm-primary", text: "去登录" })));
        return;
      }
      const query = new URLSearchParams();
      if (!state.post && state.view !== "reports") {
        query.set("page",state.page);
        if ($("mm-unread").checked) query.set("unread","1");
        else {query.set("start",state.dateRange.start);query.set("end",state.dateRange.end);}
      } else if (state.cursor) query.set("before", state.cursor);
      if (state.view === "mine") query.set("scope", "mine");
      if (state.author) query.set("author", state.author);
      let url = `/api/murmurs?${query}`;
      if (state.post) url = `/api/murmurs/${state.post}`;
      if (state.view === "reports") {
        query.set("status", $("mm-report-status").value);
        url = state.moderation === "appeals" ? `/api/admin/murmurs/appeals?${query}` : `/api/admin/murmurs/reports?${query}`;
      }
      const data = await api(url);
      if (epoch !== state.epoch) return;
      const items = data.item ? [data.item] : data.items;
      if (data.item?.is_deleted) {
        $("mm-feed-title").textContent = "已下线碎碎念";
        $("mm-feed-subtitle").replaceChildren(el("a", { href: "/murmurs?view=reports", text: "返回举报管理" }));
      }
      if (reset || (!state.post && state.view !== "reports")) feed.replaceChildren();
      let currentDay = "";
      if (!state.post && state.view !== "reports") {
        for (const item of items) { const day=chinaDay(item.created_at); if(day!==currentDay){feed.append(el("h3",{className:"mm-day-divider",text:day}));currentDay=day;} feed.append(postCard(item)); }
      } else items.forEach((item) => feed.append(state.view === "reports" ? (state.moderation === "appeals" ? appealCard(item) : reportCard(item)) : postCard(item)));
      if (state.post && !params.get("comment")) requestAnimationFrame(() => $(`murmur-${state.post}`)?.scrollIntoView({ block: "start", behavior: "instant" }));
      datePager(data);
      state.cursor = data.next_cursor || null;
      $("mm-more").textContent = state.view === "reports" ? (state.moderation === "appeals" ? "查看更多申诉" : "查看更多举报") : "再看看";
      $("mm-more").hidden = state.view !== "reports" || !state.cursor; $("mm-feed-end").hidden = !items.length || !!state.cursor || !!state.post || state.view === "reports";
      if (!feed.children.length) {
        if (state.view === "reports") feed.append(el("div", { className: "mm-state", text: state.moderation === "appeals" ? "当前筛选下没有申诉记录。" : "当前筛选下没有举报记录。" }));
        else renderEmpty();
      }
    } catch (e) {
      if (epoch !== state.epoch) return;
      const retry = button("重试", () => loadFeed(reset), "mm-secondary");
      if (reset) feed.replaceChildren(el("div", { className: "mm-state" }, el("h3", { text: state.post ? "暂时看不到这条碎碎念" : "暂时没能加载出来" }), el("p", { text: e.message }), retry, state.post ? el("a", { href: "/murmurs", className: "mm-text-button", text: "回到全部碎碎念" }) : null));
      else { toast(e.message); $("mm-more").hidden = false; $("mm-more").textContent = "加载失败，点击重试"; }
    } finally { if (epoch === state.epoch) { state.loading = false; feed.setAttribute("aria-busy", "false"); $("mm-more").disabled = false; } }
  }
  const REPORT_REASONS = { spam: "垃圾广告", abuse: "不友善内容", copyright: "版权问题", other: "其他问题" };
  function timeText(value) { return value ? new Date(value).toLocaleString("zh-CN") : "—"; }
  function modHeader(kind, target, extra, statusText, statusClass) {
    const badges = el("div", { className: "mm-mod-badges" },
      el("span", { className: `mm-mod-kind${kind === "申诉" ? " is-appeal" : ""}` }, icon(kind === "申诉" ? "shield" : "flag"), kind),
      el("span", { className: "mm-mod-chip", text: target }));
    if (extra) badges.append(el("span", { className: "mm-mod-chip", text: extra }));
    return el("header", { className: "mm-mod-head" }, badges, el("span", { className: `mm-mod-status ${statusClass}`, text: statusText }));
  }
  function modMeta(iconName, label, value) {
    return el("span", { className: "mm-mod-meta-item" }, icon(iconName), el("span", { text: label }), el("strong", { text: value || "—" }));
  }
  function modFact(label, value) {
    return el("div", { className: "mm-mod-fact" }, el("span", { text: label }), el("strong", { text: value || "—" }));
  }
  function modDetail(label, value, className = "") {
    return el("div", { className: `mm-mod-detail${className ? ` ${className}` : ""}` },
      el("span", { className: "mm-mod-detail-label", text: label }), el("p", { text: value }));
  }
  function moderationReturnHref() {
    const query = new URLSearchParams({ view: "reports" });
    if (state.from === "appeals") query.set("mod", "appeals");
    const status = params.get("status") || "";
    if (/^(pending|resolved|rejected|accepted|all)$/.test(status)) query.set("status", status);
    return `/murmurs?${query}`;
  }
  function moderationReturnLabel() { return state.from === "appeals" ? "返回申诉管理" : "返回举报管理"; }
  function modPostLink(item) {
    const comment = Boolean(item.comment_id) || item.target_type === "comment";
    const label = comment ? "查看所在帖子" : "查看原帖";
    const query = new URLSearchParams({ post: item.post_id, from: state.moderation });
    if (state.view === "reports" && $("mm-report-status").value) query.set("status", $("mm-report-status").value);
    return el("a", {
      className: "mm-mod-btn is-view",
      href: `/murmurs?${query}`,
      target: "_blank",
      rel: "noopener",
      title: "在新标签页中打开原帖",
      "aria-label": `${label}（新标签页）`,
    }, icon("external"), label);
  }
  function openReportReview(item, remove) {
    const hint = remove
      ? (item.comment_id ? "确认后评论将立即下线，作者会收到通知，并可在 7 天内提出申诉。" : "确认后碎碎念将立即下线，作者会收到通知，并可在 7 天内提出申诉。")
      : "驳回后举报人会收到处理结果，内容保持可见。";
    const note = el("textarea", { rows: "3", maxlength: "500", id: "mm-review-note", placeholder: "处理备注（选填，会同步给相关用户）" });
    const error = el("p", { className: "mm-error", role: "alert", hidden: true });
    const send = button(remove ? "确认下线" : "确认驳回", async () => {
      send.disabled = true;
      try {
        await api(`/api/admin/murmurs/reports/${item.id}/review`, { method: "POST", body: JSON.stringify({ decision: remove ? "resolved" : "rejected", remove, note: note.value }) });
        closeDialog(); toast(remove ? "内容已下线，作者可在 7 天内申诉" : "已驳回举报");
        await loadFeed(true); refreshModerationBadge();
      } catch (e) { error.textContent = e.message; error.hidden = false; }
      finally { send.disabled = false; }
    }, remove ? "mm-primary mm-mod-danger" : "mm-primary");
    openDialog(remove ? "下线被举报内容" : "驳回举报",
      el("p", { className: "mm-mod-dialog-hint", text: hint }),
      el("label", { for: note.id, text: "处理备注" }), note, error,
      el("div", { className: "mm-dialog-actions" }, button("取消", closeDialog), send));
  }
  function openAppealReview(item, decision) {
    const accepted = decision === "accepted";
    const note = el("textarea", { rows: "3", maxlength: "500", id: "mm-appeal-review-note", placeholder: "复核说明（选填，会同步给申诉人）" });
    const error = el("p", { className: "mm-error", role: "alert", hidden: true });
    const send = button(accepted ? "确认恢复" : "确认维持删除", async () => {
      send.disabled = true;
      try {
        await api(`/api/admin/murmurs/appeals/${item.id}/review`, { method: "POST", body: JSON.stringify({ decision, note: note.value }) });
        closeDialog(); toast(accepted ? "申诉通过，内容已恢复" : "已维持删除");
        await loadFeed(true); refreshModerationBadge();
      } catch (e) { error.textContent = e.message; error.hidden = false; }
      finally { send.disabled = false; }
    }, accepted ? "mm-primary mm-mod-restore" : "mm-primary mm-mod-danger");
    openDialog(accepted ? "通过申诉并恢复内容" : "维持删除",
      el("p", { className: "mm-mod-dialog-hint", text: accepted ? "确认后内容会恢复可见，作者会收到通知。" : "确认后维持删除，申诉人会收到复核结果。" }),
      el("label", { for: note.id, text: "复核说明" }), note, error,
      el("div", { className: "mm-dialog-actions" }, button("取消", closeDialog), send));
  }
  function reportCard(item) {
    const pending = item.status === "pending";
    const removed = item.removed && item.status === "resolved";
    const statusText = pending ? "待处理" : item.status === "rejected" ? "已驳回" : removed ? "已下线" : "已处理";
    const statusClass = pending ? "is-pending" : removed ? "is-removed" : "is-closed";
    const card = el("article", { className: `mm-post mm-report mm-mod-card ${statusClass}` });
    card.append(modHeader("举报", item.comment_id ? "评论" : "碎碎念", REPORT_REASONS[item.reason] || item.reason, statusText, statusClass));
    card.append(el("div", { className: "mm-mod-target" },
      el("span", { className: "mm-mod-target-label", text: "被举报内容" }),
      el("a", { href: `/forum/user/${encodeURIComponent(item.author_username)}`, text: item.author_username })));
    card.append(el("blockquote", { className: "mm-mod-quote", text: item.content || "（图片分享）" }));
    if (item.images?.length) card.append(imageGrid(item.images, item.author_username));
    const meta = el("div", { className: "mm-mod-meta" },
      modMeta("flag", "举报人", item.reporter_username),
      modMeta("clock", "提交于", timeText(item.created_at)));
    if (item.appeal_status === "pending") meta.append(el("span", { className: "mm-mod-chip is-appeal", text: "作者已申诉" }));
    card.append(meta);
    if (item.details) card.append(modDetail("补充说明", item.details));
    if (pending) {
      card.append(el("div", { className: "mm-mod-actions" },
        el("p", { className: "mm-mod-hint", text: item.comment_id ? "下线评论后，作者会收到通知，并可在 7 天内申诉。" : "下线后作者会收到通知，并可在 7 天内申诉。" }),
        el("div", { className: "mm-mod-buttons" },
          modPostLink(item),
          button("驳回举报", () => openReportReview(item, false), "mm-mod-btn is-neutral", "close"),
          button("下线内容", () => openReportReview(item, true), "mm-mod-btn is-danger", "trash"))));
    } else {
      const appealText = { pending: "作者已申诉，待复核", accepted: "申诉通过，内容已恢复", rejected: "申诉未通过，维持删除" }[item.appeal_status] || "";
      const resultClass = item.status === "rejected" ? " is-rejected" : removed ? " is-removed" : "";
      card.append(el("div", { className: `mm-mod-result${resultClass}` },
        el("div", { className: "mm-mod-result-head" }, icon(item.status === "rejected" ? "close" : removed ? "trash" : "check"), el("strong", { text: statusText })),
        el("div", { className: "mm-mod-meta" },
          modMeta("user", "处理人", item.reviewer_username),
          item.reviewed_at ? modMeta("clock", "处理于", timeText(item.reviewed_at)) : null),
        item.review_note ? el("p", { className: "mm-mod-result-note", text: `备注：${item.review_note}` }) : null,
        appealText ? el("p", { className: "mm-mod-result-note", text: appealText }) : null,
        removed && item.appeal_deadline ? el("p", { className: "mm-mod-result-note", text: `申诉期至 ${timeText(item.appeal_deadline)}` }) : null));
      card.append(el("div", { className: "mm-mod-foot" }, modPostLink(item)));
    }
    return card;
  }
  function appealCard(item) {
    const pending = item.status === "pending";
    const statusText = pending ? "待复核" : item.status === "accepted" ? "已恢复内容" : "维持删除";
    const statusClass = pending ? "is-pending" : item.status === "accepted" ? "is-restored" : "is-removed";
    const card = el("article", { className: `mm-post mm-report mm-mod-card ${statusClass}` });
    card.append(modHeader("申诉", item.target_type === "comment" ? "评论" : "碎碎念", "", statusText, statusClass));
    card.append(el("div", { className: "mm-mod-target" },
      el("span", { className: "mm-mod-target-label", text: "被删除内容" }),
      el("a", { href: `/forum/user/${encodeURIComponent(item.author_username)}`, text: item.author_username })));
    card.append(el("blockquote", { className: "mm-mod-quote", text: item.content || "（图片分享）" }));
    if (item.images?.length) card.append(imageGrid(item.images, item.author_username));
    card.append(el("div", { className: "mm-mod-facts" },
      modFact("申诉人", item.appellant_username),
      modFact("提交时间", timeText(item.created_at)),
      modFact("删除人", item.deleted_by),
      modFact("删除时间", timeText(item.deleted_at)),
      modFact("申诉截止", timeText(item.appeal_deadline))));
    card.append(modDetail("申诉理由", item.reason, "is-reason"));
    if (item.deletion_reason) card.append(modDetail("删除理由", item.deletion_reason));
    if (pending) {
      card.append(el("div", { className: "mm-mod-actions" },
        el("p", { className: "mm-mod-hint", text: "通过后内容会恢复，作者会收到通知；维持删除会通知申诉人。" }),
        el("div", { className: "mm-mod-buttons" },
          modPostLink(item),
          button("维持删除", () => openAppealReview(item, "rejected"), "mm-mod-btn is-neutral", "close"),
          button("通过申诉，恢复内容", () => openAppealReview(item, "accepted"), "mm-mod-btn is-restore", "check"))));
    } else {
      card.append(el("div", { className: `mm-mod-result${item.status === "rejected" ? " is-rejected" : ""}` },
        el("div", { className: "mm-mod-result-head" }, icon(item.status === "accepted" ? "check" : "close"), el("strong", { text: statusText })),
        el("div", { className: "mm-mod-meta" },
          modMeta("user", "复核人", item.reviewer_username),
          item.reviewed_at ? modMeta("clock", "复核于", timeText(item.reviewed_at)) : null),
        item.review_note ? el("p", { className: "mm-mod-result-note", text: `备注：${item.review_note}` }) : null));
      card.append(el("div", { className: "mm-mod-foot" }, modPostLink(item)));
    }
    return card;
  }
  async function openAppealDialog(target) {
    if (!requireLogin()) return;
    const body = el("div", { text: "正在加载…" });
    openDialog("申诉已删除的内容", body);
    try {
      const data = await api(`/api/murmurs/appeals/context?target=${encodeURIComponent(target)}`);
      body.replaceChildren();
      body.append(el("p", { className: "mm-report-reason", text: data.type === "comment" ? "评论申诉" : "碎碎念申诉" }),
        el("p", { className: "mm-post-text", text: data.content || "（图片分享）" }));
      if (data.images?.length) body.append(imageGrid(data.images, data.author.display_name));
      body.append(el("p", { className: "mm-report-details", text: `删除时间 ${data.deleted_at ? new Date(data.deleted_at).toLocaleString("zh-CN") : "—"}${data.deletion_reason ? `\n删除理由：${data.deletion_reason}` : ""}${data.appeal_deadline ? `\n申诉截止 ${new Date(data.appeal_deadline).toLocaleString("zh-CN")}` : ""}` }));
      if (data.appeal) {
        const status = { pending: "已提交，等待复核", accepted: "已通过，内容已恢复", rejected: "未通过，维持删除" }[data.appeal.status] || "已处理";
        body.append(el("p", { className: "mm-report-details", text: `申诉状态：${status}${data.appeal.review_note ? `\n复核备注：${data.appeal.review_note}` : ""}` }));
        return;
      }
      if (!data.can_appeal) { body.append(el("p", { className: "mm-report-details", text: data.message || "当前不可申诉" })); return; }
      const reason = el("textarea", { rows: "4", maxlength: "1000", id: "mm-appeal-reason", placeholder: "说明情况，便于管理员复核" });
      const error = el("p", { className: "mm-error", role: "alert", hidden: true });
      const send = button("提交申诉", async () => {
        send.disabled = true;
        try { await api("/api/murmurs/appeals", { method: "POST", body: JSON.stringify({ target: data.target, reason: reason.value }) }); toast("申诉已提交，等待管理员复核"); closeDialog(); }
        catch (e) { error.textContent = e.message; error.hidden = false; }
        finally { send.disabled = false; }
      }, "mm-primary");
      body.append(el("label", { for: reason.id, text: "申诉理由" }), reason, error, el("div", { className: "mm-dialog-actions" }, button("取消", closeDialog), send));
    } catch (e) { body.textContent = e.message; }
  }
  async function showBlocks() {
    if (!requireLogin()) return;
    const body = el("div", { text: "正在加载…" });
    openDialog("屏蔽管理", body);
    try {
      const data = await api("/api/murmurs/blocks"); body.replaceChildren();
      if (!data.items.length) body.append(el("p", { text: "你还没有屏蔽任何人。" }));
      data.items.forEach((user) => {
        const undo = button("取消屏蔽", async () => {
          undo.disabled = true;
          try { await api("/api/murmurs/blocks", { method: "DELETE", body: JSON.stringify({ username: user.username }) }); row.remove(); toast("已取消屏蔽"); if (!body.children.length) body.append(el("p", { text: "你还没有屏蔽任何人。" })); await loadFeed(true); }
          catch (e) { toast(e.message); } finally { undo.disabled = false; }
        });
        const row = el("div", { className: "mm-block-row" }, avatar(user), el("span", { text: user.display_name }), undo); body.append(row);
      });
    } catch (e) { body.textContent = e.message; }
  }
  function syncStatusOptions() {
    const options = state.moderation === "appeals"
      ? [["pending", "待复核"], ["accepted", "已恢复"], ["rejected", "已维持删除"], ["all", "全部"]]
      : [["pending", "待处理"], ["resolved", "已下线"], ["rejected", "已驳回"], ["all", "全部"]];
    $("mm-report-status").replaceChildren(...options.map(([value, label]) => el("option", { value, text: label })));
  }
  function setPageContext() {
    document.querySelectorAll("[data-mm-view]").forEach((node) => {
      if (node.dataset.mmView === state.view && !state.post && !state.author) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
    $("mm-moderation").hidden = !state.moderator;
    const returnBar = $("mm-post-return");
    if (state.post && state.from) {
      returnBar.replaceChildren(
        el("a", { className: "mm-mod-btn is-view", href: moderationReturnHref() }, icon("back"), moderationReturnLabel()),
        el("span", { className: "mm-post-return-note", text: state.from === "appeals" ? "正在查看申诉对应的原帖" : "正在查看举报对应的原帖" }));
      returnBar.hidden = false;
    } else {
      returnBar.replaceChildren();
      returnBar.hidden = true;
    }
    if (state.view === "reports") {
      $("mm-composer").hidden = true; $("mm-report-filter").hidden = !state.moderator;
      const appeals = state.moderation === "appeals";
      $("mm-feed-title").textContent = appeals ? "碎碎念申诉管理" : "碎碎念举报管理";
      $("mm-feed-subtitle").textContent = appeals ? "复核作者申诉，决定恢复或维持删除" : "核实内容，记录处理结果";
    } else if (state.post) {
      $("mm-feed-title").textContent = "这一条碎碎念";
      $("mm-feed-subtitle").replaceChildren(el("a", { href: "/murmurs", text: "回到全部碎碎念" }));
    } else if (state.view === "mine") { $("mm-feed-title").textContent = "我的碎碎念"; $("mm-feed-subtitle").textContent = "你留下的每一个日常瞬间"; }
    else if (state.author) { $("mm-feed-title").textContent = `${state.author}的碎碎念`; $("mm-feed-subtitle").replaceChildren(el("a", { href: "/murmurs", text: "看看大家的碎碎念" })); }
    if (state.profile) {
      $("mm-my-avatar").replaceWith(Object.assign(avatar(state.profile, false), { id: "mm-my-avatar" }));
      $("mm-identity").textContent = state.profile.display_name;
      $("mm-social").hidden = false;
      $("mm-social").replaceChildren(el("span", { text: "我的圈子" }), window.KflowSocial.stats(state.profile.username, state.profile.username, toast));
    } else $("mm-identity").replaceChildren(el("a", { href: loginUrl(), text: "登录，加入这场闲聊" }));
  }
  async function refreshModerationBadge() {
    if (!state.moderator) return;
    try {
      const data = await api("/api/admin/murmurs/pending-count");
      const dot = $("mm-moderation-dot");
      if (!dot) return;
      const total = Math.max(0, Number(data.total) || 0);
      dot.hidden = total === 0;
      const link = $("mm-moderation");
      if (total) link.title = `${data.reports || 0} 条待处理举报，${data.appeals || 0} 条待处理申诉`;
      else link.removeAttribute("title");
      window.dispatchEvent(new CustomEvent("kflow:moderation-changed", { detail: { reports: Number(data.reports) || 0, appeals: Number(data.appeals) || 0, total } }));
    } catch {
      /* 权限不足或网络异常时保持静默 */
    }
  }
  async function init() {
    document.querySelectorAll("[data-mm-icon]").forEach((node) => node.replaceChildren(icon(node.dataset.mmIcon)));
    const date = new Date();
    $("mm-date").textContent = date.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
    $("mm-date").dateTime = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    content.addEventListener("input", draftChanged);
    const postEmojis = emojiPicker(content, 1000, draftChanged, () => state.publishing, showPublishError);
    const mentions = mentionPicker(content, draftChanged, () => state.publishing, 1000, showPublishError);
    $("mm-counter").before(postEmojis, mentions.trigger);
    content.after(mentions.panel);
    $("mm-publish-form").addEventListener("submit", () => { postEmojis.open = false; mentions.hide(); });
    $("mm-expand-editor").addEventListener("click", () => {
      const expanded = $("mm-composer").classList.toggle("mm-writing-expanded");
      $("mm-expand-editor").setAttribute("aria-expanded", String(expanded));
      $("mm-expand-editor").textContent = expanded ? "收起编辑" : "展开编辑"; resizeEditor(content);
    });
    let editorWidth = 0;
    new ResizeObserver(([entry]) => {
      if (entry.contentRect.width === editorWidth) return;
      editorWidth = entry.contentRect.width;
      resizeEditor(content); document.querySelectorAll(".mm-comment-input").forEach(resizeEditor);
    }).observe(document.querySelector(".mm-main"));
    window.addEventListener("resize", () => { resizeEditor(content); document.querySelectorAll(".mm-comment-input").forEach(resizeEditor); });
    content.addEventListener("paste", (event) => { const images = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith("image/")); if (images.length) { event.preventDefault(); addImages(images); } });
    $("mm-publish-form").addEventListener("submit", publish);
    $("mm-add-images").addEventListener("click", () => { if (requireLogin()) $("mm-files").click(); });
    $("mm-files").addEventListener("change", (event) => { const files = [...event.target.files]; event.target.value = ""; addImages(files); });
    $("mm-write").addEventListener("click", focusComposer);
    $("mm-refresh").addEventListener("click", () => loadFeed(true));
    $("mm-more").addEventListener("click", () => loadFeed(false));
    $("mm-blocks").addEventListener("click", showBlocks);
    $("mm-mobile-blocks").addEventListener("click", showBlocks);
    $("mm-report-status").addEventListener("change", () => loadFeed(true));
    $("mm-moderation-kind").addEventListener("change", () => { state.moderation = $("mm-moderation-kind").value; syncStatusOptions(); setPageContext(); loadFeed(true); });
    $("mm-dialog-close").addEventListener("click", closeDialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog && event.clientX && (event.clientX < dialog.getBoundingClientRect().left || event.clientX > dialog.getBoundingClientRect().right || event.clientY < dialog.getBoundingClientRect().top || event.clientY > dialog.getBoundingClientRect().bottom)) closeDialog(); });
    document.querySelector(".mm-lightbox-close").addEventListener("click", () => $("mm-lightbox").close());
    document.querySelector(".mm-lightbox-prev").addEventListener("click", () => stepImage(-1));
    document.querySelector(".mm-lightbox-next").addEventListener("click", () => stepImage(1));
    $("mm-lightbox").addEventListener("keydown", (event) => { if (event.key === "ArrowLeft") stepImage(-1); if (event.key === "ArrowRight") stepImage(1); });
    $("mm-lightbox").addEventListener("close", () => { lightboxState = null; $("mm-lightbox-image").removeAttribute("src"); });
    document.querySelectorAll("[data-mm-prompt]").forEach((node) => node.addEventListener("click", () => { if (state.publishing) return; if (!content.value.trim()) { content.value = node.dataset.mmPrompt; draftChanged(); } focusComposer(); }));
    window.addEventListener("pagehide", saveDraft);
    try { const data = await api("/api/murmurs/session"); state.profile = data.profile; state.moderator = data.can_moderate; }
    catch (e) { toast(e.message); }
    $("mm-moderation-kind").value = state.moderation;
    syncStatusOptions();
    if (state.view === "reports") {
      const requestedStatus = params.get("status") || "";
      if ([...$("mm-report-status").options].some((option) => option.value === requestedStatus)) $("mm-report-status").value = requestedStatus;
    }
    setPageContext(); initDateFilter(); restoreDraft(); resizeEditor(content);
    if (state.moderator) {
      refreshModerationBadge();
      setInterval(refreshModerationBadge, 60000);
    }
    await loadFeed(true);
    if (state.appeal) openAppealDialog(state.appeal);
  }
  init();
})();
