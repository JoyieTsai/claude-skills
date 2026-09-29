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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cards    # noqa: E402  -- card grid + Interface Icons; see references/cards.md
import interface_icons  # noqa: E402  -- SVG raster for cover marks the template stores as SVG
import charts   # noqa: E402  -- native pptx charts; see references/charts.md
import md_to_spec   # noqa: E402  -- lets --spec take a .md outline directly


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

# Company template geometry (inches). Title box ends near y=1.26; start the body
# lower so the heading and the content are not stacked on each other.
BODY_BOX = (0.92, 2.40, 11.50, 4.00)
BODY_TOP = 2.40

# Recommended-style grid (inches)
R_MARGIN_L, R_MARGIN_T, R_WIDTH = 0.90, 0.55, 11.53
R_BODY_Y, R_BODY_H = 1.75, 4.90
R_COL_W = 5.55
R_COL2_X = 6.88

WARNINGS = []

# Layout name aliases so old names keep working.
_LAYOUT_ALIASES = {
    "image-right":  "image:right",
    "image-left":   "image:left",
    "image-full":   "image:full",
    "chart-right":  "chart:right",
    "big-number":   "big_number",
}

# Recommended-style dark palette (used when a slide has dark: true).
R_DARK_BG   = PRIMARY          # #0d63ba fill
R_DARK_TEXT = WHITE            # #ffffff
R_DARK_TEXT2 = rgb("e7e6e6")  # light grey for sub-text
R_DARK_BAR  = rgb("6ba5e0")   # lighter blue accent line


def _split_kind(raw):
    """Parse 'cards:icon' → ('cards', 'icon').  No colon → (kind, None).

    Also resolves legacy aliases: 'image-right' → base='image', variant='right'.
    """
    k = raw.strip().lower()
    k = _LAYOUT_ALIASES.get(k, k)
    if ":" in k:
        base, variant = k.split(":", 1)
        return base.strip(), variant.strip()
    return k, None


_CARD_VARIANTS = frozenset({"2-col", "3-col", "4-grid", "2x2", "icon", "number", "image", "steps", "bento", "featured"})


def _cards_variant_of(spec):
    """Card grid/style variant for a slide.

    Preferred: explicit `cards_variant` (needed on company/custom decks where
    `layout` is a master name like Content_heading_simple). Fallback: parse
    from layout when it is `cards:icon` / `cards:3-col` (recommended style).
    """
    explicit = spec.get("cards_variant")
    if explicit:
        v = str(explicit).strip().lower()
        return v if v in _CARD_VARIANTS else explicit
    _, from_layout = _split_kind(str(spec.get("layout", "")))
    if from_layout in _CARD_VARIANTS:
        return from_layout
    return None


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


def add_visual_bullets(slide, lines, x, y, w, h, style_run_fn,
                       color=None, sub_color=None, accent=None,
                       latin=LATIN_FONT, cjk=CJK_FONT):
    """Render bullet lines as accent-line visual items (Gamma-style).

    Each main bullet gets a short colored left-edge bar and is its own textbox
    so spacing and wrapping feel intentional.  Sub-items (two-space indent) are
    rendered smaller and lighter with a dash instead of a bar.
    """
    from pptx.enum.shapes import MSO_SHAPE as _V_MSO

    color     = color     or TEXT
    sub_color = sub_color or TEXT_2
    accent    = accent    or PRIMARY

    BAR_W   = 0.030    # width of the accent bar
    BAR_GAP = 0.14     # gap between bar and text
    TEXT_X  = x + BAR_W + BAR_GAP
    TEXT_W  = w - BAR_W - BAR_GAP
    MAIN_SZ = 18
    SUB_SZ  = 14
    MAIN_H  = 0.48     # row height for a main bullet (holds ~1–2 lines)
    SUB_H   = 0.32
    ROW_GAP = 0.10     # gap between rows
    SUB_IND = 0.22     # extra indent for sub-items

    cur_y = y
    bottom = y + h

    for raw in lines:
        is_sub = raw.startswith("  ")
        text = raw.strip()
        if not text:
            continue

        row_h = SUB_H if is_sub else MAIN_H
        if cur_y + row_h > bottom + 0.20:   # +0.20 tolerance
            break

        if is_sub:
            tb = slide.shapes.add_textbox(
                Inches(TEXT_X + SUB_IND), Inches(cur_y),
                Inches(TEXT_W - SUB_IND), Inches(SUB_H))
            tb.text_frame.word_wrap = True
            style_run_fn(tb.text_frame.paragraphs[0].add_run(),
                         "– " + text, size=SUB_SZ, color=sub_color,
                         font=latin, cjk=cjk)
        else:
            bar = slide.shapes.add_shape(
                _V_MSO.RECTANGLE,
                Inches(x), Inches(cur_y + 0.07),
                Inches(BAR_W), Inches(0.26))
            bar.fill.solid()
            bar.fill.fore_color.rgb = accent
            bar.line.fill.background()
            bar.shadow.inherit = False

            tb = slide.shapes.add_textbox(
                Inches(TEXT_X), Inches(cur_y),
                Inches(TEXT_W), Inches(MAIN_H))
            tb.text_frame.word_wrap = True
            style_run_fn(tb.text_frame.paragraphs[0].add_run(),
                         text, size=MAIN_SZ, color=color,
                         font=latin, cjk=cjk)

        cur_y += row_h + ROW_GAP


def est_lines(text, size_pt, width_in):
    """Rough wrapped line count. CJK glyphs run ~2x the width of latin."""
    weight = sum(2 if ord(c) > 0x2E80 else 1 for c in (text or "").strip())
    cpl = max(8.6 * width_in * (18.0 / max(size_pt, 1)), 1)
    return max(1, int(weight / cpl + 0.999))


def est_height_in(lines, size_pt, width_in):
    """Rough wrapped height in inches."""
    total = sum(est_lines(raw, size_pt, width_in) for raw in lines)
    return total * (size_pt * 1.45 / 72) + len(lines) * 0.19


def grow_to_fit(shape, lines, size_pt, bottom_limit_in=6.85):
    """Enlarge a placeholder that's too short for its content.

    Some template placeholders are caption-sized (layout 21's BODY is 0.48in tall).
    Filling one with three bullets overflows silently, so grow it — bounded by the
    footer row — rather than let text spill off the slide.
    """
    left, top, width = shape.left, shape.top, shape.width
    w_in = (width or Inches(11.5)) / EMU_PER_IN
    need = est_height_in(lines, size_pt, w_in)
    have = (shape.height or 0) / EMU_PER_IN
    if need <= have:
        return
    top_in = (top or 0) / EMU_PER_IN
    # Writing any one dimension on a placeholder that inherits its geometry
    # materialises an <a:xfrm> and zeroes the rest, so restate all four.
    shape.left, shape.top, shape.width = left, top, width
    shape.height = Inches(min(need, max(bottom_limit_in - top_in, have)))


def ph_font_size(ph, default=32.0):
    """The point size a placeholder's first line will actually render at.

    Layouts carry an explicit sz on their title runs (32pt on Content Heading, 46pt on
    Cover), and that's what governs whether a headline wraps. Falls back to the master's
    titleStyle size when the layout doesn't say.
    """
    sizes = re.findall(r'sz="(\d+)"', ph._element.xml)
    return int(sizes[0]) / 100.0 if sizes else default


