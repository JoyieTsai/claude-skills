#!/usr/bin/env python3
"""Native, editable PowerPoint charts for deck-builder.

A chart added here is a real `c:chart` part with its data in an embedded workbook, so
the user can click it in PowerPoint, edit the numbers, and change the type. It is not
a picture. That is the whole point — an image of a chart is a dead end for the person
who has to update the deck next quarter.

The colour and form rules come from the `dataviz` skill's method, with the palette
re-derived against *this* template's surfaces and re-validated with its
`scripts/validate_palette.js`. See references/charts.md for the measured numbers and
for what the method asks for that pptx cannot do.

Two things pptx charts cannot honour, stated rather than silently dropped:
  - No rounded data-ends. A chart series has no corner-radius control in DrawingML,
    so bars are square. (A drawn rounded rectangle would not be a chart.)
  - No hover layer. A .pptx has no hover, so identity leans on the legend and on
    selective direct labels instead — which is why those are on by default here.
"""

import copy

from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (XL_CHART_TYPE, XL_LABEL_POSITION,
                             XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_MARK)
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt


# ------------------------------------------------------------------ palette
#
# Validated with dataviz's own validator against this template's real surfaces, not
# eyeballed. Every number in references/charts.md is a command's output.
#
#   node scripts/validate_palette.js "<CATEGORICAL joined by ,>" \
#        --mode light --surface "#ffffff"
#   -> ALL CHECKS PASS  (worst adjacent CVD ΔE 8.4 protan; normal-vision 18.3;
#                        all 8 clear 3:1 on white)
#
# Slot order is fixed and never cycled — a 9th series folds into "其他" or becomes
# small multiples. Slots 1–5 are hue-distinct from the status trio, so a series never
# impersonates a status.

CATEGORICAL = ["#0d63ba",   # 1 brand blue — always the first series
               "#eb6834",   # 2 orange
               "#12a06d",   # 3 green
               "#c74d7c",   # 4 magenta
               "#4a3aa7",   # 5 violet
               "#b87c00",   # 6 ochre
               "#008300",   # 7 deep green
               "#e34948"]   # 8 red

# Under --pairs all (every series compared with every other, which is how a scatter or
# bubble chart is actually read) only the first three clear the floors: 4+ collides
# #b87c00 with #eb6834 at ΔE 2.3 protan. So scatter/bubble cap at 3 series.
ALL_PAIRS_MAX = 3

# Magnitude, one hue, light -> dark. The categorical validator FAILs a ramp by design
# (dataviz color-formula.md: "running the categorical validator on a sequential ramp
# will FAIL by design ... don't 'fix' a good ramp to satisfy it"). The real checks are
# monotonic lightness and a light end still >= 2:1 on the surface — #86b6ef is 2.11:1.
SEQUENTIAL = ["#86b6ef", "#6da7ec", "#3987e5", "#0d63ba", "#0a4a8c"]

# Polarity: two hues plus a NEUTRAL GREY midpoint, equal steps per arm. Never a hue at
# the midpoint — a coloured middle reads as a third category instead of "no change".
DIVERGING = ["#b3401c", "#e8825c", "#d8d8d8", "#6da7ec", "#0d63ba"]

# Reserved meanings. Never reused as "series 4", and never colour alone: the label text
# carries the meaning, the colour only reinforces it.
STATUS = {"good": "#008300", "warning": "#b87c00",
          "serious": "#eb6834", "critical": "#e34948"}

# The emphasis form: one bar in the brand blue, the rest recessive. #8c93a3 is 3.08:1
# on white, so the de-emphasised bars are still legible as marks; its low chroma is
# deliberate — it is a neutral, not an identity, so the chroma floor does not apply.
EMPHASIS_ON = "#0d63ba"
EMPHASIS_OFF = "#8c93a3"

# Ink. Recessive grid and axes; text in text tokens, never in a series colour.
GRID = "#d8d8d8"
AXIS_TEXT = "#5a5f6e"
LABEL_TEXT = "#13182c"

# Chart-surface colours the palette was validated against.
SURFACE_LIGHT = "#ffffff"
SURFACE_DARK = "#0b539d"   # Content Heading Dark's full-bleed navy


def _rgb(h):
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


