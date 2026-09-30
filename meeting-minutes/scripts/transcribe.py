#!/usr/bin/env python3
"""Meeting audio/video → Traditional Chinese transcript (Layer 1)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover
    OpenCC = None  # type: ignore[misc, assignment]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diarize  # noqa: E402  同目錄模組：每句標講者 A／B／C
import frames  # noqa: E402  同目錄模組：螢幕錄影關鍵畫面
import paths  # noqa: E402  同目錄模組：所有路徑的單一來源
import review  # noqa: E402  同目錄模組：待校對清單的產生邏輯

CONFIG_PATH = paths.CONFIG_PATH
DEFAULT_MODELS_DIR = paths.MODELS_DIR
DEFAULT_GLOSSARY = paths.GLOSSARY_PATH
CONFIDENCE_CACHE = paths.CONFIDENCE_DIR
REPO_ROOT = paths.REPO_DIR
PROMPT_CHAR_BUDGET = 400  # whisper initial prompt is token-capped; keep short

# Hallucination-loop post-processing
REPEAT_COLLAPSE_MIN = 3  # consecutive near-identical lines before collapsing
QUALITY_WARN_STREAK = 10  # single collapsed streak this long → warn
QUALITY_WARN_COLLAPSED_LINES = 20  # total removed lines → warn
QUALITY_WARN_RATIO = 0.05  # removed / original ≥ 5% → warn
WHISPER_MAX_CONTEXT = 64  # limit previous-text carryover (helps stop copy loops)

# VAD: strip non-speech before decoding. Silence/room-noise stretches are the
# main trigger for whisper's repetition loops, so this prevents hallucinations
# at the source rather than folding them away afterwards.
DEFAULT_VAD_MODEL = 'ggml-silero-v5.1.2.bin'
# 0.25, not silero's 0.5: measured on a 37:54 screen-share training recording,
# 0.5 dropped 26% of real speech (coverage vs Apple SpeechAnalyzer 88%),
# 0.25 recovered it to 94%. Going lower (0.15) buys nothing and starts merging
# lines into 100+ char paragraphs, which loses timestamp precision.
VAD_THRESHOLD = '0.25'
VAD_MIN_SILENCE_MS = '300'  # whisper default 100ms splits mid-sentence
VAD_SPEECH_PAD_MS = '400'  # whisper default 30ms clips word onsets


class TranscribeError(Exception):
    pass


@dataclass
class CollapseEvent:
    start_ms: int
    end_ms: int
    count: int
    sample: str


@dataclass
class QualityReport:
    original_lines: int
    kept_lines: int
    collapsed_removed: int
    events: list[CollapseEvent]

    @property
    def warned(self) -> bool:
        if self.collapsed_removed >= QUALITY_WARN_COLLAPSED_LINES:
            return True
        if self.original_lines and (self.collapsed_removed / self.original_lines) >= QUALITY_WARN_RATIO:
            return True
        return any(e.count >= QUALITY_WARN_STREAK for e in self.events)


def die(msg: str, code: int = 1) -> None:
    print(f'錯誤：{msg}', file=sys.stderr)
    raise SystemExit(code)


def check_platform() -> None:
    if platform.system() not in ('Darwin', 'Windows'):
        die('僅支援 macOS 與 Windows。')


def detect_arch() -> str:
    if paths.IS_WINDOWS:
        return 'windows'
    machine = platform.machine().lower()
    if machine in ('arm64', 'aarch64'):
        return 'apple_silicon'
    return 'intel'


def default_model_name(arch: str) -> str:
    # Windows 也用 turbo：沒有 GPU 加速時它跟 medium 差不多慢，但中文比較準，
    # 而且跟 Apple Silicon 同一個模型，全隊共用的詞彙表在兩邊的效果才一致。
    if arch in ('apple_silicon', 'windows'):
        return 'ggml-large-v3-turbo.bin'
    return 'ggml-medium.bin'


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    if yaml is None:
        die('需要 PyYAML。請在專案目錄執行：uv pip install pyyaml')
    with CONFIG_PATH.open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        die(f'設定檔格式錯誤：{CONFIG_PATH}')
    return data


def find_tool(cfg: dict[str, Any], name: str) -> str | None:
    """依序找：config.yaml 記下的絕對路徑 → PATH → repo 的 tools/。

    Windows 上 winget 裝完的東西，要等 AI 工具重開才會出現在 PATH。
    install.ps1 會把找到的絕對路徑寫進 config，所以不重開也找得到。
    """
    configured = cfg.get(name.replace('-', '_'))
    if configured and Path(str(configured)).expanduser().is_file():
        return str(Path(str(configured)).expanduser())
    found = shutil.which(name)
    if found:
        return found
    exe = f'{name}.exe' if paths.IS_WINDOWS else name
    for candidate in paths.TOOLS_DIR.rglob(exe) if paths.TOOLS_DIR.is_dir() else ():
        if candidate.is_file():
            return str(candidate)
    return None


def which_or_die(cfg: dict[str, Any], name: str) -> str:
    path = find_tool(cfg, name)
    if not path:
        how = '重跑 install.cmd --yes' if paths.IS_WINDOWS else f'brew install {name}'
        die(f'找不到 `{name}`。請先安裝（{how}）。')
    return path


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print('$ ' + ' '.join(cmd), flush=True)
    try:
        return subprocess.run(
            cmd,
            check=True,
            text=True,
            # 明講 UTF-8：Windows 預設用系統編碼解碼，ffmpeg 印出中文檔名就會當掉
            encoding='utf-8',
            errors='replace',
            capture_output=capture,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or '') if capture else ''
        die(f'指令失敗（exit {e.returncode}）：{" ".join(cmd)}\n{stderr}'.rstrip())
    except FileNotFoundError:
        die(f'找不到可執行檔：{cmd[0]}')
    raise AssertionError('unreachable')


def run_tee(cmd: list[str], stdout_path: Path) -> None:
    """執行並同時把 stdout 存檔、去掉 ANSI 後印到畫面。

    whisper 的信心度資訊只存在 stdout 的 ANSI 樣式裡，不在 -oj 的 JSON。
    但直接吃掉 stdout 會讓使用者盯著一片空白等好幾分鐘，所以兩邊都要。
    """
    print('$ ' + ' '.join(cmd), flush=True)
    try:
        with stdout_path.open('wb') as fh:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
            assert proc.stdout is not None
            for chunk in proc.stdout:
                fh.write(chunk)
                clean = review.STRIP_SGR_BYTES.sub(b'', chunk)
                sys.stdout.write(clean.decode('utf-8', 'replace'))
                sys.stdout.flush()
            code = proc.wait()
    except FileNotFoundError:
        die(f'找不到可執行檔：{cmd[0]}')
    if code != 0:
        die(f'指令失敗（exit {code}）：{" ".join(cmd)}')


def find_ffprobe(ffmpeg: str) -> str | None:
    """ffprobe 通常跟 ffmpeg 裝在同一個資料夾，先找那裡，再找 PATH。"""
    sibling = Path(ffmpeg).with_name('ffprobe' + Path(ffmpeg).suffix)
    if sibling.is_file():
        return str(sibling)
    return shutil.which('ffprobe')


def probe_duration_seconds(ffmpeg: str, src: Path) -> float | None:
    ffprobe = find_ffprobe(ffmpeg)
    if not ffprobe:
        # fall back via ffmpeg -i
        proc = subprocess.run(
            [ffmpeg, '-i', str(src)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', proc.stderr or '')
        if not m:
            return None
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s

    proc = run(
        [
            ffprobe,
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            str(src),
        ],
        capture=True,
    )
    try:
        return float((proc.stdout or '').strip())
    except ValueError:
        return None


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return '未知'
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h} 小時 {m} 分 {s} 秒'
    return f'{m} 分 {s} 秒'


def format_ts(ms: int) -> str:
    total = max(0, ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def to_wav_16k_mono(ffmpeg: str, src: Path, dst: Path) -> None:
    run(
        [
            ffmpeg,
            '-y',
            '-i',
            str(src),
            '-ac',
            '1',
            '-ar',
            '16000',
            '-c:a',
            'pcm_s16le',
            str(dst),
        ],
        capture=True,
    )


def parse_glossary(
    path: Path | None,
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Return (terms, replacements wrong=>right, known terms).

    terms 是完整清單，要送進 whisper 的 prompt 由 rank_terms + build_prompt
    決定（有長度上限，得挑）。known 多含替換規則的正詞側，給待校對清單判斷
    「這個英文字是已知術語還是音譯亂碼」用。
    """
    if path is None or not path.is_file():
        return [], [], []

    terms: list[str] = []
    replacements: list[tuple[str, str]] = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=>' in line:
            wrong, right = line.split('=>', 1)
            wrong, right = wrong.strip(), right.strip()
            if wrong and right:
                replacements.append((wrong, right))
            continue
        for part in line.split(','):
            term = part.strip()
            if term:
                terms.append(term)

    # longest first so overlapping replacements behave better
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)

    # 校正規則的「正詞」側也是已知術語（Vuetify、Sourcetree…），
    # 不然它們會被當成不認識的英文而一直被挑出來校對。
    known = terms + [right for _, right in replacements]
    return terms, replacements, known


