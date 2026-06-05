const DEFAULT_CONFIG = {
  proxyEndpoint: "/api/agnes/chat",
  model: "agnes-2.0-flash",
  systemPrompt: "You are a helpful AI assistant.",
  temperature: 0.7,
  maxTokens: 8192,
  enableThinking: true,
};

const MODEL_CATALOG = {
  "agnes-2.0-flash": {
    label: "Agnes-2.0-Flash",
    summary: "快速模型，适合多轮对话、推理和高频使用场景。",
    multimodalLabel: "文本对话",
  },
  "agnes-1.5-flash": {
    label: "Agnes-1.5-Flash",
    summary: "兼顾速度和多模态扩展能力的版本。",
    multimodalLabel: "多模态",
  },
};

const CONFIG_KEY = "kflow_chat_config_v2";
const ACTIVE_SESSION_KEY = "kflow_chat_active_session_v2";
const CHAT_CONTEXT_WINDOW_MESSAGES = 12;
const CHAT_CONTEXT_WINDOW_MESSAGES_THINKING = 8;
const CHAT_SUMMARY_MAX_LINES = 16;
const CHAT_SUMMARY_MAX_CHARS = 1800;
const CHAT_SUMMARY_MAX_CHARS_THINKING = 1200;
const RETAIN_THINKING_ON_EMPTY_CONTENT = true;

const nodes = {
  settingsShell: document.getElementById("settingsShell"),
  settingsBackdrop: document.getElementById("settingsBackdrop"),
  openSettingsBtn: document.getElementById("openSettingsBtn"),
  openSettingsNavBtn: document.getElementById("openSettingsNavBtn"),
  openSettingsSidebarBtn: document.getElementById("openSettingsSidebarBtn"),
  mobileSettingsBtn: document.getElementById("mobileSettingsBtn"),
  closeSettingsBtn: document.getElementById("closeSettingsBtn"),
  saveSettingsBtn: document.getElementById("saveSettingsBtn"),
  resetSettingsBtn: document.getElementById("resetSettingsBtn"),
  proxyEndpointInput: document.getElementById("proxyEndpointInput"),
  systemPromptInput: document.getElementById("systemPromptInput"),
  temperatureInput: document.getElementById("temperatureInput"),
  maxTokensInput: document.getElementById("maxTokensInput"),
  settingsModelSelect: document.getElementById("settingsModelSelect"),
  thinkingSwitch: document.getElementById("thinkingSwitch"),
  thinkingChip: document.getElementById("thinkingChip"),
  agentChip: document.getElementById("agentChip"),
  modelSelect: document.getElementById("modelSelect"),
  modelOverview: document.getElementById("modelOverview"),
  modelSummaryName: document.getElementById("modelSummaryName"),
  modelSummaryBadge: document.getElementById("modelSummaryBadge"),
  modelSummaryText: document.getElementById("modelSummaryText"),
  composerForm: document.getElementById("composerForm"),
  composerInput: document.getElementById("composerInput"),
  sendBtn: document.getElementById("sendBtn"),
  messageList: document.getElementById("messageList"),
  chatBrand: document.getElementById("chatBrand"),
  promptGallery: document.getElementById("promptGallery"),
  workspace: document.querySelector(".workspace"),
  historyList: document.getElementById("historyList"),
  newChatBtn: document.getElementById("newChatBtn"),
  newChatInlineBtn: document.getElementById("newChatInlineBtn"),
  requestStatus: document.getElementById("requestStatus"),
  composerHint: document.getElementById("composerHint"),
  notice: document.getElementById("notice"),
  accountName: document.getElementById("accountName"),
  accountRole: document.getElementById("accountRole"),
  accountAvatar: document.getElementById("accountAvatar"),
  loginActionLink: document.getElementById("loginActionLink"),
};

let serverChatConfig = getServerChatConfigDefaults();
let config = loadConfig();
let account = { loggedIn: false, role: "guest", username: "guest" };
let sessions = [];
let activeSessionId = "";
let isSending = false;
let modelOverviewTimer = 0;
let pendingSessionPollTimer = 0;
let isPollingSessions = false;
let lastAnimatedSessionId = "";
let lastAnimatedMessageCount = 0;

void init();

async function init() {
  bindGlobalEvents();
  bindSettingsEvents();
  bindComposerEvents();
  bindPromptShortcuts();
  syncSettingsForm();
  syncComposerHint();
  renderAll();
  await hydrateServerChatConfig();
  await hydrateAccount();
}

function bindGlobalEvents() {
  window.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key || "").toLowerCase() === "k") {
      event.preventDefault();
      void createSession();
    }
    if (event.key === "Escape" && nodes.settingsShell?.classList.contains("open")) {
      closeSettings();
    }
  });
}

function bindSettingsEvents() {
  [nodes.openSettingsBtn, nodes.openSettingsNavBtn, nodes.openSettingsSidebarBtn, nodes.mobileSettingsBtn].forEach((node) => {
    if (node) node.addEventListener("click", openSettings);
  });
  nodes.closeSettingsBtn?.addEventListener("click", closeSettings);
  nodes.settingsBackdrop?.addEventListener("click", closeSettings);
  nodes.settingsModelSelect?.addEventListener("change", (event) => {
    setActiveModel(event.target?.value || getEffectiveDefaultConfig().model);
  });
  nodes.thinkingSwitch?.addEventListener("click", () => {
    config.enableThinking = !config.enableThinking;
    persistConfig();
    syncThinkingState();
    syncComposerHint();
  });
  nodes.thinkingChip?.addEventListener("click", () => {
    config.enableThinking = !config.enableThinking;
    persistConfig();
    syncThinkingState();
    syncComposerHint();
  });
  nodes.agentChip?.addEventListener("click", () => {
    showNotice("当前页面先支持基础对话和 Thinking 开关，工具链后续再接入。", "success");
  });
  nodes.saveSettingsBtn?.addEventListener("click", () => {
    const defaults = getEffectiveDefaultConfig();
    config.model = sanitizeModel(nodes.settingsModelSelect?.value || config.model);
    config.systemPrompt = (nodes.systemPromptInput?.value || "").trim() || defaults.systemPrompt;
    config.temperature = clampNumber(nodes.temperatureInput?.value, 0, 2, defaults.temperature);
    config.maxTokens = clampNumber(nodes.maxTokensInput?.value, 128, 65535, defaults.maxTokens);
    config = applyManagedFrontendConfig(config);
    persistConfig();
    syncSettingsForm();
    syncComposerHint();
    closeSettings();
    showNotice("对话设置已保存。", "success");
  });
  nodes.resetSettingsBtn?.addEventListener("click", () => {
    config = cloneDefaultConfig();
    persistConfig();
    syncSettingsForm();
    syncComposerHint();
    showNotice("已恢复默认设置。", "success");
  });
}

function bindComposerEvents() {
  nodes.composerInput?.addEventListener("input", () => {
    updateSendState();
    storeDraftPrompt();
  });
  nodes.composerInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      nodes.composerForm?.requestSubmit();
    }
  });
  nodes.composerForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await handleSend();
  });
  nodes.modelSelect?.addEventListener("change", (event) => {
    setActiveModel(event.target?.value || getEffectiveDefaultConfig().model);
  });
  nodes.newChatBtn?.addEventListener("click", () => void createSession());
  nodes.newChatInlineBtn?.addEventListener("click", () => void createSession());
}

