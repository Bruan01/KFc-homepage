(() => {
  "use strict";
  let nextId = 0;
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
    }
    node.append(...children.filter(v => v != null)); return node;
  }
  function icon(name) {
    const paths = {
      smile: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM8 14s1.5 3 4 3 4-3 4-3M8.5 8.5h.01M15.5 8.5h.01',
      image: 'M4 4h16v16H4zM4 16l5-5 4 4 3-3 4 4M15 8h.01',
      mention: 'M16 8v6a2 2 0 0 0 4 0v-2a8 8 0 1 0-3 6.2M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
    };
    const span = el("span", {className:"ce-icon", "aria-hidden":"true"});
    span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[name]}"/></svg>`;
    return span;
  }
  function button(label, action, className="ce-button") { return el("button", {type:"button", className, onClick:action}, label); }
  function avatar(author) { return el("span", {className:"ce-initial", "aria-hidden":"true", text:[...(author.display_name || author.username)][0]}); }
  async function api(url, options={}) {
    const response = await fetch(url, {credentials:"same-origin", ...options});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) throw new Error(data.error || "操作未完成，请稍后再试"); return data;
  }
  const COMMENT_EMOJIS = [
    ["😀", "开心"], ["😂", "笑哭"], ["🤣", "大笑"], ["🥹", "感动"], ["😊", "微笑"], ["😍", "喜欢"], ["🥰", "幸福"], ["😘", "亲亲"],
    ["😎", "酷"], ["🤔", "思考"], ["🫡", "敬礼"], ["🙃", "倒脸"], ["😭", "哭泣"], ["🥲", "含泪微笑"], ["😅", "尴尬"], ["😴", "困了"],
    ["👍", "赞"], ["👎", "踩"], ["👏", "鼓掌"], ["🙌", "欢呼"], ["🙏", "感谢"], ["💪", "加油"], ["🤝", "握手"], ["🫶", "比心"],
    ["❤️", "爱心"], ["💔", "心碎"], ["🔥", "火热"], ["✨", "闪亮"], ["🎉", "庆祝"], ["🚀", "起飞"], ["☕", "咖啡"], ["🐱", "猫咪"],
  ];
  function emojiPicker(input, limit, changed, disabled, fail) {
    const picker = el("details", { className: "mm-emoji-picker" });
    const toggle = el("summary", { className: "mm-image-button", "aria-label": "选择 Emoji" }, icon("smile"), "表情");
    const emojis = el("div", { className: "mm-emoji-grid", popover:"manual", role: "group", "aria-label": "常用 Emoji" });
    let positioning;
    function place() {
      if (!picker.isConnected) {close();return;}
      const rect = toggle.getBoundingClientRect(), viewport = window.visualViewport;
      const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
      const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight;
      const panelWidth = Math.min(286,width-24), above = rect.top-top-12, below = top+height-rect.bottom-12;
      const opensUp = above>=220 || above>below;
      Object.assign(emojis.style,{position:"fixed",margin:"0",bottom:"auto",width:`${panelWidth}px`,left:`${Math.max(left+12,Math.min(rect.left,left+width-panelWidth-12))}px`,maxHeight:`${Math.max(80,Math.min(260,opensUp?above:below))}px`});
      emojis.style.top=`${opensUp?Math.max(top+8,rect.top-emojis.offsetHeight-6):rect.bottom+6}px`;
    }
    function close() {
      if(emojis.hidePopover && emojis.matches(":popover-open"))emojis.hidePopover();
      positioning?.abort();positioning=null;
    }
    picker.addEventListener("toggle",()=>{
      if(!picker.open){close();return;}
      if(emojis.showPopover && !emojis.matches(":popover-open"))emojis.showPopover();
      place();if(positioning)return;positioning=new AbortController();
      document.addEventListener("scroll",place,{capture:true,passive:true,signal:positioning.signal});
      window.addEventListener("resize",place,{signal:positioning.signal});
      window.visualViewport?.addEventListener("resize",place,{signal:positioning.signal});
    });
    for (const [emoji, label] of COMMENT_EMOJIS) {
      const choose = button(emoji, () => {
        if (disabled()) return;
        const start = input.selectionStart, end = input.selectionEnd;
        if ([...(input.value.slice(0, start) + emoji + input.value.slice(end))].length > limit) { fail(`最多支持 ${limit} 个字`); return; }
        input.setRangeText(emoji, start, end, "end"); changed(); picker.open = false; input.focus();
      }, "mm-emoji");
      choose.setAttribute("aria-label", label); choose.title = label; emojis.append(choose);
    }
    picker.append(toggle, emojis);
    picker.addEventListener("keydown", (event) => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); picker.open = false; toggle.focus(); } });
    document.addEventListener("pointerdown", function outside(event) {
      if (!picker.isConnected) { document.removeEventListener("pointerdown", outside); return; }
      if (!picker.contains(event.target)) picker.open = false;
    });
    return picker;
  }
  function mentionPicker(input, changed, disabled, limit, fail, loggedIn = () => true) {
    const panel = el("section", { className: "mm-mention-picker", hidden: true, popover:"manual", "aria-label": "选择关注的人" });
    const title = el("strong", { text: "提及关注的人" });
    const status = el("p", { className: "mm-comment-hint", role: "status" });
    const list = el("div", { role: "listbox", id: `${input.id}-mentions`, "aria-label": "关注的人" });
    const more = button("加载更多", () => search(true), "mm-text-button"); more.hidden = true;
    panel.append(title, status, list, more);
    input.setAttribute("aria-controls", list.id); input.setAttribute("aria-autocomplete", "list");
    let query = "", start = 0, end = 0, cursor = null, matches = [], active = -1, epoch = 0, timer;
    let positioning;
    function position() {
      if (panel.hidden) return;
      if (!input.isConnected) {hide();return;}
      const rect = input.getBoundingClientRect(), viewport = window.visualViewport;
      const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
      const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight;
      const panelWidth = Math.min(300, width - 24);
      panel.style.width = `${panelWidth}px`;
      panel.style.left = `${Math.max(left + 12, Math.min(rect.left, left + width - panelWidth - 12))}px`;
      const below = top + height - rect.bottom - 16, above = rect.top - top - 16;
      const opensUp = below < 220 && above > below;
      panel.style.maxHeight = `${Math.max(80, Math.min(276, opensUp ? above : below))}px`;
      panel.style.top = `${opensUp ? Math.max(top + 8, rect.top - panel.offsetHeight - 6) : Math.max(top + 8, rect.bottom + 6)}px`;
    }
    function hide() {
      if (panel.hidePopover && panel.matches(":popover-open")) panel.hidePopover();
      panel.hidden = true; positioning?.abort(); positioning = null;
      ++epoch; clearTimeout(timer); input.removeAttribute("aria-activedescendant");
    }
    function show() {
      panel.hidden = false;
      if (panel.showPopover && !panel.matches(":popover-open")) panel.showPopover();
      position();
      if (positioning) return;
      positioning = new AbortController();
      document.addEventListener("scroll", position, {capture:true, passive:true, signal:positioning.signal});
      window.addEventListener("resize", position, {signal:positioning.signal});
      window.visualViewport?.addEventListener("resize", position, {signal:positioning.signal});
    }
    function context() {
      const left = input.value.slice(0, input.selectionStart);
      const match = left.match(/(^|[^\p{L}\p{N}_@])@([^\s@{}]{0,150})$/u);
      if (!match) return null;
      return { query: match[2], start: left.length - match[2].length - 1, end: input.selectionStart };
    }
    function select(index) {
      if (disabled()) return;
      const author = matches[index]; if (!author) return;
      const token = /^[\p{L}\p{N}_-]+$/u.test(author.username) ? `@${author.username} ` : `@{${author.username}} `;
      if ([...(input.value.slice(0, start) + token + input.value.slice(end))].length > limit) { fail(`最多支持 ${limit} 个字`); return; }
      input.setRangeText(token, start, end, "end"); changed(); hide(); input.focus();
    }
    function highlight(index) {
      active = index;
      [...list.children].forEach((item, i) => item.setAttribute("aria-selected", String(i === index)));
      const item = list.children[index];
      if (item) { input.setAttribute("aria-activedescendant", item.id); item.scrollIntoView({ block: "nearest" }); }
    }
    async function search(append = false) {
      const token = ++epoch;
      status.textContent = "正在查找关注的人…"; more.disabled = true; more.textContent = "加载更多";
      const params = new URLSearchParams({ q: query }); if (append && cursor) params.set("after", cursor);
      if (!append) { list.replaceChildren(); matches = []; active = -1; cursor = null; more.hidden = true; input.removeAttribute("aria-activedescendant"); }
      try {
        const data = await api(`/api/users/mentions?${params}`);
        if (token !== epoch || panel.hidden) return;
        for (const author of data.items) {
          const index = matches.length; matches.push(author);
          const item = button("", () => select(index), "mm-mention-option");
          item.id = `${input.id}-mention-${index}`; item.setAttribute("role", "option"); item.setAttribute("aria-selected", "false");
          item.append(avatar(author, false), el("span", {}, el("strong", { text: author.display_name }), el("small", { text: `@${author.username}` })));
          if (author.is_official) item.querySelector("strong").append(" ", window.KflowSocial?.officialBadge?.() || el("span", {text:"官方"}));
          item.addEventListener("pointerdown", (event) => event.preventDefault()); list.append(item);
        }
        cursor = data.next_cursor; more.hidden = !cursor;
        status.textContent = matches.length ? "↑↓ 选择 · Enter 确认" : query ? "没有找到，试试昵称或用户名" : "先关注朋友，就能在这里提及 TA";
      } catch (error) { if (token === epoch) { status.textContent = error.message; more.textContent = "重试"; more.hidden = false; } }
      finally { if (token === epoch) {more.disabled = false; position();} }
    }
    function update(event) {
      if (event?.isComposing || disabled()) return;
      const value = context();
      if (!value || !loggedIn()) { hide(); return; }
      ({ query, start, end } = value); show();
      list.replaceChildren(); matches = []; active = -1; more.hidden = true; input.removeAttribute("aria-activedescendant");
      ++epoch; clearTimeout(timer); timer = setTimeout(() => search(), 160);
    }
    const trigger = button("", () => {
      if (!loggedIn() || disabled()) return;
      const prefix = input.selectionStart && !/\s$/.test(input.value.slice(0, input.selectionStart)) ? " @" : "@";
      if ([...input.value].length + prefix.length > limit) { fail(`最多支持 ${limit} 个字`); return; }
      input.setRangeText(prefix, input.selectionStart, input.selectionEnd, "end"); changed(); input.focus(); update();
    }, "mm-image-button");
    trigger.append(icon("mention"), "提及");
    trigger.setAttribute("aria-label", "提及关注的人");
    input.addEventListener("input", update); input.addEventListener("compositionend", update); input.addEventListener("click", update);
    input.addEventListener("keyup", (event) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) update(); });
    input.addEventListener("keydown", (event) => {
      if (panel.hidden || event.isComposing) return;
      if (event.key === "Escape") { event.preventDefault(); hide(); }
      else if (["ArrowDown", "ArrowUp"].includes(event.key) && matches.length) { event.preventDefault(); highlight((active + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length); }
      else if (event.key === "Enter" && active >= 0) { event.preventDefault(); select(active); }
    });
    window.addEventListener("kflow:follow-changed", function refresh() {
      if (!input.isConnected) { window.removeEventListener("kflow:follow-changed", refresh); return; }
      if (!panel.hidden) search();
    });
    document.addEventListener("pointerdown", function outside(event) {
      if (!input.isConnected) { document.removeEventListener("pointerdown", outside); return; }
      if (event.target !== input && !panel.contains(event.target) && !trigger.contains(event.target)) hide();
    });
    return { panel, trigger, hide };
  }

  const PATTERN = /(^|[^\p{L}\p{N}_@])@(?:\{([^{}\n]{1,150})\}|([\p{L}\p{N}_-]{1,150}))(?![\p{L}\p{N}_-])/gu;
  function plainMentions(host, value, allowed=[]) {
    const names = new Set(allowed); let offset=0;
    for (const match of value.matchAll(PATTERN)) {
      const username=match[2] || match[3], start=match.index+match[1].length;
      if (!names.has(username)) continue;
      host.append(document.createTextNode(value.slice(offset,start)), el("a", {className:"mm-mention-link user-mention", href:`/forum/user/${encodeURIComponent(username)}`, text:`@${username}`}));
      offset=match.index+match[0].length;
    }
    host.append(document.createTextNode(value.slice(offset)));
  }
  function linkify(root, allowed=[]) {
    const walker=document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode(node) {return node.parentElement?.closest("pre,code,a") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;}});
    const nodes=[]; while(walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) { const fragment=document.createDocumentFragment(); plainMentions(fragment,node.nodeValue,allowed); node.replaceWith(fragment); }
  }
  function attach(input, options={}) {
    if (input._communityEditor) return input._communityEditor;
    input.id ||= `community-input-${++nextId}`;
    const change=()=>input.dispatchEvent(new Event("input",{bubbles:true}));
    const fail=options.onError || (message=>alert(message));
    const disabled=()=>input.disabled;
    const tools=el("div",{className:"ce-tools"});
    const emojis=emojiPicker(input,options.limit || 10000,change,disabled,fail);
    const mentions=mentionPicker(input,change,disabled,options.limit || 10000,fail,options.loggedIn || (()=>true));
    tools.append(emojis,mentions.trigger);
    const anchor = input.closest?.(".markdown-editor") || input;
    anchor.after(tools,mentions.panel);
    input._communityEditor={tools,mentions}; return input._communityEditor;
  }
  function attachments(input, options={}) {
    const items=[];
    const host=el("div",{className:"ce-attachments"}), previews=el("div",{className:"ce-previews"});
    const files=el("input",{type:"file",accept:"image/jpeg,image/png,image/webp,image/gif",multiple:true,hidden:true});
    const add=button("",()=>files.click(),"ce-button");
    add.append(icon("image"),"图片"); add.title="添加图片或表情包"; add.setAttribute("aria-label","添加图片或表情包");
    const fail=options.onError || alert;
    function render() {
      previews.replaceChildren(...items.map(item=>{
        const remove=button("×",()=>{if(host.inert)return; item.abort.abort(); items.splice(items.indexOf(item),1); URL.revokeObjectURL(item.url); render();},"ce-remove");
        remove.setAttribute("aria-label","移除待发送图片");
        remove.addEventListener("pointerdown",event=>event.preventDefault());
        return el("figure",{},el("img",{src:item.url,alt:"待发送图片"}),el("span",{className:"ce-upload-status",text:item.id?"":item.failed?"上传失败，请移除后重试":"上传中…"}),remove);
      }));
    }
    async function upload(selected) {
      for(const file of selected) {
        if(items.length>=4){fail("每条评论最多 4 张图片");break;}
        if(!/^image\/(jpeg|png|webp|gif)$/.test(file.type)||file.size>5*1024*1024){fail("请选择不超过 5 MB 的 JPG、PNG、WebP 或 GIF");continue;}
        const item={url:URL.createObjectURL(file),abort:new AbortController()}; items.push(item);render();
        const body=new FormData();body.append("file",file);
        try {const data=await api("/api/forum/images",{method:"POST",body,signal:item.abort.signal});item.id=data.image.id;}
        catch(error){if(error.name!=="AbortError"){item.failed=true;fail(error.message);}}
        render();
      }
    }
    files.addEventListener("change",()=>{upload([...files.files]);files.value="";});
    input.addEventListener("paste",event=>{const images=[...(event.clipboardData?.files||[])].filter(file=>file.type.startsWith("image/"));if(images.length){event.preventDefault();upload(images);}});
    host.append(add,files,previews);input._communityEditor?.tools.append(host);
    return {host, get ids(){return items.map(i=>i.id).filter(Boolean);},get pending(){return items.some(i=>!i.id);},clear(){items.forEach(i=>{i.abort.abort();URL.revokeObjectURL(i.url);});items.length=0;render();}};
  }
  window.KflowEditor={emojiPicker,mentionPicker,plainMentions,linkify,attach,attachments};
})();
