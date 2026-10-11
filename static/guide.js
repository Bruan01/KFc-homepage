/* KFlow 新手指南：目录定位、章节完成状态和本地阅读进度。 */
(() => {
  const root = document.querySelector(".guide-page");
  if (!root) return;

  const STORAGE_KEY = "kflow:guide:progress:v1";
  const sections = [...root.querySelectorAll("[data-guide-step]")];
  const sectionIds = sections.map((section) => section.dataset.guideStep).filter(Boolean);
  const titleMap = new Map(sections.map((section) => [section.dataset.guideStep, section.querySelector("h2")?.textContent || "新手指南"]));
  const tocButtons = [...root.querySelectorAll("[data-guide-nav]")];
  const completeButtons = [...root.querySelectorAll("[data-guide-complete]")];
  const progressBar = root.querySelector("#guideProgressBar");
  const sideCount = root.querySelector("#guideSidebarCount");
  const heroProgress = root.querySelector("#guideHeroProgress");
  const resumeButton = root.querySelector("#guideResumeButton");
  const resetButton = root.querySelector("#guideResetButton");
  const toast = root.querySelector("#forum-toast");
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;
  let state = loadState();
  let toastTimer = null;

  function loadState() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      const completed = Array.isArray(saved?.completed) ? saved.completed.filter((id) => sectionIds.includes(id)) : [];
      const current = sectionIds.includes(saved?.current) ? saved.current : sectionIds[0];
      return { completed: [...new Set(completed)], current };
    } catch {
      return { completed: [], current: sectionIds[0] };
    }
  }

  function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* 本地存储不可用时，页面仍可正常阅读。 */ }
  }

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2600);
  }

  function updateProgress() {
    const completed = new Set(state.completed);
    const count = completed.size;
    const progress = sectionIds.length ? Math.round((count / sectionIds.length) * 100) : 0;
    if (progressBar) progressBar.style.width = `${progress}%`;
    if (sideCount) sideCount.textContent = `${count} / ${sectionIds.length}`;
    if (heroProgress) heroProgress.textContent = `${count} / ${sectionIds.length}`;
    tocButtons.forEach((button) => {
      const id = button.dataset.guideNav;
      button.classList.toggle("is-current", id === state.current);
      button.classList.toggle("is-done", completed.has(id));
      button.setAttribute("aria-current", id === state.current ? "step" : "false");
    });
    completeButtons.forEach((button) => {
      const id = button.dataset.guideComplete;
      const done = completed.has(id);
      button.classList.toggle("is-done", done);
      button.setAttribute("aria-pressed", String(done));
      const text = button.querySelector(".guide-complete-text");
      if (text) text.textContent = done ? "已完成这一章" : button.dataset.defaultText || text.textContent;
    });
    if (resumeButton) {
      const hasProgress = count > 0 || state.current !== sectionIds[0];
      resumeButton.hidden = !hasProgress;
      resumeButton.textContent = `继续：${titleMap.get(state.current) || "上次进度"}`;
    }
  }

  function setCurrent(id, { persistState = true } = {}) {
    if (!sectionIds.includes(id)) return;
    state.current = id;
    if (persistState) persist();
    updateProgress();
  }

  function goTo(id) {
    const target = root.querySelector(`#step-${CSS.escape(id)}`);
    if (!target) return;
    setCurrent(id);
    target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }

  function toggleComplete(id) {
    if (!sectionIds.includes(id)) return;
    const completed = new Set(state.completed);
    const wasDone = completed.has(id);
    if (wasDone) completed.delete(id);
    else completed.add(id);
    state.completed = sectionIds.filter((stepId) => completed.has(stepId));
    setCurrent(id);
    persist();
    updateProgress();
    showToast(wasDone ? "已取消这一章的完成标记" : "这一章已标记完成");
  }

  tocButtons.forEach((button) => {
    button.addEventListener("click", () => goTo(button.dataset.guideNav));
  });

  completeButtons.forEach((button) => {
    const text = button.querySelector(".guide-complete-text");
    if (text) button.dataset.defaultText = text.textContent;
    button.addEventListener("click", () => toggleComplete(button.dataset.guideComplete));
  });

  resumeButton?.addEventListener("click", () => goTo(state.current));

  resetButton?.addEventListener("click", () => {
    state = { completed: [], current: sectionIds[0] };
    persist();
    updateProgress();
    showToast("阅读进度已重置");
  });

  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => Math.abs(a.boundingClientRect.top - 130) - Math.abs(b.boundingClientRect.top - 130));
    if (visible[0]) setCurrent(visible[0].target.dataset.guideStep, { persistState: false });
  }, { rootMargin: "-12% 0px -62% 0px", threshold: [0, 0.15, 0.5] });
  sections.forEach((section) => observer.observe(section));

  const updateCurrentFromScroll = () => {
    const targetLine = 128;
    let closest = sections[0];
    let distance = Number.POSITIVE_INFINITY;
    sections.forEach((section) => {
      const nextDistance = Math.abs(section.getBoundingClientRect().top - targetLine);
      if (section.getBoundingClientRect().top <= targetLine + 150 && nextDistance < distance) {
        closest = section;
        distance = nextDistance;
      }
    });
    if (closest) setCurrent(closest.dataset.guideStep, { persistState: false });
  };
  window.addEventListener("scroll", updateCurrentFromScroll, { passive: true });

  updateProgress();
})();
