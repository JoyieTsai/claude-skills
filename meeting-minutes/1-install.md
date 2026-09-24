# 安裝說明

這個工具會把會議或教學的錄音，整理成一份可以直接轉貼給同事的會議記錄。

裝好之後，你在 AI 工具（Cursor、VS Code、Codex 或 Claude Code）的對話框輸入 `/minutes`，把錄音交給它，它就會寫出會議記錄。

**Mac 和 Windows 都能用**，安裝方式不同，請看你用的是哪一種電腦：

| 你的電腦 | 看這一段 |
| --- | --- |
| Mac | 〈[Mac 安裝](#mac-安裝)〉 |
| Windows | 〈[Windows 安裝](#windows-安裝)〉 |

裝好後怎麼用，看 [2-usage.md](2-usage.md)。

> **AI 讀到這份檔案時：** 使用者請你安裝，就直接跳到最後一節〈[給 AI 的安裝步驟](#給-ai-的安裝步驟)〉，照著做，不要自己改寫法。

---

## Mac 安裝

### 開始前先確認

| 需要 | 怎麼確認 |
| --- | --- |
| **一台 Mac** | 左上角  →「關於這台 Mac」。Apple M 系列最順；Intel 也能用，但轉錄會慢很多。 |
| **約 3GB 空間** | 語音辨識模型約 1.6GB，加上其他元件。 |
| **網路** | 第一次安裝要下載模型，約 5–30 分鐘，看網速。 |
| **Homebrew 和 git** | 見下面〈檢查 Homebrew 和 git〉。 |
| **這個工具資料夾** | 用拿到的壓縮檔解壓，或用 git 下載私有倉庫。 |

### 檢查 Homebrew 和 git

Homebrew 是 Mac 上裝軟體的工具，安裝腳本會用它裝轉檔、語音辨識需要的元件。

1. 打開「終端機」（在「應用程式 → 工具程式」裡）。
2. 貼上這兩行，按 Enter：

   ```bash
   brew --version
   git --version
   ```

3. 兩行都印出版本號（例如 `Homebrew 4.x.x`）就可以往下。

沒有版本號的話：

- **`brew` 找不到**：在終端機貼上下面這行，中途會要你輸入電腦開機密碼（打字時畫面不會顯示，是正常的）。

  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```

  裝完後，終端機最後會印出「Next steps」，照它給的兩三行指令貼上執行。然後關掉終端機重開，再跑一次 `brew --version` 確認。
- **`git` 找不到**：貼上 `xcode-select --install`，會跳出一個安裝視窗，按「安裝」等它跑完。

這兩樣請自己裝，不要叫 AI 代裝（要輸入你的電腦密碼）。

### 方式 A：請 AI 幫你裝（推薦）

1. 打開你平常用的 AI 工具，打開這個工具資料夾（裡面看得到 `install.sh` 的那一層）：
   - **Cursor／VS Code**：選「File → Open Folder」。
   - **Codex／Claude Code**：在這個資料夾裡開啟它。
2. 打開 AI 對話面板。Cursor 和 VS Code 要切到 **Agent** 模式，AI 才能執行安裝指令。
3. 在對話框輸入下面這句，按 Enter：

   ```
   請照 1-install.md 安裝這個工具
   ```

4. AI 要執行終端機指令時會先問你，按「Run」／「Accept」讓它跑。下載模型那段會跑比較久，不要關掉 AI 工具。
5. 最後 AI 會回報「安裝完成」，並列出工具和會議資料放在哪。有沒裝成功的項目，它也會寫在這份回報裡。

### 方式 B：自己在終端機裝

1. 打開終端機，進到工具資料夾。最簡單的做法：先輸入 `cd `（cd 後面有一個空格），再把工具資料夾從 Finder 拖進終端機視窗，按 Enter。
2. 貼上這行，按 Enter：

   ```bash
   ./install.sh --yes
   ```

   `--yes` 代表「全部用建議的設定，不要一題一題問我」。它會依你的晶片選好模型、補齊缺的元件、建好會議資料夾。

3. 看到最後印出安裝完成的摘要就好了。

**想自己選設定**（例如改會議資料夾的位置），改跑 `./install.sh`（不加 `--yes`），它會一題一題問你。除了「要裝哪個 AI 工具」之外，其他直接按 Enter 用建議值即可：

| 它問什麼 | 建議 |
| --- | --- |
| Git 遠端 URL | Enter |
| 模型檔名 | Enter（已依晶片選好） |
| 執行 brew install …？ | `y` |
| 下載 whisper 模型？ | `y`（最大的一個，約 5–30 分鐘） |
| 下載 VAD 模型？ | `y`（用來略過沒人講話的段落） |
| 下載聲紋模型？ | `y`。答 `n` 也能轉成文字，只是分不出誰在講 |
| 會議資料根目錄 | Enter，即 `~/Desktop/會議記錄` |
| 安裝 cursor 入口？ | 用 Cursor 就 `y` |
| 安裝 claude-code／codex／vscode 入口？ | 有在用就 `y`，沒有就 `n` |

**小技巧：** 同事已經裝好的話，可以把他們的 `models` 資料夾複製進你的工具資料夾，再跑安裝，就不用重新下載 1.6GB 的模型。

---

## Windows 安裝

> Windows 版還沒有在真的 Windows 電腦上試過。裝到錯誤時，把錯誤訊息整段留著，對照〈卡住了怎麼辦〉。

### 開始前先確認

| 需要 | 怎麼確認 |
| --- | --- |
| **Windows 10 或 11（64 位元）** | 大部分公司電腦都是。 |
| **約 4GB 空間** | 語音辨識模型約 1.6GB，加上 Python、轉檔程式等元件。 |
| **網路** | 第一次安裝要下載模型和元件，約 10–40 分鐘，看網速。 |
| **這個工具資料夾** | 用拿到的壓縮檔，或用 git 下載。 |

**轉錄會比 Mac 慢。** Windows 版只用電腦的處理器轉錄，1 小時的錄音可能要轉 1–3 小時。轉的時候電腦還是可以用，只是會比較慢。

### 先把工具資料夾放到 `C:\meeting-minutes`

**這一步很重要：工具資料夾的位置不能有中文。** Windows 版的語音辨識程式讀不到中文路徑，放在「桌面」「文件」這類資料夾底下，常常會因為路徑有中文而失敗。

- **拿到的是壓縮檔**：解壓縮後，把裡面含 `install.cmd` 的那個資料夾改名為 `meeting-minutes`，搬到 `C:\` 底下。搬好後，打開 `C:\meeting-minutes` 應該直接看到 `install.cmd`、`1-install.md` 這些檔案。
- **會用 git**：直接下載到這個位置：

  ```
  git clone https://github.com/zoetu025-ai/meeting-minutes.git C:\meeting-minutes
  ```

不用先裝其他軟體。轉檔程式、Python、git 這些，安裝程式會自己用 Windows 內建的「應用程式安裝程式」（winget）裝好。

### 方式 A：請 AI 幫你裝（推薦）

1. 打開你平常用的 AI 工具，打開 `C:\meeting-minutes` 這個資料夾：
   - **Cursor／VS Code**：選「File → Open Folder」。
   - **Codex／Claude Code**：在這個資料夾裡開啟它。
2. 打開 AI 對話面板。Cursor 和 VS Code 要切到 **Agent** 模式。
3. 在對話框輸入下面這句，按 Enter：

   ```
   請照 1-install.md 安裝這個工具
   ```

4. AI 要執行指令時會先問你，按「Run」／「Accept」讓它跑。
5. 中途 Windows 可能跳出「是否允許此 App 變更你的裝置？」，那是在裝 git 或轉檔程式，按「是」。
6. 下載模型那段會跑比較久，不要關掉 AI 工具。最後 AI 會回報「安裝完成」。

### 方式 B：自己雙擊安裝

1. 打開 `C:\meeting-minutes`，雙擊 **`install.cmd`**。
2. 如果跳出藍色的「Windows 已保護您的電腦」，按「其他資訊」→「仍要執行」。
3. 會跳出一個黑色視窗，一題一題問你。**每一題都直接按 Enter**，就是用建議的設定。
4. 中途跳出「是否允許此 App 變更你的裝置？」時按「是」。
5. 看到最後印出「安裝結果」，按任意鍵關掉視窗就好了。

它會依序：裝好轉檔程式和 Python、下載語音辨識程式和模型、在桌面建好「會議記錄」資料夾、把 `/minutes` 加進 Cursor、VS Code、Codex、Claude Code（四個都會加，沒在用的不影響）。

---

## 裝好後確認一次

1. **完全關掉你的 AI 工具再重新打開**（不是只關視窗，Mac 要從上方選單選「結束」）。
2. 打開 AI 對話面板，輸入 `/`，清單裡應該看得到 **`minutes`**。
3. 看得到就裝好了。接下來照 [2-usage.md](2-usage.md) 使用。

同時也會在桌面建好一個「會議記錄」資料夾：

```
桌面/會議記錄/
  ├─ audio/      ← 要整理的錄音、螢幕錄影放這裡
  └─ minutes/    ← 整理好的會議記錄會出現在這裡
```

---

## 卡住了怎麼辦

| 你看到 | 怎麼做 |
| --- | --- |
| （Mac）`command not found: brew` | 回到〈檢查 Homebrew 和 git〉。裝完一定要關掉終端機重開。 |
| （Mac）`command not found: git` | 在終端機執行 `xcode-select --install`，等安裝視窗跑完。 |
| （Mac）說缺少 ffmpeg／whisper-cpp／uv 然後停住 | 再跑一次 `./install.sh --yes`。 |
| （Windows）「路徑裡有中文或特殊字元」 | 照〈先把工具資料夾放到 `C:\meeting-minutes`〉搬位置，再從新位置重新安裝。 |
| （Windows）「找不到 winget」 | 打開「Microsoft Store」，搜尋「應用程式安裝程式」（App Installer），更新或安裝它，再重新安裝。 |
| （Windows）說還是找不到 ffmpeg 或 uv | 關掉黑色視窗，重新雙擊 `install.cmd`。剛裝好的程式有時要重開視窗才找得到。 |
| 模型下載到一半斷掉 | 重新安裝一次（Mac：`./install.sh --yes`；Windows：雙擊 `install.cmd`）。已下載完的會跳過，只補沒完成的。 |
| clone 時要求登入，或說沒有權限 | 這是私有倉庫。先取得倉庫權限，或改用已經解壓的工具資料夾安裝。不要換網址。 |
| 輸入 `/` 看不到 `minutes` | 先確認 AI 工具有完全結束再開。還是沒有，重裝指令入口（見下面〈更新到新版〉的第二行）。 |
| AI 說找不到 `config.yaml` | 安裝沒跑完。往上找紅色的錯誤訊息，處理後再安裝一次。 |
| 其他狀況 | 把錯誤訊息整段留著，對照上面的處理再安裝一次。 |

---

## 更新到新版

有新版時，在工具資料夾執行：

| | 第一行：下載新版 | 第二行：讓 `/minutes` 換成新版的說明 |
| --- | --- | --- |
| Mac（終端機） | `git pull` | `./install.sh --update-entrypoints` |
| Windows（PowerShell） | `git pull` | `.\install.cmd --update-entrypoints` |

不會重新下載模型，幾秒鐘就好。沒有用 git 的話，用新版資料夾覆蓋舊的，再跑第二行。

---

## 東西裝在哪、怎麼移除

| 位置 | 裡面是什麼 |
| --- | --- |
| 工具資料夾（Mac 含 `install.sh`、Windows 是 `C:\meeting-minutes`） | 工具本身與模型 |
| 桌面的「會議記錄」資料夾 | 你的錄音和會議記錄。刻意跟工具分開放，避免會議內容被上傳到 GitHub |
| 家目錄的 `.cursor`、`.claude`、`.codex` 等資料夾裡的 `minutes.md` | 讓各個 AI 工具認得 `/minutes` 的小檔案 |

**移除：** 在工具資料夾執行 `./install.sh --uninstall`（Windows：`.\install.cmd --uninstall`），會拿掉 `/minutes` 指令；再刪掉工具資料夾即可。桌面的「會議記錄」預設保留，不會被刪。

如果你校對過錯字（見使用流程的〈聽不清楚的表〉），移除前先把詞彙表同步出去（`git push`），不然這些修正只會留在你的電腦。

---

## 給 AI 的安裝步驟

這一節是寫給 AI 看的。使用者說「照 `1-install.md` 安裝」時，**只執行這一節**。不要改寫法、不要猜路徑、不要把 `--yes` 改成互動問答或你自己的安裝方式。

工作目錄必須是**本檔所在的資料夾**（跟 `install.sh`、`install.cmd`、`INSTRUCTIONS.md` 同一層）。
每一步做完再做下一步。某一步失敗就停，把終端機的錯誤原文貼給使用者，不要換一條你自己寫的安裝路徑。

### 0. 確認平台與位置

先判斷作業系統：你的終端機是 PowerShell 或 cmd、或系統資訊寫 Windows → **跳到〈[Windows：給 AI 的安裝步驟](#windows給-ai-的安裝步驟)〉**，不要跑下面的 bash 指令。

Mac 在終端機執行：

```bash
uname -s
uname -m
pwd
test -f ./install.sh && test -f ./INSTRUCTIONS.md && echo "REPO_OK"
```

| 結果 | 做法 |
| --- | --- |
| `uname -s` 不是 `Darwin` | **停止。** 告訴使用者這個工具只支援 macOS 與 Windows。不要在 Linux 上繼續。 |
| 沒有印出 `REPO_OK` | 你不在工具資料夾。若使用者已把整個資料夾給你，`cd` 到含 `install.sh` 的那一層再重跑。還沒有這份工具時，才做步驟 2 的 `git clone`，clone 完再 `cd` 進去。 |
| `uname -m` 是 `arm64` | Apple Silicon。`--yes` 會選 `ggml-large-v3-turbo.bin`。 |
| 其他 | Intel。`--yes` 會選 `ggml-medium.bin`。 |

記下 `pwd` 的結果，後面稱為 `<repo>`。

### 1. 確認 brew 與 git（沒有就停，不要代裝）

```bash
brew --version
git --version
```

- `brew` 不存在：**停止。** 請使用者照本檔〈檢查 Homebrew 和 git〉自己安裝（要輸入電腦密碼，不由你執行）。裝好、`brew --version` 有版本號後，再從步驟 0 重跑。
- `git` 不存在：**停止。** 請使用者自己執行 `xcode-select --install`，等視窗跑完再繼續。

### 2. 還沒有工具資料夾時才 clone

步驟 0 已經印出 `REPO_OK` 就**跳過這步**，不要再 clone 一份。

```bash
cd ~/Desktop
git clone https://github.com/zoetu025-ai/meeting-minutes.git
cd meeting-minutes
```

這是私有倉庫。clone 要求登入或權限失敗時：**停止。** 請使用者改用已經拿到的工具資料夾。不要換別的網址，也不要 clone 到別的路徑。

### 3. 用預設值安裝（不要改成互動問答）

```bash
./install.sh --yes
```

可重複執行。它**不會**問問題，一律用下面的預設：

| 項目 | `--yes` 的做法 |
| --- | --- |
| Git 遠端 | 沿用這個資料夾現有的 `origin`；沒有就留空 |
| 模型 | Apple Silicon → `ggml-large-v3-turbo.bin`；Intel → `ggml-medium.bin`。`config/config.yaml` 裡已有 `model` 就沿用 |
| `ffmpeg`、`whisper-cpp`、`uv` | 缺了就 `brew install` |
| Python 環境 | 建立 `.venv`，依 `requirements.txt` 安裝 |
| Whisper 模型、VAD 模型、聲紋模型 | 不存在才下載。Whisper 約 1.6GB（Intel 的 medium 較小）。已存在就跳過 |
| 會議資料夾 | `~/Desktop/會議記錄`，其下建 `audio/`、`minutes/`。已有設定就沿用原路徑 |
| AI 入口 | **一定安裝 Cursor**（`~/.cursor/commands/minutes.md`）。Claude Code／Codex／VS Code 只有這台機器偵測得到才裝 |

不要自己 `brew install` 一份清單、不要改 `config/glossary.txt`、不要 `git commit` 或 `git push`。

模型下載到一半失敗：再跑一次 `./install.sh --yes`。它會重下沒完成的檔，已完成的會跳過。

### 4. 逐項核對，缺一項就不要說裝好了

在 `<repo>` 底下執行：

```bash
test -f config/config.yaml && echo "CONFIG_OK"
test -x .venv/bin/python && echo "VENV_OK"
test -d "$HOME/Desktop/會議記錄/audio" && test -d "$HOME/Desktop/會議記錄/minutes" && echo "DATA_OK"
test -f "$HOME/.cursor/commands/minutes.md" && echo "CURSOR_OK"
```

另外確認這三個模型檔都在 `models/` 底下、大於 10MB，而且不是 0 bytes 或只下到一半的 `.partial`：

- whisper 模型（檔名以 `config/config.yaml` 的 `model:` 那一行為準）
- `models/ggml-silero-v5.1.2.bin`
- `models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx`
  聲紋模型若下載失敗，逐字稿仍可產生，但不會分講者。要把這件事寫進回報，不要當成全部成功。

`~/.cursor/commands/minutes.md` 裡的指示路徑必須是這台電腦上 `INSTRUCTIONS.md` 的**絕對路徑**，不能是 `__INSTRUCTIONS_PATH__`，也不能是別人的家目錄。

### 5. 回報給使用者（只回報這些）

```
安裝完成。

工具：<repo 絕對路徑>
會議資料：~/Desktop/會議記錄
  audio/   放要整理的錄音、螢幕錄影
  minutes/ 整理好的會議記錄與逐字稿
入口：~/.cursor/commands/minutes.md（以及偵測到的其他 AI 工具）

下一步：完全結束你的 AI 工具（不是只關視窗）再打開，在 AI 對話框輸入 /，確認清單裡有 minutes。
用法見同一資料夾的 2-usage.md。
```

有警告（例如聲紋模型沒下到）就寫在這份回報裡。不要把 `install.sh` 的整段輸出再貼一次，除非使用者問。

### Windows：給 AI 的安裝步驟

終端機是 PowerShell。下面的指令照抄，**不要**改用 bash、WSL 或 Git Bash。

**W0. 確認位置**

```powershell
Get-Location
Test-Path .\install.cmd; Test-Path .\INSTRUCTIONS.md
```

| 結果 | 做法 |
| --- | --- |
| 兩個不是都 `True` | 你不在工具資料夾。`Set-Location` 到含 `install.cmd` 的那一層再重跑。找不到就**停止**，請使用者照〈先把工具資料夾放到 `C:\meeting-minutes`〉準備好資料夾。 |
| 路徑裡有中文或全形字（例如 `桌面`、`文件`、中文使用者名稱） | **停止。** 請使用者照〈先把工具資料夾放到 `C:\meeting-minutes`〉搬位置，然後在新位置重開 AI 工具。不要自己搬檔案。 |

記下這個路徑，後面稱為 `<repo>`。

**W1. 用預設值安裝（不要改成互動問答）**

```powershell
.\install.cmd --yes
```

可重複執行。它**不會**問問題，一律用下面的預設：

| 項目 | `--yes` 的做法 |
| --- | --- |
| `ffmpeg`、`uv`、`git` | 缺了就用 `winget` 裝（`Gyan.FFmpeg`、`astral-sh.uv`、`Git.Git`）。Windows 可能跳出權限視窗，請使用者按「是」 |
| Python 環境 | 用 `uv` 建立 `.venv`（Python 3.12），依 `requirements.txt` 安裝 |
| 語音辨識程式 | 下載官方 `whisper-cli.exe`（v1.9.2）到 `tools\whisper-cpp\`，會核對檔案雜湊 |
| 模型 | `ggml-large-v3-turbo.bin`、VAD、聲紋三個，不存在才下載 |
| 會議資料夾 | 桌面的「會議記錄」，其下建 `audio`、`minutes`。已有設定就沿用原路徑 |
| AI 入口 | Cursor、Claude Code、Codex、VS Code **四個都裝** |

下載很久是正常的（模型 1.6GB）。指令逾時被中斷的話，再跑一次 `.\install.cmd --yes`，已完成的會跳過。
不要自己 `winget install` 一份清單、不要用 `pip` 直接裝、不要改 `config\glossary.txt`、不要 `git commit` 或 `git push`。

**W2. 逐項核對，缺一項就不要說裝好了**

```powershell
Test-Path .\config\config.yaml
Test-Path .\.venv\Scripts\python.exe
Test-Path (Join-Path ([Environment]::GetFolderPath('Desktop')) '會議記錄\minutes')
Test-Path "$env:USERPROFILE\.cursor\commands\minutes.md"
Get-ChildItem .\models | Select-Object Name, Length
```

前四行都要是 `True`。`models` 底下三個模型檔都要大於 10MB，不能有 `.partial`。聲紋模型沒下到要寫進回報。

**W3. 回報給使用者**

照上面 Mac 第 5 步的格式，把路徑換成這台電腦的，並加一句：

```
Windows 轉錄比 Mac 慢。5 分鐘以內的錄音可以直接交給 /minutes；更長的錄音照 2-usage.md〈長錄音：先在終端機轉〉先轉好。
```

### AI 不要做的事

- 不要執行 `--uninstall`，除非使用者明確說要移除
- 不要刪桌面的「會議記錄」資料夾
- 不要把錄音、逐字稿、會議記錄放進這個 git 資料夾
- 不要修改 `INSTRUCTIONS.md`、`templates/`、`config/glossary.txt`
- 不要為了「裝好」而跳過模型下載
