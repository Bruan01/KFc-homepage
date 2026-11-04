(function () {
  "use strict";

  function readCookie(name) {
    const prefix = name + "=";
    const value = document.cookie.split(";").map((item) => item.trim()).find((item) => item.indexOf(prefix) === 0);
    return value ? value.slice(prefix.length) : "";
  }

  const nativeFetch = window.fetch.bind(window);

  // 页面 HTML 已经不再种 csrftoken（那会让 CDN 无法缓存 HTML），
  // 所以第一次写操作前要主动领一次 cookie。pending 会被复用，
  // 并发发起的多个写请求只会触发一次 /api/csrf。
  let pending = null;

  function ensureToken() {
    if (readCookie("csrftoken")) return Promise.resolve(true);
    if (!pending) {
      pending = nativeFetch("/api/csrf", { credentials: "same-origin", cache: "no-store" })
        .then(() => Boolean(readCookie("csrftoken")))
        .catch(() => false)
        .finally(() => {
          pending = null;
        });
    }
    return pending;
  }

  window.fetch = function (input, init) {
    const options = init ? { ...init } : {};
    const method = String(options.method || (input && input.method) || "GET").toUpperCase();
    const url = typeof input === "string" ? new URL(input, window.location.href) : new URL(input.url, window.location.href);
    const sameOrigin = url.origin === window.location.origin;
    const mutating = !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method);

    if (!sameOrigin || !mutating) return nativeFetch(input, options);

    return ensureToken().then(() => {
      const headers = new Headers(options.headers || (typeof input !== "string" ? input.headers : undefined));
      if (!headers.has("X-CSRFToken")) headers.set("X-CSRFToken", decodeURIComponent(readCookie("csrftoken")));
      options.headers = headers;
      return nativeFetch(input, options);
    });
  };

  window.kflowCsrf = { ensure: ensureToken };

  // 空闲时预热，省掉用户第一次提交时的额外往返。
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => ensureToken(), { once: true });
  } else {
    ensureToken();
  }
})();
