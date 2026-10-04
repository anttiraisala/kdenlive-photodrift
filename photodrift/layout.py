"""Automatic card layout: where each card starts before any manual moves.

Coordinates are title (scene) pixels. The visible frame is (0, 0, W, H).
Cards are stacked below the frame; the viewport moves down from the frame
to below the last card, so on screen the cards rise from the bottom edge
and leave through the top edge.
"""

import math
import random

LAYOUTS = ("alternate", "center", "random")


def rotated_half_height(size, zoom, rotation):
    """Half height of the bounding box of a ``size`` image scaled by zoom % and rotated."""
    w, h = size[0] * zoom / 100.0, size[1] * zoom / 100.0
    a = math.radians(rotation)
    return (abs(w * math.sin(a)) + abs(h * math.cos(a))) / 2.0


def auto_layout(cards, frame_w, frame_h, layout="alternate", spacing=0.5, side_offset=0.2,
                jitter_x=0.03, jitter_y=0.08, tilt=5.0):
    """Return one dict per card: {"cx", "cy", "rotation"}.

    cards  -- list of dicts with "card_w", "card_h" (card size on screen, px),
              "png_w", "png_h" (padded PNG size on screen, px) and "seed".
    spacing -- vertical distance between consecutive card centres, as a fraction of frame height.
    side_offset -- for "alternate": distance of the card centre from the frame centre, fraction of width.
    jitter_x, jitter_y -- random displacement, fractions of frame width / of the spacing.
    tilt   -- maximum random rotation in degrees (each card gets a value in -tilt..tilt).
    """
    if layout not in LAYOUTS:
        raise ValueError("unknown layout %r (use %s)" % (layout, ", ".join(LAYOUTS)))
    out = []
    step = spacing * frame_h
    y = None
    for i, card in enumerate(cards):
        rng = random.Random(card["seed"])
        rotation = rng.uniform(-tilt, tilt) if tilt else 0.0
        ext = rotated_half_height((card["png_w"], card["png_h"]), 100.0, rotation)
        if layout == "center":
            cx = frame_w / 2.0
        elif layout == "alternate":
            side = -1 if i % 2 == 0 else 1
            cx = frame_w / 2.0 + side * side_offset * frame_w
        else:
            half = card["card_w"] / 2.0
            lo, hi = half + 0.03 * frame_w, frame_w - half - 0.03 * frame_w
            cx = rng.uniform(lo, hi) if hi > lo else frame_w / 2.0
        if layout != "random":
            cx += rng.uniform(-1, 1) * jitter_x * frame_w
        if y is None:
            # The first card starts just below the bottom edge of the frame.
            y = frame_h + ext
            cy = y
        else:
            y += step
            cy = y + rng.uniform(-1, 1) * jitter_y * step
        out.append({"cx": cx, "cy": cy, "rotation": rotation})
    return out
