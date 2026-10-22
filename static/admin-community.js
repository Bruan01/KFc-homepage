/* Official account settings are available only on the user-management page. */
(() => {
  "use strict";
  if (location.pathname.replace(/\/+$/, "") !== "/admin/users") return;
  const $ = (id) => document.getElementById(id);
  const panel = $("officialCommunityPanel"), form = $("officialCommunityForm"), status = $("officialCommunityStatus");
  if (!panel || !form) return;
  let busy = false, timer, searchEpoch = 0;
  async function api(url, options = {}) {
    let response;
    try { response = await fetch(url, { credentials: "same-origin", ...options, headers: { "Content-Type": "application/json", "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "" } }); }
    catch { throw new Error("网络连接中断，请检查网络后重试"); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "操作未完成，请重试");
    return data;
  }
  function message(text, error = false) { status.textContent = text; status.classList.toggle("is-error", error); }
  function lock(value) {
    busy = value;
    for (const id of ["officialAccountUsername", "officialFollowerTarget", "officialCommunitySave", "officialCommunityRefresh"]) $(id).disabled = value;
    $("officialCommunitySave").textContent = value ? "正在同步…" : "保存并同步";
  }
  function candidates(items) {
    $("officialAccountSuggestions").replaceChildren(...items.map((user) => {
      const option = document.createElement("option"); option.value = user.username; option.label = user.display_name;
      return option;
    }));
  }
  function render(settings, fillForm = true) {
    $("officialFollowerTotal").textContent = settings.follower_count.toLocaleString("zh-CN");
    $("officialFollowerManaged").textContent = settings.managed_follower_count.toLocaleString("zh-CN");
    $("officialFollowerOther").textContent = settings.other_follower_count.toLocaleString("zh-CN");
    $("officialFollowerTarget").max = String(settings.max_target);
    $("officialCommunityCurrent").textContent = settings.account ? `当前官方账号：${settings.account.display_name}（@${settings.account.username}）` : "尚未设置官方账号";
    if (fillForm) {
      $("officialAccountUsername").value = settings.account?.username || "";
      $("officialFollowerTarget").value = String(settings.target_follower_count);
    }
  }
  async function refresh(fillForm = false) {
    if (busy) return;
    lock(true);
    try { const data = await api("/api/admin/community/official"); render(data.settings, fillForm); candidates(data.candidates); message("统计已更新"); }
    catch (error) { message(error.message, true); }
    finally { lock(false); }
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (busy || !form.reportValidity()) return;
    const body = { account_username: $("officialAccountUsername").value.trim(), target_follower_count: Number($("officialFollowerTarget").value) };
    lock(true); message("正在同步默认关注与粉丝数量，请稍候…");
    try {
      const data = await api("/api/admin/community/official", { method: "POST", body: JSON.stringify(body) });
      render(data.settings);
      const changes = data.changes;
      message(`已保存。当前 ${data.settings.follower_count} 位粉丝；新增默认关注 ${changes.initialized_follows}，补充关注 ${changes.added_follows}，移除系统关注 ${changes.removed_follows}。${data.settings.follower_count > body.target_follower_count ? "用户关注已保留，因此当前数量高于目标。" : ""}`);
      window.dispatchEvent(new CustomEvent("kflow:official-updated"));
    } catch (error) { message(error.message, true); }
    finally { lock(false); }
  });
  $("officialCommunityRefresh").addEventListener("click", () => refresh());
  $("officialAccountUsername").addEventListener("input", () => {
    const epoch = ++searchEpoch; clearTimeout(timer);
    timer = setTimeout(async () => {
      try { const data = await api(`/api/admin/community/official?q=${encodeURIComponent($("officialAccountUsername").value)}`); if (epoch === searchEpoch) candidates(data.candidates); }
      catch { /* Form submission supplies actionable validation if lookup fails. */ }
    }, 200);
  });
  (async () => {
    try {
      const me = await api("/api/admin/me"); if (!me.isSuper) return;
      panel.hidden = false; await refresh(true);
    } catch { /* The existing admin page handles session expiry. */ }
  })();
})();