function bindPromptShortcuts() {
  document.querySelectorAll(".prompt-shortcut").forEach((button) => {
    button.addEventListener("click", () => {
      if (!account.loggedIn) {
        showLoginRequiredNotice();
        return;
      }
      if (!nodes.composerInput) return;
      nodes.composerInput.value = button.dataset.prompt || "";
      nodes.composerInput.focus();
      updateSendState();
      storeDraftPrompt();
    });
  });
}

function getServerChatConfigDefaults() {
  return {
    default_model: DEFAULT_CONFIG.model,
    default_system_prompt: DEFAULT_CONFIG.systemPrompt,
    default_temperature: DEFAULT_CONFIG.temperature,
    default_max_tokens: DEFAULT_CONFIG.maxTokens,
    default_enable_thinking: DEFAULT_CONFIG.enableThinking,
    context_window_messages: CHAT_CONTEXT_WINDOW_MESSAGES,
    thinking_context_window_messages: CHAT_CONTEXT_WINDOW_MESSAGES_THINKING,
    summary_max_lines: CHAT_SUMMARY_MAX_LINES,
    summary_max_chars: CHAT_SUMMARY_MAX_CHARS,
    thinking_summary_max_chars: CHAT_SUMMARY_MAX_CHARS_THINKING,
    retain_thinking_on_empty_content: RETAIN_THINKING_ON_EMPTY_CONTENT,
    proxy_endpoint: DEFAULT_CONFIG.proxyEndpoint,
  };
}

function getEffectiveDefaultConfig() {
  return {
    proxyEndpoint: String(serverChatConfig.proxy_endpoint || DEFAULT_CONFIG.proxyEndpoint || "").trim() || DEFAULT_CONFIG.proxyEndpoint,
    model: String(serverChatConfig.default_model || DEFAULT_CONFIG.model || "").trim() || DEFAULT_CONFIG.model,
    systemPrompt:
      String(serverChatConfig.default_system_prompt || DEFAULT_CONFIG.systemPrompt || "").trim() || DEFAULT_CONFIG.systemPrompt,
    temperature: clampNumber(
      serverChatConfig.default_temperature,
      0,
      2,
      DEFAULT_CONFIG.temperature
    ),
    maxTokens: clampNumber(
      serverChatConfig.default_max_tokens,
      128,
      65535,
      DEFAULT_CONFIG.maxTokens
    ),
    enableThinking: Boolean(serverChatConfig.default_enable_thinking),
  };
}

function normalizeServerChatConfig(item, proxyEndpoint) {
  const base = getServerChatConfigDefaults();
  const payload = item && typeof item === "object" ? item : {};
  const summaryMaxChars = clampNumber(payload.summary_max_chars, 0, 12000, base.summary_max_chars);
  const contextWindow = clampNumber(payload.context_window_messages, 1, 64, base.context_window_messages);
  return {
    default_model: String(payload.default_model || base.default_model).trim() || base.default_model,
    default_system_prompt: String(payload.default_system_prompt || base.default_system_prompt).trim() || base.default_system_prompt,
    default_temperature: clampNumber(payload.default_temperature, 0, 2, base.default_temperature),
    default_max_tokens: clampNumber(payload.default_max_tokens, 128, 65535, base.default_max_tokens),
    default_enable_thinking:
      typeof payload.default_enable_thinking === "boolean"
        ? payload.default_enable_thinking
        : Boolean(base.default_enable_thinking),
    context_window_messages: contextWindow,
    thinking_context_window_messages: clampNumber(
      payload.thinking_context_window_messages,
      1,
      contextWindow,
      base.thinking_context_window_messages
    ),
    summary_max_lines: clampNumber(payload.summary_max_lines, 0, 64, base.summary_max_lines),
    summary_max_chars: summaryMaxChars,
    thinking_summary_max_chars: Math.min(
      clampNumber(payload.thinking_summary_max_chars, 0, 12000, base.thinking_summary_max_chars),
      summaryMaxChars || clampNumber(payload.thinking_summary_max_chars, 0, 12000, base.thinking_summary_max_chars)
    ),
    retain_thinking_on_empty_content:
      typeof payload.retain_thinking_on_empty_content === "boolean"
        ? payload.retain_thinking_on_empty_content
        : Boolean(base.retain_thinking_on_empty_content),
    proxy_endpoint: String(proxyEndpoint || payload.proxy_endpoint || base.proxy_endpoint || "").trim() || base.proxy_endpoint,
  };
}

function getContextStrategy() {
  return {
    recentWindow: config.enableThinking
      ? clampNumber(
          serverChatConfig.thinking_context_window_messages,
          1,
          clampNumber(serverChatConfig.context_window_messages, 1, 64, CHAT_CONTEXT_WINDOW_MESSAGES),
          CHAT_CONTEXT_WINDOW_MESSAGES_THINKING
        )
      : clampNumber(serverChatConfig.context_window_messages, 1, 64, CHAT_CONTEXT_WINDOW_MESSAGES),
    summaryMaxLines: clampNumber(serverChatConfig.summary_max_lines, 0, 64, CHAT_SUMMARY_MAX_LINES),
    summaryMaxChars: config.enableThinking
      ? clampNumber(
          serverChatConfig.thinking_summary_max_chars,
          0,
          clampNumber(serverChatConfig.summary_max_chars, 0, 12000, CHAT_SUMMARY_MAX_CHARS),
          CHAT_SUMMARY_MAX_CHARS_THINKING
        )
      : clampNumber(serverChatConfig.summary_max_chars, 0, 12000, CHAT_SUMMARY_MAX_CHARS),
    retainThinkingOnEmptyContent: Boolean(serverChatConfig.retain_thinking_on_empty_content),
  };
}

function cloneDefaultConfig() {
  return JSON.parse(JSON.stringify(getEffectiveDefaultConfig()));
}

function applyManagedFrontendConfig(source) {
  const defaults = getEffectiveDefaultConfig();
  return {
    ...source,
    proxyEndpoint: defaults.proxyEndpoint,
  };
}

function loadConfig() {
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    if (!raw) return applyManagedFrontendConfig(cloneDefaultConfig());
    return applyManagedFrontendConfig({ ...cloneDefaultConfig(), ...JSON.parse(raw) });
  } catch {
    return applyManagedFrontendConfig(cloneDefaultConfig());
  }
}

function persistConfig() {
  config = applyManagedFrontendConfig(config);
  localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
}

async function hydrateServerChatConfig() {
  try {
    const hadStoredConfig = Boolean(localStorage.getItem(CONFIG_KEY));
    const response = await fetch("/api/agnes/chat-config", { credentials: "same-origin" });
    const data = response.ok ? await response.json().catch(() => ({})) : {};
    serverChatConfig = normalizeServerChatConfig(data?.item, data?.proxy_endpoint);
    if (hadStoredConfig) {
      config = applyManagedFrontendConfig({ ...cloneDefaultConfig(), ...config });
    } else {
      config = applyManagedFrontendConfig(cloneDefaultConfig());
    }
    syncSettingsForm();
    syncComposerHint();
    renderAll();
  } catch {
    serverChatConfig = getServerChatConfigDefaults();
  }
}