def check_headline(idx, text, ph=None, width_in=11.50, size_pt=32.0, height_in=0.0):
    """A headline must be one short line.

    Measured against the actual box width and font size rather than a fixed character
    count, because Cover at 46pt in 10.00in holds about half of what Content Heading
    does at 32pt in 11.50in, and the Headings_* boxes are only 4.90in wide.

    Whether it also *overflows* depends on the box height — the content layouts' title
    is 0.71in, one line, but Headings_* is 1.64in and physically fits two. The rule is
    one line either way; the message says which problem it is.
    """
    if not text:
        return
    if ph is not None:
        if ph.width:
            width_in = ph.width / EMU_PER_IN
        if ph.height:
            height_in = ph.height / EMU_PER_IN
        size_pt = ph_font_size(ph, size_pt)

    # Titles are inset from the box edge, so the usable width is slightly narrower.
    lines = est_lines(text, size_pt, width_in * 0.94)
    if lines <= 1:
        return

    fits = height_in >= lines * (size_pt * 1.45 / 72)
    tail = ("it fits the box, but a heading on two lines stops reading as a heading"
            if fits else "it will overflow the box or be autofit-shrunk")
    warn(f"slide {idx}: headline runs to {lines} lines at {size_pt:g}pt in "
         f"{width_in:.2f}in ({len(text.strip())} chars) — {tail}. Shorten it to one "
         f"clean sentence: {text.strip()[:60]!r}")


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
    # A chart beside bullets is the one legitimate pairing: the text states the "so
    # what" that a chart alone can't, and the chart is the evidence for it. The chart
    # takes the right half, the text the left. Cards replace the whole body — they
    # don't share the slide with bullets/table/chart/image. Every other combination
    # is two ideas on one slide.
    keys = ("bullets", "paragraphs", "table", "chart", "cards")
    n = sum(1 for k in keys if spec.get(k))
    text_plus_chart = (n == 2 and spec.get("chart") and not spec.get("table")
                       and not spec.get("image") and not spec.get("cards"))
    if n > 1 and not text_plus_chart:
        die(f"slide {idx}: use only one of {' / '.join(keys)} — a chart may share a "
            "slide with bullets, but nothing else may")
    img = spec.get("image")
    if img and not os.path.isfile(img):
        die(f"slide {idx}: image not found: {img}")
    if spec.get("cards"):
        if img:
            die(f"slide {idx}: cards and an image compete for the same body area — "
                "use one")
        card_variant = _cards_variant_of(spec)
        cards.check_cards(idx, spec["cards"], warn, die, variant=card_variant)
    if spec.get("chart"):
        if img:
            die(f"slide {idx}: a chart and an image compete for the same body area — "
                "use one")
        try:
            charts.check_chart(idx, spec["chart"], warn)
        except ValueError as e:
            die(str(e) if str(e).startswith("slide") else f"slide {idx}: {e}")


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

    # Equal columns are wrong whenever the content isn't: a 5-column table holding one
    # long identifier and three short numbers wraps the identifier mid-token while the
    # number columns sit half empty. Weights are relative, so they don't have to add up.
    weights = table_spec.get("col_widths")
    if weights:
        if len(weights) != ncols:
            die(f"col_widths has {len(weights)} entries, expected {ncols}")
        if any(not isinstance(v, (int, float)) or v <= 0 for v in weights):
            die("col_widths entries must all be positive numbers")
        total = float(sum(weights))
        used, emu_w = 0, Inches(w)
        for c, weight in enumerate(weights):
            # Last column absorbs the rounding, so the columns still sum to the box width.
            cw = (emu_w - used) if c == ncols - 1 else int(emu_w * weight / total)
            table.columns[c].width = cw
            used += cw

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


def add_chart_to_slide(slide, chart_spec, on_dark, idx,
                       box=(0.92, 1.70, 11.50, 4.75)):
    """Place a native chart in the body area.

    Charts get the same box tables do, minus a little height for the legend that sits
    under the plot. Fonts are passed through so a chart's Chinese category names use
    微軟正黑體 like the rest of the deck — python-pptx would otherwise write only
    a:latin on the chart's text properties.
    """
    x, y, w, h = box
    if chart_spec.get("box"):
        x, y, w, h = chart_spec["box"]
    try:
        return charts.add_chart(slide, chart_spec, x, y, w, h, on_dark=on_dark,
                                latin=LATIN_FONT, cjk=CJK_FONT, warn=warn, idx=idx)
    except ValueError as e:
        die(str(e) if str(e).startswith("slide") else f"slide {idx}: {e}")


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

def _center_cover_text(ph):
    """Cover title/subtitle: centered in the box, horizontally and vertically."""
    tf = ph.text_frame
    body = tf._txBody.find(qn("a:bodyPr"))
    if body is not None:
        body.set("anchor", "ctr")
    for para in tf.paragraphs:
        para.alignment = PP_ALIGN.CENTER


def _add_centered_title(slide, title, color, size=32):
    """Section-divider title: centered on the 13.33×7.5 canvas, text centered."""
    box_h = 1.20
    top = (7.50 - box_h) / 2
    tb = slide.shapes.add_textbox(Inches(0.92), Inches(top), Inches(11.50), Inches(box_h))
    tf = tb.text_frame
    tf.word_wrap = False
    body = tf._txBody.find(qn("a:bodyPr"))
    if body is not None:
        body.set("anchor", "ctr")
    para = tf.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    style_run(para.add_run(), title, size=size, color=color, bold=True)
    return tb


_SVG_BLIP = "{http://schemas.microsoft.com/office/drawing/2016/SVG/main}svgBlip"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_COVER_LAYOUTS = ("title", "cover")
COVER_TITLE_PT = 48


def _grab_cover_pictures(prs):
    """Slide-only pictures on Title / Cover (the brand logo lives here, not on the layout).

    CSITW's logo is an SVG on the example Title slide. strip_slides drops that slide,
    so a new cover inherits the layout art but not the logo. Save the picture element
    and its image part, then reattach them on each new Title/Cover slide.
    """
    import copy
    result = {}
    for slide in prs.slides:
        ln = (slide.slide_layout.name or "").strip().lower()
        if ln not in _COVER_LAYOUTS:
            continue
        pics = []
        for el in list(slide._element.spTree):
            if el.tag != qn("p:pic"):
                continue
            svg = el.find(".//" + _SVG_BLIP)
            blip = el.find(".//" + qn("a:blip"))
            node = svg if svg is not None and svg.get(_R_EMBED) else blip
            if node is None or not node.get(_R_EMBED):
                continue
            pics.append((copy.deepcopy(el), slide.part.related_part(node.get(_R_EMBED)),
                         svg is not None and svg.get(_R_EMBED)))
        if pics:
            result[ln] = pics
    return result


def _inject_cover_pictures(slide, saved, layout_name):
    key = (layout_name or "").strip().lower()
    for i, (el, img_part, is_svg) in enumerate(saved.get(key, [])):
        new_rid = slide.part.relate_to(img_part, _REL_IMAGE)
        node = el.find(".//" + _SVG_BLIP) if is_svg else el.find(".//" + qn("a:blip"))
        if node is not None:
            node.set(_R_EMBED, new_rid)
        c_nv = el.find(".//" + qn("p:cNvPr"))
        if c_nv is not None:
            c_nv.set("id", str(80 + i))
        slide._element.spTree.append(el)


def _grab_closing_shapes(prs):
    """Before stripping: save all text sp elements from each closing slide.

    Closing layouts (e.g. "Thank you") typically define NO placeholders in the
    layout XML, so the "THANK YOU" heading is a slide-only sp element. Saving
    all text sp elements and appending them to the new slide's spTree restores it.

    Returns {layout_name_lower: [lxml_element, ...]}
    """
    import copy
    result = {}
    for slide in prs.slides:
        if not is_closing_layout(slide.slide_layout.name):
            continue
        ln = (slide.slide_layout.name or "").strip().lower()
        # Count layout-defined placeholders — if zero, it's safe to re-inject ph elements.
        layout_phs = {
            int(ph.get("idx", "0"))
            for ph in slide.slide_layout._element.spTree.findall(
                ".//" + qn("p:ph"))
        }
        shapes = []
        for el in slide._element.spTree:
            if el.tag != qn("p:sp"):
                continue
            if not el.findall(".//" + qn("a:t")):
                continue
            ph_el = el.find(".//" + qn("p:ph"))
            if ph_el is not None:
                idx = int(ph_el.get("idx", "0"))
                if idx in layout_phs:
                    continue  # layout already provides this placeholder
            shapes.append(copy.deepcopy(el))
        if shapes:
            result[ln] = shapes
    return result


