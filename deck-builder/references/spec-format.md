# 簡報 spec（JSON）

`build_deck.py` 讀一個 JSON 檔。請從**已確認的**大綱寫出來——不要把 spec 和大綱分開寫，
它們一定會走鐘。

```json
{
  "style": "company",
  "language": "zh-TW",
  "audience": "internal",
  "title": "Genie 2026 設計審核結果",
  "slides": [
    {
      "layout": "Cover",
      "title": "Genie 2026 設計審核",
      "subtitle": "無障礙與可用性稽核 · 2026-08-04"
    },
    {
      "layout": "Agenda",
      "title": "議程",
      "notes": "大標與頁碼由後面的段落分隔頁自動產生,不必寫 bullets"
    },
    {
      "layout": "Title",
      "title": "一、對比問題"
    },
    {
      "layout": "Content Heading",
      "title": "灰階文字有 5 個色階不符 WCAG AA",
      "bullets": [
        "#b4b4b4 於白底為 1.90:1,AA 要求 4.5:1",
        "影響全站說明文字與表單提示",
        "修法:灰階最淺止於 #767676"
      ],
      "notes": "這是 P0-1。若被追問成本,色票替換是 token 層級改動,約半天。"
    },
    {
      "layout": "Content with image - right",
      "title": "設施表格在 402px 寬度下溢出",
      "bullets": ["表格固定 640px", "行動版產生橫向捲動"],
      "image": "/abs/path/to/screenshot.png"
    },
    {
      "layout": "Content Heading",
      "title": "問題分佈",
      "table": {
        "headers": ["嚴重度", "數量", "處理時程"],
        "rows": [["P0", "2", "上線前"], ["P1", "7", "本週期"], ["P2", "6", "待辦"]]
      }
    },
    { "layout": "Thank you" }
  ]
}
```

`Thank you` 不給 `title`——它維持樣板原樣（自帶字樣與公司聯絡資訊）。

## 最上層

| Key | 必填 | 說明 |
|---|---|---|
| `template` | `custom` 必填 | 來源 `.pptx`／`.potx` 的絕對路徑。`company` 風格省略時，會從 `config.json` 或 `DECK_BUILDER_TEMPLATE` 解析（見 SKILL.md 的「設定」） |
| `style` | 是 | `company` \| `recommended` \| `custom` |
| `language` | 是 | `zh-TW` \| `en` \| `mixed`——決定 CJK 的 `a:ea` 字體 |
| `audience` | 否 | `external` \| `internal`——只寫進檔案內容屬性 |
| `title` | 否 | 核心屬性的標題 |
| `fonts` | 否 | `{"latin": "Segoe UI", "cjk": "Microsoft JhengHei"}`——這就是預設值，只有使用者另有要求才設 |
| `collapse_layouts` | 否 | 預設 `true`：文字排版相同的版面會併成一個。當某個版面的底圖**就是**你選它的理由時設為 `false` |
| `slides` | 是 | 有序陣列 |

**字體。** 英文用 Segoe UI（`a:latin`），中文用微軟正黑體／Microsoft JhengHei
（`a:ea` + `a:cs`）。兩者都寫在每一個 run 上，所以同一行的中英混排不必拆開也能正確呈現。
只要有任何 run 偏離，`verify_deck.py` 就會警告。

## 每一頁

| Key | 型別 | 說明 |
|---|---|---|
| `layout` | string \| int | 版面**名稱**（建議）或索引。名稱比對不分大小寫；未知名稱 → 報錯並列出有效名稱，絕不無聲 fallback |
| `title` | string | 填入 TITLE／CENTER_TITLE |
| `subtitle` | string | 版面有 SUBTITLE 時填入。推薦風格中也用作 `quote` 的出處行 |
| `bullets` | string[] | 內文。前置 `"  "`（兩個空格）代表第二層項目 |
| `paragraphs` | string[] | 同 `bullets` 但沒有項目符號——用於敘述文字 |
| `columns` | [string[], string[]] | **推薦風格，僅 `two-column`。** 兩組文字陣列 |
| `image` | string | 絕對路徑；版面有 PICTURE placeholder 就放進去，否則自行擺放並縮放至適合 |
| `caption` | string | **推薦風格，僅 `image-full`。** 圖片下方的來源／出處行 |
| `table` | object | `{headers: [], rows: [[]]}` |
| `chart` | object | **原生、可在 PowerPoint 編輯的圖表**（不是圖片）。欄位與選用準則見 `charts.md` |
| `entries` | object[] | **僅 `Agenda` 版面。** `[{"title": …, "page": …}]`，用來取代自動產生的議程 |
| `keep_closing` | bool | **僅 `Thank you` 版面。** 設 `false` 才會讓這頁照 spec 產生內容；預設維持樣板原樣 |
| `notes` | string | 講者備註。務必寫——論述就活在這裡 |

