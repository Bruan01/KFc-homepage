(() => {
  'use strict';
  const $=id=>document.getElementById(id),status=$('admin-status');
  let timer,loading=false;
  const node=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;};
  async function api(path='',body){
    const response=await fetch('/api/admin/personality/operations'+path,{credentials:'same-origin',method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1]||''},...(body?{body:JSON.stringify(body)}:{})});
    if(response.status===401){window.PersonalityAdminAuth?.requireLogin();throw Error('管理员登录已失效，请重新登录。');}
    const data=await response.json();if(!response.ok)throw Error(response.status===403?'此页面需要主管理员权限。':data.error||'暂时无法读取，请稍后刷新。');return data;
  }
  const date=value=>value?new Date(value).toLocaleString('zh-CN'):'—';
  async function act(button,path){button.disabled=true;try{await api(path,{});status.textContent='已记录处理状态。';await load();}catch(error){status.textContent=error.message;status.classList.add('status-error');button.disabled=false;}}
  function render(data){
    $('readiness-result').textContent=data.readiness.ready?'可以对外开放':'完整服务条件尚未就绪';
    $('readiness-result').className=data.readiness.ready?'operations-pass':'status-error';
    $('operations-checked').textContent='检查于 '+date(data.readiness.checked_at)+' · 页面可见时自动刷新';
    $('readiness-checks').replaceChildren(...data.readiness.checks.map(check=>{const card=node('article',undefined,'readiness-item');const heading=node('div',undefined,'row');heading.append(node('h3',check.name),node('span',check.ready?'就绪':'待处理',check.ready?'operations-pass':'status-error'));card.append(heading,node('p',check.detail));if(!check.ready&&check.href){const link=node('a','前往处理');link.href=check.href;card.append(link);}return card;}));
    $('alert-count').textContent=data.counts.alerts+' 项待查看';$('feedback-count').textContent=data.counts.feedback+' 条未处理反馈';
    $('operations-alerts').replaceChildren(...data.alerts.map(alert=>{
      const card=node('article',undefined,'operations-item'),heading=node('div',undefined,'row');
      heading.append(node('h3',(alert.kind==='followup'?'补充追问':'人格报告')+' · '+(alert.code==='failed'?'处理未完成':'等待时间较长')),node('span',alert.status==='acknowledged'?'已知悉':'待查看','quiet'));
      const actions=node('div',undefined,'operations-actions'),link=node('a','查看分析记录','secondary');link.href='/admin/personality/analysis?id='+encodeURIComponent(alert.assessment_id);actions.append(link);
      if(alert.status!=='acknowledged'){const button=node('button','标记已知悉','secondary');button.type='button';button.onclick=()=>act(button,'/alerts/'+alert.id+'/acknowledge');actions.append(button);}
      card.append(heading,node('p','档案 '+alert.assessment_id,'operations-id'),node('p','最近任务进展：'+date(alert.updated_at),'quiet'),actions);return card;
    }));
    if(!data.alerts.length)$('operations-alerts').append(node('p','当前没有需要留意的任务。','quiet'));
    $('question-feedback-list').replaceChildren(...data.feedback.map(item=>{const card=node('article',undefined,'operations-item');card.append(node('p',item.question,'feedback-question'),node('p',item.version+' · '+item.question_id+' · '+item.pending+' 条待处理 / 累计 '+item.count+' 条','quiet'));const button=node('button','标记已处理','secondary');button.type='button';button.onclick=()=>act(button,'/feedback/'+item.id+'/handle');card.append(button);return card;}));
    if(!data.feedback.length)$('question-feedback-list').append(node('p','暂时没有新的题目理解反馈。','quiet'));
  }
  async function load(){
    clearTimeout(timer);if(loading||window.PersonalityAdminAuth?.expired)return;loading=true;$('refresh-operations').disabled=true;
    try{render(await api());if(status.classList.contains('status-error')){status.textContent='';status.classList.remove('status-error');}}catch(error){status.textContent=error.message;status.classList.add('status-error');if(error.message.includes('权限'))return;}
    finally{loading=false;$('refresh-operations').disabled=Boolean(window.PersonalityAdminAuth?.expired);}
    if(!document.hidden&&!window.PersonalityAdminAuth?.expired)timer=setTimeout(load,15000);
  }
  $('refresh-operations').onclick=()=>{status.textContent='';status.classList.remove('status-error');load();};
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)load();});
  window.addEventListener('pagehide',()=>clearTimeout(timer));window.addEventListener('personality-admin-auth-expired',()=>clearTimeout(timer));load();
})();