def _inject_closing_shapes(slide, saved, layout_name):
    key = (layout_name or "").strip().lower()
    for el in saved.get(key, []):
        slide._element.spTree.append(el)


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

    # Spec always names the cover `Cover`. CSITW's template file still labels that
    # layout "Title" (CSI uses "Title" for section dividers) — map Cover → Title
    # only when the template has no layout named Cover.
    names_lower = {lay.name.strip().lower(): lay for lay in layouts}
    if want == "cover" and "cover" not in names_lower and "title" in names_lower:
        warn(f"slide {idx}: this template names its cover layout 'Title' — using that "
             f"for spec layout 'Cover'. Prefer writing Cover in outlines so it is not "
             f"confused with CSI's Title section divider.")
        return names_lower["title"]

    if want in names_lower:
        return names_lower[want]
    names = "\n  ".join(f"[{i}] {l.name}" for i, l in enumerate(layouts))
    die(f"slide {idx}: no layout named {ref!r}. Available:\n  {names}")


_ALIGN = {
    "ctr": PP_ALIGN.CENTER,
    "l": PP_ALIGN.LEFT,
    "r": PP_ALIGN.RIGHT,
    "just": PP_ALIGN.JUSTIFY,
    "dist": PP_ALIGN.JUSTIFY,
}


def set_ph_text(ph, text, cjk=None, align=None, anchor=None):
    """Fill a placeholder, keeping the layout/master's inherited styling.

    Deliberately does not touch size or colour — that's the whole point of using the
    template's placeholders. But both typefaces are set explicitly: the company master's
    titleStyle specifies Open Sans for a:ea, which is a latin-only face, so Chinese in a
    title would fall through to a renderer default.

    `align` / `anchor` are written onto the paragraph and bodyPr. python-pptx's
    text_frame.clear() drops the layout's algn, so a centred cover title would
    otherwise come out left-aligned.
    """
    tf = ph.text_frame
    tf.clear()
    para = tf.paragraphs[0]
    if align in _ALIGN:
        para.alignment = _ALIGN[align]
    if anchor:
        body = tf._txBody.find(qn("a:bodyPr"))
        if body is not None:
            body.set("anchor", anchor)
    run = para.add_run()
    run.text = text
    run.font.name = LATIN_FONT
    _set_cjk(run, cjk)
    return run


def _layout_align(layout, ph):
    """(algn, anchor) from the matching layout placeholder, if it states them."""
    idx = ph.placeholder_format.idx
    for src in layout.placeholders:
        if src.placeholder_format.idx != idx:
            continue
        xml = src._element.xml
        algn = re.search(r'\balgn="([^"]+)"', xml)
        anchor = re.search(r'\banchor="([^"]+)"', xml)
        return (algn.group(1) if algn else None,
                anchor.group(1) if anchor else None)
    return None, None


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
    """The first placeholder whose type is one of `types`, in the order given.

    Matched on the enum name alone, not as a substring: python-pptx renders the type as
    'SUBTITLE (4)', so asking for "TITLE" by substring also matches a subtitle — and on a
    layout whose subtitle happens to come first in the placeholder list, the headline
    would land in the subtitle box.

    Ordered by `types`, not by placeholder order, so ph_by_type(s, "CENTER_TITLE",
    "TITLE") prefers a centre title when the layout has both.
    """
    found = {}
    for ph in slide.placeholders:
        try:
            name = str(ph.placeholder_format.type).split(" (")[0]
        except Exception:
            continue
        found.setdefault(name, ph)
    for want in types:
        if want in found:
            return found[want]
    return None


# ---------------------------------------------------------------- agenda

AGENDA_NAMES = ("agenda", "contents", "table of contents", "目錄")

# Layouts that mark the start of a section, so they're what an agenda lists.
_SECTION_EXACT = frozenset((
    "title",                 # CSI section divider
    "headings_custom photo",
    "headings_img",
    "headings_simple",       # CSITW default section divider
    "project plan",          # CSITW alternate section divider
    "section",               # recommended style
))


def _is_section_layout(name):
    low = (name or "").strip().lower()
    if low in _SECTION_EXACT:
        return True
    # Any layout whose name starts with "heading(s)_" follows the section-divider
    # convention used by many custom templates (e.g. "Headings_simple").
    return bool(re.match(r"headings?[_\s]", low))


def is_agenda_layout(name):
    return (name or "").strip().lower() in AGENDA_NAMES


def agenda_entries(spec_slides, agenda_idx):
    """Every section heading in the deck, with the page it starts on.

    An agenda that lists only some of the sections is worse than none — the audience
    uses it to place what they're hearing, so a missing entry reads as a missing
    section. Derived from the deck itself rather than hand-written, so it can't drift
    out of sync with the slides.

    Section dividers are preferred. A deck with no dividers falls back to the headline
    of every content slide, which is what a short deck's agenda should say anyway.
    """
    own = spec_slides[agenda_idx - 1]
    if own.get("entries"):
        return [(e.get("title", ""), e.get("page")) for e in own["entries"]]

    def collect(pred):
        out = []
        for n, s in enumerate(spec_slides, 1):
            if n == agenda_idx or not s.get("title"):
                continue
            if pred(s):
                out.append((s["title"], n))
        return out

    entries = collect(lambda s: _is_section_layout(str(s.get("layout", ""))))
    if not entries:
        entries = collect(
            lambda s: not is_closing_layout(str(s.get("layout", "")))
            and str(s.get("layout", "")).strip().lower() != "cover")
    return entries


def fill_agenda(slide, layout, spec_slides, agenda_idx, cjk=None):
    """Fill both of the Agenda layout's columns: headings on the left, pages on the right.

    The layout ships two BODY placeholders — idx 12 for the labels and idx 13 for the
    numbers, in a narrow 0.89in column at the right edge. Filling only the first leaves
    the numbers column empty, and drop_empty_placeholders would then delete it, so the
    agenda would silently lose its page numbers.
    """
    entries = agenda_entries(spec_slides, agenda_idx)
    if not entries:
        warn(f"slide {agenda_idx}: agenda has nothing to list — no section dividers and "
             "no other titled slides")
        return

    bodies = sorted(
        (ph for ph in slide.placeholders
         if "BODY" in str(ph.placeholder_format.type)),
        key=lambda ph: ph.left or 0)

    labels = [t for t, _ in entries]
    pages = [("" if p is None else f"{p:02d}") for _, p in entries]

    if len(entries) > 8:
        warn(f"slide {agenda_idx}: agenda lists {len(entries)} items — the box holds "
             "about 8; group the sections or split the agenda over two slides")

    if len(bodies) >= 2:
        fill_text_frame(bodies[0].text_frame, labels, size=18, color=TEXT,
                        space_after=14)
        grow_to_fit(bodies[0], labels, 18)
        # Right-align the numbers so they sit against the slide edge like the template's.
        fill_text_frame(bodies[-1].text_frame, pages, size=18, color=PRIMARY,
                        space_after=14)
        for para in bodies[-1].text_frame.paragraphs:
            para.alignment = PP_ALIGN.RIGHT
    else:
        # A user-supplied agenda layout with one text column: fold the page number in.
        lines = [f"{t}    {p}" if p else t for t, p in zip(labels, pages)]
        target = bodies[0] if bodies else None
        if target is not None:
            fill_text_frame(target.text_frame, lines, size=18, color=TEXT,
                            space_after=14)
            grow_to_fit(target, lines, 18)
        else:
            x, y, w, h = BODY_BOX
            tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
            fill_text_frame(tb.text_frame, lines, size=18, color=TEXT, space_after=14)


