(() => {
  'use strict';
  const $=s=>document.querySelector(s),form=$('#settings-form'),status=$('#admin-status');
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let saved=null,busy=false;
  function show(message,error=false){status.textContent=message;status.classList.toggle('status-error',error);}
  async function api(path,body){if(window.PersonalityAdminAuth?.expired)throw Error('管理员登录已失效，请重新登录后再操作。');const response=await fetch('/api/admin/personality/'+path,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1]||''},...(body?{body:JSON.stringify(body)}:{})});const result=await response.json();if(response.status===401){window.PersonalityAdminAuth?.requireLogin();throw Error('管理员登录已失效，请重新登录后再操作。');}if(!response.ok)throw Error(result.error||'请求未完成');return result;}
  function body(){return Object.fromEntries([...form.elements].filter(e=>e.name).map(e=>[e.name,e.type==='checkbox'?e.checked:e.type==='number'?Number(e.value):e.value]));}
  function date(value){const d=new Date(value);return value&&!Number.isNaN(d.getTime())?d.toLocaleString('zh-CN'):'—';}
  function renderSaved(){
    const configured=Boolean(saved?.saved&&saved.base_url&&saved.model),check=saved?.connection_check||{},states={passed:'连接通过',failed:'连接失败',unchecked:'尚未检查'};
    $('#saved-config-empty').hidden=configured;$('#saved-config-empty').textContent='还没有完整的服务配置。填写上方信息后保存。';$('#saved-config-list').hidden=!configured;
    $('#test-provider').disabled=busy||!configured||Boolean(window.PersonalityAdminAuth?.expired);
    if(configured){
      const field=(label,value)=>`<div class="saved-config-field"><dt>${label}</dt><dd>${esc(value)}</dd></div>`;
      $('#saved-config-list').innerHTML=`<div class="saved-config-head"><strong>${esc(saved.model)}</strong><div class="saved-config-badges"><span class="quality-badge">已保存</span><span class="quality-badge ${check.status==='failed'?'problem':''}" data-connection-state="${esc(check.status||'unchecked')}">${states[check.status]||'尚未检查'}</span></div></div><dl class="saved-config-fields">${field('API 地址',saved.base_url)}${field('API Key',saved.has_api_key?'已设置':'未设置')}${field('服务状态',saved.ai_enabled?'已启用':'已停用')}${field('每日每人报告上限',saved.daily_reports_per_user+' 次')}${field('保存时间',date(saved.updated_at))}${field('最近连接检查',date(check.checked_at))}${field('自动补证据',!saved.evidence_enabled?'已关闭':saved.evidence_available?'已启用 · 按需搜索':'搜索密钥待配置')}</dl>${check.status==='failed'?`<p class="status-error saved-config-error">${esc(check.error||'连接未通过，请检查配置后重试。')}</p>`:''}`;
    }
    $('#worker-state').textContent=saved?.worker_alive?'后台任务服务运行中':'后台任务服务尚未连接';
  }
  function fill(settings){saved=settings;for(const [key,value] of Object.entries(settings)){const input=form.elements.namedItem(key);if(!input)continue;if(input.type==='checkbox')input.checked=value;else input.value=value;}form.elements.api_key.value='';form.elements.clear_api_key.checked=false;form.elements.evidence_api_key.value='';form.elements.clear_evidence_api_key.checked=false;form.elements.evidence_api_key.placeholder=settings.has_evidence_api_key?'已设置，留空保留':'DeepSeek 官方文本接口可留空复用主密钥';form.elements.api_key.placeholder=settings.has_api_key?'已设置，留空保留':'填写服务密钥';renderSaved();}
  function setBusy(value){busy=value;for(const button of document.querySelectorAll('button'))button.disabled=value;form.querySelector('[type=submit]').textContent=value?'正在处理…':'保存并检查连接';$('#settings-form').setAttribute('aria-busy',String(value));if(!value)renderSaved();if(window.PersonalityAdminAuth?.expired)document.querySelectorAll('button').forEach(button=>button.disabled=true);}
  async function checkSaved(){await api('test',{});}
  form.onsubmit=async event=>{
    event.preventDefault();if(busy)return;setBusy(true);let stored=false;
    try{const payload=body();fill((await api('settings',payload)).settings);stored=true;show('配置已保存，正在检查连接…');await checkSaved();show('配置已保存，连接检查通过。');}
    catch(error){show((stored?'配置已保存，连接检查未通过：':'保存失败：')+error.message,true);}
    finally{if(stored)try{saved=(await api('settings')).settings;}catch(error){show('配置已保存，暂时无法刷新连接状态，请重新加载页面。',true);}setBusy(false);}
  };
  $('#test-provider').onclick=async()=>{if(busy)return;setBusy(true);show('正在检查已保存的连接…');try{await checkSaved();show('已保存的连接检查通过。');}catch(error){show(error.message,true);}finally{try{saved=(await api('settings')).settings;}catch(error){show('暂时无法刷新连接状态，请重新加载页面。',true);}setBusy(false);}};
  $('#load-models').onclick=async()=>{if(busy)return;setBusy(true);show('正在读取模型列表…');try{const result=await api('models',body());$('#model-options').replaceChildren(...result.models.map(name=>{const option=document.createElement('option');option.value=name;return option;}));show(`已读取 ${result.models.length} 个模型，可选择或手动填写。`);}catch(error){show(error.message,true);}finally{setBusy(false);}};
  api('settings').then(result=>fill(result.settings)).catch(error=>{show(error.message,true);$('#saved-config-empty').textContent='配置读取失败，请重新加载页面。';});
})();