MARKER_CIRCLE = XL_MARKER_STYLE.CIRCLE
MARKER_NONE = XL_MARKER_STYLE.NONE


# ------------------------------------------------------------------ chart types

# Only forms that survive being read from across a room, and only ones dataviz
# endorses. Notably absent: pie beyond 2 slices (use a bar), 3-D anything, dual-axis
# (impossible here by construction — one value axis per chart), radar, doughnut.
FORMS = {
    "bar":            XL_CHART_TYPE.BAR_CLUSTERED,        # magnitude, long labels
    "column":         XL_CHART_TYPE.COLUMN_CLUSTERED,     # magnitude over few periods
    "stacked-bar":    XL_CHART_TYPE.BAR_STACKED,
    "stacked-column": XL_CHART_TYPE.COLUMN_STACKED,
    "line":           XL_CHART_TYPE.LINE,                 # change over time, >6 points
    "line-markers":   XL_CHART_TYPE.LINE_MARKERS,
    "area":           XL_CHART_TYPE.AREA,
    "scatter":        XL_CHART_TYPE.XY_SCATTER,           # correlation
    "pie":            XL_CHART_TYPE.PIE,                  # >= 3 slices only
}

XY_FORMS = {"scatter"}


def form_for(spec):
    name = str(spec.get("form") or "column").strip().lower()
    if name not in FORMS:
        raise ValueError(
            f"unknown chart form {name!r} — use one of: {', '.join(sorted(FORMS))}")
    return name, FORMS[name]


# ------------------------------------------------------------------ font plumbing

def _set_cjk_on_defrpr(defRPr, cjk, latin):
    """Add a:ea and a:cs to a chart's defRPr, in schema order.

    python-pptx's `font.name` writes only `a:latin`, exactly as it does on slide text —
    so Chinese category names and axis labels in a chart fall back to whatever the
    renderer picks. CT_TextCharacterProperties is a sequence: solidFill? then latin,
    ea, cs. Appending out of order produces a file PowerPoint repairs, so each element
    is inserted after the last of its predecessors that is actually present.
    """
    order = ["a:latin", "a:ea", "a:cs"]
    want = {"a:latin": latin, "a:ea": cjk, "a:cs": cjk}
    for tag in order:
        el = defRPr.find(qn(tag))
        if el is None:
            el = defRPr.makeelement(qn(tag), {})
            prevs = order[:order.index(tag)]
            anchor = None
            for p in prevs:
                found = defRPr.find(qn(p))
                if found is not None:
                    anchor = found
            if anchor is not None:
                anchor.addnext(el)
            else:
                # No predecessor present: after solidFill if there is one, else first.
                fill = defRPr.find(qn("a:solidFill"))
                if fill is not None:
                    fill.addnext(el)
                else:
                    defRPr.insert(0, el)
        el.set("typeface", want[tag])


def _apply_fonts(chart, latin, cjk):
    """Set both typefaces on every defRPr in the chart part.

    Covers the chart-level font plus anything with its own text properties — axis tick
    labels, the legend, data labels — since each carries a separate defRPr and a
    missing a:ea on any one of them shows up as one mismatched line of Chinese.
    """
    for defRPr in chart._chartSpace.iter(qn("a:defRPr")):
        _set_cjk_on_defrpr(defRPr, cjk, latin)


# ------------------------------------------------------------------ ink

def _line(fmt, hex_color, width_pt):
    fmt.line.color.rgb = _rgb(hex_color)
    fmt.line.width = Pt(width_pt)


def _hide_line(fmt):
    fmt.line.fill.background()


def _paint_series(ser, hex_color, form):
    """Colour one series according to how its form carries colour.

    A bar/area series carries colour in its fill; a line carries it in its stroke, and
    setting a fill on a line series does nothing visible. Markers get a 2px ring in the
    surface colour so overlapping points stay countable — that ring is the one piece of
    dataviz's spacer spec that pptx *can* honour.
    """
    if form in ("line", "line-markers", "scatter"):
        _line(ser.format, hex_color, 2.0)
        ser.smooth = False               # a smoothed line invents values between points
        try:
            m = ser.marker
            if form in ("line-markers", "scatter"):
                m.style = MARKER_CIRCLE
                m.size = 8               # >= 8px, or the point is a speck from a room
                m.format.fill.solid()
                m.format.fill.fore_color.rgb = _rgb(hex_color)
                _line(m.format, SURFACE_LIGHT, 2.0)
            else:
                m.style = MARKER_NONE
        except (AttributeError, NotImplementedError):
            pass
        return

    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = _rgb(hex_color)
    # No border around a mark — an outline is ink that encodes nothing.
    _hide_line(ser.format)


