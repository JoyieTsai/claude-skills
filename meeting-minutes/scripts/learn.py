#!/usr/bin/env python3
"""把人工校對的結果寫回術語表與迴歸集（迭代優化第 2 步）。

輸入是 review.py 產生、人填過「應該是」那一欄的 `.review.md`。
輸出兩個地方：

1. 術語表（`config/glossary.txt`）新增 `錯詞=>正詞`
   → 下次轉錄同樣的詞就直接對。這是「變準」。
2. 迴歸集（`config/eval-cases.tsv`）
   → 存下每一筆「原本聽成什麼、其實是什麼」。這是「知道有沒有變準」，
     由 eval.py 讀，而且它會把「已寫進詞表的」和「詞表還沒有的」分開算，
     避免自己出題自己改考卷。

安全設計：
- 規則的錯詞側會盡量往左右吃相同的上下文，長度不足 3 字不罷休。
  「資料講=>資料夾」是安全的；「講=>夾」會炸掉整份稿子。
- 吃不到上下文而仍只有 1 個字的規則，不自動寫入，改寫成註解讓人決定。
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from review import english_words, parse_review  # noqa: E402

_SINGLE_LATIN = re.compile(r'^[A-Za-z][A-Za-z0-9\-]*$')


def is_risky_rule(wrong: str) -> bool:
    """錯詞側是一個真正的英文單字 → 全域替換會誤傷別的句子。

    例：某句的「actual」其實是講 ARCHITECTURE，但寫成 `actual=>ARCHITECTURE`
    之後，講者真的說「actual」時就會被改掉。這種要人自己決定，不自動啟用。
    「victify」「componer」這類音譯亂碼不在字表裡，可以安全自動啟用。
    """
    return bool(_SINGLE_LATIN.match(wrong)) and wrong.lower() in english_words()

CONFIG_DIR = paths.CONFIG_DIR
DEFAULT_GLOSSARY = paths.GLOSSARY_PATH
DEFAULT_CASES = paths.CASES_PATH
CASES_HEADER = ['date', 'source', 'timecode', 'heard', 'correct', 'wrong', 'right']
# 記到分鐘，不是只記到日。eval.py 要能分辨「規則比逐字稿新（還沒套用，正常）」
# 和「規則比逐字稿舊卻沒生效（真的壞了）」，而同一天內修詞表再重轉是常態流程，
# 只記日期的話這兩件事在同一天完全分不開。
LEARNED_FMT = '%Y-%m-%dT%H:%M'

MIN_RULE_LEN = 3  # 錯詞側盡量長到這個字數，避免誤傷
MAX_RULE_LEN = 20  # 太長的規則只會命中那一句，不值得放進詞表
MIN_SAFE_LEN = 2  # 短於此的錯詞側不自動寫入
# 兩處錯誤中間的相同片段短於這個長度就合併成一條規則。
# 不合併的話 difflib 會把「Fone Olsen → Font Awesome」拆成
# 「Fon=>Font Awesom」這種會污染所有 Font 的垃圾規則。
MIN_EQUAL_RUN = 3


def _ws_equal(a: str, b: str) -> bool:
    return re.sub(r'\s+', '', a) == re.sub(r'\s+', '', b)


def _coalesce(opcodes: list[tuple[str, int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """把被短暫相同片段隔開的差異合併成一個區間。"""
    spans: list[list[int]] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            continue
        if spans and (i1 - spans[-1][1]) < MIN_EQUAL_RUN:
            spans[-1][1] = i2
            spans[-1][3] = j2
        else:
            spans.append([i1, i2, j1, j2])
    return [(a, b, c, d) for a, b, c, d in spans]


def _is_latin(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _snap_latin(s: str, lo: int, hi: int) -> tuple[int, int]:
    """把區間邊界推到英數字串的外緣。

    difflib 是逐字比對，會在英文單字中間對齊，推出「vic=>Vue」這種
    切在字中間、會誤傷其他文字的規則。英文的自然單位是字，不是字元。
    """
    while 0 < lo < len(s) and _is_latin(s[lo - 1]) and _is_latin(s[lo]):
        lo -= 1
    while 0 < hi < len(s) and _is_latin(s[hi - 1]) and _is_latin(s[hi]):
        hi += 1
    return lo, hi


def _widen(
    heard: str, correct: str, i1: int, i2: int, j1: int, j2: int
) -> tuple[str, str]:
    """往左右吃相同的上下文，讓規則具體到不會誤傷別的句子。

    「講=>夾」會炸掉整份稿子；「資料講=>資料夾」才是安全的。
    """
    while (i2 - i1) < MIN_RULE_LEN and i1 > 0 and j1 > 0 and heard[i1 - 1] == correct[j1 - 1]:
        i1 -= 1
        j1 -= 1
    while (
        (i2 - i1) < MIN_RULE_LEN
        and i2 < len(heard)
        and j2 < len(correct)
        and heard[i2] == correct[j2]
    ):
        i2 += 1
        j2 += 1
    return heard[i1:i2], correct[j1:j2]


def apply_rules(text: str, rules: list[tuple[str, str]]) -> str:
    """完全比照 transcribe.py 的替換方式（長的先替換、純英數不分大小寫）。

    必須跟 transcribe.py 一致，不然驗證過的規則實際上不一定成立。
    """
    for wrong, right in sorted(rules, key=lambda p: len(p[0]), reverse=True):
        if wrong.isascii():
            text = re.sub(re.escape(wrong), lambda _m, r=right: r, text, flags=re.IGNORECASE)
        else:
            text = text.replace(wrong, right)
    return text


def _rules_from_spans(
    heard: str, correct: str, spans: list[tuple[int, int, int, int]]
) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    for i1, i2, j1, j2 in spans:
        i1, i2 = _snap_latin(heard, i1, i2)
        j1, j2 = _snap_latin(correct, j1, j2)
        wrong, right = _widen(heard, correct, i1, i2, j1, j2)
        wrong, right = wrong.strip(), right.strip()
        if not wrong or not right or wrong == right or _ws_equal(wrong, right):
            continue
        if len(wrong) > MAX_RULE_LEN:
            continue
        rules.append((wrong, right))
    return rules


def derive_rules(heard: str, correct: str) -> list[tuple[str, str]]:
    """從「聽到的」與「應該是」推出 錯詞=>正詞 規則。

    只差空白的不算——中英之間要不要空格是排版問題，不是辨識準確率，
    而且 `錯詞=>正詞` 的檔案格式本來就會把兩側的空白吃掉。

    最後一定驗證：把推出來的規則套回「聽到的」，必須真的變成「應該是」。
    驗不過就不推規則，寧可請人自己寫，也不要塞一條會污染其他句子的規則。
    """
    if _ws_equal(heard, correct):
        return []
    sm = difflib.SequenceMatcher(a=heard, b=correct, autojunk=False)
    spans = _coalesce(sm.get_opcodes())

    candidates = [spans]
    if len(spans) > 1:
        # 退路：整段差異併成一條。difflib 會在英文單字裡對齊出
        # 「sauce=>Sourcetree」這種只改一半的規則，併起來才對得上。
        candidates.append([(spans[0][0], spans[-1][1], spans[0][2], spans[-1][3])])

    for cand in candidates:
        rules = _rules_from_spans(heard, correct, cand)
        if rules and _ws_equal(apply_rules(heard, rules), correct):
            return rules
    return []


def load_glossary_wrongs(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    out: set[str] = set()
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if line.startswith('#') or '=>' not in line:
            continue
        out.add(line.split('=>', 1)[0].strip())
    return out


def load_cases(path: Path) -> tuple[list[dict[str, str]], set[tuple[str, str, str]]]:
    if not path.is_file():
        return [], set()
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    lines = path.read_text(encoding='utf-8').splitlines()
    for raw in lines[1:] if lines and lines[0].startswith('date\t') else lines:
        if not raw.strip():
            continue
        cells = raw.split('\t')
        cells += [''] * (len(CASES_HEADER) - len(cells))
        row = dict(zip(CASES_HEADER, cells))
        rows.append(row)
        seen.add((row['heard'], row['correct'], row['wrong']))
    return rows, seen


def _tsv(value: str) -> str:
    return value.replace('\t', ' ').replace('\n', ' ').strip()


def append_cases(path: Path, rows: list[list[str]]) -> None:
    new_file = not path.is_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        if new_file:
            fh.write('\t'.join(CASES_HEADER) + '\n')
        for row in rows:
            fh.write('\t'.join(_tsv(c) for c in row) + '\n')


def append_glossary(
    path: Path, rules: list[tuple[str, str]], unsafe: list[tuple[str, str, str]], source: str
) -> None:
    today = date.today().isoformat()
    block = [
        '',
        f'# ===== 人工校對回饋（{today}，來源 {source}）=====',
    ]
    for wrong, right in rules:
        block.append(f'{wrong}=>{right}')
    if unsafe:
        block.append(
            '# --- 下面這幾筆全域替換會誤傷（錯詞側太短，或本身是真正的英文單字）---'
        )
        block.append('# --- 想啟用請自己補上下文，例如把 abc=>xyz 改成 「的abc」=>「的xyz」 ---')
        for wrong, right, ts in unsafe:
            block.append(f'# {ts}  {wrong}=>{right}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write('\n'.join(block) + '\n')


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='把校對過的 .review.md 寫回術語表與迴歸集')
    p.add_argument('review', nargs='+', help='填好的 .review.md（可多份）')
    p.add_argument('--glossary', default=str(DEFAULT_GLOSSARY))
    p.add_argument('--cases', default=str(DEFAULT_CASES))
    p.add_argument('-n', '--dry-run', action='store_true', help='只印出會做什麼，不寫檔')
    args = p.parse_args(argv)

    glossary = Path(args.glossary).expanduser()
    cases_path = Path(args.cases).expanduser()
    known_wrongs = load_glossary_wrongs(glossary)
    _, seen_cases = load_cases(cases_path)

    total_entries = 0
    new_rules: list[tuple[str, str]] = []
    unsafe: list[tuple[str, str, str]] = []
    case_rows: list[list[str]] = []
    dup_rules = 0
    ws_only = 0
    learned_at = datetime.now().strftime(LEARNED_FMT)

    for rv in args.review:
        rv_path = Path(rv).expanduser()
        if not rv_path.is_file():
            print(f'找不到校對檔：{rv_path}', file=sys.stderr)
            return 1
        # xxx.review / xxx.ai-review（AI 整理會議記錄時回饋的）都還原成 xxx，
        # 迴歸集的 source 才對得上逐字稿名字
        source = re.sub(r'\.(ai-)?review$', '', rv_path.stem)
        entries = parse_review(rv_path)
        if not entries:
            print(f'· {rv_path.name}：沒有填過的列，跳過')
            continue
        total_entries += len(entries)
        for e in entries:
            if _ws_equal(e['heard'], e['correct']):
                # 只差空白：中英之間要不要空格是排版，不是辨識準確率，
                # 而且詞表格式本來就吃掉兩側空白。進迴歸集也量不出東西。
                ws_only += 1
                continue
            rules = derive_rules(e['heard'], e['correct'])
            usable: list[tuple[str, str]] = []
            for wrong, right in rules:
                if (
                    len(wrong) < MIN_SAFE_LEN
                    or is_risky_rule(wrong)
                    or '？' in right
                    or '?' in right
                    or right.startswith('我猜')
                    or '專有名詞' in right
                ):
                    unsafe.append((wrong, right, e['timecode']))
                    continue
                if wrong in known_wrongs:
                    dup_rules += 1
                    continue
                known_wrongs.add(wrong)
                usable.append((wrong, right))
            new_rules.extend(usable)

            # 沒推出可用規則的也要進迴歸集，只是 eval 無法自動判定，
            # 會單獨列成「未涵蓋」。寧可留著也不要丟掉人的勞動成果。
            for wrong, right in usable or [('', '')]:
                key = (e['heard'], e['correct'], wrong)
                if key in seen_cases:
                    continue
                seen_cases.add(key)
                case_rows.append(
                    [
                        learned_at,
                        source,
                        e['timecode'],
                        e['heard'],
                        e['correct'],
                        wrong,
                        right,
                    ]
                )
        print(f'· {rv_path.name}：{len(entries)} 筆校對')

    if not total_entries:
        print('\n沒有任何校對內容。請先在 .review.md 的「應該是」欄填上正確句子。')
        return 0

    print()
    print(f'校對筆數　　{total_entries}')
    print(f'新增規則　　{len(new_rules)}')
    if dup_rules:
        print(f'已有規則　　{dup_rules}（跳過）')
    if ws_only:
        print(f'只差空白　　{ws_only}（排版問題，不影響辨識，已忽略）')
    if unsafe:
        print(f'待人工判斷　{len(unsafe)}（會誤傷其他句子，寫成註解）')
    print(f'迴歸集新增　{len(case_rows)}')
    for wrong, right in new_rules[:12]:
        print(f'   + {wrong}=>{right}')
    if len(new_rules) > 12:
        print(f'   … 另有 {len(new_rules) - 12} 條')

    if args.dry_run:
        print('\n（--dry-run，沒有寫入任何檔案）')
        return 0

    if new_rules or unsafe:
        append_glossary(
            glossary, new_rules, unsafe, source='、'.join(Path(r).stem for r in args.review)
        )
        print(f'\n術語表已更新：{glossary}')
    if case_rows:
        append_cases(cases_path, case_rows)
        print(f'迴歸集已更新：{cases_path}')

    repo = paths.REPO_DIR
    print()
    print('下一步：重新轉錄同一個錄音，然後量測有沒有變準：')
    print(f'  "{paths.PYTHON}" "{repo / "scripts" / "eval.py"}" <新逐字稿> <舊逐字稿>')

    # 術語表與迴歸集是 repo 內的追蹤檔案，git 就是共用機制。不 push 的話
    # 你剛才的校對成果只有你自己受益，同事下次還是會踩同一個錯字。
    if (repo / '.git').exists() and (new_rules or case_rows):
        print()
        print('讓同事也拿到這次的校對成果（術語表是共用的）：')
        print(f'  git -C "{repo}" add config/glossary.txt config/eval-cases.tsv')
        print(f'  git -C "{repo}" commit -m "詞表：{len(new_rules)} 條新規則"')
        print(f'  git -C "{repo}" pull --rebase')
        print(f'  git -C "{repo}" push')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
