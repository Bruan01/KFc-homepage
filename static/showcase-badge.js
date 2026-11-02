/* Worn achievement badge, shared by articles, replies and murmurs. */
(() => {
  "use strict";
  const motifs = {
    INTJ: ['M12 2 15 9 22 12 15 15 12 22 9 15 2 12 9 9Z', 'M12 5v14M5 12h14'],
    INTP: ['M3 8c3-5 20 4 18 9S1 14 3 8ZM4 18C0 14 16 0 20 6S9 23 4 18Z', 'M12 10v4M10 12h4'],
    ENTJ: ['M5 22V2l15 5-15 5', 'M8 22H2'],
    ENTP: ['M12 22V11L5 5M12 11l7-7M12 15l8-3', 'M4 3v4M2 5h4M19 2v4M17 4h4M20 10v4M18 12h4'],
    INFJ: ['M7 7h10l2 13H5ZM9 4h6v3M12 2v2M9 23h6', 'M12 10v7'],
    INFP: ['M4 21C7 9 12 3 21 2c0 9-5 16-14 16', 'M4 21 17 7M8 17l1-6M12 13l6-1'],
    ENFJ: ['M8 8a4 4 0 1 0 8 0 4 4 0 0 0-8 0M3 13c0 4 3 7 7 9M21 13c0 4-3 7-7 9', 'M6 15l4 4M18 15l-4 4M12 1v1M3 7h1M20 7h1'],
    ENFP: ['M15 2l2 5 5 1-4 4 1 5-4-3-5 3 1-5-4-4 5-1Z', 'M2 23l7-7M3 16l3-3M9 23l3-3'],
    ISTJ: ['M6 3h14v17H6a3 3 0 0 1 0-6h14M6 3a3 3 0 0 0-3 3v11', 'M9 8l3 3 5-5'],
    ISFJ: ['M12 2 3 6v6c0 5 6 9 9 10 3-1 9-5 9-10V6Z', 'M12 17V9M12 13c-5 0-5-4-5-4 5 0 5 4 5 4ZM12 11c0-4 5-5 5-5 0 5-5 5-5 5Z'],
    ESTJ: ['M3 3h18v3H3ZM3 20h18v2H3ZM6 8v10M12 8v10M18 8v10', 'M5 8h2M11 8h2M17 8h2'],
    ESFJ: ['M12 12C3 12 3 1 8 3c3 1 4 5 4 9ZM12 12c0-9 11-9 9-4-1 3-5 4-9 4ZM12 12c9 0 9 11 4 9-3-1-4-5-4-9ZM12 12c0 9-11 9-9 4 1-3 5-4 9-4Z'],
    ISTP: ['M8 3h8l1 4 4 1v8l-4 1-1 4H8l-1-4-4-1V8l4-1Z', 'M8 12a4 4 0 1 0 8 0 4 4 0 0 0-8 0'],
    ISFP: ['M9 15 19 3c2-2 4 0 2 2L11 17ZM9 15c-5-1-3 6-7 6 7 3 11-2 7-6Z', 'M15 21c0-5 7-5 7-5-1 6-7 5-7 5Z'],
    ESTP: ['M14 2 3 14h8l-1 8L22 9h-9Z'],
    ESFP: ['M9 18V5l12-3v13M9 5v4l12-3', 'M3 19a3 2 0 1 0 6 0 3 2 0 0 0-6 0M15 16a3 2 0 1 0 6 0 3 2 0 0 0-6 0'],
  };
  const families = { NT: ['#bda0e5', '#eee3ff', '#352546'], NF: ['#96d7b1', '#e6f6dc', '#183e30'], SJ: ['#94bee9', '#e9f3ff', '#203a58'], SP: ['#edcc7b', '#fff4d2', '#514025'] };
  let serial = 0;
  function kindOf(badge) {
    const kind = /^mbti-([a-z]{4})$/.exec(badge?.code || '')?.[1].toUpperCase();
    return motifs[kind] ? kind : null;
  }
  function family(kind) { return kind.includes('NT') ? 'NT' : kind.includes('NF') ? 'NF' : kind.endsWith('J') ? 'SJ' : 'SP'; }
  function svgNode(tag, attrs = {}) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  }
  function symbol(kind, large = false) {
    const svg = svgNode('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': large ? '1.25' : '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false' });
    for (const d of motifs[kind]) svg.append(svgNode('path', { d }));
    return svg;
  }
  function medal(badge) {
    const kind = kindOf(badge);
    if (!kind) return null;
    const [accent, pearl, deep] = families[family(kind)], id = `mbti-moon-${++serial}`;
    const svg = svgNode('svg', { viewBox: '0 0 160 160', class: 'mbti-moon', 'aria-hidden': 'true', focusable: 'false' });
    const defs = svgNode('defs');
    const fill = svgNode('radialGradient', { id, cx: '30%', cy: '20%', r: '90%' });
    for (const [offset, color] of [['0%', accent], ['40%', deep], ['100%', '#101c24']]) fill.append(svgNode('stop', { offset, 'stop-color': color }));
    const rim = svgNode('linearGradient', { id: `${id}-rim`, x1: '0', y1: '0', x2: '1', y2: '1' });
    for (const [offset, color] of [['0%', pearl], ['35%', accent], ['60%', pearl], ['100%', accent]]) rim.append(svgNode('stop', { offset, 'stop-color': color }));
    defs.append(fill, rim); svg.append(defs);
    svg.append(svgNode('circle', { cx: 80, cy: 80, r: 69, fill: `url(#${id})`, stroke: `url(#${id}-rim)`, 'stroke-width': 3 }));
    svg.append(svgNode('circle', { cx: 80, cy: 80, r: 63, fill: 'none', stroke: accent, 'stroke-opacity': '.65', 'stroke-width': '.8' }));
    svg.append(svgNode('path', { d: 'M89 26C34 25 23 113 84 131C25 135 9 43 89 26Z', fill: pearl, opacity: '.7' }));
    svg.append(svgNode('path', { d: 'M28 38Q36 17 65 18M116 134Q132 127 139 108', fill: 'none', stroke: pearl, 'stroke-width': 2, opacity: '.55' }));
    const icon = symbol(kind, true); icon.setAttribute('x', '46'); icon.setAttribute('y', '45'); icon.setAttribute('width', '68'); icon.setAttribute('height', '68'); icon.style.color = pearl;
    svg.append(icon);
    for (const [cx, cy, r] of [[80, 10, 7], [80, 150, 5], [10, 80, 3], [150, 80, 3], [121, 59, 5]]) svg.append(svgNode('path', { d: `M${cx} ${cy-r}l${r*.4} ${r*.6} ${r*.6} ${r*.4}-${r*.6} ${r*.4}-${r*.4} ${r*.6}-${r*.4}-${r*.6}-${r*.6}-${r*.4} ${r*.6}-${r*.4}Z`, fill: pearl }));
    return svg;
  }
  window.KflowPersonalityBadge = { kindOf, family, medal };
  window.KflowShowcaseBadge = function (badge) {
    if (!badge?.name) return null;
    const tier = ["gold", "silver", "bronze"].includes(badge.tier) ? badge.tier : "bronze";
    const chip = document.createElement("a");
    chip.className = `showcase-chip tier-${tier}`;
    chip.href = "/achievements";
    chip.title = `佩戴勋章：${badge.name}`;
    chip.setAttribute("aria-label", `佩戴勋章：${badge.name}，查看成就勋章`);
    const kind = kindOf(badge);
    if (kind) {
      chip.className = 'showcase-chip mbti-capsule';
      chip.dataset.mbtiFamily = family(kind);
      chip.style.setProperty('--mbti-delay', `${Object.keys(motifs).indexOf(kind) * -.43}s`);
    }
    const icon = kind ? symbol(kind) : window.kflowIcons.el(badge.icon, 11);
    const name = document.createElement("span");
    name.className = "showcase-chip-name";
    name.textContent = kind || badge.name;
    chip.append(icon, name);
    return chip;
  };
})();