def _style_axes(chart, form, on_dark, value_fmt=None, max_scale=None):
    """Recessive grid and axes: the data is the figure, the frame is the ground.

    Gridlines on the value axis only, 0.75pt in #d8d8d8 — solid, never dashed. Category
    axis line kept (it is the baseline the bars sit on) but its ticks removed; the value
    axis line hidden, because with gridlines present it is redundant ink.
    """
    grid = GRID if not on_dark else "#4a86c8"
    text = AXIS_TEXT if not on_dark else "#e7e6e6"

    try:
        va = chart.value_axis
    except (ValueError, NotImplementedError):
        va = None
    if va is not None:
        va.has_major_gridlines = True
        _line(va.major_gridlines.format, grid, 0.75)
        _hide_line(va.format)
        va.major_tick_mark = XL_TICK_MARK.NONE
        va.minor_tick_mark = XL_TICK_MARK.NONE
        va.has_minor_gridlines = False
        va.tick_labels.font.size = Pt(12)
        va.tick_labels.font.color.rgb = _rgb(text)
        if value_fmt:
            va.tick_labels.number_format = value_fmt
            va.tick_labels.number_format_is_linked = False
        if max_scale is not None:
            va.maximum_scale = float(max_scale)

    try:
        ca = chart.category_axis
    except (ValueError, NotImplementedError):
        ca = None
    if ca is not None:
        ca.has_major_gridlines = False
        ca.has_minor_gridlines = False
        _line(ca.format, grid, 0.75)
        ca.major_tick_mark = XL_TICK_MARK.NONE
        ca.minor_tick_mark = XL_TICK_MARK.NONE
        ca.tick_labels.font.size = Pt(12)
        ca.tick_labels.font.color.rgb = _rgb(text)


def _style_legend(chart, n_series, on_dark):
    """A legend for >= 2 series, none for one.

    With one series the chart title or the slide headline already names it, so a legend
    box is a second copy of the same word. With two or more, identity must not be
    colour-alone — and a .pptx has no hover to fall back on.
    """
    if n_series < 2:
        chart.has_legend = False
        return
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False   # or it eats the plot area
    chart.legend.font.size = Pt(12)
    chart.legend.font.color.rgb = _rgb("#e7e6e6" if on_dark else AXIS_TEXT)


def _label_points(plot, series_idx, point_idxs, number_format, on_dark):
    """Direct-label only the points that carry the argument.

    A number on every point is the single most common way a chart becomes a table with
    extra steps. Labelling the first, last and peak is usually the whole story; the rest
    are read off the gridlines.
    """
    ser = plot.series[series_idx]
    for i in point_idxs:
        try:
            pt = ser.points[i]
        except IndexError:
            continue
        dLbl = pt.data_label
        dLbl.has_text_frame = False    # keep the value, don't overwrite it
        dLbl.number_format = number_format or "General"
        dLbl.number_format_is_linked = False
        dLbl.font.size = Pt(12)
        dLbl.font.bold = True
        dLbl.font.color.rgb = _rgb("#ffffff" if on_dark else LABEL_TEXT)


# ------------------------------------------------------------------ series colour

