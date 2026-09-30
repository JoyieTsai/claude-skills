#!/usr/bin/env python3
"""重標逐字稿的講者，不用重新轉錄。

自動判斷人數會錯——同一個門檻在不同錄音上會分出不同人數（理由寫在
diarize.py 的常數區）。所以「改人數」必須便宜：轉錄時聲紋已經存進
`var/embeddings/`，這支只做分群與改寫檔案，一份 27 分鐘的會議不到 1 秒。

    scripts/relabel.py <逐字稿.md> --speakers 3
    scripts/relabel.py <逐字稿.md>              # 重跑自動判斷
    scripts/relabel.py <逐字稿.md> --speakers 1 # 當成一個人（教學錄音）

改的是逐字稿裡的「講者」那行、「誰是誰」表格、以及內文的 `**講者 X**`。
`[HH:MM:SS] 內容` 那幾行一個字都不會動。已經填好的名字會被保留。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diarize  # noqa: E402

# 「說話者」是這個功能剛做出來時用的詞，後來統一成「講者」（跟範本、lint
# 一致）。這裡兩種都認：舊逐字稿重標時舊那行才會被清掉，而不是多留一行。
HEADER_SPEAKER_RE = re.compile(r'^(?:講者|說話者)：')
WHO_ROW_RE = re.compile(r'^\|\s*(?:講者|說話者)\s*([A-Z])\s*\|\s*(.*?)\s*\|')


def split_transcript(text: str) -> tuple[list[str], str]:
    """切成 (前言, 內文)。前言＝第一個 `---` 分隔線之前的所有內容。"""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if raw.strip() == '---':
            return lines[:i], '\n'.join(lines[i + 1 :])
    return lines, ''


def existing_names(head: list[str]) -> dict[str, str]:
    """保留人已經填進「誰是誰」的名字。"""
    names: dict[str, str] = {}
    for raw in head:
        m = WHO_ROW_RE.match(raw.strip())
        if m and m.group(2) not in ('@?', '名字', ''):
            names[m.group(1)] = m.group(2)
    return names


def clean_head(head: list[str]) -> list[str]:
    """拿掉舊的「講者：」那行與整個「誰是誰」區塊。"""
    out: list[str] = []
    skipping = False
    for raw in head:
        stripped = raw.strip()
        if stripped.startswith('## '):
            skipping = stripped == '## 誰是誰'
            if skipping:
                continue
        if skipping:
            continue
        if HEADER_SPEAKER_RE.match(stripped):
            continue
        out.append(raw)
    while out and not out[-1].strip():
        out.pop()
    return out


def apply_names(block: list[str], names: dict[str, str]) -> list[str]:
    out = []
    for raw in block:
        m = WHO_ROW_RE.match(raw.strip())
        if m and m.group(1) in names:
            raw = raw.replace('| @? |', f'| {names[m.group(1)]} |', 1)
        out.append(raw)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='重標逐字稿的講者（不重新轉錄）')
    p.add_argument('transcript', help='逐字稿 .md 路徑')
    p.add_argument(
        '--speakers',
        type=int,
        help='幾個人（不給＝重跑自動判斷）',
    )
    p.add_argument(
        '--dry-run',
        action='store_true',
        help='只印結果，不改檔案',
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.transcript).expanduser().resolve()
    if not path.is_file():
        print(f'找不到逐字稿：{path}', file=sys.stderr)
        return 1
    if args.speakers is not None and args.speakers < 1:
        print('--speakers 至少是 1', file=sys.stderr)
        return 1

    cached = diarize.load_cache(path.stem)
    if cached is None:
        print(
            f'沒有聲紋快取：{diarize.cache_path(path.stem)}\n'
            '這份逐字稿是在講者功能之前轉的，或快取被清掉了。\n'
            '要有講者標記得重跑一次轉錄（transcribe.py）。',
            file=sys.stderr,
        )
        return 1

    emb, durations, lines = cached
    result = diarize.assign_speakers(emb, durations, lines, speakers=args.speakers)
    diarize.emit_console(result)
    if not result.speakers:
        return 1

    original = path.read_text(encoding='utf-8')
    head, _old_body = split_transcript(original)
    names = existing_names(head)
    head = clean_head(head)
    head.append(diarize.summary_line(result))
    who = apply_names(diarize.who_block(result), names)
    body = diarize.render_body(lines, result)
    content = '\n'.join([*head, *who, '', '---', '', *body, ''])

    if args.dry_run:
        print(f'（--dry-run，沒有寫入）{path}')
        return 0

    tmp = path.with_name(path.name + '.partial')
    try:
        tmp.write_text(content, encoding='utf-8')
        tmp.replace(path)
    finally:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
    kept = '、'.join(f'{k}={v}' for k, v in sorted(names.items()))
    print(f'已重標：{path}' + (f'（保留名字 {kept}）' if kept else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
