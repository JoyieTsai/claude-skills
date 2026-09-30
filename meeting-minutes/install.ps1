#
# meeting-minutes Windows 安裝腳本（install.sh 的 Windows 版）
#
# 不要直接執行這個檔，改用同一層的 install.cmd：它會用「允許執行腳本」的方式
# 叫起 PowerShell，同事不必自己去改 Windows 的執行原則。
#
# 設計要求（跟 install.sh 一樣）：
#   - 可重複執行。再跑一次不會壞掉，用於更新設定或重裝入口檔。
#   - 互動安裝時每個動作都先問過。
#   - install.cmd --yes 不詢問，每題採用腳本裡的預設（見 1-install.md）。
#   - 所有動作都印出實際執行的指令。
#
# 用法：
#   install.cmd                       完整互動安裝／更新
#   install.cmd --yes                 非互動安裝：每題都用預設答案（給 AI 讀 1-install.md 後執行）
#   install.cmd --update-entrypoints  只重裝入口檔（git pull 後用）
#   install.cmd --redownload-model    強制重抓 whisper 模型
#   install.cmd --uninstall           解除安裝
#
# 跟 Mac 版不同的地方（理由見 maintenance.md「Windows 版」）：
#   - 沒有 Homebrew：ffmpeg、uv、git 用 winget 裝；whisper-cli.exe 直接下載官方
#     編好的版本放進 tools\（CPU 版，任何電腦都能跑，只是比 Mac 慢）。
#   - 工具資料夾的路徑不能有中文：Windows 版 whisper 讀不到中文路徑的模型檔。
#
# 本檔必須存成「UTF-8 含 BOM」，否則 Windows 內建的 PowerShell 5.1 會把中文讀成亂碼。

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
# Windows 10 舊版預設只開 TLS 1.0，連 GitHub／Hugging Face 會失敗
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RepoDir = Split-Path -Parent $PSCommandPath
$ConfigDir = Join-Path $RepoDir 'config'
$ConfigPath = Join-Path $ConfigDir 'config.yaml'
$ModelsDirDefault = Join-Path $RepoDir 'models'
$ToolsDir = Join-Path $RepoDir 'tools'
$VenvPython = Join-Path $RepoDir '.venv\Scripts\python.exe'
$BinWrapper = Join-Path $RepoDir 'bin\transcribe.cmd'

$WhisperModel = 'ggml-large-v3-turbo.bin'
$VadModel = 'ggml-silero-v5.1.2.bin'
$SpeakerModel = '3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx'
$HfWhisper = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main'
$HfVad = 'https://huggingface.co/ggml-org/whisper-vad/resolve/main'
$HfSpeaker = 'https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main'
# 跟 Mac 的 brew whisper-cpp 同一版。換版本要一起換 sha256（GitHub release 頁面有列）。
$WhisperZipUrl = 'https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/whisper-bin-x64.zip'
$WhisperZipSha256 = '49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a'

$Yes = $false

