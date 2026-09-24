#!/usr/bin/env bash
#
# meeting-minutes 安裝腳本（SPEC §4.4）
#
# 設計要求：
#   - 可重複執行。再跑一次不會壞掉，用於更新設定或重裝入口檔。
#   - 互動安裝時每個動作都先問過。不擅自 brew install、不擅自 clone。
#   - ./install.sh --yes 不詢問，每題採用腳本裡的預設（見 1-安裝說明.md）。
#   - 所有動作都印出實際執行的指令。
#
# 用法：
#   ./install.sh                       完整互動安裝／更新
#   ./install.sh --yes                 非互動安裝：每題都用預設答案（給 AI 讀 1-安裝說明.md 後執行）
#   ./install.sh --update-entrypoints  只重裝入口檔（git pull 後用）
#   ./install.sh --redownload-model    強制重抓 whisper 模型
#   ./install.sh --uninstall           解除安裝
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 全部收在 repo 裡，不散落在家目錄——這樣 git clone 就是完整一份，
# 解除安裝＝刪資料夾，而且術語表可以靠 git 在同事之間共用。
# 理由與唯一的兩個例外寫在 scripts/paths.py 的 docstring。
CONFIG_DIR="$REPO_DIR/config"
CONFIG_PATH="$CONFIG_DIR/config.yaml"
MODELS_DIR_DEFAULT="$REPO_DIR/models"
BIN_WRAPPER="$REPO_DIR/bin/transcribe"
# 迭代優化準確率會用到的兩個地方（見 維護說明.md「校對迴圈」）
EVAL_CASES="$CONFIG_DIR/eval-cases.tsv"       # 迴歸集，learn.py 寫、eval.py 讀（進版控，全員共用）
CONFIDENCE_DIR="$REPO_DIR/var/confidence"     # whisper 原始信心度輸出（不進版控，可重建）
VAD_MODEL='ggml-silero-v5.1.2.bin'
SPEAKER_MODEL='3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx'
HF_WHISPER='https://huggingface.co/ggerganov/whisper.cpp/resolve/main'
HF_VAD='https://huggingface.co/ggml-org/whisper-vad/resolve/main'
HF_SPEAKER='https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main'
# 1 = 不詢問，ask／confirm 一律採用預設值。./install.sh --yes 會打開。
YES=0

# ── 輸出 ─────────────────────────────────────────────────────────────
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m[%s]\033[0m %s\n' "$1" "$2"; }

# 印出實際執行的指令再執行
sh_run() { printf '  $ %s\n' "$*"; "$@"; }

# ask <提示> <預設值> → 回聲使用者輸入或預設值
# --yes 時不讀鍵盤，直接回預設（印到 stderr，避免污染 $() 抓到的值）
ask() {
  local prompt="$1" default="${2-}" reply
  if [[ "$YES" == 1 ]]; then
    printf '  （預設）%s → %s\n' "$prompt" "${default:-（空）}" >&2
    printf '%s' "$default"
    return
  fi
  if [[ -n "$default" ]]; then
    read -r -p "  $prompt [$default]: " reply
    printf '%s' "${reply:-$default}"
  else
    read -r -p "  $prompt: " reply
    printf '%s' "$reply"
  fi
}

# confirm <提示> [Y|N 預設] → 0=是 1=否
confirm() {
  local prompt="$1" default="${2:-Y}" reply hint
  if [[ "$YES" == 1 ]]; then
    printf '  （預設）%s → %s\n' "$prompt" "$default" >&2
    [[ "$default" == Y ]]
    return
  fi
  [[ "$default" == Y ]] && hint='Y/n' || hint='y/N'
  read -r -p "  $prompt ($hint): " reply
  reply="${reply:-$default}"
  [[ "$reply" =~ ^[Yy] ]]
}

# 讀既有 config 的某個鍵（純文字解析，不依賴 yq）
cfg_get() {
  [[ -f "$CONFIG_PATH" ]] || return 0
  sed -n "s/^$1:[[:space:]]*//p" "$CONFIG_PATH" | head -1 | sed 's/^"//; s/"$//'
}

# ── 步驟 1：平台檢查 ──────────────────────────────────────────────────
check_macos() {
  [[ "$(uname -s)" == Darwin ]] || die "本工具僅支援 macOS（偵測到 $(uname -s)）。"
}

detect_arch() {
  if [[ "$(uname -m)" == arm64 ]]; then echo apple_silicon; else echo intel; fi
}

# ── 入口檔安裝 ───────────────────────────────────────────────────────
# entry_target <tool> → 該工具的入口檔絕對路徑
entry_target() {
  case "$1" in
    cursor)      echo "$HOME/.cursor/commands/minutes.md" ;;
    claude-code) echo "$HOME/.claude/commands/minutes.md" ;;
    codex)       echo "$HOME/.codex/prompts/minutes.md" ;;
    vscode)      echo "$HOME/Library/Application Support/Code/User/prompts/minutes.prompt.md" ;;
  esac
}

