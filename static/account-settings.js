(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const el=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
  async function api(path,body){const response=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});const data=await response.json();if(!response.ok)throw new Error(data.error||'加载失败');return data;}
  async function load(){
    try{const data=await api('/api/account/settings');const list=$('settingsInfo');list.replaceChildren();
      for(const [label,value] of [['账号',data.username],['邮箱',data.email||'未绑定'],['邮箱验证',data.email_verified?'已验证':'未验证'],['密码',data.password_set?'••••••••（已设置）':'未设置'],['IP 属地',data.ip_location||'未知'],['注册时间',data.created_at?new Date(data.created_at).toLocaleString('zh-CN'):'—']])list.append(el('dt',label),el('dd',value));
    }catch(error){$('settingsStatus').textContent=error.message;}
  }
  function init(){
    const panel=$('tab-settings');if(!panel)return;
    const dialog=$('passwordChangeDialog'),warning=$('passwordChangeWarning'),form=$('passwordChangeForm');
    $('openPasswordChange').addEventListener('click',()=>{form.reset();form.hidden=true;warning.hidden=false;$('continuePasswordChange').hidden=false;$('submitPasswordChange').hidden=true;$('passwordChangeError').textContent='';dialog.showModal();});
    $('continuePasswordChange').addEventListener('click',()=>{warning.hidden=true;form.hidden=false;$('continuePasswordChange').hidden=true;$('submitPasswordChange').hidden=false;form.elements.current_password.focus();});
    $('closePasswordChange').addEventListener('click',()=>{if(!$('submitPasswordChange').disabled)dialog.close();});
    dialog.addEventListener('cancel',event=>{if($('submitPasswordChange').disabled)event.preventDefault();});
    form.addEventListener('submit',async event=>{event.preventDefault();const submit=$('submitPasswordChange');if(submit.disabled)return;submit.disabled=true;$('closePasswordChange').disabled=true;submit.textContent='正在修改…';
      try{const data=await api('/api/account/password',Object.fromEntries(new FormData(form)));form.reset();dialog.close();$('settingsStatus').textContent=data.message;await load();}
      catch(error){$('passwordChangeError').textContent=error.message;}finally{submit.disabled=false;$('closePasswordChange').disabled=false;submit.textContent='确认修改密码';}
    });
    dialog.addEventListener('close',()=>form.reset());
    document.querySelector('[data-tab=settings]')?.addEventListener('click',()=>{history.replaceState({},'', '/account/settings');load();});
    if(location.pathname==='/account/settings'||new URLSearchParams(location.search).get('tab')==='settings')document.querySelector('[data-tab=settings]')?.click();
  }
  document.addEventListener('DOMContentLoaded',init);
})();
