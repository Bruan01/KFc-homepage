(() => {
  'use strict';
  const auth={expired:false,requireLogin(){
    if(auth.expired)return;
    auth.expired=true;
    const message='管理员登录已失效，请重新登录后再操作。';
    const panel=document.createElement('p');panel.className='admin-auth-message';panel.setAttribute('role','alert');
    const text=document.createElement('span');text.textContent=message;
    const link=document.createElement('a');link.className='secondary';link.textContent='重新登录';
    link.href='/login?next='+encodeURIComponent(location.pathname+location.search);
    panel.append(text,link);
    const anchor=document.querySelector('#admin-status');if(anchor){anchor.textContent=message;anchor.classList.add('status-error');anchor.after(panel);}
    document.querySelectorAll('button').forEach(button=>{button.disabled=true;});
    window.dispatchEvent(new Event('personality-admin-auth-expired'));
  }};
  window.PersonalityAdminAuth=auth;
})();
