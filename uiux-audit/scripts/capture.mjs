#!/usr/bin/env node
// 在多個斷點對路由截圖，並執行 axe-core 無障礙掃描。
// 需要開發伺服器已在執行，且 Playwright 可用。
//
//   node capture.mjs --url http://localhost:3000 --routes /,/login --out ./.uiux-audit
//
// 選項：
//   --url      基底 URL（必要）
//   --routes   逗號分隔的路徑（預設 "/"）
//   --out      輸出目錄（預設 "./.uiux-audit"）
//   --widths   逗號分隔的視窗寬度（預設 360,768,1024,1440）
//   --full     整頁截圖而非僅視窗
//   --no-axe   略過無障礙掃描
//   --wait     載入後額外等待的毫秒數（預設 600）
//
// 輸出：<out>/<route>__<width>.png、<out>/axe-report.json、<out>/summary.md
// PNG 才是重點——之後用 Read 工具讀取它們。

import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';

const argv = process.argv.slice(2);
const opt = (name, def = null) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? def : argv[i + 1];
};
const flag = name => argv.includes(`--${name}`);

const baseUrl = opt('url');
if (!baseUrl || flag('help') || flag('h')) {
  console.log(`用法：node capture.mjs --url http://localhost:3000 [--routes /,/login] [--out ./.uiux-audit]
       [--widths 360,768,1024,1440] [--full] [--no-axe] [--wait 600]

請先啟動開發伺服器（npm run dev / nuxt dev / vite），再執行此腳本。`);
  process.exit(baseUrl ? 0 : 2);
}

const routes = (opt('routes', '/')).split(',').map(r => r.trim()).filter(Boolean);
const outDir = path.resolve(opt('out', './.uiux-audit'));
const widths = (opt('widths', '360,768,1024,1440')).split(',').map(Number).filter(n => n > 0);
const settle = Number(opt('wait', '600'));
const fullPage = flag('full');
const runAxe = !flag('no-axe');

// 先從專案解析依賴（專案鎖定優先），再從 skill 自己的
// node_modules。單獨用 `import` 只會從此檔向上搜尋，當 skill
// 位於 ~/.claude 時會找不到專案。
const require = createRequire(import.meta.url);
const skillRequire = createRequire(path.join(import.meta.dirname, '..', 'package.json'));
const projectRequire = createRequire(path.join(process.cwd(), 'package.json'));

async function resolveDep(spec, entry) {
  for (const req of [projectRequire, skillRequire, require]) {
    try {
      return await import(`file://${req.resolve(entry ?? spec)}`);
    } catch { /* try next */ }
  }
  return null;
}

let chromium;
for (const spec of ['playwright', '@playwright/test']) {
  const mod = await resolveDep(spec);
  // Playwright 以 CJS 發行：具名匯出不存在，`chromium` 掛在 default 上。
  chromium = mod?.chromium ?? mod?.default?.chromium;
  if (chromium) break;
}
if (!chromium) {
  console.error(`無法解析 Playwright。
在 skill 安裝：   (cd ${path.join(import.meta.dirname, '..')} && npm install)
或在專案安裝：    npm i -D playwright && npx playwright install chromium`);
  process.exit(3);
}

// axe-core 可選；優雅降級，不要讓整個截圖失敗。
let axeSource = null;
if (runAxe) {
  const { readFile } = await import('node:fs/promises');
  for (const req of [projectRequire, skillRequire, require]) {
    try {
      axeSource = await readFile(req.resolve('axe-core/axe.min.js'), 'utf8');
      break;
    } catch { /* try next */ }
  }
  if (!axeSource) console.warn('! 無法解析 axe-core — 略過無障礙掃描');
}

await mkdir(outDir, { recursive: true });

