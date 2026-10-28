(function () {
  "use strict";
  // 游客拿到的是登录门禁页，没有表单和模板库，脚本整体不启动。
  if (document.body.dataset.authenticated !== "1") return;
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
  let templateIndex = 0, templateView = "carousel", templateCategory = "全部", carouselTimer = null;
  let archiveItems = [], archiveOffset = 0, archiveHasMore = true, archiveLoading = false, archiveFilter = "全部";
  const archiveCards = new Map();
  let activeJobId = null, polling = false, pollFailures = 0, submitting = false, submissionKey = null, submissionSignature = null;
  const coverObserver = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
    entries.forEach((entry) => { if (entry.isIntersecting) { loadCover(entry.target); coverObserver.unobserve(entry.target); } });
  }, { rootMargin: "200px" });

  function setImage(image, url, fallback) {
    image.decoding = "async";
    image.dataset.defaultAlt ||= image.alt;
    image.alt = image.dataset.defaultAlt;
    image.classList.remove("image-load-error");
    const retry = document.querySelector(`[data-image-retry="${image.id}"]`);
    if (retry) {
      retry.classList.add("hidden");
      retry.onclick = () => {
        const fresh = new URL(url, location.origin); fresh.searchParams.set("_retry", Date.now());
        setImage(image, fresh.href, fallback);
      };
    }
    image.onload = () => { image.classList.remove("image-load-error"); if (retry) retry.classList.add("hidden"); };
    image.onerror = () => {
      if (fallback) { const original = fallback; fallback = null; image.src = original; return; }
      image.classList.add("image-load-error"); image.alt = "图片暂时无法加载";
      if (retry) retry.classList.remove("hidden");
    };
    image.src = url;
  }

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
    empty.classList.add("hidden"); result.classList.remove("hidden"); setImage($("#result-image"), job.image_url);
    $("#result-image").alt = "生成的图片"; $("#result-details").textContent = `${job.template_name ? `模板：${job.template_name} · ` : "自由创作 · "}${details(job)}`;
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

  function loadCover(cover) {
    if (!cover.dataset.coverUrl) return;
    cover.classList.add("has-image");
    cover.style.backgroundImage = `url("${cover.dataset.coverUrl.replace(/["\\\r\n]/g, "")}")`;
    delete cover.dataset.coverUrl;
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
    referenceFiles.forEach((file, index) => {
      const item = document.createElement("span"); item.className = "reference-file";
      const name = document.createElement("span"); name.textContent = file.name;
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "reference-file-remove"; remove.textContent = "×"; remove.title = `移除 ${file.name}`; remove.setAttribute("aria-label", `移除 ${file.name}`);
      remove.addEventListener("click", () => removeReferenceFile(index)); item.append(name, remove); preview.append(item);
    });
  }

  function syncReferenceInput() {
    const input = $("#reference-images");
    if (typeof DataTransfer === "undefined") return;
    const transfer = new DataTransfer(); referenceFiles.forEach((file) => transfer.items.add(file)); input.files = transfer.files;
  }

  function removeReferenceFile(index) {
    referenceFiles.splice(index, 1); syncReferenceInput(); renderReferencePreview(); say("已移除参考图片。");
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

  function makeTemplateCard(template, index, carousel) {
    const card = document.createElement("button"); card.type = "button"; card.className = `template-card${selectedTemplate && selectedTemplate.key === template.key ? " selected" : ""}`;
    card.setAttribute("aria-pressed", selectedTemplate && selectedTemplate.key === template.key ? "true" : "false");
    const cover = document.createElement("div"); cover.className = `template-cover ${template.accent || ""}`;
    const coverUrl = safeCoverUrl(template.coverUrl ?? template.cover_url);
    if (coverUrl) {
      cover.dataset.coverUrl = coverUrl;
      if (!carousel) { if (coverObserver) coverObserver.observe(cover); else loadCover(cover); }
    }
    const category = document.createElement("span"); category.className = "template-category"; category.textContent = template.category || "显影模板";
    const use = document.createElement("span"); use.className = "template-use"; use.textContent = "选用模板 ↗"; cover.append(category, use);
    const copy = document.createElement("div"); copy.className = "template-copy"; const title = document.createElement("h3"); title.textContent = template.name;
    const description = document.createElement("p"); description.textContent = template.description; copy.append(title, description); card.append(cover, copy);
    card.addEventListener("click", () => { if (carousel && index !== templateIndex) { setTemplateIndex(index); return; } selectTemplate(template); });
    return card;
  }

  function setTemplateIndex(index) {
    if (!templates.length) return;
    templateIndex = (index + templates.length) % templates.length;
    $("#template-position").textContent = `${String(templateIndex + 1).padStart(2, "0")} / ${String(templates.length).padStart(2, "0")}`;
    Array.from($("#template-grid").children).forEach((card, cardIndex) => {
      let offset = cardIndex - templateIndex;
      if (offset > templates.length / 2) offset -= templates.length;
      if (offset < -templates.length / 2) offset += templates.length;
      card.dataset.offset = Math.abs(offset) <= 2 ? String(offset) : "hidden";
      if (Math.abs(offset) <= 2) loadCover(card.querySelector(".template-cover"));
      card.tabIndex = Math.abs(offset) <= 1 ? 0 : -1;
      card.setAttribute("aria-hidden", Math.abs(offset) <= 1 ? "false" : "true");
    });
  }

  function runCarousel() {
    clearInterval(carouselTimer);
    if (templates.length < 2 || templateView !== "carousel" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    carouselTimer = setInterval(() => {
      const carousel = $("#template-carousel");
      const hovered = window.matchMedia("(hover: hover)").matches && carousel.matches(":hover");
      const focusedCard = document.activeElement && document.activeElement.classList.contains("template-card") && carousel.contains(document.activeElement);
      if (!document.hidden && !hovered && !focusedCard) setTemplateIndex(templateIndex + 1);
    }, 5500);
  }

  function renderTemplateCards() {
    const grid = $("#template-grid"), allGrid = $("#template-all-grid");
    if (coverObserver) coverObserver.disconnect();
    grid.replaceChildren(); allGrid.replaceChildren();
    templates.forEach((template, index) => grid.append(makeTemplateCard(template, index, true)));
    setTemplateIndex(templateIndex);
    const search = $("#template-search").value.trim().toLocaleLowerCase();
    templates.filter((template) => (templateCategory === "全部" || (template.category || "显影模板") === templateCategory)
      && (!search || `${template.name} ${template.description || ""}`.toLocaleLowerCase().includes(search)))
      .forEach((template) => allGrid.append(makeTemplateCard(template, templates.indexOf(template), false)));
    $("#template-search-empty").classList.toggle("hidden", templateView !== "all" || allGrid.children.length > 0);
  }

  function showTemplateView(view) {
    templateView = view;
    const showingAll = view === "all";
    $("#template-carousel").classList.toggle("hidden", showingAll);
    $("#template-carousel-meta").classList.toggle("hidden", showingAll || !templates.length);
    $("#template-filters").classList.toggle("hidden", !showingAll);
    $("#template-all-grid").classList.toggle("hidden", !showingAll);
    $("#template-search-empty").classList.toggle("hidden", !showingAll || $("#template-all-grid").children.length > 0);
    const toggle = $("#template-view-toggle"); toggle.textContent = showingAll ? "返回滚动预览 ↖" : "查看全部模板 ↗";
    toggle.setAttribute("aria-expanded", String(showingAll));
    runCarousel();
  }

  function renderTemplateCategories() {
    const categories = ["全部", ...new Set(templates.map((template) => template.category || "显影模板"))];
    const container = $("#template-categories"); container.replaceChildren();
    categories.forEach((category) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = category;
      button.classList.toggle("active", templateCategory === category);
      button.addEventListener("click", () => { templateCategory = category; renderTemplateCategories(); renderTemplateCards(); });
      container.append(button);
    });
  }

  function selectTemplate(template) {
    selectedTemplate = template; templateIndex = templates.indexOf(template); referenceFiles = []; renderTemplateCards();
    $("#template-config").classList.remove("hidden"); $("#selected-template-name").textContent = template.name; $("#selected-template-description").textContent = template.description;
    const fields = $("#template-fields"); fields.replaceChildren(); (template.fields || []).forEach((field) => fields.append(createTemplateField(field)));
    updateReferenceUpload(); $("#reference-images").value = ""; renderReferencePreview(); prompt.required = false; prompt.maxLength = 2000; prompt.value = ""; prompt.placeholder = "补充要求（可选），可直接粘贴完整的画面方向、文案、颜色和构图要求"; updateCount(); say(`已选择「${template.name}」，填写上方内容后即可生成。`); $("#template-config").scrollIntoView({ behavior: "smooth", block: "nearest" });
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
  function historyTemplateLabel(item) { return item.template_name || "自由创作"; }

  function makeHistoryItem(item) {
    const node = $("#history-template").content.cloneNode(true), btn = node.querySelector(".history-preview");
    const image = node.querySelector("img"); image.alt = "历史生成图片";
    setImage(image, item.thumbnail_url || item.image_url, item.thumbnail_url ? item.image_url : null);
    let badge = node.querySelector(".history-template-badge");
    if (!badge) { badge = document.createElement("div"); badge.className = "history-template-badge"; node.querySelector(".history-item").prepend(badge); }
    const templateLabel = historyTemplateLabel(item);
    badge.textContent = templateLabel; badge.title = `通过「${templateLabel}」生成`;
    badge.classList.toggle("free", !item.template_name);
    btn.title = `查看图片 · ${badge.title}`;
    node.querySelector("small").textContent = new Date(item.created_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    bindDownload(node.querySelector(".history-download"), item);
    btn.addEventListener("click", () => { setImage($("#dialog-image"), item.image_url); $("#image-dialog").showModal(); });
    return node;
  }

  function renderHistory(items) {
    const grid = $("#history-grid"); grid.replaceChildren(); $("#history-empty").classList.toggle("hidden", items.length > 0);
    $("#history-count").textContent = items.length ? `最近 ${Math.min(items.length, 4)} 张` : "";
    $("#history-view-all").classList.toggle("hidden", items.length <= 4);
    items.slice(0, 4).forEach((item) => grid.append(makeHistoryItem(item)));
  }

  function renderArchiveFilters() {
    const container = $("#archive-filters");
    const labels = ["全部", ...new Set(archiveItems.map(historyTemplateLabel))];
    if (!labels.includes(archiveFilter)) archiveFilter = "全部";
    container.replaceChildren();
    labels.forEach((label) => {
      const button = document.createElement("button"); button.type = "button"; button.className = "archive-filter";
      button.textContent = label; button.classList.toggle("active", archiveFilter === label);
      button.setAttribute("aria-pressed", String(archiveFilter === label));
      button.addEventListener("click", () => { archiveFilter = label; renderArchive(); });
      container.append(button);
    });
    container.classList.toggle("hidden", labels.length <= 2);
  }

  function renderArchive() {
    renderArchiveFilters();
    const groups = $("#archive-groups"); groups.replaceChildren();
    const visible = archiveFilter === "全部" ? archiveItems : archiveItems.filter((item) => historyTemplateLabel(item) === archiveFilter);
    const grouped = new Map();
    visible.forEach((item) => { const label = historyTemplateLabel(item); if (!grouped.has(label)) grouped.set(label, []); grouped.get(label).push(item); });
    grouped.forEach((items, label) => {
      const templateHeading = document.createElement("h3"); templateHeading.className = "archive-template"; templateHeading.textContent = label;
      groups.append(templateHeading);
      let currentDate = "", grid = null;
      items.forEach((item) => {
        const date = new Date(item.created_at).toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });
        if (date !== currentDate) {
          currentDate = date;
          const heading = document.createElement("h4"); heading.className = "archive-date"; heading.textContent = date;
          grid = document.createElement("div"); grid.className = "archive-grid"; groups.append(heading, grid);
        }
        if (!archiveCards.has(item.id)) archiveCards.set(item.id, makeHistoryItem(item).firstElementChild);
        grid.append(archiveCards.get(item.id));
      });
    });
    $("#archive-empty").classList.toggle("hidden", visible.length > 0);
    $("#archive-more").classList.toggle("hidden", !archiveHasMore);
  }

  async function loadArchive(reset) {
    if (archiveLoading) return;
    archiveLoading = true;
    const more = $("#archive-more"); more.disabled = true; more.textContent = "正在加载…";
    if (reset) { archiveItems = []; archiveCards.clear(); archiveOffset = 0; archiveHasMore = true; archiveFilter = "全部"; $("#archive-error").classList.add("hidden"); }
    try {
      const response = await request(`/api/imaging/history?limit=24&offset=${archiveOffset}`);
      if (!response.ok) throw new Error("无法读取生成记录，请稍后重试。");
      const items = await response.json();
      archiveItems.push(...items); archiveOffset += items.length; archiveHasMore = items.length === 24;
      $("#archive-error").classList.add("hidden");
      renderArchive();
    } catch (error) {
      say(error.message, true); archiveHasMore = true;
      $("#archive-error").textContent = error.message; $("#archive-error").classList.remove("hidden");
      more.classList.remove("hidden");
    }
    finally { archiveLoading = false; more.disabled = false; more.textContent = "加载更多"; }
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
    setImage($("#download-preview"), job.thumbnail_url || job.image_url, job.thumbnail_url ? job.image_url : null);
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
  async function loadTemplates() {
    const response = await request("/api/imaging/templates"), data = await readJson(response);
    templates = data.items || [];
    renderTemplateCategories(); renderTemplateCards(); showTemplateView(templateView);
    $("#template-view-toggle").classList.toggle("hidden", templates.length < 2);
    $("#template-library-empty").classList.toggle("hidden", templates.length > 0);
  }
  async function loadHistory() { const response = await request("/api/imaging/history?limit=5"); if (response.ok) renderHistory(await response.json()); }
  async function poll(id) {
    if (polling || activeJobId !== id || document.hidden) return;
    polling = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await request(`/api/imaging/generations/${id}`, { signal: controller.signal });
      const job = await response.json();
      if (activeJobId !== id) return;
      pollFailures = 0;
      if (job.status === "queued" || job.status === "generating") {
        setState(job.status === "queued" ? "排队准备中" : "正在生成", "working");
        say(`正在显影画面，已等待 ${Math.floor((Date.now() - startedAt) / 1000)} 秒。`);
        return;
      }
      activeJobId = null; busy(false); forgetJob(id);
      if (job.status === "completed") {
        setState("生成完成"); say("新的画面已保存到你的私有记录。"); showResult(job);
        // A failed sidebar refresh must not turn a finished generation into a failure.
        Promise.allSettled([loadHistory(), loadAccount()]);
      } else {
        setState("生成失败", "failed"); say(job.error || "生成失败，请稍后重试。", true);
        Promise.allSettled([loadAccount()]);
      }
    } catch (error) {
      if (activeJobId !== id) return;
      if (error.status === 401 || error.status === 404) {
        activeJobId = null; busy(false);
        if (error.status === 404) forgetJob(id);
        setState("无法读取任务", "failed"); say(error.message, true);
      } else {
        pollFailures += 1; setState("正在恢复连接", "working");
        say("暂时无法读取进度，任务仍在后台运行，正在自动重试。", true);
      }
    } finally {
      clearTimeout(timeout); polling = false;
      if (activeJobId === id && !document.hidden) {
        timer = setTimeout(() => poll(id), Math.min(30000, 2500 * 2 ** Math.min(pollFailures, 4)));
      }
    }
  }
  async function resumeActiveJob() {
    const active = readActiveJob(); if (!active) return;
    activeJobId = active.id; startedAt = Number(active.startedAt) || Date.now(); busy(true);
    say("正在恢复上次未完成的显影任务。"); await poll(active.id);
  }
  // 站内通知会带 ?job=<id> 直达结果，避免用户回到页面还要自己去历史里翻。
  async function openLinkedJob() {
    const raw = new URLSearchParams(location.search).get("job");
    if (!raw || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raw)) return false;
    try {
      const response = await request(`/api/imaging/generations/${raw}`);
      if (!response.ok) return false;
      const job = await response.json();
      if (job.status === "completed") {
        forgetJob(job.id); setState("生成完成"); say("通知里的画面已经生成，可以查看或下载。"); showResult(job);
        return true;
      }
      if (job.status === "queued" || job.status === "generating") {
        activeJobId = job.id; startedAt = Date.now(); busy(true); rememberJob(job.id);
        setState(job.status === "queued" ? "排队准备中" : "正在生成", "working");
        await poll(job.id);
        return true;
      }
      forgetJob(job.id); setState("生成失败", "failed"); say(job.error || "这次生成没有成功，已自动退回积分。", true);
      return true;
    } catch (_) {
      return false;
    }
  }
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer); timer = null;
    if (!document.hidden && activeJobId && !polling) poll(activeJobId);
  });
  async function submit(event) { event.preventDefault(); if (submitting || activeJobId) return;
    const text = prompt.value.trim(); if (!selectedTemplate && !text) { say("先写下一句画面描述。", true); prompt.focus(); return; } if (selectedTemplate && !form.reportValidity()) return;
    submitting = true; busy(true); startedAt = Date.now(); setState("准备生成", "working"); say("正在提交生成任务。");
    try {
      const payload = { prompt: text, size: $("#size").value, quality: $("#quality").value, output_format: $("#output-format").value };
      if (selectedTemplate) {
        payload.templateKey = selectedTemplate.key; payload.templateValues = templateValues(); payload.extraPrompt = text;
      }
      const signature = JSON.stringify([payload, referenceFiles.map((file) => [file.name, file.size, file.lastModified])]);
      if (signature !== submissionSignature) { submissionSignature = signature; submissionKey = key(); }
      payload.idempotencyKey = submissionKey;
      let body = JSON.stringify(payload);
      if (selectedTemplate) {
        const formData = new FormData(); formData.append("payload", JSON.stringify(payload)); referenceFiles.forEach((file) => formData.append("references", file, file.name)); body = formData;
      }
      const response = await request("/api/imaging/generations", { method: "POST", body });
      const data = await readJson(response); if (response.status === 401) { window.location.href = "/login?next=/imaging"; return; } if (!response.ok) throw new Error(data.error || "创建生成任务失败。");
      submissionSignature = null; submissionKey = null; pollFailures = 0;
      $("#balance").textContent = data.balance; rememberJob(data.id); activeJobId = data.id; await poll(data.id);
    } catch (error) { busy(false); setState("无法开始", "failed"); say(error.message, true); }
    finally { submitting = false; }
  }
  prompt.addEventListener("input", updateCount); prompt.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") form.requestSubmit(); }); $("#reference-images").addEventListener("change", onReferenceChange); form.addEventListener("submit", submit); $("#clear-template").addEventListener("click", clearTemplate);
  $("#template-prev").addEventListener("click", () => setTemplateIndex(templateIndex - 1));
  $("#template-next").addEventListener("click", () => setTemplateIndex(templateIndex + 1));
  $("#template-carousel").addEventListener("keydown", (event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setTemplateIndex(templateIndex + (event.key === "ArrowRight" ? 1 : -1)); } });
  $("#template-view-toggle").addEventListener("click", () => showTemplateView(templateView === "carousel" ? "all" : "carousel"));
  $("#template-search").addEventListener("input", renderTemplateCards);
  $("#history-view-all").addEventListener("click", () => { $("#history-archive").showModal(); loadArchive(true); });
  $("#archive-close").addEventListener("click", () => $("#history-archive").close());
  $("#archive-more").addEventListener("click", () => loadArchive(false));
  $("#history-archive").addEventListener("click", (event) => { if (event.target === $("#history-archive")) $("#history-archive").close(); });
  $("#dialog-close").addEventListener("click", () => $("#image-dialog").close()); $("#image-dialog").addEventListener("click", (event) => { if (event.target === $("#image-dialog")) $("#image-dialog").close(); });
  updateCount(); loadTemplates().catch((error) => { $("#template-library-empty").classList.remove("hidden"); say(error.message, true); }); loadAccount().catch((error) => say(error.message, true)); loadHistory().catch((error) => say(error.message, true));
  openLinkedJob().then((handled) => (handled ? null : resumeActiveJob())).catch((error) => say(error.message, true));
}());
