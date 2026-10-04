#!/usr/bin/env python3
"""Generate synthetic test photos for PhotoDrift.

The photos are simple painted landscapes (sky, sun, hills, a few shapes)
with a big number in the corner, so that the order of the cards is easy
to follow in a rendered video. Orientation is mixed: landscape, portrait
and square. A few photos carry an EXIF orientation tag so that the
EXIF rotation handling gets exercised, and every photo has an EXIF
DateTimeOriginal so that date sorting can be tested.

Usage:
    python3 tools/make_test_photos.py --out test-photos --count 20 --seed 1
"""

import argparse
import datetime
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PALETTES = [
    # sky top, sky bottom, hill near, hill far, sun
    ((40, 90, 170), (170, 210, 240), (60, 120, 50), (110, 150, 120), (255, 240, 180)),
    ((250, 120, 60), (255, 210, 150), (90, 60, 50), (150, 100, 90), (255, 250, 220)),
    ((20, 30, 70), (90, 70, 140), (30, 40, 40), (60, 60, 90), (240, 240, 255)),
    ((120, 180, 220), (230, 240, 245), (200, 190, 150), (170, 170, 160), (255, 255, 230)),
    ((70, 130, 120), (200, 230, 210), (40, 90, 60), (90, 140, 110), (255, 245, 200)),
    ((150, 70, 120), (250, 170, 140), (70, 40, 60), (120, 80, 100), (255, 230, 200)),
]

SIZES = [(3000, 2000), (2000, 3000), (2400, 2400), (3200, 1800), (1800, 2700), (2600, 1950)]

EXIF_ORIENTATION = 0x0112
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132


def find_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def hill_profile(width, base, amplitude, rng):
    xs = np.arange(width, dtype=np.float64)
    y = np.full(width, float(base))
    for _ in range(3):
        freq = rng.uniform(0.5, 3.0) * 2 * math.pi / width
        phase = rng.uniform(0, 2 * math.pi)
        y += amplitude * rng.uniform(0.3, 1.0) * np.sin(xs * freq + phase)
    return y


