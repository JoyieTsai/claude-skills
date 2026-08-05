# 公司樣板 — 已驗證規格

**檔案：**由 `config.json` 的 `company_template` 或 `DECK_BUILDER_TEMPLATE` 環境變數指定
（本機為 `Slide Templete/Template B 12-13-2021.pptx`，1.9 MB · 13 頁 · **13 個版面** ·
1 個 master · 15 個內嵌媒體）。

以下每一項都是從實際檔案讀出來的，不是推測。可以當成 ground truth，但**檔案一變動就重跑**
`scripts/inspect_template.py`，不要相信這一頁。

⚠️ **樣板於 2026-08-05 被更新過**——從 26 頁／25 版面／14.8 MB 變成 13 頁／13 版面／
1.9 MB。12 個 `Headings_*` 產品線分隔頁，以及 `Project plan`／`Total Public Safety Solution`
都**已消失**；`Cover`、`Headings_Img`、`Content Heading Dark` 是**新增的**；
`Content_heading_simple` 現在叫 `Content Heading`。任何依舊名稱寫的 spec 都會直接報錯，
並列出目前有效的名稱。

**頁面尺寸：**13.333 × 7.5 吋（12192000 × 6858000 EMU）——16:9。

---

## 品牌色

⚠️ **theme 是原廠 Office 預設**（`ppt/theme/*.xml` 寫的是 Calibri Light／Calibri／
accent1 `#4472c4`）。那**不是**品牌色。真正的識別藏在 slide 與 layout 的圖形裡。
絕不要從 theme part 讀品牌色。

真實色票，依在 slides + layouts + master 中的出現次數排序：

| Hex | 次數 | 用途 |
|---|---|---|
| `#0d63ba` | 40 | **主藍**——標題、色塊、深底版面的背景 |
| `#0b539d` | 7 | 深藍——Cover／Thank you 背景、漸層末端 |
| `#13182c` | 3 | 近黑——內文 |
| `#e7e6e6` | 93 | 淺灰——面板填色、表格斑馬紋、深底上的副標 |
| `#b4b4b4` | 15 | 中灰——邊框、次要文字 |
| `#3f3f3f` | 1 | 深灰——圖說 |
| `#ffffff`／`#fcfcfc` | — | 背景，以及深底版面上的文字 |
| `#ff737f` | — | 強調紅——只用於真正的警示 |

`#0d63ba` 與 Genie-2026 設計檔的 `Main/Primary/50` 完全相同——同一套企業品牌，
所以簡報與產品 UI 可以並排展示。

**內文是 `#13182c`，不是純黑。** 白底上比 `#767676` 更淺的灰在內文尺寸下不符 WCAG AA，
所以 `#b4b4b4` 不要用在任何聽眾必須讀的內容上。

## 字體

依出現次數：**Segoe UI**（398）、Verdana（164）、Open Sans（132）、Lato（100）、
Arial（18）、Roboto（18）。使用中的字級：46、44、36、32、28、24、20、18、17、16、14、12、
11、10 pt。

**規則：英文用 Segoe UI（`a:latin`），中文用微軟正黑體／Microsoft JhengHei
（`a:ea` + `a:cs`）。** 兩者都寫進每一個 run，所以單一 run 也能正確呈現中英混排——
`build_deck.py` 會自動處理。少了 `a:ea`，中文會落到 renderer 隨機挑的 fallback 字體，
通常很醜。

⚠️ **master 的 `titleStyle` 仍把 `a:ea` 設成 Open Sans**，那是純拉丁字體
（更新後已重新驗證）。所以純靠繼承填入的標題，中文沒有可用字體。因此 `build_deck.py`
即使在樣板 placeholder 上也會寫入兩種字體，同時仍繼承其字級與顏色。

master 的 `bodyStyle` 依 outline level 混用 `+mn-lt`（theme minor latin → 原廠 Calibri）
與明寫的 Segoe UI——這是另一個不能靠繼承決定字體的理由。

## Master placeholder 幾何（吋）

| Placeholder | x | y | w | h |
|---|---|---|---|---|
| Title | 0.92 | 0.40 | 11.50 | 1.45 |
| Body | 0.92 | 2.00 | 11.50 | 4.76 |
| Date | 0.92 | 6.95 | 3.00 | 0.40 |
| Footer | 4.42 | 6.95 | 4.50 | 0.40 |

更新後未變。左右邊界為 **0.92 吋**，可用寬度 **11.50 吋**。內容不應超過 y = 6.90 吋，
那裡是頁尾列的起點。

---

## 版面

索引 → 名稱 → placeholder `idx:TYPE`，標題／內文框以吋標示。

