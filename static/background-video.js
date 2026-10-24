/* Decorative video: keep the poster during critical loading and on slow links. */
(() => {
  const video = document.querySelector("#bg-video");
  if (!video) return;
  const connection = navigator.connection;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || connection?.saveData
      || ["slow-2g", "2g", "3g"].includes(connection?.effectiveType)) return;
  let scheduled = false;
  function sync() {
    scheduled = false;
    if (document.hidden || !Number.isFinite(video.duration)) return;
    const range = document.documentElement.scrollHeight - innerHeight;
    const progress = range > 0 ? Math.min(1, Math.max(0, scrollY / range)) : 0;
    const target = Math.min(video.duration, Math.max(0.08, progress * video.duration));
    if (Math.abs(video.currentTime - target) > 0.03) video.currentTime = target;
  }
  function schedule() {
    if (!scheduled) { scheduled = true; requestAnimationFrame(sync); }
  }
  function load() {
    const source = video.querySelector("source[data-src]");
    if (!source) return;
    source.src = source.dataset.src;
    delete source.dataset.src;
    video.addEventListener("loadedmetadata", schedule);
    video.addEventListener("loadeddata", () => video.classList.add("is-ready"));
    video.addEventListener("error", () => video.classList.remove("is-ready"));
    addEventListener("scroll", schedule, { passive: true });
    addEventListener("resize", schedule, { passive: true });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) schedule(); });
    video.load();
  }
  function afterLoad() {
    if ("requestIdleCallback" in window) requestIdleCallback(load, { timeout: 4000 });
    else setTimeout(load, 1000);
  }
  if (document.readyState === "complete") afterLoad();
  else addEventListener("load", afterLoad, { once: true });
})();
