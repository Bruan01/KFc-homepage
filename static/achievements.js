/* KFlow 成就勋章馆:卡片栅格 + hover 浮窗检视 */
(() => {
  const TIER_META = {
    gold: { label: "金牌成就", desc: "社区顶尖贡献的象征" },
    silver: { label: "银牌成就", desc: "持续活跃与高质量互动" },
    bronze: { label: "铜牌成就", desc: "迈出第一步就有收获" },
  };
  const TIER_ORDER = ["gold", "silver", "bronze"];
  const METRIC_LABEL = {
    topics: "主题帖",
    replies: "回复",
    likes_given: "送出点赞",
    likes_received: "主题获赞",
    reply_likes_received: "回复获赞",
    likes_total: "累计获赞",
    active_days: "活跃天数",
    max_topic_likes: "单篇最高赞",
    tutorials_completed: "完成教程",
    terms_completed: "掌握术语",
    boosts_bought: "购买加热",
    votes_cast: "投出票数",
    listings_sold: "售出商品",
    contribution: "贡献分",
  };

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

  function showToast(msg, type = "info") {
    const toast = document.querySelector("#forum-toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.className = `forum-toast show ${type}`;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => (toast.className = "forum-toast"), 3200);
  }

  function badgeIcon(name, size) {
    if (window.kflowIcons) return window.kflowIcons.el(name, size || 22);
    return document.createElement("span");
  }
  const personalityKind = item => window.KflowPersonalityBadge?.kindOf(item);
  function preparePersonality(node, item) {
    node.dataset.mbtiFamily = window.KflowPersonalityBadge.family(personalityKind(item));
  }

  let currentShowcase = null;
  let requestedBadge = new URLSearchParams(location.search).get('badge');
  let fromPersonality = new URLSearchParams(location.search).get('guide') === 'personality';
  let guidedBadgeCode='',showcasePending=false;
  let guideShade=null,guideCard=null;
  function clearWearGuide() {
    if(guideCard){
      guideCard.classList.remove('mbti-wear-target');
      if(guideCard.dataset.guideLabel)guideCard.setAttribute('aria-label',guideCard.dataset.guideLabel);
      guideCard.querySelectorAll('.mbti-wear-hint,.mbti-wear-error').forEach(node=>node.remove());
    }
    guideShade?.remove();guideShade=null;guideCard=null;guidedBadgeCode='';
    document.removeEventListener('keydown',guideKeys);
  }
  function guideKeys(event) {
    if(!guideCard)return;
    if(event.key==='Escape'){event.preventDefault();clearWearGuide();}
    else if(event.key==='Tab'){
      event.preventDefault();
      if(document.activeElement===guideCard)guideShade.querySelector('button').focus();
      else guideCard.focus({preventScroll:true});
    }
  }
  function highlightWearCard(card,item) {
    clearWearGuide();
    guideCard=card;guidedBadgeCode=item.code;
    const alreadyWorn=currentShowcase===item.code;
    card.dataset.guideLabel=card.getAttribute('aria-label');
    card.classList.add('mbti-wear-target');
    card.setAttribute('aria-label',alreadyWorn?`已佩戴「${item.name}」，点击继续`:`点击佩戴「${item.name}」勋章`);
    card.querySelector('.badge-title-row').append(el('span',{className:'mbti-wear-hint',textContent:alreadyWorn?'已佩戴 · 点击继续 →':'点击佩戴 →'}));
    guideShade=el('div',{className:'mbti-guide-shade'},el('button',{type:'button',className:'mbti-guide-dismiss',textContent:'稍后再说 ×',onclick:clearWearGuide}));
    guideShade.addEventListener('click',event=>{if(event.target===guideShade)clearWearGuide();});
    document.body.append(guideShade);
    card.scrollIntoView({block:'center',behavior:'instant'});
    card.focus({preventScroll:true});
    document.addEventListener('keydown',guideKeys);
  }
  function inviteToCommunity(item, alreadyWorn=false) {
    const dialog=document.querySelector('#badge-worn-guide');
    if (!dialog || dialog.open) return;
    dialog.querySelector('.badge-guide-kicker').textContent=alreadyWorn?'人格勋章 · 已佩戴':'人格勋章 · 佩戴成功';
    dialog.querySelector('#badge-worn-description').textContent='「'+item.name+'」已显示在你的昵称旁。';
    const art=dialog.querySelector('.badge-guide-art');
    art.replaceChildren(window.KflowPersonalityBadge.medal(item));
    preparePersonality(dialog,item);
    dialog.showModal();
    dialog.querySelector('h2').focus({preventScroll:true});
  }

  async function setShowcase(item, cancel) {
    if(showcasePending)return;
    showcasePending=true;
    const activeCard=document.querySelector(`[data-code="${item.code}"]`);
    activeCard?.setAttribute('aria-busy','true');
    try {
      const res = await fetch("/api/achievements/showcase", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "" },
        body: JSON.stringify({ code: cancel ? "" : item.code }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "操作失败");
      const changed=currentShowcase !== data.showcase?.code;
      currentShowcase = data.showcase?.code || null;
      clearWearGuide();
      showToast(cancel ? "已取消展示" : `已将「${item.name}」设为展示勋章，发帖时会显示`, "success");
      await init();
      if (!cancel && changed && personalityKind(item)) inviteToCommunity(item);
    } catch (err) {
      showToast(err.message || "操作失败", "error");
      if(guideCard){
        let note=guideCard.querySelector('.mbti-wear-error');
        if(!note){note=el('p',{className:'mbti-wear-error',role:'status'});guideCard.querySelector('.badge-body').append(note);}
        note.textContent=err.message || '佩戴未成功，请点击重试';
      }
    } finally {
      showcasePending=false;
      activeCard?.removeAttribute('aria-busy');
    }
  }

  // ── 浮窗检视 ──────────────────────────────────────────────
  let inspectOverlay = null;
  let inspectTrigger = null;

  function buildInspect(item, earnedAt, isShowcasing) {
    const root = el("div", { className: "badge-inspect" });
    const kind = personalityKind(item);
    if (kind) { root.classList.add('mbti-detail'); preparePersonality(root, item); }
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", item.name);

    const closeBtn = el("button", {
      className: "badge-inspect-close", type: "button",
      "aria-label": "关闭", textContent: "×",
    });
    closeBtn.addEventListener("click", closeInspect);

    const inner = el("div", { className: "badge-inspect-inner" });

    // 左侧(主):勋章本体
    const left = el("section", { className: "badge-inspect-left" });
    const medal = el("div", { className: `badge-inspect-medal tier-${item.tier}` },
      kind ? window.KflowPersonalityBadge.medal(item) : badgeIcon(item.icon, 38));
    if (kind) medal.classList.add('mbti-detail-medal');
    left.append(medal);
    left.append(el("h2", { className: "badge-inspect-name", textContent: item.name }));
    const tags = el("div", { className: "badge-inspect-tags" });
    const tierText = kind ? '心映月环' : ({ gold: "金牌", silver: "银牌", bronze: "铜牌" }[item.tier] || item.tier);
    tags.append(el("span", { className: `kb-pill kb-pill-tier tier-${item.tier}`, textContent: tierText }));
    const categoryText = { creation: "创作", interaction: "互动", activity: "活跃", business: "商务", personality: '人格探索' }[item.category] || item.category;
    if (categoryText) tags.append(el("span", { className: "kb-pill", textContent: categoryText }));
    if (earnedAt) {
      tags.append(el("span", { className: "kb-pill kb-pill-ready", textContent: "已获得" }));
    } else if (item.threshold || kind) {
      tags.append(el("span", { className: "kb-pill", textContent: "待解锁" }));
    }
    if (isShowcasing) {
      tags.append(el("span", { className: "kb-pill kb-pill-ready", textContent: "展示中" }));
    }
    left.append(tags);
    left.append(el("p", { className: "badge-inspect-desc", textContent: item.description || "" }));
    if (earnedAt) {
      left.append(el("div", { className: "badge-inspect-meta" },
        el("span", { textContent: `获得于 ${new Date(earnedAt).toLocaleDateString("zh-CN")}` }),
        el("span", { textContent: `${item.holderCount || 0} 人获得` }),
      ));
    } else {
      left.append(el("div", { className: "badge-inspect-meta" },
        el("span", { textContent: `${item.holderCount || 0} 人已获得` }),
      ));
    }
    if (earnedAt) {
      const btn = el("button", {
        className: "kb-btn kb-btn-ghost badge-inspect-showcase",
        type: "button",
        textContent: isShowcasing ? "取消展示" : "设为展示",
      });
      btn.addEventListener("click", () => setShowcase(item, isShowcasing));
      left.append(btn);
      btn.addEventListener('click', () => { closeInspect(); });
    }

    // 右侧(达成要求 + 进度)
    const right = el("section", { className: "badge-inspect-right" });
    right.append(el("h3", { className: "badge-inspect-right-title" }, "达成要求"));
    right.append(el("p", { className: "badge-inspect-req-text", textContent: item.requirement || "由管理员人工授予" }));

    if (kind) {
      right.append(el('h3', { className: 'badge-inspect-right-title', textContent: '昵称佩戴效果' }));
      right.append(el('div', { className: 'mbti-worn-example' }, el('strong', { textContent: '你的昵称' }), window.KflowShowcaseBadge(item)));
      right.append(el('p', { className: 'mbti-disclosure', textContent: '每人只保留一枚人格徽章，以最新一次已完成测评为准。重测结果变化后替换旧徽章；若已佩戴人格徽章，将同步更新。未完成或失败的测试不影响现有徽章。' }));
      if (!earnedAt) right.append(el('a', { className: 'kb-btn kb-btn-ghost mbti-start', href: '/personality', textContent: '前往心映探索' }));
    } else if (item.metricKey && item.threshold) {
      const metricLabel = METRIC_LABEL[item.metricKey] || item.metricKey;
      const current = Number(item.currentValue || 0);
      const target = Number(item.threshold || 0);
      const ratio = target > 0 ? Math.min(1, current / target) : 0;
      const pct = Math.round(ratio * 100);
      const done = Boolean(item.done);

      const progress = el("div", { className: "badge-progress" });
      const header = el("div", { className: "badge-progress-head" });
      header.append(el("span", { className: "badge-progress-label", textContent: metricLabel }));
      header.append(el("span", {
        className: "badge-progress-numbers",
        textContent: `${current.toLocaleString()} / ${target.toLocaleString()}`,
      }));
      progress.append(header);

      const bar = el("div", { className: "badge-progress-bar" + (done ? " done" : "") });
      const fill = el("div", { className: "badge-progress-fill", style: `width:${pct}%` });
      bar.append(fill);
      progress.append(bar);

      progress.append(el("div", { className: "badge-progress-foot" },
        el("span", { className: "badge-progress-pct", textContent: `${pct}%` }),
        el("span", {
          className: done ? "badge-progress-state done" : "badge-progress-state",
          textContent: done ? "✓ 已达成" : "未达成",
        }),
      ));
      right.append(progress);
    } else {
      right.append(el("div", { className: "badge-progress" },
        el("p", { className: "small", textContent: "此勋章由社区管理员人工授予,无法通过行为自动解锁。" }),
      ));
    }

    // 右侧附加信息(同步给前端展示)
    right.append(el("div", { className: "badge-inspect-stat" },
      el("span", { textContent: `当前持有 ${item.holderCount || 0} 人` }),
      el("span", { textContent: `代码 ${item.code}` }),
    ));

    inner.append(left, right);
    root.append(closeBtn, inner);

    // 点击遮罩关闭
    root.addEventListener("click", (e) => {
      if (e.target === root) closeInspect();
    });
    return root;
  }

  function openInspect(item) {
    closeInspect();
    inspectTrigger = document.activeElement;
    const earnedAt = item.earnedAt || "";
    const isShowcasing = currentShowcase === item.code;
    inspectOverlay = buildInspect(item, earnedAt, isShowcasing);
    document.body.appendChild(inspectOverlay);
    requestAnimationFrame(() => inspectOverlay.classList.add("open"));
    document.addEventListener("keydown", escClose);
    inspectOverlay.setAttribute('aria-modal', 'true');
    inspectOverlay.querySelector('.badge-inspect-close').focus();
  }

  function closeInspect() {
    document.removeEventListener("keydown", escClose);
    if (inspectOverlay && inspectOverlay.parentNode) {
      inspectOverlay.classList.remove("open");
      const overlay = inspectOverlay;
      setTimeout(() => overlay.parentNode?.removeChild(overlay), 180);
      inspectOverlay = null;
      inspectTrigger?.focus();
      inspectTrigger = null;
    }
  }

  function escClose(e) {
    if (e.key === 'Escape') closeInspect();
    if (e.key === 'Tab' && inspectOverlay) {
      const controls = [...inspectOverlay.querySelectorAll('button, a[href], [tabindex="0"]')].filter(n => !n.disabled && n.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }

  function badgeCard(item, earnedMap, showcasedCode, onShowcaseChange) {
    const kind = personalityKind(item);
    const earned = Boolean(earnedMap[item.code]);
    const card = el("article", {
      className: "badge-card" + (earned ? " earned" : "") + ` tier-${item.tier}`,
      "data-code": item.code,
    });
    if (kind) { card.classList.add('mbti-card'); preparePersonality(card, item); }
    const medal = el("div", { className: `badge-medal tier-${item.tier}` }, kind ? window.KflowPersonalityBadge.medal(item) : badgeIcon(item.icon, 22));
    const body = el("div", { className: "badge-body" });
    const titleRow = el("div", { className: "badge-title-row" });
    titleRow.append(el("h3", { textContent: item.name }));
    if (earned) {
      titleRow.append(el("span", { className: "badge-earned-chip" }, "已获得"));
    }
    if (showcasedCode === item.code) {
      titleRow.append(el("span", { className: "badge-earned-chip showcasing", textContent: "展示中" }));
    }
    body.append(
      titleRow,
      el("p", { className: "badge-desc", textContent: item.description || "" }),
    );
    const meta = el("div", { className: "badge-meta" });
    meta.append(
      el("span", { className: `badge-tier tier-text-${item.tier}`, textContent: kind ? (earned ? '心映月环' : '待解锁') : ({ gold: "金", silver: "银", bronze: "铜" }[item.tier] || item.tier) }),
    );
    meta.append(el("span", { className: "badge-holders", textContent: `${item.holderCount || 0} 人获得` }));
    if (earned && earnedMap[item.code]) {
      meta.append(el("span", { className: "badge-date", textContent: new Date(earnedMap[item.code]).toLocaleDateString("zh-CN") }));
    }
    body.append(meta);
    card.append(medal, body);

    // gacha 抽卡效果:鼠标位置 → 倾斜跟随
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const mx = (e.clientX - rect.left) / rect.width;
      const my = (e.clientY - rect.top) / rect.height;
      card.style.setProperty("--mx", mx.toFixed(3));
      card.style.setProperty("--my", my.toFixed(3));
    });
    card.addEventListener("mouseleave", () => {
      card.style.setProperty("--mx", 0.5);
      card.style.setProperty("--my", 0.5);
    });

    function activateCard() {
      if(showcasePending)return;
      if(earned && guidedBadgeCode===item.code){
        if(currentShowcase===item.code){clearWearGuide();inviteToCommunity(item,true);}
        else setShowcase(item,false);
      } else openInspect(item);
    }
    card.addEventListener("click", (e) => {
      if (e.target.closest(".badge-showcase-btn")) return;
      activateCard();
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activateCard();
      }
    });
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `查看「${item.name}」勋章详情`);
    return card;
  }

  async function init() {
    const groups = document.querySelector("#tierGroups");
    try {
      const res = await fetch("/api/achievements", { credentials: "same-origin" });
      const data = await res.json();
      document.querySelector("#badgeTotal").textContent = data.total ?? 0;
      document.querySelector("#myEarned").textContent = data.earned ?? 0;
      const earnedMap = {};
      for (const b of data.mine || []) earnedMap[b.code] = b.grantedAt;
      currentShowcase = data.showcaseCode || null;
      groups.replaceChildren();
      for (const tier of TIER_ORDER) {
        const items = (data.items || []).filter((a) => a.tier === tier && !personalityKind(a));
        if (!items.length) continue;
        const section = el("section", { className: "badge-tier-section" });
        section.append(
          el("div", { className: "badge-tier-heading" },
            el("h2", { textContent: TIER_META[tier].label }),
            el("span", { textContent: TIER_META[tier].desc }),
          ),
        );
        const grid = el("div", { className: "badge-grid" });
        for (const item of items) grid.append(badgeCard(item, earnedMap, currentShowcase, setShowcase));
        section.append(grid);
        groups.append(section);
      }
      const personalities = (data.items || []).filter(personalityKind);
      if (personalities.length) {
        const section = el('section', { className: 'badge-tier-section mbti-gallery', id: 'personality-badges' });
        section.append(el('div', { className: 'badge-tier-heading' }, el('h2', { textContent: '心映 · 人格月环' }), el('span', { textContent: '十六种心意，各自闪耀' })));
        const grid = el('div', { className: 'mbti-gallery-grid' });
        const order = ['INTJ','INTP','ENTJ','ENTP','INFJ','INFP','ENFJ','ENFP','ISTJ','ISFJ','ESTJ','ESFJ','ISTP','ISFP','ESTP','ESFP'];
        personalities.sort((a,b) => order.indexOf(personalityKind(a)) - order.indexOf(personalityKind(b)));
        personalities.forEach(item => grid.append(badgeCard(item, earnedMap, currentShowcase, setShowcase)));
        section.append(grid); groups.prepend(section);
      }
      if (requestedBadge) {
        const request = requestedBadge;
        requestedBadge = null;
        const requested = personalities.find(item => item.code === request && earnedMap[item.code]);
        const target = requested || (/^mbti-[a-z]{4}$/.test(request) ? personalities.find(item => earnedMap[item.code]) : null);
        if (target) {
          groups.querySelector(`[data-code="${target.code}"]`)?.scrollIntoView({block:'center',behavior:'instant'});
          highlightWearCard(groups.querySelector(`[data-code="${target.code}"]`),target);
        }
        if (fromPersonality) {
          fromPersonality=false;
          const url=new URL(location.href);url.searchParams.delete('guide');history.replaceState(null,'',url.pathname+url.search+url.hash);
        }
      }
    } catch {
      groups.replaceChildren(el("p", { className: "rankings-empty", textContent: "勋章加载失败，请稍后重试。" }));
    }
  }

  document.addEventListener("DOMContentLoaded", init);
  document.querySelectorAll('.badge-guide-close,.badge-guide-later').forEach(button=>button.addEventListener('click',()=>document.querySelector('#badge-worn-guide').close()));
})();
