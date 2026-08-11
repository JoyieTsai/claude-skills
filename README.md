# claude-skills

個人用的 Agent skills，跨機器共用。同時支援 [Claude Code](https://claude.com/claude-code) 與 [Cursor](https://cursor.com/docs/skills)。

每個頂層目錄是一個 skill（內含 `SKILL.md`）。

## Skills

| Skill | 用途 |
|---|---|
| [`uiux-audit`](uiux-audit/) | 稽核 UI/UX 品質——設計檔或已實作的程式碼——並產出依優先順序排列的發現報告。內含 WCAG 對比計算器，以及 Playwright 截圖 + axe-core 掃描器。 |
| [`deck-builder`](deck-builder/) | 產出可編輯的 `.pptx` 簡報，真正繼承樣板的 master、版面與品牌色。先問對象與風格，逐頁大綱經確認後才產生，交付前跑對比與溢出驗證。 |

## 在 Cursor 使用

Cursor 會自動掃描這些位置的 skills：

| 位置 | 範圍 |
|---|---|
| `~/.cursor/skills/<skill-name>/` | 個人，所有專案 |
| `.cursor/skills/<skill-name>/` | 僅該專案（可進版控給團隊） |
| `~/.claude/skills/<skill-name>/` | 相容路徑——與 Claude Code 共用同一份也可 |

### 安裝（個人全域）

把各個 skill 連結到 Cursor 的 skills 目錄（推薦，方便與本 repo 同步）：

```bash
git clone <this-repo-url> ~/claude-skills
mkdir -p ~/.cursor/skills
ln -s ~/claude-skills/uiux-audit ~/.cursor/skills/uiux-audit
ln -s ~/claude-skills/deck-builder ~/.cursor/skills/deck-builder
```

或只裝進某個專案：

```bash
mkdir -p /path/to/your-project/.cursor/skills
ln -s ~/claude-skills/uiux-audit /path/to/your-project/.cursor/skills/uiux-audit
```

可選：啟用瀏覽器截圖

```bash
bash ~/claude-skills/uiux-audit/install.sh
```

### 怎麼呼叫

在 **Agent** 對話裡：

1. **手動**：輸入 `/` 後選 skill 名稱（或直接打 `/uiux-audit`、`/deck-builder`）
2. **自動**：直接用自然語言，Agent 會依 skill 的 `description` 決定是否套用，例如：
   - `審核這個設計`（附上截圖）
   - `audit the login page of this project`
   - `幫我把這份報告做成簡報`
   - `做一份給客戶的提案 PPT`

也可在 Cursor Settings → Rules → Agent Decides 確認 skill 已出現。

詳細用法見 [`uiux-audit/README.md`](uiux-audit/) 與 [`deck-builder/README.md`](deck-builder/)。

## 在 Claude Code 使用

**本 repo 可直接當 `~/.claude/skills/`。** Claude Code 會在該路徑找 skills——不需要 symlink 或額外設定。

若 `~/.claude/skills/` 尚不存在：

```bash
git clone <this-repo-url> ~/.claude/skills
```

若目錄已存在且你想保留既有 skills，先 clone 到別處再搬進去：

```bash
git clone <this-repo-url> ~/claude-skills
mv ~/claude-skills/* ~/claude-skills/.git* ~/.claude/skills/
```

接著做各 skill 的機器層級設定（只有需要的 skill 才做）：

```bash
# uiux-audit：可選，啟用瀏覽器截圖
bash ~/.claude/skills/uiux-audit/install.sh

# deck-builder：不需設定。公司樣板已內建在 assets/company-template.pptx。
# 只有要改用別的樣板（例如公司發了新版）時才做這一步：
cp ~/.claude/skills/deck-builder/config.example.json \
   ~/.claude/skills/deck-builder/config.json
# 再把裡面的 company_template 改成你的樣板實際路徑
```

在 Claude Code 裡用 `/skills` 確認已載入。

> 已裝在 `~/.claude/skills/` 的話，Cursor 通常也能直接讀到（相容路徑），不必再複製一份。

## 新增 skill

```
<skills-root>/<skill-name>/
└── SKILL.md          # 必要：YAML frontmatter，含 `name` 與 `description`
```

`<skills-root>` 依工具而定：`~/.claude/skills/`、`~/.cursor/skills/`，或專案內的 `.cursor/skills/`。

`description` 是 Agent 用來判斷何時載入該 skill 的依據，所以要具體寫出**何時**該用，而不只是它是什麼。其餘皆可選：`references/` 放按需載入的細節，`scripts/` 放可執行的輔助工具。

保持 `SKILL.md` 精簡——它是永遠會載入的部分。把深度內容放到 `references/`，並在 `SKILL.md` 指向它們。

## 慣例

- **不要寫死絕對路徑。** 相對於腳本本身解析路徑（`import.meta.dirname`），這樣無論 repo clone 到哪都能運作。
- **依賴放在該 skill 自己的目錄內**，加入 gitignore，由自己的腳本安裝。不要假設有全域安裝。
- **提交 lockfile**，讓每台機器解析到相同版本。
- **Skill 應優雅降級。** 若可選依賴缺失，應說明並以縮減功能繼續，而不是直接失敗。

## 同步

在每台機器上 `git pull`。依賴不納入版本控管，所以 pull 到新增了依賴的 skill 後，請重新執行其安裝腳本。
