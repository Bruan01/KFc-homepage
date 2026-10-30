(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const esc = text => String(text ?? '').replace(/[&<>"']/g, value => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[value]));
  async function api(url, options = {}) {
    const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] || '';
    const response = await fetch(url, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', 'X-CSRFToken':token, ...options.headers}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(data.error || '服务暂时无法连接，请重试'); error.status = response.status; throw error; }
    return data;
  }
  const send = (url, body, method = 'POST') => api(url, {method, body:JSON.stringify(body)});
  const names = {active:'进行中', ready:'待生成报告', queued:'等待生成', processing:'正在分析', completed:'已完成', failed:'可重试分析'};
  async function home() {
    try {
      const config = await api('/api/personality/config');
      if(config.cast?.length){
        const art=$('.landing-art');
        art.classList.add('cast-collage');art.removeAttribute('aria-hidden');
        art.innerHTML='<div class="cast-cards">'+config.cast.map((role,i)=>`<figure class="cast-card cast-${i}"><img src="${esc(role.image)}" alt="${esc(role.name)}" loading="${i?'lazy':'eager'}"><figcaption><strong>${esc(role.name)}</strong><span>${esc(role.work)}</span></figcaption></figure>`).join('')+'</div><p class="cast-caption">不同的故事，相似的心。</p>';
        art.querySelectorAll('img').forEach(img=>img.onerror=()=>img.closest('figure').classList.add('image-unavailable'));
      }
      if (!config.enabled) $('#availability').textContent = '新测评暂时暂停，已有档案可以继续查看。';
      else if (!config.characters_ready) $('#availability').textContent = '角色档案正在准备中。你现在可以完成测评并保存人格报告，角色共鸣暂未开放。';
    } catch (error) { $('#availability').textContent = error.message; }
    async function history() {
      try {
        const data = await api('/api/personality/assessments');
        $('#history-list').innerHTML = data.items.length ? data.items.map(row => `<article class="history-item"><div><h3>${esc(row.type || names[row.status])}${row.title ? ' · '+esc(row.title) : ''}</h3><p>${esc(new Date(row.created_at).toLocaleString('zh-CN'))} · ${esc(names[row.status])}</p></div><div class="history-actions"><a href="${row.status==='active'||row.status==='ready'?'/personality/test?id=':'/personality/report/'}${esc(row.id)}">${row.status==='active'||row.status==='ready'?'继续探索':'查看档案'}</a><button type="button" data-delete="${esc(row.id)}">删除</button></div></article>`).join('') : '<p class="quiet">你的第一份人格档案，从这里开始。</p>';
      } catch (error) {
        $('#history-list').innerHTML = error.status === 401 ? '<p class="quiet"><a href="/login?next=/personality">登录后查看与保存探索记录</a></p>' : `<p class="status-error">${esc(error.message)}</p>`;
      }
    }
    $('#history-list').addEventListener('click', async event => {
      const button = event.target.closest('[data-delete]');
      if (!button || !confirm('删除这次探索及其回答？此操作无法撤回。')) return;
      button.disabled = true;
      try { await api('/api/personality/assessments/'+button.dataset.delete, {method:'DELETE'}); await history(); }
      catch (error) { $('#availability').textContent = error.message; button.disabled = false; }
    });
    await history();
  }
  async function test() {
    const container = $('#test-content'), status = $('#test-status');
    let state, questionIndex = 0, answers = {}, timer, pollTimer, pollVersion = 0, chain = Promise.resolve(), blocked = false;
    const id = new URLSearchParams(location.search).get('id');
    const validID = value => /^[0-9a-f-]{36}$/.test(value || '');
    function message(error) {
      status.textContent = error.message || String(error);
      status.classList.add('status-error');
      if (error.status === 409) { blocked = true; clearTimeout(pollTimer); $('#reload-test').hidden = false; }
    }
    $('#reload-test').addEventListener('click', () => location.reload());
    function loadRound() {
      pollVersion++;
      clearTimeout(pollTimer);
      answers = {};
      if (state.step) for (const question of state.step.questions) if (state.answers[question.id]) answers[question.id] = {...state.answers[question.id]};
      const unfinished = state.step ? state.step.questions.findIndex(question => !answered(question)) : -1;
      questionIndex = unfinished >= 0 ? unfinished : 0; render();
    }
    function persist(complete = false, action = '') {
      pollVersion++;
      clearTimeout(timer);
      clearTimeout(pollTimer);
      if (blocked) return Promise.reject(new Error('请先重新载入最新进度'));
      const snapshot = JSON.parse(JSON.stringify(answers));
      const operation = chain.catch(() => {}).then(async () => {
        if (blocked) throw new Error('请重新载入最新进度');
        const next = await send('/api/personality/assessments/'+state.id, {revision:state.revision, answers:snapshot, complete, ...(action?{action}: {})});
        state = next;
        status.textContent = '进度已保存';status.classList.remove('status-error');
        return next;
      });
      chain = operation;
      return operation;
    }
    function scheduleSave() { clearTimeout(timer); timer = setTimeout(() => persist().catch(message), 650); status.textContent = '正在保存…'; }
    document.querySelector('.app-header>a:last-child').addEventListener('click', async event => {
      if (!state || state.status !== 'active') return;
      event.preventDefault();
      if(state.step?.ai_followup?.state==='pending'){location.href='/personality';return;}
      try { await persist(); location.href='/personality'; } catch(error) { message(error); }
    });
    function answered(question) {
      const answer = answers[question.id];
      return answer && (question.kind==='scale' ? !answer.skipped && Number.isInteger(answer.value) : answer.skipped || answer.note.trim().length>=8);
    }
    function render() {
      if (['queued','processing','completed','failed'].includes(state.status)) { location.replace('/personality/report/'+state.id); return; }
      if (state.status === 'ready') {
        container.innerHTML = '<section class="intro-panel"><p class="eyebrow">探索已完成</p><h1>把这些具体的回答，连成你的轮廓。</h1><p>回答已保存。现在可以生成你的人格档案，也可以返回调整最后一轮。</p><div class="ready-actions"><button id="generate" class="primary">生成人格档案</button><button id="revise" class="secondary">返回修改</button></div></section>';
        $('#generate').onclick = async () => { $('#generate').disabled = true; try { await send('/api/personality/assessments/'+state.id+'/submit',{}); location.href='/personality/report/'+state.id; } catch (error) { message(error); $('#generate').disabled=false; } };
        $('#revise').onclick = async () => { try { await persist(false,'back'); loadRound(); } catch(error){message(error);} };
        return;
      }
      if(state.step?.ai_followup?.state==='pending'){
        const number=state.step.ai_followup.round;
        container.innerHTML=`<section class="intro-panel interview-wait" role="status"><p class="eyebrow">补充理解 · 第 ${number} 次</p><h1>顺着你的回答，再听你说一点。</h1><p>正在整理一个与你的经历有关的小问题。回答已保存，你可以稍后回来，也可以直接继续生成档案。</p><div class="ready-actions"><button id="skip-interview" class="secondary" type="button">跳过补充，继续生成</button><button id="back-interview" class="secondary" type="button">返回修改</button></div></section>`;
        async function leave(action){pollVersion++;clearTimeout(pollTimer);$('#skip-interview').disabled=true;$('#back-interview').disabled=true;try{state=await api('/api/personality/assessments/'+state.id);if(state.status==='active')await persist(false,action);loadRound();}catch(error){message(error);if($('#skip-interview'))$('#skip-interview').disabled=false;if($('#back-interview'))$('#back-interview').disabled=false;}}
        $('#skip-interview').onclick=()=>leave('skip_followup');$('#back-interview').onclick=()=>leave('back');
        const revision=state.revision,version=pollVersion;
        pollTimer=setTimeout(async()=>{try{const next=await api('/api/personality/assessments/'+state.id);if(blocked||state.revision!==revision||version!==pollVersion)return;state=next;loadRound();}catch(error){message(error);}},document.hidden?5000:1500);
        return;
      }
      const question = state.step.questions[questionIndex];
      const answer = answers[question.id] || {value:null,note:'',skipped:false};
      container.innerHTML = `<div class="stage-head"><strong>${esc(state.step.title)}</strong><span>第 ${state.step_index+1} 轮 · 本轮 ${questionIndex+1}/${state.step.questions.length}</span></div><div class="round-progress" aria-hidden="true"><span style="width:${(questionIndex+1)/state.step.questions.length*100}%"></span></div><section class="question-panel"><h1 id="question-title">${esc(question.text)}</h1>${question.hint?`<p class="question-hint">${esc(question.hint)}</p>`:''}${question.kind==='scale'?`<fieldset class="scale-options" aria-labelledby="question-title">${[1,2,3,4,5,6,7].map(n=>`<label><input type="radio" name="scale" value="${n}" ${answer.value===n&&!answer.skipped?'checked':''}><span>${n}</span></label>`).join('')}</fieldset><div class="scale-ends"><span>非常不同意</span><span>非常同意</span></div><p class="question-hint">按最近三个月通常的反应选择。没有完全相同的经历时，可以设想自己最可能怎么做。</p><details ${answer.note?'open':''}><summary>补充说明（可选）</summary><label class="question-hint" for="answer-note">例如：以前和现在不同，或只在特定情境下如此。</label><textarea id="answer-note" maxlength="3000"></textarea></details>`:'<label class="question-hint" for="answer-note">你的想法与原因</label><textarea class="open-answer" id="answer-note" maxlength="3000"></textarea>'}${question.kind==='open'?`<label class="skip-choice"><input id="skip-question" type="checkbox" ${answer.skipped?'checked':''}>暂时跳过这道情境题</label>`:''}</section><div class="test-actions"><button id="previous" class="secondary" ${questionIndex===0&&state.step_index===0?'disabled':''}>上一题</button><button id="next" class="primary">${questionIndex===state.step.questions.length-1?'完成这一轮':'下一题'}</button></div>`;
      if(question.source_quote){const quote=document.createElement('blockquote');quote.className='interview-source';const label=document.createElement('small');label.textContent='你刚才提到';const words=document.createElement('p');words.textContent=question.source_quote;quote.append(label,words);$('#question-title').before(quote);}
      if(question.context_items?.length){const list=document.createElement('div');list.className='interview-comparison';question.context_items.forEach(item=>{const card=document.createElement('blockquote');card.className='interview-source';const title=document.createElement('p');title.textContent=item.text;const value=document.createElement('small');value.textContent='你的选择：'+item.value+' / 7';card.append(title,value);list.append(card);});$('#question-title').before(list);}
      if(question.source_question){const source=document.createElement('details');source.className='interview-origin';const title=document.createElement('summary');title.textContent='查看对应的原题';const words=document.createElement('p');words.textContent=question.source_question;source.append(title,words);$('#question-title').before(source);}
      $('#answer-note').value=answer.note;
      function current() { return answers[question.id] || (answers[question.id]={value:null,note:'',skipped:false}); }
      container.querySelectorAll('input[name=scale]').forEach(input=>input.onchange=()=>{const answer=current();answer.value=Number(input.value);answer.skipped=false;scheduleSave();});
      $('#answer-note').oninput=event=>{current().note=event.target.value;if(question.kind==='open'){current().skipped=false;$('#skip-question').checked=false;}scheduleSave();};
      if ($('#skip-question')) $('#skip-question').onchange=event=>{const answer=current();answer.skipped=event.target.checked;if(answer.skipped){answer.value=null;container.querySelectorAll('input[name=scale]').forEach(input=>input.checked=false);}scheduleSave();};
      $('#next').onclick=async()=>{
        if(!answered(question)){message(new Error(question.kind==='scale'?'请先选择一个分数':'请写至少 8 个字，或选择跳过'));return;}
        $('#next').disabled=true;$('#previous').disabled=true;
        try{if(questionIndex<state.step.questions.length-1){await persist();questionIndex++;render();}else{await persist(true);loadRound();}window.scrollTo({top:0,behavior:'instant'});}
        catch(error){message(error);if($('#next'))$('#next').disabled=false;if($('#previous'))$('#previous').disabled=false;}
      };
      $('#previous').onclick=async()=>{try{await persist();if(questionIndex>0){questionIndex--;render();}else{await persist(false,'back');loadRound();}}catch(error){message(error);}};
    }
    try {
      if (id) { if(!validID(id))throw new Error('测评地址无效'); state=await api('/api/personality/assessments/'+id);loadRound(); }
      else {
        const settings=await api('/api/personality/config');
        container.innerHTML=`<section class="intro-panel"><p class="eyebrow">留一点时间，听听自己的回答</p><h1>从你的真实感受开始。</h1><p>没有正确答案。量表可以补充说明，情境题关注你的原因。进度会自动保存，随时可以回来继续。</p><p>回答默认为私密记录，你可以在探索记录中删除。</p>${settings.ai_available?'<label class="consent"><input type="checkbox" id="ai-consent"><span>同意将本次回答发送至站点配置的 AI 服务，用于个性化追问和人格分析。你也可以不勾选，使用量表与规则解读。</span></label>':''}<button class="primary" id="begin" ${settings.enabled?'':'disabled'}>开始第一轮</button></section>`;
        $('#begin').onclick=async()=>{ $('#begin').disabled=true;try{state=await send('/api/personality/assessments',{ai_consent:$('#ai-consent')?.checked||false});history.replaceState(null,'','?id='+state.id);loadRound();}catch(error){message(error);$('#begin').disabled=false;}};
      }
    } catch(error) { message(error);container.innerHTML='<p>暂时无法载入探索。<a href="/personality">返回我的记录</a></p>'; }
    window.addEventListener('pagehide',()=>{clearTimeout(timer);clearTimeout(pollTimer);});
  }
  (document.body.dataset.page==='test'?test():home()).catch(error=>{const target=$('#test-status')||$('#availability');if(target)target.textContent=error.message;});
})();
