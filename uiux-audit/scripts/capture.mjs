#!/usr/bin/env node
// Screenshot routes at multiple breakpoints and run an axe-core accessibility scan.
// Requires a dev server already running, and Playwright available.
//
//   node capture.mjs --url http://localhost:3000 --routes /,/login --out ./.uiux-audit
//
// Options:
//   --url      base URL (required)
//   --routes   comma-separated paths (default "/")
//   --out      output dir (default "./.uiux-audit")
//   --widths   comma-separated viewport widths (default 360,768,1024,1440)
//   --full     full-page screenshots instead of viewport-only
//   --no-axe   skip the accessibility scan
//   --wait     extra ms to settle after load (default 600)
//
// Output: <out>/<route>__<width>.png, <out>/axe-report.json, <out>/summary.md
// The PNGs are the point — read them with the Read tool afterwards.

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
  console.log(`Usage: node capture.mjs --url http://localhost:3000 [--routes /,/login] [--out ./.uiux-audit]
       [--widths 360,768,1024,1440] [--full] [--no-axe] [--wait 600]

Start your dev server first (npm run dev / nuxt dev / vite), then run this.`);
  process.exit(baseUrl ? 0 : 2);
}

const routes = (opt('routes', '/')).split(',').map(r => r.trim()).filter(Boolean);
const outDir = path.resolve(opt('out', './.uiux-audit'));
const widths = (opt('widths', '360,768,1024,1440')).split(',').map(Number).filter(n => n > 0);
const settle = Number(opt('wait', '600'));
const fullPage = flag('full');
const runAxe = !flag('no-axe');

// Resolve deps from the project first (so a project pin wins), then from the skill's
// own node_modules. `import` alone only searches upward from this file, which misses
// the project when the skill lives in ~/.claude.
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
  // Playwright ships CJS: named exports are absent, `chromium` hangs off default.
  chromium = mod?.chromium ?? mod?.default?.chromium;
  if (chromium) break;
}
if (!chromium) {
  console.error(`Playwright not resolvable.
Install in the skill:   (cd ${path.join(import.meta.dirname, '..')} && npm install)
Or in the project:      npm i -D playwright && npx playwright install chromium`);
  process.exit(3);
}

// axe-core is optional; degrade gracefully rather than failing the whole capture.
let axeSource = null;
if (runAxe) {
  const { readFile } = await import('node:fs/promises');
  for (const req of [projectRequire, skillRequire, require]) {
    try {
      axeSource = await readFile(req.resolve('axe-core/axe.min.js'), 'utf8');
      break;
    } catch { /* try next */ }
  }
  if (!axeSource) console.warn('! axe-core not resolvable — skipping a11y scan');
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
      // Surfaces reduced-motion handling; also stabilises screenshots.
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

      // A missing/hostile viewport meta silently invalidates every mobile measurement
      // below: Chromium falls back to a ~980px layout viewport, so nothing "overflows"
      // and touch targets look fine. Check it before trusting the mobile numbers.
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

      // Horizontal overflow is invisible in code review and always a real bug.
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

      // Undersized touch targets — WCAG 2.5.5 / Apple HIG 44px.
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
        vpBad ? 'VIEWPORT META PROBLEM' : null,
        overflow ? `overflow ${overflow.scrollWidth}>${overflow.clientWidth}` : null,
        smallTargets.length ? `${smallTargets.length} small targets` : null,
        axeAll[label]?.length ? `${axeAll[label].length} axe rules` : null,
        consoleErrors.length ? `${consoleErrors.length} console errors` : null,
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

// Markdown index so the audit can cite specific artefacts.
const lines = [
  `# Capture summary`, ``,
  `Base URL: ${baseUrl}`,
  `Routes: ${routes.join(', ')}`,
  `Widths: ${widths.join(', ')}`,
  `Screenshots: ${fullPage ? 'full page' : 'viewport'} @2x`, ``,
  `## Automated signals`, ``,
  `These are **leads, not findings** — verify each in the screenshots and source before reporting.`, ``,
];

for (const r of results) {
  lines.push(`### ${r.label}`);
  if (!r.ok) { lines.push(`- LOAD FAILED: ${r.error}`, ''); continue; }
  lines.push(`- \`${r.file}\`${r.status && r.status >= 400 ? ` — HTTP ${r.status}` : ''}`);
  const vm = r.viewportMeta;
  if (vm?.missing) {
    lines.push(`- **No \`<meta name="viewport">\`** — the page renders at a ~${vm.layoutWidth ?? 980}px`,
      `  layout viewport and is scaled down on phones. **The overflow and touch-target checks`,
      `  below are therefore not meaningful at this width.** Fix the meta tag, then re-capture.`);
  } else if (vm && (vm.noDeviceWidth || vm.blocksZoom)) {
    lines.push(`- **Viewport meta problem:** \`${vm.content}\``);
    if (vm.noDeviceWidth) lines.push(`  - missing \`width=device-width\` — mobile layout will be wrong; measurements below are unreliable`);
    if (vm.blocksZoom) lines.push(`  - blocks pinch-zoom (\`user-scalable=no\` / \`maximum-scale=1\`) — WCAG 1.4.4 failure`);
  }
  if (r.overflow) {
    lines.push(`- **Horizontal overflow:** ${r.overflow.scrollWidth}px content in ${r.overflow.clientWidth}px viewport`);
    for (const c of r.overflow.culprits) {
      lines.push(`  - \`<${c.tag}${c.cls ? ` class="${c.cls}"` : ''}>\` extends to ${c.right}px`);
    }
  }
  if (r.smallTargets?.length) {
    lines.push(`- **Touch targets under 44px:** ${r.smallTargets.length}`);
    for (const t of r.smallTargets.slice(0, 8)) {
      lines.push(`  - \`<${t.tag}>\` ${t.size}${t.text ? ` — "${t.text}"` : ''}`);
    }
  }
  const ax = axeAll[r.label] || [];
  if (ax.length) {
    lines.push(`- **axe violations:** ${ax.length} rules, ${ax.reduce((s, v) => s + v.count, 0)} nodes`);
    for (const v of ax) lines.push(`  - [${v.impact}] \`${v.id}\` ×${v.count} — ${v.help}`);
  }
  if (r.consoleErrors?.length) {
    lines.push(`- Console errors: ${r.consoleErrors.length}`);
    for (const e of r.consoleErrors.slice(0, 3)) lines.push(`  - ${e.slice(0, 160)}`);
  }
  lines.push('');
}

lines.push(`## Next step`, ``, `Read the PNGs with the Read tool. Automated checks cannot`,
  `assess hierarchy, spacing rhythm, copy quality, or whether the flow makes sense.`, '');

await writeFile(path.join(outDir, 'summary.md'), lines.join('\n'));

console.log(`\n→ ${path.relative(process.cwd(), outDir)}/  (summary.md${axeSource ? ', axe-report.json' : ''}, ${results.filter(r => r.ok).length} PNGs)`);
if (failures) console.log(`  ${failures} capture(s) failed — see summary.md`);
process.exit(0);
