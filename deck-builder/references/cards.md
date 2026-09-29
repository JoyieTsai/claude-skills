# Cards（卡片格）

`cards` 在內容頁畫出可編輯的圓角卡片（頂部品牌色條 + 可選 icon + 標題／內文），
用來取代整頁要點列。與 `bullets`／`table`／`chart`／`image` **互斥**。

## Markdown

````markdown
## Content Heading
**標題** 四個切入方向

**卡片**

```json
[
  {"title": "偵查輔助", "body": "海量數位證物主動串聯", "icon": "csi:evidence"},
  {"title": "智慧法庭", "body": "卷宗摘要與類案量刑", "icon": "csi:court"},
  {"title": "合規監督", "body": "程序合規與去識別化", "icon": "ai"},
  {"title": "資源調度", "body": "熱點預測與巡邏建議", "icon": "csi:police"}
]
```
````

## Icon 兩套來源

| 前綴 | 用途 | 來源 |
|------|------|------|
| （無）或 `ui:` | 一般 UI／功能 | Flaticon **Interface Icons**（Genie `src/assets/icons`） |
| `csi:` 或 `duotone:` | CSI 產品／模組／品牌 | **CSI Icons** duotone SVG |

CSI Icons 設計指引（內網）：
http://10.20.1.229:8081/1.0/design-style/iconography-dev/1

本機對應檔案（與設計站同一套）：

- `csi-uikit-bootstrap/public/1.0/icons/csiicon-duotone/<name>.svg`
- `csi_v3_nuxt_vuetify/assets/duotone/<name>.svg`（底線／連字號皆可）

環境變數覆寫路徑：

- `DECK_BUILDER_INTERFACE_ICONS` — Interface Icons 目錄
- `DECK_BUILDER_CSI_ICONS` — CSI duotone 目錄

### 命名範例

```text
"icon": "ai"                 → Interface
"icon": "ui:search"          → Interface（明示）
"icon": "csi:court"          → CSI 產品
"icon": "csi:justice-court"  → CSI 產品
"icon": "csi:court_outline"  → 會去掉 _outline 後找 court.svg
"icon": "/abs/path/x.png"    → 直接用檔案
```

規則：**產品相關內容用 `csi:`**；一般介面動作用 Interface Icons。

## Variants（版型）

版面名稱本身就是 variant，用冒號語法指定。可分成兩類：**網格形狀**（控制欄數）和**繪製風格**（控制每張卡的樣貌）。

### 網格 Variants

| Layout 值 | 說明 |
|---|---|
| `content`（無 variant）| 自動依數量決定：2–3 → 單列，4 → 2×2，5–6 → 3×2 |
| `cards:2-col` | 強制 2 欄單列 |
| `cards:3-col` | 強制 3 欄單列 |
| `cards:4-grid` / `cards:2x2` | 強制 2×2 方格 |

### 風格 Variants

| Layout 值 | 每張卡的外觀 | 需要的欄位 |
|---|---|---|
| （預設）| 頂部品牌色條；icon 可選（左上角）；標題＋內文 | `title`、`body?`、`icon?` |
| `cards:icon` | icon 置中放大於卡頂；標題與內文置中 | `title`、`body?`、`icon?` |
| `cards:number` | 大序號（01 02…，30pt 品牌色）替代 icon | `title`、`body?` |
| `cards:image` | 圖片填滿卡片上方 42%；無品牌色條 | `title`、`body?`、`image`（必填） |
| `cards:steps` | 垂直序號清單（品牌色圓形數字 + 標題 + 說明），有連接線；比卡片格更像流程 | `title`、`body?` |
| `cards:bento` | 非對稱：第一項為主卡（約 62% 寬），其餘為右側支援卡（2–4 項） | `title`、`body?`、`icon?` |
| `cards:featured` | 非對稱：第一項為通欄主卡，其餘最多 3 項橫列於下方 | `title`、`body?`、`icon?` |

> **`cards:steps` 與 `cards:number` 的差異**：`steps` 是**直式清單**，適合流程、步驟、檢查清單（2–8 項）；`number` 是**橫式卡片格**，適合並列概念（2–4 項）。

> **`cards:bento` / `cards:featured`**：等尺寸 grid 只代表 equal importance。有自然主次時優先用這兩個，或改用 `content:editorial`。

### 組合規則

網格 variant 和風格 variant **互斥**——一次只選一個（不支援 `cards:3-col:icon` 這種雙重 variant）。若要 3 欄 icon 風格，先確認 3 張卡，讓自動網格選 3 欄，然後用 `cards:icon`。

## 版面與數量

- 2–3 張：單列；4 張：2×2；5–6 張：最多兩列（偏擠，會警告）
- 公司樣板建議搭 `Content Heading`（淺底）；深底版面上卡片仍為淺色面板
- 標題約 8–12 字、內文約一句；icon 可省略（`cards:icon` 時 icon 更明顯，建議填）

## JSON

```json
{
  "layout": "Content Heading",
  "title": "四個切入方向",
  "cards": [
    {"title": "偵查輔助", "body": "…", "icon": "csi:evidence"},
    {"title": "智慧法庭", "body": "…", "icon": "csi:court"}
  ]
}
```
