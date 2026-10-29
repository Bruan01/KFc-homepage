/* All scores below come from explicit fictional answers. No user assessment is run here. */
(() => {
  'use strict';
  const groups = [
    {name:'内向偏好',left:'I 内向',right:'E 外向',kind:'axis',color:'#628675',answers:[6,5,2,6],reverse:[2],items:['独处后我更容易恢复精力。','面对复杂问题，我倾向先独自整理想法。','连续的社交活动通常让我更有精力。','比起边说边想，我更习惯想清楚再说。']},
    {name:'直觉偏好',left:'N 直觉',right:'S 实感',kind:'axis',color:'#6d889c',answers:[6,5,3,6],reverse:[2],items:['我容易联想到事情背后的多种可能。','学习时，我想先了解整体框架。','我通常先关注明确的细节，再考虑整体含义。','我对一个想法可能带来的变化很感兴趣。']},
    {name:'情感偏好',left:'F 情感',right:'T 思考',kind:'axis',color:'#a0807f',answers:[6,5,2,5],reverse:[2],items:['做决定时，我会考虑相关人的感受。','个人价值观会影响我的重要选择。','处理分歧时，我通常优先选择逻辑最一致的方案。','即使更麻烦，我也想照顾个体的特殊处境。']},
    {name:'灵活偏好',left:'P 灵活',right:'J 计划',kind:'axis',color:'#9a8b66',answers:[5,4,3,4],reverse:[2],items:['我喜欢为计划保留调整的空间。','新信息出现时，我愿意改变原来的安排。','提前确定每个步骤会让我更自在。','在必须决定之前，我愿意多保留几个选项。']},
    {name:'情绪敏感',kind:'dimension',answers:[6,5,2,6],reverse:[2],items:['周围气氛的变化容易影响我的情绪。','一句无意的话可能让我在意较久。','我很少注意到自己细微的情绪变化。','别人的语气变化容易被我察觉。']},
    {name:'情绪恢复',kind:'dimension',answers:[4,4,3,5],reverse:[2],items:['情绪波动后，我通常能逐渐回到自己的节奏。','我知道哪些活动可以帮助自己平静。','一次不愉快通常会影响我接下来的很长时间。','休息后，我能重新面对让我难过的问题。']},
    {name:'共情关注',kind:'dimension',answers:[6,6,2,5],reverse:[2],items:['我愿意了解他人感受背后的原因。','遇到不同看法时，我会尝试理解对方处境。','如果事情与我无关，我很少关心对方的感受。','我会留意自己的表达是否让对方难堪。']},
    {name:'关系边界',kind:'dimension',answers:[5,4,3,5],reverse:[2],items:['即使在意对方，我也能表达不愿接受的事。','我能区分理解他人与替他承担责任。','为了避免关系紧张，我通常会答应超出能力的请求。','我可以在保持尊重的同时拒绝别人。']},
    {name:'发散思考',kind:'dimension',answers:[6,5,2,6],reverse:[2],items:['面对一个问题，我容易想到多种解决方向。','我喜欢把原本不同的想法联系起来。','找到第一个可行答案后，我通常不会再探索其他可能。','我会设想事情还可能怎样发展。']},
    {name:'执行稳定',kind:'dimension',answers:[4,3,4,4],reverse:[2],items:['即使兴趣减退，我也能维持必要的行动。','我通常能按照自己的安排推进事情。','如果没有外部提醒，我容易一直推迟开始。','任务遇到阻碍时，我能继续完成一小步。']}
  ];
  function score(group) {
    const converted = group.answers.map((answer,index) => group.reverse.includes(index) ? 8-answer : answer);
    const mean = converted.reduce((a,b) => a+b,0)/converted.length;
    return {converted,mean,raw:(mean-1)/6*100,value:Math.round((mean-1)/6*100)};
  }
  groups.forEach(group => Object.assign(group,score(group)));
  const axes = groups.filter(group => group.kind==='axis');
  const dimensions = groups.filter(group => group.kind==='dimension');
  document.querySelector('#axes').innerHTML=axes.map(group=>`<div class="axis"><div class="axis-head"><span class="axis-label"><b>${group.left[0]}</b>${group.left.slice(2)}</span><span class="axis-number">${group.value}</span><span class="axis-opposite">${group.right.slice(2)}<b>${group.right[0]}</b></span></div><div class="axis-track" role="meter" aria-label="${group.name}指数" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${group.value}"><div class="axis-fill" style="width:${group.value}%;--axis-color:${group.color}"></div></div></div>`).join('');
  // Editorial assumptions for this prototype, not official or measured character data.
  const characterLevels=[6,4,6,3,5,5];
  const comparisons=dimensions.map((group,index)=>({name:group.name,user:group.raw,character:(characterLevels[index]-1)/6*100,level:characterLevels[index]}));
  comparisons.forEach(row=>row.gap=Math.abs(row.user-row.character));
  const similarity=Math.round(100-comparisons.reduce((total,row)=>total+row.gap,0)/comparisons.length);
  document.querySelector('#similarity').textContent=String(similarity);
  const byGap=[...comparisons].sort((a,b)=>a.gap-b.gap);
  document.querySelector('#closest-dimensions').textContent=byGap.slice(0,2).map(row=>row.name).join('、');
  document.querySelector('#different-dimensions').textContent=byGap.slice(-2).reverse().map(row=>row.name).join('、');
  const radar=document.querySelector('#radar');
  radar.querySelectorAll(':scope > :not(title):not(desc)').forEach(element=>element.remove());
  const ns='http://www.w3.org/2000/svg';
  const center={x:180,y:155}; const radius=96;
  function point(index,r){const angle=-Math.PI/2+index*Math.PI/3;return [center.x+Math.cos(angle)*r,center.y+Math.sin(angle)*r];}
  function add(tag,attrs,content){const element=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>element.setAttribute(key,value));if(content)element.textContent=content;radar.append(element);return element;}
  [1,0.75,0.5,0.25].forEach(level=>add('polygon',{points:dimensions.map((_,index)=>point(index,radius*level).join(',')).join(' '),fill:level===1?'#f1f5ea':'none',stroke:'#d8e1d0','stroke-width':0.8}));
  dimensions.forEach((_,index)=>{const [x,y]=point(index,radius);add('line',{x1:center.x,y1:center.y,x2:x,y2:y,stroke:'#d8e1d0','stroke-width':0.8});});
  add('polygon',{points:comparisons.map((row,index)=>point(index,radius*row.character/100).join(',')).join(' '),fill:'#c5ae87','fill-opacity':0.12,stroke:'#98724b','stroke-width':1.8,'stroke-dasharray':'4 4'});
  add('polygon',{points:comparisons.map((row,index)=>point(index,radius*row.user/100).join(',')).join(' '),fill:'#7fa18a','fill-opacity':0.22,stroke:'#396553','stroke-width':2.2});
  comparisons.forEach((row,index)=>{
    const [x,y]=point(index,radius*row.user/100);add('circle',{cx:x,cy:y,r:3.2,fill:'#396553',stroke:'#fcfdf9','stroke-width':1});
    const [cx,cy]=point(index,radius*row.character/100);add('rect',{x:cx-2.6,y:cy-2.6,width:5.2,height:5.2,fill:'#98724b',stroke:'#fcfdf9','stroke-width':0.7});
    const [lx,ly]=point(index,radius+36);add('text',{x:lx,y:ly-5,'text-anchor':'middle',class:'radar-label'},row.name);
    const values=add('text',{x:lx,y:ly+14,'text-anchor':'middle'});
    [['radar-user-value',Math.round(row.user)],['radar-slash',' / '],['radar-character-value',Math.round(row.character)]].forEach(([className,value])=>{const span=document.createElementNS(ns,'tspan');span.setAttribute('class',className);span.textContent=String(value);values.append(span);});
  });
  document.querySelector('#radar-desc').textContent=comparisons.map(row=>`${row.name}：你 ${Math.round(row.user)}，夏目贵志 ${Math.round(row.character)}`).join('；')+'。绿色实线圆点为你，暖棕虚线方点为角色。';
  function appendAnswers(target){
    const section=document.createElement('section');section.id='raw-data';section.className='raw-answers';
    section.innerHTML='<h2>原始作答</h2>'+groups.map(group=>`<div class="source-group"><h3>${group.name}</h3><ol>${group.items.map((item,index)=>`<li>${item} <strong>${group.answers[index]} 分</strong></li>`).join('')}</ol></div>`).join('');
    target.append(section);
  }
  document.querySelectorAll('.feedback-options button').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('.feedback-options button').forEach(option=>option.setAttribute('aria-pressed',String(option===button)));
    document.querySelector('#feedback-status').textContent=`已选择“${button.textContent}”。`;
  }));
  const saveDialog=document.querySelector('#save-dialog');
  document.querySelectorAll('.save-trigger').forEach(button=>button.addEventListener('click',()=>{
    document.querySelector('#save-status').textContent='';
    saveDialog.showModal();
  }));
  document.querySelector('#download-report').addEventListener('click',()=>{
    const status=document.querySelector('#save-status');
    try {
      const copy=document.documentElement.cloneNode(true);
      copy.querySelectorAll('script,#save-dialog,.save-trigger,.feedback,.skip').forEach(element=>element.remove());
      copy.querySelector('body').removeAttribute('data-print-no-quote');
      copy.querySelector('body').removeAttribute('data-print-no-answers');
      if(!document.querySelector('#include-quote').checked)copy.querySelectorAll('[data-private-quote],.evidence').forEach(element=>element.remove());
      if(document.querySelector('#include-answers').checked)appendAnswers(copy.querySelector('main'));
      copy.querySelectorAll('details').forEach(element=>element.open=true);
      const blob=new Blob(['<!doctype html>\n'+copy.outerHTML],{type:'text/html;charset=utf-8'});
      const url=URL.createObjectURL(blob);
      const link=document.createElement('a');
      link.href=url;link.download='心映-人格共鸣档案.html';
      document.body.append(link);link.click();link.remove();
      window.setTimeout(()=>URL.revokeObjectURL(url),30000);
      status.textContent='已发起下载，可在浏览器下载列表中查看。';
    } catch(error) {
      status.textContent='未能生成下载文件，请重试，或使用“打印 / 另存为 PDF”。';
    }
  });
  document.querySelector('#print-report').addEventListener('click',()=>{
    document.body.toggleAttribute('data-print-no-quote',!document.querySelector('#include-quote').checked);
    document.body.toggleAttribute('data-print-no-answers',!document.querySelector('#include-answers').checked);
    saveDialog.close();
    window.print();
  });
  let printDetails=[];
  window.addEventListener('beforeprint',()=>{
    if(document.querySelector('#include-answers').checked&&!document.querySelector('#raw-data'))appendAnswers(document.querySelector('main'));
    printDetails=[...document.querySelectorAll('details')].map(element=>({element,open:element.open}));
    printDetails.forEach(({element})=>element.open=true);
  });
  window.addEventListener('afterprint',()=>{
    printDetails.forEach(({element,open})=>element.open=open);
    printDetails=[];
    document.querySelector('#raw-data')?.remove();
    document.body.removeAttribute('data-print-no-quote');
    document.body.removeAttribute('data-print-no-answers');
  });
})();
