import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { chromium } from 'playwright';


const ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
};


async function startServer() {
  const server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url, 'http://local').pathname);
      const path = resolve(ROOT, `.${pathname}`);
      if (!path.startsWith(ROOT) || !(await stat(path)).isFile()) {
        response.writeHead(404).end();
        return;
      }
      response.setHeader('Access-Control-Allow-Origin', '*');
      response.setHeader('Cache-Control', 'no-store');
      response.setHeader('Content-Type', TYPES[extname(path)] || 'application/octet-stream');
      response.end(await readFile(path));
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  return {
    server,
    origin: `http://127.0.0.1:${server.address().port}`,
  };
}


function mockBridgeScript() {
  return `
    (() => {
      const sid = 'a:test';
      const other = 'z:other';
      let counter = 1;
      const state = {
        universal: {
          [sid]: [
            { content: '原通用', proficiency: 10, confirmed_rounds: 1, last_updated: 2 },
            { content: ' 原通用 ', proficiency: 12, confirmed_rounds: 2, last_updated: 3 },
          ],
          [other]: [],
        },
        contextual: {
          [sid]: [{ scene: '原场景', behavior: '原行为', created_at: 2 }],
          [other]: [{ scene: '其他场景', behavior: '其他行为', created_at: 1 }],
        },
        specific: {
          [sid]: [{ content: '原梗', trigger_regex: '(?i)rjw', trigger_count: 1 }],
          [other]: [{ content: '<img src=x onerror="window.__XSS=1">', trigger_regex: 'x', trigger_count: 2 }],
        },
        session_names: {
          [sid]: '开发讨论群',
          [other]: '产品反馈群',
        },
        revisions: {
          universal: { [sid]: 'u-1', [other]: 'u-2' },
          contextual: { [sid]: 'c-1', [other]: 'c-2' },
          specific: { [sid]: 's-1', [other]: 's-2' },
        },
      };
      const clone = (value) => JSON.parse(JSON.stringify(value));
      const contextHandlers = new Set();
      let context = { isDark: false, locale: 'zh-CN' };
      window.__MOCK = state;
      window.__LAYER_CALLS = [];
      window.__DEDUP_CALLS = [];
      window.__setTheme = (isDark) => {
        context = { ...context, isDark };
        contextHandlers.forEach((handler) => handler(clone(context)));
      };
      window.AstrBotPluginPage = {
        async ready() { return clone(context); },
        getContext() { return clone(context); },
        onContext(handler) { contextHandlers.add(handler); return () => contextHandlers.delete(handler); },
        async apiGet(path) {
          if (path === 'snapshot') return { status: 'ok', data: clone(state) };
          if (path === 'stats') return { status: 'ok', data: {
            total_sessions: 2, total_entries: 5, injection_enabled: true,
            caps: { universal: 10, contextual: 150, specific: 200 },
          } };
          throw new Error('unknown GET');
        },
        async apiPost(path, body) {
          if (path === 'layer') {
            window.__LAYER_CALLS.push(body.layer);
            if (state.revisions[body.layer][body.sid] !== body.base_revision) {
              return { status: 'error', message: 'revision_conflict', data: { code: 'revision_conflict' } };
            }
            state[body.layer][body.sid] = clone(body.entries);
            const revision = body.layer + '-' + (++counter);
            state.revisions[body.layer][body.sid] = revision;
            return { status: 'ok', data: { saved: true, entries: clone(body.entries), revision } };
          }
          if (path === 'clear') {
            for (const layer of ['universal', 'contextual', 'specific']) state[layer][body.sid] = [];
            return { status: 'ok', data: { cleared: true } };
          }
          if (path === 'deduplicate') {
            window.__DEDUP_CALLS.push(body.sid);
            state.universal[body.sid] = state.universal[body.sid].slice(0, 1);
            return { status: 'ok', data: {
              removed: { universal: 1, contextual: 0, specific: 0 },
              total_removed: 1,
              specific_conflicts: 0,
            } };
          }
          if (path === 'learn') return { status: 'ok', data: { learned: true } };
          if (path === 'export') return { status: 'ok', data: { sid: body.sid } };
          throw new Error('unknown POST');
        },
      };
    })();
  `;
}