# ------------------------------------------------- the closing slide isn't ours to edit

CLOSING_NAMES = ("thank you", "thankyou", "thanks", "closing")


def is_closing_layout(name):
    """True for the template's own sign-off layout.

    Matched on the layout name, so a user-supplied template with a "Thanks" or
    "Closing" layout gets the same protection.
    """
    return (name or "").strip().lower() in CLOSING_NAMES


def layout_ph_text(layout, idx_):
    """The text the layout author put in one of its placeholders.

    PowerPoint treats layout placeholder text as a prompt, so it does NOT carry onto a
    new slide — python-pptx hands back an empty frame. To reproduce the closing slide
    as drawn, its wording has to be copied across deliberately.
    """
    for ph in layout.placeholders:
        if ph.placeholder_format.idx == idx_ and ph.has_text_frame:
            return ph.text_frame.text.strip()
    return ""


def keep_closing_as_is(slide, layout, spec_slide, idx):
    """Reproduce the closing slide exactly as the template author drew it.

    The company template's `Thank you` layout is not an empty frame: it carries the
    company address, phone number and website in a non-placeholder textbox, and its
    title placeholder reads "Thank you". Those details are the template author's, not
    the deck's, so by default nothing here is generated from the spec — the layout's
    own title wording is copied over and everything else is left untouched.

    Returns True when the slide was left as drawn. `keep_closing: false` opts back in
    to normal rendering — that's the "unless told otherwise" half of the rule.
    """
    if not is_closing_layout(layout.name):
        return False
    if spec_slide.get("keep_closing") is False:
        return False

    overrides = [k for k in ("title", "subtitle", "bullets", "paragraphs",
                             "table", "image") if spec_slide.get(k)]
    if overrides:
        warn(f"slide {idx}: '{layout.name}' is kept exactly as the template draws it, "
             f"so {', '.join(overrides)} {'was' if len(overrides) == 1 else 'were'} "
             "ignored. It already carries its own sign-off wording and the company "
             'contact details. To edit it anyway, set "keep_closing": false on this '
             "slide.")

    # The layout's wording has to be written onto the slide explicitly, or the deck
    # ends up with the background art and contact line but no "Thank you".
    ph = ph_by_type(slide, "CENTER_TITLE", "TITLE")
    if ph is not None:
        text = layout_ph_text(layout, ph.placeholder_format.idx)
        if text:
            set_ph_text(ph, text)
    return True


def build_from_template(spec, out):
    tpl = spec.get("template")
    if not tpl:
        die("style 'csi'/'csitw'/'company'/'custom' requires spec['template'] "
            "(resolve_template should have filled it for csi/csitw)")
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
    # Save closing-slide text shapes before stripping — "Thank you" text lives on the
    # template's example slide, not in the layout, so strip_slides would lose it.
    _closing_shapes = _grab_closing_shapes(prs)
    _cover_pics = _grab_cover_pictures(prs)
    strip_slides(prs)

    for i, s in enumerate(spec["slides"], 1):
        check_content(i, s)
        layout = resolve_layout(prs, s.get("layout"), i, redirect)
        slide = prs.slides.add_slide(layout)

        # The closing slide is the template author's, not the deck's — reproduce it as
        # drawn and move on, unless the spec explicitly asks to edit it.
        if keep_closing_as_is(slide, layout, s, i):
            _inject_closing_shapes(slide, _closing_shapes, layout.name)
            add_notes(slide, s.get("notes"))
            continue

        # On a dark layout the placeholders already inherit light text from the layout,
        # but anything we add ourselves would default to #13182c and vanish.
        on_dark = layout.name.strip().lower() in dark_layouts
        body_color = WHITE if on_dark else TEXT
        sub_color = rgb("e7e6e6") if on_dark else TEXT_2

        on_cover = (i == 1 and layout.name.strip().lower() in ("cover", "title"))
        if on_cover and _cover_pics:
            _inject_cover_pictures(slide, _cover_pics, layout.name)

        title = s.get("title")
        if title:
            ph = ph_by_type(slide, "CENTER_TITLE", "TITLE")
            if ph is not None:
                check_headline(i, title, ph)
                run = set_ph_text(ph, title)   # inherit the master's title styling
                if on_cover:
                    run.font.size = Pt(COVER_TITLE_PT)
                    _center_cover_text(ph)
            else:
                # Headings_* are section dividers with no TITLE placeholder.
                # The title sits in the middle of the canvas, text centered.
                on_section = layout.name.strip().lower().startswith("headings")
                size_pt = 32.0 if on_section else 28.0
                check_headline(i, title, width_in=11.50, size_pt=size_pt)
                if on_section:
                    _add_centered_title(slide, title, body_color, size=size_pt)
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
                if on_cover:
                    _center_cover_text(ph)
            else:
                warn(f"slide {i}: layout '{layout.name}' has no subtitle placeholder "
                     "— subtitle rendered as a textbox")
                tb = slide.shapes.add_textbox(Inches(0.92), Inches(1.55),
                                              Inches(11.50), Inches(0.6))
                style_run(tb.text_frame.paragraphs[0].add_run(), sub,
                          size=18, color=sub_color)

        # The agenda is derived from the rest of the deck, not authored — it has to list
        # every section with its page number, and stay in sync when slides move.
        if is_agenda_layout(layout.name) and not s.get("table"):
            if s.get("bullets") or s.get("paragraphs"):
                warn(f"slide {i}: the agenda is built from the deck's own section "
                     "headings and their page numbers, so its bullets were ignored. "
                     'Use "entries": [{"title": …, "page": …}] to set it by hand.')
            fill_agenda(slide, layout, spec["slides"], i)
            drop_empty_placeholders(slide)
            add_notes(slide, s.get("notes"))
            continue

        lines = s.get("bullets") or s.get("paragraphs")
        img = s.get("image")

        if s.get("cards"):
            # Cards own the body area on title-only (and content) layouts.
            cards.add_cards(slide, s["cards"], BODY_BOX, style_run,
                            variant=_cards_variant_of(s),
                            latin=LATIN_FONT, cjk=CJK_FONT)
            drop_empty_placeholders(slide)
            add_notes(slide, s.get("notes"))
            continue

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
                if s.get("chart"):
                    # The layout's BODY spans the full width, which is where the chart
                    # goes. Writing one dimension on a placeholder that inherits its
                    # geometry materialises an <a:xfrm> and zeroes the rest, so all
                    # four are restated.
                    body.left, body.top = Inches(0.92), body.top
                    body.width, body.height = Inches(5.80), body.height
            else:
                # ~20 of the 25 company layouts are title-only; add our own box.
                x, y, w, h = BODY_BOX
                if img or s.get("chart"):
                    w = 6.10
                if s.get("bullets") and not img and not s.get("chart"):
                    add_visual_bullets(slide, lines, x, y, w, h, style_run,
                                       color=body_color, sub_color=sub_color,
                                       latin=LATIN_FONT, cjk=CJK_FONT)
                else:
                    tb = slide.shapes.add_textbox(Inches(x), Inches(y),
                                                  Inches(w), Inches(h))
                    fill_text_frame(tb.text_frame, lines, size=20, color=body_color,
                                    bullet_char=bullet, space_after=14)

        if s.get("table"):
            add_table(slide, s["table"], 0.92, BODY_TOP, 11.50,
                      min(0.45 * (len(s["table"].get("rows", [])) + 1), 4.35))

        if s.get("chart"):
            # With bullets beside it the chart takes the right half, matching how an
            # image shares the slide — the text carries the "so what", the chart the
            # evidence.
            box = ((7.10, BODY_TOP, 5.30, 4.20) if lines else (0.92, BODY_TOP, 11.50, 4.20))
            if on_dark:
                warn(f"slide {i}: a chart on the dark layout '{layout.name}' — the "
                     "palette is validated against white, and on the navy background "
                     "every series falls under 3:1, so the colours stop being "
                     "distinguishable marks. Move the chart to 'Content Heading' and "
                     "leave the dark layout for text.")
            add_chart_to_slide(slide, s["chart"], on_dark, i, box=box)

        if img:
            pic_ph = ph_by_type(slide, "PICTURE")
            if pic_ph is not None:
                pic_ph.insert_picture(img)
            elif lines:
                place_image(slide, img, 7.20, BODY_TOP, 5.20, 4.20)
            else:
                place_image(slide, img, 0.92, BODY_TOP, 11.50, 4.20)

        drop_empty_placeholders(slide)
        add_notes(slide, s.get("notes"))

    finish(prs, spec, out)


