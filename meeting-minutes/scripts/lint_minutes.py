#!/usr/bin/env python3
"""檢查產出的會議記錄有沒有照範本規則寫（INSTRUCTIONS.md 第 6 步）。

**為什麼需要這支**：規則寫在 `INSTRUCTIONS.md` 與範本註解裡，但寫的人是 AI，
使用者按一個指令就走完全程、中間沒有人看著。實測過一次：同一輪裡自檢表抓到
「範本的 HTML 註解忘了刪」，但是在**存檔之後**才發現——自檢靠的是同一個
會犯錯的腦袋，所以要有一道機器檢查。

**只檢查結構，不評價內容。** 「這段寫得像流水帳嗎」需要判斷力，機器做不了；
但「有沒有結論行」「待辦有沒有負責人」「標題順序對不對」是純結構問題，
機器抓得又快又準。抓不到的那些仍然靠 INSTRUCTIONS 的規則與自檢表。

**兩種嚴重度**：
  ❌ 錯誤（exit 1）——規則是死的，違反就是違反（缺標題、註解殘留、缺結論行）
  ⚠️ 提醒（exit 0）——靠關鍵詞猜的，可能誤判（待辦寫得抽象、決議語氣不確定）
提醒故意不讓 exit code 變 1，免得為了讓 lint 閉嘴而去改掉本來正確的內容。

用法：
    python3 scripts/lint_minutes.py <會議記錄.md> [更多檔案...]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402,F401  Windows 主控台改 UTF-8（印 ✅ ❌ 才不會當掉）

# ---------------------------------------------------------------- 範本結構定義

# (標題, 是否必填)。順序就是範本的順序，產出不可以重排。
MINUTES_SECTIONS: list[tuple[str, bool]] = [
    ('總結', True),
    ('待辦', True),
    ('決議', True),
    ('還沒決定', True),
    ('討論細節', True),
    ('風險／疑慮', False),
    ('相關檔案', False),
]

TRAINING_SECTIONS: list[tuple[str, bool]] = [
    ('總結', True),
    ('之後怎麼做', True),
    ('注意事項', True),
    ('教學細節', False),
    ('後續', False),
    ('待確認 / 沒講到的', False),
    ('相關檔案', False),
]

# 哪一節的 ### 主題需要開頭結論行，以及該用哪個詞
CONCLUSION_LEAD = {
    '教學細節': ('**重點**：',),
}

MAX_OVERVIEW_BULLETS = 4  # 「總結」拆成太多條就不是摘要了
OVERVIEW_TITLES = {'總結'}
FRAGMENT_LABELS = (
    '**在處理什麼**',
    '**結果**',
    '**接下來**',
    '**教了什麼**',
    '**之後你要自己做的**',
    '**最容易做錯的**',
    '**明講這次不談**',
)
MAX_PROSE_LINES = 3  # 連續散文超過這個行數就該拆 bullet

FOOTER = '🤖 AI 生成，未經人工審核'

# 待辦寫得等於沒寫的講法。只查待辦那幾行，別處出現（例如決議「只做 UI 小改」）是合理的。
VAGUE_TODO = ['小改', '優化一下', '研究看看', '調整一下', '處理一下', '看看', '再想一下']

# 決議區出現這些字，表示那件事其實沒拍板
UNDECIDED_IN_DECISION = ['可以考慮', '再看看', '好像可以', '也許', '應該可以', '再研究']

# 範本示範內容沒換掉的跡象。
# 只收「真實會議不可能出現」的字串：範本的教學型示範用的是真的專案（Tw 官網、
# `data/news.json`），拿來當關鍵詞會把真檔案誤判成沒換掉的示範內容。
TEMPLATE_LEFTOVERS = ['Alice、Bob、Carol', 'Alice（講解）、Bob、Cyndi', '首頁採用方案 B']


@dataclass
class Finding:
    line: int  # 1-indexed；0 代表整份檔案
    level: str  # 'error' | 'warn'
    message: str


@dataclass
class Section:
    number: int
    title: str  # 已去掉「（選填）」
    raw_title: str
    start: int  # 0-indexed
    end: int  # 0-indexed，不含


H2_RE = re.compile(r'^##\s+(\d+)\.\s*(.+?)\s*$')
H3_RE = re.compile(r'^###\s+(.+?)\s*$')
TODO_RE = re.compile(r'^\s*-\s*\[[ x]\]\s*(.*)$')
OWNER_RE = re.compile(r'\*\*[^*]+\*\*\s*[：:]')
TIMESTAMP_RE = re.compile(r'\d{1,2}:\d{2}(?::\d{2})?')


# 舊標題仍當成新標題，避免歷史稿被判「不是範本的區塊」。
TITLE_ALIASES = {
    '地雷': '注意事項',
}


def strip_optional(title: str) -> str:
    """去掉標題裡的「（選填）」。那是給 AI 看的標記，不該留在產出裡。"""
    title = re.sub(r'（選填）\s*$', '', title).strip()
    return TITLE_ALIASES.get(title, title)


def split_sections(lines: list[str], fenced: list[bool]) -> list[Section]:
    sections: list[Section] = []
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        m = H2_RE.match(line)
        if m:
            raw = m.group(2)
            sections.append(
                Section(number=int(m.group(1)), title=strip_optional(raw), raw_title=raw, start=i, end=len(lines))
            )
    for a, b in zip(sections, sections[1:]):
        a.end = b.start
    return sections


def mark_fences(lines: list[str]) -> list[bool]:
    """標出每一行是否在 ``` 圍欄裡。圍欄裡的東西一律不檢查。"""
    inside = False
    flags: list[bool] = []
    for line in lines:
        if line.lstrip().startswith('```'):
            flags.append(True)  # 圍欄自己也算在裡面
            inside = not inside
            continue
        flags.append(inside)
    return flags


