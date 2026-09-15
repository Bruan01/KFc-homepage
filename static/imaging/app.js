(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const form = $("#generation-form"), prompt = $("#prompt"), button = $("#generate-button");
  const message = $("#form-message"), state = $("#generation-state"), empty = $("#empty-state"), result = $("#result-card");
  const ACTIVE_JOB_KEY = "kflow.imaging.active-job", defaultPromptPlaceholder = prompt.placeholder;
  let timer = null, startedAt = 0, templates = [], selectedTemplate = null, referenceFiles = [];

  function say(text, error) { message.textContent = text; message.classList.toggle("error", Boolean(error)); }
  function busy(value) { button.disabled = value; button.classList.toggle("busy", value); button.querySelector("b").textContent = value ? "正在显影" : "生成图片"; }
  function setState(text, kind) { state.textContent = text; state.className = "state" + (kind ? ` ${kind}` : ""); }
  function key() { return (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, ""); }
  function rememberJob(id) { try { localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ id, startedAt: Date.now() })); } catch (_) {} }
  function readActiveJob() { try { const value = JSON.parse(localStorage.getItem(ACTIVE_JOB_KEY) || "null"); return value && value.id ? value : null; } catch (_) { return null; } }
  function forgetJob(id) { try { const active = readActiveJob(); if (!id || (active && active.id === id)) localStorage.removeItem(ACTIVE_JOB_KEY); } catch (_) {} }
  function updateCount() { $("#character-count").textContent = `${prompt.value.length} / ${prompt.maxLength}`; }

  async function readJson(response) { if ((response.headers.get("content-type") || "").includes("application/json")) return response.json(); throw new Error(`生成请求失败（HTTP ${response.status}），请刷新页面后重试。`); }
  function showResult(job) { empty.classList.add("hidden"); result.classList.remove("hidden"); $("#result-image").src = job.image_url; $("#result-image").alt = "生成的图片"; $("#download-link").href = job.download_url || job.image_url; $("#download-link").download = job.filename || "image.png"; }
  function renderHistory(items) {
    const grid = $("#history-grid"); grid.replaceChildren(); $("#history-empty").classList.toggle("hidden", items.length > 0); $("#history-count").textContent = items.length ? `最近 ${items.length} 张` : "";
    items.forEach((item) => { const node = $("#history-template").content.cloneNode(true), preview = node.querySelector(".history-preview"), image = node.querySelector("img"); image.src = item.image_url; image.alt = "历史生成图片"; const download = node.querySelector(".history-download"); download.href = item.download_url || item.image_url; download.download = item.filename || "image.png"; preview.addEventListener("click", () => { $("#dialog-image").src = item.image_url; $("#image-dialog").showModal(); }); grid.append(node); });
  }

  function createTemplateField(field) {
    const label = document.createElement("label"), control = document.createElement(field.kind === "select" ? "select" : "input"); label.append(document.createTextNode(field.label)); control.dataset.templateField = field.key; control.required = Boolean(field.required);
    if (field.kind === "select") field.options.forEach((option) => { const item = document.createElement("option"); item.value = option; item.textContent = option; control.append(item); });
    else { control.type = "text"; control.placeholder = field.placeholder || ""; control.maxLength = field.maxLength || 180; }
    control.value = field.default || ""; label.append(control); return label;
  }
  function templateValues() { const values = {}; document.querySelectorAll("[data-template-field]").forEach((control) => { values[control.dataset.templateField] = control.value.trim(); }); return values; }
  function updateReferenceUpload() {
    const panel = $("#reference-upload"), input = $("#reference-images"), hint = $("#reference-upload-hint");
    // Accept both the public API's camelCase fields and older deployments'
    // snake_case fields. Without this fallback a configured template is
    // interpreted as having a limit of zero and the panel stays hidden.
    const max = selectedTemplate ? Number(selectedTemplate.referenceMaxCount ?? selectedTemplate.reference_max_count ?? 0) : 0;
    const required = Boolean(selectedTemplate && (selectedTemplate.referenceRequired ?? selectedTemplate.reference_required));
    const selected = Boolean(selectedTemplate);
    const enabled = Boolean(selected && max > 0);
    // Keep this area visible once a template is selected. Templates that do
    // not support references explain that state instead of hiding the control.
    panel.classList.toggle("hidden", !selected);
    input.required = Boolean(required && enabled);
    input.disabled = !enabled;
    if (!enabled) { referenceFiles = []; input.value = ""; $("#reference-preview").replaceChildren(); hint.textContent = selected ? "当前模板未配置参考图上传。" : ""; return; }
    hint.textContent = `${required ? "必填 · " : "可选 · "}最多 ${max} 张，支持 JPG、PNG、WebP（单张不超过 10MB）`;
  }
  function renderReferencePreview() {
    const preview = $("#reference-preview"); preview.replaceChildren();
    referenceFiles.forEach((file) => { const item = document.createElement("span"); item.className = "reference-file"; item.textContent = file.name; preview.append(item); });
  }
  function onReferenceChange(event) {
    const max = Number(selectedTemplate && (selectedTemplate.referenceMaxCount ?? selectedTemplate.reference_max_count) || 0);
    const files = Array.from(event.target.files || []);
    if (files.length > max) { say(`最多上传${max}张参考图片。`, true); event.target.value = ""; referenceFiles = []; renderReferencePreview(); return; }
    const tooLarge = files.find((file) => file.size > 10 * 1024 * 1024);
    if (tooLarge) { say(`图片「${tooLarge.name}」超过10MB。`, true); event.target.value = ""; referenceFiles = []; renderReferencePreview(); return; }
    referenceFiles = files; renderReferencePreview();
  }
  function renderTemplateCards() {
    const grid = $("#template-grid"); grid.replaceChildren();
    templates.forEach((template) => { const card = document.createElement("button"), active = selectedTemplate && selectedTemplate.key === template.key; card.type = "button"; card.className = `template-card${active ? " selected" : ""}`; card.setAttribute("aria-pressed", active ? "true" : "false"); const cover = document.createElement("div"); cover.className = `template-cover ${template.accent || ""}`; if (template.coverUrl) { cover.classList.add("has-image"); cover.style.backgroundImage = `url("${template.coverUrl}")`; const probe = new Image(); probe.onerror = () => { cover.style.backgroundImage = "url('/static/imaging/templates/warm-dining.png')"; cover.classList.add("cover-fallback"); }; probe.src = template.coverUrl; } const category = document.createElement("span"); category.textContent = template.category; cover.append(category); const copy = document.createElement("div"), title = document.createElement("h3"), description = document.createElement("p"); copy.className = "template-copy"; title.textContent = template.name; description.textContent = template.description; copy.append(title, description); card.append(cover, copy); card.addEventListener("click", () => selectTemplate(template)); grid.append(card); });
  }
  function selectTemplate(template) {
    selectedTemplate = template; referenceFiles = []; renderTemplateCards(); $("#template-config").classList.remove("hidden"); $("#selected-template-name").textContent = template.name; $("#selected-template-description").textContent = template.description; const fields = $("#template-fields"); fields.replaceChildren(); template.fields.forEach((field) => fields.append(createTemplateField(field))); updateReferenceUpload(); prompt.required = false; prompt.maxLength = 800; prompt.value = ""; prompt.placeholder = "补充要求（可选），例如：镜头再近一些"; updateCount(); say(`已选择「${template.name}」，填写上方内容后即可生成。`); $("#template-config").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function clearTemplate() { selectedTemplate = null; referenceFiles = []; renderTemplateCards(); $("#template-config").classList.add("hidden"); updateReferenceUpload(); prompt.required = true; prompt.maxLength = 4000; prompt.value = ""; prompt.placeholder = defaultPromptPlaceholder; updateCount(); say("已切换为自由创作。"); prompt.focus(); }
  async function loadTemplates() { const response = await fetch("/api/imaging/templates"); if (!response.ok) throw new Error("无法读取模板库"); const data = await response.json(); templates = data.items || []; renderTemplateCards(); $("#template-library-empty").classList.toggle("hidden", templates.length > 0); }
  async function loadAccount() { const [points, rules] = await Promise.all([fetch("/api/points/me"), fetch("/api/points/rules")]); if (points.ok) $("#balance").textContent = (await points.json()).balance; if (rules.ok) $("#cost").textContent = (await rules.json()).item.image_generation_default_cost; }
  async function loadHistory() { const response = await fetch("/api/imaging/history"); if (response.ok) renderHistory(await response.json()); }

  async function poll(id) {
    try { const response = await fetch(`/api/imaging/generations/${id}`); if (!response.ok) { if (response.status === 401) { window.location.href = "/login?next=/imaging"; return null; } if (response.status === 404) forgetJob(id); throw new Error("无法读取任务状态"); } const job = await response.json();
      if (job.status === "queued" || job.status === "generating") { setState(job.status === "queued" ? "排队准备中" : "正在生成", "working"); say(`CPA 正在显影画面，已等待 ${Math.floor((Date.now() - startedAt) / 1000)} 秒。`); return job; }
      clearInterval(timer); timer = null; busy(false); forgetJob(id); if (job.status === "completed") { setState("生成完成"); say("新的画面已保存到你的私人记录。"); showResult(job); await Promise.all([loadHistory(), loadAccount()]); } else { setState("生成失败", "failed"); say(job.error || "生成失败，请稍后重试。", true); await loadAccount(); } return job;
    } catch (error) { clearInterval(timer); timer = null; busy(false); setState("状态中断", "failed"); say(error.message, true); return null; }
  }
  async function resumeActiveJob() { const active = readActiveJob(); if (!active) return; startedAt = Number(active.startedAt) || Date.now(); busy(true); say("正在恢复上次未完成的显影任务。"); const job = await poll(active.id); if (job && (job.status === "queued" || job.status === "generating")) timer = setInterval(() => poll(active.id), 2500); }
  async function submit(event) {
    event.preventDefault(); const text = prompt.value.trim(); if (!selectedTemplate && !text) { say("先写下一句画面描述。", true); prompt.focus(); return; } if (selectedTemplate && !form.reportValidity()) return;
    busy(true); startedAt = Date.now(); setState("准备生成", "working"); say("正在把描述交给本地 CPA。");
    try { const body = { prompt: text, size: $("#size").value, quality: $("#quality").value, output_format: $("#output-format").value, idempotencyKey: key() }; if (selectedTemplate) { body.templateKey = selectedTemplate.key; body.templateValues = templateValues(); body.extraPrompt = text; } const formData = new FormData(); formData.append("payload", JSON.stringify(body)); referenceFiles.forEach((file) => formData.append("references", file, file.name)); const response = await fetch("/api/imaging/generations", { method: "POST", body: formData }); const data = await readJson(response); if (response.status === 401) { window.location.href = "/login?next=/imaging"; return; } if (!response.ok) throw new Error(data.error || "创建生成任务失败。"); $("#balance").textContent = data.balance; rememberJob(data.id); const job = await poll(data.id); if (job && (job.status === "queued" || job.status === "generating")) timer = setInterval(() => poll(data.id), 2500); } catch (error) { busy(false); setState("无法开始", "failed"); say(error.message, true); }
  }

  prompt.addEventListener("input", updateCount); prompt.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") form.requestSubmit(); }); $("#reference-images").addEventListener("change", onReferenceChange); form.addEventListener("submit", submit); $("#clear-template").addEventListener("click", clearTemplate);
  $("#dialog-close").addEventListener("click", () => $("#image-dialog").close()); $("#image-dialog").addEventListener("click", (event) => { if (event.target === $("#image-dialog")) $("#image-dialog").close(); });
  updateCount(); loadTemplates().catch(() => $("#template-library-empty").classList.remove("hidden")); loadAccount().catch(() => {}); loadHistory().catch(() => {}); resumeActiveJob().catch(() => {});
}());
