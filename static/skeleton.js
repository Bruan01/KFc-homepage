/* KFlow 全站骨架屏 · 首屏内联控制脚本
 * 由 apps/core/pages.py 紧跟骨架 DOM 输出，不依赖任何外部资源。
 * 生命周期：DOM 出现即显示 → window.load（含 CSS/图片/脚本）后两帧淡出移除；
 * 另有硬性超时兜底，任何资源失败或脚本报错都不会把内容永久盖住。
 * 对外接口：window.kflowSkeleton.hide() / .ready()（异步页面首屏渲染完可主动收起）。
 */
(function () {
  "use strict";
  var el = document.getElementById("kflowSkeleton");
  if (!el) return;

  var started = Date.now();
  var finished = false;
  var MAX_VISIBLE_MS = 3500;   // 兜底：load 迟迟不来也要放行
  var MIN_VISIBLE_MS = 140;    // 避免秒开时闪一下骨架
  var FADE_MS = 240;
  var reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function afterPaint(fn) {
    if (window.requestAnimationFrame) {
      window.requestAnimationFrame(function () { window.requestAnimationFrame(fn); });
    } else {
      window.setTimeout(fn, 32);
    }
  }

  function finish() {
    if (finished) return;
    finished = true;
    var wait = Math.max(0, MIN_VISIBLE_MS - (Date.now() - started));
    window.setTimeout(function () {
      el.setAttribute("data-state", "hidden");
      el.setAttribute("aria-busy", "false");
      window.setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
        var style = document.getElementById("kflowSkeletonStyles");
        if (style && style.parentNode) style.parentNode.removeChild(style);
      }, reduceMotion ? 0 : FADE_MS);
    }, wait);
  }

  window.kflowSkeleton = {
    hide: finish,
    ready: finish,
    isVisible: function () { return el.getAttribute("data-state") !== "hidden"; }
  };

  if (document.readyState === "complete") {
    afterPaint(finish);
  } else {
    window.addEventListener("load", function () { afterPaint(finish); }, { once: true });
  }
  window.setTimeout(finish, MAX_VISIBLE_MS);
})();
