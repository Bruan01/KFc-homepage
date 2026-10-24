(() => {
  'use strict';
  const $=id=>document.getElementById(id), el=(tag,text,className)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};

  const CATEGORIES = {
    messages: {title:'我的消息', empty:'还没有私信', emptyCopy:'点右上角写消息，和朋友打个招呼。',
               welcomeTitle:'还没有收到消息', welcomeCopy:'快找小伙伴聊天吧 (。-ω-)ﾉ'},
    reply: {title:'回复我的', label:'回复通知', icon:'bubble', cls:'is-reply', empty:'还没有人回复你', emptyCopy:'去社区发个帖子，和更多人交流吧。',
            welcomeTitle:'还没有人回复你', welcomeCopy:'当有人评论你的帖子或碎碎念时，会出现在这里。'},
    mention: {title:'@ 我的', label:'提及通知', icon:'person', cls:'is-mention', empty:'还没有人 @ 你', emptyCopy:'有人在帖子或评论里提到你时，会出现在这里。',
              welcomeTitle:'还没有人 @ 你', welcomeCopy:'被提及的瞬间，会安静地躺在这里。'},
    like: {title:'收到的赞', label:'点赞通知', icon:'heart', cls:'is-like', empty:'还没有收到赞', emptyCopy:'分享你的作品，收获第一颗小心心。',
           welcomeTitle:'还没有收到赞', welcomeCopy:'你的作品被点赞时，会出现在这里。'},
    system: {title:'系统通知', label:'系统通知', icon:'star', cls:'is-system', empty:'暂无系统通知', emptyCopy:'账号、勋章和站务消息都会出现在这里。',
             welcomeTitle:'暂无系统通知', welcomeCopy:'重要的站务消息会出现在这里。'},
  };
  const DIVIDER_GAP = 5 * 60 * 1000;
  // 首屏与上滑都只取 10 条；本地缓存最多留 200 条，避免占满 localStorage。
  const PAGE_SIZE = 10, CACHE_MAX = 200;

  let peer=new URLSearchParams(location.search).get('user')||'';
  let tab=(()=>{const value=new URLSearchParams(location.search).get('tab')||'messages';return CATEGORIES[value]?value:'messages';})();
  let epoch=0,last=0,before=null,loading=false,sending=false,chatReady=false,clientKey=crypto.randomUUID(),inboxPage=1,me,peerIdentity;
  let inboxSignature='',noticeSignature='';

  async function api(path,body){
    const response=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
    const data=await response.json().catch(()=>({}));
    if(response.status===401){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);throw new Error('请先登录');}
    if(!response.ok)throw new Error(data.error||'消息中心暂时不可用');
    return data;
  }
  function error(message){$('messageStatus').textContent=message;$('messageStatus').hidden=!message;}

  function avatar(user){
    const source=user||{},name=source.display_name||source.username||'?';
    const host=el('span',name.slice(0,1),'message-avatar');host.setAttribute('aria-hidden','true');
    if(source.avatar_url){const image=el('img');image.alt='';image.src=source.avatar_url;image.addEventListener('error',()=>host.replaceChildren(document.createTextNode(name.slice(0,1))));host.replaceChildren(image);}
    return host;
  }
  function icon(name,size){
    if(window.kflowIcons)return window.kflowIcons.el(name,size);
    return document.createElement('span');
  }

  const pad=value=>String(value).padStart(2,'0');
  const hm=date=>`${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const sameDay=(a,b)=>a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate();
  function formatDivider(value){
    const date=new Date(value);if(Number.isNaN(date.getTime()))return '';
    const now=new Date(),yesterday=new Date(now);yesterday.setDate(now.getDate()-1);
    if(sameDay(date,now))return hm(date);
    if(sameDay(date,yesterday))return `昨天 ${hm(date)}`;
    if(date.getFullYear()===now.getFullYear())return `${date.getMonth()+1}月${date.getDate()}日 ${hm(date)}`;
    return `${date.getFullYear()}年${date.getMonth()+1}月${date.getDate()}日 ${hm(date)}`;
  }
  function formatListTime(value){
    const date=new Date(value);if(Number.isNaN(date.getTime()))return '';
    const now=new Date(),yesterday=new Date(now);yesterday.setDate(now.getDate()-1);
    if(sameDay(date,now))return hm(date);
    if(sameDay(date,yesterday))return '昨天';
    if(date.getFullYear()===now.getFullYear())return `${date.getMonth()+1}月${date.getDate()}日`;
    return `${date.getFullYear()}/${date.getMonth()+1}/${date.getDate()}`;
  }
  function formatFull(value){const date=new Date(value);return Number.isNaN(date.getTime())?'':date.toLocaleString('zh-CN');}

  // ── 本地缓存 ──────────────────────────────────────────────
  function cacheKey(){return `kflow:dm:${(me&&me.username)||'guest'}:${peer}`;}
  function readCache(){
    try{
      const raw=localStorage.getItem(cacheKey());if(!raw)return {items:[],peer:null};
      const data=JSON.parse(raw);
      return {
        items:Array.isArray(data.items)?data.items.filter(item=>item&&Number.isInteger(item.id)&&typeof item.content==='string'):[],
        peer:data.peer||null,
      };
    }catch{return {items:[],peer:null};}
  }
  function remember(items){
    if(!items||!items.length)return;
    try{
      const store=readCache(),map=new Map(store.items.map(item=>[item.id,item]));
      for(const item of items)map.set(item.id,item);
      const list=[...map.values()].sort((a,b)=>a.id-b.id).slice(-CACHE_MAX);
      localStorage.setItem(cacheKey(),JSON.stringify({v:1,items:list,peer:peerIdentity||store.peer||null,savedAt:Date.now()}));
    }catch{/* 无痕模式或空间不足时静默降级为纯在线加载 */}
  }

  function setBadge(id,count){
    const node=$(id);if(!node)return;
    const total=Math.max(0,Number(count)||0);
    node.hidden=total===0;
    node.textContent=total>99?'99+':String(total);
    node.setAttribute('aria-label',`${total} 条未读`);
  }

  // ── 会话列表 ────────────────────────────────────────────────
  async function loadInbox(){
    try{
      const data=await api(`/api/messages?page=${inboxPage}`);
      if(tab!=='messages')return;
      setBadge('railBadgeMessages',data.unread);
      $('messageUnreadTotal').hidden=!data.unread;
      $('messageUnreadTotal').textContent=data.unread>99?'99+':String(data.unread);
      const signature=JSON.stringify([inboxPage,data.items]);
      if(signature!==inboxSignature){
        inboxSignature=signature;
        const list=$('messageThreads');list.replaceChildren();
        for(const user of data.items){
          const active=user.username===peer;
          const link=el('a',null,'message-thread'+(active?' active':''));
          link.href='/messages?user='+encodeURIComponent(user.username);
          if(active)link.setAttribute('aria-current','page');
          const copy=el('span',null,'message-thread-copy');
          copy.append(el('strong',user.display_name),el('p',user.preview||''));
          const meta=el('span',null,'message-thread-meta');
          const time=el('time',formatListTime(user.last_at),'message-thread-time');
          if(user.last_at)time.dateTime=user.last_at;
          meta.append(time);
          if(user.unread){
            const badge=el('span',user.unread>99?'99+':String(user.unread),'message-unread');
            badge.setAttribute('aria-label',`${user.unread} 条未读消息`);
            meta.append(badge);
          }
          link.append(avatar(user),copy,meta);
          list.append(link);
        }
        if(!data.items.length){
          const empty=el('div',null,'message-list-empty');
          empty.append(el('strong',CATEGORIES.messages.empty),el('p',CATEGORIES.messages.emptyCopy));
          list.append(empty);
        }
      }
      $('inboxPager').hidden=data.total<=20;
      $('inboxPrevious').disabled=inboxPage<=1;
      $('inboxNext').disabled=inboxPage*20>=data.total;
      $('inboxPage').textContent=`${inboxPage} / ${Math.max(1,Math.ceil(data.total/20))}`;
    }catch(e){error(e.message);}
  }

  // ── 通知列表与详情 ──────────────────────────────────────────
  // 有来源用户时优先展示对方头像（像 B 站消息中心那样能一眼认出发消息的人），
  // 没有头像才回落到分类图标。
  function noticeIcon(meta,row,size){
    const host=el('span',null,'notice-icon '+meta.cls);
    const actor=(row&&row.actor)||{};
    if(actor.avatar_url){
      host.classList.add('has-avatar');
      const image=el('img');image.alt='';image.loading='lazy';image.src=actor.avatar_url;
      image.addEventListener('error',()=>{host.classList.remove('has-avatar');host.replaceChildren(icon(meta.icon,size));});
      host.append(image);
    }else host.append(icon(meta.icon,size));
    return host;
  }
  async function loadNotifications(){
    const current=tab;if(current==='messages')return;
    try{
      const data=await api(`/api/notifications?limit=50&category=${current}`);
      if(tab!==current)return;
      const signature=JSON.stringify([current,data.items]);
      if(signature===noticeSignature)return;
      noticeSignature=signature;
      const meta=CATEGORIES[current],list=$('messageThreads');
      list.replaceChildren();
      for(const row of data.items){
        const item=el('button',null,'message-notice'+(row.isRead?' read':' unread'));
        item.type='button';
        const iconHost=noticeIcon(meta,row,18);
        const copy=el('span',null,'notice-copy');
        copy.append(el('strong',row.title||meta.label));
        if(row.body)copy.append(el('p',row.body));
        const time=el('time',formatListTime(row.createdAt));
        if(row.createdAt)time.dateTime=row.createdAt;
        copy.append(time);
        item.append(iconHost,copy);
        if(!row.isRead)item.append(el('span',null,'notice-dot'));
        item.addEventListener('click',()=>openNotice(row,item));
        list.append(item);
      }
      if(data.items.length){
        $('messageWelcomeTitle').textContent='选择一条通知';
        $('messageWelcomeCopy').textContent='点击左侧的通知，查看完整内容。';
      }else{
        const empty=el('div',null,'message-list-empty');
        empty.append(el('strong',meta.empty),el('p',meta.emptyCopy));
        list.append(empty);
      }
    }catch(e){error(e.message);}
  }

  async function openNotice(row,node){
    if(!row.isRead){
      row.isRead=true;
      node.classList.remove('unread');node.classList.add('read');
      node.querySelector('.notice-dot')?.remove();
      try{await api('/api/notifications/mark-read',{ids:[row.id]});}catch{/* 阅读状态稍后轮询会补齐 */}
      refreshCategoryBadges();
    }
    renderNotice(row);
    noticeSignature='';
  }
  function renderNotice(row){
    const meta=CATEGORIES[tab]||CATEGORIES.system;
    const iconHost=$('noticeDetailIcon');
    const next=noticeIcon(meta,row,20);
    next.id='noticeDetailIcon';
    iconHost.replaceWith(next);
    $('noticeDetailKicker').textContent=meta.label;
    $('noticeDetailTime').textContent=formatFull(row.createdAt);
    $('noticeDetailTime').dateTime=row.createdAt||'';
    $('noticeDetailTitle').textContent=row.title||meta.label;
    $('noticeDetailBody').textContent=row.body||'这条通知没有附加说明。';
    const link=$('noticeDetailLink');
    if(row.link){link.href=row.link;link.hidden=false;}else{link.hidden=true;link.removeAttribute('href');}
    $('messageWelcome').hidden=true;$('chatPane').hidden=true;$('noticePane').hidden=false;
    document.body.classList.add('message-pane-open');
  }

  async function refreshCategoryBadges(){
    try{
      const data=await api('/api/notifications/unread-count');
      const counts=data.categories||{};
      setBadge('railBadgeReply',counts.reply);
      setBadge('railBadgeMention',counts.mention);
      setBadge('railBadgeLike',counts.like);
      setBadge('railBadgeSystem',counts.system);
    }catch{/* 未读角标失败不影响阅读 */}
  }

  // ── 聊天 ────────────────────────────────────────────────────
  function applyPolicy(policy,blocked){
    const hint=$('messageLimitHint'),input=$('messageInput'),send=$('messageSend');
    $('messageBlocked').hidden=!blocked;
    if(blocked){
      hint.hidden=true;input.disabled=true;send.disabled=true;return;
    }
    if(policy&&policy.limited){
      const left=Math.max(0,Number(policy.remaining)||0);
      hint.hidden=false;
      hint.classList.toggle('is-locked',left===0);
      hint.textContent=left>0
        ?(policy.following?`你关注了对方，在对方回复前还可以发送 ${left} 条私信`:`对方回复前还可以发送 ${left} 条私信`)
        :'对方还没有回复，暂时无法继续发送私信';
      input.disabled=left===0;
      send.disabled=left===0;
    }else{
      hint.hidden=true;
      input.disabled=false;
      send.disabled=false;
    }
  }

  function bubble(item){
    const row=el('article',null,'message-row'+(item.mine?' mine':''));
    row.dataset.id=item.id;
    row.dataset.ts=String(new Date(item.created_at).getTime()||0);
    const content=el('div',null,'message-bubble');
    content.title=formatFull(item.created_at);
    content.append(el('p',item.content));
    const face=avatar(item.mine?me:peerIdentity);
    if(!item.mine&&peer){
      const link=el('a',null,'message-avatar-link');
      link.href='/forum/user/'+encodeURIComponent(peer);
      link.setAttribute('aria-label',`查看 ${(peerIdentity&&peerIdentity.display_name)||peer} 的主页`);
      link.append(face);
      row.append(link,content);
    }else row.append(face,content);
    return row;
  }
  function refreshDividers(){
    const host=$('messageHistory');
    host.querySelectorAll('.message-time-divider').forEach(node=>node.remove());
    let previous=null;
    for(const row of host.querySelectorAll('.message-row')){
      const ts=Number(row.dataset.ts)||0;
      if(ts&&(!previous||ts-previous>=DIVIDER_GAP)){
        const wrap=el('div',null,'message-time-divider'),time=el('time',formatDivider(ts));
        time.dateTime=new Date(ts).toISOString();
        wrap.append(time);
        row.before(wrap);
      }
      if(ts)previous=ts;
    }
  }

  function renderPeer(identity){
    if(identity)peerIdentity=identity;
    const title=$('messagePeer'),source=peerIdentity||{};
    title.href='/forum/user/'+encodeURIComponent(peer);
    $('messagePeerProfile').href=title.href;
    $('messagePeerName').textContent=source.display_name||peer;
    $('messagePeerHandle').textContent='@'+(source.username||peer);
    $('messagePeerAvatar').replaceChildren(avatar(source));
  }

  function insertBubble(host,item){
    const node=bubble(item),id=Number(item.id);
    const next=[...host.querySelectorAll('.message-row')].find(row=>Number(row.dataset.id)>id);
    host.insertBefore(node,next||null);
  }

  async function thread(mode='initial'){
    if(!peer||loading)return;
    const token=epoch,host=$('messageHistory');loading=true;$('messageOlder').disabled=true;
    if(mode==='initial'){
      // 先用本地缓存把画面撑起来，再让服务器数据补齐/校正。
      const stored=readCache();
      if(stored.peer)renderPeer(stored.peer);
      host.replaceChildren();last=0;
      const cached=stored.items.slice(-PAGE_SIZE);
      if(cached.length){
        const fragment=document.createDocumentFragment();
        cached.forEach(item=>fragment.append(bubble(item)));
        host.append(fragment);
        last=cached[cached.length-1].id;
        refreshDividers();
      }
      $('messageWelcome').hidden=true;$('noticePane').hidden=true;$('chatPane').hidden=false;
      document.body.classList.add('message-pane-open');
    }
    try{
      const query=new URLSearchParams();
      if(mode!=='new')query.set('limit',PAGE_SIZE);
      if(mode==='older'&&before)query.set('before',before);
      if(mode==='new'&&last)query.set('after',last);
      const data=await api(`/api/messages/${encodeURIComponent(peer)}?${query}`);
      if(token!==epoch)return;
      renderPeer(data.peer);if(data.me)me=data.me;
      applyPolicy(data.policy,data.blocked);
      $('messageWelcome').hidden=true;$('noticePane').hidden=true;$('chatPane').hidden=false;
      document.body.classList.add('message-pane-open');
      const atBottom=host.scrollHeight-host.scrollTop-host.clientHeight<60;
      const oldHeight=host.scrollHeight;
      const rows=data.items.filter(item=>!host.querySelector(`[data-id="${item.id}"]`));
      if(mode==='older'){
        rows.forEach(item=>insertBubble(host,item));
        host.scrollTop+=host.scrollHeight-oldHeight;
      }else{
        const fragment=document.createDocumentFragment();
        rows.forEach(item=>fragment.append(bubble(item)));
        host.append(fragment);
      }
      if(rows.length)host.querySelector('.message-conversation-start')?.remove();
      if(mode==='initial'&&!host.querySelector('.message-row'))host.append(el('p','你们的对话从这里开始。','message-empty message-conversation-start'));
      remember(data.items);
      refreshDividers();
      if(data.items.length)last=Math.max(last,...data.items.map(item=>item.id));
      if(last&&!document.hidden)await api(`/api/messages/${encodeURIComponent(peer)}/read`,{upto:last});
      if(mode==='initial'&&!document.hidden)await loadInbox();
      if(mode!=='new'){before=data.next_cursor;$('messageOlder').hidden=!before;}
      if(mode==='initial'||(mode==='new'&&atBottom))host.scrollTop=host.scrollHeight;
    }catch(e){
      error(e.message);
      if(mode==='initial'&&!host.querySelector('.message-row')){document.body.classList.remove('message-pane-open');showWelcome();}
    }finally{loading=false;$('messageOlder').disabled=false;if(mode==='initial')chatReady=true;}
  }

  function showWelcome(){
    chatReady=false;
    $('messageWelcome').hidden=false;$('chatPane').hidden=true;$('noticePane').hidden=true;
    const meta=CATEGORIES[tab]||CATEGORIES.messages;
    $('messageWelcomeTitle').textContent=meta.welcomeTitle;
    $('messageWelcomeCopy').textContent=meta.welcomeCopy;
    document.body.classList.remove('message-pane-open');
  }

  function syncTab(){
    document.querySelectorAll('.message-rail-item').forEach(button=>{
      const active=button.dataset.category===tab;
      button.classList.toggle('active',active);
      if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
    $('messageListTitle').textContent=CATEGORIES[tab].title;
    $('messageUnreadTotal').hidden=tab!=='messages'||$('messageUnreadTotal').hidden;
    const conversations=tab==='messages';
    $('toggleConversation').hidden=!conversations;
    if(!conversations){$('newConversation').hidden=true;$('toggleConversation').setAttribute('aria-expanded','false');}
    $('inboxPager').hidden=!conversations||$('inboxPager').hidden;
    $('messageThreads').scrollTop=0;
    inboxSignature=noticeSignature='';
    const url=conversations?(peer?`/messages?user=${encodeURIComponent(peer)}`:'/messages'):`/messages?tab=${tab}`;
    history.replaceState(null,'',url);
  }

  function setTab(next){
    if(!CATEGORIES[next]||next===tab)return;
    tab=next;
    syncTab();
    showWelcome();
    if(tab==='messages'){
      loadInbox();
      if(peer)thread('initial');
    }else loadNotifications();
  }

  async function init(){
    me=await window.kflowAuthReady;
    if(!me){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);return;}
    function viewport(){
      const visual=window.visualViewport,height=visual?.height||window.innerHeight;
      document.documentElement.style.setProperty('--message-viewport',`${height}px`);
      const shell=document.querySelector('.messages-shell');
      const top=shell?Math.max(0,shell.getBoundingClientRect().top):0;
      document.documentElement.style.setProperty('--message-avail',`${Math.max(280,Math.min(height-8,Math.round(height-top-12)))}px`);
      document.body.classList.toggle('message-keyboard',!!visual&&visual.height<window.innerHeight*.75);
    }
    viewport();window.visualViewport?.addEventListener('resize',viewport);window.addEventListener('resize',viewport);

    document.querySelectorAll('.message-rail-item').forEach(button=>button.addEventListener('click',()=>setTab(button.dataset.category)));
    $('newConversation').addEventListener('submit',event=>{event.preventDefault();const username=$('messageUsername').value.trim();if(username)location.href='/messages?user='+encodeURIComponent(username);});
    function newConversation(open){
      if(open&&tab!=='messages')setTab('messages');
      $('newConversation').hidden=!open;
      $('toggleConversation').setAttribute('aria-expanded',String(open));
      if(open){if(window.matchMedia('(max-width:700px)').matches)document.body.classList.remove('message-pane-open');$('messageUsername').focus();}
    }
    $('toggleConversation').onclick=()=>newConversation($('newConversation').hidden);
    $('inboxPrevious').onclick=()=>{inboxPage--;loadInbox();};
    $('inboxNext').onclick=()=>{inboxPage++;loadInbox();};
    $('messageOlder').onclick=()=>thread('older');
    $('messageHistory').addEventListener('scroll',()=>{
      const host=$('messageHistory');
      if(!chatReady||loading||!before||tab!=='messages'||!peer)return;
      if(host.scrollHeight-host.clientHeight<120||host.scrollTop>48)return;
      thread('older');
    },{passive:true});
    $('noticeBack').onclick=()=>showWelcome();

    const input=$('messageInput'),tools=$('messageTools');
    tools.append(window.KflowEditor.emojiPicker(input,2000,()=>input.dispatchEvent(new Event('input')),()=>sending||input.disabled,error));
    input.addEventListener('input',()=>{clientKey=crypto.randomUUID();$('messageCount').textContent=`${[...input.value].length} / 2000`;});
    window.KflowEditor.enterToSend(input,{form:$('messageForm')});
    $('messageForm').addEventListener('submit',async event=>{
      event.preventDefault();
      if(sending||input.disabled)return;
      const content=input.value.trim();
      if(!content){error('请输入私信内容');return;}
      sending=true;input.disabled=true;$('messageSend').disabled=true;$('messageSend').querySelector('span').textContent='发送中…';
      try{
        await api(`/api/messages/${encodeURIComponent(peer)}`,{content,client_key:clientKey});
        input.value='';clientKey=crypto.randomUUID();error('');$('messageCount').textContent='0 / 2000';
        await thread('new');await loadInbox();
      }catch(e){
        error(e.message);
        try{$('messageInput').disabled=false;$('messageSend').disabled=false;}catch{/* ignore */}
      }finally{
        sending=false;
        if(!$('messageBlocked').hidden||$('messageLimitHint').classList.contains('is-locked')){
          input.disabled=true;$('messageSend').disabled=true;
        }else{input.disabled=false;$('messageSend').disabled=false;input.focus();}
        $('messageSend').querySelector('span').textContent='发送';
      }
    });

    syncTab();
    if(tab==='messages'){
      await loadInbox();
      if(peer)await thread('initial');
      else showWelcome();
    }else{
      showWelcome();
      await loadNotifications();
    }
    refreshCategoryBadges();
    setInterval(()=>{
      if(document.hidden||sending||loading)return;
      refreshCategoryBadges();
      if(tab==='messages'){loadInbox();if(peer)thread('new');}
      else loadNotifications();
    },15000);
  }
  document.addEventListener('DOMContentLoaded',()=>init().catch(e=>error(e.message)));
})();
