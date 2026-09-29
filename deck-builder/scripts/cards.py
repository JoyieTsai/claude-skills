#!/usr/bin/env python3
"""Card-grid body for deck-builder slides.

Drawn as native shapes (rounded panels + Interface Icons + text), editable in
PowerPoint. Icons default to Flaticon Interface Icons (Uicons) by name —
see interface_icons.py and references/cards.md.
"""

from __future__ import annotations

import os

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

import interface_icons

# Accent bars cycle across cards (aligned with CSI / Slidev showcase).
ACCENTS = (
    RGBColor(0x0D, 0x63, 0xBA),
    RGBColor(0x00, 0x94, 0x70),
    RGBColor(0x43, 0x9E, 0xB1),
    RGBColor(0x0B, 0x53, 0x9D),
)

CARD_FILL = RGBColor(0xF4, 0xF6, 0xF9)
CARD_EDGE = RGBColor(0xE5, 0xE7, 0xEB)
TITLE_COLOR = RGBColor(0x13, 0x18, 0x2C)
BODY_COLOR = RGBColor(0x5A, 0x5F, 0x6E)
ICON_BADGE_COLOR = RGBColor(0xE8, 0xF0, 0xFB)   # light brand-blue tint for icon badge
BAR_H = 0.08
GAP = 0.22
PAD = 0.18
ICON = 0.40
ICON_LARGE = 0.52   # icon-variant: larger icon centered above title
ICON_BADGE_PAD = 0.10   # badge extends this many inches beyond icon on each side
IMG_TOP_FRAC = 0.42  # image-variant: image takes this fraction of card height
MAX_CARDS = 6

# Grid variants: explicit column count, ignoring the count-based _grid() heuristic.
_GRID_VARIANTS = {"2-col": (2, None), "3-col": (3, None), "4-grid": (2, 2), "2x2": (2, 2)}

# Style variants that change how individual cards are drawn (not the grid shape).
_STYLE_VARIANTS = {"icon", "number", "image", "steps", "bento", "featured"}


def check_cards(idx, cards, warn, die, variant=None, icon_dirs=None):
    if not isinstance(cards, list) or not cards:
        die(f"slide {idx}: cards must be a non-empty list")
    max_n = 8 if variant == "steps" else MAX_CARDS
    if len(cards) > max_n:
        die(f"slide {idx}: {len(cards)} {'steps' if variant == 'steps' else 'cards'} "
            f"— max is {max_n}; split the slide")
    if len(cards) > 4 and variant not in ("steps", "3-col"):
        warn(f"slide {idx}: {len(cards)} cards is dense — 2–4 reads cleaner")
    for i, c in enumerate(cards):
        if not isinstance(c, dict):
            die(f"slide {idx}: cards[{i}] must be an object with title/body")
        if not (c.get("title") or "").strip():
            die(f"slide {idx}: cards[{i}] needs a title")
        if variant == "image" and not (c.get("image") or "").strip():
            warn(f"slide {idx}: cards[{i}] has no 'image' field — image-variant cards "
                 "need {{..., \"image\": \"/path/to/img.png\"}}")
        ref = c.get("icon")
        if not ref:
            continue
        path = interface_icons.resolve_icon(ref, extra_dirs=icon_dirs)
        if not path:
            ui = ", ".join(interface_icons.list_interface_icons(icon_dirs)[:8])
            csi = ", ".join(interface_icons.list_csi_icons(icon_dirs)[:8])
            die(f"slide {idx}: cards[{i}] icon {ref!r} not found. "
                f"Use Interface Icon names (e.g. ai, document) or CSI product icons "
                f"with csi: prefix (e.g. csi:court). "
                f"UI: {ui}… · CSI: {csi}… · guide: {interface_icons.CSI_ICONOGRAPHY_URL}")
        c["_icon_path"] = path


def _grid(n):
    if n <= 3:
        return n, 1
    if n == 4:
        return 2, 2
    return 3, 2 if n <= 6 else 3


