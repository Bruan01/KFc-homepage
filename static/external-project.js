/* 热榜项目详情页：概括 / 标签 / 设计剖析 / 趋势预测。 */
(() => {
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "className") node.className = value;
      else if (key === "textContent") node.textContent = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child == null) continue;
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  const SOURCE_LABEL = { github: "GitHub", producthunt: "Product Hunt", cn_community: "中文社区" };
  const TREND_CLASS = { hot: "trend-hot", rising: "trend-rising", steady: "trend-steady", cooling: "trend-cooling", fresh: "trend-fresh" };

  function section(title, bodyNode) {
    return el("section", { className: "trend-section" },
      el("h2", { className: "trend-section-title", textContent: title }),
      bodyNode,
    );
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

    // ── 头部 ──
    const head = el("div", { className: "trend-head" });
    const titleRow = el("div", { className: "trend-title-row" });
    titleRow.append(el("h1", { textContent: p.title }));
    if (p.trendLabel) {
      titleRow.append(el("span", { className: `trend-badge ${TREND_CLASS[p.trend] || ""}`, textContent: p.trendLabel }));
    }
    const meta = el("div", { className: "trend-meta" });
    meta.append(el("span", { className: "rank-source", textContent: p.sourceLabel || p.source }));
    if (p.language) meta.append(el("span", { className: "trend-meta-item", textContent: p.language }));
    if (p.metrics?.stars != null) meta.append(el("span", { className: "trend-meta-item", textContent: `★ ${p.metrics.stars.toLocaleString()}` }));
    if (p.metrics?.upvotes != null) meta.append(el("span", { className: "trend-meta-item", textContent: `▲ ${p.metrics.upvotes}` }));
    if (p.metrics?.replies != null) meta.append(el("span", { className: "trend-meta-item", textContent: `评论 ${p.metrics.replies}` }));
    meta.append(el("span", { className: "trend-meta-item", textContent: `热度 ${Math.round(p.heat_score)}` }));
    head.append(titleRow, meta);

    const actions = el("div", { className: "trend-actions" });
    actions.append(
      el("a", { className: "community-cta", href: p.url, target: "_blank", rel: "noopener nofollow" }, "查看原文 ↗"),
      el("a", { className: "community-cta ghost", href: "/rankings?tab=external" }, "返回榜单"),
    );
    head.append(actions);
    root.append(head);

    // ── 标签 ──
    if ((p.tags || []).length) {
      const tagsRow = el("div", { className: "trend-tags" });
      for (const tag of p.tags) tagsRow.append(el("span", { className: "tag-chip", textContent: `# ${tag}` }));
      root.append(tagsRow);
    }

    // ── 概括 ──
    if (p.summary) {
      root.append(section("一句话概括",
        el("p", { className: "trend-summary", textContent: p.summary })));
    }

    // ── 趋势与预测 ──
    if (p.trend) {
      const trendBox = el("div", { className: "trend-predict-box" });
      const metrics = el("div", { className: "trend-predict-metrics" });
      const items = [
        { label: "当前状态", value: p.trendLabel || "—" },
        { label: "日均增速", value: p.trend.velocityPerDay != null ? `${p.trend.velocityPerDay > 0 ? "+" : ""}${p.trend.velocityPerDay}` : "—" },
        { label: "7 天后预测", value: p.trend.predicted != null ? `≈ ${p.trend.predicted.toLocaleString()}` : "样本不足" },
      ];
      for (const item of items) {
        metrics.append(
          el("div", { className: "trend-predict-metric" },
            el("small", { textContent: item.label }),
            el("strong", { textContent: item.value }),
          ),
        );
      }
      trendBox.append(metrics);
      if (p.trend.velocityPerDay > 0) {
        trendBox.append(el("p", { className: "trend-predict-note",
          textContent: `按当前增速线性外推，预计 7 天后热度指标约达到 ${p.trend.predicted?.toLocaleString() || "—"}（预测基于历史抓取快照，仅供参考）。` }));
      } else if (p.trend.state === "cooling") {
        trendBox.append(el("p", { className: "trend-predict-note", textContent: "近期热度增速放缓，进入降温区间。" }));
      }
      root.append(section("热度趋势与预测", trendBox));
    }

    // ── 产品设计思路剖析 ──
    const analysis = p.analysis || {};
    if (analysis.positioning || analysis.mechanics || analysis.takeaway) {
      const grid = el("div", { className: "trend-analysis-grid" });
      const cards = [
        { title: "产品定位", body: analysis.positioning },
        { title: "目标用户", body: analysis.audience },
        { title: "核心机制", body: analysis.mechanics },
        { title: "可借鉴点", body: analysis.takeaway },
      ];
      for (const card of cards) {
        if (!card.body) continue;
        grid.append(
          el("div", { className: "trend-analysis-card" },
            el("h3", { textContent: card.title }),
            el("p", { textContent: card.body }),
          ),
        );
      }
      const wrapper = el("div", {}, grid);
      if (p.analysisSource) {
        wrapper.append(el("p", { className: "trend-analysis-source",
          textContent: p.analysisSource === "llm" ? "剖析内容由 AI 生成" : "剖析内容由规则引擎生成" }));
      }
      root.append(section("产品设计思路剖析", wrapper));
    }

    // ── 原文信息 ──
    const origin = el("div", { className: "trend-origin" },
      el("span", { className: "trend-origin-label", textContent: "原文链接" }),
      el("a", { href: p.url, target: "_blank", rel: "noopener nofollow", textContent: p.url }),
    );
    root.append(origin);

    // ── 相关项目 ──
    if ((p.related || []).length) {
      const list = el("div", { className: "trend-related" });
      for (const rel of p.related) {
        list.append(
          el("a", { className: "trend-related-item", href: `/rankings/project/${rel.id}` },
            el("span", { className: "rank-source", textContent: SOURCE_LABEL[rel.source] || rel.source }),
            el("strong", { textContent: rel.title }),
            el("span", { className: "trend-related-heat", textContent: `🔥 ${rel.heat}` }),
          ),
        );
      }
      root.append(section("相关项目（按共享标签推荐）", list));
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