# tool_present <tool> → 0 表示這台機器看得到這個工具
tool_present() {
  case "$1" in
    cursor)      [[ -d /Applications/Cursor.app || -d "$HOME/.cursor" ]] ;;
    claude-code) command -v claude >/dev/null || [[ -d "$HOME/.claude" ]] ;;
    codex)       command -v codex  >/dev/null || [[ -d "$HOME/.codex"  ]] ;;
    vscode)      [[ -d "/Applications/Visual Studio Code.app" ]] || command -v code >/dev/null ;;
  esac
}

install_entrypoint() {
  local tool="$1" target header body
  target="$(entry_target "$tool")"
  case "$tool" in
    vscode) header="$REPO_DIR/entrypoints/_header.vscode.prompt.md" ;;
    *)      header="$REPO_DIR/entrypoints/_header.$tool.md" ;;
  esac
  body="$REPO_DIR/entrypoints/_body.md"
  [[ -f "$header" && -f "$body" ]] || { warn "缺少 $tool 的入口檔素材，跳過"; return 1; }

  sh_run mkdir -p "$(dirname "$target")"
  # 每次都重寫（idempotent）：git pull 後路徑或說明變了也會跟著更新
  {
    cat "$header"
    sed "s|__INSTRUCTIONS_PATH__|$REPO_DIR/INSTRUCTIONS.md|g" "$body" \
      | sed '/^<!--/,/-->$/d'
  } > "$target"
  ok "$tool → $target"
}

update_entrypoints_only() {
  step 更新 '重裝入口檔'
  local any=1
  for tool in cursor claude-code codex vscode; do
    if [[ -f "$(entry_target "$tool")" ]]; then
      install_entrypoint "$tool" && any=0
    fi
  done
  [[ $any -eq 0 ]] || warn '沒有找到任何已安裝的入口檔。請跑完整安裝：./install.sh'
  echo
  ok '完成。'
}

# ── 解除安裝 ─────────────────────────────────────────────────────────
do_uninstall() {
  bold 'meeting-minutes 解除安裝'
  # 因為一切都收在 repo 裡，真正需要「解除安裝」的只有放在家目錄的入口檔。
  # 其餘全部刪掉這個資料夾就沒了，所以這裡只負責清乾淨外面那幾個檔案。
  step 1/2 '移除各 AI 工具的入口檔（唯一放在資料夾外面的東西）'
  local found=1
  for tool in cursor claude-code codex vscode; do
    local t; t="$(entry_target "$tool")"
    [[ -f "$t" ]] && { sh_run rm -f "$t"; ok "已移除 $tool"; found=0; }
  done
  [[ $found -eq 0 ]] || info '沒有找到任何入口檔'

  step 2/2 '會議資料'
  local root; root="$(cfg_get data_root)"
  if [[ -n "$root" && -d "$root" ]]; then
    warn "會議資料夾：$root"
    confirm '刪除會議資料夾？（錄音、逐字稿、會議記錄都會消失）' N \
      && sh_run rm -rf "$root" || info '保留會議資料（預設）'
  fi

  echo
  ok '入口檔已清除。'
  echo
  bold '── 剩下的請你自己刪，因為要先確認兩件事 ──'
  info "工具本體、設定、模型、術語表全部在：$REPO_DIR"
  echo
  if [[ -d "$REPO_DIR/.git" ]]; then
    warn '刪掉之前先確認術語表已經 push 出去，否則你的校對成果只存在這台機器上：'
    info "  git -C \"$REPO_DIR\" status --short config/"
  fi
  info "確認完再刪：rm -rf \"$REPO_DIR\""
}

