#!/usr/bin/env python3
"""從 whisper 的信心度輸出挑出「該人工抽聽哪幾行」（迭代優化第 1 步）。

沒有 ground truth 也能用。做法是問 whisper 自己：`whisper-cli --print-confidence`
會用 ANSI 樣式標出每個 token 的機率，我們把機率低的字挑出來排序。

樣式對應（whisper.cpp examples/cli/cli.cpp）：
    \\033[7m 反白  p < 0.33          → 權重 3
    \\033[4m 底線  0.33 <= p < 0.66  → 權重 1
    \\033[2m 變暗  p >= 0.66         → 權重 0（不算）

低信心不等於錯，所以這裡只做「排序」不做「判定」，最後仍要人看。
但它把 38 分鐘、752 行的稿子縮到幾十行，人工校對才成立。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover
    OpenCC = None  # type: ignore[misc, assignment]

# whisper.cpp 的三段式信心樣式 → 可疑權重
STYLE_WEIGHT = {7: 3, 4: 1, 2: 0}

DEFAULT_MAX_ROWS = 40  # 一次要人校對超過這個數量，就沒人會校
DEFAULT_MIN_SCORE = 2  # 低於此分數的行不值得佔用人的注意力
MIN_LINE_CHARS = 4  # 「哦」「對」這種行就算沒把握也不影響會議記錄
TIME_BUCKETS = 8  # 名額分散到錄音的 8 個時段，避免全擠在開場

# whisper 對虛詞常常沒把握（的、就、那、你說…），但這些字錯了不影響會議記錄，
# 而且它們數量極多，會把真正的術語錯誤淹掉。整段可疑片段只由虛詞組成就不計分。
_FUNCTION_CHARS = set(
    '的了就那這你我他她它是在有個們也要會說好對啊嗎吧呢哦喔嘛欸阿嗯'
    '很都還又再沒不無和跟與或但而且然後所以因為可以一二三四五六七八九十'
    '之上下前後中大小多少來去給把被讓從到於為以及其此該等'
    '，。、；：？！（）「」『』…—　 '
)

MARK_OPEN = '⟦'
MARK_CLOSE = '⟧'

_SGR_RE = re.compile(rb'\x1b\[([0-9;]*)m')
STRIP_SGR = re.compile(r'\x1b\[[0-9;]*m')
# 一定要在位元組層拿掉樣式再 decode：whisper 的樣式標記會插在多位元組字的
# 中間，先 decode 就已經解出一堆 U+FFFD 了，之後再拿掉樣式也救不回來。
STRIP_SGR_BYTES = re.compile(rb'\x1b\[[0-9;]*m')
_SEG_RE = re.compile(
    r'^\[(\d+):(\d\d):(\d\d(?:\.\d+)?)\s*-->\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)\]\s?(.*)$'
)

_LATIN_TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9\-]+')
# 不在術語表、但夾在中文裡也很正常的英文。台灣的前端／設計討論本來就中英混講，
# 「用Tailwind的prefix」是正確的稿子，不該被當成可疑。
# 刻意不把「中英黏在一起」單獨當訊號：在這個語域裡它是常態，不是錯誤。
_LATIN_OK = {
    'ok', 'okay', 'yes', 'no', 'the', 'and', 'or', 'is', 'it', 'this', 'that',
    'you', 'we', 'so', 'but', 'for', 'to', 'of', 'in', 'on', 'by', 'with',
    'all', 'one', 'two', 'three', 'up', 'down', 'new', 'old', 'yeah', 'well',
    # 前端／設計場景常出現且通常是對的
    'code', 'call', 'copy', 'paste', 'file', 'folder', 'link', 'list', 'item',
    'text', 'title', 'name', 'type', 'size', 'color', 'style', 'class', 'id',
    'key', 'value', 'test', 'demo', 'update', 'upload', 'download', 'export',
    'import', 'install', 'run', 'start', 'stop', 'open', 'close', 'save',
    'error', 'debug', 'module', 'package', 'folder', 'section', 'header',
    'footer', 'button', 'icon', 'image', 'video', 'font', 'grid', 'flex',
    'card', 'menu', 'nav', 'tab', 'modal', 'table', 'form', 'input', 'label',
    'default', 'custom', 'global', 'local', 'public', 'private', 'main',
    'version', 'release', 'tag', 'push', 'pull', 'clone', 'reset', 'diff',
    'add', 'edit', 'delete', 'remove', 'copy', 'move', 'rename', 'search',
    'based', 'on', 'off', 'true', 'false', 'null', 'set', 'get', 'post',
    # 系統字表只收 3 字以上，這些短的要自己列
    'ai', 'ui', 'ux', 'id', 'os', 'css', 'js', 'ts', 'md', 'api', 'url', 'uri',
    'cli', 'npm', 'git', 'ctrl', 'cmd', 'alt', 'esc', 'tab', 'png', 'jpg',
    'svg', 'gif', 'pdf', 'zip', 'seo', 'cdn', 'dns', 'ssh', 'ftp', 'sql',
    'php', 'xml', 'csv', 'txt', 'ide', 'pr', 'qa', 'db', 'app', 'web', 'dev',
}
# 未知英文只當「加權」，不足以自己把一行送上校對清單（WEIGHT < MIN_SCORE）。
# 一行出現兩個以上不認識的英文，或一個加上任何低信心，才值得人看。
WEIGHT_UNKNOWN_LATIN = 2

# macOS 內建的英文字表。用來分辨「真的英文字」與「音譯亂碼」：
#   actual / section / module → 字表裡有，大概是聽對的
#   victify / previct / componer → 字表裡沒有，幾乎都是聽錯的
# repo 裡附了一份（data/english-words.txt，同一份字表），Windows 才有得用；
# 兩邊都沒有就退回上面的白名單。
SYSTEM_WORDS = Path('/usr/share/dict/words')
_ENGLISH_CACHE: set[str] | None = None


def english_words() -> set[str]:
    global _ENGLISH_CACHE
    if _ENGLISH_CACHE is None:
        words: set[str] = set()
        source = paths.ENGLISH_WORDS_PATH if paths.ENGLISH_WORDS_PATH.is_file() else SYSTEM_WORDS
        try:
            with source.open(encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    w = line.strip().lower()
                    if len(w) > 2:  # 兩字以下太容易誤判（as、in、id…）
                        words.add(w)
        except OSError:
            words = set()
        _ENGLISH_CACHE = words
    return _ENGLISH_CACHE


@dataclass
class ConfSegment:
    start_ms: int
    end_ms: int
    chars: list[tuple[str, int]]  # (字, 權重)

    @property
    def text(self) -> str:
        return ''.join(c for c, _ in self.chars)

    def flagged_spans(self) -> list[tuple[str, int]]:
        """相鄰的低信心字合成一段，回傳 (文字, 該段權重總和)。"""
        spans: list[tuple[str, int]] = []
        buf: list[str] = []
        weight = 0
        for ch, w in self.chars:
            if w > 0:
                buf.append(ch)
                weight += w
            elif buf:
                spans.append((''.join(buf), weight))
                buf, weight = [], 0
        if buf:
            spans.append((''.join(buf), weight))
        return spans


def is_substantive(span: str) -> bool:
    """這段可疑文字裡有沒有實詞。全是虛詞就不值得人去聽。"""
    return any(ch not in _FUNCTION_CHARS for ch in span)


@dataclass
class ReviewRow:
    start_ms: int
    end_ms: int
    heard: str  # 最終稿的文字（已過簡繁與詞表）
    marked: str  # 同上，可疑處包在 ⟦⟧ 裡
    score: int
    reasons: list[str] = field(default_factory=list)
    guess: str = ''  # recheck.py 重解碼後的建議答案（人只要確認，不必打字）

    @property
    def density(self) -> float:
        """可疑程度佔整行的比例。

        只用絕對分數排序的話，長句子單純因為字多就贏，而
        「⟦那裡面就是貼⟧到」這種幾乎整行都沒把握的才是真正要聽的。
        """
        return self.score / max(len(self.heard), 1)


def _utf8_len(first: int) -> int:
    if first < 0x80:
        return 1
    if first >= 0xF0:
        return 4
    if first >= 0xE0:
        return 3
    if first >= 0xC0:
        return 2
    return 1  # 落單的 continuation byte，當一個壞字處理


def weighted_chars(payload: bytes) -> list[tuple[str, int]]:
    """把一行帶 ANSI 樣式的位元組，攤成 (字, 權重)。

    必須在位元組層做：whisper 的 token 邊界會切在多位元組字的中間，
    所以同一個中文字可能橫跨兩個樣式區間。
    """
    data = bytearray()
    weights: list[int] = []
    pos = 0
    cur = 0
    for m in _SGR_RE.finditer(payload):
        chunk = payload[pos : m.start()]
        data += chunk
        weights += [cur] * len(chunk)
        code = m.group(1).decode('ascii', 'replace')
        cur = STYLE_WEIGHT.get(int(code), 0) if code.isdigit() else 0
        pos = m.end()
    chunk = payload[pos:]
    data += chunk
    weights += [cur] * len(chunk)

    out: list[tuple[str, int]] = []
    raw = bytes(data)
    i = 0
    while i < len(raw):
        n = _utf8_len(raw[i])
        ch = raw[i : i + n].decode('utf-8', 'replace')
        out.append((ch, max(weights[i : i + n], default=0)))
        i += n
    return out


def parse_confidence(payload: bytes) -> list[ConfSegment]:
    """解析 `whisper-cli --print-confidence` 的 stdout。"""
    segments: list[ConfSegment] = []
    for raw_line in payload.split(b'\n'):
        if not raw_line.strip():
            continue
        plain = STRIP_SGR.sub('', raw_line.decode('utf-8', 'replace'))
        m = _SEG_RE.match(plain)
        if not m:
            continue
        start_ms = (
            int(m.group(1)) * 3600_000
            + int(m.group(2)) * 60_000
            + int(float(m.group(3)) * 1000)
        )
        end_ms = (
            int(m.group(4)) * 3600_000
            + int(m.group(5)) * 60_000
            + int(float(m.group(6)) * 1000)
        )
        # 樣式資訊只在原始位元組裡，所以要從時間戳後面重新切一次
        idx = raw_line.find(b']')
        body = raw_line[idx + 1 :] if idx >= 0 else raw_line
        chars = weighted_chars(body)
        while chars and chars[0][0] in ' \t':
            chars.pop(0)
        while chars and chars[-1][0] in ' \t\r':
            chars.pop()
        if chars:
            segments.append(ConfSegment(start_ms, end_ms, chars))
    return segments


def format_ts(ms: int) -> str:
    total = max(0, ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def _locate(needle: str, haystack: str, taken: list[tuple[int, int]]) -> tuple[int, int] | None:
    """在最終稿裡找可疑片段；找不到就換 OpenCC 轉過的版本再試一次。"""
    candidates = [needle]
    if OpenCC is not None:
        try:
            conv = OpenCC('s2twp').convert(needle)
            if conv != needle:
                candidates.append(conv)
        except Exception:  # pragma: no cover - OpenCC 資料檔缺失
            pass
    for cand in candidates:
        if not cand.strip():
            continue
        start = 0
        while True:
            i = haystack.find(cand, start)
            if i < 0:
                break
            span = (i, i + len(cand))
            if not any(a < span[1] and span[0] < b for a, b in taken):
                return span
            start = i + 1
    return None


def _mark(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out: list[str] = []
    prev = 0
    for a, b in merged:
        out.append(text[prev:a])
        out.append(MARK_OPEN + text[a:b] + MARK_CLOSE)
        prev = b
    out.append(text[prev:])
    return ''.join(out)


def _heuristic_flags(text: str, known_terms: set[str]) -> tuple[int, list[str], list[tuple[int, int]]]:
    """不依賴信心度的可疑訊號。whisper 對音譯亂碼常常很有信心。"""
    score = 0
    reasons: list[str] = []
    spans: list[tuple[int, int]] = []

    unknown: list[str] = []
    vocab = english_words()
    for m in _LATIN_TOKEN.finditer(text):
        tok = m.group(0)
        low = tok.lower()
        if low in _LATIN_OK or low in known_terms or low in vocab:
            continue
        unknown.append(tok)
        spans.append((m.start(), m.end()))
    if unknown:
        score += WEIGHT_UNKNOWN_LATIN * len(unknown)
        reasons.append('未知英文：' + '、'.join(dict.fromkeys(unknown))[:40])

    return score, reasons, spans


def latin_tokens(terms: list[str] | set[str] | None) -> set[str]:
    """把術語表的詞攤成小寫英文字。

    「Font Awesome」「HTML 碼」要能讓 font / awesome / html 都算已知，
    不然多字術語永遠對不上而一直被挑出來校對。
    """
    out: set[str] = set()
    for term in terms or ():
        for m in _LATIN_TOKEN.finditer(term):
            out.add(m.group(0).lower())
    return out


def build_rows(
    final_lines: list[tuple[int, int, str]],
    conf_segments: list[ConfSegment],
    *,
    known_terms: set[str] | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    min_score: int = DEFAULT_MIN_SCORE,
) -> tuple[list[ReviewRow], int]:
    """回傳 (要人校對的列, 因為額度而略過的列數)。

    只計「詞表沒修掉」的可疑片段——已經被 `錯詞=>正詞` 修好的就不該再問人。
    這讓校對清單隨著術語表變厚而自動變短。
    """
    known_terms = known_terms or set()
    by_start = {seg.start_ms: seg for seg in conf_segments}
    rows: list[ReviewRow] = []

    for i, (start_ms, end_ms, final_text) in enumerate(final_lines):
        if final_text.startswith('⚠️') or len(final_text) < MIN_LINE_CHARS:
            continue
        seg = by_start.get(start_ms)
        if seg is None and i < len(conf_segments):
            seg = conf_segments[i]  # 時間戳對不上時退回索引對齊

        score = 0
        reasons: list[str] = []
        spans: list[tuple[int, int]] = []
        if seg is not None:
            for span_text, weight in seg.flagged_spans():
                if not is_substantive(span_text):
                    continue
                # _locate 連 OpenCC 轉換過的寫法都找不到 → 這段已經被
                # 詞表的 `錯詞=>正詞` 改掉了，不必再問人。校對清單因此
                # 會隨著術語表變厚而自動變短，這是我們要的收斂行為。
                hit = _locate(span_text, final_text, spans)
                if hit is not None:
                    spans.append(hit)
                    score += weight
            if spans:
                reasons.append('低信心')

        h_score, h_reasons, h_spans = _heuristic_flags(final_text, known_terms)
        score += h_score
        reasons.extend(h_reasons)
        spans.extend(h_spans)

        if score >= min_score:
            rows.append(
                ReviewRow(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    heard=final_text,
                    marked=_mark(final_text, spans),
                    score=score,
                    reasons=reasons,
                )
            )

    skipped = max(0, len(rows) - max_rows)
    rows = _stratify(rows, max_rows)
    rows.sort(key=lambda r: r.start_ms)  # 依時間排，人只要順著音檔聽一次
    return rows, skipped


def _rank(row: ReviewRow) -> tuple[float, int, int]:
    return (-row.density, -row.score, row.start_ms)


def _stratify(
    rows: list[ReviewRow], max_rows: int, buckets: int = TIME_BUCKETS
) -> list[ReviewRow]:
    """名額平均分散到整段錄音，而不是全給前面幾分鐘。

    只按可疑程度排序的話，額度會被開場那段（收音差、閒聊、講者還沒進入正題）
    吃光，而真正該校的術語錯誤都在中後段的技術內容裡。
    """
    ranked = sorted(rows, key=_rank)
    if len(ranked) <= max_rows:
        return ranked

    lo = min(r.start_ms for r in ranked)
    hi = max(r.start_ms for r in ranked)
    width = max(1, (hi - lo) // buckets + 1)
    grouped: dict[int, list[ReviewRow]] = {}
    for r in ranked:  # 已排序，所以每個 bucket 內也是排序的
        grouped.setdefault((r.start_ms - lo) // width, []).append(r)

    per_bucket = max(1, max_rows // max(1, len(grouped)))
    chosen: list[ReviewRow] = []
    for key in sorted(grouped):
        chosen.extend(grouped[key][:per_bucket])

    if len(chosen) < max_rows:  # 名額沒用完就按整體排名補
        picked = {id(r) for r in chosen}
        for r in ranked:
            if len(chosen) >= max_rows:
                break
            if id(r) not in picked:
                chosen.append(r)
                picked.add(id(r))
    return chosen[:max_rows]


def _esc(text: str) -> str:
    return text.replace('|', '\\|')


def render_review(
    *,
    transcript_path: Path,
    rows: list[ReviewRow],
    total_lines: int,
    skipped: int,
    learn_cmd: str,
    clip_dir: str = '',
    clips: dict[int, str] | None = None,
) -> str:
    """產生給人填的校對表。

    clips 有值時多一個「聽」欄，直接連到切好的音檔片段——不然人得自己在
    播放器裡拖 40 次時間軸，這是整個迴圈最容易讓人放棄的地方。
    """
    clips = clips or {}
    prefilled = sum(1 for r in rows if r.guess)
    head = [
        f'# 待校對：{transcript_path.stem}',
        '',
        f'逐字稿：`{transcript_path}`',
        f'挑出 {len(rows)} 行（全稿 {total_lines} 行）'
        + (f'，另有 {skipped} 行也可疑但超出本次額度' if skipped else ''),
        '',
    ]
    if prefilled:
        head.extend(
            [
                f'其中 **{prefilled} 行已經有建議答案**——那是把音檔片段用不同設定'
                '重新解碼、多次結果一致才填上的。',
                '**請當成待確認，不是正解。** 對就留著，錯就改掉，不確定就清空。',
                '',
            ]
        )
    head.extend(
        [
            'whisper 對下面這些片段信心最低，或是格式看起來就不對。',
            '**你只要做一件事：把「應該是」那格填成正確的整句話。**',
            '聽不出來或本來就對，就留空——留空不會有任何後果。',
            '',
        ]
    )
    if clips:
        head.extend(
            [
                f'「聽」那一欄是切好的音檔片段（在 `{clip_dir}/`），點一下就能聽，'
                '不用自己拖時間軸。',
                '',
            ]
        )
    head.extend(
        [
            '填完存檔，把這個檔**拖回對話**（或說「已校對」）。詞表會自動更新，不用自己跑指令。',
            f'對話掛了再自己跑：`{learn_cmd}`',
            '',
        ]
    )
    if not rows:
        head.append('這次沒有需要校對的行。')
        return '\n'.join(head) + '\n'

    has_clips = bool(clips)
    if has_clips:
        head.extend(
            [
                '| 時間 | 聽 | whisper 聽到的（⟦⟧ 是可疑處） | 應該是 | 為什麼被挑出 |',
                '| --- | --- | --- | --- | --- |',
            ]
        )
    else:
        head.extend(
            [
                '| 時間 | whisper 聽到的（⟦⟧ 是可疑處） | 應該是 | 為什麼被挑出 |',
                '| --- | --- | --- | --- |',
            ]
        )
    for r in rows:
        cells = [f'`{format_ts(r.start_ms)}`']
        if has_clips:
            name = clips.get(r.start_ms)
            cells.append(f'[▶]({clip_dir}/{name})' if name else '')
        cells.append(_esc(r.marked))
        cells.append(_esc(r.guess))
        cells.append(_esc('；'.join(dict.fromkeys(r.reasons))))
        head.append('| ' + ' | '.join(cells) + ' |')
    head.append('')
    return '\n'.join(head) + '\n'


_CLIP_LINK = re.compile(r'^\[.*?\]\(.*?\)$')


def parse_review(path: Path) -> list[dict[str, str]]:
    """把填好的校對表讀回來。只回傳「應該是」有填的列。

    欄位位置用表頭認，不用寫死的索引——表格有沒有「聽」那一欄取決於當初
    切不切得出音檔片段，而 AI 自己寫的 `.ai-review.md` 又是另一種欄數。
    """
    out: list[dict[str, str]] = []
    idx_ts, idx_heard, idx_correct = 0, 1, 2  # 找不到表頭時的退路
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line.startswith('|') or line.startswith('| ---'):
            continue
        cells = [c.strip() for c in re.split(r'(?<!\\)\|', line)[1:-1]]
        if len(cells) < 3:
            continue

        if '應該是' in cells:  # 這是表頭
            idx_correct = cells.index('應該是')
            idx_ts = cells.index('時間') if '時間' in cells else 0
            idx_heard = next(
                (i for i, c in enumerate(cells) if 'whisper' in c.lower()),
                idx_correct - 1,
            )
            continue
        if max(idx_ts, idx_heard, idx_correct) >= len(cells):
            continue

        ts, marked, correct = cells[idx_ts], cells[idx_heard], cells[idx_correct]
        # v / ok / 對 = 人看過、whisper 沒問題，跟留空一樣不學
        if not correct or correct.lower() in {'v', 'ok', '✓', '對'} or _CLIP_LINK.match(
            marked
        ):
            continue
        heard = (
            marked.replace('\\|', '|').replace(MARK_OPEN, '').replace(MARK_CLOSE, '')
        ).strip()
        correct = correct.replace('\\|', '|').strip()
        if not heard or heard == correct:
            continue
        out.append({'timecode': ts.strip('`'), 'heard': heard, 'correct': correct})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description='從 whisper 信心度輸出產生待校對清單（通常由 transcribe.py 自動呼叫）'
    )
    p.add_argument('confidence', help='whisper --print-confidence 的 stdout 檔')
    p.add_argument('transcript', help='對應的逐字稿 .md')
    p.add_argument('-o', '--output', help='輸出路徑（預設 <逐字稿>.review.md）')
    p.add_argument(
        '--glossary',
        default=str(paths.GLOSSARY_PATH),
        help='術語表；用來判斷英文字是已知術語還是音譯亂碼',
    )
    p.add_argument('--max-rows', type=int, default=DEFAULT_MAX_ROWS)
    p.add_argument('--min-score', type=int, default=DEFAULT_MIN_SCORE)
    args = p.parse_args(argv)

    conf_path = Path(args.confidence).expanduser()
    tr_path = Path(args.transcript).expanduser()
    if not conf_path.is_file():
        print(f'找不到信心度檔：{conf_path}', file=sys.stderr)
        return 1
    if not tr_path.is_file():
        print(f'找不到逐字稿：{tr_path}', file=sys.stderr)
        return 1

    segments = parse_confidence(conf_path.read_bytes())
    starts: list[tuple[int, str]] = []
    for raw in tr_path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^\[(\d+):(\d\d):(\d\d)\]\s*(.*)$', raw)
        if m:
            ms = (
                int(m.group(1)) * 3600_000
                + int(m.group(2)) * 60_000
                + int(m.group(3)) * 1000
            )
            starts.append((ms, m.group(4)))
    # 逐字稿只記開始時間，結束時間就用下一行的開始（切音檔片段時要用）
    lines: list[tuple[int, int, str]] = [
        (ms, starts[i + 1][0] if i + 1 < len(starts) else ms + 5000, text)
        for i, (ms, text) in enumerate(starts)
    ]

    gl_path = Path(args.glossary).expanduser()
    terms: list[str] = []
    if gl_path.is_file():
        for raw in gl_path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '=>' in line:
                terms.append(line.split('=>', 1)[1].strip())
            else:
                terms.extend(t.strip() for t in line.split(',') if t.strip())

    rows, skipped = build_rows(
        lines,
        segments,
        known_terms=latin_tokens(terms),
        max_rows=args.max_rows,
        min_score=args.min_score,
    )
    out_path = (
        Path(args.output).expanduser()
        if args.output
        else tr_path.with_suffix('.review.md')
    )
    repo = Path(__file__).resolve().parent.parent
    learn_cmd = f'"{paths.PYTHON}" "{repo / "scripts" / "learn.py"}" "{out_path}"'
    out_path.write_text(
        render_review(
            transcript_path=tr_path,
            rows=rows,
            total_lines=len(lines),
            skipped=skipped,
            learn_cmd=learn_cmd,
        ),
        encoding='utf-8',
    )
    print(f'待校對清單：{out_path}（{len(rows)} 行）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