function openSettings() {
  syncSettingsForm();
  nodes.settingsShell?.classList.add("open");
  nodes.settingsShell?.setAttribute("aria-hidden", "false");
}

function closeSettings() {
  nodes.settingsShell?.classList.remove("open");
  nodes.settingsShell?.setAttribute("aria-hidden", "true");
}

function sanitizeModel(value) {
  const raw = String(value || "").trim();
  return raw || getEffectiveDefaultConfig().model || DEFAULT_CONFIG.model;
}

function getModelMeta(value = config.model) {
  const key = sanitizeModel(value);
  if (Object.prototype.hasOwnProperty.call(MODEL_CATALOG, key)) {
    return { key, ...MODEL_CATALOG[key] };
  }
  return {
    key,
    label: key,
    summary: "当前为自定义模型标识，页面未内置该模型的说明文案。",
    multimodalLabel: "待确认",
  };
}

function renderModelOptions(selectedModel) {
  const active = sanitizeModel(selectedModel);
  const entries = Object.entries(MODEL_CATALOG);
  if (!Object.prototype.hasOwnProperty.call(MODEL_CATALOG, active)) {
    entries.unshift([active, { label: `${active} (Custom)` }]);
  }
  return entries
    .map(([key, meta]) => `<option value="${escapeHtml(key)}"${key === active ? " selected" : ""}>${escapeHtml(meta.label)}</option>`)
    .join("");
}

function syncModelInfo() {
  const model = sanitizeModel(config.model || getEffectiveDefaultConfig().model);
  const meta = getModelMeta(model);
  if (nodes.modelSelect) nodes.modelSelect.innerHTML = renderModelOptions(model);
  if (nodes.settingsModelSelect) nodes.settingsModelSelect.innerHTML = renderModelOptions(model);
  if (nodes.modelSummaryName) nodes.modelSummaryName.textContent = meta.label;
  if (nodes.modelSummaryText) nodes.modelSummaryText.textContent = meta.summary;
  if (nodes.modelSummaryBadge) nodes.modelSummaryBadge.textContent = meta.multimodalLabel;
}

function setActiveModel(value, persist = true) {
  const previous = sanitizeModel(config.model || getEffectiveDefaultConfig().model);
  config.model = sanitizeModel(value);
  if (persist) persistConfig();
  syncSettingsForm();
  syncComposerHint();
  if (previous !== config.model) showModelOverview();
}

function showModelOverview() {
  if (!nodes.modelOverview) return;
  if (modelOverviewTimer) window.clearTimeout(modelOverviewTimer);
  nodes.modelOverview.classList.remove("model-overview-hidden");
  modelOverviewTimer = window.setTimeout(() => {
    nodes.modelOverview?.classList.add("model-overview-hidden");
    modelOverviewTimer = 0;
  }, 3000);
}

function getActiveSessionStorageKey() {
  const scope = account.loggedIn ? `${account.role}:${account.username || "account"}` : "guest";
  return `${ACTIVE_SESSION_KEY}:${scope}`;
}

function getDraftStorageKey(sessionId) {
  const scope = account.loggedIn ? `${account.role}:${account.username || "account"}` : "guest";
  return `kflow_chat_draft:${scope}:${String(sessionId || "")}`;
}

function persistActiveSession() {
  localStorage.setItem(getActiveSessionStorageKey(), activeSessionId || "");
}

function ensureSession() {
  if (sessions.length) {
    if (!sessions.some((item) => String(item.id) === String(activeSessionId))) {
      activeSessionId = String(sessions[0].id || "");
    }
    persistActiveSession();
    return;
  }
  activeSessionId = "";
}

async function createRemoteSession(focusInput = true) {
  const defaults = getEffectiveDefaultConfig();
  const response = await fetch("/api/agnes/chat-sessions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: "新对话",
      model: config.model || defaults.model,
      system_prompt: config.systemPrompt || defaults.systemPrompt,
      enable_thinking: Boolean(config.enableThinking),
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data?.item) {
    const message = data?.error || data?.message || `HTTP ${response.status}`;
    throw new Error(`创建会话失败: ${message}`);
  }
  const session = mapRemoteSession(data.item);
  sessions = [session, ...sessions.filter((item) => String(item.id) !== String(session.id))];
  sortSessionsArray(sessions);
  activeSessionId = String(session.id);
  persistActiveSession();
  renderAll();
  clearDraftPrompt();
  if (focusInput) nodes.composerInput?.focus();
  return session;
}

async function createSession(focusInput = true) {
  if (!account.loggedIn) {
    showLoginRequiredNotice();
    return null;
  }
  try {
    return await createRemoteSession(focusInput);
  } catch (error) {
    showNotice(error.message || "请先登录后再开始对话。", "error");
    return null;
  }
}

function getActiveSession() {
  return sessions.find((item) => String(item.id) === String(activeSessionId)) || null;
}

function setActiveSession(sessionId) {
  activeSessionId = String(sessionId || "");
  persistActiveSession();
  renderAll();
  restoreDraftPrompt();
  nodes.composerInput?.focus();
}

function touchSession(session, updatedAt = Date.now()) {
  session.updatedAt = updatedAt;
  sortSessionsArray(sessions);
}

function syncSettingsForm() {
  const defaults = getEffectiveDefaultConfig();
  config.model = sanitizeModel(config.model || defaults.model);
  if (nodes.proxyEndpointInput) nodes.proxyEndpointInput.value = config.proxyEndpoint || defaults.proxyEndpoint;
  if (nodes.systemPromptInput) nodes.systemPromptInput.value = config.systemPrompt || defaults.systemPrompt;
  if (nodes.temperatureInput) nodes.temperatureInput.value = String(config.temperature ?? defaults.temperature);
  if (nodes.maxTokensInput) nodes.maxTokensInput.value = String(config.maxTokens ?? defaults.maxTokens);
  syncModelInfo();
  syncThinkingState();
}

function syncThinkingState() {
  const active = Boolean(config.enableThinking);
  nodes.thinkingSwitch?.classList.toggle("active", active);
  nodes.thinkingSwitch?.setAttribute("aria-pressed", active ? "true" : "false");
  nodes.thinkingChip?.classList.toggle("active", active);
}

function syncComposerHint() {
  if (!nodes.composerHint) return;
  const defaults = getEffectiveDefaultConfig();
  const meta = getModelMeta(config.model || defaults.model);
  const thinkingText = config.enableThinking ? "Thinking 已开启" : "Thinking 已关闭";
  nodes.composerHint.innerHTML =
    `模型 <code>${escapeHtml(meta.label)}</code>，能力 ${escapeHtml(meta.multimodalLabel)}，接口 <code>${escapeHtml(config.proxyEndpoint || defaults.proxyEndpoint)}</code>，${escapeHtml(thinkingText)}`;
}

