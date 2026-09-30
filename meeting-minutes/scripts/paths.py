#!/usr/bin/env python3
"""所有路徑的單一來源。全部相對於 repo，不散落在使用者家目錄。

**為什麼不用 ~/.config 與 ~/.local/share**（雖然那是 macOS／Unix 慣例）：
這個工具要發給同事，而且術語表要共用。東西全部待在 repo 裡的話：

  - 拿到的人 `git clone` 就有完整的一份，不必先在家目錄長出四個資料夾
  - 術語表與迴歸集是 repo 內的追蹤檔案，**git 本身就是共用機制**：
    一行一條規則的純文字，不同人各加幾行 `git pull --rebase` 就合好了，
    不需要自己寫 merge 邏輯
  - 解除安裝＝刪掉這個資料夾，不會有殘留

**唯一兩個例外**（本來就不可能收進來）：
  1. 各家 AI 工具的入口檔——必須放在 ~/.cursor、~/.claude、~/.codex 底下，
     因為那是它們唯一會去找的地方。`./install.sh --uninstall` 會清掉。
  2. 會議資料（音檔／逐字稿／會議記錄）——**刻意**不在 repo 裡。那是機密內容，
     不能跟 .git 同住一個資料夾，一個 `git add -f` 或改錯 .gitignore 就外洩。
     它的位置由 config.yaml 的 data_root 決定，預設在桌面。
"""

from __future__ import annotations

import sys
from pathlib import Path

IS_WINDOWS = sys.platform == 'win32'

# Windows 主控台預設是系統編碼（台灣是 Big5／cp950），印到 ✓、⚠️、⟦⟧ 這類字元會直接
# UnicodeEncodeError 當掉。每支腳本都會 import 這個模組，所以統一在這裡改成 UTF-8。
if IS_WINDOWS:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8', errors='replace')

REPO_DIR = Path(__file__).resolve().parent.parent

# 進 git、全員共用的設定
CONFIG_DIR = REPO_DIR / 'config'
GLOSSARY_PATH = CONFIG_DIR / 'glossary.txt'  # 術語表：校對成果就累積在這
CASES_PATH = CONFIG_DIR / 'eval-cases.tsv'  # 迴歸集：eval.py 的考題

# 不進 git：每台機器不一樣，或體積太大，或可重建
CONFIG_PATH = CONFIG_DIR / 'config.yaml'  # 本機路徑設定
MODELS_DIR = REPO_DIR / 'models'  # whisper 模型，1.6GB
VAR_DIR = REPO_DIR / 'var'
CONFIDENCE_DIR = VAR_DIR / 'confidence'  # whisper 原始信心度輸出（快取）
BIN_DIR = REPO_DIR / 'bin'  # transcribe 包裝腳本
# Windows 沒有 Homebrew，whisper-cli.exe 由 install.ps1 下載到這裡
TOOLS_DIR = REPO_DIR / 'tools'

# 進 git 的靜態資料
# 英文字表：Webster's 2nd（1934，版權已失效），就是 macOS 的 /usr/share/dict/words。
# 附在 repo 裡是因為 Windows 沒有這個檔。
ENGLISH_WORDS_PATH = REPO_DIR / 'data' / 'english-words.txt'

# .venv 裡的 Python。印給使用者或 AI 複製的指令都用這個，不要寫死 .venv/bin/python
PYTHON = REPO_DIR / '.venv' / ('Scripts/python.exe' if IS_WINDOWS else 'bin/python')
