#!/usr/bin/env python3
"""Check a generated deck for the things that go wrong silently.

    python3 verify_deck.py output.pptx

Reports, per slide: missing title, empty placeholders, overflow risk, tiny or
low-contrast text, off-brand colours, and unresolved [待補: …] / [TODO] markers.
Package-level: duplicate zip entries, file size, orphaned slide parts.

This is the only check available — there's no LibreOffice in this environment, so the
deck cannot be rendered to images for visual inspection. Read the output, fix what it
flags, re-run.

Exit code 1 if any ERROR is reported; 0 for warnings only.
"""

import argparse
import collections
import os
import re
import sys
import zipfile

try:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Pt
except ImportError:
    sys.exit("python-pptx is not installed. Run: pip3 install python-pptx")

EMU_IN = 914400

BRAND = {"0d63ba", "0b539d", "13182c", "e7e6e6", "b4b4b4", "3f3f3f",
         "ffffff", "000000", "fcfcfc", "ff737f", "5a5f6e", "d8d8d8", "f4f6f9"}

# The chart palette, validated with the dataviz validator against this template's
# surfaces — see references/charts.md. Kept separate from BRAND because these are
# data-encoding colours, legitimate inside a chart and nowhere else.
CHART_COLORS = {"0d63ba", "eb6834", "12a06d", "c74d7c", "4a3aa7", "b87c00",
                "008300", "e34948",                              # categorical
                "86b6ef", "6da7ec", "3987e5", "0a4a8c",           # sequential
                "b3401c", "e8825c",                               # diverging arms
                "8c93a3",                                         # de-emphasis
                "d8d8d8", "5a5f6e", "13182c", "ffffff", "4a86c8", "e7e6e6"}

# Segoe UI for latin, Microsoft JhengHei (微軟正黑體) for Chinese.
# The template's own slides also use Lato/Verdana/Open Sans, so those are accepted
# without complaint on latin text — but Chinese must not land in a latin-only face.
EXPECT_LATIN, EXPECT_CJK = "Segoe UI", "Microsoft JhengHei"
LATIN_OK = {EXPECT_LATIN, "Lato", "Verdana", "Open Sans", "Roboto", "Arial"}
CJK_OK = {EXPECT_CJK, "微軟正黑體", "Microsoft JhengHei UI",
          "PingFang TC", "Microsoft YaHei", "微軟雅黑"}

# Rough chars-per-line at a given point size across one inch of width.
CHARS_PER_INCH_AT_18PT = 8.6

errors, warnings = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def luminance(h):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(fg, bg="ffffff"):
    a, b = luminance(fg) + 0.05, luminance(bg) + 0.05
    return round(max(a, b) / min(a, b), 2)


def est_lines(text, size_pt, width_in):
    """Estimate wrapped line count. CJK glyphs are ~2x the width of latin."""
    if not text:
        return 0
    weight = sum(2 if ord(c) > 0x2E80 else 1 for c in text)
    cpl = max(CHARS_PER_INCH_AT_18PT * width_in * (18.0 / max(size_pt, 1)), 1)
    return max(1, int(weight / cpl + 0.999))


A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def is_label(shape):
    """Slide numbers, captions, source lines and cover subtitles — small by design.

    Exempting them keeps the minimum-size and overflow checks pointed at body text,
    which is the only place those rules matter. build_deck.py names such boxes
    "db:label"; the size heuristic covers decks it didn't build.
    """
    if not shape.has_text_frame:
        return False
    if (shape.name or "").startswith("db:label"):
        return True
    h_in = (shape.height or 0) / EMU_IN
    text = shape.text_frame.text.strip()
    return h_in <= 0.42 and len(text) <= 60 and "\n" not in text


def is_title_ph(t):
    """True for TITLE / CENTER_TITLE, but not SUBTITLE.

    python-pptx renders the enum as 'SUBTITLE (4)', which contains the substring
    'TITLE' — so a plain `"TITLE" in t` counts a Cover's subtitle as the headline and
    reports the one-line rule against a box that is meant to hold a longer line.
    """
    return "TITLE" in t and "SUBTITLE" not in t


def is_headline(shape):
    """A slide's heading, whether a placeholder or a drawn textbox."""
    if shape.is_placeholder and is_title_ph(str(shape.placeholder_format.type)):
        return True
    return (shape.name or "").startswith("db:headline")


