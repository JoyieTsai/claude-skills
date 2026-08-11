# deck-builder

產出**可編輯的 .pptx** 簡報，真正繼承樣板的 master、版面、字體與品牌色——不是做一個外觀相似的檔案。適用 [Claude Code](https://claude.com/claude-code) 與 [Cursor](https://cursor.com/docs/skills)。

三種風格：

- **公司樣板** — 已內建在 `assets/company-template.pptx`，clone 完直接可用，真正的 master 繼承
- **系統推薦** — 保留企業藍，但版面更簡潔密實的自繪風格
- **使用者提供的樣板** — 先檢視你的 `.pptx`／`.potx`，報告版面與色票後再開始做

兩種用法：交給 Agent 對話（它會問對象與風格、先給你大綱確認），或**自己寫一份 `.md`
直接 build**（見[直接用 Markdown 做](#直接用-markdown-做)）。

## 安裝

此 skill 位於 `claude-skills` repo——完整 clone 步驟見該 repo 的 [README](../README.md)。

**公司樣板不需要設定。** 它跟著 skill 一起附在 `assets/company-template.pptx`，所以 clone
下來就能用 `style: "company"` 做簡報。

### 換成別的樣板（選用）

公司發了新版樣板，或你要用另一份時，才需要這一步。優先序高到低：

```bash
export DECK_BUILDER_TEMPLATE="$HOME/Documents/.../Your Template.pptx"
```

或建立 `config.json`（已被 gitignore，因為絕對路徑因機器而異）：

```bash
cp ~/.claude/skills/deck-builder/config.example.json \
   ~/.claude/skills/deck-builder/config.json
# 然後把 company_template 改成你的樣板實際路徑
```

設了但檔案不存在會**直接報錯**，不會無聲改用內建那份——否則你會拿到一份看起來成功、其實
用舊樣板做的簡報。spec 裡明寫的 `template` 一律優先於以上兩者。

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

> Cursor 用符號連結時，`assets/company-template.pptx` 也一起指到同一份，不需另外複製。

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

### 直接用 Markdown 做

第 3 步那份大綱**本身就是 build 的輸入**，不必再轉成別的格式：

```bash
python3 ~/.claude/skills/deck-builder/scripts/build_deck.py \
  --spec deck.md --out deck.pptx
```

```markdown
---
style: company
language: zh-TW
---

## Cover
**標題** Genie 2026 設計審核
**副標** 無障礙稽核 · 2026-08-04

## Content Heading
**標題** 灰階文字有 5 個色階不符 AA
- `#b4b4b4` 於白底為 1.90:1
- 影響全站說明文字
**備註** 這是 P0-1。

## Thank you
```

一頁一個 `##`，標題文字就是版面名稱（`### 4 · Cover` 這種大綱編號會自動去掉）。表格用
Markdown 表格語法，圖表用 `**圖表**` 加一個 JSON 區塊。完整欄位對照見
`references/markdown-format.md`，可直接跑的範例是 `assets/example-company.md` 與
`assets/example-recommended.md`。

為什麼是同一個檔案：spec 和大綱只要分成兩份，中間那次手抄就沒有人檢查，而使用者確認的是
大綱、產出的卻是 spec。需要更精細控制時 `--spec` 一樣吃 JSON（依副檔名判斷），兩者走同一個
builder、同一套檢查。

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
├── config.example.json          # 只在要換掉內建樣板時才需要
├── references/
│   ├── company-template.md      # 公司樣板已驗證規格：色票、字體、13 個版面
│   ├── recommended-style.md     # 系統推薦風格的色票、字級、格線、版面
│   ├── markdown-format.md       # 用 .md 大綱直接 build 的格式對照
│   ├── spec-format.md           # build_deck.py 讀的 JSON 格式（底層）
│   ├── charts.md                # 圖表形式與色票的選用準則（實測數據）
│   └── narrative.md             # 敘事結構、頁數、大綱範本
├── scripts/
│   ├── inspect_template.py      # 讀出任何樣板的版面、色票、字體、重複版面
│   ├── build_deck.py            # spec .md／.json → .pptx
│   ├── md_to_spec.py            # .md 大綱 → spec（也可單獨跑來檢查轉換結果）
│   ├── charts.py                # 原生可編輯圖表 ＋ 已驗證色票
│   └── verify_deck.py           # 交付前檢查
└── assets/
    ├── company-template.pptx    # 內建公司樣板，不需設定
    ├── example-company.md       # 可直接跑的公司樣板範例（Markdown）
    ├── example-recommended.md   # 可直接跑的推薦風格範例（Markdown）
    ├── example-company.json     # 同一份內容的 JSON 寫法
    └── example-recommended.json # 同上
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
- **內建樣板是最後的 fallback，不是最優先。** 解析順序是 spec 的 `template` →
  `DECK_BUILDER_TEMPLATE` → `config.json` → `assets/company-template.pptx`。已經設過路徑的
  人升級後仍會拿到自己那份。而設了路徑卻找不到檔案時是**硬錯誤**，刻意不退回內建那份——
  無聲換樣板會產出一份看起來成功、實際用錯樣板的簡報。
- **`.md` 與 `.json` 走同一個 builder。** `md_to_spec.py` 只做格式轉換，轉完之後所有規則
  （版面名稱、每頁只能一種內容、`Thank you` 保護、深底禁圖表）都還在。所以新增 spec 欄位時
  記得同步 `md_to_spec.py` 的 `FIELDS`，否則那個欄位在 Markdown 裡會被當成內文而不是欄位。
- **Markdown 的 frontmatter 是手寫的，不是 YAML。** 只支援 `key: value` 純量，刻意不用
  `pyyaml`——為了六個值增加一個 pip 依賴，會讓全新 clone 跑不動。
- **改色票就要重跑驗證器。** `CATEGORICAL` 的色盲區辨是當成**一組**量的：換掉其中一個色相，會破壞它對其他色相的保證。改完要跑 dataviz 的 `validate_palette.js`，並同步更新 `verify_deck.py` 的 `CHART_COLORS` 與 `charts.md` 裡的實測數字。
