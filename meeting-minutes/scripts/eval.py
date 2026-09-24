#!/usr/bin/env python3
"""量測逐字稿在迴歸集上的表現（迭代優化第 3 步）。

刻意把「詞表修出來的」和「whisper 自己聽對的」分開報，因為混在一起就是
自己出題自己改考卷——校對過的錯誤一定會被詞表修好，那個數字必然漂亮，
但它完全不代表辨識變準了。

  修正後　　整條管線的最終結果。詞表有規則的就該 100%。
            低於 100% 代表規則沒生效（whisper 現在聽成別的樣子、或詞表被改壞）。
  whisper　 拿掉詞表，whisper 自己聽對幾成。**只有這個數字上升才是真的變準。**
            改 VAD 門檻、換模型、改 prompt 術語才會動到它；加校正規則不會。

資料來源是 transcribe.py 留下的信心度原始輸出（詞表校正前的文字），
所以不必為了留考題而故意不修錯誤。

用法：
  eval.py <逐字稿.md> [更多逐字稿.md ...]     # 多份 = 比設定
  eval.py -v <逐字稿.md>                      # 列出每一筆沒過的
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from learn import load_cases, load_glossary_wrongs  # noqa: E402
from review import STRIP_SGR_BYTES  # noqa: E402

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover
    OpenCC = None  # type: ignore[misc, assignment]

DEFAULT_GLOSSARY = paths.GLOSSARY_PATH
DEFAULT_CASES = paths.CASES_PATH
CONFIDENCE_CACHE = paths.CONFIDENCE_DIR
DEFAULT_WINDOW_S = 20  # 不同設定的分段邊界會漂，給前後各 20 秒

_TS_LINE = re.compile(r'^\[(\d+):(\d\d):(\d\d)\]\s*(.*)$')
_CONF_LINE = re.compile(r'^\[(\d+):(\d\d):(\d\d(?:\.\d+)?)\s*-->[^\]]*\]\s?(.*)$')
_RUN_AT = re.compile(r'^轉錄時間：(\d{4}-\d\d-\d\d)(?:[ T](\d\d:\d\d))?')

PASS, WRONG, UNCOVERED, PENDING = 'pass', 'wrong', 'uncovered', 'pending'


@dataclass
class Outcome:
    case: dict[str, str]
    learned: bool
    status: str  # 詞表校正後的結果
    raw_status: str  # 詞表校正前（whisper 自己）的結果


def _contains(needle: str, haystack: str) -> bool:
    """比對方式要跟 transcribe.py 的替換一致：純英數不分大小寫。"""
    if not needle:
        return False
    if needle.isascii():
        return needle.lower() in haystack.lower()
    return needle in haystack


def read_transcript(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        m = _TS_LINE.match(raw)
        if m:
            ms = (
                int(m.group(1)) * 3600_000
                + int(m.group(2)) * 60_000
                + int(m.group(3)) * 1000
            )
            lines.append((ms, m.group(4)))
    return lines


def transcribed_at(path: Path) -> datetime:
    """逐字稿是什麼時候轉的。用來分辨「規則比稿子新」和「規則失效」。

    讀 transcribe.py 寫在檔頭的「轉錄時間」；沒有就退回檔案修改時間。
    """
    for raw in path.read_text(encoding='utf-8').splitlines()[:12]:
        m = _RUN_AT.match(raw.strip())
        if m:
            stamp = f'{m.group(1)}T{m.group(2) or "00:00"}'
            try:
                return datetime.strptime(stamp, '%Y-%m-%dT%H:%M')
            except ValueError:
                break
    return datetime.fromtimestamp(path.stat().st_mtime)


def learned_after(case_date: str, made_at: datetime) -> bool:
    """這條規則是不是在這份逐字稿產生「之後」才學到的。

    是 → 這份稿子當時還沒有這條規則，錯了很正常，不是迴歸。
    舊的迴歸集只記到日期。同一天內無法判斷先後時，一律當成「規則比較新」：
    誤判成「尚未套用」只是叫人重轉一次；誤判成「迴歸失敗」會害人去追一個
    根本不存在的 bug。
    """
    case_date = case_date.strip()
    if not case_date:
        return False
    if 'T' in case_date:
        try:
            return datetime.strptime(case_date, '%Y-%m-%dT%H:%M') > made_at
        except ValueError:
            return False
    try:
        d = datetime.strptime(case_date, '%Y-%m-%d').date()
    except ValueError:
        return False
    return d >= made_at.date()


def read_raw(path: Path, cache_dir: Path) -> list[tuple[int, str]] | None:
    """讀 transcribe.py 留下的信心度輸出＝詞表校正前的 whisper 原文。

    那份是簡體（OpenCC 之前），所以要先轉繁，才能跟繁體的正解比對。
    """
    cached = cache_dir / f'{path.stem}.txt'
    if not cached.is_file():
        return None
    text = STRIP_SGR_BYTES.sub(b'', cached.read_bytes()).decode('utf-8', 'replace')
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        m = _CONF_LINE.match(raw.strip())
        if m:
            ms = (
                int(m.group(1)) * 3600_000
                + int(m.group(2)) * 60_000
                + int(float(m.group(3)) * 1000)
            )
            lines.append((ms, m.group(4).strip()))
    if not lines:
        return None
    if OpenCC is not None:
        cc = OpenCC('s2twp')
        lines = [(ms, cc.convert(t)) for ms, t in lines]
    return lines


def _ts_to_ms(ts: str) -> int | None:
    try:
        nums = [int(p) for p in ts.strip('`').split(':')]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600_000 + nums[1] * 60_000 + nums[2] * 1000
    if len(nums) == 2:
        return nums[0] * 60_000 + nums[1] * 1000
    return None


def scope_for(
    lines: list[tuple[int, str]], timecode: str, window_s: int
) -> str:
    at_ms = _ts_to_ms(timecode)
    if at_ms is not None:
        lo, hi = at_ms - window_s * 1000, at_ms + window_s * 1000
        window = '\n'.join(t for ms, t in lines if lo <= ms <= hi)
        if window.strip():
            return window
    return '\n'.join(t for _, t in lines)  # 時間軸對不上就看全稿


def judge(case: dict[str, str], lines: list[tuple[int, str]], window_s: int) -> str:
    wrong, right = case['wrong'], case['right']
    if not wrong or not right:
        return UNCOVERED  # 沒有可自動判定的規則
    scope = scope_for(lines, case['timecode'], window_s)
    if _contains(right, scope):
        return PASS
    if _contains(wrong, scope):
        return WRONG
    return UNCOVERED


def evaluate(
    path: Path,
    cases: list[dict[str, str]],
    learned_wrongs: set[str],
    window_s: int,
    cache_dir: Path,
) -> tuple[list[Outcome], bool]:
    lines = read_transcript(path)
    raw_lines = read_raw(path, cache_dir)
    made_at = transcribed_at(path)
    out: list[Outcome] = []
    for case in cases:
        status = judge(case, lines, window_s)
        # 規則比這份稿子新 → 這份稿子當時還沒有這條規則，不是迴歸失敗
        if status == WRONG and learned_after(case.get('date', ''), made_at):
            status = PENDING
        out.append(
            Outcome(
                case=case,
                learned=bool(case['wrong']) and case['wrong'] in learned_wrongs,
                status=status,
                raw_status=judge(case, raw_lines, window_s) if raw_lines else UNCOVERED,
            )
        )
    return out, raw_lines is not None


def _rate(hit: int, total: int) -> str:
    return f'{hit}/{total} {hit / total * 100:5.1f}%' if total else '   —   '


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='用迴歸集量測逐字稿準確率')
    p.add_argument('transcript', nargs='+', help='逐字稿 .md（可多份，用來比設定）')
    p.add_argument('--cases', default=str(DEFAULT_CASES))
    p.add_argument('--glossary', default=str(DEFAULT_GLOSSARY))
    p.add_argument('--confidence-cache', default=str(CONFIDENCE_CACHE))
    p.add_argument('--window', type=int, default=DEFAULT_WINDOW_S, help='時間軸容差秒數')
    p.add_argument('-v', '--verbose', action='store_true', help='列出沒過的細節')
    args = p.parse_args(argv)

    cases_path = Path(args.cases).expanduser()
    cases, _ = load_cases(cases_path)
    if not cases:
        print(f'迴歸集是空的：{cases_path}')
        print('先跑 transcribe.py 產生 .review.md，人工填好，再跑 learn.py 建立迴歸集。')
        return 0
    learned = load_glossary_wrongs(Path(args.glossary).expanduser())
    cache_dir = Path(args.confidence_cache).expanduser()

    print(f'迴歸集：{cases_path}（{len(cases)} 筆）')
    print(f'術語表：{args.glossary}')
    print()
    print(f'{"逐字稿":<34}{"修正後":>12}{"whisper 自己 ←看這個":>22}{"尚未套用":>10}{"未涵蓋":>8}')
    print('─' * 92)

    exit_code = 0
    all_outcomes: dict[str, list[Outcome]] = {}
    missing_raw: list[str] = []
    for tr in args.transcript:
        tr_path = Path(tr).expanduser()
        if not tr_path.is_file():
            print(f'找不到逐字稿：{tr_path}', file=sys.stderr)
            return 1
        outcomes, has_raw = evaluate(tr_path, cases, learned, args.window, cache_dir)
        all_outcomes[tr_path.name] = outcomes
        if not has_raw:
            missing_raw.append(tr_path.name)

        scored = [o for o in outcomes if o.status in (PASS, WRONG)]
        raw_scored = [o for o in outcomes if o.raw_status in (PASS, WRONG)]
        pending = sum(1 for o in outcomes if o.status == PENDING)
        uncovered = sum(1 for o in outcomes if o.status == UNCOVERED)
        fixed = sum(1 for o in scored if o.status == PASS)
        raw_ok = sum(1 for o in raw_scored if o.raw_status == PASS)

        name = tr_path.name if len(tr_path.name) <= 32 else tr_path.name[:31] + '…'
        print(
            f'{name:<34}{_rate(fixed, len(scored)):>12}'
            f'{_rate(raw_ok, len(raw_scored)):>22}{pending:>10}{uncovered:>8}'
        )
        if fixed < len(scored):
            exit_code = 1

    print()
    regressions = [
        (n, o)
        for n, outs in all_outcomes.items()
        for o in outs
        if o.learned and o.status == WRONG
    ]
    if regressions:
        print(f'⚠️ 修正後仍然錯 {len(regressions)} 筆——詞表有規則卻沒生效：')
        for name, o in regressions[:10]:
            print(
                f'   · [{name}] {o.case["timecode"]}'
                f'  規則 {o.case["wrong"]}=>{o.case["right"]}'
            )
        print('   可能原因：whisper 這次聽成別的樣子、或規則被後面的規則蓋掉。')
        print()

    if missing_raw:
        print(
            f'註：{len(missing_raw)} 份逐字稿沒有信心度原始輸出，'
            '「whisper 自己」這欄無法計算。'
        )
        print(f'    （只有 {CONFIDENCE_CACHE} 裡有快取的才算得出來）')
        print()

    if args.verbose:
        for name, outs in all_outcomes.items():
            bad = [o for o in outs if o.status in (WRONG, PENDING)]
            print(f'── {name} ──')
            for o in bad:
                tag = {WRONG: '仍然錯', PENDING: '尚未套用'}[o.status]
                raw = {PASS: '原文就對', WRONG: '原文也錯', UNCOVERED: '原文未涵蓋'}[
                    o.raw_status
                ]
                print(
                    f'   [{tag}] {o.case["timecode"]}  聽成「{o.case["wrong"]}」'
                    f'  應為「{o.case["right"]}」（{raw}）'
                )
            if not bad:
                print('   全數通過')
            print()

    print('讀法：')
    print('  修正後　　　　低於 100% 表示詞表規則沒生效，先修這個。')
    print('  whisper 自己　拿掉詞表後 whisper 聽對幾成。**只有它上升才是真的變準。**')
    print('  尚未套用　　　規則比這份稿子新，重新轉錄就會修好，不算失敗。')
    print('  未涵蓋　　　　推不出可自動判定的規則，或時間軸對不上，不計分。')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
