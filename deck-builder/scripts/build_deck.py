#!/usr/bin/env python3
"""Build an editable .pptx from a JSON deck spec.

    python3 build_deck.py --spec deck.json --out output.pptx

Two modes, chosen by spec["style"]:

  company | custom  -- open the template, strip its own slides (keeping master +
                       layouts), then add slides on its layouts. Output inherits real
                       master inheritance, so the user can keep editing in PowerPoint
                       with the template's theme intact.
  recommended       -- blank 16:9 deck, every slide drawn by this script from the
                       palette/grid in references/recommended-style.md.

See references/spec-format.md for the spec schema.
"""

import argparse
import collections
import json
import os
import re
import sys
import zipfile

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.oxml.ns import qn
    from pptx.util import Inches, Pt, Emu
except ImportError:
    sys.exit("python-pptx is not installed. Run: pip3 install python-pptx")


# ---------------------------------------------------------------- palette

def rgb(h):
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


PRIMARY      = rgb("0d63ba")
PRIMARY_DARK = rgb("0b539d")
TEXT         = rgb("13182c")
TEXT_2       = rgb("5a5f6e")
RULE         = rgb("d8d8d8")
PANEL        = rgb("f4f6f9")
WHITE        = rgb("ffffff")

# Typography: Segoe UI for latin, Microsoft JhengHei (微軟正黑體) for Chinese.
# Written as a:latin and a:ea respectively, so one run renders both scripts correctly.
# Override per deck with spec["fonts"] = {"latin": ..., "cjk": ...}.
LATIN_FONT = "Segoe UI"
CJK_FONT   = "Microsoft JhengHei"

EMU_PER_IN = 914400

# Company template geometry (inches) -- from the master, see references/company-template.md
BODY_BOX = (0.92, 1.60, 11.50, 4.80)

# Recommended-style grid (inches)
R_MARGIN_L, R_MARGIN_T, R_WIDTH = 0.90, 0.55, 11.53
R_BODY_Y, R_BODY_H = 1.75, 4.90
R_COL_W = 5.55
R_COL2_X = 6.88

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print("WARN  " + msg, file=sys.stderr)


def die(msg):
    sys.exit("ERROR  " + msg)


# ---------------------------------------------------------------- text helpers

def apply_fonts(spec):
    """Let a spec override the two typefaces. Called once, before any slide is built."""
    global LATIN_FONT, CJK_FONT
    fonts = spec.get("fonts") or {}
    LATIN_FONT = fonts.get("latin", LATIN_FONT)
    CJK_FONT = fonts.get("cjk", CJK_FONT)


def _set_cjk(run, cjk=None):
    """Set the east-asian and complex-script typefaces on a run.

    python-pptx's font.name only writes a:latin. Without a:ea, Chinese text falls back
    to whatever the renderer picks, which is usually the wrong face.
    """
    cjk = cjk or CJK_FONT
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", cjk)


def style_run(run, text, size=None, color=None, bold=None,
              font=None, cjk=None, italic=None):
    """Write text into a run and style it. Paragraph-level font settings silently
    no-op in python-pptx, so all styling has to happen here."""
    run.text = text
    f = run.font
    if size is not None:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    f.name = font or LATIN_FONT
    if color is not None:
        f.color.rgb = color
    _set_cjk(run, cjk)
    return run


def fill_text_frame(tf, lines, size, color, bullet_char=None,
                    space_after=12, bold=False, sub_size=None, sub_color=None):
    """Replace a text frame's contents with `lines`.

    A line prefixed with two spaces becomes a level-2 item.
    """
    tf.word_wrap = True
    tf.clear()
    sub_size = sub_size or max(size - 2, 10)
    sub_color = sub_color or color

    for i, raw in enumerate(lines):
        sub = raw.startswith("  ")
        text = raw.strip()
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.level = 1 if sub else 0
        para.space_after = Pt(space_after if not sub else max(space_after - 4, 4))
        if bullet_char:
            text = ("– " if sub else bullet_char + " ") + text
        style_run(para.add_run(), text,
                  size=sub_size if sub else size,
                  color=sub_color if sub else color,
                  bold=False if sub else bold)


