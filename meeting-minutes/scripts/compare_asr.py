#!/usr/bin/env python3
"""ASR 路線橫向比較（**已退役**的一次性測試腳本，非正式流程的一部分）。

當初用來決定「whisper + VAD + 術語表」還是「Apple SpeechAnalyzer」，那個選擇
已經做完了。檔案與檔名都寫死在 main() 裡，只對當時那批測試檔有意義。

**要量測準確率請用 `eval.py`，不要用這支。** 下面的 TERMS 是我手寫的，而且
只收了我早就寫過 `錯詞=>正詞` 規則的那幾個詞——詞表一定修得掉，所以它算出來的
「術語正確率」必然偏高，量的其實是我自己的詞表，不是辨識能力。`eval.py` 改成
從人工校對累積的迴歸集取題，並且把「詞表修出來的」和「whisper 自己聽對的」
分兩欄報，就是為了避免這個循環。

留著的理由只有一個：`fix_overconversion()`。Apple 的 zh-TW 輸出有簡→繁過度
轉換的痕跡（只→隻、面→麵、複→復），先 t2s 再 s2twp 可以修掉一批。哪天再評估
Apple 或其他 SRT 來源的引擎會用到。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from opencc import OpenCC

# Apple zh-TW 輸出帶有簡→繁過度轉換痕跡（只→隻、面→麵、複→復…）。
# 先轉回簡體再用 s2twp 正規化，可修掉這批錯字。
_T2S = OpenCC('t2s')
_S2TWP = OpenCC('s2twp')


def fix_overconversion(text: str) -> str:
    return _S2TWP.convert(_T2S.convert(text))


def parse_srt(path: Path) -> list[tuple[str, str]]:
    """回傳 [(hh:mm:ss, text), ...]。"""
    out: list[tuple[str, str]] = []
    blocks = re.split(r'\n\s*\n', path.read_text(encoding='utf-8').strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = re.match(r'(\d{2}:\d{2}:\d{2}),\d+\s*-->', lines[1])
        if not m:
            continue
        out.append((m.group(1), ' '.join(lines[2:]).strip()))
    return out


def parse_whisper_md(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\[(\d{2}:\d{2}:\d{2})\]\s*(.*)', line)
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


# 已知術語：正確寫法 -> 該術語所有已觀察到的錯誤變體
TERMS: dict[str, list[str]] = {
    'README': ['REME', 'reme', 'Renme', 'remme', 'raime', 'Rinmi', 'Reme'],
    'timeline': ['tine line', 'TiNine', 'tineline', 'Tinige', 'tinelight',
                 'tinigh', 'tine', 'Tine'],
    '資料夾': ['資料講', '資料墻', '資料牆'],
    '靜態網頁': ['心態網路', '現態網頁', '心態網頁'],
    'news.json': ['news.Jason', 'news. Jason', 'news點這son', 'news.Jser',
                  'news.Json'],
    'HTML': ['HTM Reco', 'HTML扣', 'HTM口', 'HTM'],
    '程式碼': ['陳司馬', '陳司碼'],
}


def score(name: str, entries: list[tuple[str, str]]) -> None:
    body = '\n'.join(t for _, t in entries)
    print(f'\n{"=" * 62}\n{name}')
    print(f'  段數 {len(entries)}　字數 {len(body.replace(chr(10), ""))}')
    total_ok = total_bad = 0
    for right, wrongs in TERMS.items():
        ok = len(re.findall(re.escape(right), body, re.IGNORECASE))
        bad = sum(body.count(w) for w in wrongs)
        total_ok += ok
        total_bad += bad
        flag = '✓' if bad == 0 else '✗'
        print(f'  {flag} {right:<12} 正確 {ok:>3}　錯誤 {bad:>3}')
    rate = total_ok / (total_ok + total_bad) * 100 if (total_ok + total_bad) else 0
    print(f'  ── 術語正確率 {rate:.0f}%（{total_ok}/{total_ok + total_bad}）')


def main() -> int:
    base = Path(__file__).resolve().parent.parent.parent
    tdir = base / 'minutes' / '2026-07-02-Tw-site-training-2'

    targets = [
        ('基準線：whisper turbo，無 VAD、無術語表',
         tdir / '2026-09-10-Tw-site-training-2-20260702.md', 'md', False),
        ('TEST-A：whisper turbo + VAD + 術語表',
         tdir / 'TEST-A-vad-glossary.md', 'md', False),
        ('TEST-B：Apple SpeechAnalyzer（原始）',
         tdir / 'TEST-B-apple.srt', 'srt', False),
        ('TEST-B′：Apple + OpenCC 修字',
         tdir / 'TEST-B-apple.srt', 'srt', True),
    ]

    for name, path, kind, fix in targets:
        if not path.is_file():
            print(f'\n{"=" * 62}\n{name}\n  （檔案尚未產生：{path.name}）')
            continue
        entries = parse_srt(path) if kind == 'srt' else parse_whisper_md(path)
        if fix:
            entries = [(ts, fix_overconversion(t)) for ts, t in entries]
        score(name, entries)
    return 0


if __name__ == '__main__':
    sys.exit(main())
