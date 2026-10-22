(() => {
  "use strict";
  if (location.pathname.replace(/\/+$/, "") !== "/admin/users") return;
  const $ = (id) => document.getElementById(id), panel = $("communityAIPanel");
  if (!panel) return;
  let busy = false;
  async function api(path, body) {
    let response;
    try { response = await fetch(path, { method: body ? "POST" : "GET", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "" }, ...(body ? { body: JSON.stringify(body) } : {}) }); }
    catch { throw new Error("网络连接中断，请检查网络后重试"); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "操作未完成，请重试");
    return data;
  }
  function message(text, error = false) { $("communityAIStatus").textContent = text; $("communityAIStatus").classList.toggle("is-error", error); }
  function lock(value) { busy = value; panel.querySelectorAll("form input, form textarea, form button, #communityAITest").forEach((item) => { item.disabled = value; }); }
  function values() {
    return { enabled: $("communityAIEnabled").checked, base_url: $("communityAIBaseURL").value.trim(), model: $("communityAIModel").value.trim(),
      api_key: $("communityAIKey").value, clear_api_key: $("communityAIKeyClear").checked,
      persona: $("communityAIPersona").value, knowledge: $("communityAIKnowledge").value };
  }
  function render(config, fill = true) {
    $("communityAIWorker").textContent = config.worker_alive ? "回复服务运行中" : "回复服务未连接";
    $("communityAIAccount").textContent = config.official_account ? `使用官方账号：${config.official_account.display_name}（@${config.official_account.username}）` : "请先在上方指定小 K 官方账号，再启用自动回复。";
    if (!fill) return;
    $("communityAIEnabled").checked = config.enabled;
    $("communityAIBaseURL").value = config.base_url; $("communityAIModel").value = config.model;
    $("communityAIPersona").value = config.persona; $("communityAIKnowledge").value = config.knowledge;
    $("communityAIKey").value = ""; $("communityAIKeyClear").checked = false;
    $("communityAIKeyHint").textContent = config.has_api_key ? "密钥已加密保存，留空保留原密钥。" : "尚未配置密钥；本地无鉴权服务可留空。";
    $("communityAIKeyClearLabel").hidden = !config.has_api_key;
  }
  async function refresh(fill = false) { const data = await api("/api/admin/community-ai/settings"); render(data.settings, fill); }
  function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text) node.textContent = text; return node; }
  async function records() {
    const host = $("communityAIRecords"), button = $("communityAIRecordsRefresh"); button.disabled = true;
    try {
      const data = await api("/api/admin/community-ai/records");
      const labels = { queued: "等待回复", processing: "正在生成", completed: "已回复", failed: "未完成", skipped: "已跳过" };
      host.replaceChildren(...data.items.map((item) => {
        const row = element("article", "community-ai-record");
        const head = element("div", "community-ai-record-head");
        head.append(element("strong", "", `@${item.requester_username}`), element("span", "official-community-tag", labels[item.status] || item.status), element("time", "small", new Date(item.created_at).toLocaleString("zh-CN")));
        row.append(head, element("p", "community-ai-record-source", item.trigger_excerpt || "发送了图片"));
        if (item.reply) row.append(element("p", "community-ai-record-reply", item.reply));
        if (item.error) row.append(element("p", "small", item.error));
        const link = element("a", "small", "查看对应讨论"); link.href = item.link; link.target = "_blank"; link.rel = "noopener"; row.append(link);
        if (item.status === "failed") {
          const retry = element("button", "btn", "重试回复"); retry.type = "button";
          retry.addEventListener("click", async () => { retry.disabled = true; try { await api(`/api/admin/community-ai/records/${item.id}/retry`, {}); await records(); } catch (error) { message(error.message, true); retry.disabled = false; } });
          row.append(retry);
        }
        return row;
      }));
      if (!data.items.length) host.append(element("p", "small", "还没有回复记录。启用后，用户 @ 小 K 时会在这里留下记录。"));
    } catch (error) { host.replaceChildren(element("p", "small", error.message)); }
    finally { button.disabled = false; }
  }
  $("communityAIForm").addEventListener("submit", async (event) => {
    event.preventDefault(); if (busy) return;
    const body = values(); lock(true); message("正在保存…");
    try { const data = await api("/api/admin/community-ai/settings", body); render(data.settings); message(data.settings.enabled ? "已保存，小 K 会回应新的 @ 和对它的 AI 评论的回复。" : "已保存，自动回复已关闭。"); }
    catch (error) { message(error.message, true); }
    finally { lock(false); }
  });
  $("communityAITest").addEventListener("click", async () => {
    if (busy) return;
    const body = { ...values(), prompt: $("communityAITestPrompt").value };
    lock(true); $("communityAITestResult").hidden = false; $("communityAITestResult").textContent = "小 K 正在思考…";
    try { const data = await api("/api/admin/community-ai/test", body); $("communityAITestResult").textContent = data.reply; }
    catch (error) { $("communityAITestResult").textContent = error.message; }
    finally { lock(false); }
  });
  $("communityAIRefresh").addEventListener("click", async () => { if (busy) return; try { await refresh(); message("运行状态已更新，填写中的内容已保留。"); } catch (error) { message(error.message, true); } });
  $("communityAIRecordsRefresh").addEventListener("click", records);
  panel.querySelector("details").addEventListener("toggle", (event) => { if (event.target.open) records(); });
  window.addEventListener("kflow:official-updated", () => { refresh().catch(() => {}); });
  (async () => { try { const me = await api("/api/admin/me"); if (!me.isSuper) return; panel.hidden = false; await refresh(true); } catch (error) { message(error.message, true); } })();
})();
