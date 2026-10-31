(() => {
  'use strict';
  if(!location.pathname.startsWith('/admin'))return;
  let timer;
  async function refresh(){
    clearTimeout(timer);if(document.hidden||window.PersonalityAdminAuth?.expired)return;
    try{
      const response=await fetch('/api/admin/personality/operations?summary=1',{credentials:'same-origin'});
      if(response.status===403){document.querySelectorAll('[data-operations-link]').forEach(e=>{e.hidden=true;e.style.display='none';});return;}
      if(response.status===401){window.PersonalityAdminAuth?.requireLogin();return;}
      if(response.ok){const data=await response.json(),count=data.counts.alerts+data.counts.feedback;document.querySelectorAll('[data-operations-link]').forEach(link=>{link.hidden=false;link.style.removeProperty('display');link.textContent=(link.dataset.operationsTitle||'运行与反馈')+(count?'（'+count+'）':'');link.classList.toggle('has-operations-alerts',Boolean(data.counts.alerts));});}
    }catch(_){/* A transient summary failure must not block other admin work. */}
    timer=setTimeout(refresh,30000);
  }
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)refresh();});window.addEventListener('pagehide',()=>clearTimeout(timer));refresh();
})();