# ------------------------------------------------------------------- 各項檢查


def check_comments(lines: list[str], fenced: list[bool]) -> list[Finding]:
    """範本註解要刪掉。這是實測真的發生過的錯。"""
    out = []
    for i, line in enumerate(lines):
        if not fenced[i] and '<!--' in line:
            out.append(Finding(i + 1, 'error', '殘留範本的 HTML 註解，產出時要刪掉'))
    return out


def check_header_table(lines: list[str]) -> list[Finding]:
    """開頭資訊表：至少要有「參加者」與「會議類型」兩列。"""
    head = '\n'.join(lines[:15])
    out = []
    if '| 項目 | 內容 |' not in head:
        out.append(Finding(1, 'error', '檔案開頭缺少資訊表（`| 項目 | 內容 |`）'))
        return out
    for required in ('參加者', '會議類型', '主題'):
        if f'| {required}' not in head:
            out.append(Finding(1, 'error', f'開頭資訊表缺少「{required}」列'))
    return out


def check_participants(lines: list[str]) -> list[Finding]:
    """參加者列：只列與會者、一人一行、只標主持人。"""
    out = []
    for i, line in enumerate(lines[:20]):
        if not line.startswith('| 參加者'):
            continue
        if '@?' in line:
            out.append(
                Finding(
                    i + 1,
                    'warn',
                    '參加者是 `@?`，讀的人分不出誰是誰。分得出人就寫名字（主持人標「（主持人）」，其他人只寫名字）',
                )
            )
        if '非主持人' in line:
            out.append(
                Finding(
                    i + 1,
                    'error',
                    '參加者不要標「非主持人」，其他與會者只寫名字',
                )
            )
        if '講者' in line:
            out.append(
                Finding(
                    i + 1,
                    'error',
                    '參加者列不要寫「講者 A／B」代號，代號留在逐字稿；主持人寫「（主持人）」，其他人只寫名字',
                )
            )
        cell = line.split('|')[2] if line.count('|') >= 3 else line
        if '、' in cell:
            out.append(
                Finding(
                    i + 1,
                    'error',
                    '參加者每個人一行，同一格用 `<br>` 換行，不要用頓號列在同一行',
                )
            )
        break
    return out


def detect_kind(lines: list[str]) -> tuple[str, list[tuple[str, bool]]] | tuple[None, None]:
    body = '\n'.join(lines)
    if '# 教學筆記' in body:
        return 'training', TRAINING_SECTIONS
    if '# 會議摘要' in body:
        return 'minutes', MINUTES_SECTIONS
    return None, None


def check_sections(sections: list[Section], expected: list[tuple[str, bool]]) -> list[Finding]:
    """標題文字、順序、編號、必填區塊。"""
    out: list[Finding] = []
    expected_titles = [t for t, _ in expected]

    for sec in sections:
        if sec.title not in expected_titles:
            out.append(Finding(sec.start + 1, 'error', f'不是範本的區塊標題：「{sec.title}」'))
        if '（選填）' in sec.raw_title:
            out.append(Finding(sec.start + 1, 'error', '標題裡的「（選填）」是給 AI 看的標記，產出要拿掉'))

    known = [s for s in sections if s.title in expected_titles]

    # 順序：必須是範本順序的子序列
    positions = [expected_titles.index(s.title) for s in known]
    if positions != sorted(positions):
        out.append(Finding(known[0].start + 1 if known else 1, 'error', '區塊順序跟範本不一致，不要重排'))

    # 編號：必須 1、2、3… 連續
    for want, sec in enumerate(known, start=1):
        if sec.number != want:
            out.append(Finding(sec.start + 1, 'error', f'區塊編號應該是 {want}，寫的是 {sec.number}'))
            break

    present = {s.title for s in known}
    for title, required in expected:
        if required and title not in present:
            out.append(Finding(0, 'error', f'缺少必填區塊「{title}」'))
    return out