def _series_colors(spec, n_series, n_points):
    """Which colour each series gets, by the job the colour is doing.

    - emphasis: one point in brand blue, the others neutral. One series only — it is a
      per-point encoding, so a second series has nowhere to put it.
    - sequential / ordinal: one hue, light -> dark, so the reader sees the order.
    - diverging: two hues around a grey midpoint.
    - categorical (default): fixed slot order, never cycled.
    """
    scheme = str(spec.get("colors") or "categorical").strip().lower()

    if scheme == "emphasis":
        if n_series != 1:
            raise ValueError("colors 'emphasis' marks one point of one series — "
                             f"got {n_series} series")
        hi = spec.get("emphasize")
        if hi is None:
            raise ValueError('colors "emphasis" needs "emphasize": <point index>')
        idxs = hi if isinstance(hi, list) else [hi]
        return ("per_point",
                [EMPHASIS_ON if i in idxs else EMPHASIS_OFF for i in range(n_points)])

    if scheme in ("sequential", "ordinal"):
        ramp = _resample(SEQUENTIAL, n_series if n_series > 1 else n_points)
        return ("per_series" if n_series > 1 else "per_point", ramp)

    if scheme == "diverging":
        ramp = _resample(DIVERGING, n_series if n_series > 1 else n_points)
        return ("per_series" if n_series > 1 else "per_point", ramp)

    if scheme == "status":
        keys = spec.get("status") or []
        if len(keys) != n_points:
            raise ValueError(f'colors "status" needs a "status" list of {n_points} '
                             f"role names, one per point — got {len(keys)}")
        bad = [k for k in keys if k not in STATUS]
        if bad:
            raise ValueError(f"unknown status role(s) {bad} — use "
                             f"{', '.join(sorted(STATUS))}")
        return ("per_point", [STATUS[k] for k in keys])

    if scheme != "categorical":
        raise ValueError(f"unknown colors {scheme!r} — use categorical, sequential, "
                         "ordinal, diverging, emphasis or status")

    if n_series > len(CATEGORICAL):
        raise ValueError(
            f"{n_series} series exceeds the {len(CATEGORICAL)} fixed categorical "
            "slots. Hues are never cycled — a 9th series is indistinguishable from "
            "the 1st. Fold the tail into 「其他」, or split into small multiples.")
    if n_series > 1:
        return ("per_series", CATEGORICAL[:n_series])
    # One nominal series: every bar takes slot 1. A value-ramp across nominal
    # categories implies an order that isn't there.
    return ("per_point", [CATEGORICAL[0]] * n_points)


