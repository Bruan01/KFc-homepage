(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const form = $("#generation-form"), prompt = $("#prompt"), button = $("#generate-button");
  const message = $("#form-message"), state = $("#generation-state"), empty = $("#empty-state"), result = $("#result-card");
  const request = window.ImagingHttp.request;
  const DOWNLOAD_URL_RELEASE_MS = 60000;
  const DEFAULT_PROMPT_PLACEHOLDER = "例如：日出时分，一座漂浮在云海中的未来图书馆，玻璃穹顶映着金色天光……";
  const MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024;
  const downloadDialog = $("#download-dialog");
  let downloadJob = null, downloadKey = null, downloading = false;
  const ACTIVE_JOB_KEY = "kflow.imaging.active-job";
  let timer = null, startedAt = 0, templates = [], selectedTemplate = null, referenceFiles = [];

  function say(text, error) { message.textContent = text; message.classList.toggle("error", Boolean(error)); }
  function busy(value) { button.disabled = value; button.classList.toggle("busy", value); button.querySelector("b").textContent = value ? "正在显影" : "生成图片"; }
  function setState(text, kind) { state.textContent = text; state.className = "state" + (kind ? " " + kind : ""); }
  function key() { return (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, ""); }
  function rememberJob(id) { try { localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ id, startedAt: Date.now() })); } catch (_) {} }
  function readActiveJob() { try { const value = JSON.parse(localStorage.getItem(ACTIVE_JOB_KEY) || "null"); return value && value.id ? value : null; } catch (_) { return null; } }
  function forgetJob(id) { try { const active = readActiveJob(); if (!id || (active && active.id === id)) localStorage.removeItem(ACTIVE_JOB_KEY); } catch (_) {} }
  function updateCount() { $("#character-count").textContent = `${prompt.value.length} / ${prompt.maxLength}`; }
  async function readJson(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) return response.json();
    throw new Error(`生成请求失败（HTTP ${response.status}），请刷新页面后重试。`);
  }
  function details(job) { return `${job.size.replace("x", " × ")} · ${job.quality} · ${job.output_format.toUpperCase()}`; }
  function showResult(job) {
    empty.classList.add("hidden"); result.classList.remove("hidden"); $("#result-image").src = job.image_url;
    $("#result-image").alt = job.prompt; $("#result-prompt").textContent = job.prompt; $("#result-details").textContent = details(job);
    bindDownload($("#download-link"), job);
  }

  function safeCoverUrl(value) {
    if (!value) return "";
    try {
      const parsed = new URL(String(value), window.location.origin);
      if (!["http:", "https:"].includes(parsed.protocol)) return "";
      return parsed.href;
    } catch (_) { return ""; }
  }

  function createTemplateField(field) {
    const wrapper = document.createElement("div"); wrapper.className = "template-field";
    const label = document.createElement("label"); label.textContent = field.label || field.key;
    let control;
    if (Array.isArray(field.options) && field.options.length) {
      control = document.createElement("select");
      field.options.forEach((option) => { const item = document.createElement("option"); item.value = option; item.textContent = option; control.append(item); });
    } else {
      control = document.createElement("input"); control.type = "text";
    }
    control.dataset.templateKey = field.key; control.maxLength = Number(field.maxLength || field.max_length || 180);
    control.placeholder = field.placeholder || ""; control.value = field.default || ""; control.required = Boolean(field.required);
    label.htmlFor = `template-field-${field.key}`; control.id = label.htmlFor; label.append(control); wrapper.append(label); return wrapper;
  }

  function templateValues() {
    return Object.fromEntries(Array.from(document.querySelectorAll("[data-template-key]")).map((field) => [field.dataset.templateKey, field.value]));
  }

  function renderReferencePreview() {
    const preview = $("#reference-preview"); preview.replaceChildren();
    referenceFiles.forEach((file) => { const item = document.createElement("span"); item.className = "reference-file"; item.textContent = file.name; preview.append(item); });
  }

  function updateReferenceUpload() {
    const section = $("#reference-upload");
    if (!selectedTemplate) { section.classList.add("hidden"); return; }
    const maximum = Number(selectedTemplate.referenceMaxCount ?? selectedTemplate.reference_max_count ?? 0);
    const required = Boolean(selectedTemplate.referenceRequired ?? selectedTemplate.reference_required);
    section.classList.remove("hidden");
    const capText = maximum > 0 ? `，最多 ${maximum} 张` : "";
    $("#reference-upload-hint").textContent = required
      ? `至少上传 1 张${capText}；单张不超过 10MB。`
      : `可选：不上传则无参考图${capText}；单张不超过 10MB。`;
  }

  function renderTemplateCards() {
    const grid = $("#template-grid"); grid.replaceChildren();
    templates.forEach((template) => {
      const card = document.createElement("button"); card.type = "button"; card.className = `template-card${selectedTemplate && selectedTemplate.key === template.key ? " selected" : ""}`;
      card.setAttribute("aria-pressed", selectedTemplate && selectedTemplate.key === template.key ? "true" : "false");
      const cover = document.createElement("div"); cover.className = `template-cover ${template.accent || ""}`;
      const coverUrl = safeCoverUrl(template.coverUrl ?? template.cover_url);
      if (coverUrl) { cover.classList.add("has-image"); cover.style.backgroundImage = `url("${coverUrl.replace(/["\\\r\n]/g, "")}")`; }
      const category = document.createElement("span"); category.textContent = template.category || "显影模板"; cover.append(category);
      const copy = document.createElement("div"); copy.className = "template-copy"; const title = document.createElement("h3"); title.textContent = template.name;
      const description = document.createElement("p"); description.textContent = template.description; copy.append(title, description); card.append(cover, copy);
      card.addEventListener("click", () => selectTemplate(template)); grid.append(card);
    });
  }

  function selectTemplate(template) {
    selectedTemplate = template; referenceFiles = []; renderTemplateCards();
    $("#template-config").classList.remove("hidden"); $("#selected-template-name").textContent = template.name; $("#selected-template-description").textContent = template.description;
    const fields = $("#template-fields"); fields.replaceChildren(); (template.fields || []).forEach((field) => fields.append(createTemplateField(field)));
    updateReferenceUpload(); $("#reference-images").value = ""; renderReferencePreview(); prompt.required = false; prompt.maxLength = 800; prompt.value = ""; prompt.placeholder = "补充要求（可选），例如：镜头再近一些"; updateCount(); say(`已选择「${template.name}」，填写上方内容后即可生成。`); $("#template-config").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function clearTemplate() {
    selectedTemplate = null; referenceFiles = []; renderTemplateCards(); $("#template-config").classList.add("hidden"); updateReferenceUpload(); $("#reference-images").value = ""; renderReferencePreview(); prompt.required = true; prompt.maxLength = 4000; prompt.value = ""; prompt.placeholder = DEFAULT_PROMPT_PLACEHOLDER; updateCount(); say("已切换为自由创作。"); prompt.focus();
  }

  function onReferenceChange(event) {
    const maximum = Number(selectedTemplate && (selectedTemplate.referenceMaxCount ?? selectedTemplate.reference_max_count) || 0);
    const files = Array.from(event.target.files || []);
    if (maximum > 0 && files.length > maximum) { say(`最多上传${maximum}张参考图片。`, true); event.target.value = ""; referenceFiles = []; renderReferencePreview(); return; }
    const invalid = files.find((file) => !["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > MAX_REFERENCE_IMAGE_BYTES);
    if (invalid) { say(`图片「${invalid.name}」格式不支持或超过10MB。`, true); event.target.value = ""; referenceFiles = []; renderReferencePreview(); return; }
    referenceFiles = files; renderReferencePreview();
  }
  function renderHistory(items) {
    const grid = $("#history-grid"); grid.replaceChildren(); $("#history-empty").classList.toggle("hidden", items.length > 0);
    $("#history-count").textContent = items.length ? `最近 ${items.length} 张` : "";
    items.forEach((item) => { const node = $("#history-template").content.cloneNode(true), btn = node.querySelector(".history-preview");
      const image = node.querySelector("img"); image.src = item.image_url; image.alt = item.prompt; node.querySelector("b").textContent = item.prompt;
      node.querySelector("small").textContent = new Date(item.created_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      bindDownload(node.querySelector(".history-download"), item);
      btn.addEventListener("click", () => { $("#dialog-image").src = item.image_url; $("#dialog-caption").textContent = item.prompt; $("#image-dialog").showModal(); }); grid.append(node);
    });
  }
  /** Bind only originals that the server retained; never download the preview as an original. */
  function bindDownload(button, job) {
    button.disabled = !job.original_available;
    button.textContent = job.original_available ? "下载原图 ↓" : "原图未保留";
    button.title = job.original_available ? "每次下载 1 积分" : "历史图片未保存原始文件";
    button.onclick = () => openDownload(job);
  }
  /** Show the price before requesting any paid content. */
  async function openDownload(job) {
    downloadJob = job; downloadKey = key();
    const openingKey = downloadKey;
    $("#download-preview").src = job.image_url;
    $("#download-file-details").textContent = `${job.size.replace("x", " × ")} · ${(job.filename || "").split(".").pop().toUpperCase()}`;
    $("#download-balance").textContent = "读取中…";
    $("#download-message").textContent = "";
    $("#download-confirm").disabled = true;
    downloadDialog.showModal();
    try {
      const response = await request("/api/points/me");
      const account = await response.json();
      if (!downloadDialog.open || downloadKey !== openingKey) return;
      $("#balance").textContent = account.balance;
      $("#download-balance").textContent = `${account.balance} 积分`;
      $("#download-confirm").disabled = account.balance < job.original_download_cost;
      if (account.balance < job.original_download_cost) $("#download-message").textContent = "积分不足，获取积分后再来珍藏这张作品吧。";
    } catch (error) { if (downloadDialog.open && downloadKey === openingKey) $("#download-message").textContent = error.message; }
  }
  /** One confirmation has one request key, including a retry after a lost response. */
  async function confirmDownload() {
    if (downloading || !downloadJob) return;
    downloading = true;
    $("#download-confirm").disabled = true;
    $("#download-cancel").disabled = true;
    $("#download-close").disabled = true;
    $("#download-confirm").textContent = "正在准备原图…";
    $("#download-message").textContent = "请稍候，原图准备完成后将开始下载。";
    try {
      const response = await request(downloadJob.download_url, { method: "POST", body: JSON.stringify({ confirmed: true, idempotency_key: downloadKey }) });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = downloadJob.filename; document.body.append(link);
      link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_URL_RELEASE_MS);
      $("#balance").textContent = response.headers.get("X-Points-Balance");
      downloadDialog.close();
      say("原图下载已发起，本次扣除 1 积分。");
    } catch (error) {
      $("#download-message").textContent = `${error.message} 如网络中断，可在此重试，同一请求不会重复扣费。`;
    } finally {
      downloading = false;
      $("#download-confirm").disabled = false;
      $("#download-cancel").disabled = false;
      $("#download-close").disabled = false;
      $("#download-confirm").textContent = "支付 1 积分并下载 ↓";
    }
  }
  $("#download-confirm").addEventListener("click", confirmDownload);
  [$("#download-cancel"), $("#download-close")].forEach((button) => button.addEventListener("click", () => { if (!downloading) downloadDialog.close(); }));
  downloadDialog.addEventListener("cancel", (event) => { if (downloading) event.preventDefault(); });
  downloadDialog.addEventListener("click", (event) => {
    const rect = downloadDialog.getBoundingClientRect();
    if (!downloading && event.target === downloadDialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) downloadDialog.close();
  });
  async function loadAccount() { const [points, rules] = await Promise.all([request("/api/points/me"), request("/api/points/rules")]);
    if (points.ok) $("#balance").textContent = (await points.json()).balance;
    if (rules.ok) { const data = await rules.json(); $("#cost").textContent = data.item.image_generation_default_cost; }
  }
  async function loadTemplates() { const response = await request("/api/imaging/templates"); const data = await readJson(response); templates = data.items || []; renderTemplateCards(); $("#template-library-empty").classList.toggle("hidden", templates.length > 0); }
  async function loadHistory() { const response = await request("/api/imaging/history"); if (response.ok) renderHistory(await response.json()); }
  async function poll(id) { try { const response = await request(`/api/imaging/generations/${id}`); if (!response.ok) { if (response.status === 401) { window.location.href = "/login?next=/imaging"; return null; } if (response.status === 404) forgetJob(id); throw new Error("无法读取任务状态"); } const job = await response.json();
      if (job.status === "queued" || job.status === "generating") { setState(job.status === "queued" ? "排队准备中" : "正在生成", "working"); say(`CPA 正在显影画面，已等待 ${Math.floor((Date.now() - startedAt) / 1000)} 秒。`); return job; }
      clearInterval(timer); timer = null; busy(false); forgetJob(id);
      if (job.status === "completed") { setState("生成完成"); say("新的画面已保存到你的私有记录。"); showResult(job); await Promise.all([loadHistory(), loadAccount()]); }
      else { setState("生成失败", "failed"); say(job.error || "生成失败，请稍后重试。", true); await loadAccount(); }
      return job;
    } catch (error) { if (error.status === 404) forgetJob(id); clearInterval(timer); timer = null; busy(false); setState("状态中断", "failed"); say(error.message, true); }
  }
  async function resumeActiveJob() { const active = readActiveJob(); if (!active) return; startedAt = Number(active.startedAt) || Date.now(); busy(true); say("正在恢复上次未完成的显影任务。"); const job = await poll(active.id); if (job && (job.status === "queued" || job.status === "generating")) timer = setInterval(() => poll(active.id), 2500); }
  async function submit(event) { event.preventDefault(); const text = prompt.value.trim(); if (!selectedTemplate && !text) { say("先写下一句画面描述。", true); prompt.focus(); return; } if (selectedTemplate && !form.reportValidity()) return;
    busy(true); startedAt = Date.now(); setState("准备生成", "working"); say("正在把描述交给本机 CPA。");
    try {
      const payload = { prompt: text, size: $("#size").value, quality: $("#quality").value, output_format: $("#output-format").value, idempotencyKey: key() };
      let body = JSON.stringify(payload);
      if (selectedTemplate) {
        payload.templateKey = selectedTemplate.key; payload.templateValues = templateValues(); payload.extraPrompt = text;
        const formData = new FormData(); formData.append("payload", JSON.stringify(payload)); referenceFiles.forEach((file) => formData.append("references", file, file.name)); body = formData;
      }
      const response = await request("/api/imaging/generations", { method: "POST", body });
      const data = await readJson(response); if (response.status === 401) { window.location.href = "/login?next=/imaging"; return; } if (!response.ok) throw new Error(data.error || "创建生成任务失败。");
      $("#balance").textContent = data.balance; rememberJob(data.id); const job = await poll(data.id); if (job && (job.status === "queued" || job.status === "generating")) timer = setInterval(() => poll(data.id), 2500);
    } catch (error) { busy(false); setState("无法开始", "failed"); say(error.message, true); }
  }
  prompt.addEventListener("input", updateCount); prompt.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") form.requestSubmit(); }); $("#reference-images").addEventListener("change", onReferenceChange); form.addEventListener("submit", submit); $("#clear-template").addEventListener("click", clearTemplate);
  $("#dialog-close").addEventListener("click", () => $("#image-dialog").close()); $("#image-dialog").addEventListener("click", (event) => { if (event.target === $("#image-dialog")) $("#image-dialog").close(); });
  updateCount(); loadTemplates().catch((error) => { $("#template-library-empty").classList.remove("hidden"); say(error.message, true); }); loadAccount().catch((error) => say(error.message, true)); loadHistory().catch((error) => say(error.message, true)); resumeActiveJob().catch((error) => say(error.message, true));
}());