def est_height_in(lines, size_pt, width_in):
    """Rough wrapped height in inches. CJK glyphs run ~2x the width of latin."""
    total = 0
    for raw in lines:
        text = raw.strip()
        weight = sum(2 if ord(c) > 0x2E80 else 1 for c in text)
        cpl = max(8.6 * width_in * (18.0 / max(size_pt, 1)), 1)
        total += max(1, int(weight / cpl + 0.999))
    return total * (size_pt * 1.45 / 72) + len(lines) * 0.19


def grow_to_fit(shape, lines, size_pt, bottom_limit_in=6.85):
    """Enlarge a placeholder that's too short for its content.

    Some template placeholders are caption-sized (layout 21's BODY is 0.48in tall).
    Filling one with three bullets overflows silently, so grow it — bounded by the
    footer row — rather than let text spill off the slide.
    """
    w_in = (shape.width or Inches(11.5)) / EMU_PER_IN
    need = est_height_in(lines, size_pt, w_in)
    have = (shape.height or 0) / EMU_PER_IN
    if need <= have:
        return
    top_in = (shape.top or 0) / EMU_PER_IN
    shape.height = Inches(min(need, max(bottom_limit_in - top_in, have)))


def add_notes(slide, text):
    if not text:
        return
    tf = slide.notes_slide.notes_text_frame
    tf.text = ""
    style_run(tf.paragraphs[0].add_run(), text, size=12, color=TEXT, bold=False)


# ---------------------------------------------------------------- validation

def check_content(idx, spec):
    bullets = spec.get("bullets") or spec.get("paragraphs") or []
    if len(bullets) > 8:
        warn(f"slide {idx}: {len(bullets)} bullets (>8) — likely to overflow; "
             "split the slide instead")
    for b in bullets:
        if len(b.strip()) > 120:
            warn(f"slide {idx}: a line is {len(b.strip())} chars — that's a paragraph, "
                 "move it to speaker notes")
    if "[待補" in json.dumps(spec, ensure_ascii=False) or "[TODO" in json.dumps(spec):
        warn(f"slide {idx}: contains an unresolved placeholder marker")
    n = sum(1 for k in ("bullets", "paragraphs", "table") if spec.get(k))
    if n > 1:
        die(f"slide {idx}: use only one of bullets / paragraphs / table")
    img = spec.get("image")
    if img and not os.path.isfile(img):
        die(f"slide {idx}: image not found: {img}")


# ---------------------------------------------------------------- tables

