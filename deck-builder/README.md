# deck-builder

產出**可編輯的 .pptx** 簡報，真正繼承樣板的 master、版面、字體與品牌色——不是做一個外觀相似的檔案。適用 [Claude Code](https://claude.com/claude-code) 與 [Cursor](https://cursor.com/docs/skills)。

三種風格：

- **公司樣板** — 由 `config.json` 指定路徑，真正的 master 繼承
- **系統推薦** — 保留企業藍，但版面更簡潔密實的自繪風格
- **使用者提供的樣板** — 先檢視你的 `.pptx`／`.potx`，報告版面與色票後再開始做

## 安裝

此 skill 位於 `claude-skills` repo——完整 clone 步驟見該 repo 的 [README](../README.md)。

### 設定公司樣板路徑

樣板路徑因機器而異，所以不進版控。以範例檔為範本建立自己的 `config.json`：

```bash
cp ~/.claude/skills/deck-builder/config.example.json \
   ~/.claude/skills/deck-builder/config.json
# 然後把 company_template 改成你的樣板實際路徑
```

`config.json` 已被 gitignore。也可以改用環境變數，它的優先序更高：

```bash
export DECK_BUILDER_TEMPLATE="$HOME/Documents/.../Your Template.pptx"
```

兩者皆無而 spec 又沒指定 `template` 時，`build_deck.py` 會直接報錯並說明怎麼設定——不會猜。只用「系統推薦」風格或每次都在 spec 裡明寫 `template` 的話，這一步可以略過。

### Cursor

個人全域（所有專案可用）：

```bash
mkdir -p ~/.cursor/skills
ln -s ~/claude-skills/deck-builder ~/.cursor/skills/deck-builder
```

僅單一專案（可 commit 給團隊）：

```bash
mkdir -p .cursor/skills
ln -s ~/claude-skills/deck-builder .cursor/skills/deck-builder
```

在 Agent 對話輸入 `/deck-builder`，或用自然語言觸發。

> 若你已把本 repo 裝在 `~/.claude/skills/`，Cursor 通常也會直接讀到，不必再連結一份。

### Claude Code

把 repo clone 到 `~/.claude/skills/`（見上層 README）。用 `/skills` 確認 `deck-builder` 在列表中。

## 用法

用自然語言提出需求即可：

```
/deck-builder
幫我把這份稽核報告做成簡報
做一份給客戶的提案 PPT，15 分鐘
整理成內部設計審核簡報
```

流程固定是五步：

1. **問三個問題** — 對象（對外／對內）、風格、語言。三題一次問完，不會擅自假設。
2. **蒐集內容** — 你提供的文件、訪談你、或直接讀專案程式碼／Figma。缺的數字會標成 `[待補: …]`，絕不編造。
3. **逐頁大綱等你確認**（硬性關卡）— 完整大綱會貼在對話裡，附頁數與預估時長。**未經你同意不會產生任何 .pptx**，因為分頁與故事順序是你該操舵的地方，在大綱改比在成品改便宜得多。
4. **產生** — 依已確認的大綱寫 spec 並 build。
5. **驗證後交付** — 一定跑 `verify_deck.py`，過了才交。

交付物是你能在 PowerPoint 打開並繼續編輯的檔案。

## 圖表

圖表是**原生的 `c:chart` 部件**，資料存在內嵌的 Excel 工作表裡——在 PowerPoint 點下去就能
改數字、換圖表類型。不是圖片。

色票不是挑好看的，是用 [`dataviz`](https://code.claude.com/docs/en/skills) skill 的驗證器
針對這個樣板的實際底色實測出來的：8 個固定類別槽位，色相永不循環，最差相鄰色對在
protanopia 模擬下 ΔE 8.4、正常視覺 18.3，全部通過白底 3:1。

會被擋下來的反模式：超過 8 個數列、少於 3 片的圓餅、一根柱子的長條圖、雙 Y 軸（結構上不
可能）、每個點都標數字、超過 3 個數列的散佈圖（那裡每點都和其他所有點比，只有前 3 槽過得了
all-pairs）。

**深底版面不放圖表。** 這是量出來的，不是偏好：在 `Content Heading Dark` 的導覽藍
`#0b539d` 上，dataviz 的深色步階 8 個全部低於 3:1，亮色步階則超出深色模式的明度帶。
深底是給一句重話用的。

兩件 pptx 做不到、所以明說而不默默丟掉的事：**沒有圓角資料端**（DrawingML 的圖表數列沒有
圓角可設）、**沒有 hover 層**（所以身分改為靠圖例與選擇性直接標註承擔）。

完整的形式與色票選用準則見 `references/charts.md`。

## 固定規則

- **標題是一句放得下一行的簡潔話**（約 20 個中文字以內）。樣板標題框只有一行高，換行會溢出或被縮小到不像標題。超長會警告。
- **議程頁自動列出所有段落大標與頁碼**，從各段落分隔頁算出來，所以搬動頁面後不會失準。
- **`Thank you` 頁維持樣板原樣**——它自帶字樣與公司地址／電話／網址，那是樣板作者的內容。要改就在該頁設 `"keep_closing": false`。

## 驗證器會檢查什麼

```bash
python3 ~/.claude/skills/deck-builder/scripts/verify_deck.py deck.pptx
```

文字溢出、空的 placeholder、小於 12pt 的文字、WCAG 對比（對照真實背景，不是假設白底）、非品牌色、各語系字體錯誤或缺失、過大的表格、缺少講者備註、重複的 zip entry 與孤立的 slide part。**未解決的 `[待補: …]` 標記是錯誤**（exit code 1），所以未完成的簡報不會被誤交出去。

## 需求

- **Python 3** ＋ `python-pptx`（`pip3 install python-pptx`）
- 字體：英文 Segoe UI、中文微軟正黑體／Microsoft JhengHei。缺字體不影響產出，只影響你機器上的預覽。
- 沒有 LibreOffice 也可以——但那表示無法把簡報轉成圖片做視覺檢查，`verify_deck.py` 就是唯一的檢查手段。

## 目錄結構

```
deck-builder/
├── SKILL.md                     # Agent 遵循的工作流程
├── config.example.json          # 複製成 config.json 並填入你的樣板路徑
├── references/
│   ├── company-template.md      # 公司樣板已驗證規格：色票、字體、13 個版面
│   ├── recommended-style.md     # 系統推薦風格的色票、字級、格線、版面
│   ├── spec-format.md           # build_deck.py 讀的 JSON 格式
│   ├── charts.md                # 圖表形式與色票的選用準則（實測數據）
│   └── narrative.md             # 敘事結構、頁數、大綱範本
├── scripts/
│   ├── inspect_template.py      # 讀出任何樣板的版面、色票、字體、重複版面
│   ├── build_deck.py            # spec JSON → .pptx
│   ├── charts.py                # 原生可編輯圖表 ＋ 已驗證色票
│   └── verify_deck.py           # 交付前檢查
└── assets/
    ├── example-company.json     # 可直接跑的公司樣板範例
    └── example-recommended.json # 可直接跑的推薦風格範例
```

## 日後修改注意

`build_deck.py` 裡有幾處會**無聲**出錯的地方：

- 刪除樣板自帶的頁面時，要先 `presentation_part.drop_rel(sldId.rId)` 再 `sldIdLst.remove()`。少了 drop_rel，那些 part 會留在 package 裡，輸出多出重複的 zip entry 與原始媒體。
- 字體必須設在 **run** 層級。段落層級的字體指定會靜靜失效。
- 中文要設 `a:ea`／`a:cs`，英文設 `a:latin`，而且兩者都寫在同一個 run 上，混排才正確。不能靠繼承——公司 master 的 `titleStyle` 把 `a:ea` 設成 Open Sans（純拉丁字體）。
- 品牌色**不在** `ppt/theme/` 裡。公司樣板的 theme 是原廠 Office 預設（Calibri／`#4472c4`）；真正的色票只存在於 slide 與 layout 的圖形中。
- 文字排版相同的版面會被併成一個（底圖不算），但底色**明暗**永遠獨立成組——深底版面的文字必須是亮色，否則會直接看不見。
- 版面 placeholder 裡的文字是「提示」，**不會**被帶到新頁面上。`Thank you` 頁要維持原樣，就得主動把那句話複製過去，否則輸出只有底圖與聯絡資訊。
- `Agenda` 版面有**兩個** BODY placeholder（大標欄＋頁碼欄）。只填一個，另一個會被 `drop_empty_placeholders()` 刪掉，議程就悄悄少了頁碼。
- placeholder 型別**不能用子字串比對**。python-pptx 把型別印成 `SUBTITLE (4)`，字串裡含有 `TITLE`——所以 `"TITLE" in t` 會把封面副標當成標題。`build_deck.py` 用 `ph_by_type()` 精確比對列舉名稱，`verify_deck.py` 用 `is_title_ph()`；否則副標會被拿去檢查「標題只有一行」的規則，而標題也可能被寫進副標框。
- **圖表部件裡的字體要再設一次。** `font.name` 一樣只寫 `a:latin`，而圖表是獨立的 part、有自己的文字屬性（軸標籤、圖例、資料標註各有一個 `defRPr`），所以 `charts.py` 的 `_apply_fonts()` 走訪整個 `chartSpace` 補上 `a:ea`／`a:cs`。而且 `a:defRPr` 的子元素**有 schema 順序**（solidFill?, latin, ea, cs），順序錯了 PowerPoint 會要求修復檔案——所以每個元素是插在實際存在的前一個元素之後，不是直接 append。
- **圖表沒有圓角可設。** DrawingML 的數列沒有 corner radius，所以 dataviz 規格裡的「4px 圓角資料端」在 pptx 做不到。這件事寫在 `charts.md` 裡明說，而不是默默照做失敗——畫一個圓角矩形就不是圖表了。
- **改色票就要重跑驗證器。** `CATEGORICAL` 的色盲區辨是當成**一組**量的：換掉其中一個色相，會破壞它對其他色相的保證。改完要跑 dataviz 的 `validate_palette.js`，並同步更新 `verify_deck.py` 的 `CHART_COLORS` 與 `charts.md` 裡的實測數字。
