(() => {
  'use strict';
  const openers=[...document.querySelectorAll('[data-request-limits-open]')];
  if(!openers.length)return;
  const dialog=document.createElement('dialog');
  dialog.id='request-limits-dialog';
  dialog.setAttribute('aria-labelledby','request-limits-title');
  dialog.setAttribute('aria-describedby','request-limits-description');
  dialog.innerHTML=`<form id="request-limits-form">
    <h2 id="request-limits-title">AI 请求额度</h2>
    <p id="request-limits-description" class="admin-note">设置用户同一份测评累计可请求 AI 的次数，首次分析、自动修正和手动重试共用此额度，失败也计次。</p>
    <label for="report-request-limit">同一份测评最多请求 AI 次数</label>
    <input id="report-request-limit" name="report_requests_per_assessment" type="number" min="1" max="1000" step="1" required aria-describedby="request-limit-hint">
    <p id="request-limit-hint" class="admin-note">可设置 1–1000 次。保存后适用于已有未完成测评，无需清零历史请求。</p>
    <p id="request-daily-limit" class="admin-note"></p>
    <div class="request-admin-policy"><strong>管理员后台重试不限次数</strong><p>主管理员在“运行与反馈”重新发起 AI 分析时，不受单份测评、每日请求额度和用户重试冷却限制。仍需用户授权和 AI 服务可用，每次调用保留记录，可能产生服务商费用。</p></div>
    <p id="request-limits-status" role="status" aria-live="polite"></p>
    <div class="request-limits-actions"><button type="button" class="secondary" id="close-request-limits">关闭</button><button type="submit" class="primary">保存额度</button></div>
  </form>`;
  document.body.append(dialog);
  const form=dialog.querySelector('form'),input=form.elements.report_requests_per_assessment,
    status=dialog.querySelector('#request-limits-status'),save=form.querySelector('[type=submit]'),
    close=dialog.querySelector('#close-request-limits');
  let busy=false,loaded=false,dailyReports=0;
  function message(text,error=false){status.textContent=text;status.classList.toggle('status-error',error);}
  function setBusy(value){busy=value;dialog.setAttribute('aria-busy',String(value));input.disabled=value||!loaded;save.disabled=value||!loaded||Boolean(window.PersonalityAdminAuth?.expired);close.disabled=value;save.textContent=value?'正在处理…':'保存额度';}
  function dailyHint(){dialog.querySelector('#request-daily-limit').textContent=`用户每日 AI 请求上限 = 每日报告上限 ${dailyReports} 份 × 单份请求上限 ${input.value} 次。与服务商余额分别计算。`;}
  async function api(body){
    if(window.PersonalityAdminAuth?.expired)throw Error('管理员登录已失效，请重新登录。');
    const response=await fetch('/api/admin/personality/settings',{credentials:'same-origin',method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1]||''},...(body?{body:JSON.stringify(body)}:{})});
    if(response.status===401){window.PersonalityAdminAuth?.requireLogin();throw Error('管理员登录已失效，请重新登录。');}
    const data=await response.json();if(!response.ok)throw Error(data.error||'额度设置暂时无法保存，请稍后重试。');return data.settings;
  }
  for(const opener of openers)opener.onclick=async()=>{
    if(dialog.open)return;loaded=false;input.value='';dialog.querySelector('#request-daily-limit').textContent='';
    message('正在读取已保存额度…');setBusy(true);dialog.showModal();
    try{const settings=await api();input.value=settings.report_requests_per_assessment;dailyReports=settings.daily_reports_per_user;loaded=true;dailyHint();message('');}
    catch(error){message(error.message,true);}
    finally{setBusy(false);if(loaded)input.focus();else close.focus();}
  };
  input.addEventListener('input',()=>{dailyHint();message('');});
  close.onclick=()=>dialog.close();
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  form.onsubmit=async event=>{
    event.preventDefault();if(busy||!loaded||!form.reportValidity())return;setBusy(true);message('正在保存额度…');
    try{const settings=await api({report_requests_per_assessment:Number(input.value)});input.value=settings.report_requests_per_assessment;dailyReports=settings.daily_reports_per_user;dailyHint();message('额度已保存。已有失败测评按新额度校验，管理员可直接重新发起 AI 分析。');}
    catch(error){message(error.message,true);}
    finally{setBusy(false);if(dialog.open)(save.disabled?close:save).focus();}
  };
})();
