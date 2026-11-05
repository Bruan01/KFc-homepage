(() => {
  'use strict';
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  window.KflowRegistrationReward = {
    show(reward = {}, destination = '/') {
      const dialog = node('dialog', '', 'registration-reward');
      dialog.setAttribute('aria-labelledby', 'registration-reward-title');
      const title = node('h2', '欢迎加入 KFlow'); title.id = 'registration-reward-title';
      const close = node('button', '×', 'registration-reward-close');
      close.type = 'button'; close.setAttribute('aria-label', '继续前往原页面');
      close.onclick = () => location.assign(destination);
      const amount = Math.max(0, Number(reward.points) || 0);
      const earned = node('p', amount ? `${amount} K 积分已到账` : '账号已创建', 'registration-reward-earned');
      earned.setAttribute('role', 'status');
      dialog.append(close, node('p', '注册成功', 'registration-reward-eyebrow'), title, earned,
        node('p', '积分可以用来探索自己，也能把日常变成一张新作品。', 'registration-reward-note'));
      const uses = node('div', '', 'registration-reward-uses');
      for (const [name, href, cost, description] of [
        ['心映 · MBTI 测评', '/personality', reward.personality_cost, '认识自己的偏好，领取人格勋章'],
        ['显影 · AI 生图', '/imaging', reward.imaging_cost, '描述灵感，或上传照片进行创作'],
      ]) {
        const link = node('a', '', 'registration-reward-use'); link.href = href;
        link.append(node('strong', name), node('span', Number.isFinite(Number(cost)) ? `${Number(cost)} K / 次` : '查看当前费用'), node('small', description));
        uses.append(link);
      }
      dialog.append(uses);
      if (reward.first_post?.eligible && reward.first_post.points > 0) {
        const offer = node('p', `首条碎碎念还可获得 ${reward.first_post.points} K 积分。`, 'registration-reward-note');
        const link = node('a', '去社区打个招呼 →'); link.href = '/murmurs';
        offer.append(document.createElement('br'), link); dialog.append(offer);
      }
      const proceed = node('a', '继续前往原页面 →', 'registration-reward-continue'); proceed.href = destination;
      dialog.append(proceed);
      dialog.addEventListener('cancel', event => { event.preventDefault(); location.assign(destination); });
      document.body.append(dialog);
      if (dialog.showModal) dialog.showModal();
      else { dialog.setAttribute('open',''); dialog.classList.add('is-fallback'); }
      proceed.focus({preventScroll:true});
    },
  };
})();