_SKIP_TRANSCRIPT_SUFFIXES = ('.review.md', '.ai-review.md', '.frames.md')


def iter_transcript_markdown(
    roots: list[Path],
    minutes_dir: Path | None = None,
) -> list[Path]:
    """收集逐字稿 markdown。略過校對／畫面索引，以及 minutes 根目錄那層的會議記錄。"""
    seen: set[Path] = set()
    out: list[Path] = []
    minutes_root = minutes_dir.resolve() if minutes_dir and minutes_dir.is_dir() else None
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*.md')):
            if any(path.name.endswith(sfx) for sfx in _SKIP_TRANSCRIPT_SUFFIXES):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            if minutes_root and path.parent.resolve() == minutes_root:
                continue
            seen.add(resolved)
            out.append(path)
    return out


def rank_terms(
    terms: list[str],
    replacements: list[tuple[str, str]],
    corpus_roots: list[Path],
    minutes_dir: Path | None = None,
) -> list[tuple[str, int, str]]:
    """把術語按「該不該佔用 prompt 預算」排序，回傳 (術語, 分數, 理由)。

    prompt 有硬性長度上限，塞不完的會被丟掉。原本照檔案順序截斷——等於由
    使用者在文字檔裡的排版決定哪些詞進得去，這不合理。

    排序的依據是**誰需要幫忙**，不是誰常出現：

    1. **有 `錯詞=>正詞` 規則** → whisper 已經被證實會聽錯這個詞，最需要提示。
       實測 00:35:48 那段：prompt 裡有 merge 就直接聽對，沒有就聽成 murge。
    2. **在過去的逐字稿完全沒出現過** → 兩種可能，而且分不出來：真的沒講過
       （Wireframe、Notion），或是**每次都被聽錯所以看不到**（Font Awesome 出現
       0 次，但實際上講者講了，被聽成「鳳猴身」）。無法分辨就給機會，因為漏掉
       第二種的代價比多帶一個詞高。
    3. **出現很多次卻沒有規則** → whisper 本來就聽得對（data 出現 61 次），
       **優先權最低**。花預算提示它是浪費，而且實測 prompt 塞太多反而會讓
       whisper 掉內容，所以少帶無用的詞本身就是好事。

    同分時保留檔案順序（Python 的 sort 穩定），使用者手動排的先後仍然有效。

    ⚠️ 第 3 條有一個混淆因子：過去的逐字稿本身多半是**帶著 prompt** 產生的，
    所以「出現很多次而且沒錯」有可能是 prompt 提示的功勞，把它擠出去反而會退步。
    這條規則是假設，不是定論——換了排序之後請跑 `eval.py` 對照，「whisper 自己」
    那一欄掉了就把該詞加回高優先（在術語表裡替它補一條 `錯詞=>正詞` 即可）。
    """
    parts: list[str] = []
    for path in iter_transcript_markdown(corpus_roots, minutes_dir):
        try:
            parts.append(path.read_text(encoding='utf-8'))
        except OSError:
            continue
    corpus = '\n'.join(parts)
    corpus_low = corpus.lower()

    # 有規則的「正詞」→ 這個術語 whisper 錯過
    corrected = {right.lower() for _, right in replacements}

    ranked: list[tuple[str, int, str]] = []
    for term in terms:
        low = term.lower()
        hits = corpus_low.count(low) if corpus_low and low else 0
        if low in corrected:
            score, why = 2000 + min(hits, 999), '曾聽錯，最需要提示'
        elif hits == 0:
            score, why = 1000, '過去沒出現（可能沒講過，也可能一直被聽錯）'
        else:
            # 出現越多次代表 whisper 越沒問題 → 分數越低
            score, why = 100 - min(hits, 99), f'出現 {hits} 次且沒錯過，不需提示'
        ranked.append((term, score, why))

    # -score 主排，order 次排 → 同分維持原檔案順序（Python sort 是穩定的）
    ranked.sort(key=lambda item: -item[1])
    return ranked


