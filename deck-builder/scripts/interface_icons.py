#!/usr/bin/env python3
"""Resolve icons for deck-builder cards.

Two catalogs (see references/cards.md):

1. **Interface Icons** (Flaticon Uicons) — default for UI chrome
   Source: <Frond-end>/genie-ai-agent/src/assets/icons/<name>.svg
   Spec:  `"icon": "ai"`  or  `"icon": "ui:search"`

2. **CSI Icons** (product / module / brand) — for CSI product content
   Design guide: http://10.20.1.229:8081/1.0/design-style/iconography-dev/1
   Local SVGs (duotone): csi-uikit-bootstrap/public/1.0/icons/csiicon-duotone/
                         csi_v3_nuxt_vuetify/assets/duotone/
   Spec:  `"icon": "csi:court"`  or  `"icon": "csi:justice-court"`

Also accepts an absolute filesystem path to png/jpg/svg.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET

try:
    from PIL import Image
except ImportError:
    Image = None

# viewBox units → pixels
DEFAULT_PX = 256

# Brand ink (matches Uicons fill #22354A / CSI $dark)
DEFAULT_INK = (0x22, 0x35, 0x4A, 0xFF)

# Docs page for the CSI set (intranet design system).
CSI_ICONOGRAPHY_URL = "http://10.20.1.229:8081/1.0/design-style/iconography-dev/1"

_CACHE_DIR = None


def _frond_end_root():
    """Walk up from this file / cwd looking for Frond-end workspace."""
    here = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.abspath(os.path.join(here, *([os.pardir] * 4))),
        os.path.abspath(os.path.join(os.getcwd(), os.pardir)),
        os.getcwd(),
        os.path.expanduser("~/Documents/Frond-end"),
    ]
    for root in candidates:
        for probe in (
            os.path.join(root, "genie-ai-agent", "src", "assets", "icons"),
            os.path.join(root, "csi-uikit-bootstrap", "public", "1.0", "icons",
                         "csiicon-duotone"),
        ):
            if os.path.isdir(probe):
                return root
        up = os.path.abspath(os.path.join(root, os.pardir))
        if os.path.isdir(os.path.join(up, "genie-ai-agent", "src", "assets", "icons")):
            return up
    return None


def _dedupe_dirs(dirs):
    seen, out = set(), []
    for d in dirs:
        d = os.path.abspath(os.path.expanduser(d))
        if d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def interface_icon_dirs(extra=None):
    dirs = []
    env = os.environ.get("DECK_BUILDER_INTERFACE_ICONS")
    if env:
        dirs.append(os.path.expanduser(env))
    if extra:
        dirs.extend(extra if isinstance(extra, (list, tuple)) else [extra])
    skill_assets = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "interface-icons")
    for sub in ("png", "svg", ""):
        p = os.path.join(skill_assets, sub) if sub else skill_assets
        if os.path.isdir(p):
            dirs.append(p)
    root = _frond_end_root()
    if root:
        dirs.append(os.path.join(root, "genie-ai-agent", "src", "assets", "icons"))
    return _dedupe_dirs(dirs)


def csi_icon_dirs(extra=None):
    """CSI product duotone SVGs — same set as the iconography design page."""
    dirs = []
    env = os.environ.get("DECK_BUILDER_CSI_ICONS")
    if env:
        dirs.append(os.path.expanduser(env))
    if extra:
        dirs.extend(extra if isinstance(extra, (list, tuple)) else [extra])
    skill_assets = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "csi-icons")
    for sub in ("png", "svg", "duotone", ""):
        p = os.path.join(skill_assets, sub) if sub else skill_assets
        if os.path.isdir(p):
            dirs.append(p)
    root = _frond_end_root()
    if root:
        dirs.append(os.path.join(
            root, "csi-uikit-bootstrap", "public", "1.0", "icons", "csiicon-duotone"))
        dirs.append(os.path.join(root, "csi_v3_nuxt_vuetify", "assets", "duotone"))
    return _dedupe_dirs(dirs)


def icon_search_dirs(extra=None):
    """Back-compat alias: Interface Icons only."""
    return interface_icon_dirs(extra)


def _name_variants(name):
    n = name.strip()
    if n.lower().endswith((".svg", ".png", ".jpg", ".jpeg")):
        n = os.path.splitext(n)[0]
    base = re.sub(r"[_-](outline|solid)$", "", n, flags=re.I)
    variants = []
    for cand in (n, base):
        variants.extend((cand, cand.replace("_", "-"), cand.replace("-", "_")))
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _list_names(dirs):
    names = set()
    for d in dirs:
        for fn in os.listdir(d):
            base, ext = os.path.splitext(fn)
            if ext.lower() in (".svg", ".png", ".jpg", ".jpeg") and base:
                names.add(base)
    return sorted(names)


def list_interface_icons(extra=None):
    return _list_names(interface_icon_dirs(extra))


def list_csi_icons(extra=None):
    return _list_names(csi_icon_dirs(extra))


def resolve_icon(ref, extra_dirs=None, cache_dir=None, px=DEFAULT_PX):
    """Return an absolute path to a PNG/JPEG suitable for pptx add_picture.

    Prefixes:
      csi:court / duotone:court  → CSI product icons, rendered monochrome (same ink as Uicons)
      ui:ai / interface:ai       → Interface Icons
      ai                         → Interface Icons only (no CSI fallback)

    All SVGs are rasterised to flat single-colour PNGs so every icon on a slide
    uses the same visual language regardless of source.
    """
    if not ref or not str(ref).strip():
        return None
    ref = str(ref).strip()

    if os.path.isfile(ref):
        path = os.path.abspath(ref)
        if path.lower().endswith(".svg"):
            return _svg_to_png(path, cache_dir=cache_dir, px=px)
        return path

    catalog = None
    name = ref
    low = ref.lower()
    for prefix, cat in (
        ("csi:", "csi"), ("csi/", "csi"),
        ("duotone:", "csi"), ("duotone/", "csi"),
        ("ui:", "interface"), ("ui/", "interface"),
        ("interface:", "interface"), ("interface/", "interface"),
    ):
        if low.startswith(prefix):
            catalog = cat
            name = ref[len(prefix):]
            break

    if catalog == "csi":
        # Render with forced ink so duotone SVGs look the same as Uicons
        return _find_in_dirs(name, csi_icon_dirs(extra_dirs), cache_dir, px,
                             force_ink=True)
    if catalog == "interface":
        return _find_in_dirs(name, interface_icon_dirs(extra_dirs), cache_dir, px)

    # No prefix → Interface Icons only; no silent CSI fallback
    return _find_in_dirs(name, interface_icon_dirs(extra_dirs), cache_dir, px)


def _find_in_dirs(name, dirs, cache_dir, px, force_ink=False):
    for variant in _name_variants(name):
        for d in dirs:
            for ext in (".png", ".jpg", ".jpeg", ".svg"):
                cand = os.path.join(d, variant + ext)
                if os.path.isfile(cand):
                    if ext == ".svg":
                        return _svg_to_png(cand, cache_dir=cache_dir, px=px,
                                           force_ink=force_ink)
                    return cand
    return None


def _cache_dir(explicit=None):
    global _CACHE_DIR
    if explicit:
        os.makedirs(explicit, exist_ok=True)
        return explicit
    if _CACHE_DIR is None:
        _CACHE_DIR = os.path.join(tempfile.gettempdir(), "deck-builder-icons")
        os.makedirs(_CACHE_DIR, exist_ok=True)
    return _CACHE_DIR


def _svg_to_png(svg_path, cache_dir=None, px=DEFAULT_PX, ink=DEFAULT_INK,
                force_ink=False):
    if Image is None:
        raise RuntimeError("Pillow is required to rasterise Interface Icon SVGs "
                           "(pip install pillow)")
    svg_path = os.path.abspath(svg_path)
    mtime = os.path.getmtime(svg_path)
    key = hashlib.sha1(
        f"{svg_path}|{mtime}|{px}|{ink}|{force_ink}".encode()).hexdigest()[:16]
    base = os.path.splitext(os.path.basename(svg_path))[0]
    out = os.path.join(_cache_dir(cache_dir), f"{base}-{key}.png")
    if os.path.isfile(out):
        return out
    img = rasterise_uicon_svg(svg_path, px=px, ink=ink, force_ink=force_ink)
    img.save(out, "PNG")
    return out


# ---------------------------------------------------------------- path raster

_TOKEN = re.compile(
    r"([MmLlHhVvCcQqTtSsAaZz])|([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)


def _tokens(d):
    for m in _TOKEN.finditer(d):
        yield m.group(1) or m.group(2)


def _parse_path(d):
    """Yield subpaths as lists of (x, y) points (quadratic curves flattened)."""
    tokens = list(_tokens(d))
    i = 0
    cx = cy = 0.0
    sx = sy = 0.0
    points = []
    subpaths = []

    def flush():
        nonlocal points
        if len(points) >= 2:
            subpaths.append(points)
        points = []

    def take(n):
        nonlocal i
        vals = []
        for _ in range(n):
            if i >= len(tokens):
                break
            vals.append(float(tokens[i]))
            i += 1
        return vals

    while i < len(tokens):
        t = tokens[i]
        i += 1
        if t.isalpha():
            cmd = t
        else:
            # implicit repeat of previous command — push back
            i -= 1
            cmd = prev
        prev = cmd
        abs_cmd = cmd.upper()
        rel = cmd.islower()

        if abs_cmd == "M":
            flush()
            vals = take(2)
            if len(vals) < 2:
                break
            x, y = vals
            if rel:
                x, y = cx + x, cy + y
            cx, cy = x, y
            sx, sy = x, y
            points = [(x, y)]
            # subsequent pairs are implicit L
            prev = "l" if rel else "L"
            while i < len(tokens) and not str(tokens[i])[:1].isalpha():
                vals = take(2)
                if len(vals) < 2:
                    break
                x, y = vals
                if rel:
                    x, y = cx + x, cy + y
                cx, cy = x, y
                points.append((x, y))
        elif abs_cmd == "L":
            while True:
                vals = take(2)
                if len(vals) < 2:
                    break
                x, y = vals
                if rel:
                    x, y = cx + x, cy + y
                cx, cy = x, y
                points.append((x, y))
                if i >= len(tokens) or str(tokens[i])[:1].isalpha():
                    break
        elif abs_cmd == "H":
            vals = take(1)
            if not vals:
                break
            x = cx + vals[0] if rel else vals[0]
            cx = x
            points.append((cx, cy))
        elif abs_cmd == "V":
            vals = take(1)
            if not vals:
                break
            y = cy + vals[0] if rel else vals[0]
            cy = y
            points.append((cx, cy))
        elif abs_cmd == "Q":
            while True:
                vals = take(4)
                if len(vals) < 4:
                    break
                x1, y1, x, y = vals
                if rel:
                    x1, y1, x, y = cx + x1, cy + y1, cx + x, cy + y
                points.extend(_quad(cx, cy, x1, y1, x, y))
                cx, cy = x, y
                if i >= len(tokens) or str(tokens[i])[:1].isalpha():
                    break
        elif abs_cmd == "C":
            while True:
                vals = take(6)
                if len(vals) < 6:
                    break
                x1, y1, x2, y2, x, y = vals
                if rel:
                    x1, y1 = cx + x1, cy + y1
                    x2, y2 = cx + x2, cy + y2
                    x, y = cx + x, cy + y
                points.extend(_cubic(cx, cy, x1, y1, x2, y2, x, y))
                cx, cy = x, y
                if i >= len(tokens) or str(tokens[i])[:1].isalpha():
                    break
        elif abs_cmd == "Z":
            if points and (points[0] != points[-1]):
                points.append(points[0])
            cx, cy = sx, sy
            flush()
        else:
            # unsupported (A, S, T…) — skip one pair to avoid infinite loop
            take(2)
    flush()
    return subpaths


def _quad(x0, y0, x1, y1, x2, y2, steps=8):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u * u * x0 + 2 * u * t * x1 + t * t * x2,
                    u * u * y0 + 2 * u * t * y1 + t * t * y2))
    return out


def _cubic(x0, y0, x1, y1, x2, y2, x3, y3, steps=10):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((
            u * u * u * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
            u * u * u * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3,
        ))
    return out


def _evenodd_mask(subpaths, size, view):
    """Boolean mask size×size from path in viewBox coords (vx0,vy0,vw,vh)."""
    vx0, vy0, vw, vh = view
    mask = [[False] * size for _ in range(size)]
    # edge list for scanline
    scaled = []
    for sp in subpaths:
        pts = [((p[0] - vx0) / vw * (size - 1),
                (p[1] - vy0) / vh * (size - 1)) for p in sp]
        scaled.append(pts)

    for y in range(size):
        y_s = y + 0.5
        xs = []
        for pts in scaled:
            for i in range(len(pts) - 1):
                x0, y0 = pts[i]
                x1, y1 = pts[i + 1]
                if y0 == y1:
                    continue
                if y0 > y1:
                    x0, y0, x1, y1 = x1, y1, x0, y0
                if not (y0 <= y_s < y1):
                    continue
                t = (y_s - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
        xs.sort()
        row = mask[y]
        for i in range(0, len(xs) - 1, 2):
            a = max(0, min(size - 1, int(xs[i] + 0.5)))
            b = max(0, min(size - 1, int(xs[i + 1] + 0.5)))
            for x in range(a, b + 1):
                row[x] = True
    return mask


def rasterise_uicon_svg(svg_path, px=DEFAULT_PX, ink=DEFAULT_INK, force_ink=False):
    """Rasterise an SVG to a Pillow RGBA image.

    force_ink=True: ignore all explicit fill colours in the SVG and use `ink`
    for every path.  Use this for CSI duotone icons so they render flat and
    visually consistent with single-colour Uicons.
    """
    tree = ET.parse(svg_path)
    root = tree.getroot()
    # strip ns
    tag = root.tag.split("}")[-1]
    assert tag == "svg" or root.tag.endswith("svg")

    vb = root.get("viewBox")
    if vb:
        parts = [float(v) for v in vb.replace(",", " ").split()]
        view = (parts[0], parts[1], parts[2], parts[3])
    else:
        w = float(root.get("width", 300))
        h = float(root.get("height", 300))
        view = (0, 0, w, h)

    paths = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "path":
            d = el.get("d")
            if d:
                paths.append((d, el.get("fill")))
        elif tag == "polygon":
            pts = el.get("points")
            if not pts:
                continue
            nums = [float(x) for x in re.split(r"[\s,]+", pts.strip()) if x]
            if len(nums) < 6:
                continue
            pairs = list(zip(nums[0::2], nums[1::2]))
            d = "M " + " L ".join(f"{x},{y}" for x, y in pairs) + " Z"
            paths.append((d, el.get("fill")))

    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    pixels = img.load()
    for d, fill in paths:
        if not force_ink and fill and str(fill).lower() in ("none", "transparent"):
            continue
        if fill and str(fill).lower() in ("none", "transparent"):
            continue
        sub = _parse_path(d)
        mask = _evenodd_mask(sub, px, view)
        if not force_ink and isinstance(fill, str) and fill.startswith("#"):
            hexv = fill.lstrip("#")
            if len(hexv) == 3:
                hexv = "".join(c * 2 for c in hexv)
            color = (int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16), 255)
        else:
            color = ink
        for y in range(px):
            row = mask[y]
            for x in range(px):
                if row[x]:
                    pixels[x, y] = color
    return img