def add_table(slide, table_spec, x, y, w, h, header_fill=PRIMARY,
              header_color=WHITE, band=PANEL, size=14):
    headers = table_spec.get("headers") or []
    rows = table_spec.get("rows") or []
    if not rows:
        die("table has no rows")
    ncols = len(headers) if headers else len(rows[0])
    nrows = len(rows) + (1 if headers else 0)

    shape = slide.shapes.add_table(nrows, ncols, Inches(x), Inches(y),
                                   Inches(w), Inches(h))
    table = shape.table
    r0 = 0

    if headers:
        for c, text in enumerate(headers):
            cell = table.cell(0, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.clear()
            style_run(tf.paragraphs[0].add_run(), str(text),
                      size=size, color=header_color, bold=True)
        r0 = 1

    for r, row in enumerate(rows):
        if len(row) != ncols:
            die(f"table row {r} has {len(row)} cells, expected {ncols}")
        for c, text in enumerate(row):
            cell = table.cell(r + r0, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = band if r % 2 else WHITE
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.clear()
            style_run(tf.paragraphs[0].add_run(), str(text),
                      size=size, color=TEXT, bold=False)
    return shape


def place_image(slide, path, x, y, max_w, max_h):
    """Insert a picture scaled to fit the box, aspect preserved, centred.

    add_picture with no size uses the image's native EMU size, so we can read that back
    and rescale — no Pillow needed.
    """
    pic = slide.shapes.add_picture(path, Inches(x), Inches(y))
    scale = min(Inches(max_w) / pic.width, Inches(max_h) / pic.height)
    if scale < 1 or scale > 1:
        pic.width = Emu(int(pic.width * scale))
        pic.height = Emu(int(pic.height * scale))
    pic.left = Emu(int(Inches(x) + (Inches(max_w) - pic.width) / 2))
    pic.top = Emu(int(Inches(y) + (Inches(max_h) - pic.height) / 2))
    return pic


# ================================================================ company / custom

def strip_slides(prs):
    """Remove the template's own slides, keeping master, layouts and theme.

    drop_rel is essential: without it the slide parts stay in the package, producing
    duplicate zip entries and carrying the template's full media payload into the output.
    """
    part = prs.part
    lst = prs.slides._sldIdLst
    for sldId in list(lst):
        part.drop_rel(sldId.rId)
        lst.remove(sldId)


GENERIC_WORDS = ("simple", "basic", "plain", "default", "blank", "content",
                 "general", "standard", "custom")


def specificity(name):
    """0 if the name is reusable for any topic, 1 if it asserts a subject.

    Used to pick which layout in a group to keep. "Content_heading_simple" beats
    "Table" and "Comparison chart": all three are a lone title box, but only the first
    doesn't claim the slide is something it may not be.

    Deliberately binary. Ranking "Headings_Courts" against "Headings_Fire&EMS" by name
    length or word count is arbitrary — neither is more reusable than the other, so
    those ties fall through to template order instead.
    """
    low = name.strip().lower()
    return 0 if any(w in low for w in GENERIC_WORDS) else 1


def is_dark_layout(lay, xml):
    """True if the layout has a dark background, so text on it must be light.

    Two signals, either is enough:
      - a <p:bg> solid/gradient fill that is dark
      - a full-bleed shape (>=95% of the slide) whose fill is dark

    Needed because a light and a dark layout can have identical placeholder geometry --
    the company template's 'Content Heading' and 'Content Heading Dark' are exactly that
    pair. They are NOT interchangeable: one takes #13182c text, the other white.
    """
    def dark(hexv):
        r, g, b = (int(hexv[i:i+2], 16) for i in (0, 2, 4))
        return (0.299 * r + 0.587 * g + 0.114 * b) < 128

    bg = re.search(r"<p:bg>.*?</p:bg>", xml, re.S)
    if bg and any(dark(h) for h in
                  re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', bg.group(0))):
        return True

    # A rectangle covering the whole slide is a background by another name.
    full = 0.95 * prs_area(lay)
    for sh in lay.shapes:
        if sh.shape_type is None or not all((sh.width, sh.height)):
            continue
        if sh.width * sh.height < full:
            continue
        cols = re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', sh._element.xml)
        if cols and all(dark(h) for h in cols[:2]):   # solid, or the gradient's first stops
            return True
    return False


def prs_area(lay):
    p = lay.part.package.presentation_part.presentation
    return p.slide_width * p.slide_height


def layout_groups(prs, path):
    """Group layouts by placeholder geometry, plus whether the background is dark.

    Background *art* is deliberately ignored: a different photo behind the same title
    and subtitle boxes is the same layout. Background *tone* is not, because a dark
    layout needs light text — 'Content Heading' and 'Content Heading Dark' have identical
    geometry but take opposite text colours, so collapsing them would make one of them
    unreachable and put #13182c text on a navy background.

    Returns (groups, redirect, dark):
      groups   -- list of [(index, name, decorative_words), ...], canonical first
      redirect -- lowercased duplicate name -> canonical name
      dark     -- set of layout names (lowercased) needing light text
    """
    z = zipfile.ZipFile(path)
    groups = collections.defaultdict(list)
    dark = set()

    for i, lay in enumerate(prs.slide_layouts):
        phs = tuple(sorted(
            (p.placeholder_format.idx, str(p.placeholder_format.type),
             p.left, p.top, p.width, p.height) for p in lay.placeholders))
        xml = z.read(str(lay.part.partname)[1:]).decode("utf-8", "replace")
        words = " ".join(t for t in re.findall(r"<a:t>([^<]*)</a:t>", xml)
                         if t.strip() and "Click to edit" not in t
                         and "Click icon" not in t and t.strip() != "‹#›")
        on_dark = is_dark_layout(lay, xml)
        if on_dark:
            dark.add(lay.name.strip().lower())
        groups[(phs, on_dark)].append((i, lay.name, words))

    out, redirect = [], {}
    for members in groups.values():
        # Canonical = the most generic layout in the group, so neither its name nor the
        # wording burnt into its art contradicts the slide: a reusable name first, then
        # the least decorative wording ("HEADING" over "STANDARD TABLE"), then the
        # template's own order. That last tiebreak is what settles a group of equally
        # specific siblings like the 12 Headings_* product lines — the first one the
        # template author wrote, rather than whichever name happens to be shortest.
        members.sort(key=lambda t: (specificity(t[1]), len(t[2]), t[0]))
        out.append(members)
        canon = members[0][1]
        for _, name, _ in members[1:]:
            redirect[name.strip().lower()] = canon
    return out, redirect, dark


def log_dupes(groups, redirect):
    """Report the collapse, so a silent redirect never surprises anyone."""
    total = sum(len(g) for g in groups)
    print(f"  layouts: {total} in the template -> {len(groups)} distinct arrangements "
          f"({len(redirect)} collapsed)")
    for g in groups:
        if len(g) > 1:
            print(f"    keep '{g[0][1]}' over: "
                  + ", ".join(f"'{n}'" for _, n, _ in g[1:]))


def resolve_layout(prs, ref, idx, redirect=None):
    layouts = list(prs.slide_layouts)
    if isinstance(ref, int):
        if not 0 <= ref < len(layouts):
            die(f"slide {idx}: layout index {ref} out of range (0–{len(layouts)-1})")
        return layouts[ref]
    if ref is None:
        die(f"slide {idx}: no layout specified")
    want = str(ref).strip().lower()

    canon = (redirect or {}).get(want)
    if canon:
        warn(f"slide {idx}: layout {ref!r} lays its text out exactly like {canon!r}, so "
             f"only one of them is kept — using {canon!r}. If you wanted {ref!r} for its "
             'background art specifically, set "collapse_layouts": false in the spec.')
        want = canon.strip().lower()

    for lay in layouts:
        if lay.name.strip().lower() == want:
            return lay
    names = "\n  ".join(f"[{i}] {l.name}" for i, l in enumerate(layouts))
    die(f"slide {idx}: no layout named {ref!r}. Available:\n  {names}")


def set_ph_text(ph, text, cjk=None):
    """Fill a placeholder, keeping the layout/master's inherited styling.

    Deliberately does not touch size or colour — that's the whole point of using the
    template's placeholders. But both typefaces are set explicitly: the company master's
    titleStyle specifies Open Sans for a:ea, which is a latin-only face, so Chinese in a
    title would fall through to a renderer default.
    """
    tf = ph.text_frame
    tf.clear()
    run = tf.paragraphs[0].add_run()
    run.text = text
    run.font.name = LATIN_FONT
    _set_cjk(run, cjk)
    return run


def drop_empty_placeholders(slide):
    """Delete placeholders left unfilled.

    An empty placeholder is invisible when presenting but shows 'Click to add text' in
    edit view, and the user is going to keep editing this file.
    """
    for shape in list(slide.placeholders):
        t = str(shape.placeholder_format.type)
        if "SLIDE_NUMBER" in t or "FOOTER" in t or "DATE" in t:
            continue
        if shape.has_text_frame and shape.text_frame.text.strip():
            continue
        if not shape.has_text_frame:      # a filled picture placeholder
            continue
        shape._element.getparent().remove(shape._element)


def ph_by_type(slide, *types):
    for ph in slide.placeholders:
        try:
            t = str(ph.placeholder_format.type)
        except Exception:
            continue
        if any(name in t for name in types):
            return ph
    return None


def build_from_template(spec, out):
    tpl = spec.get("template")
    if not tpl:
        die("style 'company'/'custom' requires spec['template']")
    if not os.path.isfile(tpl):
        die(f"template not found: {tpl}")
    if os.path.abspath(tpl) == os.path.abspath(out):
        die("refusing to write over the template — choose a different --out")

    prs = Presentation(tpl)
    groups, redirect, dark_layouts = layout_groups(prs, tpl)
    if spec.get("collapse_layouts") is False:
        # Escape hatch: when the background art is the reason for the choice — a section
        # that genuinely is about Fire & EMS — honour the exact name asked for.
        print(f"  layouts: collapsing disabled, all "
              f"{sum(len(g) for g in groups)} kept as-is")
        redirect = {}
    else:
        log_dupes(groups, redirect)
    if dark_layouts:
        print(f"  dark layouts (text flips to white): "
              + ", ".join(sorted(dark_layouts)))
    strip_slides(prs)

    for i, s in enumerate(spec["slides"], 1):
        check_content(i, s)
        layout = resolve_layout(prs, s.get("layout"), i, redirect)
        slide = prs.slides.add_slide(layout)

        # On a dark layout the placeholders already inherit light text from the layout,
        # but anything we add ourselves would default to #13182c and vanish.
        on_dark = layout.name.strip().lower() in dark_layouts
        body_color = WHITE if on_dark else TEXT
        sub_color = rgb("e7e6e6") if on_dark else TEXT_2

        title = s.get("title")
        if title:
            ph = ph_by_type(slide, "CENTER_TITLE", "TITLE")
            if ph is not None:
                set_ph_text(ph, title)   # inherit the master's title styling
            else:
                tb = slide.shapes.add_textbox(Inches(0.92), Inches(0.50),
                                              Inches(11.50), Inches(1.0))
                style_run(tb.text_frame.paragraphs[0].add_run(), title,
                          size=28, color=body_color, bold=True)

        sub = s.get("subtitle")
        if sub:
            ph = ph_by_type(slide, "SUBTITLE")
            if ph is not None:
                set_ph_text(ph, sub)
            else:
                warn(f"slide {i}: layout '{layout.name}' has no subtitle placeholder "
                     "— subtitle rendered as a textbox")
                tb = slide.shapes.add_textbox(Inches(0.92), Inches(1.55),
                                              Inches(11.50), Inches(0.6))
                style_run(tb.text_frame.paragraphs[0].add_run(), sub,
                          size=18, color=sub_color)

        lines = s.get("bullets") or s.get("paragraphs")
        img = s.get("image")
        if lines:
            bullet = "•" if s.get("bullets") else None
            # BODY first: on layouts 21–23 the OBJECT placeholder is the image slot,
            # so text must not claim it when there's also an image.
            body = ph_by_type(slide, "BODY")
            if body is None and not img:
                body = ph_by_type(slide, "OBJECT")
            if body is not None:
                fill_text_frame(body.text_frame, lines, size=20, color=body_color,
                                bullet_char=bullet, space_after=14)
                grow_to_fit(body, lines, 20)
            else:
                # ~20 of the 25 company layouts are title-only; add our own box.
                x, y, w, h = BODY_BOX
                if img:
                    w = 6.10
                tb = slide.shapes.add_textbox(Inches(x), Inches(y),
                                              Inches(w), Inches(h))
                fill_text_frame(tb.text_frame, lines, size=20, color=body_color,
                                bullet_char=bullet, space_after=14)

        if s.get("table"):
            add_table(slide, s["table"], 0.92, 1.70, 11.50,
                      min(0.45 * (len(s["table"].get("rows", [])) + 1), 4.9))

        if img:
            pic_ph = ph_by_type(slide, "PICTURE")
            if pic_ph is not None:
                pic_ph.insert_picture(img)
            elif lines:
                place_image(slide, img, 7.20, 1.70, 5.20, 4.60)
            else:
                place_image(slide, img, 0.92, 1.70, 11.50, 4.90)

        drop_empty_placeholders(slide)
        add_notes(slide, s.get("notes"))

    finish(prs, spec, out)


# ================================================================ recommended

def r_headline(slide, text, rule=True):
    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_MARGIN_T),
                                  Inches(R_WIDTH), Inches(0.90))
    tf = tb.text_frame
    tf.word_wrap = True
    tb.name = "db:headline"
    style_run(tf.paragraphs[0].add_run(), text, size=28, color=TEXT, bold=True)
    if rule:
        from pptx.enum.shapes import MSO_SHAPE
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(R_MARGIN_L),
                                     Inches(1.52), Inches(2.2), Pt(3))
        bar.fill.solid()
        bar.fill.fore_color.rgb = PRIMARY
        bar.line.fill.background()
        bar.shadow.inherit = False