def build_prompt(
    ranked: list[tuple[str, int, str]], budget: int = PROMPT_CHAR_BUDGET
) -> tuple[str, list[str]]:
    """填滿 prompt 預算，回傳 (prompt, 塞不進去的術語)。

    塞不進去的要回報，不能像以前一樣默默丟掉——使用者以為自己加進詞表的詞
    有生效，其實根本沒送給 whisper。
    """
    parts: list[str] = []
    dropped: list[str] = []
    size = 0
    for term, _score, _why in ranked:
        add = (', ' if parts else '') + term
        if size + len(add) > budget:
            dropped.append(term)
            continue  # 不 break：後面可能有更短的詞塞得進來
        parts.append(term)
        size += len(add)
    return ', '.join(parts), dropped


def apply_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
    for wrong, right in replacements:
        if wrong.isascii():
            # 純英數的錯詞不分大小寫。whisper 同一個詞會時而 Tailway、
            # 時而 tailway，沒有人寫 `Tailway=>Tailwind` 是希望只中一種。
            # 用 lambda 當替換字串，re 才不會去解讀 right 裡的反斜線
            text = re.sub(re.escape(wrong), lambda _m, r=right: r, text, flags=re.IGNORECASE)
        else:
            text = text.replace(wrong, right)
    return text


def mostly_simplified(text: str) -> bool:
    if OpenCC is None:
        return False
    s2t = OpenCC('s2tw').convert(text)
    if s2t == text:
        return False
    cjk = [c for c in text if '\u4e00' <= c <= '\u9fff']
    if not cjk:
        return False
    changed = sum(1 for a, b in zip(text, s2t) if a != b)
    return (changed / len(cjk)) > 0.02


def to_traditional(text: str) -> tuple[str, bool]:
    if OpenCC is None:
        print('警告：未安裝 opencc，跳過簡繁轉換。', file=sys.stderr)
        return text, False
    if not mostly_simplified(text):
        return text, False
    return OpenCC('s2twp').convert(text), True


