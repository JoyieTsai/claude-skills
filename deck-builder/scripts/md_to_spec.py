#!/usr/bin/env python3
"""Markdown → deck spec (the JSON build_deck.py consumes).

The point: the outline the user approves in step 3 *is* the build input. Two formats
that drift apart is the failure this avoids — an outline in one file and a spec in
another guarantees they diverge, and the deck then argues something the user never
approved.

So this parser accepts the outline shape from `references/narrative.md` verbatim,
including its `### 4 · Content Heading` numbering and `**標題** …` bold labels, as well
as a plainer Markdown form. Run it directly to inspect the spec, or just hand a `.md`
file to `build_deck.py --spec` — it dispatches on the extension.

    python3 md_to_spec.py deck.md            # print the spec
    python3 md_to_spec.py deck.md -o deck.json

Nothing here is lossy in the direction that matters: every field in `spec-format.md`
is reachable from Markdown except `entries` (a hand-written agenda), which stays
JSON-only because the agenda is derived from the deck, not written by hand.
"""

import argparse
import json
import os
import re
import sys

# Deck-level keys, from the frontmatter. Anything else is passed through untouched, so
# a future spec key works here before this file learns about it.
BOOL_KEYS = {"collapse_layouts", "keep_closing"}

# Per-slide field names → spec key. Both English and 繁中, because the outline the user
# reads is Chinese but the spec is not.
FIELDS = {
    "layout": "layout", "版面": "layout",
    "title": "title", "標題": "title", "大標": "title",
    "subtitle": "subtitle", "副標": "subtitle", "副標題": "subtitle",
    "notes": "notes", "備註": "notes", "講者備註": "notes",
    "image": "image", "圖片": "image",
    "caption": "caption", "圖說": "caption",
    "table": "table", "表格": "table",
    "chart": "chart", "圖表": "chart",
    "keep_closing": "keep_closing", "保留結尾": "keep_closing",
}

# These switch where subsequent bullets land, for the recommended style's two-column.
COL_FIELDS = {"左欄": 0, "右欄": 1, "column1": 0, "column2": 1, "col1": 0, "col2": 1}

RE_H1 = re.compile(r"^#\s+(.*)$")
RE_SLIDE = re.compile(r"^#{2,3}\s+(.*)$")
# `4 · Cover`, `4. Cover`, `4、Cover`, `4 - Cover` — outline numbering, not the name.
RE_LEADNUM = re.compile(r"^\d+\s*[·.、:\-–—]\s*")
RE_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
RE_BOLD_FIELD = re.compile(r"^\*\*([^*]+?)\*\*\s*[:：]?\s*(.*)$")
RE_FIELD = re.compile(r"^([A-Za-z_][A-Za-z0-9_ ]*|[一-鿿]+)\s*[:：]\s*(.*)$")
RE_FENCE = re.compile(r"^\s*```+\s*([A-Za-z0-9]*)\s*$")
RE_IMAGE_MARK = re.compile(r"\[image\s*[:：]\s*([^\]]+)\]", re.I)
RE_MD_IMAGE = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
# A whole line in italics is an outline annotation ("_自動列出…_"), not slide content.
RE_ITALIC_ONLY = re.compile(r"^\s*[_*]([^_*].*?)[_*]\s*$")
RE_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


class MdError(ValueError):
    """A problem in the Markdown that the user has to fix — never guessed around."""


def _strip_inline(s):
    """Drop the emphasis markers Markdown uses for the *outline's* benefit.

    The outline is read by a person, so it has `**bold**` and `` `code` ``. Those are
    presentation of the outline, not of the slide — a literal asterisk on the slide is
    almost never what was meant.
    """
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def _scalar(v):
    v = v.strip()
    low = v.lower()
    if low in ("true", "yes", "是"):
        return True
    if low in ("false", "no", "否"):
        return False
    return v


def _split_frontmatter(lines):
    """`---` fenced key: value block at the top. Deliberately not YAML.

    Hand-rolled because a `pip install pyyaml` to read six scalars would make the skill
    fail to run on a fresh clone — which is the whole thing the bundled template fixed.
    """
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return {}, lines
    meta, j = {}, i + 1
    while j < len(lines) and lines[j].strip() != "---":
        line = lines[j].strip()
        if line and not line.startswith("#"):
            m = RE_FIELD.match(line)
            if not m:
                raise MdError(f"frontmatter line {j + 1} is not `key: value`: {line}")
            meta[m.group(1).strip()] = _scalar(m.group(2))
        j += 1
    if j >= len(lines):
        raise MdError("frontmatter opened with `---` but never closed")
    return meta, lines[j + 1:]


def _parse_table(rows):
    """Markdown pipe table → {headers, rows}, separator row dropped."""
    cells = []
    for r in rows:
        r = r.strip()
        if RE_TABLE_SEP.match(r):
            continue
        r = r.strip("|")
        cells.append([_strip_inline(c) for c in r.split("|")])
    if not cells:
        raise MdError("empty table")
    return {"headers": cells[0], "rows": cells[1:]}


def _flush_table(slide, buf):
    if buf:
        slide["table"] = _parse_table(buf)
        buf.clear()


def _finish(slide, tbuf, notes, paras, cols):
    """Close out one slide: attach the buffers, drop what stayed empty."""
    _flush_table(slide, tbuf)
    if notes:
        slide["notes"] = " ".join(notes)
    if paras and not slide.get("bullets"):
        slide["paragraphs"] = paras
    if cols[0] or cols[1]:
        slide["columns"] = [cols[0], cols[1]]
    return slide


