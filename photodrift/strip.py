"""The scroll strip: all cards in one tall transparent PNG, plus a Kdenlive preset to move it.

Why: a Kdenlive title clip scrolls over its own fixed duration, so stretching
the clip on the timeline does not slow the cards down. An image clip moved by
the Transform effect (MLT qtblend) does follow the clip length: the preset
has two keyframes, at the first frame (0) and at the last frame (-1, which
MLT and Kdenlive resolve against the clip length), and Kdenlive moves the
last keyframe along when the clip end is dragged.

The strip is rendered from the same placements as the title clip, so card
moves made in Kdenlive's title editor end up in the strip on the next run.
"""

import json
import math
import os
import shutil

import numpy as np
from PIL import Image

from . import title as titlemod

STRIP_NAME = "photodrift-strip.png"
PRESET_COPY_NAME = "photodrift-transform-preset.json"
# Qt 6 refuses to load images larger than this (QImageReader allocation limit, 256 MB).
QT_IMAGE_LIMIT_BYTES = 256 * 1024 * 1024


def card_bounds(p):
    """(x0, y0, x1, y1) scene bounding box of a placed card image."""
    m = titlemod.transform_matrix(p.zoom, p.rotation)
    x, y = titlemod.center_to_pos(p.center, p.image_size, p.zoom, p.rotation)
    w, h = p.image_size
    pts = [titlemod.map_point(m, cx, cy) for cx, cy in ((0, 0), (w, 0), (0, h), (w, h))]
    xs = [x + px for px, _ in pts]
    ys = [y + py for _, py in pts]
    return min(xs), min(ys), max(xs), max(ys)


def strip_extent(placements):
    """Scene y range (top, bottom) covered by the cards, in whole pixels."""
    tops, bottoms = [], []
    for p in placements:
        _, y0, _, y1 = card_bounds(p)
        tops.append(y0)
        bottoms.append(y1)
    return int(math.floor(min(tops))), int(math.ceil(max(bottoms)))


def _draw_card(strip, card, p, top):
    """Draw one card into ``strip`` (RGBa, premultiplied) the way Qt draws the title item."""
    sw, sh = strip.size
    x0, y0, x1, y1 = card_bounds(p)
    px0, py0 = int(math.floor(x0)), int(math.floor(y0 - top))
    px1, py1 = int(math.ceil(x1)), int(math.ceil(y1 - top))
    # Clip to the strip.
    cx0, cy0 = max(px0, 0), max(py0, 0)
    cx1, cy1 = min(px1, sw), min(py1, sh)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    s = p.zoom / 100.0
    a = math.radians(p.rotation)
    cos, sin = math.cos(a), math.sin(a)
    posx, posy = titlemod.center_to_pos(p.center, p.image_size, p.zoom, p.rotation)
    # Output pixel (x, y) of the patch -> scene (cx0 + x, top + cy0 + y) -> card image coords.
    dx0 = cx0 - posx
    dy0 = top + cy0 - posy
    coeffs = (cos / s, sin / s, (dx0 * cos + dy0 * sin) / s,
              -sin / s, cos / s, (-dx0 * sin + dy0 * cos) / s)
    patch = card.transform((cx1 - cx0, cy1 - cy0), Image.AFFINE, coeffs, resample=Image.BICUBIC)
    # "Over" in premultiplied space.
    dst = np.asarray(strip.crop((cx0, cy0, cx1, cy1)), np.float32)
    src = np.asarray(patch, np.float32)
    out = src + dst * (1.0 - src[..., 3:4] / 255.0)
    strip.paste(Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGBa"), (cx0, cy0))


def render_strip(placements, frame_w, path):
    """Render all cards into one PNG. Returns (top, height) of the strip in scene coordinates."""
    top, bottom = strip_extent(placements)
    height = max(1, bottom - top)
    strip = Image.new("RGBa", (frame_w, height), (0, 0, 0, 0))
    cache = {}
    for p in sorted(placements, key=lambda q: q.z):
        card = cache.get(p.url)
        if card is None:
            card = Image.open(p.url).convert("RGBA").convert("RGBa")
            cache[p.url] = card
        _draw_card(strip, card, p, top)
    tmp = path + ".tmp.png"
    strip.convert("RGBA").save(tmp, compress_level=6)
    os.replace(tmp, path)
    return top, height


def transform_rect(frame_w, frame_h, strip_top, strip_h, travel):
    """Transform (qtblend) rect animation: the strip moves as the title viewport would.

    The title viewport moves from y=0 to y=travel, so a scene point at y appears at
    y - viewport. The strip's top edge is scene y = strip_top. Values are percentages
    of the frame size, so the preset also works when Kdenlive renders a scaled preview.
    """
    def pct(v, full):
        return ("%.6f" % (100.0 * v / full)).rstrip("0").rstrip(".") + "%"

    def rect(y):
        return "%s %s %s %s 1" % (pct(0, frame_w), pct(y, frame_h), pct(frame_w, frame_w), pct(strip_h, frame_h))

    return "0=%s;-1=%s" % (rect(strip_top), rect(strip_top - travel))


def preset_params(rect):
    """Parameters of the Transform effect preset, as Kdenlive stores them."""
    return [
        {"name": "rect", "value": rect},
        {"name": "distort", "value": "1"},
        {"name": "compositing", "value": "0"},
        {"name": "rotation", "value": "0"},
    ]


def default_kdenlive_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "kdenlive")


def write_kdenlive_preset(kdenlive_dir, preset_name, params):
    """Add or replace one preset in Kdenlive's Transform presets (effects/presets/qtblend.json).

    Other presets in the file are kept. A copy of the previous file is saved
    next to it as qtblend.json.bak. Returns the preset file path.
    """
    preset_dir = os.path.join(kdenlive_dir, "effects", "presets")
    os.makedirs(preset_dir, exist_ok=True)
    path = os.path.join(preset_dir, "qtblend.json")
    entries = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            data = json.loads(text) if text.strip() else []
        except ValueError:
            raise ValueError("cannot read %s (not JSON); move it away or use --no-kdenlive-preset" % path)
        if isinstance(data, dict):
            data = [{k: v} for k, v in data.items()]
        for entry in data:
            if isinstance(entry, dict):
                entry = {k: v for k, v in entry.items() if k != preset_name}
                if entry:
                    entries.append(entry)
        shutil.copy2(path, path + ".bak")
    entries.append({preset_name: params})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=4, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return path
