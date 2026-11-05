(() => {
  'use strict';
  const buttons = [...document.querySelectorAll('.claim-trigger')];
  const claim = document.getElementById('claim-personality-badge');
  let busy = false, attentionShown = false, observer;
  function watchClaim() {
    if (!claim || claim.disabled || attentionShown || observer) return;
    const highlight = () => {
      attentionShown = true;
      claim.classList.add('claim-attention');
      claim.addEventListener('animationend', () => claim.classList.remove('claim-attention'), {once:true});
      observer?.disconnect();
    };
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting && entry.intersectionRatio >= .6)) highlight();
      }, {threshold:.6});
      observer.observe(claim);
    }
  }
  document.addEventListener('kflow:personality-report-ready', watchClaim);
  for (const button of buttons) button.addEventListener('click', async () => {
    if (busy || button.disabled) return;
    busy = true;
    for (const item of buttons) { item.disabled = true; item.dataset.claiming = 'true'; item.setAttribute('aria-busy','true'); item.textContent = '正在领取并佩戴…'; }
    try {
      const id = location.pathname.split('/').filter(Boolean).pop();
      const response = await fetch('/api/achievements/personality/claim', {
        method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({assessment_id:id, equip:true}),
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 401) {
        location.replace('/login?next=' + encodeURIComponent(location.pathname + location.search));
        return;
      }
      if (!response.ok) throw Error(data.error || '暂时无法领取，请稍后重试。你的报告已保存，无需重做。');
      if (!data.equipped) throw Error('勋章已领取，佩戴暂未完成，请重试。');
      location.assign('/murmurs?welcome=personality');
    } catch (error) {
      document.getElementById('reward-status').textContent = error.message || '暂时无法连接领取服务，请稍后重试。';
      const dialog = document.getElementById('badge-claim-dialog');
      if (!dialog.open) dialog.showModal();
      document.getElementById('badge-claim-title').focus({preventScroll:true});
    } finally {
      busy = false;
      for (const item of buttons) { item.disabled = false; delete item.dataset.claiming; item.removeAttribute('aria-busy'); item.textContent = '领取并佩戴勋章'; }
    }
  });
  window.addEventListener('pagehide', () => observer?.disconnect());
})();