def body_lines(lines: list[str], sec: Section) -> list[tuple[int, str]]:
    """區塊內容（去掉標題行與空行、分隔線）。回傳 (0-indexed 行號, 內容)。"""
    out = []
    for i in range(sec.start + 1, sec.end):
        stripped = lines[i].strip()
        if not stripped or stripped == '---':
            continue
        out.append((i, stripped))
    return out


def check_empty_sections(lines: list[str], sections: list[Section]) -> list[Finding]:
    out = []
    for sec in sections:
        if not body_lines(lines, sec):
            out.append(
                Finding(sec.start + 1, 'error', f'「{sec.title}」只有標題沒有內容。選填的整段刪，必填的寫一行說明為什麼沒有')
            )
    return out


def check_overview(lines: list[str], sections: list[Section]) -> list[Finding]:
    """總結要寫確認後的結果，不要標籤拼盤。"""
    out = []
    for sec in sections:
        if sec.title not in OVERVIEW_TITLES:
            continue
        body = body_lines(lines, sec)
        bullets = [n for n, text in body if text.startswith('- ')]
        if len(bullets) > MAX_OVERVIEW_BULLETS:
            out.append(
                Finding(
                    sec.start + 1,
                    'error',
                    f'「{sec.title}」有 {len(bullets)} 條，上限 {MAX_OVERVIEW_BULLETS} 條。細節本來就該放後面',
                )
            )
        for n, text in body:
            if any(label in text for label in FRAGMENT_LABELS):
                out.append(
                    Finding(
                        n + 1,
                        'error',
                        '「總結」不要用「在處理什麼／結果／教了什麼」標籤拼盤，改寫成確認後的結果（這場是什麼、確認了什麼、接下來怎麼走）',
                    )
                )
                break
    return out


def check_todos(lines: list[str], sections: list[Section]) -> list[Finding]:
    """待辦要有負責人，而且不能寫成「做小改」。"""
    out = []
    for sec in sections:
        if sec.title not in ('待辦', '後續'):
            continue
        found = False
        for n, text in body_lines(lines, sec):
            m = TODO_RE.match(text)
            if not m:
                continue
            found = True
            content = m.group(1)
            if not OWNER_RE.search(content):
                out.append(
                    Finding(n + 1, 'error', '待辦缺少 `**負責人**：` 格式（沒名字用 `**講者 B**`，真的不知道才 `**@?**`）')
                )
            else:
                tail = OWNER_RE.sub('', content, count=1).strip()
                if tail in ('', '…', '...'):
                    out.append(Finding(n + 1, 'error', '待辦只有負責人、沒有內容（範本的 `…` 忘了換掉）'))
            for word in VAGUE_TODO:
                if word in content:
                    out.append(
                        Finding(n + 1, 'warn', f'待辦出現「{word}」，看不出要動哪裡、改成什麼。寫不具體就移到「還沒決定」')
                    )
                    break
        if not found:
            out.append(Finding(sec.start + 1, 'warn', f'「{sec.title}」沒有任何 `- [ ]` 項目'))
    return out


def check_decisions(lines: list[str], sections: list[Section]) -> list[Finding]:
    out = []
    for sec in sections:
        if sec.title != '決議':
            continue
        for n, text in body_lines(lines, sec):
            for word in UNDECIDED_IN_DECISION:
                if word in text:
                    out.append(Finding(n + 1, 'warn', f'決議裡出現「{word}」，這件事可能沒拍板，該放「還沒決定」'))
                    break
    return out


