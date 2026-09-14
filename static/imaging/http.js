(function () {
  "use strict";
  let pendingRequests = 0;

  /** Centralize same-origin requests, CSRF headers, loading state and errors. */
  async function request(path, options = {}) {
    const headers = new Headers(options.headers);
    if (options.body) headers.set("Content-Type", "application/json");
    pendingRequests += 1;
    document.documentElement.dataset.networkBusy = "true";
    try {
      // /csrf.js supplies the shared CSRF interceptor for mutating requests.
      const response = await window.fetch(path, { credentials: "same-origin", ...options, headers });
      if (response.status === 401) {
        window.location.assign("/login?next=/imaging");
        throw new Error("登录已过期，请重新登录。");
      }
      if (!response.ok) {
        let message = `请求失败（HTTP ${response.status}），请稍后重试。`;
        if ((response.headers.get("content-type") || "").includes("application/json")) {
          const data = await response.json();
          message = data.error || message;
        }
        const error = new Error(message);
        error.status = response.status;
        throw error;
      }
      return response;
    } catch (error) {
      console.error("显影请求失败", error);
      throw error;
    } finally {
      pendingRequests -= 1;
      document.documentElement.dataset.networkBusy = String(pendingRequests > 0);
    }
  }
  window.ImagingHttp = Object.freeze({ request });
}());