`bullets`／`paragraphs`／`table`／`chart` 每頁只能選一個，**唯一例外是 `chart` 可以和
`bullets`／`paragraphs` 同頁**——文字講「所以呢」，圖表是證據，自動排成左文右圖。
`image` 可與文字類欄位併用，但不能和 `chart` 併用（兩者搶同一塊版面）。

## `style: "recommended"` 的版面名稱

`title`、`section`、`content`、`two-column`、`image-right`、`image-full`、`table`、
`chart`、`chart-right`、`quote`、`closing`。未知名稱會以 `content` 呈現並警告（與樣板風格不同——在樣板風格下，
未知版面是硬錯誤，因為在那裡猜錯會無聲套上錯誤的 master 樣式）。

## 腳本會強制執行的規則

- 未知版面名稱（樣板風格）→ 硬錯誤。無聲套錯版面比 build 失敗更糟。
- **文字排版相同的版面會被併成一個。** 底圖會被忽略——同樣的標題與副標框，背後換一張照片，
  仍是同一個版面。公司樣板的 13 個版面變成 11 個：`Table` 與 `Comparison chart` 都會轉到
  `Content Heading`。每次轉址都會警告。當特定底圖就是重點時，設 `"collapse_layouts": false`
  以保留所有版面。這是從檔案算出的，所以使用者提供的樣板也一樣處理。
- **深色背景不是「底圖」——它是版面的一部分。** `Content Heading Dark` 的幾何與
  `Content Heading` 相同但仍保持獨立，而在那六個深底版面上，builder 自己加入的文字會翻成
  `#ffffff`（副標 `#e7e6e6`）。絕不要在使用這些版面的頁面上手動指定深色；`verify_deck.py`
  是對照真實背景量對比度，會直接判為錯誤。
- **`Thank you` 頁維持樣板原樣。** 那個版面自帶「Thank you」字樣與公司地址／電話／網址，
  所以這頁不從 spec 產生任何內容——只把版面自己的標題文字複製到頁面上（PowerPoint 把版面
  placeholder 的文字當提示，不會自動帶過來），其餘都不動。給了 `title` 等欄位會被忽略並警告。
  要改就在該頁設 `"keep_closing": false`。名稱為 `Thank you`／`Thanks`／`Closing` 的版面
  同樣受保護。
- **`Agenda` 頁自動列出所有段落大標與頁碼。** 內容取自各段落分隔頁（`Title`、`Headings_*`）
  的標題與它們實際的頁次，填進版面的兩個 BODY placeholder：左欄大標、右欄頁碼（靠右對齊）。
  沒有分隔頁時，退回列出除封面與結尾外所有有標題的頁。手寫的 `bullets` 會被忽略並警告；
  要完全自訂就用 `"entries": [{"title": "一、對比問題", "page": 3}]`。超過 8 項會警告，
  因為框裝不下。
- **標題換行會警告。** 依該版面實際的框寬與字級量測（`Cover` 46pt/10.00 吋、內容版面
  32pt/11.50 吋），約超過 20 個中文字就會換行。標題必須是一句能放在一行的簡潔句子。
- 在只有標題的版面上使用 `bullets` → 會於 (0.92, 1.60, 11.50, 4.80) 吋加一個文字框。
  同時有圖片時，文字框縮到 6.10 吋寬。
- BODY placeholder 裝不下內容時會被**放大**，上限是 y = 6.85 吋的頁尾列。
  `Content with image - right` 的 BODY 只有 0.48 吋高（圖說欄位），否則三條要點會無聲溢出。
- 沒填內容的 placeholder 會被**刪除**，這樣使用者打開來編輯時不會看到「Click to add text」。
- 超過 8 條要點，或任一條超過約 120 字元 → 警告，不是錯誤。應該回頭修大綱，而不是讓它溢出。
- 圖片路徑不存在、同一頁同時有 `bullets`+`table`、`chart`+`table`、`chart`+`image`、
  或 `--out` 等於樣板本身 → 硬錯誤。
- **圖表是原生 `c:chart` 部件**，資料存在內嵌工作表裡，使用者點下去就能改數字、換類型。
  形式與色票的選用準則、以及 pptx 做不到的兩件事（圓角資料端、hover 層），見 `charts.md`。
  硬錯誤：數列超過 8 個（色相永不循環）、少於 3 片的圓餅。深底版面放圖表在 build 階段警告、
  在 `verify_deck.py` 是錯誤——那個導覽藍上所有色票都低於 3:1，實測過。
- `--out` 已存在 → 硬錯誤，除非加 `--force`。
- 文字以 **run** 寫入並設好 `a:ea`／`a:cs`，中文才會正確呈現。
- `[待補: …]`／`[TODO…]` 標記在 build 階段只警告，但在 `verify_deck.py` 是**錯誤**——
  所以未完成的簡報可以建出來檢視，但絕不會被悄悄交出去。