| # | 名稱 | Placeholders | 深底？ |
|---|---|---|---|
| 0 | Cover | 0:CENTER_TITLE (1.15, 3.40, 10.00, 0.90), 1:SUBTITLE (1.15, 4.36, 10.00, 0.34) | ● `#0b539d` |
| 1 | Agenda | 0:TITLE, 12:BODY (1.22, 2.26, 5.02, 3.85), 13:BODY (11.37, 2.26, 0.89, 3.85) | |
| 2 | Title | 0:TITLE (1.55, 2.51, 10.24, 1.24), 1:SUBTITLE (1.55, 4.32, 10.24, 1.24) | ● `#0d63ba` |
| 3 | Headings_Custom Photo | 0:TITLE (1.26, 2.02, 4.90, 1.64), 1:SUBTITLE, 10:PICTURE (6.16, 2.57, 6.66, 3.76) | ● `#0d63ba` |
| 4 | Headings_Img | 0:TITLE (1.26, 2.02, 4.90, 1.64), 1:SUBTITLE, 10:OBJECT (6.81, 1.62, 5.71, 4.09) | ● `#0d63ba` |
| 5 | Content Heading | 0:TITLE (0.92, 0.56, 11.50, 0.71) | |
| 6 | Content Heading Dark | 0:TITLE (0.92, 0.56, 11.50, 0.71) | ● 漸層 |
| 7 | Table | 0:TITLE——與 [5] 同框 | |
| 8 | Comparison chart | 0:TITLE——與 [5] 同框 | |
| 9 | Content with image - right | 0:TITLE, 1:OBJECT (7.60, 2.28, 4.63, 4.09), 2:BODY (1.26, 2.28, 6.12, 0.48), 10–13:BODY | |
| 10 | Content with image - left | 0:TITLE, 1:OBJECT (1.10, 2.28, 5.17, 4.09), 2:BODY (6.62, 2.28, 5.61, 4.09) | |
| 11 | Content with image - centered | 0:TITLE, 1:OBJECT (1.26, 1.91, 10.97, 2.96), 2:BODY (1.26, 5.00, 10.97, 1.26) | |
| 12 | Thank you | 0:CENTER_TITLE (1.16, 3.40, 10.00, 0.90) | ● `#0b539d` |

### 深底版面需要亮色文字

**六個版面是深色背景：**0 `Cover`、2 `Title`、3 `Headings_Custom Photo`、
4 `Headings_Img`、6 `Content Heading Dark`、12 `Thank you`。它們的標題 placeholder 在樣板
裡本來就設成 `bg1`（白），所以靠繼承填入的內容沒問題。

但 **`build_deck.py` 自己加上的文字框會預設 `#13182c` 而整段消失**，所以它在這些版面上
會把自己的文字翻成白色（`#ffffff`）、副標翻成 `#e7e6e6`。`verify_deck.py` 是對照真實背景
量對比度——依序是該頁的 `<p:bg>`、版面的、master 的，再看有無滿版圖形——而不是假設白底。
深底上的深色文字是硬錯誤；白字配深藍會通過。

判斷依據是背景亮度（0.299/0.587/0.114 加權後小於 128），從檔案算出，所以使用者提供的樣板
也會得到相同處理。

### 13 個版面其實是 11 個

**把文字放在同一個位置的版面，就是同一個版面。** 底圖不屬於版面的身分——版面給你的是
標題、副標與內文的落點。

| 保留 | 被併入 |
|---|---|
| **5 `Content Heading`** | 7 `Table`、8 `Comparison chart` |

`Table` 與 `Comparison chart` 都沒有表格或圖表 placeholder；名稱只是底圖上燒進去的字
（`STANDARD TABLE`、`REGIONAL CONCEPT`），而那個英文字壓在中文頁面上很怪——這正是中性的
`HEADING` 版本勝出的原因。表格無論選哪個版面都是畫成圖形。

**底色明暗不算「底圖」。** `Content Heading Dark` [6] 的幾何與 `Content Heading` [5] 完全
相同，但文字顏色相反，所以它保持獨立。若連明暗都忽略，深色版本就永遠選不到，而文字會落
在它上面看不見。

**保留哪一個成員：**先取名稱不指定特定主題的，再取措辭最不裝飾的，最後照樣板本身的順序。

**當底圖**就是**選它的理由**時——例如某個段落非那張背景照不可——在 spec 設
`"collapse_layouts": false`，所有版面名稱都會被完全照寫的方式尊重。

以上全部從檔案算出，沒有寫死，所以使用者提供的樣板一樣適用。對任何樣板跑
`inspect_template.py` 就能看到分組結果。

### `Thank you`[12] 維持原樣

這個版面**不是空框**。它自帶：

- 燒進底圖的 `Thank` / `you` 字樣
- 一個非 placeholder 的文字框，內容是 `330 Mac Lane Keasbey, NJ 08832 | Tel: +1(732)346-0200 | www.csitech.com`
- 標題 placeholder 本身預填 `Thank you`