function hasPendingMessages() {
  return sessions.some((session) =>
    Array.isArray(session?.messages) &&
    session.messages.some((message) => message && message.role === "assistant" && ["pending", "queued", "in_progress"].includes(String(message.status || "")))
  );
}

function stopPendingSessionPolling() {
  if (pendingSessionPollTimer) {
    window.clearInterval(pendingSessionPollTimer);
    pendingSessionPollTimer = 0;
  }
}

async function refreshPendingSessions() {
  if (!account.loggedIn || isPollingSessions || !hasPendingMessages()) {
    if (!hasPendingMessages()) stopPendingSessionPolling();
    return;
  }
  isPollingSessions = true;
  const before = JSON.stringify(sessions.map((s) => ({ id: s.id, updatedAt: s.updatedAt, msgCount: s.messages?.length })));
  try {
    await loadRemoteSessions();
    // Only re-render if something actually changed
    const after = JSON.stringify(sessions.map((s) => ({ id: s.id, updatedAt: s.updatedAt, msgCount: s.messages?.length })));
    if (before !== after) {
      renderMessages();
      renderHistory();
    }
  } catch {
    // keep silent during background polling
  } finally {
    isPollingSessions = false;
  }
}

function syncPendingSessionPolling() {
  if (!account.loggedIn || !hasPendingMessages()) {
    stopPendingSessionPolling();
    return;
  }
  if (pendingSessionPollTimer) return;
  pendingSessionPollTimer = window.setInterval(() => {
    void refreshPendingSessions();
  }, 2000);
}

function renderAll() {
  renderHistory();
  renderMessages();
  syncComposerHint();
  syncSettingsForm();
  updateSendState();
  syncPendingSessionPolling();
}

function renderHistory() {
  if (!nodes.historyList) return;
  if (!account.loggedIn) {
    nodes.historyList.innerHTML = '<div class="history-empty">请先登录后查看和保存对话记录。</div>';
    return;
  }
  if (!sessions.length) {
    nodes.historyList.innerHTML = '<div class="history-empty">当前账号还没有对话记录，点击“新建对话”开始。</div>';
    return;
  }

  nodes.historyList.innerHTML = sessions
    .map((session) => {
      const active = String(session.id) === String(activeSessionId) ? " active" : "";
      return (
        `<div class="history-item-wrap">` +
        `<button type="button" class="history-item${active}" data-session-id="${escapeHtml(String(session.id))}">` +
        `<span class="history-dot">#</span>` +
        `<span class="history-meta">` +
        `<span class="history-title">${escapeHtml(session.title || "未命名对话")}</span>` +
        `<span class="history-time">${escapeHtml(formatTime(session.updatedAt))}</span>` +
        `</span>` +
        `</button>` +
        `<button type="button" class="history-del-btn" data-del-session-id="${escapeHtml(String(session.id))}" title="删除对话">×</button>` +
        `</div>`
      );
    })
    .join("");

  nodes.historyList.querySelectorAll("[data-session-id]").forEach((node) => {
    node.addEventListener("click", () => setActiveSession(node.dataset.sessionId || ""));
  });
  nodes.historyList.querySelectorAll("[data-del-session-id]").forEach((node) => {
    node.addEventListener("click", async (e) => {
      e.stopPropagation();
      const sid = node.dataset.delSessionId || "";
      if (!sid) return;
      if (!window.confirm("确认删除此对话？此操作不可恢复。")) return;
      try {
        const res = await fetch(`/api/agnes/chat-sessions/${sid}`, {
          method: "DELETE",
          credentials: "same-origin",
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || "删除失败");
        }
        sessions = sessions.filter((s) => String(s.id) !== sid);
        if (activeSessionId === sid) {
          activeSessionId = sessions.length > 0 ? String(sessions[0].id) : "";
        }
        renderAll();
      } catch (err) {
        showNotice(err.message || "删除对话失败", "error");
      }
    });
  });
}

function renderMessages() {
  const session = getActiveSession();
  const sessionId = String(session?.id || "");
  const messages = session?.messages || [];
  const hasMessages = messages.length > 0;

  nodes.workspace?.classList.toggle("has-messages", hasMessages);
  nodes.workspace?.classList.toggle("is-empty", !hasMessages);
  nodes.messageList?.classList.toggle("active", hasMessages);
  nodes.chatBrand?.classList.toggle("hidden", hasMessages);
  nodes.promptGallery?.classList.toggle("hidden", hasMessages);

  if (!nodes.messageList) return;
  if (!hasMessages) {
    nodes.messageList.innerHTML = "";
    lastAnimatedSessionId = sessionId;
    lastAnimatedMessageCount = 0;
    if (nodes.requestStatus) {
      nodes.requestStatus.textContent = account.loggedIn ? "准备就绪" : "请先登录后开始对话";
    }
    return;
  }

  const animateFromIndex =
    sessionId === lastAnimatedSessionId && messages.length > lastAnimatedMessageCount ? lastAnimatedMessageCount : -1;

  nodes.messageList.innerHTML = messages
    .map((message, index) => {
      const isUser = message.role === "user";
      const avatar = isUser ? "U" : "AI";
      const messageStatus = String(message.status || (message.loading ? "in_progress" : "completed"));
      const isPending = !isUser && ["pending", "queued", "in_progress"].includes(messageStatus);
      const isFailed = !isUser && messageStatus === "failed";
      const showThinking = !isUser && Boolean(message.enableThinking) && (Boolean((message.thinking || "").trim()) || isPending);
      const thinkingMarkup = showThinking
        ? `
          <section class="thinking-box">
            <div class="thinking-box-head">思考过程</div>
            <div class="thinking-box-body">${escapeHtml((message.thinking || "").trim() || "思考中...")}</div>
          </section>
        `
        : "";
      const contentValue = isUser
        ? message.content || ""
        : (message.content || "").trim() || (isPending ? "正在生成回复..." : (isFailed ? `生成失败：${message.errorText || "请稍后重试"}` : ""));
      const contentClass = isUser ? "" : " message-markdown";
      const contentMarkup = isUser ? renderPlainText(contentValue) : renderMarkdown(contentValue);
      return `
        <article class="message-row ${isUser ? "user" : "assistant"}" data-message-index="${index}">
          ${isUser ? "" : `<div class="message-avatar">${avatar}</div>`}
          <div class="message-bubble${isPending ? " loading" : ""}">
            ${thinkingMarkup}
            <div class="message-text${contentClass}${isPending ? " loading" : ""}">${contentMarkup}</div>
          </div>
          ${isUser ? `<div class="message-avatar">${avatar}</div>` : ""}
        </article>
      `;
    })
    .join("");

  requestAnimationFrame(() => {
    if (animateFromIndex >= 0) {
      nodes.messageList?.querySelectorAll(".message-row").forEach((node) => {
        const index = Number(node.getAttribute("data-message-index") || "-1");
        if (index >= animateFromIndex) {
          node.classList.add("message-enter");
        }
      });
    }
    if (nodes.messageList) nodes.messageList.scrollTop = nodes.messageList.scrollHeight;
    document.querySelectorAll(".thinking-box-body").forEach((node) => {
      node.scrollTop = node.scrollHeight;
    });
  });

  lastAnimatedSessionId = sessionId;
  lastAnimatedMessageCount = messages.length;

  if (nodes.requestStatus) {
    nodes.requestStatus.textContent = `共 ${messages.length} 条消息，最近更新 ${formatTime(session.updatedAt)}`;
  }
}

