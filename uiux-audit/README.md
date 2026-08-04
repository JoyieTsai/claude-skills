# uiux-audit

稽核 UI/UX 品質，並產出依優先順序排列的發現報告。適用 [Claude Code](https://claude.com/claude-code) 與 [Cursor](https://cursor.com/docs/skills)。

兩種模式：

- **設計審查** — 指向圖片、PDF 或 Figma 匯出檔
- **專案稽核** — 靜態審查已實作的 UI 程式碼，可選搭配即時瀏覽器截圖與 axe-core 無障礙掃描

與技術棧無關：Vue/Nuxt/Vuetify、React/Tailwind、Bootstrap，或純 HTML/CSS 皆可。

## 安裝

此 skill 位於 `claude-skills` repo——完整 clone 步驟見該 repo 的 [README](../README.md)。Skill 本身約 70KB 的 Markdown 與兩個 Node 腳本；`node_modules/`（約 21MB）與 Playwright 瀏覽器快取（約 1.6GB）**不**納入版本控管，需在每台機器重新安裝。

### Cursor

個人全域（所有專案可用）：

```bash
mkdir -p ~/.cursor/skills
ln -s ~/claude-skills/uiux-audit ~/.cursor/skills/uiux-audit
```

僅單一專案（可 commit 給團隊）：

```bash
mkdir -p .cursor/skills
ln -s ~/claude-skills/uiux-audit .cursor/skills/uiux-audit
# 或直接複製／subtree 進 repo：cp -R ~/claude-skills/uiux-audit .cursor/skills/
```

在 Agent 對話輸入 `/uiux-audit`，或用自然語言觸發。也可到 Settings → Rules → Agent Decides 確認已載入。

> 若你已把本 repo 裝在 `~/.claude/skills/`，Cursor 通常也會直接讀到，不必再連結一份。

### Claude Code

把 repo clone 到 `~/.claude/skills/`（見上層 README）。用 `/skills` 確認 `uiux-audit` 在列表中。

### 啟用瀏覽器截圖（可選）

```bash
# 路徑依你實際安裝位置調整
bash ~/.cursor/skills/uiux-audit/install.sh
# 或
bash ~/.claude/skills/uiux-audit/install.sh
```

會把 `playwright` + `axe-core` 安裝到 skill 目錄，並下載對應的 Chromium。冪等——可安全重跑。

**除了 `scripts/capture.mjs` 之外，其餘功能不需此步驟。** 設計審查、程式碼稽核與 `contrast.mjs` 只需 Node。若不需要截圖可略過。

## 用法

用自然語言提問；skill 會自行決定套用哪種模式。在 Cursor 也可先打 `/uiux-audit` 再補需求。

```
/uiux-audit
審核這個設計 <attach image>
audit the login page of this project
檢查登入頁的無障礙與對比
```

**設計審查** — 附加或指向圖片、PDF 或 Figma 匯出檔。注意：Figma *連結* 無法讀取；請先匯出成 PNG/PDF。

**專案稽核** — 指定路由、元件或功能。縮小範圍比「稽核全部」好——後者只會產出浮淺報告。

若要即時瀏覽器證據，請先自行啟動開發伺服器再說——skill 不會擅自啟動你的專案。會在 360/768/1024/1440px 截圖並執行 axe-core。

輸出為 `UIUX-AUDIT.md`，發現依 P0–P3 分級。報告本身就是交付物；除非你接著要求修復，否則不會改程式碼。

## 需求

- **Node 20+** — `capture.mjs` 使用 `import.meta.dirname`。其餘功能 Node 18 即可。
- 其他不需要。無需全域安裝，無需 API key。

## 目錄結構

```
uiux-audit/
├── SKILL.md                     # Agent 遵循的工作流程
├── install.sh                   # 可選依賴安裝
├── references/
│   ├── rubric.md                # 12 個稽核維度與具體門檻
│   ├── design-review.md         # 設計檔模式
│   ├── code-audit.md            # 程式碼稽核模式、各技術棧備註
│   └── report-template.md       # 報告結構與 P0–P3 嚴重度量表
└── scripts/
    ├── contrast.mjs             # WCAG 對比計算器（無依賴）
    └── capture.mjs              # 截圖 + axe 掃描（需 install.sh）
```

## 日後修改注意

`capture.mjs` 裡有兩處容易踩雷：

- Playwright 的進入點是 CJS，所以 `import { chromium } from 'playwright'` 會得到 `undefined`。請用 `mod?.chromium ?? mod?.default?.chromium`。
- 每個 Playwright 版本綁定精確的瀏覽器 build。升級依賴後需再跑 `npx playwright install chromium`，否則會因 build 編號不符而啟動失敗。
