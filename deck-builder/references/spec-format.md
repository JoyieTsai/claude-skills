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
    { "layout": "Thank you", "title": "謝謝" }
  ]
}
```

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
| `notes` | string | 講者備註。務必寫——論述就活在這裡 |

`bullets`／`paragraphs`／`table` 每頁只能選一個。`image` 可與其中任一併用。

## `style: "recommended"` 的版面名稱

`title`、`section`、`content`、`two-column`、`image-right`、`image-full`、`table`、
`quote`、`closing`。未知名稱會以 `content` 呈現並警告（與樣板風格不同——在樣板風格下，
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
- 在只有標題的版面上使用 `bullets` → 會於 (0.92, 1.60, 11.50, 4.80) 吋加一個文字框。
  同時有圖片時，文字框縮到 6.10 吋寬。
- BODY placeholder 裝不下內容時會被**放大**，上限是 y = 6.85 吋的頁尾列。
  `Content with image - right` 的 BODY 只有 0.48 吋高（圖說欄位），否則三條要點會無聲溢出。
- 沒填內容的 placeholder 會被**刪除**，這樣使用者打開來編輯時不會看到「Click to add text」。
- 超過 8 條要點，或任一條超過約 120 字元 → 警告，不是錯誤。應該回頭修大綱，而不是讓它溢出。
- 圖片路徑不存在、同一頁同時有 `bullets`+`table`、或 `--out` 等於樣板本身 → 硬錯誤。
- `--out` 已存在 → 硬錯誤，除非加 `--force`。
- 文字以 **run** 寫入並設好 `a:ea`／`a:cs`，中文才會正確呈現。
- `[待補: …]`／`[TODO…]` 標記在 build 階段只警告，但在 `verify_deck.py` 是**錯誤**——
  所以未完成的簡報可以建出來檢視，但絕不會被悄悄交出去。
