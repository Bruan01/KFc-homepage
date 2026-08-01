(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const form = $("#generation-form"), prompt = $("#prompt"), button = $("#generate-button");
  const message = $("#form-message"), state = $("#generation-state"), empty = $("#empty-state"), result = $("#result-card");
  const ACTIVE_JOB_KEY = "kflow.imaging.active-job";
  let timer = null, startedAt = 0;

  function say(text, error) { message.textContent = text; message.classList.toggle("error", Boolean(error)); }
  function busy(value) { button.disabled = value; button.classList.toggle("busy", value); button.querySelector("b").textContent = value ? "正在显影" : "生成图片"; }
  function setState(text, kind) { state.textContent = text; state.className = "state" + (kind ? " " + kind : ""); }
  function key() { return (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, ""); }
  function rememberJob(id) { try { localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ id, startedAt: Date.now() })); } catch (_) {} }
  function readActiveJob() { try { const value = JSON.parse(localStorage.getItem(ACTIVE_JOB_KEY) || "null"); return value && value.id ? value : null; } catch (_) { return null; } }
  function forgetJob(id) { try { const active = readActiveJob(); if (!id || (active && active.id === id)) localStorage.removeItem(ACTIVE_JOB_KEY); } catch (_) {} }
  function updateCount() { $("#character-count").textContent = `${prompt.value.length} / 4000`; }
  function details(job) { return `${job.size.replace("x", " × ")} · ${job.quality} · ${job.output_format.toUpperCase()}`; }
  function showResult(job) {
    empty.classList.add("hidden"); result.classList.remove("hidden"); $("#result-image").src = job.image_url;
    $("#result-image").alt = job.prompt; $("#result-prompt").textContent = job.prompt; $("#result-details").textContent = details(job);
    $("#download-link").href = job.download_url || job.image_url; $("#download-link").download = job.filename || "image.png";
  }
  function renderHistory(items) {
    const grid = $("#history-grid"); grid.replaceChildren(); $("#history-empty").classList.toggle("hidden", items.length > 0);
    $("#history-count").textContent = items.length ? `最近 ${items.length} 张` : "";
    items.forEach((item) => { const node = $("#history-template").content.cloneNode(true), btn = node.querySelector(".history-preview");
      const image = node.querySelector("img"); image.src = item.image_url; image.alt = item.prompt; node.querySelector("b").textContent = item.prompt;
      node.querySelector("small").textContent = new Date(item.created_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      const download = node.querySelector(".history-download"); download.href = item.download_url || item.image_url; download.download = item.filename || "image.png";
      btn.addEventListener("click", () => { $("#dialog-image").src = item.image_url; $("#dialog-caption").textContent = item.prompt; $("#image-dialog").showModal(); }); grid.append(node);
    });
  }
  async function loadAccount() { const [points, rules] = await Promise.all([fetch("/api/points/me"), fetch("/api/points/rules")]);
    if (points.ok) $("#balance").textContent = (await points.json()).balance;
    if (rules.ok) { const data = await rules.json(); $("#cost").textContent = data.item.image_generation_default_cost; }
  }
  async function loadHistory() { const response = await fetch("/api/imaging/history"); if (response.ok) renderHistory(await response.json()); }
  async function poll(id) { try { const response = await fetch(`/api/imaging/generations/${id}`); if (!response.ok) { if (response.status === 401) { window.location.href = "/login?next=/imaging"; return null; } if (response.status === 404) forgetJob(id); throw new Error("无法读取任务状态"); } const job = await response.json();
      if (job.status === "queued" || job.status === "generating") { setState(job.status === "queued" ? "排队准备中" : "正在生成", "working"); say(`CPA 正在显影画面，已等待 ${Math.floor((Date.now() - startedAt) / 1000)} 秒。`); return job; }
      clearInterval(timer); timer = null; busy(false); forgetJob(id);
      if (job.status === "completed") { setState("生成完成"); say("新的画面已保存到你的私有记录。"); showResult(job); await Promise.all([loadHistory(), loadAccount()]); }
      else { setState("生成失败", "failed"); say(job.error || "生成失败，请稍后重试。", true); await loadAccount(); }
      return job;
    } catch (error) { clearInterval(timer); timer = null; busy(false); setState("状态中断", "failed"); say(error.message, true); }
  }
  async function resumeActiveJob() { const active = readActiveJob(); if (!active) return; startedAt = Number(active.startedAt) || Date.now(); busy(true); say("正在恢复上次未完成的显影任务。"); const job = await poll(active.id); if (job && (job.status === "queued" || job.status === "generating")) timer = setInterval(() => poll(active.id), 2500); }
  async function submit(event) { event.preventDefault(); const text = prompt.value.trim(); if (!text) { say("先写下一句画面描述。", true); prompt.focus(); return; }
    busy(true); startedAt = Date.now(); setState("准备生成", "working"); say("正在把描述交给本机 CPA。");
    try { const response = await fetch("/api/imaging/generations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: text, size: $("#size").value, quality: $("#quality").value, output_format: $("#output-format").value, idempotencyKey: key() }) });
      const data = await response.json(); if (response.status === 401) { window.location.href = "/login?next=/imaging"; return; } if (!response.ok) throw new Error(data.error || "创建生成任务失败。");
      $("#balance").textContent = data.balance; rememberJob(data.id); const job = await poll(data.id); if (job && (job.status === "queued" || job.status === "generating")) timer = setInterval(() => poll(data.id), 2500);
    } catch (error) { busy(false); setState("无法开始", "failed"); say(error.message, true); }
  }
  prompt.addEventListener("input", updateCount); prompt.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") form.requestSubmit(); }); form.addEventListener("submit", submit);
  $("#dialog-close").addEventListener("click", () => $("#image-dialog").close()); $("#image-dialog").addEventListener("click", (event) => { if (event.target === $("#image-dialog")) $("#image-dialog").close(); });
  updateCount(); loadAccount().catch(() => {}); loadHistory().catch(() => {}); resumeActiveJob().catch(() => {});
}());