# ================================================================ recommended

def r_headline(slide, text, rule=True, idx=None, text_color=None, bar_color=None):
    text_color = text_color or TEXT
    bar_color = bar_color or PRIMARY
    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_MARGIN_T),
                                  Inches(R_WIDTH), Inches(0.90))
    tf = tb.text_frame
    tf.word_wrap = True
    tb.name = "db:headline"
    if idx is not None:
        check_headline(idx, text, width_in=R_WIDTH, size_pt=28.0)
    style_run(tf.paragraphs[0].add_run(), text, size=28, color=text_color, bold=True)
    if rule:
        from pptx.enum.shapes import MSO_SHAPE
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(R_MARGIN_L),
                                     Inches(1.52), Inches(2.2), Pt(3))
        bar.fill.solid()
        bar.fill.fore_color.rgb = bar_color
        bar.line.fill.background()
        bar.shadow.inherit = False


def r_slide_number(slide, n, color=None):
    tb = slide.shapes.add_textbox(Inches(12.10), Inches(6.90),
                                  Inches(0.60), Inches(0.30))
    tb.name = "db:label"
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    style_run(p.add_run(), str(n), size=11, color=color or TEXT_2)


def build_recommended(spec, out):
    prs = Presentation()
    prs.slide_width = Emu(12192000)
    prs.slide_height = Emu(6858000)
    blank = prs.slide_layouts[6]

    for i, s in enumerate(spec["slides"], 1):
        check_content(i, s)
        base, variant = _split_kind(str(s.get("layout", "content")))
        kind = base  # kept for clarity in the branches below
        slide = prs.slides.add_slide(blank)
        lines = s.get("bullets") or s.get("paragraphs")
        bullet = "•" if s.get("bullets") else None

        # Dark-slide background (recommended style only; company template uses
        # its own dark layouts instead).  The background rect is pushed to index 2 in
        # spTree so it sits behind every shape the branches below draw.
        on_dark = s.get("dark", False)
        if on_dark:
            from pptx.enum.shapes import MSO_SHAPE as _MSO
            _bg = slide.shapes.add_shape(
                _MSO.RECTANGLE, Emu(0), Emu(0), prs.slide_width, prs.slide_height)
            _bg.name = "db:bg"
            _bg.fill.solid()
            _bg.fill.fore_color.rgb = R_DARK_BG
            _bg.line.fill.background()
            _bg.shadow.inherit = False
            _e = _bg._element
            _e.getparent().remove(_e)
            slide._element.spTree.insert(2, _e)
        # Color tokens — override to white on dark slides
        _txt  = R_DARK_TEXT  if on_dark else TEXT
        _txt2 = R_DARK_TEXT2 if on_dark else TEXT_2
        _bar  = R_DARK_BAR   if on_dark else PRIMARY

        if kind in ("cover", "title"):
            # `cover` is the canonical name; `title` remains a legacy alias for the
            # recommended-style cover (CSI/CSITW use Title for section dividers).
            tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(2.55),
                                          Inches(R_WIDTH), Inches(1.20))
            tb.name = "db:headline"
            p = tb.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            style_run(p.add_run(), s.get("title", ""), size=40, color=_txt, bold=True)
            if s.get("subtitle"):
                from pptx.enum.shapes import MSO_SHAPE
                bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(6.07),
                                             Inches(3.95), Inches(1.2), Pt(3))
                bar.fill.solid()
                bar.fill.fore_color.rgb = _bar
                bar.line.fill.background()
                bar.shadow.inherit = False
                tb2 = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(4.25),
                                               Inches(R_WIDTH), Inches(0.6))
                tb2.name = "db:label"
                p2 = tb2.text_frame.paragraphs[0]
                p2.alignment = PP_ALIGN.CENTER
                style_run(p2.add_run(), s["subtitle"], size=18, color=_txt2)

        elif kind == "section":
            tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(3.05),
                                          Inches(R_WIDTH), Inches(1.0))
            tb.name = "db:headline"
            # Section label keeps brand blue even on dark (high-contrast accent).
            style_run(tb.text_frame.paragraphs[0].add_run(), s.get("title", ""),
                      size=32, color=PRIMARY, bold=True)

        elif kind == "statement":
            # Narrative pivot / high-impact conclusion. Intentionally open composition.
            eyebrow = (s.get("eyebrow") or "").strip()
            title_text = (s.get("title") or "").strip()
            # Prefer subtitle; fall back to first paragraph so Markdown outlines work either way.
            support = (s.get("subtitle") or "").strip()
            if not support:
                _paras = s.get("paragraphs") or []
                if _paras:
                    support = str(_paras[0]).strip()
            if eyebrow:
                tb_e = slide.shapes.add_textbox(Inches(1.15), Inches(1.55), Inches(4.0), Inches(0.35))
                tb_e.name = "db:label"
                style_run(tb_e.text_frame.paragraphs[0].add_run(), eyebrow.upper(),
                          size=12, color=_bar if not on_dark else _txt2, bold=True)
            tb_s = slide.shapes.add_textbox(Inches(1.15), Inches(2.05), Inches(9.70), Inches(2.25))
            tb_s.name = "db:headline"
            tb_s.text_frame.word_wrap = True
            style_run(tb_s.text_frame.paragraphs[0].add_run(), title_text,
                      size=42, color=_txt, bold=True)
            if support:
                tb_sub = slide.shapes.add_textbox(Inches(7.25), Inches(4.70), Inches(4.70), Inches(1.0))
                tb_sub.name = "db:body"
                tb_sub.text_frame.word_wrap = True
                style_run(tb_sub.text_frame.paragraphs[0].add_run(), support,
                          size=16, color=_txt2)
            r_slide_number(slide, i, color=_txt2)

        elif kind == "quote":
            tb = slide.shapes.add_textbox(Inches(1.60), Inches(2.60),
                                          Inches(10.13), Inches(1.80))
            tf = tb.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            style_run(p.add_run(), s.get("title", ""), size=32, color=_txt, bold=True)
            if s.get("subtitle"):
                p2 = tf.add_paragraph()
                p2.alignment = PP_ALIGN.CENTER
                p2.space_before = Pt(18)
                style_run(p2.add_run(), s["subtitle"], size=16, color=_txt2)
            r_slide_number(slide, i, color=_txt2)

        elif kind == "closing":
            r_headline(slide, s.get("title", ""), idx=i, text_color=_txt, bar_color=_bar)
            if lines:
                tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                              Inches(R_WIDTH), Inches(R_BODY_H))
                fill_text_frame(tb.text_frame, lines, size=18, color=_txt,
                                bullet_char=bullet, sub_color=_txt2)
            r_slide_number(slide, i, color=_txt2)

        elif kind == "big_number":
            # Large metric centered on slide — no headline bar; the number is the message.
            from pptx.enum.shapes import MSO_SHAPE as _MSO2
            num_text   = (s.get("title") or "").strip()
            label_text = (s.get("subtitle") or "").strip()
            paras      = lines or []
            NUM_H, LABEL_H, PARA_H, GAP = 1.40, 0.50, 0.55, 0.20
            total_h = (NUM_H
                       + (GAP + LABEL_H if label_text else 0)
                       + (GAP + PARA_H  if paras      else 0))
            slide_h_in = prs.slide_height / EMU_PER_IN
            top = (slide_h_in - total_h) / 2

            tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(top),
                                          Inches(R_WIDTH), Inches(NUM_H))
            tb.name = "db:big-number"
            _p = tb.text_frame.paragraphs[0]
            _p.alignment = PP_ALIGN.CENTER
            # On dark slides _bar (#6ba5e0) on #0d63ba is only 2.3:1; use white instead.
            _num_color = _txt if on_dark else _bar
            style_run(_p.add_run(), num_text, size=72, color=_num_color, bold=True,
                      font=LATIN_FONT, cjk=CJK_FONT)

            if label_text:
                top += NUM_H + GAP
                tb2 = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(top),
                                               Inches(R_WIDTH), Inches(LABEL_H))
                tb2.name = "db:label"
                _p2 = tb2.text_frame.paragraphs[0]
                _p2.alignment = PP_ALIGN.CENTER
                style_run(_p2.add_run(), label_text, size=22, color=_txt2,
                          font=LATIN_FONT, cjk=CJK_FONT)

            if paras:
                top += LABEL_H + GAP
                tb3 = slide.shapes.add_textbox(Inches(2.50), Inches(top),
                                               Inches(8.33), Inches(PARA_H))
                tb3.name = "db:body"
                tf3 = tb3.text_frame
                tf3.word_wrap = True
                _p3 = tf3.paragraphs[0]
                _p3.alignment = PP_ALIGN.CENTER
                style_run(_p3.add_run(), " · ".join(p.strip() for p in paras),
                          size=16, color=_txt2, font=LATIN_FONT, cjk=CJK_FONT)

            r_slide_number(slide, i, color=_txt2)

        elif kind == "image" and variant == "split":
            # Full-bleed split: image fills left half edge-to-edge, title+text on right.
            # No header bar — title lives inside the right column.
            if not s.get("image"):
                die(f"slide {i}: layout 'image:split' needs an image")
            from pptx.enum.shapes import MSO_SHAPE
            SPLIT_IMG_W = 6.30
            SPLIT_TX_X  = SPLIT_IMG_W + 0.35
            SPLIT_TX_W  = 13.333 - SPLIT_TX_X - 0.50
            place_image(slide, s["image"], 0, 0, SPLIT_IMG_W, 7.5)
            title_text = s.get("title", "")
            if title_text:
                check_headline(i, title_text, width_in=SPLIT_TX_W, size_pt=28.0)
                tb_t = slide.shapes.add_textbox(
                    Inches(SPLIT_TX_X), Inches(1.50), Inches(SPLIT_TX_W), Inches(0.90))
                tb_t.name = "db:headline"
                tb_t.text_frame.word_wrap = True
                style_run(tb_t.text_frame.paragraphs[0].add_run(), title_text,
                          size=28, color=_txt, bold=True)
                bar_s = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE, Inches(SPLIT_TX_X), Inches(2.55),
                    Inches(2.2), Pt(3))
                bar_s.fill.solid()
                bar_s.fill.fore_color.rgb = _bar
                bar_s.line.fill.background()
                bar_s.shadow.inherit = False
            if lines:
                tb = slide.shapes.add_textbox(
                    Inches(SPLIT_TX_X), Inches(2.75), Inches(SPLIT_TX_W), Inches(3.80))
                fill_text_frame(tb.text_frame, lines, size=18, color=_txt,
                                bullet_char=bullet, sub_color=_txt2)
            r_slide_number(slide, i, color=_txt2)

        else:
            r_headline(slide, s.get("title", ""), idx=i, text_color=_txt, bar_color=_bar)

            if kind == "two-column":
                cols = s.get("columns") or []
                if len(cols) != 2:
                    die(f"slide {i}: layout 'two-column' needs columns: [[..],[..]]")
                for cx, col in ((R_MARGIN_L, cols[0]), (R_COL2_X, cols[1])):
                    tb = slide.shapes.add_textbox(Inches(cx), Inches(R_BODY_Y),
                                                  Inches(R_COL_W), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, col, size=18, color=_txt,
                                    bullet_char="•", sub_color=_txt2)

            elif kind == "table":
                if not s.get("table"):
                    die(f"slide {i}: layout 'table' needs a table object")
                nrows = len(s["table"].get("rows", [])) + 1
                add_table(slide, s["table"], R_MARGIN_L, R_BODY_Y, R_WIDTH,
                          min(0.42 * nrows, R_BODY_H))

            elif kind == "chart" and variant != "right":
                if not s.get("chart"):
                    die(f"slide {i}: layout 'chart' needs a chart object")
                add_chart_to_slide(slide, s["chart"], False, i,
                                   box=(R_MARGIN_L, R_BODY_Y, R_WIDTH, R_BODY_H - 0.15))

            elif kind == "chart" and variant == "right":
                if not s.get("chart"):
                    die(f"slide {i}: layout 'chart:right' needs a chart object")
                if lines:
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                                  Inches(R_COL_W), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, lines, size=18, color=_txt,
                                    bullet_char=bullet, sub_color=_txt2)
                add_chart_to_slide(slide, s["chart"], False, i,
                                   box=(R_COL2_X, R_BODY_Y, R_COL_W, R_BODY_H - 0.15))

            elif kind == "image" and variant == "full":
                if not s.get("image"):
                    die(f"slide {i}: layout 'image:full' needs an image")
                place_image(slide, s["image"], R_MARGIN_L, R_BODY_Y,
                            R_WIDTH, R_BODY_H - 0.35)
                if s.get("caption"):
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(6.55),
                                                  Inches(R_WIDTH), Inches(0.3))
                    tb.name = "db:label"
                    style_run(tb.text_frame.paragraphs[0].add_run(), s["caption"],
                              size=12, color=_txt2)

            elif kind == "image" and variant in ("right", None) and s.get("image"):
                # Product/editorial default: image leads at ~65%, text supports at ~35%.
                text_w, gap = 3.75, 0.35
                img_x = R_MARGIN_L + text_w + gap
                img_w = R_WIDTH - text_w - gap
                if lines:
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                                  Inches(text_w), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, lines, size=18, color=_txt,
                                    bullet_char=bullet, sub_color=_txt2)
                place_image(slide, s["image"], img_x, R_BODY_Y, img_w, R_BODY_H)

            elif kind == "image" and variant == "left":
                if not s.get("image"):
                    die(f"slide {i}: layout 'image:left' needs an image")
                img_w, gap = 7.43, 0.35
                text_x = R_MARGIN_L + img_w + gap
                text_w = R_WIDTH - img_w - gap
                place_image(slide, s["image"], R_MARGIN_L, R_BODY_Y, img_w, R_BODY_H)
                if lines:
                    tb = slide.shapes.add_textbox(Inches(text_x), Inches(R_BODY_Y),
                                                  Inches(text_w), Inches(R_BODY_H))
                    fill_text_frame(tb.text_frame, lines, size=18, color=_txt,
                                    bullet_char=bullet, sub_color=_txt2)

            elif kind == "image" and variant == "top":
                if not s.get("image"):
                    die(f"slide {i}: layout 'image:top' needs an image")
                IMG_H = R_BODY_H * 0.52
                place_image(slide, s["image"], R_MARGIN_L, R_BODY_Y, R_WIDTH, IMG_H)
                if lines:
                    text_y = R_BODY_Y + IMG_H + 0.12
                    text_h = max(6.65 - text_y, 0.5)
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(text_y),
                                                  Inches(R_WIDTH), Inches(text_h))
                    fill_text_frame(tb.text_frame, lines, size=16, color=_txt,
                                    bullet_char=bullet, sub_color=_txt2)

            elif kind == "content" and variant == "editorial":
                # 65/35 editorial hierarchy: lead idea left, supporting detail right.
                lead = (s.get("subtitle") or (lines[0] if lines else "")).strip()
                rest = lines if s.get("subtitle") else (lines[1:] if lines else [])
                tb_lead = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y + 0.30),
                                                    Inches(7.10), Inches(2.35))
                tb_lead.name = "db:editorial-lead"
                tb_lead.text_frame.word_wrap = True
                style_run(tb_lead.text_frame.paragraphs[0].add_run(), lead,
                          size=30, color=_txt, bold=True)
                if rest:
                    tb = slide.shapes.add_textbox(Inches(8.45), Inches(R_BODY_Y + 0.35),
                                                  Inches(3.95), Inches(3.90))
                    fill_text_frame(tb.text_frame, rest, size=16, color=_txt2,
                                    bullet_char=bullet, sub_color=_txt2)

            elif kind == "content" and variant == "spotlight":
                focus = (s.get("subtitle") or (lines[0] if lines else "")).strip()
                rest = lines if s.get("subtitle") else (lines[1:] if lines else [])
                tb_focus = slide.shapes.add_textbox(Inches(2.05), Inches(R_BODY_Y + 0.45),
                                                     Inches(9.20), Inches(1.65))
                tb_focus.name = "db:spotlight"
                tb_focus.text_frame.word_wrap = True
                pp = tb_focus.text_frame.paragraphs[0]
                pp.alignment = PP_ALIGN.CENTER
                style_run(pp.add_run(), focus, size=34, color=_txt, bold=True)
                if rest:
                    tb = slide.shapes.add_textbox(Inches(7.10), Inches(4.35), Inches(4.80), Inches(1.35))
                    fill_text_frame(tb.text_frame, rest, size=15, color=_txt2,
                                    bullet_char=None, sub_color=_txt2)

            elif kind == "content" and variant == "diagram":
                items = s.get("cards") or []
                if not items:
                    die(f"slide {i}: layout 'content:diagram' needs cards: [{{title, body?}}, ...]")
                # Reuse native editable card primitives but arrange them as a hub-and-spoke diagram.
                core = items[0]
                support = items[1:5]
                cards.add_cards(slide, [core], (4.65, 3.05, 4.00, 1.35),
                                style_run, variant="featured", latin=LATIN_FONT, cjk=CJK_FONT)
                if support:
                    cards.add_cards(slide, support, (R_MARGIN_L, 4.65, R_WIDTH, 1.55),
                                    style_run, variant="3-col" if len(support) == 3 else "4-grid",
                                    latin=LATIN_FONT, cjk=CJK_FONT)

            elif kind == "content" and variant == "data-story":
                if not s.get("chart"):
                    die(f"slide {i}: layout 'content:data-story' needs a chart object")
                insight_w, gap = 3.20, 0.35
                chart_x = R_MARGIN_L + insight_w + gap
                chart_w = R_WIDTH - insight_w - gap
                if lines or s.get("subtitle"):
                    insight_lines = ([s["subtitle"]] if s.get("subtitle") else []) + (lines or [])
                    tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y + 0.15),
                                                  Inches(insight_w), Inches(R_BODY_H - 0.30))
                    fill_text_frame(tb.text_frame, insight_lines, size=17, color=_txt,
                                    bullet_char=None, sub_color=_txt2)
                add_chart_to_slide(slide, s["chart"], False, i,
                                   box=(chart_x, R_BODY_Y, chart_w, R_BODY_H - 0.15))

            elif kind == "cards" or s.get("cards"):
                if not s.get("cards"):
                    die(f"slide {i}: layout 'cards' needs a cards list")
                cards.add_cards(slide, s["cards"],
                                (R_MARGIN_L, R_BODY_Y, R_WIDTH, R_BODY_H),
                                style_run, variant=variant,
                                latin=LATIN_FONT, cjk=CJK_FONT)

            elif kind == "timeline":
                from pptx.enum.shapes import MSO_SHAPE as _MSO3
                evs = s.get("events")
                if not evs or not isinstance(evs, list) or len(evs) < 2:
                    die(f"slide {i}: layout 'timeline' needs an events list "
                        "with at least 2 items")
                if len(evs) > 6:
                    warn(f"slide {i}: {len(evs)} events — more than 6 will be cramped; "
                         "consider a table or splitting into two slides")

                n = len(evs)
                slot_w  = R_WIDTH / n
                LINE_Y  = 3.55
                DOT_D   = 0.22
                DOT_R   = DOT_D / 2
                LABEL_H = 0.40
                LABEL_Y = LINE_Y - DOT_R - 0.10 - LABEL_H
                TITLE_Y = LINE_Y + DOT_R + 0.14
                TITLE_H = 0.52
                BODY_Y  = TITLE_Y + TITLE_H + 0.08
                BODY_H  = 0.90

                # Horizontal connector line
                tl_line = slide.shapes.add_shape(
                    _MSO3.RECTANGLE,
                    Inches(R_MARGIN_L), Inches(LINE_Y - 0.01),
                    Inches(R_WIDTH), Pt(2))
                tl_line.name = "db:timeline-line"
                tl_line.fill.solid()
                tl_line.fill.fore_color.rgb = RULE
                tl_line.line.fill.background()
                tl_line.shadow.inherit = False

                for j, ev in enumerate(evs):
                    cx     = R_MARGIN_L + (j + 0.5) * slot_w
                    accent = cards.ACCENTS[j % len(cards.ACCENTS)]
                    tw     = slot_w * 0.90
                    tx     = cx - tw / 2

                    # Dot on the line
                    dot = slide.shapes.add_shape(
                        _MSO3.OVAL,
                        Inches(cx - DOT_R), Inches(LINE_Y - DOT_R),
                        Inches(DOT_D), Inches(DOT_D))
                    dot.name = f"db:timeline-dot-{j}"
                    dot.fill.solid()
                    dot.fill.fore_color.rgb = accent
                    dot.line.fill.background()
                    dot.shadow.inherit = False

                    # Date / label above the line
                    lbl = (ev.get("label") or "").strip()
                    if lbl:
                        tb_l = slide.shapes.add_textbox(
                            Inches(tx), Inches(LABEL_Y), Inches(tw), Inches(LABEL_H))
                        tb_l.name = f"db:timeline-label-{j}"
                        _pl = tb_l.text_frame.paragraphs[0]
                        _pl.alignment = PP_ALIGN.CENTER
                        style_run(_pl.add_run(), lbl, size=12, color=_txt2,
                                  font=LATIN_FONT, cjk=CJK_FONT)

                    # Event title below the line
                    ev_title = (ev.get("title") or "").strip()
                    if ev_title:
                        tb_t = slide.shapes.add_textbox(
                            Inches(tx), Inches(TITLE_Y), Inches(tw), Inches(TITLE_H))
                        tb_t.name = f"db:timeline-title-{j}"
                        tf_t = tb_t.text_frame
                        tf_t.word_wrap = True
                        _pt = tf_t.paragraphs[0]
                        _pt.alignment = PP_ALIGN.CENTER
                        style_run(_pt.add_run(), ev_title, size=14, color=_txt,
                                  bold=True, font=LATIN_FONT, cjk=CJK_FONT)

                    # Optional body text below title
                    ev_body = (ev.get("body") or "").strip()
                    if ev_body:
                        tb_b = slide.shapes.add_textbox(
                            Inches(tx), Inches(BODY_Y), Inches(tw), Inches(BODY_H))
                        tb_b.name = f"db:timeline-body-{j}"
                        tf_b = tb_b.text_frame
                        tf_b.word_wrap = True
                        _pb = tf_b.paragraphs[0]
                        _pb.alignment = PP_ALIGN.CENTER
                        style_run(_pb.add_run(), ev_body, size=12, color=_txt2,
                                  font=LATIN_FONT, cjk=CJK_FONT)

            else:  # content (default)
                if kind not in ("content", "image"):
                    warn(f"slide {i}: unknown layout {kind!r} for the recommended "
                         "style — rendered as 'content'")
                if s.get("cards"):
                    cards.add_cards(slide, s["cards"],
                                    (R_MARGIN_L, R_BODY_Y, R_WIDTH, R_BODY_H),
                                    style_run, variant=variant,
                                    latin=LATIN_FONT, cjk=CJK_FONT)
                elif lines:
                    if (s.get("bullets") and not s.get("chart")
                            and not s.get("image")):
                        add_visual_bullets(slide, lines,
                                           R_MARGIN_L, R_BODY_Y, R_WIDTH, R_BODY_H,
                                           style_run, color=_txt, sub_color=_txt2,
                                           accent=_bar,
                                           latin=LATIN_FONT, cjk=CJK_FONT)
                    elif s.get("bullets") and (s.get("chart") or s.get("image")):
                        # Narrow column beside chart/image — keep compact text
                        chart_x = R_MARGIN_L + 4.0 + 0.35
                        tb = slide.shapes.add_textbox(
                            Inches(R_MARGIN_L), Inches(R_BODY_Y),
                            Inches(4.0), Inches(R_BODY_H))
                        fill_text_frame(tb.text_frame, lines, size=16, color=_txt,
                                        bullet_char="•", sub_color=_txt2)
                    else:
                        tb = slide.shapes.add_textbox(Inches(R_MARGIN_L), Inches(R_BODY_Y),
                                                      Inches(R_WIDTH), Inches(R_BODY_H))
                        fill_text_frame(tb.text_frame, lines, size=18, color=_txt,
                                        bullet_char=None, sub_color=_txt2)
                if s.get("chart"):
                    add_chart_to_slide(slide, s["chart"], False, i,
                                       box=(R_MARGIN_L, R_BODY_Y, R_WIDTH,
                                            R_BODY_H - 0.15))
                if s.get("image"):
                    place_image(slide, s["image"], 3.50, R_BODY_Y + 0.20,
                                6.33, R_BODY_H - 0.40)

            r_slide_number(slide, i, color=_txt2)

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
# CSI (US/global) — also the legacy `style: "company"` target.
BUNDLED_CSI = os.path.join("assets", "company-template.pptx")
BUNDLED_CSITW = os.path.join("assets", "csitw-template.pptx")
# Back-compat alias used in older docs/errors.
BUNDLED_TEMPLATE = BUNDLED_CSI

