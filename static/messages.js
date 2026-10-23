(() => {
  'use strict';
  const $=id=>document.getElementById(id), el=(tag,text,className)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(className)node.className=className;return node;};
  let peer=new URLSearchParams(location.search).get('user')||'',epoch=0,last=0,before=null,loading=false,sending=false,clientKey=crypto.randomUUID(),inboxPage=1,me,peerIdentity,inboxSignature='';
  async function api(path,body){const response=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});const data=await response.json().catch(()=>({}));if(response.status===401){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);throw new Error('请先登录');}if(!response.ok)throw new Error(data.error||'私信暂时不可用');return data;}
  function error(message){$('messageStatus').textContent=message;$('messageStatus').hidden=!message;}
  function avatar(user){
    const host=el('span',(user.display_name||user.username||'?').slice(0,1),'message-avatar');host.setAttribute('aria-hidden','true');
    if(user.avatar_url){const image=el('img');image.alt='';image.src=user.avatar_url;image.addEventListener('error',()=>host.replaceChildren(document.createTextNode((user.display_name||user.username).slice(0,1))));host.replaceChildren(image);}
    return host;
  }
  async function inbox(){try{
    const data=await api(`/api/messages?page=${inboxPage}`),signature=JSON.stringify([inboxPage,data]),list=$('messageThreads');
    $('messageUnreadTotal').hidden=!data.unread;$('messageUnreadTotal').textContent=data.unread>99?'99+':data.unread;
    if(signature!==inboxSignature){inboxSignature=signature;list.replaceChildren();for(const user of data.items){
      const active=user.username===peer,link=el('a',null,'message-thread'+(active?' active':''));link.href='/messages?user='+encodeURIComponent(user.username);
      if(active)link.setAttribute('aria-current','page');
      const copy=el('span',null,'message-thread-copy');copy.append(el('strong',user.display_name),el('p',user.preview));link.append(avatar(user),copy);
      if(user.unread){const badge=el('span',user.unread>99?'99+':user.unread,'message-unread');badge.setAttribute('aria-label',`${user.unread} 条未读消息`);link.append(badge);}list.append(link);
    }if(!data.items.length){const empty=el('div',null,'message-list-empty');empty.append(el('strong','还没有私信'),el('p','点右上角写消息，和朋友打个招呼。'));list.append(empty);}}
    $('inboxPager').hidden=data.total<=20;$('inboxPrevious').disabled=inboxPage<=1;$('inboxNext').disabled=inboxPage*20>=data.total;$('inboxPage').textContent=`${inboxPage} / ${Math.max(1,Math.ceil(data.total/20))}`;
  }catch(e){error(e.message);}}
  function bubble(item){
    const row=el('article',null,'message-row'+(item.mine?' mine':''));row.dataset.id=item.id;
    const content=el('div',null,'message-bubble'),meta=el('div',null,'message-meta'),time=el('time',new Date(item.created_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}));
    time.dateTime=item.created_at;time.title=new Date(item.created_at).toLocaleString('zh-CN');meta.append(time);
    if(item.mine)meta.append(el('span',item.is_read?'已读':'已发送'));
    content.append(el('p',item.content),meta);row.append(avatar(item.mine?me:peerIdentity),content);return row;
  }
  async function thread(mode='initial'){
    if(!peer||loading)return;const token=epoch;loading=true;$('messageOlder').disabled=true;
    try{const query=new URLSearchParams();if(mode==='older'&&before)query.set('before',before);if(mode==='new'&&last)query.set('after',last);
      const data=await api(`/api/messages/${encodeURIComponent(peer)}?${query}`);if(token!==epoch)return;
      peerIdentity=data.peer;
      const title=$('messagePeer');title.href='/forum/user/'+encodeURIComponent(peer);$('messagePeerProfile').href=title.href;
      $('messagePeerName').textContent=data.peer.display_name;$('messagePeerHandle').textContent='@'+data.peer.username;$('messagePeerAvatar').replaceChildren(avatar(data.peer));
      $('messagePaneHead').hidden=false;$('messageHistory').hidden=false;
      $('messageForm').hidden=false;$('messageSend').disabled=data.blocked;$('messageInput').disabled=data.blocked;
      $('messageBlocked').hidden=!data.blocked;
      const host=$('messageHistory'),atBottom=host.scrollHeight-host.scrollTop-host.clientHeight<60;
      if(mode==='initial'){host.replaceChildren();last=0;}
      const rows=data.items.filter(item=>!host.querySelector(`[data-id="${item.id}"]`));const fragment=document.createDocumentFragment();rows.forEach(item=>fragment.append(bubble(item)));
      if(rows.length)host.querySelector('.message-conversation-start')?.remove();
      if(mode==='older'){const oldHeight=host.scrollHeight;host.prepend(fragment);host.scrollTop+=host.scrollHeight-oldHeight;}
      else host.append(fragment);
      if(mode==='initial'&&!data.items.length)host.append(el('p','你们的对话从这里开始。','message-empty message-conversation-start'));
      if(data.items.length)last=Math.max(last,...data.items.map(item=>item.id));
      if(last && !document.hidden)await api(`/api/messages/${encodeURIComponent(peer)}/read`,{upto:last});
      if(mode!=='new'){before=data.next_cursor;$('messageOlder').hidden=!before;}
      if(mode==='initial'||(mode==='new'&&atBottom))host.scrollTop=host.scrollHeight;
      $('messagePlaceholder').hidden=true;
    }catch(e){error(e.message);if(mode==='initial')document.body.classList.remove('message-has-peer');}finally{loading=false;$('messageOlder').disabled=false;}
  }
  async function init(){
    me=await window.kflowAuthReady;if(!me){location.href='/login?next='+encodeURIComponent(location.pathname+location.search);return;}
    document.body.classList.toggle('message-has-peer',!!peer);
    function viewport(){const visual=window.visualViewport;document.documentElement.style.setProperty('--message-viewport',`${visual?.height||window.innerHeight}px`);document.body.classList.toggle('message-keyboard',!!visual&&visual.height<window.innerHeight*.75);}
    viewport();window.visualViewport?.addEventListener('resize',viewport);window.addEventListener('resize',viewport);
    $('newConversation').addEventListener('submit',event=>{event.preventDefault();const username=$('messageUsername').value.trim();if(username)location.href='/messages?user='+encodeURIComponent(username);});
    function newConversation(open){$('newConversation').hidden=!open;$('toggleConversation').setAttribute('aria-expanded',String(open));if(open){if(window.matchMedia('(max-width:640px)').matches)document.body.classList.remove('message-has-peer');$('messageUsername').focus();}}
    $('toggleConversation').onclick=()=>newConversation($('newConversation').hidden);
    $('startFirstConversation').onclick=()=>newConversation(true);
    $('inboxPrevious').onclick=()=>{inboxPage--;inbox();};$('inboxNext').onclick=()=>{inboxPage++;inbox();};
    $('messageOlder').onclick=()=>thread('older');
    const input=$('messageInput'),tools=$('messageTools');
    tools.append(window.KflowEditor.emojiPicker(input,2000,()=>input.dispatchEvent(new Event('input')),()=>sending||input.disabled,error));
    input.addEventListener('input',()=>{clientKey=crypto.randomUUID();$('messageCount').textContent=`${[...input.value].length} / 2000`;});
    $('messageForm').addEventListener('submit',async event=>{event.preventDefault();if(sending||input.disabled)return;const content=input.value.trim();if(!content){error('请输入私信内容');return;}sending=true;input.disabled=true;$('messageSend').disabled=true;$('messageSend').querySelector('span').textContent='发送中…';
      try{await api(`/api/messages/${encodeURIComponent(peer)}`,{content,client_key:clientKey});input.value='';clientKey=crypto.randomUUID();error('');$('messageCount').textContent='0 / 2000';await thread('new');await inbox();}
      catch(e){error(e.message);}finally{sending=false;if(!$('messageBlocked').hidden){input.disabled=true;$('messageSend').disabled=true;}else{input.disabled=false;$('messageSend').disabled=false;input.focus();}$('messageSend').querySelector('span').textContent='发送';}
    });
    await inbox();if(peer)await thread();
    setInterval(()=>{if(document.hidden||sending||loading)return;inbox();if(peer)thread('new');},15000);
  }
  document.addEventListener('DOMContentLoaded',()=>init().catch(e=>error(e.message)));
})();