def parse(text):
    """Markdown → spec dict. Raises MdError on anything ambiguous."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta, lines = _split_frontmatter(lines)

    spec = {}
    for k, v in meta.items():
        spec[k] = bool(v) if k in BOOL_KEYS else v

    slides = []
    slide = None
    tbuf, notes, paras = [], [], []
    cols = [[], []]
    bullet_target = None          # None → slide bullets; 0/1 → a column
    fence_lang, fence_buf, fence_field = None, [], "chart"

    for n, raw in enumerate(lines, 1):
        line = raw.rstrip()
        stripped = line.strip()

        # --- fenced block (a chart spec) -------------------------------------
        if fence_lang is not None:
            if RE_FENCE.match(line):
                body = "\n".join(fence_buf)
                if slide is None:
                    raise MdError(f"line {n}: code block before any slide heading")
                try:
                    slide[fence_field] = json.loads(body)
                except ValueError as e:
                    raise MdError(f"line {n}: `{fence_field}` block is not valid JSON: {e}")
                fence_lang, fence_buf, fence_field = None, [], "chart"
            else:
                fence_buf.append(raw)
            continue
        m = RE_FENCE.match(line)
        if m and slide is not None:
            fence_lang, fence_buf = m.group(1) or "json", []
            continue

        # --- slide heading ---------------------------------------------------
        m = RE_SLIDE.match(line)
        if m:
            if slide is not None:
                slides.append(_finish(slide, tbuf, notes, paras, cols))
            name = RE_LEADNUM.sub("", _strip_inline(m.group(1))).strip()
            if not name:
                raise MdError(f"line {n}: slide heading has no layout name")
            slide = {"layout": name}
            tbuf, notes, paras = [], [], []
            cols = [[], []]
            bullet_target = None
            continue

        if slide is None:
            # Preamble: an H1 titles the deck, everything else is the outline's own
            # header lines (audience / style / timing) and is not slide content.
            m = RE_H1.match(line)
            if m and "title" not in spec:
                spec["title"] = _strip_inline(m.group(1))
            continue

        if not stripped or stripped in ("---", "***", "___"):
            _flush_table(slide, tbuf)
            continue

        # An `[image: …]` marker can ride along on any line, including a bold one.
        m = RE_IMAGE_MARK.search(line)
        if m:
            slide["image"] = _strip_inline(m.group(1))
            line = RE_IMAGE_MARK.sub("", line).strip().strip("*").strip()
            stripped = line
            if not stripped:
                continue

        m = RE_MD_IMAGE.match(stripped)
        if m:
            slide["image"] = m.group(1).strip()
            continue

        if stripped.startswith("|"):
            tbuf.append(stripped)
            continue
        _flush_table(slide, tbuf)

        if stripped.startswith(">"):
            notes.append(_strip_inline(stripped.lstrip("> ").strip()))
            continue

        m = RE_BULLET.match(line)
        if m:
            indent, txt = len(m.group(1).expandtabs(4)), _strip_inline(m.group(2))
            if not txt:
                continue
            if bullet_target is None:
                # Two spaces is the spec's second-level marker.
                slide.setdefault("bullets", []).append(("  " + txt) if indent >= 2 else txt)
            else:
                cols[bullet_target].append(("  " + txt) if indent >= 2 else txt)
            continue

        # A bold or plain `label: value` field.
        m = RE_BOLD_FIELD.match(stripped) or RE_FIELD.match(stripped)
        if m:
            key, val = m.group(1).strip().lower(), m.group(2).strip()
            if key in COL_FIELDS:
                bullet_target = COL_FIELDS[key]
                continue
            if key in FIELDS:
                target = FIELDS[key]
                if target in ("table", "chart"):
                    # The structure follows on the next lines; remember where it goes.
                    fence_field = target
                    continue
                val = _strip_inline(val)
                if target == "keep_closing":
                    slide[target] = bool(_scalar(val))
                elif target == "notes":
                    notes.append(val)
                elif val:
                    slide[target] = val
                continue
            # An unknown `foo: bar` is prose (a slide can legitimately say
            # "修法: 灰階最淺止於 #767676"), so fall through rather than error.

        if RE_ITALIC_ONLY.match(stripped) and not RE_BOLD_FIELD.match(stripped):
            continue                      # outline annotation, not slide content

        paras.append(_strip_inline(stripped))

    if fence_lang is not None:
        raise MdError("a code block was opened but never closed")
    if slide is not None:
        slides.append(_finish(slide, tbuf, notes, paras, cols))
    if not slides:
        raise MdError("no slides found — each slide starts with a `## <layout>` heading")

    spec["slides"] = slides
    spec.setdefault("style", "company")
    spec.setdefault("language", "zh-TW")
    return spec


def load(path):
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", help="Markdown outline / deck source")
    ap.add_argument("-o", "--out", help="write the spec JSON here (default: stdout)")
    args = ap.parse_args()
    try:
        spec = load(args.md)
    except MdError as e:
        sys.exit(f"error: {os.path.basename(args.md)}: {e}")
    text = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}  ({len(spec['slides'])} slides)")
    else:
        print(text)


if __name__ == "__main__":
    main()