def _grid_for_variant(n, variant):
    if variant in _GRID_VARIANTS:
        cols, rows = _GRID_VARIANTS[variant]
        return cols, rows or max(1, -(-n // cols))
    return _grid(n)


def add_cards(slide, cards, box, style_run, variant=None,
              latin="Segoe UI", cjk="Microsoft JhengHei"):
    """Lay out `cards` inside `box` = (x, y, w, h) inches.

    variant: None/auto — auto-grid, default card style
             2-col / 3-col / 4-grid — forced column count, default card style
             icon    — icon centered above title, no inline icon
             number  — large ordinal number (01 02 …) instead of icon
             image   — image thumbnail fills card top (each card needs `image` field)
             steps   — vertical numbered-step list; more editorial than grid cards
    """
    if variant == "steps":
        _step_list(slide, cards, box, style_run, latin, cjk)
        return
    if variant == "bento":
        _bento_cards(slide, cards, box, style_run, latin, cjk)
        return
    if variant == "featured":
        _featured_cards(slide, cards, box, style_run, latin, cjk)
        return

    x0, y0, bw, bh = box
    n = len(cards)
    style = variant if variant in _STYLE_VARIANTS else None
    cols, rows = _grid_for_variant(n, variant)
    cell_w = (bw - GAP * (cols - 1)) / cols
    cell_h = (bh - GAP * (rows - 1)) / rows

    for i, card in enumerate(cards):
        r, c = divmod(i, cols)
        if r >= rows:
            break
        cx = x0 + c * (cell_w + GAP)
        cy = y0 + r * (cell_h + GAP)
        accent = ACCENTS[i % len(ACCENTS)]
        if style == "icon":
            _one_card_icon(slide, card, cx, cy, cell_w, cell_h, accent,
                           style_run, latin, cjk)
        elif style == "number":
            _one_card_number(slide, card, i, cx, cy, cell_w, cell_h, accent,
                             style_run, latin, cjk)
        elif style == "image":
            _one_card_image(slide, card, cx, cy, cell_w, cell_h,
                            style_run, latin, cjk)
        else:
            _one_card(slide, card, cx, cy, cell_w, cell_h, accent,
                      style_run, latin, cjk)


def _one_card(slide, card, x, y, w, h, accent, style_run, latin, cjk):
    panel = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    panel.name = "db:card"
    panel.fill.solid()
    panel.fill.fore_color.rgb = CARD_FILL
    panel.line.color.rgb = CARD_EDGE
    panel.line.width = Pt(1)
    panel.shadow.inherit = False

    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(BAR_H))
    bar.name = "db:card-bar"
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    bar.shadow.inherit = False

    content_top = y + BAR_H + PAD
    text_left = x + PAD
    text_w = w - 2 * PAD

    icon_path = card.get("_icon_path") or (
        interface_icons.resolve_icon(card["icon"]) if card.get("icon") else None)

    if icon_path:
        ix, iy = x + PAD, content_top
        _icon_badge(slide, ix, iy, ICON)
        pic = slide.shapes.add_picture(
            icon_path, Inches(ix), Inches(iy),
            width=Inches(ICON), height=Inches(ICON))
        pic.name = "db:card-icon"
        scale = min(Inches(ICON) / pic.width, Inches(ICON) / pic.height)
        pic.width = Emu(int(pic.width * scale))
        pic.height = Emu(int(pic.height * scale))
        text_left = x + PAD + ICON + 0.12
        text_w = w - PAD - (text_left - x)

    title = (card.get("title") or "").strip()
    body = (card.get("body") or card.get("text") or "").strip()

    title_h = 0.42 if not body else 0.38
    tb = slide.shapes.add_textbox(
        Inches(text_left), Inches(content_top), Inches(text_w), Inches(title_h))
    tb.name = "db:card-title"
    tf = tb.text_frame
    tf.word_wrap = True
    style_run(tf.paragraphs[0].add_run(), title, size=15, color=TITLE_COLOR, bold=True,
              font=latin, cjk=cjk)

    if body:
        body_top = content_top + title_h + 0.04
        if icon_path:
            body_left, body_w = x + PAD, w - 2 * PAD
            body_top = max(body_top, content_top + ICON + 0.10)
        else:
            body_left, body_w = text_left, text_w
        body_h = max(y + h - PAD - body_top, 0.4)
        tb2 = slide.shapes.add_textbox(
            Inches(body_left), Inches(body_top), Inches(body_w), Inches(body_h))
        tb2.name = "db:card-body"
        tf2 = tb2.text_frame
        tf2.word_wrap = True
        style_run(tf2.paragraphs[0].add_run(), body, size=12, color=BODY_COLOR,
                  font=latin, cjk=cjk)


def _step_list(slide, cards, box, style_run, latin, cjk):
    """Vertical numbered-step list — open layout, no card panel.

    Visual: accent circle with white number · bold title · lighter body
    Two columns when more than 4 steps so everything fits on one slide.
    """
    from pptx.dml.color import RGBColor as _RGB
    WHITE = _RGB(0xFF, 0xFF, 0xFF)

    x0, y0, bw, bh = box
    n = len(cards)
    cols = 2 if n > 4 else 1

    col_w   = (bw - (GAP * (cols - 1))) / cols
    CIRC_D  = 0.42
    CIRC_R  = CIRC_D / 2
    NUM_OFF = CIRC_R - 0.08      # nudge number into circle center
    TEXT_X  = CIRC_D + 0.18     # text starts this far right of column origin
    TEXT_W  = col_w - TEXT_X - PAD
    TITLE_H = 0.38
    BODY_H  = 0.36
    GAP_ROW = 0.26               # vertical gap between steps
    ROW_H   = TITLE_H + (BODY_H + 0.08 if True else 0) + GAP_ROW

    # Compute actual row height from content presence
    rows_per_col = -(-n // cols)   # ceil division

    for i, card in enumerate(cards):
        col_idx = i // rows_per_col
        row_idx = i % rows_per_col

        # Connector line between consecutive steps in the same column
        if row_idx > 0:
            prev_cy = y0 + (row_idx - 1) * ROW_H + CIRC_R
            curr_cy = y0 + row_idx * ROW_H - CIRC_R
            cx_col  = x0 + col_idx * (col_w + GAP) + CIRC_R
            line = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(cx_col - 0.01), Inches(prev_cy),
                Inches(0.02), Inches(curr_cy - prev_cy))
            line.name = f"db:step-line-{i}"
            line.fill.solid()
            line.fill.fore_color.rgb = CARD_EDGE
            line.line.fill.background()
            line.shadow.inherit = False

        sx = x0 + col_idx * (col_w + GAP)
        sy = y0 + row_idx * ROW_H
        accent = ACCENTS[i % len(ACCENTS)]

        # Numbered circle
        circ = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(sx), Inches(sy), Inches(CIRC_D), Inches(CIRC_D))
        circ.name = f"db:step-circle-{i}"
        circ.fill.solid()
        circ.fill.fore_color.rgb = accent
        circ.line.fill.background()
        circ.shadow.inherit = False

        num_tb = slide.shapes.add_textbox(
            Inches(sx), Inches(sy + NUM_OFF),
            Inches(CIRC_D), Inches(CIRC_D - NUM_OFF))
        num_tb.name = f"db:step-num-{i}"
        _p = num_tb.text_frame.paragraphs[0]
        _p.alignment = PP_ALIGN.CENTER
        style_run(_p.add_run(), f"{i + 1:02d}", size=13, color=WHITE,
                  bold=True, font=latin, cjk=cjk)

        # Title
        title = (card.get("title") or "").strip()
        tx = sx + TEXT_X
        tb_t = slide.shapes.add_textbox(
            Inches(tx), Inches(sy), Inches(TEXT_W), Inches(TITLE_H))
        tb_t.name = f"db:step-title-{i}"
        tf_t = tb_t.text_frame
        tf_t.word_wrap = True
        style_run(tf_t.paragraphs[0].add_run(), title, size=15, color=TITLE_COLOR,
                  bold=True, font=latin, cjk=cjk)

        # Body
        body = (card.get("body") or card.get("text") or "").strip()
        if body:
            bt = slide.shapes.add_textbox(
                Inches(tx), Inches(sy + TITLE_H + 0.04),
                Inches(TEXT_W), Inches(BODY_H))
            bt.name = f"db:step-body-{i}"
            tf_b = bt.text_frame
            tf_b.word_wrap = True
            style_run(tf_b.paragraphs[0].add_run(), body, size=12, color=BODY_COLOR,
                      font=latin, cjk=cjk)


