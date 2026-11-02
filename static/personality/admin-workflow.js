(() => {
  'use strict';
  const $=s=>document.querySelector(s), status=$('#admin-status');
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stages=['candidate','draft','approved','excluded'];
  const labels={sensitivity:'情绪敏感',recovery:'情绪恢复',empathy:'共情理解',boundary:'关系边界',divergence:'发散思考',execution:'行动持续'};
  let stage=new URLSearchParams(location.search).get('stage')||'candidate';if(!stages.includes(stage))stage='candidate';
  let characters=[],selected=null,pageNumber=1,busy=false,lastJobs='',undoIDs=[],regenerateIDs=[],regenerateVersions={},missingMbti=0,mbtiPending=false,missingMottos=0,mottoPending=false;
  const choices=new Map();let choiceKey='',loadSequence=0;
  function saveChoices(){try{if(choiceKey)sessionStorage.setItem(choiceKey,JSON.stringify([...choices]));}catch(error){}}
  function restoreChoices(operator){const key='xinying-review:'+operator;if(key===choiceKey)return;choiceKey=key;choices.clear();try{const saved=JSON.parse(sessionStorage.getItem(key)||'[]');if(Array.isArray(saved))for(const pair of saved.slice(0,10000)){if(Array.isArray(pair)&&/^(candidate|draft|approved|excluded):[0-9]+$/.test(pair[0])&&typeof pair[1]==='boolean')choices.set(pair[0],pair[1]);}}catch(error){}}
  function updateStageURL(){const url=new URL(location.href);url.searchParams.set('stage',stage);history.replaceState(null,'',url);}

  function show(message,error=false,local=false){const target=local?$('#batch-status'):status;target.textContent=message;target.classList.toggle('status-error',error);}
  async function api(url,body){if(window.PersonalityAdminAuth?.expired)throw Error('管理员登录已失效，请重新登录后再操作。');const r=await fetch(url,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1]||''},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json().catch(()=>({}));if(r.status===401){window.PersonalityAdminAuth?.requireLogin();throw Error('管理员登录已失效，请重新登录后再操作。');}if(!r.ok)throw Error(d.error||'请求未完成，请重试');return d;}
  const versions=ids=>Object.fromEntries(characters.filter(c=>ids.includes(c.id)).map(c=>[String(c.id),c.revision]));
  const inProgress=c=>['queued','reviewing'].includes(c.profile_check?.status);
  function picked(){return [...document.querySelectorAll('[data-select-character]:checked')].map(input=>characters.find(c=>c.id===Number(input.dataset.selectCharacter))).filter(Boolean);}
  function selectedByDefault(c){const key=stage+':'+c.id;if(choices.has(key))return choices.get(key);return stage==='candidate'||(stage==='draft'&&c.publication.ready&&!c.publication.held);}
  function forget(ids){for(const key of [...choices.keys()])if(ids.includes(Number(key.split(':')[1])))choices.delete(key);saveChoices();}
  window.addEventListener('personality-admin-auth-expired',()=>{document.querySelectorAll('[data-select-character]').forEach(input=>choices.set(stage+':'+input.dataset.selectCharacter,input.checked));saveChoices();updateToolbar();});
  function quality(c){
    if(c.status==='approved')return ['已发布',''];if(c.status==='excluded')return ['已排除',''];
    if(c.profile_check?.status==='queued')return ['等待生成 / 复核','busy'];
    if(c.profile_check?.status==='reviewing')return ['AI 依据复核中','busy'];
    if(c.profile_check?.status==='error')return [c.profile_check.category==='reference_error'?'证据引用需修正':c.profile_check.category==='output_limit'||c.profile_check.issues?.some(text=>/输出.*(上限|截断)/.test(text))?'输出被截断':'接口 / 任务异常','problem'];
    if(c.publication.held)return ['暂缓发布',''];
    if(c.status==='candidate')return ['待初选',''];
    if(c.profile_check?.category==='format_error')return ['格式异常','problem'];
    if(c.profile_check?.category==='missing_evidence')return ['资料不足','problem'];
    if(c.profile_check?.category==='evidence_conflict')return ['依据需核对','problem'];
    return c.publication.ready?['可发布','']:['需处理','problem'];
  }
  function updateToolbar(){
    if(window.PersonalityAdminAuth?.expired){document.querySelectorAll('button').forEach(button=>button.disabled=true);return;}
    const rows=picked(),publishable=rows.filter(c=>c.publication.ready).length;
    const selectable=[...document.querySelectorAll('[data-select-character]:not(:disabled)')];
    $('#select-all-characters').checked=selectable.length>0&&rows.length===selectable.length;
    $('#select-all-characters').indeterminate=rows.length>0&&rows.length<selectable.length;
    $('#select-all-characters').disabled=!selectable.length||busy;
    $('#selection-count').textContent=`已选 ${rows.length} 项（本页）${stage==='draft'?' · 可发布 '+publishable+' 项':''}`;
    for(const [id,shown] of Object.entries({'batch-drafts':stage==='candidate','batch-approve':stage==='draft','batch-regenerate':stage==='draft','batch-recheck':stage==='draft','batch-restore':stage==='excluded','batch-exclude':stage==='approved'})){$('#'+id).hidden=!shown;$('#'+id).disabled=busy||!rows.length;}
    $('#batch-mbti').hidden=stage!=='approved';$('#batch-mbti').disabled=busy||!missingMbti||mbtiPending;
    $('#batch-mbti').setAttribute('aria-busy',String(mbtiPending));
    $('#batch-mbti').textContent=mbtiPending?'MBTI 补全中，请勿重复点击':missingMbti?`一键补全缺失 MBTI（${missingMbti}）`:'MBTI 已全部定位';
    $('#batch-mottos').hidden=stage!=='approved';$('#batch-mottos').disabled=busy||!missingMottos||mottoPending;
    $('#batch-mottos').setAttribute('aria-busy',String(mottoPending));
    $('#batch-mottos').textContent=mottoPending?'语录补全中，请勿重复点击':missingMottos?`一键补全缺失语录（${missingMottos}）`:'语录已全部收录';
    $('#batch-approve').disabled=busy||!publishable;
    $('#batch-approve').textContent=`批量通过（${publishable}）`;
    $('#batch-drafts').textContent=`生成人格档案并复核（${rows.length}）`;
    $('#keep-classics-option').hidden=stage!=='candidate'||!rows.some(c=>c.classic_candidate&&!c.classic);
    $('#generation-cost-note').hidden=!['candidate','draft'].includes(stage);
  }
  function characterInsights(c){
    const dimensions=c.profile?.dimensions||{},inferred=Object.values(dimensions).filter(row=>row?.evidence_type==='inferred'&&Number.isInteger(row.level)).length;
    const evidence=Object.keys(dimensions).length?`<span class="inference-badge ${inferred?'has-inference':''}" ${inferred?'title="这些维度按 0.5 权重参与匹配，可查看依据并人工复核"':''}>${inferred?`含 AI 推断 · ${inferred} 维`:'无 AI 推断'}</span>`:'';
    return `<div class="character-insights"><span class="character-mbti">${esc(c.mbti_type||'MBTI 未确定')}</span>${evidence}</div>`;
  }
  function summaryControl(c){
    if(stage==='candidate')return `<p class="review-excerpt">${esc(c.source_text)}</p>`;
    const rawOriginal=c.profile.signature_quote?.text,rawMotto=c.profile.motto,original=typeof rawOriginal==='string'?rawOriginal.trim():'',motto=typeof rawMotto==='string'?rawMotto.trim():'',value=original||motto;
    const origin=original?'角色原话':motto?'AI 提炼 / 编辑':'';
    return `<div class="inline-summary"><p class="review-excerpt review-quote" data-summary-view="${c.id}">${esc(value||'暂未收录角色语录')}</p>${origin?`<small class="quote-origin">${origin}</small>`:''}<button type="button" class="text-action inline-edit-link" data-inline-open="summary:${c.id}">编辑语录</button><div class="inline-editor" data-inline-editor="summary:${c.id}" hidden><textarea rows="2" maxlength="${original?300:80}" data-inline-input aria-label="编辑 ${esc(c.name)} 的角色语录">${esc(value)}</textarea><div class="inline-actions"><button type="button" class="primary" data-inline-save="summary:${c.id}">保存语录</button><button type="button" class="secondary" data-inline-cancel="summary:${c.id}">取消</button></div><p class="inline-status" data-inline-status="summary:${c.id}" role="status"></p></div></div>`;
  }
  function imageControl(c){
    return `<div class="review-image">${c.image_url?`<a href="${esc(c.image_url)}" target="_blank" rel="noopener" title="查看原图"><img src="${esc(c.image_url)}" alt="查看 ${esc(c.name)} 原图" loading="lazy" referrerpolicy="no-referrer"></a>`:''}<button type="button" class="text-action image-edit-link" data-inline-open="image:${c.id}">${c.image_url?'更换':'添加'}图片</button></div>`;
  }
  function imageEditor(c){
    return `<div class="inline-editor image-inline-editor" data-inline-editor="image:${c.id}" hidden><input type="url" maxlength="1000" data-inline-input value="${esc(c.image_url||'')}" aria-label="${esc(c.name)} 的图片地址" placeholder="https://lain.bgm.tv/…"><div class="inline-actions"><button type="button" class="primary" data-inline-save="image:${c.id}">保存图片</button><button type="button" class="secondary" data-inline-cancel="image:${c.id}">取消</button></div><p class="inline-status" data-inline-status="image:${c.id}" role="status"></p></div>`;
  }
  function renderCharacters(){
    if(!characters.length){$('#character-list').innerHTML='<p class="quiet">这个列表暂时没有角色。</p>';updateToolbar();return;}
    const actions=c=>{
      let html=`<button type="button" class="text-action" data-character="${c.id}">查看${stage==='candidate'?'资料':'依据'}</button>`;
      if(stage==='candidate')html+=`<button type="button" class="text-action danger" data-row-action="exclude" data-id="${c.id}" aria-label="排除 ${esc(c.name)}">× 排除</button>`;
      if(stage==='draft'&&!inProgress(c))html+=`<button type="button" class="text-action" data-row-action="regenerate" data-id="${c.id}">重新生成</button><button type="button" class="text-action" data-row-action="${c.publication.held?'release':'hold'}" data-id="${c.id}">${c.publication.held?'恢复待发布':'× 暂不发布'}</button><button type="button" class="text-action danger" data-row-action="exclude" data-id="${c.id}">不收录</button>`;
      if(stage==='approved')html+=`<button type="button" class="text-action danger" data-row-action="exclude" data-id="${c.id}">下架</button>`;
      if(stage==='excluded')html+=`<button type="button" class="text-action" data-row-action="restore" data-id="${c.id}">恢复</button>`;
      return html;
    };
    $('#character-list').innerHTML='<table class="review-table" aria-label="'+({candidate:'角色初选',draft:'档案发布',approved:'可匹配角色',excluded:'已排除角色'}[stage])+'"><thead><tr><th class="check-col" scope="col">选择</th><th class="person-col" scope="col">角色 / 作品</th><th class="summary-col" scope="col">'+(stage==='candidate'?'资料简介':'角色语录')+'</th><th class="quality-col" scope="col">检查结果</th><th scope="col">操作</th></tr></thead><tbody>'+characters.map(c=>{
      const [badge,kind]=quality(c),problems=c.profile_check?.issues?.length?c.profile_check.issues:c.publication.problems;
      const classic=(c.classic||c.classic_candidate)&&stage==='draft'?`<label class="classic-toggle"><input type="checkbox" data-classic="${c.id}" ${c.classic?'checked':''} ${inProgress(c)?'disabled':''}>经典保留</label>`:'';
      return `<tr data-character-row="${c.id}"><td><label class="row-check"><input type="checkbox" data-select-character="${c.id}" aria-label="选择 ${esc(c.name)}" ${!inProgress(c)&&selectedByDefault(c)?'checked':''} ${inProgress(c)?'disabled':''}></label></td><td><div class="review-person">${imageControl(c)}<div><strong>${esc(c.name)}</strong><small>${esc(c.work_name)}</small><small>${esc(c.work_year||'年代未录入')}${c.classic?' · 经典保留':''}</small>${characterInsights(c)}${imageEditor(c)}${classic}</div></div></td><td><span class="mobile-cell-label">${stage==='candidate'?'资料简介':'角色语录'}</span>${summaryControl(c)}</td><td><span class="quality-badge ${kind}">${badge}</span>${stage==='draft'?`<p class="quality-note">${esc(inProgress(c)?'任务在后台继续，可稍后回来查看。':c.publication.ready?c.profile_check.summary||'依据检查已完成':problems.slice(0,2).join('；'))}</p>${c.profile_check?.evidence?.note?`<p class="quality-note">${esc(c.profile_check.evidence.note)}</p>`:''}`:''}</td><td><div class="row-actions">${actions(c)}</div></td></tr>`;
    }).join('')+'</tbody></table>';
    updateToolbar();
  }
  async function loadCharacters(){
    const sequence=++loadSequence;try{const d=await api('/api/admin/personality/characters?'+new URLSearchParams({q:$('#character-search').value,status:stage,page:String(pageNumber),mbti:$('#character-mbti-filter').value,inference:$('#character-inference-filter').value}));if(sequence!==loadSequence)return;restoreChoices(d.operator||'admin');characters=d.items;pageNumber=d.page;missingMbti=d.missing_mbti||0;missingMottos=d.missing_mottos||0;
      $('#filter-result-count').textContent=`筛选结果：${d.total} 个角色`;
      for(const option of $('#character-mbti-filter').options){const value=option.value,count=value===''?d.filter_base_total:(d.mbti_counts?.[value]||0);option.value=value;option.textContent=(value===''?'全部 MBTI':value==='unknown'?'MBTI 未确定':value)+`（${count}）`;}
      $('#page-info').textContent=`第 ${d.page} / ${d.pages} 页 · 共 ${d.total} 个角色`;$('#previous-page').disabled=d.page<=1;$('#next-page').disabled=d.page>=d.pages;$('#ready-count').textContent=`可参与匹配：${d.ready}`;
      document.querySelectorAll('[data-count]').forEach(e=>e.textContent=d.counts[e.dataset.count]||0);
      document.querySelectorAll('[data-stage]').forEach(e=>e.setAttribute('aria-selected',String(e.dataset.stage===stage)));
      $('#stage-help').textContent={candidate:'本页默认全选。点 × 排除不想收录的角色，再为所选角色批量生成档案。',draft:'生成后会自动进行 AI 依据复核。合格档案默认勾选；异常和暂缓项保留在列表中。',approved:'这些角色已进入可匹配库。已完成的用户报告会保留原来的角色。',excluded:'排除记录会保留，下次采集不再获取这些角色的详情。恢复时可沿用已有资料。'}[stage];
      renderCharacters();
    }catch(error){show(error.message,true,true);}
  }
  function openInline(token){
    const [kind,id]=token.split(':'),editor=document.querySelector(`[data-inline-editor="${kind}:${id}"]`);if(!editor)return;
    editor.hidden=false;editor.querySelector('[data-inline-input]').focus();
    if(kind==='summary')document.querySelector(`[data-summary-view="${id}"]`).hidden=true;
  }
  function cancelInline(token){
    const [kind,id]=token.split(':'),editor=document.querySelector(`[data-inline-editor="${kind}:${id}"]`),c=characters.find(item=>item.id===Number(id));if(!editor||!c)return;
    editor.hidden=true;editor.querySelector('[data-inline-input]').value=kind==='summary'?c.profile.signature_quote?.text||c.profile.motto||'':c.image_url||'';editor.querySelector('[data-inline-status]').textContent='';
    if(kind==='summary')document.querySelector(`[data-summary-view="${id}"]`).hidden=false;
  }
  async function saveInline(token){
    const [kind,rawId]=token.split(':'),id=Number(rawId),c=characters.find(item=>item.id===id),editor=document.querySelector(`[data-inline-editor="${kind}:${id}"]`);if(!c||!editor)return;
    const input=editor.querySelector('[data-inline-input]'),button=editor.querySelector('[data-inline-save]'),state=editor.querySelector('[data-inline-status]'),value=input.value.trim();
    button.disabled=true;state.classList.remove('status-error');state.textContent='正在保存…';
    try{const content=kind==='summary'?(c.profile.signature_quote?.text?{signature_quote:value}:{motto:value}):{image_url:value};const d=await api('/api/admin/personality/characters/'+id,{action:'inline_edit',revision:c.revision,...content});characters[characters.findIndex(item=>item.id===id)]=d.character;renderCharacters();show(kind==='summary'?'角色语录已保存':'角色图片已更新',false,true);}
    catch(error){state.textContent=error.message;state.classList.add('status-error');}
    finally{if(button.isConnected)button.disabled=false;}
  }
  function showProblems(items){const target=$('#batch-problems');target.hidden=!items?.length;target.innerHTML=items?.length?'<strong>以下项目未处理</strong><ul>'+items.map(item=>`<li>${esc(characters.find(c=>c.id===item.id)?.name||'角色 '+item.id)}：${esc(item.reason)}</li>`).join('')+'</ul>':'';}
  async function act(action,ids,extra={}){
    if(!ids.length||busy)return false;busy=true;updateToolbar();show('正在处理所选角色…',false,true);
    try{const d=await api('/api/admin/personality/characters/batch-action',{action,ids,versions:versions(ids),...extra});showProblems(d.skipped);forget(ids);
      if(action==='exclude'){undoIDs=ids.filter(id=>!d.skipped.some(item=>item.id===id));$('#undo-exclusion').hidden=!undoIDs.length;}
      if(['generate','regenerate','recheck'].includes(action)){show(`已创建 ${d.queued} 个${action==='recheck'?'复核':'生成与复核'}任务。${d.skipped.length?'另有 '+d.skipped.length+' 项未处理。':''}`,false,true);stage='draft';pageNumber=1;updateStageURL();}
      else show(`已${{approve:'发布',exclude:'排除',restore:'恢复',hold:'暂缓',release:'恢复待发布'}[action]} ${d.changed} 个角色。${d.skipped.length?'另有 '+d.skipped.length+' 项未处理。':''}`,false,true);
      await loadCharacters();await jobs();return true;
    }catch(error){show(error.message,true,true);return false;}finally{busy=false;updateToolbar();}
  }
  async function completeMbti(){
    if(busy||mbtiPending)return;busy=true;mbtiPending=true;updateToolbar();show('正在创建 MBTI 补全任务，请勿重复点击…',false,true);
    try{const d=await api('/api/admin/personality/characters/batch-action',{action:'complete_mbti'});showProblems(d.skipped);mbtiPending=d.queued>0;show(d.queued?`已创建 ${d.queued} 个 MBTI 补全任务。按钮已锁定，后台会继续处理，完成后自动恢复。`:'当前没有需要补全的已发布角色。',false,true);updateToolbar();await jobs();}
    catch(error){mbtiPending=false;show(error.message,true,true);}finally{busy=false;updateToolbar();}
  }
  $('#batch-mbti').onclick=completeMbti;
  async function completeMottos(){
    if(busy||mottoPending)return;busy=true;mottoPending=true;updateToolbar();show('正在创建语录补全任务，请勿重复点击…',false,true);
    try{const d=await api('/api/admin/personality/characters/batch-action',{action:'complete_mottos'});showProblems(d.skipped);mottoPending=d.queued>0;show(d.queued?`已创建 ${d.queued} 个语录补全任务。按钮已锁定，后台会继续处理，完成后自动恢复。`:'当前没有需要补全语录的已发布角色。',false,true);updateToolbar();await jobs();}
    catch(error){mottoPending=false;show(error.message,true,true);}finally{busy=false;updateToolbar();}
  }
  $('#batch-mottos').onclick=completeMottos;
  $('#select-all-characters').onchange=event=>{document.querySelectorAll('[data-select-character]:not(:disabled)').forEach(input=>{input.checked=event.target.checked;choices.set(stage+':'+input.dataset.selectCharacter,input.checked);});saveChoices();updateToolbar();};
  $('#character-list').onchange=async event=>{
    const input=event.target;
    if(input.matches('[data-select-character]')){choices.set(stage+':'+input.dataset.selectCharacter,input.checked);saveChoices();updateToolbar();}
    if(input.matches('[data-classic]')){const row=characters.find(c=>c.id===Number(input.dataset.classic));input.disabled=true;try{await api('/api/admin/personality/characters/'+row.id,{classic:input.checked,revision:row.revision});await loadCharacters();}catch(error){show(error.message,true,true);input.checked=!input.checked;input.disabled=false;}}
  };
  $('#character-list').onclick=event=>{const open=event.target.closest('[data-inline-open]');if(open){openInline(open.dataset.inlineOpen);return;}const cancel=event.target.closest('[data-inline-cancel]');if(cancel){cancelInline(cancel.dataset.inlineCancel);return;}const save=event.target.closest('[data-inline-save]');if(save){saveInline(save.dataset.inlineSave);return;}const view=event.target.closest('[data-character]');if(view){openReview(Number(view.dataset.character));return;}const button=event.target.closest('[data-row-action]');if(!button)return;const ids=[Number(button.dataset.id)];if(button.dataset.rowAction==='regenerate')openRegenerate(ids);else act(button.dataset.rowAction,ids);};
  $('#batch-drafts').onclick=()=>act('generate',picked().map(c=>c.id),{keep_classics:$('#keep-selected-classics').checked});
  $('#batch-approve').onclick=()=>act('approve',picked().map(c=>c.id));$('#batch-recheck').onclick=()=>act('recheck',picked().map(c=>c.id));
  $('#batch-restore').onclick=()=>act('restore',picked().map(c=>c.id));$('#batch-exclude').onclick=()=>act('exclude',picked().map(c=>c.id));
  $('#undo-exclusion').onclick=async()=>{if(await act('restore',undoIDs,{versions:{}})){$('#undo-exclusion').hidden=true;undoIDs=[];}};
  document.querySelectorAll('[data-stage]').forEach(button=>button.onclick=()=>{stage=button.dataset.stage;pageNumber=1;const url=new URL(location.href);url.searchParams.set('stage',stage);history.replaceState(null,'',url);loadCharacters();});
  document.querySelector('.workflow-tabs').onkeydown=event=>{const buttons=[...document.querySelectorAll('[data-stage]')],index=buttons.indexOf(document.activeElement);if(index<0)return;let next;if(event.key==='ArrowRight')next=(index+1)%buttons.length;else if(event.key==='ArrowLeft')next=(index+buttons.length-1)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;event.preventDefault();buttons[next].focus();buttons[next].click();};
  function openRegenerate(ids){regenerateIDs=ids;regenerateVersions=versions(ids);$('#regenerate-selection').textContent='所选：'+ids.map(id=>characters.find(c=>c.id===id)?.name||id).join('、');$('#regenerate-feedback').value='';$('#regenerate-status').textContent='';$('#regenerate-dialog').showModal();}
  $('#batch-regenerate').onclick=()=>openRegenerate(picked().map(c=>c.id));$('#cancel-regenerate').onclick=()=>$('#regenerate-dialog').close();
  $('#regenerate-form').onsubmit=async event=>{event.preventDefault();const button=event.target.querySelector('[type=submit]');button.disabled=true;try{const done=await act('regenerate',regenerateIDs,{versions:regenerateVersions,feedback:$('#regenerate-feedback').value});if(done)$('#regenerate-dialog').close();else $('#regenerate-status').textContent=$('#batch-status').textContent;}finally{button.disabled=false;}};
  const emptyProfile=()=>({summary:'',mechanism:'',dimensions:Object.fromEntries(Object.keys(labels).map(key=>[key,{level:null,quote:'',reason:''}]))});
  function showSources(){renderEvidence();const sources=selected?.extra_sources||[];$('#extra-source-list').innerHTML=sources.map((source,i)=>`<p class="admin-note"><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">补充来源 ${i+1}</a> · ${source.text.length} 字 <button type="button" data-remove-source="${i}" class="secondary">移除</button></p>`).join('');}
  $('#add-source').onclick=()=>{if(!selected)return;const url=$('#extra-source-url').value.trim(),text=$('#extra-source-text').value.trim();if(!url.startsWith('https://')||text.length<10){show('请填写 HTTPS 来源链接和至少 10 字的原文',true);return;}selected.extra_sources=selected.extra_sources||[];if(selected.extra_sources.length>=12){show('最多补充 12 个来源',true);return;}selected.extra_sources.push({url,text});$('#extra-source-url').value='';$('#extra-source-text').value='';showSources();show('已加入当前编辑内容，保存草稿后生效。');};
  $('#extra-source-list').onclick=event=>{const button=event.target.closest('[data-remove-source]');if(button&&selected){selected.extra_sources.splice(Number(button.dataset.removeSource),1);showSources();}};
  function renderEvidence(){
    let panel=$('#evidence-inventory');if(!panel){panel=document.createElement('details');panel.id='evidence-inventory';panel.className='evidence-inventory';$('#profile-review-result').after(panel);}
    const check=selected?.profile_check||{},table=check.evidence_table,rows=Array.isArray(check.dimensions)?check.dimensions:[];
    if(!table?.dimensions){panel.hidden=true;if(selected?.review_origin==='starter_editor')$('#profile-review-result').insertAdjacentHTML('beforeend','<p>预置编辑档案：初始化时发布，未经过当前 AI 复核。</p>');return;}
    panel.hidden=false;const supported=rows.filter(row=>row.verdict==='supported').length;
    panel.innerHTML=`<summary>六维证据与判定 · 已认可 ${supported}/6</summary><div class="evidence-grid">${Object.entries(labels).map(([key,label])=>{
      const decision=rows.find(row=>row.key===key),dimension=selected.profile?.dimensions?.[key]||{},raw=table.dimensions[key]?.candidates,candidates=Array.isArray(raw)?raw.filter(item=>typeof item?.quote==='string').slice(0,2):[];
      return `<article><strong>${label} <small>${{supported:'已认可',insufficient:'资料不足',contradicted:'存在矛盾',inferred:'AI 推断'}[decision?.verdict]||'待复核'}</small></strong>${decision?.reason?`<p>${esc(decision.reason)}</p>`:''}${dimension.quote?`<p class="admin-note">当前引用</p><blockquote>${esc(dimension.quote)}</blockquote>`:''}<p class="admin-note">候选原文${candidates.length?'':'：暂无'}</p>${candidates.map(item=>`<blockquote>${esc(item.quote)}</blockquote>`).join('')}</article>`;
    }).join('')}</div>`;
  }
  function profileFields(profile){
    const types=['INTJ','INTP','ENTJ','ENTP','INFJ','INFP','ENFJ','ENFP','ISTJ','ISFJ','ESTJ','ESFJ','ISTP','ISFP','ESTP','ESFP'];
    $('#profile-fields').innerHTML=`<div class="review-fields"><label>MBTI 类型<select id="character-mbti"><option value="">未确定</option>${types.map(type=>`<option value="${type}">${type}</option>`).join('')}</select></label><label>角色图片地址<input id="character-image-url" type="url" maxlength="1000" placeholder="https://lain.bgm.tv/…"></label></div><label>角色简介<textarea data-profile="summary" maxlength="1200"></textarea></label><label>核心心理机制<textarea data-profile="mechanism" maxlength="1200"></textarea></label>`+Object.entries(labels).map(([key,label])=>`<fieldset class="dimension-editor" data-dimension="${key}"><legend>${label}</legend><label>倾向级别<select data-field="level"><option value="">资料不足</option>${[1,2,3,4,5,6,7].map(n=>`<option value="${n}">${n}</option>`).join('')}</select></label><label>依据类型<select data-field="evidence_type"><option value="verified">原文验证</option><option value="inferred">AI 推断</option><option value="manual">人工复核</option></select></label><label>资料原文<textarea data-field="quote" maxlength="1500"></textarea></label><label>标注理由<textarea data-field="reason" maxlength="1000"></textarea></label></fieldset>`).join('');
    $('#character-mbti').value=selected.mbti_type||'';$('#character-image-url').value=selected.image_url||'';
    for(const field of ['summary','mechanism'])$(`[data-profile="${field}"]`).value=profile[field]||'';
    for(const key of Object.keys(labels)){const wrap=$(`[data-dimension="${key}"]`);for(const field of ['level','quote','reason','evidence_type'])wrap.querySelector(`[data-field="${field}"]`).value=profile.dimensions?.[key]?.[field]??(field==='evidence_type'?'verified':'');}
    $('#profile-editor').value=JSON.stringify(profile,null,2);
  }
  function readProfile(){const profile=JSON.parse($('#profile-editor').value||'{}'),previous=profile.dimensions||{};for(const field of ['summary','mechanism'])profile[field]=$(`[data-profile="${field}"]`).value;profile.dimensions={};for(const key of Object.keys(labels)){const wrap=$(`[data-dimension="${key}"]`),get=field=>wrap.querySelector(`[data-field="${field}"]`).value;profile.dimensions[key]={level:get('level')?Number(get('level')):null,evidence_type:get('evidence_type'),quote:previous[key]?.evidence_id&&String(previous[key].quote).replace(/\r\n?/g,'\n')===get('quote')?previous[key].quote:get('quote'),reason:get('reason'),...(previous[key]?.evidence_id&&String(previous[key].quote).replace(/\r\n?/g,'\n')===get('quote')?{evidence_id:previous[key].evidence_id}:{}),...(Array.isArray(previous[key]?.supporting_quotes)?{supporting_quotes:previous[key].supporting_quotes}:{}),...(Array.isArray(previous[key]?.supporting_evidence_ids)?{supporting_evidence_ids:previous[key].supporting_evidence_ids}:{})};}return profile;}
  function openReview(id){const row=characters.find(c=>c.id===id);if(!row)return;selected=JSON.parse(JSON.stringify(row));$('#review').hidden=false;$('#review-title').textContent=selected.name+' · '+selected.work_name;$('#source-text').textContent=selected.source_text;$('#source-link').href=selected.source_url;$('#character-theme').value=selected.theme;$('#image-layout').value=selected.image_layout;$('#classic-keep').checked=selected.classic;profileFields(Object.keys(selected.profile).length?selected.profile:emptyProfile());$('#profile-review-result').innerHTML=`<strong>${esc(quality(selected)[0])}</strong><p>${esc(selected.profile_check.summary||'')}${selected.profile_check.issues?.length?'\n'+esc(selected.profile_check.issues.join('\n')):''}</p>`;for(const id of ['generate-draft','recheck-character','save-draft','approve-character'])$('#'+id).disabled=inProgress(selected);$('#generate-draft').disabled||=['approved','excluded'].includes(selected.status);$('#recheck-character').disabled||=['approved','excluded'].includes(selected.status);showSources();$('#review').scrollIntoView({behavior:'smooth'});}
  $('#close-review').onclick=()=>{$('#review').hidden=true;selected=null;};
  $('#apply-profile-json').onclick=()=>{try{profileFields(JSON.parse($('#profile-editor').value));show('JSON 已应用到表单，保存后生效。');}catch(error){show('JSON 格式有误',true);}};
  async function save(state){
    if(!selected)return false;
    const controls=['save-draft','approve-character','exclude-character','return-character'].map(id=>$('#'+id));
    controls.forEach(button=>{if(button)button.disabled=true;});
    try{const result=await api('/api/admin/personality/characters/'+selected.id,{status:state,theme:$('#character-theme').value,image_layout:$('#image-layout').value,mbti_type:$('#character-mbti').value,image_url:$('#character-image-url').value.trim(),classic:$('#classic-keep').checked,profile:readProfile(),extra_sources:selected.extra_sources||[],revision:selected.revision});selected=result.character;forget([selected.id]);show(state==='approved'?'已记录人工确认并发布':'角色内容已保存');await loadCharacters();return true;}catch(error){show(error instanceof SyntaxError?'档案 JSON 格式有误':error.message,true);return false;}finally{controls.forEach(button=>{if(button)button.disabled=false;});}
  }
  $('#save-draft').onclick=()=>save('draft');$('#approve-character').onclick=()=>save('approved');$('#exclude-character').onclick=()=>save('excluded');$('#return-character').onclick=()=>save('candidate');
  $('#generate-draft').onclick=()=>{if(selected)openRegenerate([selected.id]);};$('#recheck-character').onclick=async()=>{if(selected&&await save('draft'))await act('recheck',[selected.id]);};
  async function settings(){try{const d=await api('/api/admin/personality/catalog-settings');for(const [key,value] of Object.entries(d.settings))$('#catalog-settings-form').elements.namedItem(key).value=value;}catch(error){show(error.message,true);}}
  $('#catalog-settings-form').onsubmit=async event=>{event.preventDefault();try{await api('/api/admin/personality/catalog-settings',Object.fromEntries([...event.target.elements].filter(e=>e.name).map(e=>[e.name,Number(e.value)])));show('采集配置已保存');}catch(error){show(error.message,true);}};
  $('#import-catalog-file').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>2*1024*1024)throw Error('网页导入上限 2 MB，更大的数据包请使用管理命令');const d=await api('/api/admin/personality/catalog/import',JSON.parse(await file.text()));show(`已导入 ${d.imported} 个角色，保留 ${d.preserved} 个已有审核档案`);await loadCharacters();}catch(error){show(error.message,true);}finally{event.target.value='';}};
  $('#import-form').onsubmit=async event=>{event.preventDefault();const f=event.target.elements,button=event.target.querySelector('[type=submit]');button.disabled=true;try{const ids=f.subject_ids.value.trim();await api('/api/admin/personality/characters',{mode:f.mode.value,work_limit:Number(f.work_limit.value),character_limit:Number(f.character_limit.value),subject_ids:ids?ids.split(/[,，\s]+/).map(Number):[],retry_errors:f.retry_errors.checked});show('采集任务已创建，新增角色会进入待初选列表。');await jobs();}catch(error){show(error.message,true);}finally{button.disabled=false;}};
  async function jobs(){try{const d=await api('/api/admin/personality/jobs'),signature=JSON.stringify(d.items.map(j=>[j.id,j.status,j.phase,j.result]));mbtiPending=d.mbti_active>0;mottoPending=d.motto_active>0;updateToolbar();$('#job-list').innerHTML=d.items.length?d.items.map(j=>{const title=j.mbti_only?'MBTI 补全':j.motto_only?'语录补全':{import:'角色采集',profile:'档案生成与复核',report:'测评报告'}[j.kind],state={queued:'排队中',processing:'处理中',completed:'已完成',failed:'未完成',cancelled:'已取消'}[j.status]||j.status,phase={report_combined:'人格与角色综合分析',report_validation:'检查报告完整性',report_repair:'补充缺失内容',evidence_inventory:'整理六维证据',targeted_revision:'修正问题维度',evidence_search:'联网补证据',profile_generation:'生成档案',profile_inference:'AI 推断补全',profile_review:'依据复核',profile_reviewed:'复核完成',mbti_analysis:'分析角色 MBTI',motto_generation:'生成角色座右铭',person_analysis:'人格分析',character_review:'角色对照',finalized:'已完成'}[j.phase]||'';let summary='';if(j.mbti_only&&j.result.mbti_type)summary=`MBTI 已定位为 ${j.result.mbti_type}`;if(j.motto_only&&j.result.motto)summary=`已生成座右铭：${j.result.motto}`;if(j.kind==='import'&&Object.keys(j.result).length)summary=`检查作品 ${j.result.works||0} · 新增 ${j.result.imported||0} · 已有 ${j.result.existing||0} · 去重跳过 ${j.result.remembered||0} · 过滤 ${j.result.skipped||0} · 失败 ${j.result.failed||0}`;if(j.kind==='profile'&&j.result.review)summary=j.result.review==='passed'?'AI 依据复核通过，等待勾选发布':'资料需要补充，已进入待处理列表';if(j.kind==='profile'&&j.result.reused_dimensions)summary+=' · 沿用 '+j.result.reused_dimensions+' 个已认可维度';return `<div class="job-line"><strong>${esc(title)} · ${esc(state)}${phase?' · '+esc(phase):''}</strong><p>${esc(new Date(j.created_at).toLocaleString('zh-CN'))}</p>${summary?`<p>${esc(summary)}</p>`:''}${j.error?`<p class="status-error">${esc(j.error)}</p>`:''}${j.status==='failed'&&j.kind!=='report'?`<button type="button" class="secondary" data-retry="${esc(j.id)}">继续处理</button>`:''}</div>`;}).join(''):'<p class="quiet">暂无任务。</p>';if(lastJobs&&lastJobs!==signature)await loadCharacters();lastJobs=signature;}catch(error){show(error.message,true);}}
  $('#job-list').onclick=async event=>{const button=event.target.closest('[data-retry]');if(!button)return;button.disabled=true;try{await api('/api/admin/personality/jobs/'+button.dataset.retry+'/retry',{});await jobs();}catch(error){show(error.message,true);button.disabled=false;}};
  $('#refresh-jobs').onclick=jobs;$('#refresh-characters').onclick=()=>{pageNumber=1;loadCharacters();};$('#previous-page').onclick=()=>{pageNumber--;loadCharacters();};$('#next-page').onclick=()=>{pageNumber++;loadCharacters();};$('#character-search').onkeydown=event=>{if(event.key==='Enter'){pageNumber=1;loadCharacters();}};
  for(const id of ['character-mbti-filter','character-inference-filter'])$('#'+id).onchange=()=>{pageNumber=1;loadCharacters();};
  Promise.all([settings(),loadCharacters(),jobs()]).catch(error=>show(error.message,true));setInterval(()=>{if(!window.PersonalityAdminAuth?.expired&&!document.hidden&&!$('#regenerate-dialog').open)jobs();},6000);
})();
