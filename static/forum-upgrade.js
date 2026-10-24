(() => {
  "use strict";
  const node=(tag,attrs={},...children)=>{const item=document.createElement(tag);for(const [key,value] of Object.entries(attrs)){if(key==='text')item.textContent=value;else if(key==='className')item.className=value;else item.setAttribute(key,value);}item.append(...children);return item;};
  async function api(url,body) { const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error || '操作失败，请重试');return data; }
  let viewer=null;
  window.addEventListener('kflow:auth-changed',event=>{viewer=event.detail;});
  function collectPoll(){if(!document.getElementById('topicPollEnabled')?.checked)return null;return {question:document.getElementById('topicPollQuestion').value, multiple:document.getElementById('topicPollMultiple').checked, options:document.getElementById('topicPollOptions').value.split('\n').map(v=>v.trim()).filter(Boolean)};}
  function renderPoll(topic,container,toast) {
    if(!topic.poll)return;
    const poll=topic.poll;
    const form=node('form',{className:'community-poll'},node('h3',{text:poll.question}),node('small',{text:`${poll.multiple?'多选':'单选'} · ${poll.voters} 人参与 · 每个账号投票一次，提交后不可修改`}));
    for(const option of poll.options){
      const input=node('input',{type:poll.multiple?'checkbox':'radio',name:'poll-option',value:option.id});input.checked=option.selected;input.disabled=poll.voted;
      const label=node('label',{},input,node('span',{text:option.text}));
      if(poll.voted){const percent=poll.voters?Math.round(option.votes/poll.voters*100):0;const bar=node('span',{className:'poll-bar','aria-hidden':'true'});bar.style.width=`${percent}%`;label.append(bar,node('small',{text:`${option.votes} 票 · ${percent}%`}));}
      form.append(label);
    }
    const submit=node('button',{type:'submit',className:'ce-button',text:poll.voted?'已投票':'提交投票'});submit.disabled=poll.voted;form.append(submit);
    form.addEventListener('submit',async event=>{event.preventDefault();const options=[...form.querySelectorAll('input:checked')].map(input=>Number(input.value));if(!options.length){toast('请先选择投票选项','warn');return;}submit.disabled=true;try{const data=await api(`/api/forum/topics/${topic.id}/poll/vote`,{options});topic.poll=data.poll;form.remove();renderPoll(topic,container,toast);toast('投票成功','success');}catch(error){toast(error.message,'error');submit.disabled=false;}});
    container.querySelector('.detail-body')?.after(form);
  }
  function render(container,topic,{currentUser,onSent,toast}) {
    renderPoll(topic,container,toast);
    const form=container.querySelector('#replyForm'),input=form?.querySelector('textarea');if(!input)return;
    input.required=false;
    const editor=window.KflowEditor.attach(input,{limit:10000,loggedIn:()=>!!currentUser,onError:message=>toast(message,'error')});
    window.KflowEditor.enterToSend(input,{form,blocked:()=>editor.mentions.pending()});
    const attachments=window.KflowEditor.attachments(input,{onError:message=>toast(message,'error')});
    form.onsubmit=async event=>{
      event.preventDefault();if(form.dataset.sending==='1')return;
      if(attachments.pending){toast('请等待图片上传完成，或移除失败的图片','warn');return;}
      const content=input.value.trim();if(!content&&!attachments.ids.length){toast('写点什么或添加图片吧','warn');return;}
      const submit=form.querySelector('[type=submit]');form.dataset.sending='1';if(submit)submit.disabled=true;attachments.host.inert=true;input.disabled=true;
      try{await api(`/api/forum/topics/${topic.id}/replies`,{content,images:attachments.ids});input.value='';attachments.clear();toast('回复已发布','success');await onSent();}
      catch(error){toast(error.message,'error');}
      finally{form.dataset.sending='0';if(submit)submit.disabled=false;input.disabled=false;attachments.host.inert=false;}
    };
    const target=new URLSearchParams(location.search).get('comment');
    if(target){const all=node('button',{type:'button',className:'ce-button',text:'查看全部回复'});all.onclick=()=>{const url=new URL(location.href);url.searchParams.delete('comment');url.hash='';history.replaceState({},'',url);onSent();};container.querySelector('.replies-heading')?.after(all);requestAnimationFrame(()=>container.querySelector(`#forum-reply-${Number(target)}`)?.scrollIntoView({block:'center'}));}
  }
  function init(){
    const input=document.getElementById('topicContent');if(input)window.KflowEditor.attach(input,{limit:20000,loggedIn:()=>!!viewer,onError:message=>alert(message)});
    window.kflowAuthReady?.then?.(user=>{viewer=user;});
    const enabled=document.getElementById('topicPollEnabled'),fields=document.getElementById('topicPollFields');enabled?.addEventListener('change',()=>{fields.hidden=!enabled.checked;});
    document.getElementById('newTopicForm')?.addEventListener('reset',()=>queueMicrotask(()=>{fields.hidden=true;}));
    const resize=()=>document.documentElement.style.setProperty('--compose-height',`${window.visualViewport?.height || window.innerHeight}px`);resize();window.visualViewport?.addEventListener('resize',resize);
  }
  window.KflowForumExtras={collectPoll,render};
  document.addEventListener('DOMContentLoaded',init);
})();
