const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [390, 1440]) {
      for (const scenario of ['anonymous', 'expired', 'authenticated', 'home', 'report', 'settings']) {
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        const calls = [];
        await page.route('**/*', async route => {
          const url = new URL(route.request().url());
          const p = url.pathname;
          calls.push(p);
          if (p === '/login') return route.fulfill({ contentType: 'text/html', body: '<h1>登录</h1>' });
          if (p.startsWith('/api/')) {
            let data = {};
            let status = 200;
            if (p === '/api/user/me') data = { loggedIn: scenario !== 'anonymous' };
            if (p === '/api/personality/config') data = { enabled: true, ai_available: true, characters_ready: true };
            if (p === '/api/personality/assessments' || scenario === 'report' && p.startsWith('/api/personality/assessments/') || p === '/api/account/settings') {
              status = 401; data = { error: 'user login required' };
            }
            return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
          }
          const file = path.join(process.cwd(), p === '/personality/test' ? 'static/personality/test.html'
            : p.startsWith('/personality/report/') ? 'static/personality/report.html'
            : p === '/account/settings' ? 'static/account.html'
            : p === '/personality' ? 'static/personality/index.html' : p.startsWith('/static/') ? p.slice(1) : 'static' + p);
          if (fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file });
          return route.fulfill({ status: 404, body: '' });
        });
        // Serve a cached test shell directly, deliberately bypassing server redirects.
        const destination = scenario === 'home' ? '/personality' : scenario === 'report' ? '/personality/report/00000000-0000-0000-0000-000000000001?from=wechat' : scenario === 'settings' ? '/account/settings' : '/personality/test?from=wechat';
        await page.goto('https://kflow.test' + destination);
        if (scenario === 'expired') {
          await page.locator('#ai-consent').check();
          await page.locator('#begin').click();
        }
        if (['anonymous', 'expired', 'report', 'settings'].includes(scenario)) {
          await page.waitForURL('**/login?next=*');
          const next = new URL(page.url()).searchParams.get('next');
          assert.equal(next, destination);
          if (scenario === 'anonymous') assert(!calls.includes('/api/personality/config'));
        } else if (scenario === 'authenticated') {
          await page.locator('#ai-consent').waitFor();
          assert(new URL(page.url()).pathname === '/personality/test');
        } else {
          await page.locator('.history-empty-action').waitFor();
          assert(new URL(page.url()).pathname === '/personality');
        }
        console.log(`PASS ${width}px: ${scenario}`);
        await page.close();
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