def check_conclusion_lines(lines: list[str], fenced: list[bool], sections: list[Section]) -> list[Finding]:
    """教學細節每個 ### 第一行要是重點；討論細節標題下面直接列結論 bullet。"""
    out = []
    for sec in sections:
        topics: list[int] = [i for i in range(sec.start + 1, sec.end) if not fenced[i] and H3_RE.match(lines[i])]
        if not topics:
            continue
        if sec.title == '討論細節':
            for idx, start in enumerate(topics):
                stop = topics[idx + 1] if idx + 1 < len(topics) else sec.end
                first = next((lines[i].strip() for i in range(start + 1, stop) if lines[i].strip()), '')
                if first.startswith('**項目結論**：') or first.startswith('**結論**：'):
                    out.append(
                        Finding(
                            start + 1,
                            'error',
                            '這個主題不要寫「項目結論」或「結論」小標，標題下面直接列結論',
                        )
                    )
                elif not first.startswith('- '):
                    out.append(
                        Finding(
                            start + 1,
                            'error',
                            f'這個主題標題下面要直接列結論（`- **標籤**：完整句`），現在是：{first[:30] or "（空的）"}',
                        )
                    )
            continue
        lead = CONCLUSION_LEAD.get(sec.title)
        if not lead:
            continue
        for idx, start in enumerate(topics):
            stop = topics[idx + 1] if idx + 1 < len(topics) else sec.end
            first = next((lines[i].strip() for i in range(start + 1, stop) if lines[i].strip()), '')
            leads = lead if isinstance(lead, tuple) else (lead,)
            if not any(first.startswith(l) for l in leads):
                shown = '／'.join(leads)
                out.append(Finding(start + 1, 'error', f'這個主題第一行要是 {shown}，現在是：{first[:30] or "（空的）"}'))
    return out


DIALOGUE_BULLET_RE = re.compile(
    r'^-\s+(?!\*\*)(?:[A-Za-z][\w.\-]*|[\u4e00-\u9fff]{1,4})(?:：|:| (?:認為|指出|覺得|說) )'
)
PROPOSED_BY_RE = re.compile(r'（[^）]*提出）')
OLD_CONCLUSION_RE = re.compile(r'^\*\*(?:項目)?結論\*\*：')
TYPED_POINT_RE = re.compile(r'^-\s+\*\*(?:問題|決策)\*\*：')


def check_dialogue_bullets(lines: list[str], fenced: list[bool], sections: list[Section]) -> list[Finding]:
    """討論細節：標題下直接列結論；提問重點是誰提出了哪個關鍵問題／決策。可 0／1／多人。"""
    out = []
    for sec in sections:
        if sec.title != '討論細節':
            continue
        topics: list[int] = [i for i in range(sec.start + 1, sec.end) if not fenced[i] and H3_RE.match(lines[i])]
        for n, text in body_lines(lines, sec):
            if fenced[n]:
                continue
            if OLD_CONCLUSION_RE.match(text):
                out.append(
                    Finding(
                        n + 1,
                        'error',
                        '討論細節不要寫「項目結論」或「結論」小標。標題下面直接列結論；誰提出了哪個關鍵問題／決策放「**提問重點**：」',
                    )
                )
            if TYPED_POINT_RE.match(text):
                out.append(
                    Finding(
                        n + 1,
                        'error',
                        '提問重點不要標「問題」或「決策」，直接列這個人提出的重點',
                    )
                )
            if PROPOSED_BY_RE.search(text):
                out.append(
                    Finding(
                        n + 1,
                        'error',
                        '討論細節不要寫「（誰提出）」。已確認的結論直接列（不要掛名）；誰提出了哪個關鍵問題／決策放到提問重點、按人分組',
                    )
                )
            if text.startswith('- ') and DIALOGUE_BULLET_RE.match(text):
                out.append(
                    Finding(
                        n + 1,
                        'error',
                        '討論細節不要寫成「誰：…」或「誰問了什麼」。結論直接列 `- **標籤**：完整句`；提問重點有人就把人名單獨一行，下面直接列重點',
                    )
                )
        for idx, start in enumerate(topics):
            stop = topics[idx + 1] if idx + 1 < len(topics) else sec.end
            q_at = next(
                (i for i in range(start + 1, stop) if not fenced[i] and lines[i].strip().startswith('**提問重點**：')),
                None,
            )
            if q_at is None:
                continue
            has_q = any(
                not fenced[i] and lines[i].lstrip().startswith('- ')
                for i in range(q_at + 1, stop)
            )
            if not has_q:
                out.append(
                    Finding(
                        q_at + 1,
                        'error',
                        '「提問重點」寫了標題就要有內容；沒有就把這整段刪掉，不要留空標題或硬加人名',
                    )
                )
    return out


