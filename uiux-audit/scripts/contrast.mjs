#!/usr/bin/env node
// WCAG 2.1 對比比值計算器。
// 用這個，不要用估計——目測對比主張經常是錯的。
//
//   node contrast.mjs "#767676" "#ffffff"
//   node contrast.mjs "rgb(118,118,118)" white
//   node contrast.mjs "#888" "#fff" --size 24 --bold      # 大字門檻
//   node contrast.mjs --pairs "#333 #fff, #999 #fff, #06c #fff"

const NAMED = {
  white: '#ffffff', black: '#000000', red: '#ff0000', green: '#008000',
  blue: '#0000ff', gray: '#808080', grey: '#808080', silver: '#c0c0c0',
  transparent: null,
};

function parseColor(input) {
  const s = String(input).trim().toLowerCase();

  if (s in NAMED) {
    if (NAMED[s] === null) throw new Error('無法對 "transparent" 計算對比 — 請改取合成後的顏色');
    return parseColor(NAMED[s]);
  }

  let m = s.match(/^#([0-9a-f]{3,8})$/);
  if (m) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = [...h].map(c => c + c).join('');
    if (h.length !== 6 && h.length !== 8) throw new Error(`無效的 hex：${input}`);
    const rgb = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return { rgb, a };
  }

  m = s.match(/^rgba?\(([^)]+)\)$/);
  if (m) {
    const parts = m[1].split(/[,\s/]+/).filter(Boolean);
    const rgb = parts.slice(0, 3).map(p =>
      p.endsWith('%') ? Math.round(parseFloat(p) * 2.55) : parseFloat(p));
    const a = parts[3] === undefined ? 1
      : (parts[3].endsWith('%') ? parseFloat(parts[3]) / 100 : parseFloat(parts[3]));
    return { rgb, a };
  }

  throw new Error(`無法辨識的顏色：${input}（請用 hex、rgb()，或基本名稱）`);
}

// sRGB 相對亮度，WCAG 2.1 §relative-luminance
function luminance([r, g, b]) {
  const lin = [r, g, b].map(v => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function composite(fg, bg) {
  if (fg.a >= 1) return fg.rgb;
  return fg.rgb.map((c, i) => Math.round(c * fg.a + bg.rgb[i] * (1 - fg.a)));
}

function ratio(fgIn, bgIn) {
  const fg = parseColor(fgIn), bg = parseColor(bgIn);
  if (bg.a < 1) {
    console.warn(`  注意：背景有透明度 ${bg.a} — 已合成到白色上；請取樣真實背景以提高準確度`);
    bg.rgb = composite(bg, { rgb: [255, 255, 255], a: 1 });
    bg.a = 1;
  }
  const fgRgb = composite(fg, bg);
  const [l1, l2] = [luminance(fgRgb), luminance(bg.rgb)].sort((a, b) => b - a);
  return { value: (l1 + 0.05) / (l2 + 0.05), composited: fg.a < 1 ? fgRgb : null };
}

function grade(r, { size = 16, bold = false } = {}) {
  const isLarge = size >= 24 || (bold && size >= 18.66);
  const need = { aa: isLarge ? 3 : 4.5, aaa: isLarge ? 4.5 : 7 };
  return {
    isLarge,
    text: r >= need.aaa ? 'AAA' : r >= need.aa ? 'AA' : 'FAIL',
    ui: r >= 3 ? 'PASS' : 'FAIL',      // WCAG 1.4.11 非文字對比
    need,
  };
}

function report(fg, bg, opts) {
  const { value, composited } = ratio(fg, bg);
  const g = grade(value, opts);
  const r = value.toFixed(2);
  const mark = g.text === 'FAIL' ? '✗' : '✓';

  console.log(`\n${mark} ${fg} on ${bg} → ${r}:1`);
  if (composited) console.log(`    前景合成為 rgb(${composited.join(', ')})`);
  console.log(`    文字（${opts.size}px${opts.bold ? ' 粗體' : ''}，${g.isLarge ? '大字' : '一般'}）：` +
              `${g.text}   AA 需 ${g.need.aa}:1，AAA 需 ${g.need.aaa}:1`);
  console.log(`    UI／邊框／focus ring（需 3:1）：${g.ui}`);
  if (g.text === 'FAIL') {
    console.log(`    → 不足：${(g.need.aa - value).toFixed(2)} — 加深前景或提亮背景`);
  }
  return g.text !== 'FAIL';
}

// ---- CLI ----
const argv = process.argv.slice(2);
const opts = { size: 16, bold: false };
const positional = [];
let pairs = null;

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--bold') opts.bold = true;
  else if (a === '--size') opts.size = parseFloat(argv[++i]);
  else if (a === '--pairs') pairs = argv[++i];
  else if (a === '-h' || a === '--help') { printHelp(); process.exit(0); }
  else positional.push(a);
}

function printHelp() {
  console.log(`WCAG 對比比值計算器

  node contrast.mjs <前景> <背景> [--size N] [--bold]
  node contrast.mjs --pairs "#333 #fff, #999 #fff"

門檻：一般文字 4.5:1（AA）／7:1（AAA）；大字（>=24px，或 >=18.66px 粗體）
3:1／4.5:1；UI 元件、邊框、圖示與 focus ring 3:1。`);
}

try {
  if (pairs) {
    let allPass = true;
    for (const p of pairs.split(',')) {
      const [fg, bg] = p.trim().split(/\s+/);
      if (!fg || !bg) { console.error(`略過格式錯誤的配對："${p.trim()}"`); allPass = false; continue; }
      allPass = report(fg, bg, opts) && allPass;
    }
    console.log('');
    process.exit(allPass ? 0 : 1);
  }

  if (positional.length < 2) { printHelp(); process.exit(2); }
  const ok = report(positional[0], positional[1], opts);
  console.log('');
  process.exit(ok ? 0 : 1);
} catch (e) {
  console.error(`錯誤：${e.message}`);
  process.exit(2);
}