function renderPlainText(value) {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function renderInlineMarkdown(value) {
  const segments = String(value || "").split(/(`[^`\n]+`)/g);
  return segments
    .map((segment) => {
      if (/^`[^`\n]+`$/.test(segment)) {
        return `<code>${escapeHtml(segment.slice(1, -1))}</code>`;
      }
      return escapeHtml(segment)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/~~(.+?)~~/g, "<del>$1</del>")
        .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href=\"$2\" target=\"_blank\" rel=\"noreferrer\">$1</a>');
    })
    .join("");
}

function buildCodeBlock(lines, language) {
  const lang = escapeHtml(language || "text");
  const content = escapeHtml(lines.join("\n"));
  return `<pre class=\"message-code\"><div class=\"message-code-head\">${lang}</div><code>${content}</code></pre>`;
}

function renderMarkdown(value) {
  const lines = String(value || "").replace(/\r/g, "").split("\n");
  const html = [];
  let paragraph = [];
  let codeLines = [];
  let codeLanguage = "";
  let inCode = false;
  let inTable = false;
  let tableRows = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    html.push(`<p>${renderInlineMarkdown(paragraph.join("<br>"))}</p>`);
    paragraph = [];
  }

  function flushCode() {
    if (!codeLines.length) return;
    html.push(buildCodeBlock(codeLines, codeLanguage));
    codeLines = [];
    codeLanguage = "";
  }

  function flushTable() {
    if (!tableRows.length) return;
    const header = tableRows[0];
    const body = tableRows.slice(1);
    let table = "<table class=\"message-table\"><thead><tr>";
    header.forEach((cell) => { table += `<th>${renderInlineMarkdown(cell)}</th>`; });
    table += "</tr></thead><tbody>";
    body.forEach((row) => {
      table += "<tr>";
      row.forEach((cell) => { table += `<td>${renderInlineMarkdown(cell)}</td>`; });
      table += "</tr>";
    });
    table += "</tbody></table>";
    html.push(table);
    tableRows = [];
    inTable = false;
  }

  lines.forEach((line) => {
    if (line.startsWith("```")) {
      if (inCode) { flushCode(); } else { flushParagraph(); }
      inCode = !inCode;
      return;
    }
    if (inCode) { codeLines.push(line); return; }

    // Table: detect pipe-separated rows
    const isTableLine = line.trim().startsWith("|") && line.trim().endsWith("|");
    const isTableSep = /^\|[\s\-:|]+\|$/.test(line.trim());
    if (isTableLine && !isTableSep) {
      if (!inTable) { flushParagraph(); inTable = true; }
      const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      tableRows.push(cells);
      return;
    }
    if (isTableSep && inTable) {
      tableRows.push(null); // mark separator, ignored
      return;
    }
    if (inTable) { flushTable(); }

    // Headers
    if (/^#{1,6}\s+/.test(line)) {
      flushParagraph();
      const m = line.match(/^(#{1,6})\s+(.+)/);
      const level = Math.min(6, m[1].length);
      html.push(`<h${level} class=\"message-h\">${renderInlineMarkdown(m[2])}</h${level}>`);
      return;
    }

    // Blockquote
    if (/^>\s?/.test(line)) {
      flushParagraph();
      html.push(`<blockquote class=\"message-blockquote\"><p>${renderInlineMarkdown(line.replace(/^>\s?/, ""))}</p></blockquote>`);
      return;
    }

    // Horizontal rule
    if (/^[-*_]{3,}\s*$/.test(line)) {
      flushParagraph();
      html.push("<hr class=\"message-hr\">");
      return;
    }

    // Unordered list
    if (/^\s*[-*]\s+/.test(line)) {
      flushParagraph();
      html.push(`<li>${renderInlineMarkdown(line.replace(/^\s*[-*]\s+/, ""))}</li>`);
      return;
    }

    // Ordered list
    if (/^\s*\d+[\.\)]\s+/.test(line)) {
      flushParagraph();
      html.push(`<li class=\"message-ol\">${renderInlineMarkdown(line.replace(/^\s*\d+[\.\)]\s+/, ""))}</li>`);
      return;
    }

    if (!line.trim()) {
      flushParagraph();
      return;
    }

    paragraph.push(line);
  });

  flushParagraph();
  flushTable();
  if (inCode) flushCode();

  return html.join("") || `<p>${renderInlineMarkdown(String(value || ""))}</p>`;
}

async function handleSend() {
  const content = (nodes.composerInput?.value || "").trim();
  if (!account.loggedIn) {
    showLoginRequiredNotice();
    return;
  }
  if (!content || isSending) return;

  let session = getActiveSession();
  if (!session) {
    session = await createSession(false);
    if (!session) return;
  }

  hideNotice();
  const createdAt = Date.now();
  session.messages.push({ role: "user", content, thinking: "", enableThinking: false, loading: false, createdAt });
  session.title = buildSessionTitle(content);
  session.systemPrompt = config.systemPrompt || getEffectiveDefaultConfig().systemPrompt;
  session.model = config.model || getEffectiveDefaultConfig().model;
  session.enableThinking = Boolean(config.enableThinking);
  touchSession(session, createdAt);

  if (nodes.composerInput) nodes.composerInput.value = "";
  clearDraftPrompt();

  const loadingMessage = {
    role: "assistant",
    content: "",
    thinking: "",
    enableThinking: Boolean(config.enableThinking),
    taskId: "",
    status: "in_progress",
    errorText: "",
    finishReason: "",
    loading: true,
    createdAt: Date.now(),
  };
  session.messages.push(loadingMessage);
  renderAll();

  isSending = true;
  updateSendState();
  if (nodes.requestStatus) {
    nodes.requestStatus.textContent = "请求中...";
  }

  try {
    const result = await requestAgnes(
      session.messages.filter((item) => !item.loading && item.role !== "system").map((item) => ({ role: item.role, content: item.content })),
      session,
      (delta) => {
        loadingMessage.content = delta.content || loadingMessage.content;
        loadingMessage.thinking = delta.thinking || loadingMessage.thinking || "";
        loadingMessage.status = "in_progress";
        loadingMessage.loading = true;
        if (delta.usage && nodes.requestStatus) {
          nodes.requestStatus.textContent = buildUsageStatus("流式输出", delta.usage, delta.finishReason || "");
        }
        renderMessages();
      }
    );
    loadingMessage.content = result.content || loadingMessage.content;
    loadingMessage.thinking = result.thinking || loadingMessage.thinking || "";
    loadingMessage.status = "completed";
    loadingMessage.loading = false;
    loadingMessage.finishReason = result.finishReason || "";
    if (nodes.requestStatus) {
      nodes.requestStatus.textContent = buildUsageStatus("完成", result.usage, result.finishReason);
    }
    renderMessages();
    await loadRemoteSessions();
    sortSessionsArray(sessions);
  } catch (error) {
    loadingMessage.status = "failed";
    loadingMessage.errorText = error.message;
    loadingMessage.loading = false;
    renderMessages();
    showNotice(error.message || "调用 Agnes 失败。", "error");
  } finally {
    isSending = false;
    updateSendState();
  }
}