def check_prose(lines: list[str], fenced: list[bool]) -> list[Finding]:
    """連續散文超過 3 行就該拆 bullet。總結用合成段，不計入。"""
    out: list[Finding] = []
    run_start = None
    run = 0
    in_overview = False
    for i, raw in enumerate(lines + ['']):
        text = raw.strip() if i < len(lines) else ''
        if i < len(lines) and not fenced[i]:
            m = H2_RE.match(lines[i])
            if m:
                in_overview = strip_optional(m.group(2)) in OVERVIEW_TITLES
        is_prose = bool(text) and not fenced[i] if i < len(lines) else False
        if is_prose:
            if text.startswith(('#', '-', '*', '|', '>', '```')) or text == '---':
                is_prose = False
            if in_overview:
                is_prose = False
        if is_prose:
            run += 1
            if run_start is None:
                run_start = i
        else:
            if run > MAX_PROSE_LINES and run_start is not None:
                out.append(Finding(run_start + 1, 'warn', f'連續 {run} 行散文，超過 {MAX_PROSE_LINES} 行就該拆成 bullet'))
            run = 0
            run_start = None
    return out


def check_warnings_have_quote(lines: list[str], fenced: list[bool]) -> list[Finding]:
    """每個 ⚠️ 要附逐字稿原文；「不清楚／指向畫面」還要附錄音時間戳。"""
    out = []
    for i, line in enumerate(lines):
        if fenced[i] or '⚠️' not in line:
            continue
        # 原文可以用 `code`、「」或 ⟦⟧ 標出，也接受「：」後面直接接原文
        if not any(mark in line for mark in ('`', '「', '⟦', '：')):
            out.append(Finding(i + 1, 'warn', '⚠️ 後面沒有附逐字稿原文片段，補不出來就把那段刪掉'))
        if any(token in line for token in ('此處逐字稿不清楚', '此處講者指向畫面')) and not TIMESTAMP_RE.search(
            line
        ):
            out.append(
                Finding(
                    i + 1,
                    'error',
                    '⚠️ 要附錄音時間，寫成「去聽錄音 HH:MM:SS」，方便直接跳去聽',
                )
            )
    return out


def check_footer(lines: list[str]) -> list[Finding]:
    if not any(FOOTER in line for line in lines[-6:]):
        return [Finding(len(lines), 'error', f'檔尾缺少「{FOOTER}」')]
    return []


def check_leftovers(lines: list[str]) -> list[Finding]:
    out = []
    for i, line in enumerate(lines):
        for token in TEMPLATE_LEFTOVERS:
            if token in line:
                out.append(Finding(i + 1, 'warn', f'看起來是範本的示範內容沒換掉：「{token}」'))
                break
    return out


# ----------------------------------------------------------------------- 主流程


def lint(path: Path) -> list[Finding]:
    lines = path.read_text(encoding='utf-8').splitlines()
    if not lines:
        return [Finding(0, 'error', '檔案是空的')]

    fenced = mark_fences(lines)
    findings: list[Finding] = []
    findings += check_comments(lines, fenced)
    findings += check_header_table(lines)
    findings += check_participants(lines)
    findings += check_footer(lines)
    findings += check_leftovers(lines)
    findings += check_prose(lines, fenced)
    findings += check_warnings_have_quote(lines, fenced)

    kind, expected = detect_kind(lines)
    if kind is None:
        findings.append(Finding(1, 'error', '認不出用哪一個範本（缺少 `# 會議摘要` 或 `# 教學筆記`）'))
        return sorted(findings, key=lambda f: (f.line, f.level))

    sections = split_sections(lines, fenced)
    findings += check_sections(sections, expected)
    findings += check_empty_sections(lines, sections)
    findings += check_overview(lines, sections)
    findings += check_todos(lines, sections)
    findings += check_decisions(lines, sections)
    findings += check_conclusion_lines(lines, fenced, sections)
    findings += check_dialogue_bullets(lines, fenced, sections)

    return sorted(findings, key=lambda f: (f.line, f.level))


def main() -> int:
    parser = argparse.ArgumentParser(description='檢查會議記錄有沒有照範本規則寫')
    parser.add_argument('paths', nargs='+', type=Path, help='會議記錄 .md（可多個）')
    parser.add_argument('--quiet', action='store_true', help='只印有問題的檔案')
    args = parser.parse_args()

    worst = 0
    for path in args.paths:
        if not path.exists():
            print(f'❌ 找不到檔案：{path}', file=sys.stderr)
            worst = 1
            continue

        findings = lint(path)
        errors = [f for f in findings if f.level == 'error']
        warns = [f for f in findings if f.level == 'warn']

        if not findings:
            if not args.quiet:
                print(f'✅ {path.name}：沒有問題')
            continue

        print(f'\n{path}')
        for f in findings:
            icon = '❌' if f.level == 'error' else '⚠️ '
            where = f'第 {f.line} 行' if f.line else '整份檔案'
            print(f'  {icon} {where}：{f.message}')
        print(f'  —— 錯誤 {len(errors)}、提醒 {len(warns)}')

        if errors:
            worst = 1

    return worst


if __name__ == '__main__':
    sys.exit(main())