def check_headline(i, shape):
    """A headline has to be one short line.

    The template's title boxes are a single line tall (0.71in at 32pt on the content
    layouts), so a wrapping headline either overflows or gets autofit-shrunk until it
    stops reading as a heading. Measured against the box's real width and the run's
    real size, since Cover at 46pt in 10.00in wraps much sooner than a content title.
    """
    tf = shape.text_frame
    text = tf.text.strip()
    if not text or "\n" in text:
        if "\n" in text:
            warn(f"slide {i}: headline is on {text.count(chr(10)) + 1} lines — a "
                 "heading should be one short sentence")
        return
    size = 32.0
    for para in tf.paragraphs:
        for run in para.runs:
            if run.font.size:
                size = run.font.size.pt
                break
        break
    w_in = (shape.width or Emu(EMU_IN * 11.5)) / EMU_IN
    h_in = (shape.height or 0) / EMU_IN
    lines = est_lines(text, size, w_in * 0.94)
    if lines > 1:
        fits = h_in >= lines * (size * 1.45 / 72)
        tail = ("it fits the box but stops reading as a heading" if fits
                else "it will overflow or be autofit-shrunk")
        warn(f"slide {i}: headline runs to {lines} lines at {size:g}pt in "
             f"{w_in:.2f}in ({len(text)} chars) — {tail}; shorten it: {text[:50]!r}")


def check_runs(i, tf, on_fill=None, label=False):
    """Contrast, minimum size and CJK typeface, per run.

    on_fill is the cell/shape fill hex when known, so text on the blue table header
    isn't measured against white.
    """
    for para in tf.paragraphs:
        for run in para.runs:
            size = run.font.size.pt if run.font.size else 18.0
            if run.font.size and size < 12 and not label:
                warn(f"slide {i}: {size:g}pt text — too small to read from a room "
                     "(min 14pt, 18pt preferred)")

            try:
                rgbv = run.font.color.rgb
            except Exception:
                rgbv = None
            if rgbv is not None:
                hexv = str(rgbv).lower()
                if hexv not in BRAND:
                    warn(f"slide {i}: off-brand colour #{hexv} — "
                         "check it against the style's palette")
                ratio = contrast(hexv, on_fill or "ffffff")
                need = 3.0 if size >= 24 or (size >= 18.66 and run.font.bold) else 4.5
                if ratio < need:
                    err(f"slide {i}: #{hexv} at {size:g}pt on #{on_fill or 'ffffff'} "
                        f"is {ratio}:1, WCAG AA needs {need}:1")

            rPr = run._r.find(A_NS + "rPr")

            def typeface(tag):
                if rPr is None:
                    return None
                el = rPr.find(A_NS + tag)
                return el.get("typeface") if el is not None else None

            if re.search(r'[一-鿿　-〿＀-￯]', run.text):
                ea = typeface("ea")
                if ea is None:
                    warn(f"slide {i}: Chinese text with no a:ea typeface — "
                         "it will render in a fallback font")
                elif ea not in CJK_OK:
                    warn(f"slide {i}: Chinese text set in {ea!r} — expected "
                         f"{EXPECT_CJK} (微軟正黑體)")

            if re.search(r'[A-Za-z]', run.text):
                lat = typeface("latin")
                if lat is not None and lat not in LATIN_OK and not lat.startswith("+"):
                    warn(f"slide {i}: latin text set in {lat!r} — expected "
                         f"{EXPECT_LATIN}")


def cell_fill_hex(cell):
    try:
        if cell.fill.type is not None and cell.fill.fore_color.rgb is not None:
            return str(cell.fill.fore_color.rgb).lower()
    except Exception:
        pass
    return None


def shape_fill_hex(shape):
    """A text box's own fill, when it has one — it sits between the text and the slide."""
    try:
        if shape.fill.type is not None and shape.fill.fore_color.rgb is not None:
            return str(shape.fill.fore_color.rgb).lower()
    except Exception:
        pass
    return None


def slide_bg_hex(slide):
    """The effective background behind a slide's text, as a hex string.

    Contrast has to be measured against what's actually behind the text. A dark layout
    -- the company template's Cover, Thank you and Content Heading Dark are #0b539d or
    #0d63ba -- would otherwise be assumed white, and white-on-navy title text gets
    reported as a 1.0:1 failure when it's the correct choice.

    Checks the slide's own <p:bg>, then its layout's, then the master's. A full-bleed
    shape counts too, since that's how the Dark layout is built.
    """
    for part in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        el = part._element.find(qn("p:cSld"))
        bg = el.find(qn("p:bg")) if el is not None else None
        if bg is not None:
            cols = re.findall(r'val="([0-9A-Fa-f]{6})"', bg.xml)
            if cols:
                return cols[0].lower()

    prs = slide.part.package.presentation_part.presentation
    full = 0.95 * prs.slide_width * prs.slide_height
    for src in (slide, slide.slide_layout):
        for sh in src.shapes:
            if not all((sh.width, sh.height)) or sh.width * sh.height < full:
                continue
            cols = re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', sh._element.xml)
            if cols:
                return cols[0].lower()
    return "ffffff"


