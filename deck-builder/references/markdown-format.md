# 用 Markdown 直接做簡報

`build_deck.py --spec` 除了 JSON，也吃 `.md`。**而且吃的就是步驟 3 那份大綱的格式**——
`references/narrative.md` 的範本原封不動可以 build。

這不是為了少打字。JSON spec 和大綱是同一份內容的兩種寫法，只要分成兩個檔案就一定會走鐘：
使用者確認的是大綱，產出的卻是 spec，中間那次手抄沒有人檢查。讓大綱本身可以 build，這個
落差就不存在。

```bash
python3 ~/.claude/skills/deck-builder/scripts/build_deck.py \
  --spec deck.md --out deck.pptx
```

想先看轉出來的 spec：

```bash
python3 ~/.claude/skills/deck-builder/scripts/md_to_spec.py deck.md
python3 ~/.claude/skills/deck-builder/scripts/md_to_spec.py deck.md -o deck.json
```

可直接跑的範例：`assets/example-company.md`、`assets/example-recommended.md`。

---

## 一、整體結構

```markdown
---
style: company
language: zh-TW
audience: internal
title: Genie 2026 設計審核
---

# 這是大綱的抬頭，不會進簡報

**對象** 內部 · **9 張 · 約 8–10 分鐘**

---

## 1 · Cover
**標題** Genie 2026 設計審核
**副標** 無障礙稽核 · 2026-08-04
**備註** 開場一句。

## 2 · Content Heading
**標題** 灰階文字有 5 個色階不符 AA
- `#b4b4b4` 於白底為 1.90:1
- 影響全站說明文字
  - 修法：最淺止於 `#767676`
**備註** 這是 P0-1。
```

- **frontmatter**（開頭的 `---` 區塊）＝ spec 的最上層欄位，`key: value` 一行一個。
  刻意不是 YAML——為了六個純量值去要求 `pip install pyyaml`，會讓全新 clone 跑不動，
  那正是內建樣板要解決的問題。省略時預設 `style: company`、`language: zh-TW`。
- **第一個 `##` 之前的所有東西都是大綱的抬頭**，不會進簡報。所以頁數、時長、「要對方做的
  決定」那幾行可以照寫。其中 `# H1` 若 frontmatter 沒給 `title`，會拿來當檔案屬性標題。
- **每個 `##`（或 `###`）標題開一頁**，標題文字就是版面名稱。`1 · `、`4. `、`7、` 這種
  大綱編號會被去掉，所以 `### 4 · Content Heading` 的版面是 `Content Heading`。

## 二、每一頁可以寫什麼

| 寫法 | 對應 spec 欄位 |
|---|---|
| `**標題** …` / `**title** …` | `title` |
| `**副標** …` | `subtitle` |
| `- 項目`（縮排 2 格 = 第二層） | `bullets` |
| 沒有項目符號的一般段落 | `paragraphs` |
| `**左欄**` / `**右欄**` 之後的項目 | `columns`（推薦風格的 `two-column`） |
| Markdown 表格 | `table`（欄寬均分；要調就改用 JSON 的 `col_widths`） |
| `**圖表**` ＋ 隨後的 ```` ```json ```` 區塊 | `chart` |
| `![](/abs/path.png)` 或 `**[image: /abs/path.png]**` | `image` |
| `**圖說** …` | `caption` |
| `**備註** …` 或 `> …` | `notes` |
| `**保留結尾** 否` | `keep_closing: false` |

欄位名稱中英皆可（`**notes**` 等於 `**備註**`）。`**bold**`、`_italic_`、`` `code` ``
是大綱給人讀的排版，寫進簡報前會被去掉——投影片上出現一顆星號幾乎都不是原意。

**整行斜體是註解，不會進簡報。** 所以 `_自動列出以下段落大標與頁碼_` 這種大綱說明可以留著。

`entries`（手寫議程）只有 JSON 有。議程本來就該從簡報自己算出來，不該手寫。

## 三、圖表為什麼是 JSON 區塊

圖表有 12 個欄位、巢狀的 `series`、還有數值陣列。硬要發明一套 Markdown 語法來表達它，
只會多一層會錯的東西，而且錯的時候訊息很難懂。所以圖表就寫 JSON——欄位與選用準則見
`charts.md`，區塊裡的內容和 spec 裡的 `chart` 物件一模一樣。

````markdown
## Content Heading
**標題** P1 是最大的一群，但 P0 決定能不能上線
- P0 只有 2 條，卻是上線的關卡

**圖表**

```json
{"form": "column", "categories": ["P0", "P1", "P2", "P3"],
 "series": [{"name": "問題數", "values": [2, 7, 6, 3]}],
 "colors": "emphasis", "emphasize": 0}
```
````

JSON 有語法錯誤會**報出行號**並停下，不會猜。

## 四、規則完全一樣

Markdown 只是輸入格式，不是另一條路徑——它轉成 spec 之後走的是同一個 builder。所以
`spec-format.md` 的每一條約束都還在，包括：

- 未知版面名稱（樣板風格）→ 硬錯誤
- `bullets`／`paragraphs`／`table`／`chart` 每頁只能一個，**唯一例外是 `chart` 可與
  `bullets` 同頁**（自動左文右圖）；`chart`＋`table`、`chart`＋`image` 是硬錯誤
- `Thank you` 維持樣板原樣，除非該頁寫 `**保留結尾** 否`
- `Agenda` 自動列出所有段落大標與頁碼
- 標題換行會警告（依實際框寬與字級量測）
- 深底版面放圖表：build 警告、`verify_deck.py` 錯誤
- `[待補: …]` 在 build 只警告，在 verify 是錯誤

產出後照樣要跑 `verify_deck.py`。