def paint_photo(index, size, rng):
    w, h = size
    sky_top, sky_bottom, hill_near, hill_far, sun = PALETTES[index % len(PALETTES)]
    yy = np.linspace(0.0, 1.0, h)[:, None, None]
    sky = np.array(sky_top, float) * (1 - yy) + np.array(sky_bottom, float) * yy
    img = np.broadcast_to(sky, (h, w, 3)).copy()

    # Sun with a soft glow.
    cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.15, 0.4) * h
    r = rng.uniform(0.05, 0.09) * min(w, h)
    ys, xs = np.mgrid[0:h, 0:w]
    d = np.hypot(xs - cx, ys - cy)
    glow = np.clip(1.0 - (d - r) / (r * 4), 0, 1) ** 2 * 0.5
    disc = np.clip(r - d + 1.5, 0, 1)
    a = np.maximum(glow, disc)[..., None]
    img = img * (1 - a) + np.array(sun, float) * a

    # Two layers of hills.
    for color, base, amp in ((hill_far, 0.62, 0.06), (hill_near, 0.75, 0.05)):
        profile = hill_profile(w, base * h, amp * h, rng)
        mask = (ys >= profile[None, :]).astype(np.float64)[..., None]
        shade = 1.0 - 0.25 * ((ys - profile[None, :]) / h).clip(0, 1)[..., None]
        img = img * (1 - mask) + np.array(color, float) * shade * mask

    # Mild grain so that the image is not perfectly flat.
    img += rng_normal(rng, (h, w, 1)) * 3.0
    pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")

    draw = ImageDraw.Draw(pil)
    # A few simple objects: trees or houses.
    for _ in range(rng.randint(2, 5)):
        tx = rng.uniform(0.05, 0.95) * w
        ty = rng.uniform(0.78, 0.92) * h
        s = rng.uniform(0.04, 0.09) * min(w, h)
        if rng.random() < 0.6:
            draw.rectangle([tx - s * 0.08, ty - s * 0.2, tx + s * 0.08, ty + s * 0.4], fill=(70, 50, 35))
            draw.polygon([(tx, ty - s * 1.4), (tx - s * 0.5, ty), (tx + s * 0.5, ty)], fill=(30, 80, 40))
        else:
            draw.rectangle([tx - s * 0.5, ty - s * 0.5, tx + s * 0.5, ty + s * 0.3], fill=(200, 60, 50))
            draw.polygon([(tx - s * 0.65, ty - s * 0.5), (tx, ty - s * 1.0), (tx + s * 0.65, ty - s * 0.5)],
                         fill=(90, 50, 40))
            draw.rectangle([tx - s * 0.12, ty - s * 0.1, tx + s * 0.12, ty + s * 0.3], fill=(250, 230, 160))

    # Big number for following the order, and an orientation arrow.
    font = find_font(int(min(w, h) * 0.16))
    label = "%02d" % (index + 1)
    m = int(min(w, h) * 0.04)
    # Centred, so that the number survives any centre crop.
    draw.text((w // 2 + 6, h // 2 + 6), label, font=font, fill=(0, 0, 0), anchor="mm")
    draw.text((w // 2, h // 2), label, font=font, fill=(255, 255, 255), anchor="mm")
    small = find_font(int(min(w, h) * 0.035))
    draw.text((w - m, m), "UP %dx%d" % (w, h), font=small, fill=(255, 255, 255), anchor="ra")
    return pil


def rng_normal(rng, shape):
    seed = rng.randrange(2 ** 32)
    return np.random.default_rng(seed).standard_normal(shape)


def save_photo(pil, path, orientation, when):
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = orientation
    stamp = when.strftime("%Y:%m:%d %H:%M:%S")
    exif[EXIF_DATETIME] = stamp
    exif[EXIF_IFD] = {EXIF_DATETIME_ORIGINAL: stamp}
    pil.save(path, "JPEG", quality=90, exif=exif)


def store_with_orientation(pil, orientation):
    """Return pixels as a camera would store them for the given EXIF tag.

    The tag tells a viewer how to rotate the stored pixels for display;
    here we do the inverse so that the photo looks upright when the tag
    is honoured (and sideways when it is not).
    """
    if orientation == 6:  # display = stored rotated 90 degrees clockwise
        return pil.transpose(Image.Transpose.ROTATE_90)
    if orientation == 8:  # display = stored rotated 90 degrees counter-clockwise
        return pil.transpose(Image.Transpose.ROTATE_270)
    if orientation == 3:
        return pil.transpose(Image.Transpose.ROTATE_180)
    return pil


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="output folder")
    parser.add_argument("--count", type=int, default=20, help="number of photos (default 20)")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="size multiplier; 0.25 makes small photos for fast tests")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    start = datetime.datetime(2025, 6, 1, 10, 0, 0)
    for i in range(args.count):
        w, h = SIZES[rng.randrange(len(SIZES))]
        w, h = max(64, int(w * args.scale)), max(64, int(h * args.scale))
        pil = paint_photo(i, (w, h), rng)
        # Every fifth photo is stored sideways with an EXIF orientation tag.
        orientation = (6, 8)[(i // 5) % 2] if i % 5 == 3 else 1
        stored = store_with_orientation(pil, orientation)
        # Dates go backwards for a few photos so that name order != date order.
        when = start + datetime.timedelta(days=i * 2 - (5 if i % 7 == 6 else 0), minutes=rng.randrange(600))
        path = os.path.join(args.out, "IMG_%04d.jpg" % (i + 1))
        save_photo(stored, path, orientation, when)
        print("wrote %s (%dx%d, orientation %d)" % (path, w, h, orientation))
    return 0


if __name__ == "__main__":
    sys.exit(main())