def resolve_model_path(cfg: dict[str, Any], model_arg: str | None) -> Path:
    models_dir = Path(cfg.get('models_dir') or DEFAULT_MODELS_DIR).expanduser()
    name = model_arg or cfg.get('model') or default_model_name(detect_arch())
    path = Path(name).expanduser()
    if path.is_file():
        return path.resolve()
    candidate = models_dir / name
    if candidate.is_file():
        return candidate.resolve()
    die(
        f'找不到模型：{candidate}\n'
        f'請下載 ggml 模型到 {models_dir}/，例如：\n'
        f'  curl -L -o {models_dir}/ggml-large-v3-turbo.bin \\\n'
        f'    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin'
    )
    raise AssertionError('unreachable')


def resolve_output_dir(
    cfg: dict[str, Any],
    output_dir: str | None,
    src: Path | None = None,
) -> Path:
    if output_dir:
        path = Path(output_dir).expanduser()
    elif cfg.get('minutes_dir') and src is not None:
        path = minutes_bundle_dir(Path(cfg['minutes_dir']).expanduser(), src)
    elif cfg.get('transcripts_dir'):
        path = Path(cfg['transcripts_dir']).expanduser()
    else:
        path = Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def resolve_glossary(cfg: dict[str, Any], glossary_arg: str | None) -> Path | None:
    if glossary_arg:
        path = Path(glossary_arg).expanduser()
        if not path.is_file():
            die(f'找不到術語表：{path}')
        return path
    for candidate in (
        Path(cfg['glossary_path']).expanduser() if cfg.get('glossary_path') else None,
        DEFAULT_GLOSSARY,
        REPO_ROOT / 'config' / 'glossary.txt.example',
    ):
        if candidate and candidate.is_file():
            return candidate
    return None


def resolve_vad_model(model: Path) -> Path | None:
    """VAD model lives beside the whisper model; None disables VAD."""
    candidate = model.parent / DEFAULT_VAD_MODEL
    return candidate if candidate.is_file() else None


def windows_response_file(cmd: list[str], work_dir: Path) -> list[str]:
    """把參數改寫進 UTF-8 檔案，回傳 `whisper-cli @檔案`。

    Windows 版 whisper-cli 收到的命令列參數是系統編碼（台灣是 Big5），
    但它把 --prompt 當 UTF-8 解讀，中文術語送進去就變亂碼。
    它支援「只給一個 @檔名 參數時，從檔案一行讀一個參數」，檔案內容原封不動
    當 UTF-8 用，所以改走這條路。

    代價：檔案裡的路徑也是 UTF-8，而它開檔用系統編碼，所以路徑要是純英數。
    暫存 wav 與輸出都放在 repo 的 var/tmp、模型在 repo 的 models/；
    install.ps1 會擋掉含中文的 repo 路徑，所以正常安裝不會踩到下面的檢查。
    """
    args = [a.replace('\r', ' ').replace('\n', ' ') for a in cmd[1:]]
    path_flags = {'-m', '-f', '-of', '--vad-model'}
    for flag, value in zip(args, args[1:]):
        if flag in path_flags and not value.isascii():
            die(
                f'Windows 上 whisper 讀不到含中文或特殊字元的路徑：{value}\n'
                '請把工具資料夾搬到路徑沒有中文的位置（例如 C:\\meeting-minutes），再重跑 install.cmd --yes。'
            )
    rsp = work_dir / 'whisper_args.txt'
    # 一行一個參數；用 \n 不用 \r\n，否則每個參數尾巴會多一個 \r
    rsp.write_bytes(('\n'.join(args) + '\n').encode('utf-8'))
    return [cmd[0], '@' + str(rsp)]


def whisper_transcribe(
    whisper: str,
    wav: Path,
    model: Path,
    prompt: str,
    work_dir: Path,
    vad_model: Path | None = None,
    vad_threshold: str = VAD_THRESHOLD,
    vad_speech_pad_ms: str = VAD_SPEECH_PAD_MS,
) -> tuple[list[dict[str, Any]], bytes]:
    """回傳 (segments, 帶信心度樣式的原始 stdout)。"""
    out_base = work_dir / 'whisper_out'
    # Anti-hallucination defaults: suppress non-speech tokens, limit text context
    # carryover, keep temperature fallback (do NOT pass --no-fallback).
    cmd = [
        whisper,
        '-m',
        str(model),
        '-f',
        str(wav),
        '-l',
        'zh',
        '-oj',
        '-of',
        str(out_base),
        '-np',
        '-pp',
        '--suppress-nst',
        '--max-context',
        str(WHISPER_MAX_CONTEXT),
        # 逐 token 信心度只會出現在 stdout 的 ANSI 樣式裡（JSON 沒有這個欄位）。
        # 這是「該人工抽聽哪幾行」唯一不需要 ground truth 的客觀依據。
        '--print-confidence',
    ]
    if vad_model:
        cmd.extend(
            [
                '--vad',
                '--vad-model',
                str(vad_model),
                '--vad-threshold',
                str(vad_threshold),
                '--vad-min-silence-duration-ms',
                VAD_MIN_SILENCE_MS,
                '--vad-speech-pad-ms',
                str(vad_speech_pad_ms),
            ]
        )
    if prompt:
        cmd.extend(['--prompt', prompt])

    if paths.IS_WINDOWS:
        # Windows 版只有 CPU，whisper 預設最多用 4 條執行緒。一般筆電有 8 條以上，
        # 多給一點大約快三到五成；超過 8 條幾乎沒差，還會讓電腦卡到不能做別的事。
        cmd.extend(['-t', str(min(8, os.cpu_count() or 4))])
        cmd = windows_response_file(cmd, work_dir)

    conf_path = work_dir / 'whisper_confidence.txt'
    run_tee(cmd, conf_path)
    json_path = Path(str(out_base) + '.json')
    if not json_path.is_file():
        die(f'whisper 未產生 JSON：{json_path}')

    data = json.loads(json_path.read_text(encoding='utf-8'))
    transcription = data.get('transcription') or data.get('segments') or []
    if not isinstance(transcription, list):
        die('whisper JSON 格式無法解析（缺少 transcription / segments）')
    # work_dir 是暫存目錄，會在 finally 被清掉，所以先把內容讀進記憶體
    conf_raw = conf_path.read_bytes() if conf_path.is_file() else b''
    return transcription, conf_raw


