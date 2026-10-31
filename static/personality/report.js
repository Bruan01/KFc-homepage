(() => {
  'use strict';
  const $=s=>document.querySelector(s),main=$('#main'),state=$('#report-state');
  const id=location.pathname.split('/').filter(Boolean).pop();
  const base='/api/personality/assessments/'+id;
  let report,originals=null,pollTimer,heartlineReady=false;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const selectedText=(question,answer)=>question.options?.find(option=>option.id===answer.choice)?.text||'';
  async function api(url,body){const r=await fetch(url,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/csrftoken=([^;]+)/)?.[1]||''},body:JSON.stringify(body)}:{})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||'暂时无法读取档案，请稍后重试');return d;}
  document.querySelectorAll('.save-trigger').forEach(b=>b.disabled=true);
  async function getOriginals(){if(!originals)originals=await api(base+'/answers');return originals;}
  function applyHeartline(){
    const value=$('#heartline-text').value.trim(),shown=$('#include-quote').checked;
    $('#report-quote').textContent=value;
    $('.keepsake-quote').hidden=!shown||!value;
    $('#quote-note').textContent=value===(report?.heartline?.text||'')?'根据回答提炼':'由你编辑';
    $('#quote-title').firstChild.textContent=report?.heartline?.origin==='ai_from_choices'?'属于你的一句话':'你的心声';
    $('#heartline-editor').hidden=!shown;
    $('#heartline-count').textContent=$('#heartline-text').value.length+' / 60';
  }
  function prepareHeartline(){
    const value=$('#heartline-text').value.trim();
    if($('#include-quote').checked&&(!value||value.length>60))throw Error('请填写一句不超过 60 字的心声，或取消展示。');
    applyHeartline();
    return $('#include-quote').checked&&Boolean(value);
  }
  $('#heartline-text').addEventListener('input',applyHeartline);
  $('#include-quote').addEventListener('change',applyHeartline);
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
  function render(data){
    report=data;
    const role=report.character;
    $('#analysis-mode').textContent=report.analysis_mode==='ai'?'AI 深度解读':'量表解读';$('#analysis-process-link').href='/personality/analysis/'+id;
    document.documentElement.dataset.personalityTheme=report.theme;
    document.body.classList.toggle('has-character',Boolean(role?.image_url));
    document.body.classList.toggle('image-portrait',role?.image_layout!=='cutout');
    $('#report-title').textContent=role?role.name:'你的人格档案';
    $('#character-work').textContent=role?'《'+role.work+'》':'';
    $('#report-summary').textContent=role?role.resonance:report.summary;
    $('#report-type').textContent=report.type;
    $('#report-type-name').textContent=report.title;
    $('#report-keywords').replaceChildren(...report.keywords.map(word=>{const span=document.createElement('span');span.textContent=word;return span;}));
    if(!heartlineReady){const line=['ai_refined','ai_from_choices'].includes(report.heartline?.origin)?report.heartline.text:'';$('#heartline-text').value=line||'';$('#include-quote').checked=Boolean(line);heartlineReady=true;}
    applyHeartline();
    $('#radar-heading').textContent=role?'你与角色的六维对照':'你的六维人格画像';
    $('#character-legend').hidden=!role;$('#match-badge').hidden=!role;
    $('#legend-name').textContent=role?.name||'';$('#similarity').textContent=role?.similarity??'';
    const img=$('#character-image');
    if(role?.image_url){img.src=base+'/image';img.hidden=false;img.alt=role.name;img.onerror=()=>{img.hidden=true;document.body.classList.remove('has-character');};}
    $('#axes').innerHTML=report.axes.map(axis=>`<div class="axis"><div class="axis-head"><span class="axis-label"><b>${esc(axis.left)}</b>${esc(axis.left_name)}</span><span class="axis-number">${axis.value??'—'}</span><span class="axis-opposite">${esc(axis.right_name)}<b>${esc(axis.right)}</b></span></div><div class="axis-track" ${axis.value===null?'':`role="meter" aria-label="${esc(axis.left_name)}倾向" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${axis.value}"`}>${axis.value===null?'':`<div class="axis-fill" style="width:${axis.value}%"></div>`}</div></div>`).join('');
    $('#report-sections').innerHTML=report.sections.map((section,i)=>`<article><h3>${esc(section.title)}</h3><p>${esc(section.text)}</p><details data-evidence="${i}"><summary>查看回答依据</summary><div class="evidence" data-private-quote></div></details></article>`).join('');
    $('#report-sections').querySelectorAll('[data-evidence]').forEach(details=>details.addEventListener('toggle',async()=>{if(!details.open||details.dataset.loaded)return;const target=details.querySelector('.evidence');try{const source=await getOriginals();const map=Object.fromEntries(source.steps.flatMap(s=>s.questions).map(q=>[q.id,q]));target.innerHTML=report.sections[Number(details.dataset.evidence)].evidence.map(qid=>{const q=map[qid],a=source.answers[qid];return q&&a?`<p><strong>${esc(q.text)}</strong><br>${a.value!==null?esc(a.value)+' / 7':''}${selectedText(q,a)?'<br>所选：'+esc(selectedText(q,a)):''}${a.note?'<br>补充：'+esc(a.note):''}</p>`:'';}).join('');details.dataset.loaded='true';}catch(error){target.textContent=error.message;}}));
    const uncertain=report.axes.filter(axis=>axis.uncertain).map(axis=>axis.left+'/'+axis.right);
    $('#type-reason').textContent=(report.candidates.length?'当前匹配为 '+report.type+'。补充候选：'+report.candidates.slice(1).join('、')+'。':'部分维度的有效回答不足，当前保留空缺。')+(uncertain.length?' '+uncertain.join('、')+' 的方向仍较接近，可以结合真实情境继续理解。':' 四组偏好在本次回答中呈现了较明确的方向。');
    if(report.type_review?.length){$('#type-reason').innerHTML=report.type_review.map(item=>`<article><h3>${esc(item.type)}</h3><p>${esc(item.support)}</p><p>${esc(item.against)}</p></article>`).join('');}$('#resonance').hidden=!role;
    document.querySelectorAll('a[href="#resonance"]').forEach(a=>a.hidden=!role);
    if(role){$('#resonance-title').textContent=role.resonance;$('#resonance-text').textContent=role.mechanism;$('#difference-text').textContent=role.difference;}
    $('#growth-items').innerHTML=report.growth.map(item=>`<article><h3>${esc(item.title)}</h3><p>${esc(item.text)}</p></article>`).join('');
    drawRadar();main.hidden=false;state.hidden=true;
    document.querySelectorAll('.save-trigger').forEach(b=>b.disabled=false);
  }
  async function load(){
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
        $('#retry-ai-consent').hidden=!result.needs_ai_consent;
        $('#retry-report').disabled=Boolean(result.needs_ai_consent)&&!$('#retry-ai-agreement').checked;
        $('#report-status').textContent=result.error||'分析未完成，回答已保存。';$('#retry-report').hidden=false;return;
      }
      $('#retry-ai-consent').hidden=true;
      $('#retry-report').hidden=true;
      if(['active','ready'].includes(result.status)){
        state.querySelector('h1').textContent='测评还未提交';
        $('#report-status').innerHTML='<a href="/personality/test?id='+encodeURIComponent(id)+'">返回测评并完成提交</a>';return;
      }
      state.querySelector('h1').textContent='正在整理你的人格档案';
      $('#report-status').textContent=result.status==='queued'?'正在等待分析。可以关闭页面，稍后回来查看。':({person_analysis_inner:'正在整理你的情绪、价值与关系模式…',person_analysis_daily:'正在理解你的学习、行动与日常选择…',person_analysis_summary:'正在汇总人格关键词与成长建议…',character_review:'人格画像已整理，正在寻找与你共鸣的角色…'}[result.phase]||'正在结合你的回答整理人格档案…');
      if(result.is_delayed){state.querySelector('h1').textContent='回答已保存';$('#report-status').textContent=result.notice||'回答已保存，不用重做，可以稍后回来。';}
      if(!$('#report-background-note')){const note=document.createElement('p');note.id='report-background-note';note.textContent='可以离开这个页面，报告完成后会收到站内通知。';$('#report-status').after(note);}
      pollTimer=setTimeout(load,document.hidden?6000:2500);
    }catch(error){state.querySelector('h1').textContent='暂时无法读取档案';$('#report-status').textContent=error.message;$('#retry-report').hidden=false;}
  }
  $('#add-character').onclick=async()=>{const button=$('#add-character');button.disabled=true;try{await api(base+'/complete-character',{});await load();}catch(error){$('#character-upgrade-status').textContent=error.message;button.disabled=false;}};
  $('#retry-ai-agreement').onchange=()=>{$('#retry-report').disabled=!$('#retry-ai-agreement').checked;};
  $('#retry-report').onclick=async()=>{try{$('#retry-report').disabled=true;await api(base+'/submit',$('#retry-ai-consent').hidden?{}:{ai_consent:$('#retry-ai-agreement').checked});$('#retry-report').hidden=true;await load();}catch(error){$('#report-status').textContent=error.message;}finally{$('#retry-report').disabled=!$('#retry-ai-consent').hidden&&!$('#retry-ai-agreement').checked;}};
  const dialog=$('#save-dialog');
  document.querySelectorAll('.save-trigger').forEach(b=>b.onclick=()=>{dialog.showModal();$('#save-status').textContent='';});
  function appendAnswers(target,data){target.querySelector('#raw-data')?.remove();const section=document.createElement('section');section.id='raw-data';section.className='raw-answers';section.innerHTML='<h2>原始作答</h2>'+data.steps.flatMap(s=>s.questions).map(q=>{const a=data.answers[q.id];return a?`<div class="source-group"><h3>${esc(q.text)}</h3><p>${a.skipped?'已跳过':a.value!==null?esc(a.value)+' / 7':''}</p>${selectedText(q,a)?`<p>所选：${esc(selectedText(q,a))}</p>`:''}${a.note?`<p class="answer-note">${esc(a.note)}</p>`:''}</div>`:'';}).join('');target.append(section);}
  function dataURL(blob){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob);});}
  $('#download-image').onclick=async()=>{const button=$('#download-image');button.disabled=true;$('#save-status').textContent='正在生成首屏图片…';try{await window.XinyingExportPNG({includeQuote:prepareHeartline(),type:report.type});$('#save-status').textContent='图片已生成，可在浏览器下载列表查看。';}catch(error){$('#save-status').textContent=error.message||'图片未能保存，请重试';}finally{button.disabled=false;}};
  $('#download-report').onclick=async()=>{
    const button=$('#download-report'),status=$('#save-status');button.disabled=true;status.textContent='正在准备档案…';
    try{
      const includeAnswers=$('#include-answers').checked,includeQuote=prepareHeartline();
      const css=await Promise.all([...document.querySelectorAll('link[rel=stylesheet]')].map(async link=>{const r=await fetch(link.href);if(!r.ok)throw Error('样式读取失败，请重试');return r.text();}));
      let image='';const img=$('#character-image');if(img.src&&!img.hidden){const r=await fetch(img.src);if(!r.ok)throw Error('角色图片尚未准备好，请稍后重试');image=await dataURL(await r.blob());}
      const source=includeAnswers?await getOriginals():null;
      const copy=document.documentElement.cloneNode(true);
      copy.querySelectorAll('script,link[rel=stylesheet],#save-dialog,.save-trigger,.feedback,.skip,#report-state,#character-upgrade,[data-export-exclude]').forEach(e=>e.remove());
      copy.querySelector('body').removeAttribute('data-print-no-quote');copy.querySelector('body').removeAttribute('data-print-no-answers');
      if(!includeQuote)copy.querySelectorAll('[data-private-quote],.evidence').forEach(e=>e.remove());
      copy.querySelectorAll('details[data-evidence]').forEach(e=>e.remove());
      copy.querySelectorAll('details').forEach(e=>e.open=true);
      const style=document.createElement('style');style.textContent=css.join('\n');copy.querySelector('head').append(style);
      if(image)copy.querySelector('#character-image').src=image;
      if(source)appendAnswers(copy.querySelector('main'),source);
      const url=URL.createObjectURL(new Blob(['<!doctype html>\n'+copy.outerHTML],{type:'text/html;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='心映-'+report.type+'-人格档案.html';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);status.textContent='已发起下载，可在浏览器下载列表查看。';
    }catch(error){status.textContent=error.message||'档案未能保存，请重试';}finally{button.disabled=false;}
  };
  $('#print-report').onclick=async()=>{const button=$('#print-report');button.disabled=true;try{const includeQuote=prepareHeartline();if($('#include-answers').checked)appendAnswers(main,await getOriginals());else $('#raw-data')?.remove();document.body.toggleAttribute('data-print-no-quote',!includeQuote);document.body.toggleAttribute('data-print-no-answers',!$('#include-answers').checked);dialog.close();window.print();}catch(error){$('#save-status').textContent=error.message;}finally{button.disabled=false;}};
  window.addEventListener('afterprint',()=>{$('#raw-data')?.remove();document.body.removeAttribute('data-print-no-quote');document.body.removeAttribute('data-print-no-answers');});
  window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
  load();
})();