const slug = r => (r === '/' ? 'root' : r.replace(/^\//, '').replace(/[^\w.-]+/g, '_')) || 'root';

const browser = await chromium.launch();
const results = [];
const axeAll = {};
let failures = 0;

for (const route of routes) {
  const url = new URL(route, baseUrl).href;

  for (const width of widths) {
    const isMobile = width < 768;
    const context = await browser.newContext({
      viewport: { width, height: isMobile ? 800 : 900 },
      deviceScaleFactor: 2,
      isMobile,
      hasTouch: isMobile,
      // 觸發 reduced-motion 處理；也穩定截圖。
      reducedMotion: 'no-preference',
    });
    const page = await context.newPage();

    const consoleErrors = [];
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => consoleErrors.push(String(e.message || e)));

    const label = `${slug(route)}__${width}`;
    try {
      const resp = await page.goto(url, { waitUntil: 'networkidle', timeout: 30_000 });
      await page.waitForTimeout(settle);

      const file = path.join(outDir, `${label}.png`);
      await page.screenshot({ path: file, fullPage });

      // 缺少／有敵意的 viewport meta 會默默讓下方所有行動測量失效：
      // Chromium 退回約 980px 的版面視窗，於是什麼都不「overflow」，
      // 觸控目標看起來也沒問題。信任行動數字前先檢查。
      const viewportMeta = isMobile ? await page.evaluate(() => {
        const m = document.querySelector('meta[name="viewport" i]');
        if (!m) return { missing: true };
        const content = m.getAttribute('content') || '';
        const blocksZoom = /user-scalable\s*=\s*(no|0)/i.test(content)
          || /(maximum-scale)\s*=\s*(1(\.0+)?|0?\.\d+)\b/i.test(content);
        return {
          missing: false, content, blocksZoom,
          noDeviceWidth: !/width\s*=\s*device-width/i.test(content),
          layoutWidth: document.documentElement.clientWidth,
        };
      }) : null;

      // 橫向 overflow 在程式碼審查中看不見，且永遠是真 bug。
      const overflow = await page.evaluate(() => {
        const de = document.documentElement;
        const scrollW = Math.max(de.scrollWidth, document.body.scrollWidth);
        if (scrollW <= de.clientWidth + 1) return null;
        const culprits = [];
        for (const el of document.querySelectorAll('*')) {
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.right > de.clientWidth + 1) {
            culprits.push({
              tag: el.tagName.toLowerCase(),
              cls: (el.className && String(el.className).slice(0, 80)) || null,
              right: Math.round(r.right),
            });
            if (culprits.length >= 5) break;
          }
        }
        return { scrollWidth: scrollW, clientWidth: de.clientWidth, culprits };
      });

      // 過小的觸控目標 — WCAG 2.5.5 / Apple HIG 44px。
      const smallTargets = isMobile ? await page.evaluate(() => {
        const sel = 'a,button,input,select,textarea,[role=button],[role=link],[onclick],[tabindex]';
        const out = [];
        for (const el of document.querySelectorAll(sel)) {
          const r = el.getBoundingClientRect();
          const st = getComputedStyle(el);
          if (r.width === 0 || r.height === 0) continue;
          if (st.visibility === 'hidden' || st.display === 'none') continue;
          if (r.width < 44 || r.height < 44) {
            out.push({
              tag: el.tagName.toLowerCase(),
              text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40),
              size: `${Math.round(r.width)}x${Math.round(r.height)}`,
            });
          }
          if (out.length >= 20) break;
        }
        return out;
      }) : [];

      if (axeSource) {
        await page.addScriptTag({ content: axeSource });
        const axe = await page.evaluate(async () => {
          const r = await window.axe.run(document, {
            resultTypes: ['violations'],
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] },
          });
          return r.violations.map(v => ({
            id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
            count: v.nodes.length,
            nodes: v.nodes.slice(0, 5).map(n => ({
              target: n.target, html: (n.html || '').slice(0, 200), summary: n.failureSummary,
            })),
          }));
        });
        axeAll[label] = axe;
      }

      results.push({
        route, width, label, ok: true,
        status: resp?.status() ?? null,
        file: path.relative(process.cwd(), file),
        overflow, smallTargets, viewportMeta, consoleErrors: consoleErrors.slice(0, 10),
      });
      const vpBad = viewportMeta && (viewportMeta.missing || viewportMeta.noDeviceWidth || viewportMeta.blocksZoom);
      const bits = [
        vpBad ? 'VIEWPORT META 問題' : null,
        overflow ? `overflow ${overflow.scrollWidth}>${overflow.clientWidth}` : null,
        smallTargets.length ? `${smallTargets.length} 個過小目標` : null,
        axeAll[label]?.length ? `${axeAll[label].length} 條 axe 規則` : null,
        consoleErrors.length ? `${consoleErrors.length} 個 console 錯誤` : null,
      ].filter(Boolean);
      console.log(`✓ ${label}${bits.length ? '  — ' + bits.join(', ') : ''}`);
    } catch (e) {
      failures++;
      results.push({ route, width, label, ok: false, error: String(e.message || e) });
      console.error(`✗ ${label} — ${String(e.message || e).split('\n')[0]}`);
    } finally {
      await context.close();
    }
  }
}