def _seg_ms(seg: dict[str, Any], key_from: str, key_to: str) -> tuple[int, int]:
    offsets = seg.get('offsets') or {}
    if 'from' in offsets:
        start_ms = int(offsets['from'])
        end_ms = int(offsets.get('to', offsets['from']))
        return start_ms, end_ms
    if key_from in seg:
        start_ms = int(float(seg[key_from]) * 1000)
        end_ms = int(float(seg.get(key_to, seg[key_from])) * 1000)
        return start_ms, end_ms
    if 'start' in seg:
        start_ms = int(float(seg['start']) * 1000)
        end_ms = int(float(seg.get('end', seg['start'])) * 1000)
        return start_ms, end_ms
    return 0, 0


def segments_to_lines(segments: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    """Return (start_ms, end_ms, text)."""
    lines: list[tuple[int, int, str]] = []
    for seg in segments:
        text = (seg.get('text') or '').strip()
        if not text:
            continue
        start_ms, end_ms = _seg_ms(seg, 'from', 'to')
        lines.append((start_ms, end_ms, text))
    return lines


def normalize_for_repeat(text: str) -> str:
    t = text.strip().casefold()
    t = re.sub(r'[\s\u3000]+', '', t)
    t = re.sub(r'[^\w\u4e00-\u9fff]+', '', t, flags=re.UNICODE)
    return t


def collapse_repeat_hallucinations(
    lines: list[tuple[int, int, str]],
    *,
    min_streak: int = REPEAT_COLLAPSE_MIN,
) -> tuple[list[tuple[int, int, str]], QualityReport]:
    """Collapse consecutive near-identical utterances; record fold events."""
    if not lines:
        return [], QualityReport(0, 0, 0, [])

    out: list[tuple[int, int, str]] = []
    events: list[CollapseEvent] = []
    removed = 0
    i = 0
    n = len(lines)
    while i < n:
        start_ms, end_ms, text = lines[i]
        key = normalize_for_repeat(text)
        j = i + 1
        streak_end = end_ms
        while j < n and normalize_for_repeat(lines[j][2]) == key and key:
            streak_end = max(streak_end, lines[j][1])
            j += 1
        streak = j - i
        if streak >= min_streak and key:
            out.append((start_ms, streak_end, text))
            note = (
                f'⚠️ 已摺疊重複幻聽 ×{streak}'
                f'（約 {format_ts(start_ms)}–{format_ts(streak_end)}）'
            )
            out.append((start_ms, streak_end, note))
            events.append(
                CollapseEvent(start_ms, streak_end, streak, text[:40])
            )
            removed += streak - 1
        else:
            for k in range(i, j):
                out.append(lines[k])
        i = j

    report = QualityReport(
        original_lines=n,
        kept_lines=len(out),
        collapsed_removed=removed,
        events=events,
    )
    return out, report


def stem_slug(src: Path) -> str:
    stem = re.sub(r'[^\w\-]+', '-', src.stem, flags=re.UNICODE).strip('-')
    stem = stem.replace('_', '-')
    return stem or 'transcript'


_DATE_ISO = re.compile(r'^(\d{4}-\d{2}-\d{2})[-_\s]+(.+)$')
_DATE_YMD_END = re.compile(r'[-_\s](\d{8})$')


def recording_date_and_slug(src: Path) -> tuple[str, str]:
    """從檔名抽出錄音日與 slug；對不到才用 mtime。

    Tw site training-1  20260702.m4a → ('2026-07-02', 'Tw-site-training-1')
    2026-04-01_DesignTeam_AI應用分享.mp4 → ('2026-04-01', 'DesignTeam-AI應用分享')
    """
    stem = src.stem
    matched = _DATE_ISO.match(stem)
    if matched:
        return matched.group(1), stem_slug(Path(matched.group(2)))
    matched = _DATE_YMD_END.search(stem)
    if matched:
        raw = matched.group(1)
        date = f'{raw[:4]}-{raw[4:6]}-{raw[6:8]}'
        rest = stem[: matched.start()].rstrip(' -_')
        slug = stem_slug(Path(rest)) if rest else stem_slug(src)
        return date, slug
    date = datetime.fromtimestamp(src.stat().st_mtime).strftime('%Y-%m-%d')
    return date, stem_slug(src)


def minutes_bundle_dir(minutes_dir: Path, src: Path) -> Path:
    """會議記錄同名資料夾：<minutes_dir>/<錄音日>-<slug>/"""
    date, slug = recording_date_and_slug(src)
    return minutes_dir / f'{date}-{slug}'


def write_markdown(
    *,
    out_path: Path,
    src: Path,
    duration_s: float | None,
    model: Path,
    arch: str,
    lines: list[tuple[int, int, str]],
    quality: QualityReport | None = None,
    speakers: 'diarize.DiarizeResult | None' = None,
) -> None:
    platform_label = {
        'apple_silicon': 'Apple Silicon (Metal)',
        'windows': 'Windows (CPU)',
    }.get(arch, 'Intel (CPU)')
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    body_lines = diarize.render_body(lines, speakers)

    header = [
        f'# 逐字稿：{out_path.stem}',
        '',
        f'錄音檔：{src.name}',
        f'路徑：{src.resolve()}',
        f'時長：{format_duration(duration_s)}',
        f'轉錄時間：{now}',
        f'模型：{model.name}',
        f'平台：{platform_label}',
    ]
    if speakers and speakers.speakers:
        header.append(diarize.summary_line(speakers))
    if quality and quality.events:
        header.append(
            f'重複摺疊：{len(quality.events)} 段，移除 {quality.collapsed_removed} 行'
        )
    if quality and quality.warned:
        header.extend(
            [
                '',
                '> ⚠️ **品質警告**：偵測到疑似幻聽迴圈，已自動摺疊重複句。'
                '請人工抽聽標註時段後再整理會議記錄。',
            ]
        )
    who = diarize.who_block(speakers) if speakers and speakers.speakers else []

    content = '\n'.join([*header, *who, '', '---', '', *body_lines, ''])
    tmp = out_path.with_name(out_path.name + '.partial')
    try:
        tmp.write_text(content, encoding='utf-8')
        tmp.replace(out_path)
    finally:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)