# ── 主流程 ───────────────────────────────────────────────────────────
main_install() {
  local redownload="${1:-no}"
  bold 'meeting-minutes 安裝'
  info "repo：$REPO_DIR"
  [[ -f "$CONFIG_PATH" ]] && info "偵測到既有設定：${CONFIG_PATH}（會顯示目前值供確認）"

  # 步驟 2–3：git 遠端與 repo 路徑
  # 這支腳本是從 repo 內執行的，所以 repo 已經在本機了。只記錄 remote 供更新用。
  step 2/12 'Git 遠端'
  local remote_default remote
  remote_default="$(cfg_get repo_remote)"
  if [[ -z "$remote_default" ]] && git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    remote_default="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
  fi
  info '留空＝「我已經 clone 好了，只用目前目錄」。這個值只用在日後 git pull。'
  remote="$(ask 'Git 遠端 URL（可留空）' "$remote_default")"

  step 3/12 'repo 路徑'
  info "使用目前目錄：$REPO_DIR"
  info '（要換位置請自己搬走 repo 再在新位置跑一次 ./install.sh）'

  # 步驟 4：架構與模型
  step 4/12 '架構與模型'
  local arch model model_default
  arch="$(detect_arch)"
  if [[ "$arch" == apple_silicon ]]; then
    model_default='ggml-large-v3-turbo.bin'
    ok "Apple Silicon（Metal 加速）→ 預設 $model_default"
  else
    model_default='ggml-medium.bin'
    ok "Intel → 預設 $model_default"
    info 'Intel 轉錄約「1 分鐘音訊 ≈ 60–90 秒」，large-v3-turbo 品質較好但更慢。'
  fi
  local model_current; model_current="$(cfg_get model)"
  model="$(ask '模型檔名' "${model_current:-$model_default}")"

  # 步驟 5：brew 依賴
  step 5/12 '系統依賴'
  local brew_ok=1
  command -v brew >/dev/null && brew_ok=0 || warn '找不到 brew。缺少的依賴要自己裝。'
  local missing=()
  for pkg in ffmpeg whisper-cpp uv; do
    local probe="$pkg"
    [[ "$pkg" == whisper-cpp ]] && probe=whisper-cli
    if command -v "$probe" >/dev/null; then ok "$pkg 已安裝"; else missing+=("$pkg"); fi
  done
  if (( ${#missing[@]} )); then
    warn "缺少：${missing[*]}"
    if [[ $brew_ok -eq 0 ]] && confirm "執行 brew install ${missing[*]}？"; then
      sh_run brew install "${missing[@]}" || die 'brew install 失敗，請自行處理後重跑。'
    else
      die "請先安裝：brew install ${missing[*]}"
    fi
  fi

  # 步驟 6：Python 環境
  step 6/12 'Python 環境'
  if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    ok '.venv 已存在'
  else
    sh_run uv venv "$REPO_DIR/.venv" || die 'uv venv 失敗'
  fi
  sh_run uv pip install --python "$REPO_DIR/.venv/bin/python" -r "$REPO_DIR/requirements.txt" \
    || die 'uv pip install 失敗'

  # 步驟 7：模型
  step 7/12 'Whisper 模型'
  local models_dir
  models_dir="$(cfg_get models_dir)"; models_dir="${models_dir:-$MODELS_DIR_DEFAULT}"
  sh_run mkdir -p "$models_dir"
  download_model() {  # <檔名> <base url>
    local name="$1" base="$2" dest="$models_dir/$1"
    if [[ -f "$dest" && "$redownload" != yes ]]; then
      ok "$name 已存在（$(du -h "$dest" | cut -f1)）"
      return 0
    fi
    if ! confirm "下載 ${name}？"; then warn "跳過 $name"; return 1; fi
    sh_run curl -L --fail --progress-bar -o "$dest.partial" "$base/$name" \
      && sh_run mv "$dest.partial" "$dest" \
      && ok "$name 下載完成" \
      || { rm -f "$dest.partial"; warn "$name 下載失敗"; return 1; }
  }
  download_model "$model" "$HF_WHISPER"
  info 'VAD 模型（Silero）用來在解碼前切掉非語音，是防幻聽最有效的一步。'
  download_model "$VAD_MODEL" "$HF_VAD"
  info '聲紋模型（3D-Speaker，28MB）用來標「這句是誰講的」。'
  info '跳過也能用，逐字稿只是不會有 說話者A／B／C。'
  download_model "$SPEAKER_MODEL" "$HF_SPEAKER"

  # 步驟 8：會議資料夾
  step 8/12 '會議資料夾'
  local root audio minutes
  local root_current; root_current="$(cfg_get data_root)"
  info '這是放你的錄音與會議記錄的地方。'
  info '刻意跟工具資料夾分開：會議內容是機密的，不該跟 .git 住在一起。'
  root="$(ask '會議資料根目錄' "${root_current:-$HOME/Desktop/會議記錄}")"
  root="${root/#\~/$HOME}"
  audio="$(cfg_get audio_dir)";     audio="${audio:-$root/audio}"
  minutes="$(cfg_get minutes_dir)"; minutes="${minutes:-$root/minutes}"
  sh_run mkdir -p "$audio" "$minutes"
  ok "audio / minutes 就緒"
  info '本工具不做保存期限、不自動刪除。檔案怎麼備份歸檔由你決定。'

  # 步驟 9：AI 工具入口
  step 9/12 'AI 工具入口（Layer 3）'
  local installed=()
  for tool in cursor claude-code codex vscode; do
    local label="$tool" present='未偵測到' default=N
    tool_present "$tool" && { present='已偵測到'; default=Y; }
    [[ "$tool" == cursor ]] && default=Y   # SPEC：預設安裝 Cursor
    if confirm "安裝 $label 入口？（${present}，$(entry_target "$tool")）" "$default"; then
      install_entrypoint "$tool" && installed+=("$tool")
    fi
  done

  # 步驟 10：寫入 config
  step 10/12 "寫入 $CONFIG_PATH"
  sh_run mkdir -p "$CONFIG_DIR"
  # 術語表現在是 repo 內的追蹤檔案，所以 clone 下來就已經有全隊累積的版本。
  # 只有在完全沒有的情況（例如不是從 git 拿到的）才從範例建立。
  if [[ ! -f "$CONFIG_DIR/glossary.txt" ]]; then
    sh_run cp "$REPO_DIR/config/glossary.txt.example" "$CONFIG_DIR/glossary.txt"
    ok '術語表已從範例建立'
  else
    ok "術語表已存在，保留不動（$(grep -cv '^\s*#\|^\s*$' "$CONFIG_DIR/glossary.txt" 2>/dev/null || echo 0) 條）"
  fi
  info '這份術語表是全隊共用的：它進版控，git pull 會拿到同事的校對成果，'
  info 'git push 會把你的分享出去。詳見 維護說明.md「校對迴圈」。'
  local notion_db; notion_db="$(cfg_get 'database_id')"
  cat > "$CONFIG_PATH" <<YAML
# <repo>/config/config.yaml
# 由 install.sh 產生（$(date '+%Y-%m-%d %H:%M')）。可手改，再跑 install.sh 會保留多數值。
# 這個檔案**不進版控**（每台機器路徑不同）。

repo_dir: "$REPO_DIR"
repo_remote: "$remote"
instructions_path: "$REPO_DIR/INSTRUCTIONS.md"
template_path: "$REPO_DIR/templates/minutes.md"
templates_dir: "$REPO_DIR/templates"

data_root: "$root"
audio_dir: "$audio"
# 舊鍵：逐字稿改放會議記錄同名資料夾。保留以免舊指令尋檔失敗。
transcripts_dir: "$minutes"
minutes_dir: "$minutes"

glossary_path: "$CONFIG_DIR/glossary.txt"

model: $model
models_dir: "$models_dir"
arch: $arch
python_path: "$REPO_DIR/.venv/bin/python"

# 可選；Notion 整合用。空 = 不自動寫入。
notion:
  database_id: "${notion_db}"
YAML
  ok '設定已寫入'

  # 步驟 11：transcribe 包裝
  step 11/12 'transcribe 命令'
  # 包裝腳本放在 repo 內（$REPO_DIR/bin），不是 ~/.local/bin——一切收在資料夾裡。
  sh_run mkdir -p "$(dirname "$BIN_WRAPPER")"
  cat > "$BIN_WRAPPER" <<WRAP
#!/usr/bin/env bash
exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/scripts/transcribe.py" "\$@"
WRAP
  sh_run chmod +x "$BIN_WRAPPER"
  ok "已建立 $BIN_WRAPPER"
  info '主要用法是在 AI 工具裡下 /minutes，不需要這個命令。'
  info '想在任何目錄直接打 transcribe 的話，加一行進 ~/.zshrc（這會動到家目錄，所以不自動做）：'
  info "  export PATH=\"$(dirname "$BIN_WRAPPER"):\$PATH\""

  # 步驟 12：摘要
  step 12/12 '完成'
  echo
  bold '── 安裝結果 ──'
  info "工具資料夾　$REPO_DIR"
  info "  ├─ config/config.yaml　本機設定（不進版控）"
  info "  ├─ config/glossary.txt　術語表（進版控，全隊共用）"
  info "  ├─ config/eval-cases.tsv　迴歸集（進版控，全隊共用）"
  info "  ├─ models/$model"
  info "  ├─ models/$SPEAKER_MODEL　聲紋（標說話者）"
  info "  └─ var/confidence/　信心度快取（可重建）"
  echo
  info "會議資料夾　$root　（刻意放在工具資料夾外面）"
  info "  ├─ 待轉錄音　$audio"
  info "  └─ 會議記錄　$minutes"
  info "      每場一份 .md；逐字稿／校對／畫面在同名資料夾"
  if (( ${#installed[@]} )); then
    echo
    info "入口檔　　${installed[*]}（指令：/minutes）"
    info '（入口檔是唯一放在家目錄的東西，因為那是各工具唯一會找的位置）'
  else
    warn '沒有安裝任何入口檔——只能走保底方案（見下）'
  fi
  echo
  bold '── 怎麼用（詳見 2-使用流程.md）──'
  info '把音檔或 mp4、相關的 PPT／PDF／Excel，以及參加者是誰、有幾位，一起交給 AI。'
  info '它會轉逐字稿、自己 review 一次，再交出會議記錄和一份聽不清的人工表（那張表不必填）。'
  if [[ "$arch" == apple_silicon ]]; then
    info '短錄音（約 60 分鐘以內）：直接在 Cursor 下 /minutes，把檔案拖進同一則訊息。'
    info '長錄音：先在 Terminal 轉，再拿逐字稿回去整理。'
  else
    info 'Intel Mac 轉錄很慢（1 分鐘音訊 ≈ 60–90 秒）。'
    info '一律先在 Terminal 轉完，再 /minutes <逐字稿.md>——不要在對話裡等。'
  fi
  echo
  info "  transcribe \"$audio/會議.m4a\""
  info '  然後：/minutes <逐字稿.md>'
  echo
  bold '── 怎麼讓它越用越準（每次約 10 分鐘，很值得）──'
  info '轉錄時會順手產生 <逐字稿>.review.md，裡面只挑出 whisper 最沒把握的幾十行。'
  info '把「應該是」那欄填成正確的整句（聽不出來就留空），存檔後把檔拖回對話（或說已校對）。'
  info '詞表會自動更新。想知道有沒有真的變準，重轉一次然後：'
  echo
  info "  \"$REPO_DIR/.venv/bin/python\" \"$REPO_DIR/scripts/eval.py\" <新逐字稿> <舊逐字稿>"
  echo
  info '★ 術語表是全隊共用的，記得 push 出去，不然只有你自己受益：'
  info "  git -C \"$REPO_DIR\" add config/glossary.txt config/eval-cases.tsv && git -C \"$REPO_DIR\" commit -m 詞表 && git -C \"$REPO_DIR\" pull --rebase && git -C \"$REPO_DIR\" push"
  info '  （learn.py 跑完也會提示你這幾行）'
  echo
  bold '── 保底方案（任何工具的 slash command 掛了都能用）──'
  info '1. 手動跑轉錄取得逐字稿'
  info "2. 把 $REPO_DIR/INSTRUCTIONS.md 的內容貼給 AI，附上逐字稿"
  info '這條路不依賴任何工具的自訂指令機制，一定行得通。'
  echo
  bold '── git pull 之後 ──'
  info './install.sh --update-entrypoints   # 否則入口檔可能還指著舊說明'
  echo
}

# ── 參數 ─────────────────────────────────────────────────────────────
check_macos
case "${1-}" in
  --yes|--non-interactive) YES=1; main_install no ;;
  --uninstall)           do_uninstall ;;
  --update-entrypoints)  update_entrypoints_only ;;
  --redownload-model)    main_install yes ;;
  ''|--install)          main_install no ;;
  -h|--help)
    sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^#\{1\} \{0,1\}//' ;;
  *) die "未知參數：$1（用 --help 看用法）" ;;
esac