# Template-backed styles. `company` is a legacy alias for `csi`.
TEMPLATE_STYLES = frozenset({"csi", "csitw", "company", "custom"})


def skill_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize_style(spec):
    """Return the canonical style name; map legacy `company` → `csi`."""
    raw = (spec.get("style") or "company").lower().strip()
    if raw == "company":
        return "csi"
    return raw


def load_config():
    """Machine-local overrides for the bundled CSI / CSITW templates.

    Env (highest → lowest within each brand):
      DECK_BUILDER_CSI_TEMPLATE / DECK_BUILDER_CSITW_TEMPLATE
      DECK_BUILDER_TEMPLATE          — legacy; treated as CSI override

    Then `<skill>/config.json` keys: `csi_template`, `csitw_template`,
    and legacy `company_template` (→ CSI).

    Neither is required — the skill ships both templates in `assets/`.
    """
    cfg = {}
    path = os.path.join(skill_dir(), CONFIG_NAME)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh) or {}
        except (OSError, ValueError) as e:
            warn(f"ignoring unreadable {CONFIG_NAME}: {e}")

    # Env overrides win over config.json.
    if os.environ.get("DECK_BUILDER_CSI_TEMPLATE"):
        cfg["csi_template"] = os.environ["DECK_BUILDER_CSI_TEMPLATE"]
    if os.environ.get("DECK_BUILDER_CSITW_TEMPLATE"):
        cfg["csitw_template"] = os.environ["DECK_BUILDER_CSITW_TEMPLATE"]
    # Legacy single override → CSI only.
    if os.environ.get("DECK_BUILDER_TEMPLATE"):
        cfg.setdefault("csi_template", os.environ["DECK_BUILDER_TEMPLATE"])
        cfg.setdefault("company_template", os.environ["DECK_BUILDER_TEMPLATE"])
    return cfg


