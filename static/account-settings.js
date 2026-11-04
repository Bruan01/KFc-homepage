(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const el=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
  const EMAIL_RE=/^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  async function api(path,body){const response=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});const data=await response.json();if(!response.ok)throw new Error(data.error||'加载失败');return data;}

  function applyEmailState(data){
    const summary=$('accountEmailSummary'),toggle=$('toggleEmailForm'),submit=$('bindSubmit');
    if(!summary||!toggle)return;
    if(data.email_verified&&data.email){
      summary.textContent=`当前绑定：${data.email}（已验证）`;
      toggle.textContent='更换邮箱';
      if(submit)submit.textContent='确认更换';
    }else{
      summary.textContent=data.email
        ?`当前邮箱：${data.email}（未验证，不能用于登录）`
        :'尚未绑定邮箱。绑定后可用于登录和找回密码。';
      toggle.textContent='绑定邮箱';
      if(submit)submit.textContent='确认绑定';
    }
  }

  function startCountdown(button,seconds=60){
    button.disabled=true;
    let left=seconds;
    button.textContent=`${left}s 后重发`;
    const timer=setInterval(()=>{
      left-=1;
      if(left<=0){clearInterval(timer);button.disabled=false;button.textContent='发送验证码';return;}
      button.textContent=`${left}s 后重发`;
    },1000);
  }

  async function load(){
    try{const data=await api('/api/account/settings');const list=$('settingsInfo');list.replaceChildren();
      for(const [label,value] of [['账号',data.username],['邮箱',data.email||'未绑定'],['邮箱验证',data.email_verified?'已验证':'未验证'],['密码',data.password_set?'••••••••（已设置）':'未设置'],['IP 属地',data.ip_location||'未知'],['注册时间',data.created_at?new Date(data.created_at).toLocaleString('zh-CN'):'—']])list.append(el('dt',label),el('dd',value));
      applyEmailState(data);
    }catch(error){$('settingsStatus').textContent=error.message;}
  }

  function bindEmailSection(){
    const form=$('emailBindForm'),toggle=$('toggleEmailForm');
    if(!form||!toggle)return;
    toggle.addEventListener('click',()=>{
      form.hidden=!form.hidden;
      if(!form.hidden)$('bindEmail').focus();
      $('bindStatus').textContent='';
    });
    $('sendBindCode').addEventListener('click',async()=>{
      const email=($('bindEmail').value||'').trim().toLowerCase();
      const button=$('sendBindCode');
      if(!EMAIL_RE.test(email)){$('bindStatus').textContent='请先填写正确的新邮箱';return;}
      button.disabled=true;
      $('bindStatus').textContent='正在发送…';
      try{
        await api('/api/user/verification-code',{email,purpose:'bind'});
        $('bindStatus').textContent='验证码已发送，请查收（含垃圾箱）';
        startCountdown(button);
      }catch(error){button.disabled=false;$('bindStatus').textContent=error.message;}
    });
    form.addEventListener('submit',async(event)=>{
      event.preventDefault();
      const email=($('bindEmail').value||'').trim().toLowerCase();
      const code=($('bindCode').value||'').trim();
      const password=$('bindPassword').value||'';
      if(!EMAIL_RE.test(email))return $('bindStatus').textContent='请填写正确的新邮箱';
      if(!code)return $('bindStatus').textContent='请填写邮箱验证码';
      if(!password)return $('bindStatus').textContent='请填写当前密码';
      const submit=$('bindSubmit');
      submit.disabled=true;
      $('bindStatus').textContent='正在提交…';
      try{
        const data=await api('/api/user/email/bind',{email,code,currentPassword:password});
        form.reset();form.hidden=true;
        $('bindStatus').textContent=data.rebound?'邮箱已更换':'邮箱已绑定';
        await load();
      }catch(error){$('bindStatus').textContent=error.message;}
      finally{submit.disabled=false;}
    });
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
    bindEmailSection();
    document.querySelector('[data-tab=settings]')?.addEventListener('click',()=>{history.replaceState({},'', '/account/settings');load();});
    if(location.pathname==='/account/settings'||new URLSearchParams(location.search).get('tab')==='settings')document.querySelector('[data-tab=settings]')?.click();
  }
  document.addEventListener('DOMContentLoaded',init);
})();