def r_slide_number(slide, n):
    tb = slide.shapes.add_textbox(Inches(12.10), Inches(6.90),
                                  Inches(0.60), Inches(0.30))
    tb.name = "db:label"
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    style_run(p.add_run(), str(n), size=11, color=TEXT_2)


def build_recommended(spec, out):
    prs = Presentation()
    prs.slide_width = Emu(12192000)
    prs.slide_height = Emu(6858000)
    blank = prs.slide_layouts[6]

    for i, s in enumerate(spec["slides"], 1):
        check_content(i, s)
        kind = str(s.get("layout", "content")).strip().lower()
        slide = prs.slides.add_slide(blank)
        lines = s.get("bullets") or s.get("paragraphs")
        bullet = "•" if s.get("bullets") else None

        if kind == "title":
            tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(2.55),
                                          Inches(R_WIDTH), Inches(1.20))
            tb.name = "db:headline"
            p = tb.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            style_run(p.add_run(), s.get("title", ""), size=40, color=TEXT, bold=True)
            if s.get("subtitle"):
                from pptx.enum.shapes import MSO_SHAPE
                bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(6.07),
                                             Inches(3.95), Inches(1.2), Pt(3))
                bar.fill.solid()
                bar.fill.fore_color.rgb = PRIMARY
                bar.line.fill.background()
                bar.shadow.inherit = False
                tb2 = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(4.25),
                                               Inches(R_WIDTH), Inches(0.6))
                tb2.name = "db:label"
                p2 = tb2.text_frame.paragraphs[0]
                p2.alignment = PP_ALIGN.CENTER
                style_run(p2.add_run(), s["subtitle"], size=18, color=TEXT_2)

        elif kind == "section":
            tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(3.05),
                                          Inches(R_WIDTH), Inches(1.0))
            tb.name = "db:headline"
            style_run(tb.text_frame.paragraphs[0].add_run(), s.get("title", ""),
                      size=32, color=PRIMARY, bold=True)

        elif kind == "quote":
            tb = slide.shapes.add_textbox(Inches(1.60), Inches(2.60),
                                          Inches(10.13), Inches(1.80))
            tf = tb.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            style_run(p.add_run(), s.get("title", ""), size=32, color=TEXT, bold=True)
            if s.get("subtitle"):
                p2 = tf.add_paragraph()
                p2.alignment = PP_ALIGN.CENTER
                p2.space_before = Pt(18)
                style_run(p2.add_run(), s["subtitle"], size=16, color=TEXT_2)
            r_slide_number(slide, i)

        elif kind == "closing":
            r_headline(slide, s.get("title", ""))
            if lines:
                tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                              Inches(R_WIDTH), Inches(R_BODY_H))
                fill_text_frame(tb.text_frame, lines, size=18, color=TEXT,
                                bullet_char=bullet, sub_color=TEXT_2)
            r_slide_number(slide, i)

        else:
            r_headline(slide, s.get("title", ""))

            if kind == "two-column":
                cols = s.get("columns") or []
                if len(cols) != 2:
                    die(f"slide {i}: layout 'two-column' needs columns: [[..],[..]]")
                for ci, (cx, col) in enumerate(((R_MARGIN_L, cols[0]),
                                                (R_COL2_X, cols[1]))):
                    tb = slide.shapes.add_textbox(Inches(cx), Inches(R_BODY_Y),
                                                  Inches(R_COL_W), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, col, size=18, color=TEXT,
                                    bullet_char="•", sub_color=TEXT_2)

            elif kind == "table":
                if not s.get("table"):
                    die(f"slide {i}: layout 'table' needs a table object")
                nrows = len(s["table"].get("rows", [])) + 1
                add_table(slide, s["table"], R_MARGIN_L, R_BODY_Y, R_WIDTH,
                          min(0.42 * nrows, R_BODY_H))

            elif kind == "image-full":
                if not s.get("image"):
                    die(f"slide {i}: layout 'image-full' needs an image")
                place_image(slide, s["image"], R_MARGIN_L, R_BODY_Y,
                            R_WIDTH, R_BODY_H - 0.35)
                if s.get("caption"):
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(6.55),
                                                  Inches(R_WIDTH), Inches(0.3))
                    tb.name = "db:label"
                    style_run(tb.text_frame.paragraphs[0].add_run(), s["caption"],
                              size=12, color=TEXT_2)

            elif kind == "image-right":
                if not s.get("image"):
                    die(f"slide {i}: layout 'image-right' needs an image")
                if lines:
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                                  Inches(R_COL_W), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, lines, size=18, color=TEXT,
                                    bullet_char=bullet, sub_color=TEXT_2)
                place_image(slide, s["image"], R_COL2_X, R_BODY_Y,
                            R_COL_W, R_BODY_H)

            else:  # content
                if kind != "content":
                    warn(f"slide {i}: unknown layout {kind!r} for the recommended "
                         "style — rendered as 'content'")
                if lines:
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                                  Inches(R_WIDTH), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, lines, size=18, color=TEXT,
                                    bullet_char=bullet, sub_color=TEXT_2)
                if s.get("image"):
                    place_image(slide, s["image"], 3.50, R_BODY_Y + 0.20,
                               6.33, R_BODY_H - 0.40)

            r_slide_number(slide, i)

        add_notes(slide, s.get("notes"))

    finish(prs, spec, out)