async function enqueueChatTask(chatMessages, session) {
  const requestBody = buildRequestBody(chatMessages, session);
  requestBody.async = true;
  requestBody.stream = true;
  let response;
  try {
    response = await fetch(config.proxyEndpoint || getEffectiveDefaultConfig().proxyEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
  } catch {
    throw new Error("无法连接到本站 Agnes 代理接口，请确认服务端正在运行。");
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.error?.message || data?.detail || data?.error || data?.message || `HTTP ${response.status}`;
    if (response.status === 401) {
      throw new Error("请先登录后再使用 Agnes Chat。");
    }
    if (response.status === 503 && String(message).toLowerCase().includes("api key")) {
      throw new Error("当前没有可用的 Agnes API Key，请在后台启用 Agnes key，或在 .env 中配置 AGNES_CHAT_API_KEY。");
    }
    throw new Error(`Agnes 入队失败: ${message}`);
  }
  return data || {};
}

async function requestAgnes(chatMessages, session, onDelta) {
  const defaults = getEffectiveDefaultConfig();
  const strategy = getContextStrategy();
  const requestBody = buildRequestBody(chatMessages, session);
  if (nodes.requestStatus) nodes.requestStatus.textContent = `请求中: model=${requestBody.model}`;

  let response;
  try {
    response = await fetch(config.proxyEndpoint || defaults.proxyEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
  } catch {
    throw new Error("无法连接到本站 Agnes 代理接口，请确认服务端正在运行。");
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message = data?.error?.message || data?.detail || data?.error || data?.message || `HTTP ${response.status}`;
    if (response.status === 401) {
      throw new Error("请先登录后再使用 Agnes Chat。");
    }
    if (response.status === 503 && String(message).toLowerCase().includes("api key")) {
      throw new Error("当前没有可用的 Agnes API Key，请在后台启用 Agnes key，或在 .env 中配置 AGNES_CHAT_API_KEY。");
    }
    throw new Error(`Agnes 返回失败: ${message}`);
  }

  const contentType = (response.headers.get("Content-Type") || "").toLowerCase();
  if (!contentType.includes("text/event-stream")) {
    const data = await response.json().catch(() => ({}));
    const message = data?.choices?.[0]?.message || {};
    const content = typeof message?.content === "string" ? message.content : "";
    const thinking = extractThinkingText(message) || extractThinkingText(data?.choices?.[0]) || extractThinkingText(data) || "";
    if (!content.trim()) {
      if (thinking.trim() && strategy.retainThinkingOnEmptyContent) {
        const fallbackContent = "本次响应仅返回思考过程，未收到最终答复。";
        if (typeof onDelta === "function") onDelta({ content: fallbackContent, thinking, usage: data?.usage || null, finishReason: data?.choices?.[0]?.finish_reason || "" });
        if (nodes.requestStatus) nodes.requestStatus.textContent = buildUsageStatus("请求完成", data?.usage || null, data?.choices?.[0]?.finish_reason || "");
        return { content: fallbackContent, thinking: thinking.trim(), usage: data?.usage || null, finishReason: data?.choices?.[0]?.finish_reason || "" };
      }
      throw new Error("Agnes 返回成功，但响应内容为空。");
    }
    if (typeof onDelta === "function") onDelta({ content, thinking, usage: data?.usage || null, finishReason: data?.choices?.[0]?.finish_reason || "" });
    if (nodes.requestStatus) nodes.requestStatus.textContent = buildUsageStatus("请求完成", data?.usage || null, data?.choices?.[0]?.finish_reason || "");
    return { content: content.trim(), thinking: thinking.trim(), usage: data?.usage || null, finishReason: data?.choices?.[0]?.finish_reason || "" };
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("浏览器当前无法读取流式响应。");

  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalText = "";
  let finalThinking = "";
  let usage = null;
  let finishReason = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";

    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (!parsed) continue;
      if (parsed.error) throw new Error(parsed.error);
      if (parsed.delta) finalText = mergeText(finalText, parsed.delta);
      if (parsed.thinking) finalThinking = mergeText(finalThinking, parsed.thinking);
      if (parsed.usage) usage = parsed.usage;
      if (parsed.finishReason) finishReason = parsed.finishReason;
      if ((parsed.delta || parsed.thinking || parsed.usage) && typeof onDelta === "function") {
        onDelta({ content: finalText, thinking: finalThinking, usage, finishReason });
      }
      if (parsed.done) {
        if (!finalText.trim()) {
          if (finalThinking.trim() && strategy.retainThinkingOnEmptyContent) {
            const fallbackContent = "本次响应仅返回思考过程，未收到最终答复。";
            if (nodes.requestStatus) nodes.requestStatus.textContent = buildUsageStatus("Streaming", usage, finishReason);
            return { content: fallbackContent, thinking: finalThinking.trim(), usage, finishReason };
          }
          if (finalThinking.trim()) {
            throw new Error("Thinking 已结束，但模型没有返回最终回答。通常是上下文过长，或 Thinking 阶段耗尽了输出预算。");
          }
          throw new Error("流式响应结束，但没有收到有效内容。");
        }
        if (nodes.requestStatus) nodes.requestStatus.textContent = buildUsageStatus("Streaming", usage, finishReason);
        return { content: finalText.trim(), thinking: finalThinking.trim(), usage, finishReason };
      }
    }

    if (done) break;
  }

  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed) {
      if (parsed.error) throw new Error(parsed.error);
      if (parsed.delta) finalText = mergeText(finalText, parsed.delta);
      if (parsed.thinking) finalThinking = mergeText(finalThinking, parsed.thinking);
      if (parsed.usage) usage = parsed.usage;
      if (parsed.finishReason) finishReason = parsed.finishReason;
      if ((parsed.delta || parsed.thinking || parsed.usage) && typeof onDelta === "function") {
        onDelta({ content: finalText, thinking: finalThinking, usage, finishReason });
      }
    }
  }

  if (!finalText.trim()) {
    if (finalThinking.trim() && strategy.retainThinkingOnEmptyContent) {
      const fallbackContent = "本次响应仅返回思考过程，未收到最终答复。";
      if (nodes.requestStatus) nodes.requestStatus.textContent = buildUsageStatus("Streaming", usage, finishReason);
      return { content: fallbackContent, thinking: finalThinking.trim(), usage, finishReason };
    }
    if (finalThinking.trim()) {
      throw new Error("Thinking 已结束，但模型没有返回最终回答。通常是上下文过长，或 Thinking 阶段耗尽了输出预算。");
    }
    throw new Error("流式响应结束，但没有收到有效内容。");
  }
  if (nodes.requestStatus) nodes.requestStatus.textContent = buildUsageStatus("Streaming", usage, finishReason);
  return { content: finalText.trim(), thinking: finalThinking.trim(), usage, finishReason };
}

