/* 交互反馈动效：勋章庆祝 toast、升级提示（全站共享）。 */
(() => {
  const TIER_META = {
    gold: { label: "金牌成就", color: "#f5c04a", bg: "#fffaf0", ink: "#7a5800" },
    silver: { label: "银牌成就", color: "#c6ccd4", bg: "#fafbfc", ink: "#48484a" },
    bronze: { label: "铜牌成就", color: "#d9a06a", bg: "#fffaf5", ink: "#8a4b12" },
  };

  function ensureHost() {
    let host = document.getElementById("celebrate-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "celebrate-host";
      document.body.append(host);
    }
    return host;
  }

  function showCard({ icon, title, body, tier, accent }) {
    const host = ensureHost();
    const card = document.createElement("div");
    card.className = "celebrate-card";
    if (tier) card.classList.add(`tier-${tier}`);

    const medal = document.createElement("span");
    medal.className = "celebrate-medal";
    if (window.kflowIcons) medal.append(window.kflowIcons.el(icon || "trophy", 22));
    card.append(medal);

    const text = document.createElement("div");
    text.className = "celebrate-text";
    text.append(Object.assign(document.createElement("strong"), { textContent: title }));
    if (body) text.append(Object.assign(document.createElement("small"), { textContent: body }));
    card.append(text);

    const close = document.createElement("button");
    close.type = "button";
    close.className = "celebrate-close";
    close.setAttribute("aria-label", "关闭");
    if (window.kflowIcons) close.append(window.kflowIcons.el("xmark", 13));
    card.append(close);
    close.addEventListener("click", () => dismiss());

    host.append(card);
    requestAnimationFrame(() => card.classList.add("in"));

    let done = false;
    function dismiss() {
      if (done) return;
      done = true;
      card.classList.remove("in");
      card.classList.add("out");
      setTimeout(() => card.remove(), 320);
    }
    setTimeout(dismiss, 4600);
  }

  /** newBadges: [{ name, icon, tier }] —— 依次弹出庆祝卡片 */
  function celebrateBadges(newBadges) {
    (newBadges || []).forEach((badge, index) => {
      if (!badge || !badge.name) return;
      setTimeout(() => {
        const meta = TIER_META[badge.tier] || TIER_META.bronze;
        showCard({
          icon: badge.icon || "trophy",
          tier: badge.tier,
          title: `获得${meta.label}「${badge.name}」`,
          body: "点击头像 → 成就勋章馆查看全部成就",
        });
      }, index * 700);
    });
  }

  /** 等级提升大卡片 */
  function celebrateLevel(level, name) {
    showCard({
      icon: "star",
      title: `升级到 LV${level} ${name || ""}`,
      body: "新的社区权限已解锁，查看等级说明了解详情",
    });
  }

  window.kflowCelebrate = { badges: celebrateBadges, level: celebrateLevel };
})();