def _icon_badge(slide, cx, cy, size):
    """Draw a light circle badge centered at (cx, cy) with given diameter."""
    d = size + ICON_BADGE_PAD * 2
    bx, by = cx - ICON_BADGE_PAD, cy - ICON_BADGE_PAD
    badge = slide.shapes.add_shape(
        MSO_SHAPE.OVAL, Inches(bx), Inches(by), Inches(d), Inches(d))
    badge.name = "db:card-icon-badge"
    badge.fill.solid()
    badge.fill.fore_color.rgb = ICON_BADGE_COLOR
    badge.line.fill.background()
    badge.shadow.inherit = False
    return badge


def _card_panel(slide, x, y, w, h, accent, with_bar=True):
    """Flat panel + optional accent bar. Returns the panel shape."""
    panel = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    panel.name = "db:card"
    panel.fill.solid()
    panel.fill.fore_color.rgb = CARD_FILL
    panel.line.color.rgb = CARD_EDGE
    panel.line.width = Pt(1)
    panel.shadow.inherit = False
    if with_bar:
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(BAR_H))
        bar.name = "db:card-bar"
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()
        bar.shadow.inherit = False
    return panel


def _one_card_icon(slide, card, x, y, w, h, accent, style_run, latin, cjk):
    """Icon centered above title — icon is the visual anchor, not inline."""
    _card_panel(slide, x, y, w, h, accent, with_bar=True)
    content_top = y + BAR_H + PAD

    icon_path = card.get("_icon_path") or (
        interface_icons.resolve_icon(card["icon"]) if card.get("icon") else None)
    if icon_path:
        ix = x + (w - ICON_LARGE) / 2
        _icon_badge(slide, ix, content_top, ICON_LARGE)
        pic = slide.shapes.add_picture(
            icon_path, Inches(ix), Inches(content_top),
            width=Inches(ICON_LARGE), height=Inches(ICON_LARGE))
        pic.name = "db:card-icon"
        scale = min(Inches(ICON_LARGE) / pic.width, Inches(ICON_LARGE) / pic.height)
        pic.width = Emu(int(pic.width * scale))
        pic.height = Emu(int(pic.height * scale))
        content_top += ICON_LARGE + 0.10

    title = (card.get("title") or "").strip()
    body = (card.get("body") or card.get("text") or "").strip()
    title_h = 0.40
    tb = slide.shapes.add_textbox(
        Inches(x + PAD), Inches(content_top), Inches(w - 2 * PAD), Inches(title_h))
    tb.name = "db:card-title"
    tf = tb.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    style_run(tf.paragraphs[0].add_run(), title, size=14, color=TITLE_COLOR, bold=True,
              font=latin, cjk=cjk)
    if body:
        body_top = content_top + title_h + 0.04
        body_h = max(y + h - PAD - body_top, 0.3)
        tb2 = slide.shapes.add_textbox(
            Inches(x + PAD), Inches(body_top), Inches(w - 2 * PAD), Inches(body_h))
        tb2.name = "db:card-body"
        tf2 = tb2.text_frame
        tf2.word_wrap = True
        tf2.paragraphs[0].alignment = PP_ALIGN.CENTER
        style_run(tf2.paragraphs[0].add_run(), body, size=12, color=BODY_COLOR,
                  font=latin, cjk=cjk)