await browser.close();

if (axeSource) {
  await writeFile(path.join(outDir, 'axe-report.json'), JSON.stringify(axeAll, null, 2));
}

// Markdown 索引，讓稽核能引用具體產物。
const lines = [
  `# 截圖摘要`, ``,
  `基底 URL：${baseUrl}`,
  `路由：${routes.join(', ')}`,
  `寬度：${widths.join(', ')}`,
  `截圖：${fullPage ? '整頁' : '視窗'} @2x`, ``,
  `## 自動化訊號`, ``,
  `這些是**線索，不是發現**——回報前請在截圖與原始碼中逐一驗證。`, ``,
];

for (const r of results) {
  lines.push(`### ${r.label}`);
  if (!r.ok) { lines.push(`- 載入失敗：${r.error}`, ''); continue; }
  lines.push(`- \`${r.file}\`${r.status && r.status >= 400 ? ` — HTTP ${r.status}` : ''}`);
  const vm = r.viewportMeta;
  if (vm?.missing) {
    lines.push(`- **沒有 \`<meta name="viewport">\`** — 頁面以約 ${vm.layoutWidth ?? 980}px`,
      `  的版面視窗渲染，並在手機上縮小。**因此下方的 overflow 與觸控目標檢查`,
      `  在此寬度沒有意義。** 修好 meta 標籤後再重新截圖。`);
  } else if (vm && (vm.noDeviceWidth || vm.blocksZoom)) {
    lines.push(`- **Viewport meta 問題：** \`${vm.content}\``);
    if (vm.noDeviceWidth) lines.push(`  - 缺少 \`width=device-width\` — 行動版面會錯；下方測量不可靠`);
    if (vm.blocksZoom) lines.push(`  - 阻擋雙指縮放（\`user-scalable=no\` / \`maximum-scale=1\`）— WCAG 1.4.4 失敗`);
  }
  if (r.overflow) {
    lines.push(`- **橫向 overflow：** ${r.overflow.scrollWidth}px 內容塞在 ${r.overflow.clientWidth}px 視窗`);
    for (const c of r.overflow.culprits) {
      lines.push(`  - \`<${c.tag}${c.cls ? ` class="${c.cls}"` : ''}>\` 延伸到 ${c.right}px`);
    }
  }
  if (r.smallTargets?.length) {
    lines.push(`- **觸控目標小於 44px：** ${r.smallTargets.length}`);
    for (const t of r.smallTargets.slice(0, 8)) {
      lines.push(`  - \`<${t.tag}>\` ${t.size}${t.text ? ` — "${t.text}"` : ''}`);
    }
  }
  const ax = axeAll[r.label] || [];
  if (ax.length) {
    lines.push(`- **axe 違規：** ${ax.length} 條規則，${ax.reduce((s, v) => s + v.count, 0)} 個節點`);
    for (const v of ax) lines.push(`  - [${v.impact}] \`${v.id}\` ×${v.count} — ${v.help}`);
  }
  if (r.consoleErrors?.length) {
    lines.push(`- Console 錯誤：${r.consoleErrors.length}`);
    for (const e of r.consoleErrors.slice(0, 3)) lines.push(`  - ${e.slice(0, 160)}`);
  }
  lines.push('');
}

lines.push(`## 下一步`, ``, `用 Read 工具讀取 PNG。自動化檢查無法`,
  `評估層級、間距節奏、文案品質，或流程是否合理。`, '');

await writeFile(path.join(outDir, 'summary.md'), lines.join('\n'));

console.log(`\n→ ${path.relative(process.cwd(), outDir)}/  (summary.md${axeSource ? ', axe-report.json' : ''}, ${results.filter(r => r.ok).length} 張 PNG)`);
if (failures) console.log(`  ${failures} 次截圖失敗 — 見 summary.md`);
process.exit(0);
