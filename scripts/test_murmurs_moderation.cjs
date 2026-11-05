const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { chromium } = require('playwright');
fs.mkdirSync('data/logs', { recursive: true });
const base = { id: 1, post_id: 1, author_username: 'author', content: '这里是待审核的内容。', status: 'pending', created_at: '2026-11-05T03:00:00+00:00', images: [], videos: [] };
const rows = [
  { ...base, moderation_kind: 'reports', reporter_username: 'reader', reason: 'spam' },
  { ...base, moderation_kind: 'appeals', appellant_username: 'author', target_type: 'post', reason: '请求复核', removed: true },
  { ...base, moderation_kind: 'features', requested_by: 'author', source: 'author' },
];
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [390, 1440]) for (const theme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
      await page.addInitScript(theme => localStorage.setItem('kflow-theme', theme), theme);
      const requests = [];
      await page.route('**/*', async route => {
        const url = new URL(route.request().url()), p = url.pathname;
        let data;
        if (p === '/api/murmurs/session') data = { profile: { username: 'reviewer', display_name: '审核员' }, can_moderate: true, can_tune_heat: true };
        else if (p === '/api/admin/me') data = { loggedIn: true, username: 'reviewer', adminLevel: 2 };
        else if (/^\/api\/admin\/murmurs\/(moderation|reports|appeals|features)$/.test(p)) {
          requests.push(url);
          const kind = p.split('/').pop(), status = url.searchParams.get('status');
          let items = rows.filter(row => kind === 'moderation' || row.moderation_kind === kind);
          if (status !== 'all' && status !== 'pending') items = [];
          data = { items, next_cursor: null };
        } else if (p.startsWith('/api/')) data = { items: [], counts: {}, total: 0 };
        if (data) return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });
        const file = path.join(process.cwd(), p === '/admin/murmurs' ? 'static/murmurs.html' : p.startsWith('/static/') ? p.slice(1) : 'static' + p);
        return fs.existsSync(file) && fs.statSync(file).isFile() ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
      });
      await page.goto('https://kflow.test/admin/murmurs');
      await page.waitForFunction(() => document.querySelectorAll('.mm-mod-card').length === 3);
      assert.equal(await page.locator('#mm-moderation-kind').inputValue(), 'all');
      assert.equal(await page.locator('#mm-report-status').inputValue(), 'all');
      assert.equal(requests.at(-1).pathname, '/api/admin/murmurs/moderation');
      assert((await page.locator('#mm-review-summary').innerText()).includes('3'));
      await page.locator('#mm-moderation-kind').selectOption('features');
      await page.waitForFunction(() => document.querySelectorAll('.mm-mod-card').length === 1);
      assert.equal(await page.locator('#mm-report-status').inputValue(), 'all');
      await page.locator('#mm-report-status').selectOption('rejected');
      await page.locator('.mm-review-empty').waitFor();
      assert((await page.locator('.mm-review-empty').innerText()).includes('没有符合条件'));
      await page.locator('#mm-reset-moderation').click();
      await page.waitForFunction(() => document.querySelectorAll('.mm-mod-card').length === 3);
      assert.equal(await page.locator('#mm-moderation-kind').inputValue(), 'all');
      assert.equal(await page.locator('#mm-report-status').inputValue(), 'all');
      assert(await page.locator('.mm-rail').isHidden());
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      if (theme === 'dark') assert.equal(await page.locator('.mm-main').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(10, 10, 10)');
      await page.screenshot({ path: `data/logs/murmurs-review-${theme}-${width}.png`, fullPage: false });
      await page.goto('https://kflow.test/admin/murmurs?mod=appeals&status=accepted');
      await page.locator('.mm-review-empty').waitFor();
      assert.equal(await page.locator('#mm-moderation-kind').inputValue(), 'appeals');
      assert.equal(await page.locator('#mm-report-status').inputValue(), 'accepted');
      console.log(`PASS ${width}px ${theme}: all defaults, combined queue, filters/reset, deep link, layout`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