def check_chart(i, shape, bg):
    """Check a native chart: its colours, its series count, and its CJK typefaces.

    A chart is a separate part with its own text properties, so the run-level font rules
    that apply to slide text apply again here — and python-pptx's font.name writes only
    a:latin, so a missing a:ea shows up as one line of Chinese in a fallback face.

    Off-palette series colours matter more in a chart than elsewhere: the palette is
    validated for colour-vision separation as a *set*, so substituting one hue breaks a
    guarantee about the others.
    """
    chart = shape.chart
    xml = chart._chartSpace.xml

    for hexv in {h.lower() for h in
                 re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', xml)}:
        if hexv not in CHART_COLORS:
            warn(f"slide {i}: chart uses #{hexv}, which is not in the validated chart "
                 "palette — the palette's colour-vision separation was measured as a "
                 "set, so one substituted hue invalidates it for the others")

    n_series = len(chart.series)
    if n_series > 8:
        err(f"slide {i}: chart has {n_series} series but there are only 8 fixed "
            "categorical slots — hues are never cycled; fold the tail into 「其他」")

    if not chart.has_legend and n_series >= 2:
        warn(f"slide {i}: chart has {n_series} series and no legend — identity would "
             "be colour-alone, and a .pptx has no hover to fall back on")
    if chart.has_legend and n_series < 2:
        warn(f"slide {i}: a one-series chart with a legend — the headline already "
             "names it")

    # Chinese anywhere in the chart (categories, series names, axis titles) needs a:ea.
    if re.search(r'[一-鿿]', "".join(re.findall(r"<c:v>([^<]*)</c:v>", xml))):
        for defRPr in chart._chartSpace.iter(qn("a:defRPr")):
            ea = defRPr.find(qn("a:ea"))
            if ea is None or ea.get("typeface") not in CJK_OK:
                warn(f"slide {i}: chart has Chinese text but its a:ea typeface is "
                     f"{'missing' if ea is None else repr(ea.get('typeface'))} — it "
                     "will render in a fallback font")
                break

    dark_bg = luminance(bg) < 0.18
    if dark_bg:
        err(f"slide {i}: chart on a dark background (#{bg}) — the palette is validated "
            "against white; on the navy every series measures about 2:1, so the "
            "colours stop working as distinguishable marks. Move it to a light layout.")


def check_slide(i, slide, slide_h_in):
    bg = slide_bg_hex(slide)
    texts = []
    placeholder_empty = []
    has_title = False
    has_table = False
    has_chart = False

    for shape in slide.shapes:
        if getattr(shape, "has_chart", False) and shape.has_chart:
            has_chart = True
            check_chart(i, shape, bg)
            continue

        if shape.is_placeholder:
            t = str(shape.placeholder_format.type)
            if is_title_ph(t):
                has_title = bool(
                    shape.has_text_frame and shape.text_frame.text.strip())
            if shape.has_text_frame and not shape.text_frame.text.strip():
                if "PICTURE" not in t and "OBJECT" not in t:
                    placeholder_empty.append(t)

        if shape.has_table:
            has_table = True
            tbl = shape.table
            for r, row in enumerate(tbl.rows):
                for cell in row.cells:
                    if cell.text.strip():
                        texts.append(cell.text)
                    check_runs(i, cell.text_frame,
                               on_fill=cell_fill_hex(cell) or bg)
            ncols = len(tbl.columns)
            if ncols > 6:
                warn(f"slide {i}: table has {ncols} columns — hard to read from a "
                     "room; split it or move detail to an appendix")
            if len(tbl.rows) > 12:
                warn(f"slide {i}: table has {len(tbl.rows)} rows — likely too dense")
            continue

        if not shape.has_text_frame:
            continue

        tf = shape.text_frame
        full = tf.text
        if full.strip():
            texts.append(full)

        w_in = (shape.width or Emu(EMU_IN * 11.5)) / EMU_IN
        top_in = (shape.top or 0) / EMU_IN
        h_in = (shape.height or 0) / EMU_IN

        label = is_label(shape)
        check_runs(i, tf, on_fill=shape_fill_hex(shape) or bg, label=label)
        if is_headline(shape):
            check_headline(i, shape)

        total_lines = 0
        for para in tf.paragraphs:
            size = None
            for run in para.runs:
                if run.font.size:
                    size = run.font.size.pt
                    break
            total_lines += est_lines(para.text, size or 18.0, w_in)

        if h_in > 0.2 and not label:
            # ~1.45x line spacing at the nominal size
            need_in = total_lines * 0.34
            if need_in > h_in * 1.12:
                warn(f"slide {i}: text needs ~{need_in:.1f}in but the box is "
                     f"{h_in:.1f}in — likely overflow, cut content or split the slide")
        if top_in + h_in > slide_h_in - 0.15:
            warn(f"slide {i}: a shape extends to {top_in + h_in:.2f}in on a "
                 f"{slide_h_in:.2f}in slide — past the safe area")

    joined = "\n".join(texts)
    for m in set(re.findall(r'\[(?:待補|TODO)[^\]]*\]', joined)):
        err(f"slide {i}: unresolved placeholder {m}")

    if not has_title and slide.shapes and any(
            s.is_placeholder and is_title_ph(str(s.placeholder_format.type))
            for s in slide.shapes):
        warn(f"slide {i}: title placeholder is empty")
    for t in placeholder_empty:
        warn(f"slide {i}: empty {t} placeholder — delete it or fill it, "
             "it shows 'Click to add text' in edit view")

    bullets = sum(1 for line in joined.split("\n") if line.strip())
    if bullets > 10 and not has_table and not has_chart:
        warn(f"slide {i}: ~{bullets} text lines — dense; consider splitting")

    notes = ""
    if slide.has_notes_slide:
        notes = slide.notes_slide.notes_text_frame.text.strip()

    # A content slide is one that carries substance beyond its heading — that's what
    # consumes talk time. Covers, section dividers and the closing slide don't.
    body_shapes = 0
    for sh in slide.shapes:
        if (sh.has_table or sh.shape_type == MSO_SHAPE_TYPE.PICTURE
                or (getattr(sh, "has_chart", False) and sh.has_chart)):
            body_shapes += 1
            continue
        if not (sh.has_text_frame and sh.text_frame.text.strip()):
            continue
        if is_headline(sh) or is_label(sh):
            continue
        body_shapes += 1
    return {"has_title": has_title, "chars": len(joined),
            "notes": bool(notes), "is_content": body_shapes > 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        sys.exit(f"not found: {args.path}")

    with zipfile.ZipFile(args.path) as z:
        names = z.namelist()
    dupes = [n for n, c in collections.Counter(names).items() if c > 1]
    if dupes:
        err(f"package has {len(dupes)} duplicate zip entries — slides were removed "
            "without drop_rel; rebuild")

    prs = Presentation(args.path)
    slide_h_in = prs.slide_height / EMU_IN
    n_parts = len([n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)])
    n_slides = len(prs.slides)
    if n_parts != n_slides:
        err(f"{n_parts} slide parts in the package but {n_slides} in the slide list — "
            "orphaned parts; rebuild with drop_rel")

    print(f"\n{os.path.basename(args.path)}")
    print(f"  {os.path.getsize(args.path)/1e6:.1f} MB · {n_slides} slides · "
          f"{prs.slide_width/EMU_IN:.2f} × {slide_h_in:.2f} in")

    stats = [check_slide(i, s, slide_h_in) for i, s in enumerate(prs.slides, 1)]
    no_notes = [i for i, st in enumerate(stats, 1) if not st["notes"]]
    if no_notes:
        warn(f"{len(no_notes)} slide(s) have no speaker notes: "
             f"{', '.join(map(str, no_notes[:12]))}"
             f"{'…' if len(no_notes) > 12 else ''}")

    content = sum(1 for st in stats if st["is_content"])
    print(f"  {content} content slides · est. talk time "
          f"{content * 1.5:.0f}–{content * 2:.0f} min")

    print()
    if errors:
        print(f"ERRORS ({len(errors)}) — fix these:")
        for e in errors:
            print(f"  ✗ {e}")
        print()
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in dict.fromkeys(warnings):
            print(f"  · {w}")
        print()
    if not errors and not warnings:
        print("Clean — no errors, no warnings.\n")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