# ---------------------------------------------------------------- output

def finish(prs, spec, out):
    cp = prs.core_properties
    if spec.get("title"):
        cp.title = spec["title"]
    aud = spec.get("audience")
    if aud:
        cp.comments = f"audience={aud}; style={spec.get('style')}; " \
                      f"language={spec.get('language')}"
    prs.save(out)

    n = len(prs.slides)
    print(f"\nWrote {out}")
    print(f"  slides: {n}")
    print(f"  size:   {os.path.getsize(out) / 1e6:.1f} MB")
    print(f"  style:  {spec.get('style')}  language: {spec.get('language')}")
    if WARNINGS:
        print(f"\n{len(WARNINGS)} warning(s) — see above.")
    print("\nNow run verify_deck.py on it.")


CONFIG_NAME = "config.json"


def skill_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    """Machine-local settings, kept out of the repo.

    Looks for DECK_BUILDER_TEMPLATE in the environment, then <skill>/config.json.
    The company template lives in the user's Documents, which is neither portable nor
    something a shared repo should record — so the path is configured, not committed.
    """
    tpl = os.environ.get("DECK_BUILDER_TEMPLATE")
    if tpl:
        return {"company_template": tpl}
    path = os.path.join(skill_dir(), CONFIG_NAME)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as e:
            warn(f"ignoring unreadable {CONFIG_NAME}: {e}")
    return {}