def _configured_template(cfg, style):
    """Pick the configured path for a template-backed style, if any."""
    if style == "csi":
        return cfg.get("csi_template") or cfg.get("company_template")
    if style == "csitw":
        return cfg.get("csitw_template")
    return None


def resolve_template(spec):
    """Fill in spec['template'] when the spec doesn't name one.

    Order: spec's own `template` → env/config for that brand → bundled asset.
    `recommended` draws its own slides (no template). `custom` must set `template`.
    Explicit `template` in the spec always wins.
    """
    if spec.get("template"):
        return
    style = normalize_style(spec)
    if style == "recommended":
        return
    if style == "custom":
        return  # build_from_template will die if template is still missing
    if style not in ("csi", "csitw"):
        return

    cfg = load_config()
    tpl = _configured_template(cfg, style)
    if tpl:
        tpl = os.path.expanduser(tpl)
        if not os.path.isfile(tpl):
            die(f"configured {style} template not found: {tpl}\n"
                "Fix the path in config.json / DECK_BUILDER_CSI_TEMPLATE / "
                "DECK_BUILDER_CSITW_TEMPLATE, or remove the setting to fall back "
                f"to the bundled asset.")
        spec["template"] = tpl
        return

    bundled_rel = BUNDLED_CSI if style == "csi" else BUNDLED_CSITW
    bundled = os.path.join(skill_dir(), bundled_rel)
    if not os.path.isfile(bundled):
        die(f"the bundled {style} template is missing ({bundled}). Re-clone the skill, "
            "or set \"template\" in the spec / the matching DECK_BUILDER_*_TEMPLATE "
            f"env var. See references/{'company-template' if style == 'csi' else 'csitw-template'}.md.")
    spec["template"] = bundled


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True,
                    help="path to the deck source: a spec .json, or a .md outline")
    ap.add_argument("--out", required=True, help="output .pptx path")
    ap.add_argument("--force", action="store_true",
                    help="overwrite --out if it exists")
    args = ap.parse_args()

    # A .md source is the approved outline itself, so it can be built without being
    # transcribed into JSON first — transcription is where an outline and its deck drift.
    if os.path.splitext(args.spec)[1].lower() in (".md", ".markdown"):
        try:
            spec = md_to_spec.load(args.spec)
        except md_to_spec.MdError as e:
            die(f"{os.path.basename(args.spec)}: {e}")
    else:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)

    resolve_template(spec)
    if not spec.get("slides"):
        die("spec has no slides")
    if os.path.exists(args.out) and not args.force:
        die(f"{args.out} already exists — pass --force to overwrite")

    apply_fonts(spec)
    style = normalize_style(spec)
    if style == "recommended":
        build_recommended(spec, args.out)
    elif style in TEMPLATE_STYLES:
        build_from_template(spec, args.out)
    else:
        die(f"unknown style {style!r} — use csi, csitw, company (alias of csi), "
            "recommended or custom")


if __name__ == "__main__":
    main()