function parseSseBlock(block) {
  const lines = String(block || "")
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"));
  if (!lines.length) return null;
  const dataText = lines.map((line) => line.slice(5).trimStart()).join("\n").trim();
  if (!dataText) return null;
  if (dataText === "[DONE]") return { done: true, delta: "", thinking: "", usage: null, finishReason: "", error: "" };

  let payload;
  try {
    payload = JSON.parse(dataText);
  } catch {
    return null;
  }

  const choice = payload?.choices?.[0] || {};
  let errorText = "";
  if (typeof payload?.error === "string") errorText = payload.error;
  else if (typeof payload?.error?.message === "string") errorText = payload.error.message;
  return {
    done: false,
    delta: normalizeMaybeComplexText(choice?.delta?.content) || normalizeMaybeComplexText(choice?.message?.content),
    thinking: extractThinkingText(choice?.delta) || extractThinkingText(choice?.message) || extractThinkingText(choice) || extractThinkingText(payload),
    usage: payload?.usage || null,
    finishReason: String(choice?.finish_reason || ""),
    error: errorText,
  };
}

function summarizeContextText(value, maxLength = 160) {
  const compact = String(value || "").replace(/\s+/g, " ").trim();
  if (!compact) return "";
  return compact.length > maxLength ? `${compact.slice(0, maxLength)}...` : compact;
}

function buildHistorySummary(messages, maxChars = CHAT_SUMMARY_MAX_CHARS) {
  const strategy = getContextStrategy();
  if (strategy.summaryMaxLines <= 0 || maxChars <= 0) return "";
  const lines = [];
  const source = Array.isArray(messages) ? messages.slice(-strategy.summaryMaxLines) : [];
  for (const item of source) {
    if (!item || (item.role !== "user" && item.role !== "assistant")) continue;
    const text = summarizeContextText(item.content, 140);
    if (!text) continue;
    lines.push(`- ${item.role === "user" ? "User" : "Assistant"}: ${text}`);
  }
  if (!lines.length) return "";
  const summary = lines.join("\n");
  return summary.length > maxChars ? `${summary.slice(0, maxChars)}...` : summary;
}

function buildContextMessages(chatMessages, systemPrompt) {
  const strategy = getContextStrategy();
  const source = Array.isArray(chatMessages) ? chatMessages.filter((item) => item && item.role && item.content) : [];
  const recentWindow = strategy.recentWindow;
  const summaryMaxChars = strategy.summaryMaxChars;
  const recentMessages = source.slice(-recentWindow);
  const olderMessages = source.slice(0, Math.max(0, source.length - recentMessages.length));
  const summary = buildHistorySummary(olderMessages, summaryMaxChars);
  const messages = [];

  if (systemPrompt) {
    messages.push({ role: "system", content: systemPrompt });
  }

  if (summary) {
    messages.push({
      role: "system",
      content:
        "Earlier conversation summary:\n" +
        summary +
        "\nUse this as compressed context. If any detail conflicts with recent messages, trust the recent messages.",
    });
  }

  recentMessages.forEach((item) => {
    messages.push({ role: item.role, content: item.content });
  });

  return {
    messages,
    summaryApplied: Boolean(summary),
    recentCount: recentMessages.length,
    summarizedCount: olderMessages.length,
  };
}

function buildRequestBody(chatMessages, session) {
  const defaults = getEffectiveDefaultConfig();
  const systemPrompt = (config.systemPrompt || defaults.systemPrompt || "").trim();
  const context = buildContextMessages(chatMessages, systemPrompt);

  const body = {
    model: config.model || defaults.model,
    messages: context.messages,
    stream: true,
    temperature: clampNumber(config.temperature, 0, 2, defaults.temperature),
    max_tokens: clampNumber(config.maxTokens, 128, 65535, defaults.maxTokens),
    system_prompt: systemPrompt,
    enable_thinking: Boolean(config.enableThinking),
    session_title: session?.title || "新对话",
  };

  if (account.loggedIn && session?.id) body.session_id = Number(session.id);
  if (config.enableThinking) body.chat_template_kwargs = { enable_thinking: true };
  if (nodes.requestStatus) {
    nodes.requestStatus.textContent = context.summaryApplied
      ? `请求中: 已摘要 ${context.summarizedCount} 条旧消息，保留最近 ${context.recentCount} 条`
      : `请求中: 最近上下文 ${context.recentCount} 条`;
  }
  return body;
}

function extractThinkingText(source) {
  if (!source || typeof source !== "object") return "";
  const candidates = [source.reasoning_content, source.reasoning, source.thinking, source.thought, source.reasoning_text];
  for (const item of candidates) {
    const text = normalizeMaybeComplexText(item);
    if (text) return text;
  }
  return "";
}

function normalizeMaybeComplexText(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((item) => normalizeMaybeComplexText(item)).join("");
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    if (Array.isArray(value.content)) return value.content.map((item) => normalizeMaybeComplexText(item)).join("");
  }
  return "";
}

function mergeText(existing, incoming) {
  const base = String(existing || "");
  const chunk = String(incoming || "");
  if (!chunk) return base;
  if (!base) return chunk;
  if (chunk.startsWith(base)) return chunk;
  if (base.endsWith(chunk)) return base;
  return `${base}${chunk}`;
}

function updateSendState() {
  const hasContent = Boolean((nodes.composerInput?.value || "").trim());
  if (!nodes.sendBtn) return;
  const disabled = !account.loggedIn || !hasContent || isSending;
  nodes.sendBtn.disabled = disabled;
  nodes.sendBtn.classList.toggle("enabled", !disabled);
}

function buildSessionTitle(value) {
  const compact = String(value || "").replace(/\s+/g, " ").trim();
  if (!compact) return "新对话";
  return compact.length > 24 ? `${compact.slice(0, 24)}...` : compact;
}