def emit_quality_console(quality: QualityReport) -> None:
    if not quality.events:
        print('→ 幻聽檢查：未發現連續重複段', flush=True)
        return
    print(
        f'→ 幻聽檢查：摺疊 {len(quality.events)} 段，移除 {quality.collapsed_removed} 行'
        f'（原文 {quality.original_lines} → {quality.kept_lines}）',
        flush=True,
    )
    for ev in quality.events[:8]:
        print(
            f'   · ×{ev.count}  {format_ts(ev.start_ms)}–{format_ts(ev.end_ms)}'
            f'  「{ev.sample}」',
            flush=True,
        )
    if len(quality.events) > 8:
        print(f'   · …另有 {len(quality.events) - 8} 段', flush=True)
    if quality.warned:
        print(
            '⚠️ 品質警告：幻聽佔比偏高，exit code=2（檔案仍已寫入）。'
            '請抽聽後再整理。',
            file=sys.stderr,
            flush=True,
        )


def emit_review(
    *,
    out_path: Path,
    lines: list[tuple[int, int, str]],
    conf_raw: bytes,
    glossary_terms: list[str],
    max_rows: int,
    ffmpeg: str | None = None,
    audio_src: Path | None = None,
) -> Path | None:
    """順手產出待校對清單。這是「讓準確率會自己變好」的入口。"""
    if not conf_raw:
        print('→ 待校對清單：whisper 沒有輸出信心度資訊，略過', flush=True)
        return None
    segments = review.parse_confidence(conf_raw)
    if not segments:
        print('→ 待校對清單：無法解析信心度輸出，略過', flush=True)
        return None

    # 留一份原始信心度輸出。重新調門檻不必再花好幾分鐘轉一次：
    #   review.py <這個檔> <逐字稿> --min-score 5
    cache = CONFIDENCE_CACHE / f'{out_path.stem}.txt'
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(conf_raw)
    except OSError:
        cache = None  # type: ignore[assignment]

    rows, skipped = review.build_rows(
        lines,
        segments,
        known_terms=review.latin_tokens(glossary_terms),
        max_rows=max_rows,
    )
    review_path = out_path.with_suffix('.review.md')

    # 切出可疑片段的音檔，校對表才能直接點開聽。只切被挑中的那幾十段，
    # 不是整份錄音，所以很快（40 段約幾秒）。
    clip_dir_name = f'{out_path.stem}.clips'
    clips: dict[int, str] = {}
    if rows and ffmpeg and audio_src and audio_src.is_file():
        clips = audioclip.cut_many(
            ffmpeg,
            audio_src,
            out_path.parent / clip_dir_name,
            [(r.start_ms, r.end_ms) for r in rows],
        )
        if clips:
            print(f'→ 音檔片段：{len(clips)} 段切在 {clip_dir_name}/', flush=True)
        else:
            print('→ 音檔片段：切片失敗，校對表改用純時間戳', flush=True)

    learn_cmd = (
        f'"{paths.PYTHON}" "{REPO_ROOT / "scripts" / "learn.py"}" '
        f'"{review_path}"'
    )
    review_path.write_text(
        review.render_review(
            transcript_path=out_path,
            rows=rows,
            total_lines=len(lines),
            skipped=skipped,
            learn_cmd=learn_cmd,
            clip_dir=clip_dir_name,
            clips=clips,
        ),
        encoding='utf-8',
    )
    if rows:
        print(
            f'→ 待校對清單：{review_path}'
            f'（{len(rows)} 行需要抽聽，全稿 {len(lines)} 行）',
            flush=True,
        )
        print('   填好「應該是」後把檔拖回對話（或說已校對），詞表會自動更新。', flush=True)
    else:
        print('→ 待校對清單：這次沒有明顯可疑的行', flush=True)
    if cache:
        print(f'   （信心度原始輸出留在 {cache}）', flush=True)
    return review_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='將音訊／視訊轉成繁體中文逐字稿（macOS／Windows + whisper.cpp）'
    )
    p.add_argument('input', help='音訊或視訊檔路徑')
    p.add_argument(
        '--output-dir',
        help='逐字稿輸出目錄（預設：會議記錄同名資料夾 minutes/<錄音日>-<slug>/）',
    )
    p.add_argument('--model', help='模型檔名或完整路徑（預設依架構：large-v3-turbo / medium）')
    p.add_argument('--glossary', help='術語表路徑')
    p.add_argument('--output-name', help='輸出檔名（不含路徑，預設依輸入檔名）')
    p.add_argument(
        '--no-vad',
        action='store_true',
        help='停用 VAD（預設啟用，需 models 目錄有 ggml-silero-*.bin）',
    )
    p.add_argument(
        '--vad-threshold',
        default=VAD_THRESHOLD,
        help=f'VAD 語音判定門檻，越低越不容易漏掉語音（預設 {VAD_THRESHOLD}）',
    )
    p.add_argument(
        '--vad-speech-pad-ms',
        default=VAD_SPEECH_PAD_MS,
        help=f'VAD 語音段前後留白毫秒（預設 {VAD_SPEECH_PAD_MS}）',
    )
    p.add_argument(
        '--no-review',
        action='store_true',
        help='不產生待校對清單（預設會產生 <逐字稿>.review.md）',
    )
    p.add_argument(
        '--review-max-rows',
        type=int,
        default=review.DEFAULT_MAX_ROWS,
        help=f'待校對清單最多幾行（預設 {review.DEFAULT_MAX_ROWS}；再多沒人會校）',
    )
    p.add_argument(
        '--no-frames',
        action='store_true',
        help='有影像軌也不抽畫面截圖（預設：螢幕錄影會在「你看這個」附近截圖）',
    )
    p.add_argument(
        '--no-speakers',
        action='store_true',
        help='不標講者（預設會用聲紋標 講者 A／B／C，27 分鐘錄音約多花 10 秒）',
    )
    p.add_argument(
        '--speakers',
        type=int,
        help='直接指定幾個人（預設自動判斷）。自動判斷分錯人數時才用',
    )
    return p


