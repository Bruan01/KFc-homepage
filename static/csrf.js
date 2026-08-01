(function () {
  "use strict";

  function readCookie(name) {
    const prefix = name + "=";
    const value = document.cookie.split(";").map((item) => item.trim()).find((item) => item.indexOf(prefix) === 0);
    return value ? value.slice(prefix.length) : "";
  }

  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const options = init ? { ...init } : {};
    const method = String(options.method || (input && input.method) || "GET").toUpperCase();
    const url = typeof input === "string" ? new URL(input, window.location.href) : new URL(input.url, window.location.href);
    if (url.origin === window.location.origin && !["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
      const headers = new Headers(options.headers || (typeof input !== "string" ? input.headers : undefined));
      if (!headers.has("X-CSRFToken")) headers.set("X-CSRFToken", decodeURIComponent(readCookie("csrftoken")));
      options.headers = headers;
    }
    return nativeFetch(input, options);
  };
})();
