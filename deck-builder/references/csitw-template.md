# CSITW 樣板 — 已驗證規格

**檔案：**內建於 `assets/csitw-template.pptx`（7.4 MB · 11 頁 · **11 個版面** ·
14 個媒體檔），`style: "csitw"` 時使用。台灣實體（CSITW）簡報用這份，不要跟 CSI
（美國／全球）的 `company-template.pptx` 搞混——**版面名稱不同**。

以下從 `scripts/inspect_template.py` 讀出。檔案一更新就重跑 inspect，不要盲信這一頁。

**頁面尺寸：**13.333 × 7.5 吋（16:9）。

**結尾頁地址：**`Suite E, 11F., No.101, Songren Rd., Xinyi Dist., Taipei…`（Thank you 版面燒進去的，預設原樣保留）。

---

## 品牌色

Theme 仍是原廠 Office 預設；真正色票在 slide／layout 圖形裡：

| Hex | 用途 |
|---|---|
| `#0d63ba` | 主藍 |
| `#0b539d` | 深藍 |
| `#13182c` | 近黑內文 |
| `#e7e6e6` | 淺灰面板 |
| `#b4b4b4` | 中灰／次要 |
| `#ff737f` | 警示紅（少用） |

與 CSI 樣板同色系，兩種實體簡報並排也不衝突。

## 字體

Segoe UI、Verdana、Lato 為主；有少量**微軟正黑體**（CSITW 才有）。內文仍建議明確設
CJK 字型（見 SKILL／spec 的 fonts）。

---

## 版面一覽

| # | 名稱（樣板檔） | 大綱應寫 | 何時用 | 深底？ |
|---|---|---|---|---|
| 0 | `Cover` | **`Cover`** | 封面（樣板檔仍叫 Title；大綱一律寫 Cover，避免跟 CSI 段落頁搞混） | ● |
| 1 | `Agenda` | `Agenda` | 議程——自動填段落大標＋頁碼 | |
| 2 | `Project plan` | `Project plan` | 備用標題頁（專案計畫底圖；一般標題頁請用 `Headings_simple`） | ● |
| 3 | `Title` | **`Headings_simple`** | **預設**純文字標題頁／段落分隔 | ● |
| 4 | `Headings_Custom Photo` | `Headings_Custom Photo` | 段落分隔＋可換照片 | ● |
| 5 | `Headings_Public Safety_1` | `Headings_Public Safety_1` | 段落分隔（公共安全底圖） | ● |
| 6 | `Headings_Cloud Integration` | `Headings_Public Safety_1` | 與 #5 文字排版相同，預設合併 | ● |
| 7 | `Comparison chart` | `Content_heading_simple` | 內容頁（預設合併到主力內容） | |
| 8 | `Table` | `Content_heading_simple` | 內容頁（預設合併到主力內容） | |
| 9 | `Content_heading_simple` | `Content_heading_simple` | **主力內容頁** | |
| 10 | `Thank you` | `Thank you` | 結尾——預設原樣保留 | ● |

Builder 在沒有名為 `Cover` 的版面時，會把大綱的 `Cover` 對到樣板的 `Title`。
**不要**在 CSITW 大綱寫 `Title`——那在 CSI 是段落分隔頁。

**合併後約 8 個獨立排版：**`Headings_Cloud Integration` → `Headings_Public Safety_1`；
`Table`／`Comparison chart` → `Content_heading_simple`。要保留特定底圖時設
`"collapse_layouts": false`。

---

## 與 CSI 樣板的名稱對照

寫大綱時**必須用當前 style 的真實版面名**。不要把 CSI 名稱套到 CSITW。

| 用途 | CSI（`style: "csi"`／`"company"`） | CSITW（`style: "csitw"`） |
|---|---|---|
| 封面 | **`Cover`** | **`Cover`**（樣板檔內部名仍是 `Title`；大綱寫 Cover） |
| 議程 | `Agenda` | `Agenda` |
| 段落分隔（純文字） | `Title` | **`Headings_simple`**（預設；`Project plan` 僅備用） |
| 段落分隔＋照片 | `Headings_Custom Photo` | `Headings_Custom Photo` |
| 段落分隔＋圖 | `Headings_Img` | `Headings_Public Safety_1`（或 Cloud） |
| 主力內容 | `Content Heading` | `Content_heading_simple` |
| 深底強調 | `Content Heading Dark` | （無對應——用深底段落頁或 `recommended`） |
| 圖文右／左／中 | `Content with image - *` | （無——改 `Content_heading_simple` + image，或 `recommended` 的 `image:*`） |
| 結尾 | `Thank you` | `Thank you` |

CSITW **沒有** `Content Heading Dark`、也沒有三個 image-split 版面。需要那些構圖時改用
`style: "recommended"`，或接受在 `Content_heading_simple` 上由 builder 排圖。

---

## 選用時機

| 情境 | 用 |
|---|---|
| 台灣客戶、標案、CSITW 對外 | `csitw` |
| 台灣對內（管理層／跨部門）且要公司版面 | `csitw` |
| 美國／全球 CSI 品牌 | `csi`（或舊名 `company`） |
| 版面要更自由、或不符公共安全框架 | `recommended` |
