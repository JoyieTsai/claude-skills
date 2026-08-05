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
│   └── narrative.md             # 敘事結構、頁數、大綱範本
├── scripts/
│   ├── inspect_template.py      # 讀出任何樣板的版面、色票、字體、重複版面
│   ├── build_deck.py            # spec JSON → .pptx
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