# ── 輸出 ─────────────────────────────────────────────────────────────
function Bold($msg) { Write-Host $msg -ForegroundColor White }
function Info($msg) { Write-Host "  $msg" }
function Ok($msg)   { Write-Host "  √ $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "× $msg" -ForegroundColor Red; exit 1 }
function Step($n, $msg) { Write-Host ''; Write-Host "[$n] $msg" -ForegroundColor White }

# 印出實際執行的指令再執行，回傳是否成功
function Run {
    param([string]$Exe, [string[]]$Arguments)
    $shown = ($Arguments | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
    Write-Host "  > $Exe $shown" -ForegroundColor DarkGray
    # 輸出直接送到畫面：留在管線裡的話會混進回傳值，if (Run …) 就永遠成立
    & $Exe @Arguments | Out-Host
    return ($LASTEXITCODE -eq 0)
}

# --yes 時不讀鍵盤，直接回預設
function Ask($prompt, $default) {
    if ($Yes) {
        $shown = if ($default) { $default } else { '（空）' }
        Info "（預設）$prompt → $shown"
        return $default
    }
    $reply = if ($default) { Read-Host "  $prompt [$default]" } else { Read-Host "  $prompt" }
    if ([string]::IsNullOrWhiteSpace($reply)) { return $default }
    return $reply.Trim()
}

function Confirm($prompt, $default = 'Y') {
    if ($Yes) {
        Info "（預設）$prompt → $default"
        return ($default -eq 'Y')
    }
    $hint = if ($default -eq 'Y') { 'Y/n' } else { 'y/N' }
    $reply = Read-Host "  $prompt ($hint)"
    if ([string]::IsNullOrWhiteSpace($reply)) { $reply = $default }
    return ($reply -match '^[Yy]')
}

# 讀既有 config 的某個鍵（純文字解析）
function CfgGet($key) {
    if (-not (Test-Path $ConfigPath)) { return '' }
    foreach ($line in [IO.File]::ReadAllLines($ConfigPath, [Text.Encoding]::UTF8)) {
        if ($line -match "^${key}:\s*(.*)$") { return $Matches[1].Trim().Trim('"') }
    }
    return ''
}

# 寫 UTF-8「不含」BOM。PowerShell 5.1 的 Set-Content -Encoding UTF8 會加 BOM，
# 入口檔開頭多一個 BOM 會讓 Claude Code 讀不到 --- 開頭的設定區。
function WriteUtf8($path, $text) {
    $dir = Split-Path -Parent $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
}

# YAML 的雙引號字串會把 \U 當跳脫字元，所以 Windows 路徑一律寫成正斜線
function Fwd($p) { return ($p -replace '\\', '/') }

# winget 裝完的程式，這個視窗要重讀一次 PATH 才找得到
function RefreshPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function FindExe($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

# ── 入口檔 ───────────────────────────────────────────────────────────
function EntryTarget($tool) {
    switch ($tool) {
        'cursor'      { return Join-Path $env:USERPROFILE '.cursor\commands\minutes.md' }
        'claude-code' { return Join-Path $env:USERPROFILE '.claude\commands\minutes.md' }
        'codex'       { return Join-Path $env:USERPROFILE '.codex\prompts\minutes.md' }
        'vscode'      { return Join-Path $env:APPDATA 'Code\User\prompts\minutes.prompt.md' }
    }
}

$AllTools = @('cursor', 'claude-code', 'codex', 'vscode')

function InstallEntrypoint($tool) {
    $target = EntryTarget $tool
    $headerName = if ($tool -eq 'vscode') { '_header.vscode.prompt.md' } else { "_header.$tool.md" }
    $header = Join-Path $RepoDir "entrypoints\$headerName"
    $body = Join-Path $RepoDir 'entrypoints\_body.md'
    if (-not ((Test-Path $header) -and (Test-Path $body))) { Warn "缺少 $tool 的入口檔素材，跳過"; return $false }

    $instructions = Fwd (Join-Path $RepoDir 'INSTRUCTIONS.md')
    $bodyText = [IO.File]::ReadAllText($body, [Text.Encoding]::UTF8)
    $bodyText = $bodyText.Replace('__INSTRUCTIONS_PATH__', $instructions)
    # 拿掉開頭那段給維護者看的 HTML 註解（install.sh 用 sed 做同一件事）
    $bodyText = [regex]::Replace($bodyText, '(?s)^<!--.*?-->\r?\n', '')
    $headerText = [IO.File]::ReadAllText($header, [Text.Encoding]::UTF8)
    # 每次都重寫：git pull 後路徑或說明變了也會跟著更新
    WriteUtf8 $target ($headerText + $bodyText)
    Ok "$tool → $target"
    return $true
}

function UpdateEntrypointsOnly {
    Step '更新' '重裝入口檔'
    $any = $false
    foreach ($tool in $AllTools) {
        if (Test-Path (EntryTarget $tool)) { if (InstallEntrypoint $tool) { $any = $true } }
    }
    if (-not $any) { Warn '沒有找到任何已安裝的入口檔。請跑完整安裝：install.cmd' }
    Write-Host ''
    Ok '完成。'
}

# ── 解除安裝 ─────────────────────────────────────────────────────────
function DoUninstall {
    Bold 'meeting-minutes 解除安裝'
    Step '1/2' '移除各 AI 工具的入口檔（唯一放在資料夾外面的東西）'
    $found = $false
    foreach ($tool in $AllTools) {
        $t = EntryTarget $tool
        if (Test-Path $t) { Remove-Item -Force $t; Ok "已移除 $tool"; $found = $true }
    }
    if (-not $found) { Info '沒有找到任何入口檔' }

    Step '2/2' '會議資料'
    $root = CfgGet 'data_root'
    if ($root -and (Test-Path $root)) {
        Warn "會議資料夾：$root"
        if (Confirm '刪除會議資料夾？（錄音、逐字稿、會議記錄都會消失）' 'N') {
            Remove-Item -Recurse -Force $root
            Ok '已刪除'
        } else { Info '保留會議資料（預設）' }
    }
    Write-Host ''
    Ok '入口檔已清除。'
    Info "工具本體、設定、模型、術語表全部在：$RepoDir"
    if (Test-Path (Join-Path $RepoDir '.git')) {
        Warn '刪掉之前先確認術語表已經 push 出去，否則你的校對成果只存在這台機器上：'
        Info "  git -C `"$RepoDir`" status --short config/"
    }
    Info '確認完再把整個工具資料夾刪掉即可。'
}

# ── 下載 ─────────────────────────────────────────────────────────────
# 先下載到 .partial，完整了才改名；中途斷線再跑一次會重下
function Download($url, $dest) {
    $partial = "$dest.partial"
    if (Run 'curl.exe' @('-L', '--fail', '--progress-bar', '-o', $partial, $url)) {
        Move-Item -Force $partial $dest
        return $true
    }
    Remove-Item -Force $partial -ErrorAction SilentlyContinue
    return $false
}

# ── 主流程 ───────────────────────────────────────────────────────────
function MainInstall($redownload) {
    Bold 'meeting-minutes 安裝（Windows）'
    Info "工具資料夾：$RepoDir"
    if (Test-Path $ConfigPath) { Info "偵測到既有設定：$ConfigPath（會沿用目前的值）" }

    Step '1/11' '檢查工具資料夾位置'
    # Windows 版 whisper 收到的路徑會被轉成系統編碼，中文路徑讀不到模型檔。
    # 這是 whisper 那邊的限制，腳本這邊繞不過去，只能請使用者搬位置。
    if ($RepoDir -match '[^\x00-\x7F]') {
        Die "工具資料夾的路徑裡有中文或特殊字元：$RepoDir`n  請把整個資料夾搬到 C:\meeting-minutes，再到新位置重跑 install.cmd。"
    }
    Ok '路徑沒有中文'
    if (-not (FindExe 'curl.exe')) { Die '找不到 curl.exe。這台 Windows 太舊（需要 Windows 10 1803 以後），請先更新 Windows。' }

    Step '2/11' 'Git 遠端'
    $remote = CfgGet 'repo_remote'
    if (-not $remote -and (FindExe 'git') -and (Test-Path (Join-Path $RepoDir '.git'))) {
        $remote = (& git -C $RepoDir remote get-url origin 2>$null)
    }
    Info '留空＝「我已經有這個資料夾了」。這個值只用在日後 git pull。'
    $remote = Ask 'Git 遠端 URL（可留空）' $remote

    Step '3/11' '系統元件（ffmpeg、uv、git）'
    $winget = FindExe 'winget'
    if (-not $winget) { Warn '找不到 winget（Windows 內建的「應用程式安裝程式」）。缺少的元件要自己裝。' }
    $packages = @(
        @{ Name = 'ffmpeg'; Probe = 'ffmpeg'; Id = 'Gyan.FFmpeg'; Required = $true },
        @{ Name = 'uv'; Probe = 'uv'; Id = 'astral-sh.uv'; Required = $true },
        @{ Name = 'git'; Probe = 'git'; Id = 'Git.Git'; Required = $false }
    )
    foreach ($p in $packages) {
        if (FindExe $p.Probe) { Ok "$($p.Name) 已安裝"; continue }
        Warn "缺少 $($p.Name)"
        if ($winget -and (Confirm "用 winget 安裝 $($p.Name)？")) {
            Run 'winget' @('install', '--id', $p.Id, '-e', '--silent', '--accept-source-agreements', '--accept-package-agreements') | Out-Null
            RefreshPath
        }
        if (FindExe $p.Probe) { Ok "$($p.Name) 安裝完成" }
        elseif ($p.Required) { Die "還是找不到 $($p.Name)。請關掉這個視窗重開再跑一次 install.cmd；還是不行，把上面的訊息整段傳給 Zoe。" }
        else { Warn "沒有 $($p.Name) 也能用，只是之後不能用 git pull 更新、不能分享詞彙表。" }
    }
    $ffmpeg = FindExe 'ffmpeg'
    $ffprobe = Join-Path (Split-Path -Parent $ffmpeg) 'ffprobe.exe'
    if (-not (Test-Path $ffprobe)) { $ffprobe = FindExe 'ffprobe' }

    Step '4/11' 'Python 環境'
    if (Test-Path $VenvPython) { Ok '.venv 已存在' }
    elseif (-not (Run 'uv' @('venv', '--python', '3.12', (Join-Path $RepoDir '.venv')))) { Die 'uv venv 失敗' }
    if (-not (Run 'uv' @('pip', 'install', '--python', $VenvPython, '-r', (Join-Path $RepoDir 'requirements.txt')))) {
        Die 'uv pip install 失敗'
    }

    Step '5/11' '語音辨識程式（whisper-cli.exe）'
    $whisperDir = Join-Path $ToolsDir 'whisper-cpp'
    $whisper = Get-ChildItem -Path $whisperDir -Recurse -Filter 'whisper-cli.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($whisper) { Ok "已存在：$($whisper.FullName)" }
    else {
        New-Item -ItemType Directory -Force -Path $whisperDir | Out-Null
        $zip = Join-Path $ToolsDir 'whisper-bin-x64.zip'
        if (-not (Download $WhisperZipUrl $zip)) { Die 'whisper 下載失敗。檢查網路後再跑一次 install.cmd。' }
        $hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
        if ($hash -ne $WhisperZipSha256) {
            Remove-Item -Force $zip
            Die "whisper 下載的檔案不完整或被換過（sha256 不符）。再跑一次 install.cmd。"
        }
        Expand-Archive -Force -Path $zip -DestinationPath $whisperDir
        Remove-Item -Force $zip
        $whisper = Get-ChildItem -Path $whisperDir -Recurse -Filter 'whisper-cli.exe' | Select-Object -First 1
        if (-not $whisper) { Die '解壓縮後找不到 whisper-cli.exe' }
        Ok "已安裝：$($whisper.FullName)"
    }
    # 官方版需要微軟的 VC++ 執行元件。大部分電腦已經有；沒有的話一執行就會失敗。
    & $whisper.FullName --help *> $null
    if ($LASTEXITCODE -ne 0) {
        Warn 'whisper-cli.exe 無法執行，可能缺少 Microsoft Visual C++ 執行元件'
        if ($winget -and (Confirm '用 winget 安裝 Microsoft Visual C++ 執行元件？')) {
            Run 'winget' @('install', '--id', 'Microsoft.VCRedist.2015+.x64', '-e', '--silent', '--accept-source-agreements', '--accept-package-agreements') | Out-Null
        }
        & $whisper.FullName --help *> $null
        if ($LASTEXITCODE -ne 0) { Die 'whisper-cli.exe 還是無法執行。把上面的訊息整段傳給 Zoe。' }
    }
    Ok 'whisper-cli.exe 可以執行'

    Step '6/11' '模型'
    $model = CfgGet 'model'
    if (-not $model) { $model = $WhisperModel }
    $model = Ask '模型檔名' $model
    $modelsDir = CfgGet 'models_dir'
    if (-not $modelsDir) { $modelsDir = $ModelsDirDefault }
    New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null
    $failed = @()
    $downloads = @(
        @{ Name = $model; Base = $HfWhisper; Note = '語音辨識模型，約 1.6GB，最久的一步' },
        @{ Name = $VadModel; Base = $HfVad; Note = '用來略過沒人講話的段落，防止亂寫字' },
        @{ Name = $SpeakerModel; Base = $HfSpeaker; Note = '聲紋模型，用來分「這句是誰講的」。跳過也能用，只是分不出講者' }
    )
    foreach ($d in $downloads) {
        $dest = Join-Path $modelsDir $d.Name
        if ((Test-Path $dest) -and ($redownload -ne 'yes')) {
            Ok ("{0} 已存在（{1:N0} MB）" -f $d.Name, ((Get-Item $dest).Length / 1MB))
            continue
        }
        Info $d.Note
        if (-not (Confirm "下載 $($d.Name)？")) { Warn "跳過 $($d.Name)"; $failed += $d.Name; continue }
        if (Download "$($d.Base)/$($d.Name)" $dest) { Ok "$($d.Name) 下載完成" }
        else { Warn "$($d.Name) 下載失敗"; $failed += $d.Name }
    }

    Step '7/11' '會議資料夾'
    Info '這是放你的錄音與會議記錄的地方。'
    Info '刻意跟工具資料夾分開：會議內容是機密的，不該跟 .git 住在一起。'
    $root = CfgGet 'data_root'
    if (-not $root) { $root = Join-Path ([Environment]::GetFolderPath('Desktop')) '會議記錄' }
    $root = Ask '會議資料根目錄' $root
    $audio = CfgGet 'audio_dir'; if (-not $audio) { $audio = Join-Path $root 'audio' }
    $minutes = CfgGet 'minutes_dir'; if (-not $minutes) { $minutes = Join-Path $root 'minutes' }
    New-Item -ItemType Directory -Force -Path $audio, $minutes | Out-Null
    Ok 'audio / minutes 就緒'
    Info '本工具不做保存期限、不自動刪除。檔案怎麼備份歸檔由你決定。'

    Step '8/11' 'AI 工具入口（/minutes 指令）'
    # Mac 版只裝偵測得到的工具；Windows 同事用的工具比較雜，偵測也不可靠，
    # 所以四個全裝。沒用到的那幾個只是多一個小檔案，不影響任何東西。
    $installed = @()
    foreach ($tool in $AllTools) {
        if (Confirm "安裝 $tool 入口？（$(EntryTarget $tool)）" 'Y') {
            if (InstallEntrypoint $tool) { $installed += $tool }
        }
    }

    Step '9/11' "寫入 $ConfigPath"
    $glossary = Join-Path $ConfigDir 'glossary.txt'
    if (-not (Test-Path $glossary)) {
        Copy-Item (Join-Path $ConfigDir 'glossary.txt.example') $glossary
        Ok '術語表已從範例建立'
    } else { Ok '術語表已存在，保留不動' }
    Info '這份術語表是全隊共用的：它進版控，git pull 會拿到同事的校對成果，'
    Info 'git push 會把你的分享出去。詳見 maintenance.md「校對迴圈」。'
    $notionDb = CfgGet 'database_id'
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm'
    $repoF = Fwd $RepoDir
    $yaml = @"
# <repo>/config/config.yaml
# 由 install.ps1 產生（$now）。可手改，再跑 install.cmd 會保留多數值。
# 這個檔案**不進版控**（每台機器路徑不同）。路徑一律用正斜線（YAML 會把 \U 當跳脫字元）。

repo_dir: "$repoF"
repo_remote: "$remote"
instructions_path: "$repoF/INSTRUCTIONS.md"
template_path: "$repoF/templates/minutes.md"
templates_dir: "$repoF/templates"

data_root: "$(Fwd $root)"
audio_dir: "$(Fwd $audio)"
# 舊鍵：逐字稿改放會議記錄同名資料夾。保留以免舊指令尋檔失敗。
transcripts_dir: "$(Fwd $minutes)"
minutes_dir: "$(Fwd $minutes)"

glossary_path: "$(Fwd $glossary)"

model: $model
models_dir: "$(Fwd $modelsDir)"
arch: windows

# 執行檔的絕對路徑。winget 裝的東西要等 AI 工具重開才進 PATH，寫在這裡就不用等。
python_path: "$(Fwd $VenvPython)"
ffmpeg: "$(Fwd $ffmpeg)"
ffprobe: "$(Fwd $ffprobe)"
whisper_cli: "$(Fwd $whisper.FullName)"

# 可選；Notion 整合用。空 = 不自動寫入。
notion:
  database_id: "$notionDb"
"@
    WriteUtf8 $ConfigPath (($yaml -replace "`r`n", "`n") + "`n")
    Ok '設定已寫入'

    Step '10/11' 'transcribe 命令'
    $wrapper = "@echo off`r`n`"%~dp0..\.venv\Scripts\python.exe`" `"%~dp0..\scripts\transcribe.py`" %*`r`n"
    WriteUtf8 $BinWrapper $wrapper
    Ok "已建立 $BinWrapper"
    Info '主要用法是在 AI 工具裡下 /minutes，不需要這個命令。'

    Step '11/11' '完成'
    Write-Host ''
    Bold '── 安裝結果 ──'
    Info "工具資料夾　$RepoDir"
    Info "會議資料夾　$root"
    Info "  ├─ 待轉錄音　$audio"
    Info "  └─ 會議記錄　$minutes"
    if ($installed.Count) { Info "入口檔　　　$($installed -join '、')（指令：/minutes）" }
    else { Warn '沒有安裝任何入口檔' }
    if ($failed.Count) { Warn "沒有下載成功：$($failed -join '、')。再跑一次 install.cmd --yes 會補下載。" }
    Write-Host ''
    Bold '── 怎麼用（詳見 2-usage.md）──'
    Info 'Windows 沒有 Mac 的晶片加速，轉錄比較慢（1 分鐘錄音大約要 1–3 分鐘）。'
    Info '10 分鐘以內的錄音：直接在 AI 對話框輸入 /minutes，附上錄音。'
    Info '更長的錄音：先在這個資料夾執行下面這行，轉完再把逐字稿交給 /minutes：'
    Info "  `"$BinWrapper`" `"$audio\會議.m4a`""
    Write-Host ''
    Bold '── git pull 之後 ──'
    Info 'install.cmd --update-entrypoints   # 否則入口檔可能還指著舊說明'
    Write-Host ''
}

# ── 參數 ─────────────────────────────────────────────────────────────
$mode = if ($args.Count) { $args[0] } else { '' }
switch ($mode) {
    { $_ -in '--yes', '--non-interactive' } { $Yes = $true; MainInstall 'no' }
    '--uninstall' { DoUninstall }
    '--update-entrypoints' { UpdateEntrypointsOnly }
    '--redownload-model' { MainInstall 'yes' }
    { $_ -in '', '--install' } { MainInstall 'no' }
    { $_ -in '-h', '--help' } {
        Get-Content -Encoding UTF8 $PSCommandPath | Select-Object -Skip 1 -First 18 | ForEach-Object { $_ -replace '^# ?', '' }
    }
    default { Die "未知參數：$mode（用 --help 看用法）" }
}