那些是樣板作者的東西，不是某一份簡報的內容，所以 `build_deck.py` 預設**不動這一頁**——只把
版面自己的標題文字複製到頁面上，其餘都不產生。

⚠️ **PowerPoint 把版面 placeholder 的文字視為提示，不會帶到新頁面上**（python-pptx 回傳空
的 text frame）。所以「維持原樣」必須是主動把那句話寫上去，否則輸出會只有底圖與聯絡資訊，
少了「Thank you」。

spec 給了 `title`／`bullets` 等會被忽略並警告。要改就在該頁設 `"keep_closing": false`。
名稱為 `Thank you`／`Thanks`／`Closing` 的版面同樣受保護，所以使用者提供的樣板也適用。

### `Agenda`[1] 的兩欄

這個版面有**兩個** BODY placeholder，不是一個：

| idx | x | w | 用途 |
|---|---|---|---|
| 12 | 1.22 | 5.02 | 段落大標 |
| 13 | 11.37 | 0.89 | 頁碼（樣板原本是 `02 23 27 32 40`） |

只填左欄，右欄會空著，然後被 `drop_empty_placeholders()` 刪掉——議程就悄悄失去頁碼。所以
`build_deck.py` 兩欄都填：大標取自各段落分隔頁（`Title`、`Headings_*`）的標題，頁碼取自它們
實際落在第幾頁，並靠右對齊。全部從簡報自己算出來，所以搬動頁面後議程不會失準。

### 標題只有一行的高度

所有內容版面的標題框都是 **0.71 吋高、32pt**（`Cover` 與 `Thank you` 是 46pt、`Title` 與
`Headings_*` 是 36pt）。0.71 吋在 32pt 下只夠一行，所以換行的標題會溢出或被 autofit 縮小
到不像標題。中文大約 20 字就會換行，`Cover` 的 46pt/10.00 吋更早。

`build_deck.py` 與 `verify_deck.py` 都會依該版面**實際的**框寬與字級量測後警告，不是用固定
字數，因為 46pt/10.00 吋和 32pt/11.50 吋的容納量差很多。

### 決定每份簡報形狀的那個限制

**只有版面 1、4、9、10、11 有 body 或 object placeholder。** 其餘**八個**只有標題。
所以 `Content Heading`、`Content Heading Dark`、`Table`、`Comparison chart`、`Cover`、
`Title`、`Headings_Custom Photo` 與 `Thank you` 的項目文字必須放進**手動加入的文字框**——
`build_deck.py` 會放在 `(0.92, 1.60, 11.50, 4.80)` 吋，避開標題與頁尾列。

版面 9 的 `2:BODY` 只有 **0.48 吋高**——那是圖說欄位，不是內文框。塞三條要點會無聲溢出，
所以 `build_deck.py` 會把它放大，上限在 y = 6.85 吋。

### 選版面

| 需求 | 版面 |
|---|---|
| 封面 | 0 `Cover` |
| 目錄 | 1 `Agenda` |
| 段落分隔 | 2 `Title` |
| 帶照片的段落分隔 | 3 `Headings_Custom Photo` |
| 一般要點／敘述 | **5 `Content Heading`**——主力 |
| 需要跳出來的一頁（唯一那個 P0、那個請求） | 6 `Content Heading Dark` |
| 文字＋截圖 | 9 或 10（LTR 語言下 `- right` 讀起來較順） |
| 標題旁配圖表或示意圖 | 4 `Headings_Img` |
| 單張大圖 | 11 `Content with image - centered` |
| 表格資料 | 5——`Table` [7] 是同一個版面，只是底圖上寫著「STANDARD TABLE」 |
| 功能／方案比較 | 5——同上，`Comparison chart` [8] 不是獨立版面 |
| 結尾 | 12 `Thank you` |

舊樣板的時程版面（`Project plan`）已經沒了。要表達階段，用 5 配表格，或 11 配一張示意圖。

## 不要

- **不要修改或覆蓋這個檔案。** 開啟它、建立內容、`save()` 到別的地方。
- 不要用單純的 `sldIdLst.remove()` 刪頁——先呼叫 `presentation_part.drop_rel(sldId.rId)`，
  否則那些 part 會留在 package 裡，輸出會有重複的 zip entry 以及原始媒體。
- 不要在段落上設字體然後以為它生效了。要對 **run** 設定。
- 不要在那六個深底版面上放 `#13182c` 的文字。
- **不要改 `Thank you` 頁**，除非使用者明確要求。那頁的字樣與公司聯絡資訊不屬於任何一份簡報。
- 不要手寫議程的項目。它是從各段落分隔頁算出來的，手寫的版本在頁面搬動後就會失準。
- 不要寫會換行的標題。標題框只有一行高。
- 不要以為樣板自帶的 13 頁是值得照抄的風格指南——那是一份 CSI Technology Group 的公共安全
  簡報，全英文，而且文字相當密。
