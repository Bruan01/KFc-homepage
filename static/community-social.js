/* Shared follow controls. User supplied strings only enter textContent. */
(() => {
  "use strict";
  const cache = new Map();
  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text != null) result.textContent = text;
    return result;
  }
  async function api(url, method = "GET") {
    let response;
    try { response = await fetch(url, { method, credentials: "same-origin", headers: { "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "" } }); }
    catch { throw new Error("网络连接中断，请检查网络后重试"); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "操作未完成，请重试");
    return data;
  }
  function changed(username, data) {
    cache.set(username, data.is_following);
    window.dispatchEvent(new CustomEvent("kflow:follow-changed", { detail: { username, ...data } }));
  }
  function officialBadge() { return node("span", "social-official-badge", "官方"); }
  function followButton(author, viewer, onError = alert) {
    const control = node("button", "social-follow"); control.type = "button";
    if (author.username === viewer) { control.hidden = true; return control; }
    if (!cache.has(author.username)) cache.set(author.username, !!author.is_following);
    function render() {
      const following = cache.get(author.username);
      control.textContent = following ? "已关注" : "关注";
      control.setAttribute("aria-label", `${following ? "取消关注" : "关注"}${author.display_name || author.username}`);
      control.setAttribute("aria-pressed", String(following));
    }
    const listener = (event) => {
      if (!control.isConnected) { window.removeEventListener("kflow:follow-changed", listener); return; }
      if (event.detail.username === author.username) render();
    };
    window.addEventListener("kflow:follow-changed", listener);
    control.addEventListener("click", async () => {
      if (!viewer) { location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`; return; }
      control.disabled = true;
      try { changed(author.username, await api(`/api/users/${encodeURIComponent(author.username)}/follow`, cache.get(author.username) ? "DELETE" : "POST")); }
      catch (error) { onError(error.message || "网络连接中断，请重试"); }
      finally { control.disabled = false; }
    });
    render(); return control;
  }
  function stats(username, viewer, onError = alert) {
    const wrap = node("div", "social-stats");
    const own = !!viewer && username === viewer;
    const following = node(own ? "button" : "span", "social-stat", "关注 …"), followers = node(own ? "button" : "span", "social-stat", "粉丝 …");
    for (const [control, kind] of [[following, "following"], [followers, "followers"]]) {
      if (own) { control.type = "button"; control.addEventListener("click", () => showConnections(username, kind, viewer)); }
      else control.title = "名单仅本人可见";
    }
    wrap.append(following, followers);
    let version = 0;
    async function refresh() {
      const epoch = ++version;
      try {
        const data = await api(`/api/users/${encodeURIComponent(username)}/social`);
        if (epoch !== version) return;
        following.textContent = `关注 ${data.following_count}`; followers.textContent = `粉丝 ${data.follower_count}`;
        if (own) following.disabled = followers.disabled = !data.can_view_connections;
        changed(username, data);
      } catch (error) { following.textContent = "关注"; followers.textContent = "粉丝"; onError(error.message); }
    }
    const listener = (event) => {
      if (!wrap.isConnected) { window.removeEventListener("kflow:follow-changed", listener); return; }
      if (username === viewer && event.detail.username !== username) refresh();
      else if (event.detail.username === username) followers.textContent = `粉丝 ${event.detail.follower_count}`;
    };
    window.addEventListener("kflow:follow-changed", listener);
    refresh(); return wrap;
  }
  function showConnections(username, kind, viewer) {
    if (!viewer || viewer !== username) return;
    const existing = document.getElementById("community-social-dialog"); existing?.remove();
    const dialog = node("dialog", "social-dialog"); dialog.id = "community-social-dialog";
    const heading = node("h2", "", `${username === viewer ? "我的" : username + "的"}${kind === "followers" ? "粉丝" : "关注"}`);
    heading.id = "community-social-title"; dialog.setAttribute("aria-labelledby", heading.id);
    const close = node("button", "social-close", "关闭"); close.type = "button"; close.addEventListener("click", () => dialog.close());
    const head = node("div", "social-dialog-head"); head.append(heading, close);
    const searchLabel = node("label", "social-search-label", "搜索昵称或用户名"); searchLabel.htmlFor = "social-search";
    const search = node("input", "social-search"); search.id = "social-search"; search.type = "search"; search.placeholder = "搜索昵称或用户名";
    const list = node("div", "social-people"); const status = node("p", "social-status"); status.setAttribute("role", "status");
    const more = node("button", "social-more", "加载更多"); more.type = "button"; more.hidden = true;
    dialog.append(head, searchLabel, search, list, status, more); document.body.append(dialog); dialog.showModal();
    dialog.addEventListener("close", () => dialog.remove());
    let cursor = null, epoch = 0, timer;
    async function load(reset) {
      const token = ++epoch; more.disabled = true; status.textContent = "正在加载…";
      if (reset) { list.replaceChildren(); cursor = null; }
      const query = new URLSearchParams({ q: search.value }); if (cursor) query.set("after", cursor);
      try {
        const data = await api(`/api/users/${encodeURIComponent(username)}/${kind}?${query}`);
        if (token !== epoch) return;
        for (const author of data.items) {
          const row = node("div", "social-person");
          const link = node("a", "social-person-name", author.display_name); link.href = `/forum/user/${encodeURIComponent(author.username)}`;
          const copy = node("div", "social-person-copy"); copy.append(link, node("small", "", `@${author.username}`));
          if (author.is_official) link.append(" ", officialBadge());
          row.append(copy, followButton(author, viewer, (message) => { status.textContent = message; })); list.append(row);
        }
        cursor = data.next_cursor; more.hidden = !cursor;
        status.textContent = list.children.length ? "" : search.value ? "没有匹配的用户，换个关键词试试" : kind === "following" ? "还没有关注的人，去碎碎念中认识大家吧" : "还没有粉丝，分享日常让大家认识你吧";
      } catch (error) { if (token === epoch) { status.textContent = error.message || "加载失败，请重试"; more.hidden = false; } }
      finally { if (token === epoch) more.disabled = false; }
    }
    search.addEventListener("input", () => { ++epoch; more.hidden = true; clearTimeout(timer); timer = setTimeout(() => load(true), 200); });
    more.addEventListener("click", () => load(!list.children.length)); load(true);
  }
  window.KflowSocial = { followButton, stats, showConnections, officialBadge };
})();
