/* Plain text throughout: user content is only assigned with textContent. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const paths = {
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
  const state = { profile: null, moderator: false, images: [], publishing: false, loading: false, cursor: null, epoch: 0, key: newKey(),
    view: params.get("view") === "reports" ? "reports" : params.get("scope") === "mine" ? "mine" : "all", author: params.get("author") || "", post: /^\d+$/.test(params.get("post") || "") ? params.get("post") : "" };
  const content = $("mm-content");
  const feed = $("mm-feed");
  const dialog = $("mm-dialog");
  let toastTimer, draftTimer;
  function newKey() { return globalThis.crypto?.randomUUID?.() || `m-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
  function toast(message) {
    $("mm-toast").textContent = message;
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
      toast("已发布，今天又留下了一点记录");
      if (state.view === "reports" || state.post || (state.author && state.author !== state.profile.username)) {
        location.href = `/murmurs?post=${result.item.id}`;
      } else await loadFeed(true);
    } catch (e) { showPublishError(e.message); }
    finally {
      state.publishing = false; content.disabled = false; $("mm-add-images").disabled = false;
      $("mm-publish").replaceChildren("发布", icon("arrow-up-right")); renderPreviews();
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
    if (post.can_delete) actions.append(button(post.is_own ? "删除这条碎碎念" : "管理：删除这条碎碎念", () => confirmAction("删除碎碎念？", "删除后，这条内容将不再公开显示。", "确认删除", async () => {
      await api(`/api/murmurs/${post.id}`, { method: "DELETE" }); card.remove(); toast("碎碎念已删除");
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
    try { await navigator.clipboard.writeText(url); toast("链接已复制"); }
    catch {
      const input = el("input", { value: url, readonly: "", className: "mm-copy-input", "aria-label": "碎碎念分享链接" });
      openDialog("分享这条碎碎念", el("p", { text: "复制下面的链接，即可分享给朋友。" }), input); input.select();
    }
  }
  function postCard(post) {
    const card = el("article", { className: "mm-post", id: `murmur-${post.id}`, "aria-label": `${post.author.display_name}的碎碎念` });
    const more = button("", () => postMenu(post, card), "mm-icon-button", "more"); more.setAttribute("aria-label", "更多操作");
    card.append(el("div", { className: "mm-post-header" }, avatar(post.author), el("div", { className: "mm-author-meta" }, el("a", { href: `/forum/user/${encodeURIComponent(post.author.username)}`, className: "mm-author-name", text: post.author.display_name }), timestamp(post.created_at, `/murmurs?post=${post.id}`)), more));
    if (post.content) {
      const long = post.content.length > 260 || post.content.split("\n").length > 6;
      const body = el("p", { className: `mm-post-text${long ? " mm-collapsed" : ""}`, text: post.content, id: `mm-text-${post.id}` });
      card.append(body);
      if (long) {
        const expand = button("展开全文", () => { const collapsed = body.classList.toggle("mm-collapsed"); expand.textContent = collapsed ? "展开全文" : "收起"; expand.setAttribute("aria-expanded", String(!collapsed)); }, "mm-text-button mm-expand");
        expand.setAttribute("aria-expanded", "false"); expand.setAttribute("aria-controls", body.id); card.append(expand);
      }
    }
    if (post.images.length) card.append(imageGrid(post.images, post.author.display_name));
    const likes = button("", async () => {
      if (!requireLogin()) return;
      likes.disabled = true;
      try {
        const data = await api(`/api/murmurs/${post.id}/like`, { method: "POST", body: JSON.stringify({ liked: !post.liked }) });
        post.liked = data.liked; post.like_count = data.like_count; updateLikes();
      } catch (e) { toast(e.message); }
      finally { likes.disabled = false; }
    }, "mm-action");
    function updateLikes() { likes.replaceChildren(icon("heart"), `${post.like_count || ""}${post.like_count ? " 个赞" : "点赞"}`); likes.setAttribute("aria-pressed", String(post.liked)); likes.setAttribute("aria-label", `${post.liked ? "取消点赞" : "点赞"}，${post.like_count} 个赞`); }
    updateLikes();
    const comments = el("div", { className: "mm-comments", id: `mm-comments-${post.id}`, hidden: true });
    let opened = false;
    const commentButton = button("", () => {
      comments.hidden = !comments.hidden; commentButton.setAttribute("aria-expanded", String(!comments.hidden));
      if (!comments.hidden && !opened) { opened = true; renderComments(post, comments, updateComments); }
    }, "mm-action", "comment");
    commentButton.setAttribute("aria-expanded", "false"); commentButton.setAttribute("aria-controls", comments.id);
    function updateComments(count = post.comment_count) { post.comment_count = count; commentButton.replaceChildren(icon("comment"), count ? `${count} 条评论` : "评论"); }
    updateComments();
    const share = button("分享", () => copyPost(post), "mm-action mm-share", "link");
    card.append(el("div", { className: "mm-post-footer" }, likes, commentButton, share), comments);
    if (state.post) { comments.hidden = false; commentButton.setAttribute("aria-expanded", "true"); opened = true; renderComments(post, comments, updateComments); }
    return card;
  }
  function renderComments(post, host, updateCount) {
    const list = el("div");
    const status = el("p", { className: "mm-comment-hint", role: "status", text: "正在加载评论…" });
    const more = button("查看更多评论", () => load(false), "mm-text-button"); more.hidden = true;
    let next = null, loading = false, requestKey = newKey();
    host.replaceChildren(list, status, more);
    async function load(reset) {
      if (loading) return;
      loading = true; more.disabled = true;
      if (reset) { list.replaceChildren(); next = null; }
      try {
        const data = await api(`/api/murmurs/${post.id}/comments${next ? `?after=${next}` : ""}`);
        for (const item of data.items) if (!list.querySelector(`[data-comment-id="${item.id}"]`)) list.append(commentCard(item));
        next = data.next_cursor; more.hidden = !next; status.hidden = true;
        if (!list.children.length) { status.textContent = "还没有评论，来接一句吧。"; status.hidden = false; }
      } catch (e) { status.textContent = e.message; status.hidden = false; more.textContent = "重试加载评论"; more.hidden = false; }
      finally { loading = false; more.disabled = false; }
    }
    function commentCard(item) {
      const row = el("div", { className: "mm-comment", "data-comment-id": item.id });
      const menu = button("", () => {
        if (item.can_delete) confirmAction("删除这条评论？", "删除后，这条评论将不再显示。", "确认删除", async () => {
          const data = await api(`/api/murmurs/comments/${item.id}`, { method: "DELETE" }); row.remove(); updateCount(data.comment_count); toast("评论已删除");
        });
        else openReport(post, item);
      }, "mm-icon-button", "more"); menu.setAttribute("aria-label", item.can_delete ? "删除评论" : "举报评论");
      row.append(avatar(item.author), el("div", { className: "mm-comment-main" }, el("div", { className: "mm-comment-meta" }, el("a", { href: `/forum/user/${encodeURIComponent(item.author.username)}`, text: item.author.display_name }), timestamp(item.created_at)), el("p", { text: item.content })), menu);
      return row;
    }
    if (state.profile) {
      const input = el("textarea", { rows: "1", className: "mm-comment-input", placeholder: "说两句……", "aria-label": "评论内容（最多500字）" });
      const error = el("p", { className: "mm-error", role: "alert", hidden: true });
      input.addEventListener("input", () => { requestKey = newKey(); });
      const send = el("button", { type: "submit", className: "mm-primary", text: "发送" });
      const form = el("form", { className: "mm-comment-form", onSubmit: async (event) => {
        event.preventDefault();
        if (!input.value.trim()) { error.textContent = "写点什么再发送吧"; error.hidden = false; input.focus(); return; }
        if ([...input.value.trim()].length > 500) { error.textContent = "评论最多支持 500 个字"; error.hidden = false; return; }
        send.disabled = true; input.disabled = true; error.hidden = true;
        try {
          const data = await api(`/api/murmurs/${post.id}/comments`, { method: "POST", body: JSON.stringify({ content: input.value.trim(), client_key: requestKey }) });
          if (!list.querySelector(`[data-comment-id="${data.item.id}"]`)) list.append(commentCard(data.item));
          input.value = ""; requestKey = newKey(); status.hidden = true; updateCount(data.comment_count); toast("评论已发送");
        } catch (e) { error.hidden = false; error.textContent = e.message; }
        finally { send.disabled = false; input.disabled = false; }
      } }, input, send);
      host.append(form, error);
    } else host.append(button("登录后，来说两句", requireLogin, "mm-text-button"));
    load(true);
  }
  function renderEmpty(message) {
    const mine = state.view === "mine";
    feed.replaceChildren(el("div", { className: "mm-state" }, icon("comment"), el("h3", { text: message || (mine ? "把今天的第一句话留在这里" : state.author ? "这里还没有留下碎碎念" : "日常的故事，从你开始") }),
      el("p", { text: "一句感慨、一张照片，或今天值得记住的小事。" }), state.author ? el("a", { href: "/murmurs", className: "mm-secondary", text: "看看大家的碎碎念" }) : button("写一条碎碎念", focusComposer, "mm-primary")));
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
      if (state.cursor) query.set("before", state.cursor);
      if (state.view === "mine") query.set("scope", "mine");
      if (state.author) query.set("author", state.author);
      let url = `/api/murmurs?${query}`;
      if (state.post) url = `/api/murmurs/${state.post}`;
      if (state.view === "reports") { query.set("status", $("mm-report-status").value); url = `/api/admin/murmurs/reports?${query}`; }
      const data = await api(url);
      if (epoch !== state.epoch) return;
      const items = data.item ? [data.item] : data.items;
      if (reset) feed.replaceChildren();
      items.forEach((item) => feed.append(state.view === "reports" ? reportCard(item) : postCard(item)));
      state.cursor = data.next_cursor || null;
      $("mm-more").textContent = state.view === "reports" ? "查看更多举报" : "再看看";
      $("mm-more").hidden = !state.cursor; $("mm-feed-end").hidden = !items.length || !!state.cursor || !!state.post || state.view === "reports";
      if (!feed.children.length) {
        if (state.view === "reports") feed.append(el("div", { className: "mm-state", text: "当前筛选下没有举报记录。" }));
        else renderEmpty();
      }
    } catch (e) {
      if (epoch !== state.epoch) return;
      const retry = button("重试", () => loadFeed(reset), "mm-secondary");
      if (reset) feed.replaceChildren(el("div", { className: "mm-state" }, el("h3", { text: state.post ? "暂时看不到这条碎碎念" : "暂时没能加载出来" }), el("p", { text: e.message }), retry, state.post ? el("a", { href: "/murmurs", className: "mm-text-button", text: "回到全部碎碎念" }) : null));
      else { toast(e.message); $("mm-more").hidden = false; $("mm-more").textContent = "加载失败，点击重试"; }
    } finally { if (epoch === state.epoch) { state.loading = false; feed.setAttribute("aria-busy", "false"); $("mm-more").disabled = false; } }
  }
  function reportCard(item) {
    const card = el("article", { className: "mm-post mm-report" });
    card.append(el("p", { className: "mm-report-reason", text: `${item.comment_id ? "评论" : "碎碎念"}举报 · ${{ spam: "垃圾广告", abuse: "不友善内容", copyright: "版权问题", other: "其他问题" }[item.reason] || item.reason}` }),
      el("strong", { text: item.author_username }), el("p", { className: "mm-post-text", text: item.content || "（图片分享）" }));
    if (item.images.length) card.append(imageGrid(item.images, item.author_username));
    card.append(el("p", { className: "mm-report-details", text: `${item.reporter_username} 提交于 ${new Date(item.created_at).toLocaleString("zh-CN")}${item.details ? `\n补充：${item.details}` : ""}` }));
    if (item.status === "pending") {
      const actions = el("div", { className: "mm-report-actions" });
      for (const [label, decision, remove] of [["处理并下线", "resolved", true], ["标记已处理", "resolved", false], ["驳回举报", "rejected", false]]) {
        actions.append(button(label, () => {
          const note = el("textarea", { rows: "3", maxlength: "500", id: "mm-review-note", placeholder: "处理备注（选填）" });
          const error = el("p", { className: "mm-error", role: "alert", hidden: true });
          const send = button("确认处理", async () => {
            send.disabled = true;
            try { await api(`/api/admin/murmurs/reports/${item.id}/review`, { method: "POST", body: JSON.stringify({ decision, remove, note: note.value }) }); closeDialog(); toast("举报已处理"); await loadFeed(true); }
            catch (e) { error.textContent = e.message; error.hidden = false; }
            finally { send.disabled = false; }
          }, "mm-primary");
          openDialog(label, el("label", { for: note.id, text: "处理备注" }), note, error, el("div", { className: "mm-dialog-actions" }, button("取消", closeDialog), send));
        }, remove ? "mm-primary" : "mm-secondary"));
      }
      card.append(actions);
    } else card.append(el("p", { className: "mm-report-details", text: `${item.status === "resolved" ? "已处理" : "已驳回"}${item.removed ? "，内容已下线" : ""} · ${item.reviewer_username}${item.review_note ? `\n备注：${item.review_note}` : ""}` }));
    return card;
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
  function setPageContext() {
    document.querySelectorAll("[data-mm-view]").forEach((node) => {
      if (node.dataset.mmView === state.view && !state.post && !state.author) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
    $("mm-moderation").hidden = !state.moderator;
    if (state.view === "reports") {
      $("mm-composer").hidden = true; $("mm-report-filter").hidden = !state.moderator;
      $("mm-feed-title").textContent = "碎碎念举报管理"; $("mm-feed-subtitle").textContent = "核实内容，记录处理结果";
    } else if (state.post) {
      $("mm-feed-title").textContent = "这一条碎碎念";
      $("mm-feed-subtitle").replaceChildren(el("a", { href: "/murmurs", text: "回到全部碎碎念" }));
    } else if (state.view === "mine") { $("mm-feed-title").textContent = "我的碎碎念"; $("mm-feed-subtitle").textContent = "你留下的每一个日常瞬间"; }
    else if (state.author) { $("mm-feed-title").textContent = `${state.author}的碎碎念`; $("mm-feed-subtitle").replaceChildren(el("a", { href: "/murmurs", text: "看看大家的碎碎念" })); }
    if (state.profile) {
      $("mm-my-avatar").replaceWith(Object.assign(avatar(state.profile, false), { id: "mm-my-avatar" }));
      $("mm-identity").textContent = state.profile.display_name;
    } else $("mm-identity").replaceChildren(el("a", { href: loginUrl(), text: "登录，加入这场闲聊" }));
  }
  async function init() {
    document.querySelectorAll("[data-mm-icon]").forEach((node) => node.replaceChildren(icon(node.dataset.mmIcon)));
    const date = new Date();
    $("mm-month").textContent = date.toLocaleDateString("zh-CN", { year: "numeric", month: "long" });
    $("mm-day").textContent = String(date.getDate()).padStart(2, "0");
    $("mm-weekday").textContent = date.toLocaleDateString("zh-CN", { weekday: "long" });
    content.addEventListener("input", draftChanged);
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
    setPageContext(); restoreDraft();
    await loadFeed(true);
  }
  init();
})();