test('official sandbox boots and preserves critical workflows', { timeout: 45000 }, async () => {
  const { server, origin } = await startServer();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });

    const source = await readFile(resolve(ROOT, 'pages/style-manager/index.html'), 'utf8');
    const document = source
      .replace(
        '<link rel="stylesheet" href="./styles.css">',
        `<base href="${origin}/pages/style-manager/"><link rel="stylesheet" href="./styles.css">`,
      )
      .replace(
        '<script type="module" src="./src/app.js"></script>',
        `<script>${mockBridgeScript().replaceAll('</script>', '<\\/script>')}</script>`
          + '<script type="module" src="./src/app.js"></script>',
      );

    await page.setContent('<iframe id="app" title="plugin" sandbox="allow-scripts allow-forms allow-downloads"></iframe>');
    const iframe = page.locator('#app');
    await iframe.evaluate((element, html) => { element.srcdoc = html; }, document);
    const frame = page.frames().find((candidate) => candidate.parentFrame() === page.mainFrame());
    assert.ok(frame);
    await frame.waitForSelector('#curSid');
    assert.equal(await frame.locator('#curSid').textContent(), '开发讨论群');
    assert.equal(await frame.locator('#curSid').getAttribute('title'), 'a:test');
    assert.equal(await frame.locator('.session-item').first().locator('.session-id').textContent(), '开发讨论群');
    assert.equal(await frame.locator('.session-item').first().getAttribute('title'), 'a:test');

    await frame.getByRole('button', { name: '去重本会话' }).click();
    assert.match(await frame.locator('#mBody').textContent(), /安全重复/);
    await frame.locator('#mOk').click();
    await frame.waitForFunction(() => window.__MOCK.universal['a:test'].length === 1);
    assert.deepEqual(await frame.evaluate(() => window.__DEDUP_CALLS), ['a:test']);

    await frame.evaluate(() => window.__setTheme(true));
    await frame.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await frame.locator('#btnTheme').click();
    assert.equal(await frame.locator('html').getAttribute('data-theme'), 'light');
    await frame.evaluate(() => window.__setTheme(true));
    assert.equal(await frame.locator('html').getAttribute('data-theme'), 'light');

    await frame.locator('#btnHelp').click();
    await frame.waitForFunction(() => document.activeElement?.id === 'helpClose');
    await page.keyboard.press('Escape');
    await frame.waitForFunction(() => !document.querySelector('#helpOv').open);
    assert.equal(await frame.evaluate(() => document.activeElement?.id), 'btnHelp');

    const otherSession = frame.getByRole('button', { name: /z:other/ });
    await otherSession.focus();
    await otherSession.press('Enter');
    assert.equal(await frame.locator('#curSid').textContent(), '产品反馈群');
    assert.equal(await frame.locator('#curSid').getAttribute('title'), 'z:other');
    assert.equal(await frame.locator('#ovPortrait').textContent(),
      '通用风格：（暂无）；情境提示：其他场景→其他行为；特定层数据：<img src=x onerror="window.__XSS=1">');
    assert.deepEqual(await frame.locator('.donut circle').evaluateAll((nodes) =>
      nodes.slice(1).map((node) => node.getAttribute('stroke'))
    ), ['var(--c-contextual)', 'var(--c-specific)']);
    assert.equal(await frame.locator('img').count(), 0);
    assert.equal(await frame.evaluate(() => window.__XSS), undefined);

    const firstSession = frame.getByRole('button', { name: /a:test/ });
    await firstSession.focus();
    await firstSession.press('Space');
    assert.equal(await frame.locator('#curSid').textContent(), '开发讨论群');

    await frame.getByRole('tab', { name: '特定' }).click();
    const specificRegex = frame.locator('input.mono').first();
    assert.equal(await specificRegex.inputValue(), '(?i)rjw');
    assert.equal(await specificRegex.evaluate((input) => input.classList.contains('invalid')), false);

    const overviewTab = frame.getByRole('tab', { name: '总览' });
    await overviewTab.focus();
    await overviewTab.press('ArrowRight');
    assert.equal(await frame.getByRole('tab', { name: '通用' }).getAttribute('aria-selected'), 'true');

    await frame.getByPlaceholder('风格描述，如：语气活泼、爱用短句').first().fill('新通用');
    await frame.getByRole('tab', { name: '情境' }).click();
    await frame.getByPlaceholder('场景，如：有人发消息').first().fill('新场景');
    await frame.getByRole('button', { name: '去重本会话' }).click();
    assert.deepEqual(await frame.evaluate(() => window.__DEDUP_CALLS), ['a:test']);
    await frame.getByRole('button', { name: '保存全部' }).click();
    await frame.waitForFunction(() => !document.querySelector('#dirtyBanner').classList.contains('show'));
    assert.deepEqual(await frame.evaluate(() => ({
      universal: window.__MOCK.universal['a:test'][0].content,
      contextual: window.__MOCK.contextual['a:test'][0].scene,
    })), { universal: '新通用', contextual: '新场景' });
    assert.deepEqual(await frame.evaluate(() => window.__LAYER_CALLS), ['universal', 'contextual']);

    await frame.getByRole('button', { name: '清空本会话' }).click();
    assert.equal(await frame.evaluate(() => document.activeElement.id), 'mCancel');
    await page.keyboard.press('Enter');
    assert.equal(await frame.evaluate(() => document.querySelector('#overlay').open), false);
    assert.equal(await frame.evaluate(() => window.__MOCK.universal['a:test'].length), 1);

    await frame.getByRole('tab', { name: '通用' }).click();
    await frame.getByPlaceholder('风格描述，如：语气活泼、爱用短句').first().fill('未保存旧值');
    await frame.getByRole('button', { name: '清空本会话' }).click();
    assert.match(await frame.locator('#mBody').textContent(), /本地未保存修改也会丢弃/);
    await frame.locator('#mOk').click();
    await frame.waitForFunction(() => !document.querySelector('#dirtyBanner').classList.contains('show'));
    assert.deepEqual(await frame.evaluate(() => ({
      universal: window.__MOCK.universal['a:test'],
      contextual: window.__MOCK.contextual['a:test'],
      specific: window.__MOCK.specific['a:test'],
    })), { universal: [], contextual: [], specific: [] });
    await frame.waitForFunction(() =>
      document.querySelector('[data-tab="overview"]').getAttribute('aria-selected') === 'true'
    );
    await frame.getByRole('tab', { name: '通用' }).click();
    assert.equal(await frame.locator('input').evaluateAll((inputs) =>
      inputs.filter((input) => input.value === '未保存旧值').length
    ), 0);

    for (const width of [320, 768, 1280]) {
      await iframe.evaluate((element, value) => { element.style.width = `${value}px`; }, width);
      const overflow = await frame.evaluate(() => ({
        client: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth,
        tabRight: document.querySelector('[data-tab="specific"]').getBoundingClientRect().right,
      }));
      assert.equal(overflow.scroll, overflow.client, `horizontal overflow at ${width}px`);
      assert.ok(overflow.tabRight <= overflow.client, `tab overflow at ${width}px`);
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise((resolveClose) => server.close(resolveClose));
  }
});
