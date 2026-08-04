#!/usr/bin/env bash
# Bootstrap the uiux-audit skill's optional browser-capture dependencies.
#
# The skill's audit features work WITHOUT this — it only enables scripts/capture.mjs
# (multi-breakpoint screenshots + axe-core scanning). Run it from anywhere:
#
#   bash ~/.claude/skills/uiux-audit/install.sh
#
# Safe to re-run; skips work that is already done.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SKILL_DIR"

echo "uiux-audit skill → $SKILL_DIR"
echo

if ! command -v node >/dev/null 2>&1; then
  echo "✗ node not found. Install Node 18+ first (https://nodejs.org or nvm), then re-run."
  exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "✗ Node $NODE_MAJOR is too old — capture.mjs needs 18+ (uses import.meta.dirname on 20+)."
  exit 1
fi
echo "✓ node $(node -v)"

echo
echo "→ installing playwright + axe-core into the skill…"
npm install --silent --no-audit --no-fund

# Playwright pins an exact browser build per version; a stale ms-playwright cache
# fails at launch with a build-number mismatch. Let playwright decide what it needs.
echo
echo "→ downloading the matching chromium build (~100MB, skipped if present)…"
npx --yes playwright install chromium

echo
echo "→ verifying…"
node -e '
const { createRequire } = require("module");
const r = createRequire(process.cwd() + "/package.json");
const pw = require(r.resolve("playwright"));
if (!pw.chromium) { console.error("✗ playwright resolved but chromium missing"); process.exit(1); }
console.log("  ✓ playwright " + require(r.resolve("playwright/package.json")).version);
console.log("  ✓ axe-core " + require(r.resolve("axe-core/package.json")).version);
'

# Confirm a browser can actually launch — the failure mode we most want to catch here.
node -e '
const { createRequire } = require("module");
const r = createRequire(process.cwd() + "/package.json");
const { chromium } = require(r.resolve("playwright"));
chromium.launch().then(async b => { await b.close(); console.log("  ✓ chromium launches"); })
  .catch(e => { console.error("  ✗ chromium failed to launch:\n" + e.message); process.exit(1); });
'

echo
echo "Done. The skill is ready, including live browser capture."
