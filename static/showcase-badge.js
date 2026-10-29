/* Worn achievement badge, shared by articles, replies and murmurs. */
(() => {
  "use strict";
  window.KflowShowcaseBadge = function (badge) {
    if (!badge?.name) return null;
    const tier = ["gold", "silver", "bronze"].includes(badge.tier) ? badge.tier : "bronze";
    const chip = document.createElement("a");
    chip.className = `showcase-chip tier-${tier}`;
    chip.href = "/achievements";
    chip.title = `佩戴勋章：${badge.name}`;
    chip.setAttribute("aria-label", `佩戴勋章：${badge.name}，查看成就勋章`);
    const icon = window.kflowIcons.el(badge.icon, 11);
    const name = document.createElement("span");
    name.className = "showcase-chip-name";
    name.textContent = badge.name;
    chip.append(icon, name);
    return chip;
  };
})();
