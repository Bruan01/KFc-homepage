(() => {
  'use strict';
  const $=s=>document.querySelector(s),main=$('#main'),state=$('#report-state');
  const id=location.pathname.split('/').filter(Boolean).pop();
  const base='/api/personality/assessments/'+id;
  let report,originals=null,pollTimer,retryTimer;
  let claimingBadge=false;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const selectedText=(question,answer)=>question.options?.find(option=>option.id===answer.choice)?.text||'';
  async function api(url,body){
    const claiming=url==='/api/achievements/personality/claim';
    let r;
    try{r=await fetch(url,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/csrftoken=([^;]+)/)?.[1]||''},body:JSON.stringify(body)}:{})});}
    catch(error){throw Error(claiming?'暂时无法连接勋章领取服务，请稍后重试。你的报告已保存，无需重做。':'暂时无法连接档案服务，请稍后重试');}
    const d=await r.json().catch(()=>({}));
    if(!r.ok){
      if(claiming&&r.status===401)throw Error('请先登录，再回到这份报告领取勋章。');
      const fallback=claiming?(r.status===404?'勋章领取接口暂不可用，请联系管理员更新或重启服务。你的报告已保存，无需重做。':r.status===403?'领取请求未通过校验，请刷新页面后重试。':'勋章暂时领取失败，请稍后重试。你的报告已保存，无需重做。'):'暂时无法读取档案，请稍后重试';
      throw Error(d.error||fallback);
    }
    return d;
  }
  document.querySelectorAll('.save-trigger').forEach(b=>b.disabled=true);
  async function getOriginals(){if(!originals)originals=await api(base+'/answers');return originals;}
  function drawRadar(){
    const svg=$('#radar'),ns='http://www.w3.org/2000/svg';
    svg.querySelectorAll(':scope > :not(title):not(desc)').forEach(e=>e.remove());
    const style=getComputedStyle(document.documentElement),primary=style.getPropertyValue('--theme-primary').trim(),secondary=style.getPropertyValue('--theme-secondary').trim(),line=style.getPropertyValue('--theme-line').trim(),paper=style.getPropertyValue('--theme-sheet').trim();
    const dimensions=report.dimensions,role=report.character;
    function point(i,r){const a=-Math.PI/2+i*Math.PI/3;return [180+Math.cos(a)*r,155+Math.sin(a)*r];}
    function add(tag,attributes,text,parent=svg){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attributes))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;parent.append(e);return e;}
    [1,.75,.5,.25].forEach(level=>add('polygon',{points:dimensions.map((_,i)=>point(i,96*level).join(',')).join(' '),fill:level===1?paper:'none',stroke:line,'stroke-width':.8}));
    dimensions.forEach((_,i)=>{const [x,y]=point(i,96);add('line',{x1:180,y1:155,x2:x,y2:y,stroke:line,'stroke-width':.8});});
    if(role)add('polygon',{points:dimensions.map((d,i)=>point(i,96*role.dimensions[d.key]/100).join(',')).join(' '),fill:secondary,'fill-opacity':.12,stroke:secondary,'stroke-width':1.8,'stroke-dasharray':'4 4'});
    if(dimensions.every(d=>d.value!==null))add('polygon',{points:dimensions.map((d,i)=>point(i,96*d.value/100).join(',')).join(' '),fill:primary,'fill-opacity':.22,stroke:primary,'stroke-width':2.2});
    dimensions.forEach((d,i)=>{if(d.value!==null){const [x,y]=point(i,96*d.value/100);add('circle',{cx:x,cy:y,r:3.2,fill:primary,stroke:paper,'stroke-width':1});}if(role){const [x,y]=point(i,96*role.dimensions[d.key]/100);add('rect',{x:x-2.6,y:y-2.6,width:5.2,height:5.2,fill:secondary,stroke:paper,'stroke-width':.7});}const [x,y]=point(i,132);add('text',{x,y:y-5,'text-anchor':'middle',class:'radar-label'},d.name);const t=add('text',{x,y:y+14,'text-anchor':'middle'});add('tspan',{fill:primary,class:'radar-user-value'},d.value??'—',t);if(role){add('tspan',{class:'radar-slash'},' / ',t);add('tspan',{fill:secondary,class:'radar-character-value'},role.dimensions[d.key],t);}});
    $('#radar-desc').textContent=dimensions.map(d=>d.name+'：你 '+(d.value??'回答不足')+(role?'，角色 '+role.dimensions[d.key]:'')).join('；');
  }
  function renderCharacterCards(items,target){
    target.innerHTML=items.map(role=>`<article class="recommendation-card"><img src="/api/personality/cast/${role.id}/image" alt="${esc(role.name)}" loading="lazy"><div><h3>${esc(role.name)}</h3><p class="recommendation-work">${esc(role.work)}</p><p>${esc(role.summary)}</p>${role.source_quote_url?`<blockquote>${esc(role.source_quote)}</blockquote>`:''}</div></article>`).join('');
    target.querySelectorAll('img').forEach(img=>img.onerror=()=>{img.hidden=true;});
  }
  function render(data){
    report=data;
    const role=report.character;
    $('#analysis-mode').textContent=report.analysis_mode==='ai'?'AI 深度解读':'量表解读';
    document.documentElement.dataset.personalityTheme=report.theme;
    document.body.classList.toggle('has-character',Boolean(role?.image_url));
    document.body.classList.toggle('image-portrait',role?.image_layout!=='cutout');
    $('#report-title').textContent=role?role.name:'你的人格档案';
    const characterQuote=role?.source_quote_url?role.source_quote:'';
    $('#character-work').textContent=role?`《${role.work}》${characterQuote?' · “'+characterQuote+'”':''}`:'';
    $('#report-summary').textContent=role?role.resonance:report.summary;
    $('#report-type').textContent=report.type;
    $('#report-type-name').textContent=report.title;
    $('#report-type-traits').innerHTML=report.axes.filter(axis=>axis.value!==null).map(axis=>{const right=axis.value<50;return `<span>${esc(right?axis.right_name:axis.left_name)}<b>${esc(right?axis.right:axis.left)}</b></span>`;}).join('');
    $('#report-keywords').replaceChildren(...report.keywords.map(word=>{const span=document.createElement('span');span.textContent=word;return span;}));
    const line=report.heartline?.text||'';
    $('#report-quote').textContent=line;$('.keepsake-quote').hidden=!line;
    $('#quote-title').firstChild.textContent='送给用户的一句话';
    const heartlineOrigin=report.heartline?.origin;
    $('#quote-note').textContent=heartlineOrigin==='literal_quote'?'来自你的原话':['choice_literal','choice_refined','ai_from_choices'].includes(heartlineOrigin)?'来自你的选择':'参考你的回答提炼';
    $('#radar-heading').textContent=role?'你与角色的六维对照':'你的六维人格画像';
    $('#character-legend').hidden=!role;$('#match-badge').hidden=!role;
    $('#legend-name').textContent=role?.name||'';$('#similarity').textContent=role?.similarity??'';
    const img=$('#character-image');
    if(role?.image_url){img.src=base+'/image';img.hidden=false;img.alt=role.name;img.onerror=()=>{img.hidden=true;document.body.classList.remove('has-character');};}
    $('#axes').innerHTML=report.axes.map(axis=>{const right=axis.value!==null&&axis.value<50,width=axis.value===null?0:right?100-axis.value:axis.value;return `<div class="axis ${right?'axis-right':''}"><div class="axis-head"><span class="axis-label"><b>${esc(axis.left)}</b>${esc(axis.left_name)}</span><span class="axis-number">${axis.value??'—'}</span><span class="axis-opposite">${esc(axis.right_name)}<b>${esc(axis.right)}</b></span></div><div class="axis-track" ${axis.value===null?'':`role="meter" aria-label="${esc(right?axis.right_name:axis.left_name)}倾向" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${width}"`}>${axis.value===null?'':`<div class="axis-fill" style="width:${width}%"></div>`}</div></div>`;}).join('');
    $('#report-sections').innerHTML=report.sections.map((section,i)=>`<article><h3>${esc(section.title)}</h3><p>${esc(section.text)}</p><details data-evidence="${i}"><summary>查看回答依据</summary><div class="evidence" data-private-quote></div></details></article>`).join('');
    $('#report-sections').querySelectorAll('[data-evidence]').forEach(details=>details.addEventListener('toggle',async()=>{if(!details.open||details.dataset.loaded)return;const target=details.querySelector('.evidence');try{const source=await getOriginals(),scale=source.steps[0]?.response_scale||7,map=Object.fromEntries(source.steps.flatMap(s=>s.questions).map(q=>[q.id,q]));target.innerHTML=report.sections[Number(details.dataset.evidence)].evidence.map(qid=>{const q=map[qid],a=source.answers[qid];return q&&a?`<p><strong>${esc(q.text)}</strong><br>${a.value!==null?esc(a.value)+' / '+scale:''}${selectedText(q,a)?'<br>所选：'+esc(selectedText(q,a)):''}${a.note?'<br>补充：'+esc(a.note):''}</p>`:'';}).join('');details.dataset.loaded='true';}catch(error){target.textContent=error.message;}}));
    const uncertain=report.axes.filter(axis=>axis.uncertain).map(axis=>axis.left+'/'+axis.right);
    $('#type-reason').textContent=(report.candidates.length?'当前匹配为 '+report.type+'。补充候选：'+report.candidates.slice(1).join('、')+'。':'部分维度的有效回答不足，当前保留空缺。')+(uncertain.length?' '+uncertain.join('、')+' 的方向仍较接近，可以结合真实情境继续理解。':' 四组偏好在本次回答中呈现了较明确的方向。');
    if(report.type_review?.length)$('#type-reason').innerHTML=report.type_review.map(item=>`<article><h3>${esc(item.type)}</h3><p>${esc(item.support)}</p><p>${esc(item.against)}</p></article>`).join('');
    $('#resonance').hidden=!role;document.querySelectorAll('a[href="#resonance"]').forEach(a=>a.hidden=!role);
    if(role){$('#resonance-title').textContent=role.resonance;$('#resonance-text').textContent=role.mechanism;$('#difference-text').textContent=role.difference;}
    const others=report.other_characters||[],opposite=report.opposite_character;
    $('#similar-characters').hidden=!others.length;$('#opposite-character-section').hidden=!opposite;
    if(others.length)renderCharacterCards(others,$('#other-characters'));
    if(opposite)renderCharacterCards([opposite],$('#opposite-character'));
    $('#growth-items').innerHTML=report.growth.map(item=>`<article><h3>${esc(item.title)}</h3><p>${esc(item.text)}</p></article>`).join('');
    drawRadar();main.hidden=false;state.hidden=true;
    document.querySelectorAll('.save-trigger').forEach(b=>b.disabled=false);
    const rewardKind=window.KflowPersonalityBadge?.kindOf({code:'mbti-'+String(report.type||'').toLowerCase()});
    document.querySelectorAll('.claim-trigger').forEach(button=>button.disabled=!rewardKind||claimingBadge);
  }
  async function load(){
    clearTimeout(pollTimer);clearTimeout(retryTimer);
    try{
      const result=await api(base+'/report');
      if($('#report-background-note'))$('#report-background-note').hidden=!['queued','processing'].includes(result.status);
      if(result.status==='completed'){
        render(result.report);const pending=['queued','processing'].includes(result.character_match_status);
        $('#character-upgrade').hidden=Boolean(result.report.character);$('#add-character').hidden=!result.can_add_character;$('#add-character').disabled=pending;
        $('#character-upgrade-status').textContent=pending?'正在为这份档案寻找共鸣角色，可以稍后回来查看。':result.character_match_error||result.character_missing_reason||'这份档案还缺少角色共鸣，可以用原答案补全。';
        if(pending)pollTimer=setTimeout(load,2500);return;
      }
      if(result.status==='failed'){
        state.querySelector('h1').textContent='分析暂未完成';
        const button=$('#retry-report'),consentRequired=Boolean(result.needs_ai_consent),cooling=result.retry_block_reason==='cooldown';
        $('#retry-ai-consent').hidden=!consentRequired;
        button.dataset.allowed=String(Boolean(result.can_retry||consentRequired));
        button.hidden=!result.can_retry&&!consentRequired&&!cooling;
        button.disabled=!result.can_retry||consentRequired&&!$('#retry-ai-agreement').checked;
        button.textContent='重试分析';$('#report-status').textContent=result.error||'分析未完成，回答已保存。';
        if(cooling){const deadline=Date.now()+result.retry_after*1000;const countdown=()=>{const seconds=Math.max(0,Math.ceil((deadline-Date.now())/1000));button.textContent=seconds?seconds+' 秒后重试':'重试分析';if(seconds)retryTimer=setTimeout(countdown,1000);else load();};countdown();}
        return;
      }
      $('#retry-ai-consent').hidden=true;$('#retry-report').hidden=true;
      if(['active','ready'].includes(result.status)){
        state.querySelector('h1').textContent='测评还未提交';
        $('#report-status').innerHTML='<a href="/personality/test?id='+encodeURIComponent(id)+'">返回测评并完成提交</a>';return;
      }
      state.querySelector('h1').textContent='正在整理你的人格档案';
      $('#report-status').textContent=result.status==='queued'?'正在等待分析。可以关闭页面，稍后回来查看。':({person_analysis_inner:'正在整理你的情绪、价值与关系模式…',person_analysis_daily:'正在理解你的学习、行动与日常选择…',person_analysis_summary:'正在汇总人格关键词与成长建议…',character_review:'人格画像已整理，正在寻找与你共鸣的角色…'}[result.phase]||'正在结合你的回答整理人格档案…');
      if(result.is_delayed){state.querySelector('h1').textContent='回答已保存';$('#report-status').textContent=result.notice||'回答已保存，不用重做，可以稍后回来。';}
      if(!$('#report-background-note')){const note=document.createElement('p');note.id='report-background-note';note.textContent='可以离开这个页面，报告完成后会收到站内通知。';$('#report-status').after(note);}
      pollTimer=setTimeout(load,document.hidden?6000:2500);
    }catch(error){state.querySelector('h1').textContent='暂时无法读取档案';$('#report-status').textContent=error.message;$('#retry-report').hidden=true;}
  }
  $('#add-character').onclick=async()=>{const button=$('#add-character');button.disabled=true;try{await api(base+'/complete-character',{});await load();}catch(error){$('#character-upgrade-status').textContent=error.message;button.disabled=false;}};
  document.querySelectorAll('.claim-trigger').forEach(button=>button.onclick=async()=>{
    if(button.disabled||claimingBadge)return;
    claimingBadge=true;document.querySelectorAll('.claim-trigger').forEach(b=>b.disabled=true);
    $('#claim-badge-art').replaceChildren();
    $('#go-badge-gallery').hidden=true;$('#reward-status').textContent='正在领取你当前的人格勋章…';
    $('#badge-claim-dialog').showModal();
    $('#badge-claim-title').focus({preventScroll:true});
    try{
      const result=await api('/api/achievements/personality/claim',{assessment_id:id});
      $('#reward-status').textContent='已领取「'+result.badge.name+'」。';
      $('#claim-badge-art').replaceChildren(window.KflowPersonalityBadge.medal(result.badge));
      $('#go-badge-gallery').href='/achievements?badge='+encodeURIComponent(result.badge.code)+'&guide=personality#personality-badges';
      $('#go-badge-gallery').hidden=false;
    }catch(error){$('#reward-status').textContent=error.message;}
    finally{claimingBadge=false;document.querySelectorAll('.claim-trigger').forEach(b=>b.disabled=false);}
  });
  document.querySelectorAll('.claim-dialog-close,.claim-dialog-later').forEach(button=>button.onclick=()=>$('#badge-claim-dialog').close());
  $('#retry-ai-agreement').onchange=()=>{const button=$('#retry-report');button.disabled=button.dataset.allowed!=='true'||!$('#retry-ai-agreement').checked;};
  $('#retry-report').onclick=async()=>{const button=$('#retry-report');try{button.disabled=true;await api(base+'/submit',$('#retry-ai-consent').hidden?{}:{ai_consent:$('#retry-ai-agreement').checked});button.hidden=true;await load();}catch(error){await load();}};
  const dialog=$('#save-dialog');
  document.querySelectorAll('.save-trigger').forEach(b=>b.onclick=()=>{dialog.showModal();$('#save-status').textContent='';});
  $('#download-image').onclick=async()=>{const button=$('#download-image'),mode=document.querySelector('input[name=image-format]:checked').value;button.disabled=true;$('#save-status').textContent=mode==='long'?'正在生成完整长图…':'正在生成首屏短图…';try{$('#save-status').textContent=await window.XinyingExportPNG({includeQuote:true,type:report.type,mode});}catch(error){$('#save-status').textContent=error.message||'图片未能保存，请重试';}finally{button.disabled=false;}};
  window.addEventListener('pagehide',()=>{clearTimeout(pollTimer);clearTimeout(retryTimer);});
  load();
})();