def resolve_template(spec):
    """Fill in spec['template'] from config when the spec doesn't name one.

    Lets a spec say `"style": "company"` and stay portable. An explicit template in the
    spec always wins, so `custom` decks and one-off templates are unaffected.
    """
    if spec.get("template") or (spec.get("style") or "company").lower() == "recommended":
        return
    cfg = load_config()
    tpl = cfg.get("company_template")
    if not tpl:
        die("no company template configured. Either set \"template\" in the spec, or "
            f"create {os.path.join(skill_dir(), CONFIG_NAME)} with\n"
            '  {"company_template": "/path/to/Template.pptx"}\n'
            "or set DECK_BUILDER_TEMPLATE in the environment. "
            "See references/company-template.md.")
    spec["template"] = os.path.expanduser(tpl)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="path to the deck spec JSON")
    ap.add_argument("--out", required=True, help="output .pptx path")
    ap.add_argument("--force", action="store_true",
                    help="overwrite --out if it exists")
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)

    resolve_template(spec)
    if not spec.get("slides"):
        die("spec has no slides")
    if os.path.exists(args.out) and not args.force:
        die(f"{args.out} already exists — pass --force to overwrite")

    apply_fonts(spec)
    style = (spec.get("style") or "company").lower()
    if style == "recommended":
        build_recommended(spec, args.out)
    elif style in ("company", "custom"):
        build_from_template(spec, args.out)
    else:
        die(f"unknown style {style!r} — use company, recommended or custom")


if __name__ == "__main__":
    main()
