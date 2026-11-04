const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = process.cwd();
fs.mkdirSync(path.join(root, 'data/logs'), { recursive: true });
const users = [
  {id: 1, username: 'real_user', email: 'real@example.com', created_at: '2026-01-01', download_count: 5, request_count: 0, is_subscribed: true},
  {id: 2, username: 'system_user', is_system_generated: true, created_at: '2026-02-01', download_count: 0, request_count: 1},
];
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    for (const width of [375, 844, 1440]) {
      const context = await browser.newContext({viewport: {width, height: 950}, reducedMotion: 'reduce'});
      const page = await context.newPage(), errors = [], requests = [];
      page.on('pageerror', e => errors.push(e.message));
      const configs = {forum: {enabled: true, admin_only: false}, murmurs: {enabled: true, admin_only: false}};
      await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url()), p = url.pathname;
        let data;
        if (p === '/api/admin/me') data = {loggedIn: true, isSuper: true, adminLevel: 3, username: 'root'};
        else if (p === '/api/admin/community/official') data = {settings:{follower_count:0, managed_follower_count:0, other_follower_count:0, target_follower_count:0, max_target:10000},candidates:[]};
        else if (p === '/api/admin/community-ai/settings') data = {settings:{enabled:false, worker_alive:true, model:'', base_url:'', persona:'', knowledge:'', today_requests:0, daily_limit_total:0, daily_limit_per_user:0, min_interval_seconds:0}};
        else if (p === '/api/admin/users') {
          requests.push(url.searchParams.toString());
          let items = users.filter(u => url.searchParams.get('account_type') !== 'real' || !u.is_system_generated);
          if (url.searchParams.get('q')) items = items.filter(u => u.username.includes(url.searchParams.get('q')));
          data = {items, count: items.length, total: users.length};
        } else if (/\/api\/admin\/(forum|murmurs)\/heat\/settings/.test(p)) {
          const kind = p.split('/')[3];
          if (req.method() === 'POST') Object.assign(configs[kind], JSON.parse(req.postData()));
          data = {settings: configs[kind]};
        } else if (p === '/api/users/mentions') data = {items: [
          {username:'picture', display_name:'大图片用户', avatar_url:'/fixture-avatar.png'},
          {username:'missing', display_name:'图片失效用户', avatar_url:'/missing-avatar.png'},
          {username:'initial', display_name:'无头像用户', avatar_url:''},
        ], next_cursor: null};
        else if (p.startsWith('/api/')) data = {items: [], counts:{alerts:0,feedback:0}};
        if (data) return route.fulfill({contentType:'application/json', body:JSON.stringify(data)});
        if (p === '/fixture-avatar.png') return route.fulfill({contentType:'image/svg+xml', body:'<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1200"><rect width="1800" height="1200" fill="#c03956"/></svg>'});
        if (p === '/missing-avatar.png') return route.fulfill({status:404,body:''});
        if (p === '/mention-fixture') return route.fulfill({contentType:'text/html', body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/forum.css"><link rel="stylesheet" href="/murmurs.css"><link rel="stylesheet" href="/community-editor.css"><script src="/community-editor.js" defer></script><style>body{padding:18px;background:white}textarea{width:90%;height:160px}</style><textarea id="test-input"></textarea><div id="tools"></div>'});
        let file = p === '/admin/users' || p === '/admin/settings' ? 'static/admin.html' : p.replace(/^\//, '');
        if (!file.startsWith('static/')) file = 'static/' + file;
        file = path.join(root, file);
        return fs.existsSync(file) && fs.statSync(file).isFile() ? route.fulfill({path:file}) : route.fulfill({status:404,body:''});
      });
      await page.goto('http://kflow.test/admin/users');
      await page.waitForFunction(() => document.querySelector('#userCount').textContent.includes('全部 2'));
      await page.locator('#userAccountType').selectOption('real');
      await page.waitForFunction(() => document.querySelectorAll('#userTableBody tr').length === 1);
      assert((await page.locator('#userTableBody').innerText()).includes('real_user'));
      await page.locator('#userSort').selectOption('downloads_desc');
      await page.waitForFunction(() => document.querySelector('#userFilterStatus').textContent.includes('已应用'));
      await page.locator('#userSearch').fill('none');
      await page.locator('#userFilters [type=submit]').click();
      await page.locator('#userTableBody').getByText('没有符合条件的用户', {exact:false}).waitFor();
      await page.locator('#userFilters [type=reset]').click();
      await page.waitForFunction(() => document.querySelectorAll('#userTableBody tr').length === 2);
      assert(requests.some(q => q.includes('sort=downloads_desc')));
      assert(!(await page.locator('#officialCommunityStatus').innerText()).includes('Cannot read'));
      await page.screenshot({path:`data/logs/community-users-${width}.png`,fullPage:true});
      await page.goto('http://kflow.test/admin/settings');
      await page.locator('#heatMurmurEnabled').waitFor({state:'visible'});
      await page.waitForFunction(() => document.querySelector('#heatMurmurViews').value === '300');
      await page.locator('#heatMurmurAdminOnly').check();
      await page.locator('#saveHeatMurmurBtn').click();
      await page.waitForFunction(() => document.querySelector('#heatMurmurStatus').textContent.includes('已保存'));
      assert.equal(configs.murmurs.admin_only, true);
      assert.equal(configs.forum.admin_only, false);
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#heatMurmurAdminOnly').checked);
      assert.equal(await page.locator('#heatForumAdminOnly').isChecked(), false);
      await page.screenshot({path:`data/logs/community-heat-${width}.png`,fullPage:true});
      await page.goto('http://kflow.test/mention-fixture');
      await page.waitForFunction(() => Boolean(window.KflowEditor));
      await page.evaluate(() => {
        const picker = window.KflowEditor.mentionPicker(document.querySelector('#test-input'), () => {}, () => false, 1000, message => {throw Error(message)});
        document.querySelector('#tools').append(picker.panel, picker.trigger);
      });
      await page.locator('#test-input').fill('@');
      await page.locator('.mm-mention-option').first().waitFor();
      await page.waitForFunction(() => document.querySelector('.ce-initial img')?.complete);
      assert(await page.locator('.mm-mention-picker > button').isHidden());
      const dimensions = await page.locator('.ce-initial').evaluateAll(nodes => nodes.map(n => ({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height})));
      for (const d of dimensions) {assert.equal(d.width,30);assert.equal(d.height,30);}
      await page.waitForFunction(() => [...document.querySelectorAll('.ce-initial')].some(n => n.textContent === '图'));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path:`data/logs/community-mentions-${width}.png`,fullPage:true});
      await page.locator('#test-input').press('Enter');
      assert.equal(await page.locator('#test-input').inputValue(), '@picture ');
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: user filters/sort/reset, heat save/reload, 30px avatars and keyboard mention`);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