def _one_card_number(slide, card, idx, x, y, w, h, accent, style_run, latin, cjk):
    """Large ordinal number (01, 02 …) replaces the icon as visual anchor."""
    _card_panel(slide, x, y, w, h, accent, with_bar=True)
    content_top = y + BAR_H + PAD

    num_text = f"{idx + 1:02d}"
    NUM_H = 0.55
    tb_n = slide.shapes.add_textbox(
        Inches(x + PAD), Inches(content_top), Inches(w - 2 * PAD), Inches(NUM_H))
    tb_n.name = "db:card-num"
    style_run(tb_n.text_frame.paragraphs[0].add_run(), num_text,
              size=30, color=accent, bold=True, font=latin, cjk=cjk)

    title = (card.get("title") or "").strip()
    body = (card.get("body") or card.get("text") or "").strip()
    title_top = content_top + NUM_H + 0.06
    title_h = 0.40
    tb = slide.shapes.add_textbox(
        Inches(x + PAD), Inches(title_top), Inches(w - 2 * PAD), Inches(title_h))
    tb.name = "db:card-title"
    tb.text_frame.word_wrap = True
    style_run(tb.text_frame.paragraphs[0].add_run(), title, size=14, color=TITLE_COLOR,
              bold=True, font=latin, cjk=cjk)
    if body:
        body_top = title_top + title_h + 0.04
        body_h = max(y + h - PAD - body_top, 0.3)
        tb2 = slide.shapes.add_textbox(
            Inches(x + PAD), Inches(body_top), Inches(w - 2 * PAD), Inches(body_h))
        tb2.name = "db:card-body"
        tb2.text_frame.word_wrap = True
        style_run(tb2.text_frame.paragraphs[0].add_run(), body, size=12,
                  color=BODY_COLOR, font=latin, cjk=cjk)


