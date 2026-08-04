# 模式 B — 稽核已實作的專案

對真實 UI 程式碼做靜態審查。目標：錨定到 `file:line`、使用者能立刻採取行動的發現。

## 步驟 1 — 界定範圍

稽核大型應用的每個檔案只會產出浮淺報告。先縮小：

- 若使用者點名路由、元件或功能 → 稽核它與其依賴。
- 若沒有 → 詢問哪個介面重要，或選最高流量的進入點（登入、首頁／儀表板、主要列表、主要表單），並**說明你選了什麼**。

經驗法則：3–8 個畫面或 15–30 個元件才是真正的稽核。再多就是略讀——寧可在重要介面深挖，並說明跳過了什麼。

## 步驟 2 — 先讀設計系統，再讀元件

不知道標準就無法標記不一致。先讀設定：

```bash
# tokens / theme
fd -H -t f '(tailwind|vuetify|nuxt|vite)\.config\.(js|ts|mjs)$' -E node_modules
fd -H -t f '(variables|settings|theme|tokens|_vars)\.(s?css|less)$' -E node_modules
rg -n '^\s*(--[\w-]+|\$[\w-]+)\s*:' --glob '!node_modules' -g '*.{css,scss,less}' | head -60
```

記下間距尺度、字級尺度、色彩 token、圓角與陰影階梯。這些是維度 12 的比較基準。

## 步驟 3 — 掃描高訊號模式

這些 grep 能快速找到真 bug。每筆命中都要在脈絡中驗證——許多是假陽性。

```bash
# --- 無障礙：通常是真正 P0/P1 最密集的來源 ---
rg -n 'outline:\s*(none|0)' --glob '!node_modules'                 # 殺掉了 focus ring
rg -n '<img(?![^>]*\balt=)' -P --glob '!node_modules'              # 缺少 alt
rg -n 'onClick|@click' --glob '!node_modules' -g '*.{vue,jsx,tsx,html}' \
   | rg -v '<(button|a|input|select|textarea|v-btn|VBtn|NuxtLink|RouterLink)'  # 非語意可點擊
rg -n 'tabindex=["\x27]-?[1-9]' --glob '!node_modules'             # tabindex 技巧
rg -n 'placeholder=' --glob '!node_modules' -g '*.{vue,jsx,tsx,html}'  # 再檢查每個是否有真正標籤
rg -n 'aria-hidden' --glob '!node_modules'                         # 藏起可聚焦內容？
rg -n 'user-select:\s*none' --glob '!node_modules'

# --- 應為 token 的硬編碼值 ---
rg -n '#[0-9a-fA-F]{3,8}\b' --glob '!node_modules' -g '*.{vue,jsx,tsx,css,scss}' | head -50
rg -n ':\s*\d+px' --glob '!node_modules' -g '*.{css,scss,vue}' | head -60

# --- 版面脆弱性 ---
rg -n '\bwidth:\s*\d{3,}px|\bheight:\s*\d{3,}px' --glob '!node_modules'   # 固定尺寸
rg -n 'white-space:\s*nowrap|overflow:\s*hidden' --glob '!node_modules'
rg -n 'z-index:\s*\d{3,}' --glob '!node_modules'                   # 堆疊混亂
rg -n 'position:\s*absolute' --glob '!node_modules' -c             # 密度訊號

# --- 逃生艙 = 設計系統漂移 ---
rg -n '!important' --glob '!node_modules' -c
rg -n ':deep\(|::v-deep|/deep/' --glob '!node_modules'

# --- 缺少狀態 ---
rg -n 'v-if|useState|isLoading|loading' --glob '!node_modules' -g '*.{vue,jsx,tsx}' | head -40
rg -n 'await |\.then\(' --glob '!node_modules' -g '*.{vue,jsx,tsx}' | head -40
# ^ 對每個非同步呼叫：有載入狀態嗎？錯誤狀態？停用送出？

# --- 動態安全 ---
rg -n 'prefers-reduced-motion' --glob '!node_modules'   # 有動畫的應用缺少它就是發現
rg -n 'transition|animation' --glob '!node_modules' -g '*.{css,scss}' -c
```