function formatTime(value) {
  const timestamp = normalizeTimestamp(value);
  if (!timestamp) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function normalizeTimestamp(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function clampNumber(value, min, max, fallback) {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function buildUsageStatus(prefix, usage, finishReason = "") {
  const finishText = String(finishReason || "").trim();
  const finishSuffix = finishText ? ` finish=${finishText}` : "";
  if (!usage) return `${prefix}${finishSuffix}`;
  const prompt = Number(usage.prompt_tokens || 0);
  const completion = Number(usage.completion_tokens || 0);
  const total = Number(usage.total_tokens || prompt + completion || 0);
  return `${prefix}: in=${prompt} out=${completion} total=${total}${finishSuffix}`;
}

function showNotice(text, type = "") {
  if (!nodes.notice) return;
  nodes.notice.textContent = text;
  nodes.notice.className = `notice show ${type}`.trim();
}

function hideNotice() {
  if (!nodes.notice) return;
  nodes.notice.className = "notice";
  nodes.notice.textContent = "";
}

function showLoginRequiredNotice() {
  showNotice("请先登录后再使用对话功能。", "error");
  if (nodes.loginActionLink) {
    nodes.loginActionLink.textContent = "登录";
    nodes.loginActionLink.href = "/login?next=/agnes-chat";
  }
}

function restoreDraftPrompt() {
  const session = getActiveSession();
  if (!session || !nodes.composerInput) return;
  nodes.composerInput.value = localStorage.getItem(getDraftStorageKey(session.id)) || "";
  updateSendState();
}

function storeDraftPrompt() {
  const session = getActiveSession();
  if (!session || !account.loggedIn) return;
  localStorage.setItem(getDraftStorageKey(session.id), nodes.composerInput?.value || "");
}

function clearDraftPrompt() {
  const session = getActiveSession();
  if (!session || !account.loggedIn) return;
  localStorage.removeItem(getDraftStorageKey(session.id));
}

async function hydrateAccount() {
  try {
    const response = await fetch("/api/account/me", { credentials: "same-origin" });
    const data = response.ok ? await response.json() : { loggedIn: false, role: "guest" };
    if (!data.loggedIn) {
      account = { loggedIn: false, role: "guest", username: "guest" };
      setGuestAccount();
      sessions = [];
      activeSessionId = "";
      renderAll();
      return;
    }

    account = {
      loggedIn: true,
      role: data.role === "admin" ? "admin" : "user",
      username: String(data.username || "user").trim() || "user",
    };
    applyAccountUi(data);
    enableLoggedInChatUi();
    await loadRemoteSessions();
    ensureSession();
    renderAll();
    restoreDraftPrompt();
  } catch {
    account = { loggedIn: false, role: "guest", username: "guest" };
    setGuestAccount("当前用户状态读取失败");
    sessions = [];
    activeSessionId = "";
    renderAll();
  }
}

function applyAccountUi(data) {
  const username = String(data.username || "用户").trim() || "用户";
  if (nodes.accountName) nodes.accountName.textContent = username;
  if (nodes.accountAvatar) nodes.accountAvatar.textContent = username.slice(0, 1).toUpperCase();
  if (data.role === "admin") {
    if (nodes.accountRole) nodes.accountRole.textContent = "当前为管理员会话";
    if (nodes.loginActionLink) {
      nodes.loginActionLink.textContent = "后台";
      nodes.loginActionLink.href = "/admin";
    }
    return;
  }
  if (nodes.accountRole) nodes.accountRole.textContent = "当前为用户会话";
  if (nodes.loginActionLink) {
    nodes.loginActionLink.textContent = "账户";
    nodes.loginActionLink.href = "/account";
  }
}

function setGuestAccount(roleText = "登录后可使用当前账号的对话历史") {
  stopPendingSessionPolling();
  if (nodes.accountName) nodes.accountName.textContent = "游客";
  if (nodes.accountRole) nodes.accountRole.textContent = roleText;
  if (nodes.accountAvatar) nodes.accountAvatar.textContent = "G";
  if (nodes.loginActionLink) {
    nodes.loginActionLink.textContent = "登录";
    nodes.loginActionLink.href = "/login?next=/agnes-chat";
  }
  if (nodes.composerInput) {
    nodes.composerInput.value = "";
    nodes.composerInput.disabled = true;
    nodes.composerInput.placeholder = "请先登录后再开始对话";
  }
  if (nodes.newChatBtn) nodes.newChatBtn.disabled = true;
  if (nodes.newChatInlineBtn) nodes.newChatInlineBtn.disabled = true;
}

function enableLoggedInChatUi() {
  if (nodes.composerInput) {
    nodes.composerInput.disabled = false;
    nodes.composerInput.placeholder = "输入你的问题。Enter 发送，Shift + Enter 换行。";
  }
  if (nodes.newChatBtn) nodes.newChatBtn.disabled = false;
  if (nodes.newChatInlineBtn) nodes.newChatInlineBtn.disabled = false;
}

async function loadRemoteSessions() {
  const response = await fetch("/api/agnes/chat-sessions", { credentials: "same-origin" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data?.error || data?.message || `HTTP ${response.status}`;
    throw new Error(`加载聊天记录失败: ${message}`);
  }
  const items = Array.isArray(data?.items) ? data.items : [];
  const remoteSessions = items.map(mapRemoteSession);
  sortSessionsArray(remoteSessions);

  // Merge instead of replace: keep local state, update from server
  for (const remote of remoteSessions) {
    const existing = sessions.find((s) => String(s.id) === String(remote.id));
    if (existing) {
      // Update metadata from server (title might have changed)
      existing.title = remote.title;
      existing.model = remote.model;
      existing.updatedAt = remote.updatedAt;
      existing.systemPrompt = remote.systemPrompt;
      existing.enableThinking = remote.enableThinking;
      // Merge messages: keep local loading items, update completed ones
      const remoteMessages = remote.messages || [];
      const merged = [];
      for (const rm of remoteMessages) {
        const local = existing.messages.find(
          (lm) => lm.role === rm.role && lm.createdAt === rm.createdAt && String(lm.content || "") === String(rm.content || "")
        );
        if (local) {
          merged.push({ ...rm, ...local, id: rm.id || local.id });
        } else {
          merged.push(rm);
        }
      }
      // Add any local messages not in remote (loading messages)
      for (const lm of existing.messages) {
        if (!merged.some((m) => m.role === lm.role && m.createdAt === lm.createdAt)) {
          merged.push(lm);
        }
      }
      merged.sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
      existing.messages = merged;
    } else {
      sessions.push(remote);
    }
  }
  // Remove sessions deleted on server
  sessions = sessions.filter((s) => remoteSessions.some((r) => String(r.id) === String(s.id)));
  sortSessionsArray(sessions);

  const storedActiveId = localStorage.getItem(getActiveSessionStorageKey()) || "";
  activeSessionId = sessions.some((item) => String(item.id) === String(storedActiveId))
    ? String(storedActiveId)
    : String(sessions[0]?.id || "");
  persistActiveSession();
}

function sortSessionsArray(arr) {
  arr.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

function mapRemoteSession(item) {
  const enableThinking = Boolean(item?.enable_thinking);
  return {
    id: String(item?.id || ""),
    title: String(item?.title || "新对话"),
    updatedAt: normalizeTimestamp(item?.updated_at) || Date.now(),
    createdAt: normalizeTimestamp(item?.created_at) || Date.now(),
    systemPrompt: String(item?.system_prompt || ""),
    model: String(item?.model || getEffectiveDefaultConfig().model),
    enableThinking,
    messages: Array.isArray(item?.messages)
      ? item.messages.map((message) => ({
          role: String(message?.role || "assistant"),
          content: String(message?.content || ""),
          thinking: String(message?.thinking || ""),
          enableThinking: enableThinking || Boolean(String(message?.thinking || "").trim()),
          createdAt: normalizeTimestamp(message?.created_at) || Date.now(),
          promptTokens: Number(message?.prompt_tokens || 0),
          completionTokens: Number(message?.completion_tokens || 0),
          totalTokens: Number(message?.total_tokens || 0),
          tokenSource: String(message?.token_source || ""),
          taskId: String(message?.task_id || ""),
          status: String(message?.status || "completed"),
          errorText: String(message?.error_text || ""),
          finishReason: String(message?.finish_reason || ""),
          loading: ["queued", "in_progress"].includes(String(message?.status || "")),
        }))
      : [],
  };
}