def _one_card_image(slide, card, x, y, w, h, style_run, latin, cjk):
    """Image thumbnail fills top portion of the card."""
    _card_panel(slide, x, y, w, h, accent=ACCENTS[0], with_bar=False)

    img_path = (card.get("image") or "").strip()
    IMG_H = h * IMG_TOP_FRAC
    if img_path and os.path.isfile(img_path):
        pic = slide.shapes.add_picture(
            img_path, Inches(x), Inches(y), width=Inches(w), height=Inches(IMG_H))
        pic.name = "db:card-img"

    content_top = y + IMG_H + PAD * 0.6
    title = (card.get("title") or "").strip()
    body = (card.get("body") or card.get("text") or "").strip()
    title_h = 0.38
    tb = slide.shapes.add_textbox(
        Inches(x + PAD), Inches(content_top), Inches(w - 2 * PAD), Inches(title_h))
    tb.name = "db:card-title"
    tb.text_frame.word_wrap = True
    style_run(tb.text_frame.paragraphs[0].add_run(), title, size=14, color=TITLE_COLOR,
              bold=True, font=latin, cjk=cjk)
    if body:
        body_top = content_top + title_h + 0.04
        body_h = max(y + h - PAD - body_top, 0.3)
        tb2 = slide.shapes.add_textbox(
            Inches(x + PAD), Inches(body_top), Inches(w - 2 * PAD), Inches(body_h))
        tb2.name = "db:card-body"
        tb2.text_frame.word_wrap = True
        style_run(tb2.text_frame.paragraphs[0].add_run(), body, size=12,
                  color=BODY_COLOR, font=latin, cjk=cjk)


# ---------------------------------------------------------------- editorial card compositions

def _bento_cards(slide, cards, box, style_run, latin, cjk):
    """Asymmetric bento: one dominant card plus supporting cards.

    Best with 3–5 items. The first card is intentionally dominant; remaining
    items occupy a narrower supporting column (or a compact lower row for 5).
    """
    x, y, w, h = box
    n = len(cards)
    if n < 2:
        _one_card(slide, cards[0], x, y, w, h, ACCENTS[0], style_run, latin, cjk)
        return

    main_w = w * 0.62
    side_x = x + main_w + GAP
    side_w = w - main_w - GAP
    _one_card(slide, cards[0], x, y, main_w, h, ACCENTS[0], style_run, latin, cjk)

    rest = cards[1:]
    if len(rest) <= 3:
        cell_h = (h - GAP * (len(rest) - 1)) / len(rest)
        for j, card in enumerate(rest):
            cy = y + j * (cell_h + GAP)
            _one_card(slide, card, side_x, cy, side_w, cell_h,
                      ACCENTS[(j + 1) % len(ACCENTS)], style_run, latin, cjk)
    else:
        # Four supporting items: compact 2x2 block on the right.
        cols, rows = 2, 2
        cw = (side_w - GAP) / cols
        ch = (h - GAP) / rows
        for j, card in enumerate(rest[:4]):
            r, c = divmod(j, cols)
            _one_card(slide, card, side_x + c * (cw + GAP), y + r * (ch + GAP),
                      cw, ch, ACCENTS[(j + 1) % len(ACCENTS)], style_run, latin, cjk)


def _featured_cards(slide, cards, box, style_run, latin, cjk):
    """Editorial hierarchy: a wide featured item followed by compact supports."""
    x, y, w, h = box
    n = len(cards)
    if n == 1:
        _one_card(slide, cards[0], x, y, w, h, ACCENTS[0], style_run, latin, cjk)
        return

    feature_h = h * 0.52
    _one_card(slide, cards[0], x, y, w, feature_h, ACCENTS[0], style_run, latin, cjk)
    rest = cards[1:]
    lower_y = y + feature_h + GAP
    lower_h = h - feature_h - GAP
    cols = min(len(rest), 3)
    cw = (w - GAP * (cols - 1)) / cols
    for j, card in enumerate(rest[:3]):
        _one_card(slide, card, x + j * (cw + GAP), lower_y, cw, lower_h,
                  ACCENTS[(j + 1) % len(ACCENTS)], style_run, latin, cjk)