若 `rg`/`fd` 不可用，退回 `grep -rn` / `find`。

## 步驟 4 — 認真讀元件

Grep 找症狀；閱讀找原因。對每個範圍內的元件，讀完整個檔案並檢查：

- **語意** — 正確的元素、標題層級正確、有地標。
- **全部五種互動狀態** — 尤其 focus。追蹤樣式從哪來；可能是全域的（`assets/main.css`、reset、UI 函式庫預設）。未檢查全域層就不要報告「沒有 focus 樣式」。
- **非同步完整性** — 對每個請求：載入指示、錯誤呈現、空結果、防重複送出。多數真正的 P1 住在這裡。
- **響應式行為** — 是否依賴固定寬度？360px 時會怎樣？
- **表單正確性** — 標籤關聯、`type`/`inputmode`/`autocomplete`、錯誤位置與宣告。
- **Token 使用 vs 硬編碼** — 對照步驟 2 的基準。

## 各技術棧備註

**Vue / Nuxt / Vuetify**
- Vuetify 大致免費提供無障礙與 focus 狀態——檢查是否被 `:deep()` 或 `!important` 覆寫。大量深層選擇器本身就是發現。
- 自訂元件上的 `v-model`：有處理 invalid／error 狀態嗎？
- 優先用 Vuetify 的 `density`、`variant`、`color` props，而非自訂 CSS；覆寫暗示選錯了元件。
- Nuxt：檢查 `<Head>`/`useHead` 的 `title` 與 `lang`；內部路由用 `<NuxtLink>` 而非裸 `<a>`。
- 留意 `v-html`（XSS 與未樣式化內容風險）。

**React / Tailwind**
- 長 utility 字串隱藏不一致——抽出並比較相鄰元件的實際值。兩個同角色卡片用 `p-4` 與 `p-5` 就是維度 12。
- 檢查任意值（`w-[327px]`、`text-[13px]`）——這些繞過尺度。
- `focus:outline-none` 卻沒有 `focus-visible:ring-*` 是 P0。
- 條件式 class 字串：確認每個分支都產出有效、對比足夠的結果——尤其停用與錯誤變體。
- 元件函式庫（Radix、Headless UI、shadcn）處理 focus trap 與 ARIA；手寫 modal／dropdown 通常沒有。確認你用的是哪種。

**Bootstrap**
- 確認 utility class 存在於使用的版本（v4 vs v5 改名很多：`ml-*` → `ms-*`、`.form-group` 移除）。打錯的 class 默默不做任何事——真實且隱形的 bug。
- `.sr-only`（v4）vs `.visually-hidden`（v5）。

**純 HTML/CSS**
- 檢查 reset／normalize 沒有剝掉 focus outline。
- 檢查存在 `<meta name="viewport" content="width=device-width, initial-scale=1">`，且未設 `maximum-scale=1` 或 `user-scalable=no`（阻擋縮放——無障礙失敗）。

## 步驟 5 — 可選的即時驗證

若應用可啟動，執行 `scripts/capture.mjs`（見 SKILL.md）。截圖抓住程式碼審查抓不到的：實際渲染間距、360px 的 overflow、真實計算對比，以及頁面是否真的像設計。

讀取產出的 PNG。交叉比對 axe 發現與靜態發現——一致提高信心；瀏覽器反證的靜態發現應刪除。

## 不要報告什麼

- 已全域處理但你沒檢查到的。
- 沒有使用者面向影響的程式碼品質問題（命名、檔案結構、死 CSS）——超出範圍；那是 code review。
- 把框架預設當成團隊的錯誤。
- 一長串硬編碼 hex 當成個別發現。合併為一項：「N 個硬編碼顏色繞過主題——這裡是最糟的 5 個與完整清單。」
