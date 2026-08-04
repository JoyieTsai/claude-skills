#!/usr/bin/env bash
# 為 uiux-audit skill 安裝可選的瀏覽器截圖依賴。
#
# Skill 的稽核功能不需要這一步——它只啟用 scripts/capture.mjs
#（多斷點截圖 + axe-core 掃描）。可從任何位置執行：
#
#   bash ~/.claude/skills/uiux-audit/install.sh
#
# 可安全重跑；已完成的步驟會略過。

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SKILL_DIR"

echo "uiux-audit skill → $SKILL_DIR"
echo

if ! command -v node >/dev/null 2>&1; then
  echo "✗ 找不到 node。請先安裝 Node 18+（https://nodejs.org 或 nvm），再重跑。"
  exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "✗ Node $NODE_MAJOR 太舊——capture.mjs 需要 18+（20+ 使用 import.meta.dirname）。"
  exit 1
fi
echo "✓ node $(node -v)"

echo
echo "→ 正在將 playwright + axe-core 安裝到 skill…"
npm install --silent --no-audit --no-fund

# Playwright 每個版本綁定精確的瀏覽器 build；過期的 ms-playwright 快取
# 會在啟動時因 build 編號不符而失敗。讓 playwright 決定它需要什麼。
echo
echo "→ 下載對應的 chromium build（約 100MB，已存在則略過）…"
npx --yes playwright install chromium

echo
echo "→ 驗證中…"
node -e '
const { createRequire } = require("module");
const r = createRequire(process.cwd() + "/package.json");
const pw = require(r.resolve("playwright"));
if (!pw.chromium) { console.error("✗ playwright 已解析但缺少 chromium"); process.exit(1); }
console.log("  ✓ playwright " + require(r.resolve("playwright/package.json")).version);
console.log("  ✓ axe-core " + require(r.resolve("axe-core/package.json")).version);
'

# 確認瀏覽器真的能啟動——這是我們最想在這裡抓到的失敗模式。
node -e '
const { createRequire } = require("module");
const r = createRequire(process.cwd() + "/package.json");
const { chromium } = require(r.resolve("playwright"));
chromium.launch().then(async b => { await b.close(); console.log("  ✓ chromium 可啟動"); })
  .catch(e => { console.error("  ✗ chromium 啟動失敗：\n" + e.message); process.exit(1); });
'

echo
echo "完成。Skill 已就緒，包含即時瀏覽器截圖。"