def main(argv: list[str] | None = None) -> int:
    check_platform()
    args = build_parser().parse_args(argv)
    cfg = load_config()

    src = Path(args.input).expanduser().resolve()
    if not src.is_file():
        die(f'找不到輸入檔：{src}')

    ffmpeg = which_or_die(cfg, 'ffmpeg')
    whisper = which_or_die(cfg, 'whisper-cli')
    if OpenCC is None:
        die('需要 opencc-python-reimplemented。請在專案執行：uv pip install opencc-python-reimplemented')

    arch = detect_arch()
    model = resolve_model_path(cfg, args.model)
    out_dir = resolve_output_dir(cfg, args.output_dir, src)
    glossary_path = resolve_glossary(cfg, args.glossary)
    terms, replacements, glossary_terms = parse_glossary(glossary_path)
    # prompt 有長度上限，塞不完的要挑——按「曾經聽錯」與「過去出現次數」排，
    # 不是按術語表的檔案順序。實測 prompt 裡有 merge 就能讓 murge 直接聽對。
    minutes_dir = (
        Path(cfg['minutes_dir']).expanduser() if cfg.get('minutes_dir') else None
    )
    corpus_roots: list[Path] = []
    if minutes_dir is not None:
        corpus_roots.append(minutes_dir)
    if cfg.get('transcripts_dir'):
        corpus_roots.append(Path(cfg['transcripts_dir']).expanduser())
    corpus_roots.append(out_dir)
    ranked = rank_terms(terms, replacements, corpus_roots, minutes_dir)
    prompt, dropped = build_prompt(ranked)
    if dropped:
        print(
            f'提示：術語表有 {len(terms)} 個詞，prompt 上限 {PROMPT_CHAR_BUDGET} 字元，'
            f'這次 {len(dropped)} 個沒送進 whisper：',
            flush=True,
        )
        print(f'      {"、".join(dropped[:12])}' + (' …' if len(dropped) > 12 else ''), flush=True)
        print('      （轉錄後的 `錯詞=>正詞` 替換不受這個上限影響，仍會生效）', flush=True)

    duration_s = probe_duration_seconds(ffmpeg, src)
    if duration_s and duration_s > 10 * 60:
        print(
            f'提示：音訊約 {format_duration(duration_s)}。'
            '若在 AI Agent 內執行且預估超過約 10 分鐘，建議改在系統 Terminal 跑。',
            flush=True,
        )

    out_name = args.output_name or f'{datetime.now().strftime("%Y-%m-%d")}-{stem_slug(src)}.md'
    if not out_name.endswith('.md'):
        out_name += '.md'
    out_path = out_dir / out_name

    wav_path: Path | None = None
    # Windows 的系統暫存資料夾在使用者名稱底下，名稱是中文就會讓 whisper 開不了檔
    # （見 windows_response_file），所以改放 repo 內的 var/tmp。
    work_parent = None
    if paths.IS_WINDOWS:
        work_parent = paths.VAR_DIR / 'tmp'
        work_parent.mkdir(parents=True, exist_ok=True)
    work = tempfile.TemporaryDirectory(prefix='meeting-minutes-', dir=work_parent)
    try:
        work_dir = Path(work.name)
        wav_path = work_dir / 'audio_16k_mono.wav'
        print('→ ffmpeg：轉 16kHz 單聲道 WAV', flush=True)
        to_wav_16k_mono(ffmpeg, src, wav_path)

        vad_model = None if args.no_vad else resolve_vad_model(model)
        print(
            f'→ whisper-cli：模型 {model.name}（{arch}）；'
            f'防幻聽：--suppress-nst --max-context {WHISPER_MAX_CONTEXT}',
            flush=True,
        )
        if vad_model:
            print(
                f'→ VAD：{vad_model.name}'
                f'（threshold {args.vad_threshold}，pad {args.vad_speech_pad_ms}ms）',
                flush=True,
            )
        elif args.no_vad:
            print('→ VAD：已停用（--no-vad）', flush=True)
        else:
            print(
                f'→ VAD：未啟用（模型不存在：{model.parent / DEFAULT_VAD_MODEL}）',
                flush=True,
            )
        if prompt:
            print(f'→ prompt 術語（截短）：{prompt[:120]}{"…" if len(prompt) > 120 else ""}', flush=True)
        if glossary_path:
            print(f'→ 術語表：{glossary_path}', flush=True)

        segments, conf_raw = whisper_transcribe(
            whisper,
            wav_path,
            model,
            prompt,
            work_dir,
            vad_model,
            args.vad_threshold,
            args.vad_speech_pad_ms,
        )
        lines = segments_to_lines(segments)
        if not lines:
            die('轉錄結果為空。請檢查錄音是否有人聲、格式是否正常。')

        joined = '\n'.join(text for _, _, text in lines)
        converted, did_opencc = to_traditional(joined)
        if did_opencc:
            print('→ OpenCC：偵測到簡體，已轉為繁體（s2twp）', flush=True)
        else:
            print('→ OpenCC：已是繁體（或無需轉換），跳過', flush=True)

        # map back line-by-line after full-doc convert for consistency
        converted_lines = converted.split('\n')
        if len(converted_lines) != len(lines):
            # fallback: convert each line
            new_lines = []
            for start_ms, end_ms, text in lines:
                t, _ = to_traditional(text)
                t = apply_replacements(t, replacements)
                new_lines.append((start_ms, end_ms, t))
            lines = new_lines
        else:
            lines = [
                (start_ms, end_ms, apply_replacements(text, replacements))
                for (start_ms, end_ms, _), text in zip(lines, converted_lines)
            ]

        if replacements:
            print(f'→ 詞表校正：{len(replacements)} 條規則', flush=True)

        lines, quality = collapse_repeat_hallucinations(lines)
        emit_quality_console(quality)

        speakers_result = None
        if args.no_speakers:
            print('→ 講者：已停用（--no-speakers）', flush=True)
        else:
            speakers_result = diarize.diarize_lines(
                wav_path,
                lines,
                model.parent,
                speakers=args.speakers,
                cache_stem=out_path.stem,
            )
            diarize.emit_console(speakers_result)

        write_markdown(
            out_path=out_path,
            src=src,
            duration_s=duration_s,
            model=model,
            arch=arch,
            lines=lines,
            quality=quality,
            speakers=speakers_result,
        )
        if not args.no_review:
            emit_review(
                out_path=out_path,
                lines=lines,
                conf_raw=conf_raw,
                glossary_terms=glossary_terms,
                max_rows=args.review_max_rows,
            )
        if not args.no_frames:
            frames.emit_frames(
                ffmpeg=ffmpeg,
                src=src,
                transcript_path=out_path,
                lines=lines,
                duration_s=duration_s,
                ffprobe=find_ffprobe(ffmpeg),
            )

        print(f'完成：{out_path}', flush=True)
        return 2 if quality.warned else 0
    except KeyboardInterrupt:
        print('\n已中斷。暫存 WAV 將清除；不覆寫既有成功逐字稿。', file=sys.stderr)
        return 130
    finally:
        work.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