def _resample(ramp, n):
    """n evenly spaced steps from a ramp, endpoints included."""
    if n <= 1:
        return [ramp[-2] if len(ramp) > 1 else ramp[0]]
    if n >= len(ramp):
        return (ramp * ((n // len(ramp)) + 1))[:n]
    step = (len(ramp) - 1) / (n - 1)
    return [ramp[round(i * step)] for i in range(n)]


# ------------------------------------------------------------------ sanity checks

def check_chart(idx, spec, warn):
    """Catch the anti-patterns before the chart is drawn.

    Each of these is in dataviz's anti-pattern catalogue, and each is the kind of thing
    that looks fine in the spec and wrong on the slide.
    """
    form = str(spec.get("form") or "column").strip().lower()
    series = spec.get("series") or []
    cats = spec.get("categories") or []

    if not series:
        raise ValueError(f"slide {idx}: chart has no series")
    for s in series:
        vals = s.get("values") or []
        if form in XY_FORMS:
            if not all(isinstance(v, (list, tuple)) and len(v) == 2 for v in vals):
                raise ValueError(f"slide {idx}: {form} series values must be "
                                 "[x, y] pairs")
        elif len(vals) != len(cats):
            raise ValueError(
                f"slide {idx}: series {s.get('name')!r} has {len(vals)} values but "
                f"there are {len(cats)} categories")

    n = len(series)
    if form == "pie":
        if n > 1:
            raise ValueError(f"slide {idx}: a pie shows one series")
        k = len(series[0].get("values") or [])
        if k < 3:
            raise ValueError(
                f"slide {idx}: a {k}-slice pie is two numbers pretending to be a "
                "chart — use a bar, or a single figure in text")
        if k > 5:
            warn(f"slide {idx}: {k} pie slices — past about 5 the angles stop being "
                 "comparable; a bar chart ranks them readably")

    if form in XY_FORMS and n > ALL_PAIRS_MAX:
        warn(f"slide {idx}: {n} series on a {form} — every series is compared with "
             f"every other here, and only {ALL_PAIRS_MAX} of the slots stay separable "
             "under colour-vision deficiency (slot 6 sits ΔE 2.3 from slot 2 under "
             "protanopia). Facet it, or cut to 3.")

    if form in ("bar", "column") and len(cats) == 1 and n == 1:
        warn(f"slide {idx}: a one-bar bar chart — that is a single number; put it in "
             "the headline or as a large figure instead")

    if form in ("line", "line-markers", "area") and len(cats) < 4:
        warn(f"slide {idx}: a line over {len(cats)} points — a line implies a trend "
             "worth following; with this few, a column chart compares them better")

    if form in ("stacked-bar", "stacked-column") and n > 4:
        warn(f"slide {idx}: {n} stacked segments — only the bottom one shares a "
             "baseline, so the rest can't be compared; cap at about 4")

    if len(cats) > 12 and form in ("bar", "column"):
        warn(f"slide {idx}: {len(cats)} categories — too many bars to read from a "
             "room; take the top few and group the rest")

    labels = spec.get("label_points")
    if labels == "all":
        warn(f"slide {idx}: label_points 'all' puts a number on every point, which "
             "makes a table with extra steps — label the first, last and peak")


# ------------------------------------------------------------------ the entry point

def add_chart(slide, spec, x, y, w, h, on_dark=False,
              latin="Segoe UI", cjk="Microsoft JhengHei", warn=print, idx=0):
    """Add a native, editable chart to a slide and return its graphic frame.

    `spec` is the slide's "chart" object — see references/spec-format.md.
    """
    form_name, xl_type = form_for(spec)
    series = spec["series"]
    cats = spec.get("categories") or []

    if form_name in XY_FORMS:
        cd = XyChartData()
        for s in series:
            sd = cd.add_series(str(s.get("name") or ""))
            for pair in s["values"]:
                sd.add_data_point(float(pair[0]), float(pair[1]))
        n_points = max(len(s["values"]) for s in series)
    else:
        cd = CategoryChartData()
        cd.categories = [str(c) for c in cats]
        for s in series:
            cd.add_series(str(s.get("name") or ""),
                          tuple(None if v is None else float(v)
                                for v in s["values"]),
                          number_format=spec.get("number_format"))
        n_points = len(cats)

    frame = slide.shapes.add_chart(xl_type, Inches(x), Inches(y),
                                   Inches(w), Inches(h), cd)
    chart = frame.chart
    chart.has_title = False        # the slide headline is the title
    plot = chart.plots[0]

    chart.font.size = Pt(12)
    chart.font.name = latin
    chart.font.color.rgb = _rgb("#ffffff" if on_dark else LABEL_TEXT)

    mode, colors = _series_colors(spec, len(series), n_points)

    if mode == "per_series":
        for si, hexc in enumerate(colors):
            _paint_series(plot.series[si], hexc, form_name)
    else:
        ser = plot.series[0]
        if form_name in ("line", "line-markers", "area"):
            # A per-point fill on a line means nothing — the line is one stroke.
            _paint_series(ser, colors[0], form_name)
        else:
            _paint_series(ser, colors[0], form_name)
            for pi, hexc in enumerate(colors):
                try:
                    pt = ser.points[pi]
                except IndexError:
                    break
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = _rgb(hexc)

    # Thin marks: a 40% gap between bars reads as separate marks rather than a solid
    # block, and no overlap between series in a cluster.
    if form_name in ("bar", "column", "stacked-bar", "stacked-column"):
        try:
            plot.gap_width = 60 if form_name.startswith("stacked") else 80
            plot.overlap = 100 if form_name.startswith("stacked") else -10
        except (AttributeError, NotImplementedError):
            pass

    _style_axes(chart, form_name, on_dark,
                value_fmt=spec.get("axis_format"),
                max_scale=spec.get("max_scale"))
    _style_legend(chart, len(series), on_dark)

    labels = spec.get("label_points")
    if labels == "all":
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.number_format = spec.get("number_format") or "General"
        dl.number_format_is_linked = False
        dl.font.size = Pt(11)
        dl.font.color.rgb = _rgb("#ffffff" if on_dark else LABEL_TEXT)
        if form_name in ("bar", "column"):
            dl.position = XL_LABEL_POSITION.OUTSIDE_END
    elif labels:
        # {"series": 0, "points": [0, -1]} or just [0, -1] for the first series.
        if isinstance(labels, dict):
            si = int(labels.get("series", 0))
            pts = labels.get("points") or []
        else:
            si, pts = 0, list(labels)
        pts = [p if p >= 0 else n_points + p for p in pts]
        _label_points(plot, si, pts, spec.get("number_format"), on_dark)

    _apply_fonts(chart, latin, cjk)
    return frame
