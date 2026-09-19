/* KFlow 项目详情页：按照 kaiyuanbang.cn 详情页排版布局 */
(() => {
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child == null) continue;
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  const SOURCE_LABEL = { kaiyuanbang: "开源榜" };
  const SOURCE_NOTE = {
    kaiyuanbang: "数据来源 开源榜(kaiyuanbang.cn),由 KFlowBot 抓取,内容由 AI 辅助生成,欢迎纠错。",
  };

  function fmtInt(n) {
    n = Number(n) || 0;
    return n.toLocaleString("en-US");
  }

  function csrf() {
    return document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  }

  async function init() {
    const root = document.querySelector("#detailRoot");
    const parts = location.pathname.split("/").filter(Boolean);
    const id = Number(parts[parts.length - 1]);
    if (!id) {
      root.replaceChildren(el("p", { className: "rankings-empty", textContent: "无效的项目地址。" }));
      return;
    }
    try {
      const res = await fetch(`/api/rankings/external/${id}`, { credentials: "same-origin" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "项目不存在");
      render(root, data.project);
    } catch (err) {
      root.replaceChildren(el("p", { className: "rankings-empty", textContent: err.message || "加载失败。" }));
    }
  }

  function render(root, p) {
    document.title = `${p.title} | KFlow 热榜详情`;
    root.replaceChildren();
    root.append(
      renderBreadcrumb(p),
      renderHero(p),
      renderStatsCard(p),
      renderSparkline(p),
      renderMetaCard(p),
      renderTagsRow(p),
      renderSummary(p),
      renderTrend(p),
      renderRelated(p),
    );
    bindVote(root, p);
  }

  // ── 面包屑 ──
  function renderBreadcrumb(p) {
    const nav = el("nav", { className: "kb-breadcrumb", "aria-label": "breadcrumb" });
    nav.append(
      el("a", { href: "/rankings?tab=external" }, "排行榜"),
      el("span", { className: "kb-bc-sep", textContent: "›" }),
      el("a", { href: "/rankings?tab=external&source=" + encodeURIComponent(p.source) },
        SOURCE_LABEL[p.source] || p.source),
      el("span", { className: "kb-bc-sep", textContent: "›" }),
      el("span", { className: "kb-bc-current", textContent: p.title }),
    );
    return nav;
  }

  // ── Hero ──
  function renderHero(p) {
    const card = el("section", { className: "kb-hero" });
    const avatar = el("div", { className: "kb-hero-avatar" });
    const initial = (p.title || p.author || "?").trim().slice(0, 1).toUpperCase();
    avatar.textContent = initial;

    const body = el("div", { className: "kb-hero-body" });
    const ownerRow = el("div", { className: "kb-hero-owner" });
    if (p.author) ownerRow.append(el("bdi", { textContent: p.author }));
    if (p.topic) ownerRow.append(el("span", { className: "kb-pill kb-pill-topic", textContent: p.topic }));
    if (p.language) ownerRow.append(el("span", { className: "kb-pill kb-pill-lang", textContent: p.language }));
    if (p.license) ownerRow.append(el("span", { className: "kb-pill kb-pill-license", textContent: p.license }));
    body.append(ownerRow);

    body.append(el("h1", { className: "kb-hero-title", textContent: p.title || "未命名项目" }));
    if (p.description) {
      body.append(el("p", { className: "kb-hero-desc", textContent: p.description }));
    } else {
      body.append(el("p", { className: "kb-hero-desc empty", textContent: "暂无简介,欢迎提交补充。" }));
    }
    body.append(el("p", { className: "kb-hero-attr", textContent: SOURCE_NOTE[p.source] || SOURCE_NOTE.kaiyuanbang }));

    // 操作按钮组(对应 kaiyuanbang 的 GitHub 原站 / 项目官网 / 对比 / 纠错 / 加入对比 / 收藏 / 分享)
    const actions = el("div", { className: "kb-hero-actions" });
    actions.append(
      el("a", { className: "kb-btn kb-btn-primary", href: p.url, target: "_blank", rel: "noopener nofollow" },
        "GitHub 原站 ↗"),
    );
    if (p.homepage) {
      actions.append(
        el("a", { className: "kb-btn kb-btn-ghost", href: p.homepage, target: "_blank", rel: "noopener nofollow" },
          "项目官网 ↗"),
      );
    }
    actions.append(
      el("button", { className: "kb-btn kb-btn-ghost", id: "kbVoteBtn", type: "button",
        textContent: p.voted ? `已赞 ${p.votes}` : `创意赞 ${p.votes || 0}` }),
      el("button", { className: "kb-btn kb-btn-ghost", type: "button", onclick: () => copyShareLink(p) },
        "分享"),
      el("a", { className: "kb-btn kb-btn-ghost", href: "/rankings?tab=external" }, "返回榜单"),
    );

    card.append(avatar, body, actions);
    return card;
  }

  // ── 数据卡(Stars / Forks / Watching / Issues / Heat + 24h / 7d / 30d 增长) ──
  function renderStatsCard(p) {
    const card = el("section", { className: "kb-card kb-stats-card" });
    card.append(el("h2", { className: "kb-card-title" }, "项目数据"));

    const stars = Number(p.stars || 0);
    const forks = Number(p.forks || 0);
    const watching = Number(p.watching || 0);
    const issues = Number(p.issues || 0);
    const heat = Math.round(Number(p.heat_score || 0));
    const g24 = Number(p.growth_24h || 0);
    const g7 = Number(p.growth_7d || 0);
    const g30 = Number(p.growth_30d || 0);

    const grid = el("div", { className: "kb-stats-grid" });
    grid.append(
      kbStatBlock("Stars", "★", fmtInt(stars), null),
      kbStatBlock("Forks", "🍴", fmtInt(forks), null),
      kbStatBlock("Watching", "👁", fmtInt(watching), null),
      kbStatBlock("Issues", "🐞", fmtInt(issues), null),
      kbStatBlock("热度分", "🔥", fmtInt(heat), "kb-stat-warm"),
    );

    if (g24 || g7 || g30) {
      const growthRow = el("div", { className: "kb-growth-row" });
      if (g24) growthRow.append(el("div", { className: "kb-growth-cell" },
        el("small", { textContent: "24h 增长" }),
        el("strong", { className: "kb-stat-up", textContent: "+" + fmtInt(g24) })));
      if (g7) growthRow.append(el("div", { className: "kb-growth-cell" },
        el("small", { textContent: "7 日增长" }),
        el("strong", { className: "kb-stat-up", textContent: "+" + fmtInt(g7) })));
      if (g30) growthRow.append(el("div", { className: "kb-growth-cell" },
        el("small", { textContent: "30 日增长" }),
        el("strong", { className: "kb-stat-up", textContent: "+" + fmtInt(g30) })));
      card.append(grid, growthRow);
    } else {
      card.append(grid);
    }
    return card;
  }

  // ── Star 趋势 sparkline(从 90 天快照渲染) ──
  function renderSparkline(p) {
    const snaps = p.snapshots || [];
    if (snaps.length < 2) return document.createDocumentFragment();
    const card = el("section", { className: "kb-card kb-trend-card" });
    card.append(el("h2", { className: "kb-card-title" },
      "Star 趋势 · 最近 90 天本地快照"));

    const stars = snaps.map((s) => Number(s.stars) || 0);
    const min = Math.min(...stars);
    const max = Math.max(...stars);
    const range = max - min || 1;
    const w = 720, h = 140, pad = 12;
    const step = (w - pad * 2) / (stars.length - 1);
    const points = stars.map((v, i) => {
      const x = pad + i * step;
      const y = pad + (1 - (v - min) / range) * (h - pad * 2);
      return [x, y];
    });
    const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(" ");
    const fillD = `${pathD} L ${pad + (stars.length - 1) * step} ${h - pad} L ${pad} ${h - pad} Z`;
    const first = stars[0];
    const last = stars[stars.length - 1];
    const delta = last - first;
    const deltaCls = delta >= 0 ? "kb-stat-up" : "kb-stat-down";

    const stats = el("div", { className: "kb-trend-stats" });
    stats.append(el("span", {},
      el("strong", { textContent: fmtInt(last) }), " 当前 Stars"));
    stats.append(el("span", {},
      el("strong", { className: deltaCls, textContent: (delta >= 0 ? "+" : "") + fmtInt(delta) }), " 首尾差值"));
    stats.append(el("span", {},
      el("strong", { textContent: String(snaps.length) }), " 快照数量"));
    if (snaps.length) {
      const lastDate = snaps[snaps.length - 1].date || "";
      stats.append(el("span", {}, el("strong", { textContent: lastDate }), " 最近快照"));
    }

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "kb-sparkline");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Star 趋势");

    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    const grad = document.createElementNS("http://www.w3.org/2000/svg", "linearGradient");
    grad.setAttribute("id", "kb-spark-fill");
    grad.setAttribute("x1", "0"); grad.setAttribute("x2", "0");
    grad.setAttribute("y1", "0"); grad.setAttribute("y2", "1");
    const stop1 = document.createElementNS("http://www.w3.org/2000/svg", "stop");
    stop1.setAttribute("offset", "0%");
    stop1.setAttribute("stop-color", "#5b3aa8");
    stop1.setAttribute("stop-opacity", "0.32");
    const stop2 = document.createElementNS("http://www.w3.org/2000/svg", "stop");
    stop2.setAttribute("offset", "100%");
    stop2.setAttribute("stop-color", "#5b3aa8");
    stop2.setAttribute("stop-opacity", "0");
    grad.append(stop1, stop2);
    defs.append(grad);
    svg.append(defs);

    const fillPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    fillPath.setAttribute("d", fillD);
    fillPath.setAttribute("fill", "url(#kb-spark-fill)");
    fillPath.setAttribute("stroke", "none");
    svg.append(fillPath);

    const linePath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    linePath.setAttribute("d", pathD);
    linePath.setAttribute("fill", "none");
    linePath.setAttribute("stroke", "#5b3aa8");
    linePath.setAttribute("stroke-width", "1.5");
    linePath.setAttribute("stroke-linecap", "round");
    linePath.setAttribute("stroke-linejoin", "round");
    svg.append(linePath);

    card.append(stats, svg);
    return card;
  }

  function kbStatBlock(label, icon, value, valueCls) {
    return el("div", { className: "kb-stat-block" },
      el("div", { className: "kb-stat-block-label", textContent: label }),
      el("div", { className: "kb-stat-block-value " + (valueCls || "") },
        el("span", { className: "kb-stat-block-icon", textContent: icon }),
        el("span", { textContent: value }),
      ),
    );
  }

  // ── 元信息(数据来源 / 语言 / 许可证 / 仓库 / 官网 / 创建时间 / 数据同步 / 热度) ──
  function renderMetaCard(p) {
    const rows = [];
    rows.push(["数据来源", SOURCE_LABEL[p.source] || p.source]);
    if (p.author) rows.push(["仓库地址", p.author]);
    if (p.language) rows.push(["语言", p.language]);
    if (p.license) rows.push(["许可证", p.license]);
    if (p.homepage) rows.push(["项目官网", p.homepage]);
    if (p.created_at) rows.push(["创建时间", p.created_at]);
    if (p.pushed_at_fact) rows.push(["最近 Push", p.pushed_at_fact]);
    if (p.synced_at) rows.push(["数据同步", p.synced_at]);
    if (p.last_crawled_at) {
      const t = new Date(p.last_crawled_at);
      rows.push(["本地抓取", t.toLocaleString("zh-CN", { hour12: false })]);
    }
    rows.push(["热度分", fmtInt(Math.round(p.heat_score || 0))]);
    if (p.trendLabel) rows.push(["当前状态", p.trendLabel]);
    rows.push(["创意赞", String(p.votes || 0)]);

    const card = el("section", { className: "kb-card kb-meta-card" });
    card.append(el("h2", { className: "kb-card-title" }, "项目信息"));
    const dl = el("dl", { className: "kb-meta-list" });
    for (const [k, v] of rows) {
      const dt = el("dt", { textContent: k });
      let dd;
      if ((k === "项目官网" || k === "仓库地址") && /^https?:\/\//.test(v)) {
        const isHomepage = k === "项目官网";
        dd = el("dd", {},
          el("a", { href: v, target: "_blank", rel: "noopener nofollow",
            className: "kb-meta-link" + (isHomepage ? " kb-meta-link-em" : ""),
            textContent: v.replace(/^https?:\/\//, "").replace(/\/$/, "") }),
        );
      } else {
        dd = el("dd", { textContent: v });
      }
      dl.append(dt, dd);
    }
    card.append(dl);
    return card;
  }

  // ── 标签行 ──
  function renderTagsRow(p) {
    if (!(p.tags || []).length && !p.topic && !p.language) return document.createDocumentFragment();
    const row = el("section", { className: "kb-tags-row" });
    row.append(el("h2", { className: "kb-card-title" }, "Topics"));
    const wrap = el("div", { className: "kb-tags-wrap" });
    if (p.topic) wrap.append(el("a", { className: "kb-pill kb-pill-topic", href: `/rankings?tab=external&source=kaiyuanbang`, textContent: p.topic }));
    if (p.language) wrap.append(el("span", { className: "kb-pill kb-pill-lang", textContent: p.language }));
    if (p.analyzed) wrap.append(el("span", { className: "kb-pill kb-pill-ready", textContent: "本地解读" }));
    for (const tag of (p.tags || []).slice(0, 6)) {
      wrap.append(el("span", { className: "kb-pill", textContent: `# ${tag}` }));
    }
    row.append(wrap);
    return row;
  }

  // ── 一句话概括 ──
  function renderSummary(p) {
    if (!p.summary) return document.createDocumentFragment();
    return el("section", { className: "kb-card" },
      el("h2", { className: "kb-card-title" }, "一句话概括"),
      el("p", { className: "kb-summary", textContent: p.summary }),
    );
  }

  // ── 趋势与预测 ──
  function renderTrend(p) {
    const trend = p.trend || {};
    if (!trend.state) return document.createDocumentFragment();
    const card = el("section", { className: "kb-card kb-trend-card" });
    card.append(el("h2", { className: "kb-card-title" }, "热度趋势与预测"));
    const grid = el("div", { className: "kb-trend-grid" });
    const items = [
      { label: "当前状态", value: p.trendLabel || "—" },
      { label: "日均增速", value: trend.velocityPerDay != null
        ? `${trend.velocityPerDay > 0 ? "+" : ""}${trend.velocityPerDay}`
        : "样本不足" },
      { label: "7 天后预测", value: trend.predicted != null
        ? `≈ ${fmtInt(trend.predicted)}`
        : "样本不足" },
    ];
    for (const it of items) {
      grid.append(
        el("div", { className: "kb-trend-cell" },
          el("small", { textContent: it.label }),
          el("strong", { textContent: it.value }),
        ),
      );
    }
    card.append(grid);
    if (trend.velocityPerDay > 0) {
      card.append(el("p", { className: "kb-trend-note",
        textContent: `按当前增速线性外推,预计 7 天后热度指标约达到 ${fmtInt(trend.predicted || 0)}(预测基于历史抓取快照,仅供参考)。` }));
    } else if (trend.state === "cooling") {
      card.append(el("p", { className: "kb-trend-note", textContent: "近期热度增速放缓,进入降温区间。" }));
    }
    return card;
  }

  // ── 相关项目 ──
  function renderRelated(p) {
    if (!(p.related || []).length) return document.createDocumentFragment();
    const card = el("section", { className: "kb-card" });
    const head = el("div", { className: "kb-related-head" });
    head.append(el("h2", { className: "kb-card-title" }, "同类项目推荐"));
    head.append(el("a", { className: "kb-related-more", href: "/rankings?tab=external" }, "查看更多 ›"));
    card.append(head);

    const list = el("ol", { className: "kb-related-list" });
    for (const rel of (p.related || []).slice(0, 8)) {
      const li = el("li", { className: "kb-related-item" });
      li.append(el("span", { className: "kb-related-initial",
        textContent: (rel.title || rel.author || "?").slice(0, 1).toUpperCase() }));
      const main = el("div", { className: "kb-related-main" });
      main.append(el("a", { className: "kb-related-title", href: `/rankings/project/${rel.id}`, textContent: rel.title }));
      if (rel.author) main.append(el("div", { className: "kb-related-author" },
        el("bdi", { textContent: rel.author })));
      const meta = el("div", { className: "kb-related-meta" });
      meta.append(el("span", { textContent: SOURCE_LABEL[rel.source] || rel.source }));
      meta.append(el("span", { textContent: `🔥 ${rel.heat}` }));
      li.append(main, meta);
      list.append(li);
    }
    card.append(list);
    return card;
  }

  // ── 创意赞 ──
  async function bindVote(root, p) {
    const btn = root.querySelector("#kbVoteBtn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      if (btn.classList.contains("voted")) return;
      try {
        const res = await fetch(`/api/rankings/external/${p.id}/vote`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrf() },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (res.status === 401) {
            const toast = document.querySelector("#forum-toast");
            if (toast) {
              toast.textContent = "请先登录后再投票";
              toast.className = "forum-toast show warn";
              clearTimeout(toast._t);
              toast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
            }
            return;
          }
          throw new Error(data.error || "投票失败");
        }
        btn.classList.add("voted");
        btn.textContent = `已赞 ${data.votes}`;
      } catch (err) {
        const toast = document.querySelector("#forum-toast");
        if (toast) {
          toast.textContent = err.message || "投票失败";
          toast.className = "forum-toast show error";
          clearTimeout(toast._t);
          toast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
        }
      }
    });
  }

  function copyShareLink(p) {
    const url = `${location.origin}/rankings/project/${p.id}`;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        const toast = document.querySelector("#forum-toast");
        if (toast) {
          toast.textContent = "链接已复制";
          toast.className = "forum-toast show success";
          clearTimeout(toast._t);
          toast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
        }
      }).catch(() => fallbackCopy(url));
    } else {
      fallbackCopy(url);
    }
  }
  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (_) {}
    document.body.removeChild(ta);
  }

  document.addEventListener("DOMContentLoaded", init);
})();