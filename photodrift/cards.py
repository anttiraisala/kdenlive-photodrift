"""Card rendering: turn a photo into a transparent RGBA "card" PNG.

A style is a function that takes a photo and returns an RGBA image plus
the geometry needed for placing the card (where the card centre is in
the PNG, since the PNG has padding around the card for the shadow).

The only style so far is ``instant``: an instant-camera print with a
warm white frame, a wide bottom border, a slight curl, gloss, a faint
bumpy surface and a soft drop shadow. Everything is computed with numpy
so that the only dependencies are Pillow and numpy.
"""

import math
import zlib
from dataclasses import dataclass, field, asdict, fields

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# EXIF orientation is handled by ImageOps.exif_transpose().


@dataclass
class InstantStyle:
    """Parameters for the ``instant`` style. Sizes are fractions of the card width."""

    border_side: float = 0.06
    border_top: float = 0.06
    border_bottom: float = 0.22
    # "4:5" (width:height), "1:1", any "W:H", or "native" (the photo's own aspect).
    aperture: str = "4:5"
    paper_color: tuple = (243, 239, 229)
    film: float = 0.6        # faded, warm, low-contrast look; 0 = untouched photo
    vignette: float = 0.35   # darkening of the photo corners (scaled by film)
    curl: float = 0.5        # how much the card bends; 0 = flat
    gloss: float = 0.5       # strength of the diagonal reflection
    gloss_angle: float = 30  # degrees from horizontal
    bump: float = 0.5        # surface unevenness; 0 = perfectly smooth
    shadow: float = 0.45     # drop shadow opacity; 0 = no shadow
    shadow_blur: float = 0.022
    shadow_offset: tuple = (0.010, 0.018)
    corner_radius: float = 0.006

    @classmethod
    def from_dict(cls, data):
        names = {f.name for f in fields(cls)}
        values = {k: v for k, v in (data or {}).items() if k in names}
        for key in ("paper_color", "shadow_offset"):
            if key in values:
                values[key] = tuple(values[key])
        return cls(**values)

    def to_dict(self):
        d = asdict(self)
        d["paper_color"] = list(self.paper_color)
        d["shadow_offset"] = list(self.shadow_offset)
        return d


STYLES = {"instant": InstantStyle}


@dataclass
class CardImage:
    image: Image.Image          # RGBA
    center: tuple               # (x, y) of the card centre inside the PNG, in PNG pixels
    card_size: tuple            # (w, h) of the card itself without padding, in PNG pixels
    meta: dict = field(default_factory=dict)


def card_seed(global_seed, card_id):
    """Stable per-card seed: same inputs give the same card, different cards differ."""
    return zlib.crc32(("%d:%s" % (global_seed, card_id)).encode("utf-8")) & 0xFFFFFFFF


def load_photo(path):
    """Open a photo, apply its EXIF orientation and return an RGB image."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(bg, img)
        img = img.convert("RGB")
    return img


def parse_aspect(aperture, photo_size):
    """Return aperture aspect as width/height."""
    if aperture == "native":
        w, h = photo_size
        return max(0.5, min(2.0, w / float(h)))
    if aperture == "square":
        return 1.0
    try:
        a, b = aperture.split(":")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        raise ValueError("invalid aperture %r (use e.g. 4:5, 1:1 or native)" % aperture)


def card_geometry(style, card_w, photo_size):
    """Return (card_w, card_h, aperture box (x0, y0, x1, y1)) in pixels."""
    bs = round(card_w * style.border_side)
    bt = round(card_w * style.border_top)
    bb = round(card_w * style.border_bottom)
    ap_w = card_w - 2 * bs
    ap_h = round(ap_w / parse_aspect(style.aperture, photo_size))
    card_h = bt + ap_h + bb
    return card_w, card_h, (bs, bt, bs + ap_w, bt + ap_h)


# --------------------------------------------------------------------------
# numpy helpers


def smooth_noise(shape, scale, rng):
    """Smooth value noise in [-1, 1]: random grid of ``scale`` pixel cells, bicubic upsampled."""
    h, w = shape
    gh, gw = max(2, int(math.ceil(h / scale)) + 3), max(2, int(math.ceil(w / scale)) + 3)
    grid = rng.uniform(-1.0, 1.0, (gh, gw)).astype(np.float32)
    big = Image.fromarray(grid, "F").resize((int(gw * scale), int(gh * scale)), Image.BICUBIC)
    arr = np.asarray(big, dtype=np.float32)
    oy, ox = int(scale), int(scale)
    return arr[oy:oy + h, ox:ox + w]


def fractal_noise(shape, base_scale, octaves, rng):
    out = np.zeros(shape, np.float32)
    amp, scale, total = 1.0, float(base_scale), 0.0
    for _ in range(octaves):
        out += amp * smooth_noise(shape, max(2.0, scale), rng)
        total += amp
        amp *= 0.5
        scale /= 2.0
    return out / total


def bilinear(img, x, y):
    """Sample ``img`` (H, W, C) at float coords with edge clamping."""
    h, w = img.shape[:2]
    x = np.clip(x, 0, w - 1.001)
    y = np.clip(y, 0, h - 1.001)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    a = img[y0, x0]
    b = img[y0, x0 + 1]
    c = img[y0 + 1, x0]
    d = img[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def rounded_rect_coverage(x, y, x0, y0, x1, y1, radius):
    """Anti-aliased coverage (0..1) of a rounded rectangle at float pixel coords."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hx, hy = (x1 - x0) / 2.0 - radius, (y1 - y0) / 2.0 - radius
    qx = np.abs(x - cx) - hx
    qy = np.abs(y - cy) - hy
    outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    inside = np.minimum(np.maximum(qx, qy), 0)
    dist = outside + inside - radius
    return np.clip(0.5 - dist, 0.0, 1.0)


def blur_float(arr, radius):
    """Gaussian blur of a float array in [0, 1] (via 16-bit-ish precision using two 8-bit planes)."""
    if radius <= 0:
        return arr
    img = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8), "L")
    return np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), np.float32) / 255.0


# --------------------------------------------------------------------------
# instant style


def film_tone(rgb, strength, vignette):
    """Faded, warm, low-contrast instant-film look. ``rgb`` is float (H, W, 3) in 0..1."""
    if strength <= 0 and vignette <= 0:
        return rgb
    f = strength
    lum = (rgb * np.array([0.299, 0.587, 0.114], np.float32)).sum(axis=2, keepdims=True)
    out = lum + (rgb - lum) * (1.0 - 0.22 * f)                 # less saturation
    out = 0.5 + (out - 0.5) * (1.0 - 0.20 * f)                 # less contrast
    lift = np.array([0.075, 0.065, 0.045], np.float32) * f     # warm, lifted blacks
    out = out * (1.0 - lift) + lift
    out = out * np.array([1.0 + 0.035 * f, 1.0 + 0.005 * f, 1.0 - 0.06 * f], np.float32)
    out = 1.0 - (1.0 - np.clip(out, 0, 1)) ** (1.0 + 0.12 * f)  # softer highlights
    if vignette > 0:
        h, w = rgb.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        u = (xx + 0.5) / w * 2 - 1
        v = (yy + 0.5) / h * 2 - 1
        r2 = (u * u + v * v) / 2.0
        out = out * (1.0 - vignette * max(f, 0.3) * 0.55 * r2 ** 1.5)[..., None]
    return np.clip(out, 0.0, 1.0)


def render_instant(photo, card_w, style, seed, focus=(0.5, 0.5)):
    """Render one instant-style card.

    photo   -- PIL RGB image (already EXIF-transposed)
    card_w  -- card width in output pixels (without padding)
    style   -- InstantStyle
    seed    -- int, per-card seed
    focus   -- (x, y) in 0..1: which part of the photo to keep when cropping
    """
    rng = np.random.default_rng(seed)
    card_w = int(round(card_w))
    cw, ch, (ax0, ay0, ax1, ay1) = card_geometry(style, card_w, photo.size)

    # ---- flat card ---------------------------------------------------------
    paper = np.array(style.paper_color, np.float32) / 255.0
    flat = np.empty((ch, cw, 3), np.float32)
    flat[:] = paper
    # Paper: faint low-frequency mottling and fine grain.
    mott = fractal_noise((ch, cw), cw * 0.25, 3, rng)
    grain = rng.standard_normal((ch, cw)).astype(np.float32)
    flat *= (1.0 + 0.012 * mott + 0.006 * grain)[..., None]

    ap_w, ap_h = ax1 - ax0, ay1 - ay0
    fitted = ImageOps.fit(photo, (ap_w, ap_h), Image.LANCZOS, centering=focus)
    pix = np.asarray(fitted, np.float32) / 255.0
    pix = film_tone(pix, style.film, style.vignette)
    # The print sits slightly under the frame: a thin dark line at the top and left edges.
    yy, xx = np.mgrid[0:ap_h, 0:ap_w].astype(np.float32)
    edge = np.exp(-yy / max(1.0, cw * 0.003)) * 0.18 + np.exp(-xx / max(1.0, cw * 0.003)) * 0.10
    edge += np.exp(-(ap_h - 1 - yy) / max(1.0, cw * 0.002)) * 0.05
    pix = pix * (1.0 - np.clip(edge, 0, 0.3))[..., None]
    flat[ay0:ay1, ax0:ax1] = pix
    photo_mask = np.zeros((ch, cw), np.float32)
    photo_mask[ay0:ay1, ax0:ax1] = 1.0

    # ---- surface: curl height field and bumps ------------------------------
    # Height z is in pixels, positive towards the viewer. Defined over the flat card.
    gy, gx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    u = (gx + 0.5) / cw * 2 - 1
    v = (gy + 0.5) / ch * 2 - 1
    a1, a2 = rng.uniform(0.6, 1.0), rng.uniform(0.0, 0.35)
    a3, c4 = rng.uniform(-0.25, 0.25), rng.uniform(0.3, 0.8)
    amp = style.curl * 0.028 * cw
    z_curl = amp * (a1 * u * u + a2 * v * v + a3 * u * v + c4 * (u * v) ** 2)

    bump_h = fractal_noise((ch, cw), cw * 0.10, 2, rng)
    bdy, bdx = np.gradient(bump_h)
    rms = float(np.sqrt((bdx ** 2 + bdy ** 2).mean())) or 1.0
    bump_slope = style.bump * 0.016 / rms

    cdy, cdx = np.gradient(z_curl)
    dzdx = cdx + bdx * bump_slope
    dzdy = cdy + bdy * bump_slope
    light = np.array([-0.35, -0.55, 1.0], np.float32)
    light /= np.linalg.norm(light)

    def lambert(dx, dy):
        n = np.stack([-dx, -dy, np.ones_like(dx)], axis=-1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        return (n @ light) / light[2]

    shade_all = lambert(dzdx, dzdy)
    shade_curl = lambert(cdx, cdy)
    shade_bump = shade_all / np.maximum(shade_curl, 1e-3)

    lit = flat * shade_all[..., None]

    # ---- gloss -------------------------------------------------------------
    if style.gloss > 0:
        th = math.radians(style.gloss_angle)
        # Coordinate across the reflection band (band runs along the angle).
        t = (-math.sin(th) * gx + math.cos(th) * gy) / math.hypot(cw, ch)
        t0 = rng.uniform(0.15, 0.55)
        width = rng.uniform(0.10, 0.16)
        band = np.exp(-((t - t0) / width) ** 2)
        band2 = 0.35 * np.exp(-((t - t0 - width * 1.8) / (width * 0.35)) ** 2)
        g = (band + band2) * style.gloss * 0.40
        # Bends with the curl and sparkles a little on the bumps.
        g *= np.clip(1.0 + 5.0 * (shade_curl - 1.0), 0.3, 2.0)
        g *= np.clip(1.0 + 12.0 * (shade_bump - 1.0), 0.0, 2.5)
        g *= 0.35 + 0.65 * photo_mask        # the print is glossier than the frame
        g = np.clip(g, 0.0, 0.9)[..., None]
        lit = 1.0 - (1.0 - lit) * (1.0 - g)  # screen blend

    lit = np.clip(lit, 0.0, 1.0)

    # ---- warp to output canvas ----------------------------------------------
    pad = int(math.ceil(cw * (0.05 + style.shadow_blur * 3 + max(style.shadow_offset))))
    ow, oh = cw + 2 * pad, ch + 2 * pad
    oy, ox = np.mgrid[0:oh, 0:ow].astype(np.float32)
    ox += 0.5
    oy += 0.5
    ccx, ccy = ow / 2.0, oh / 2.0
    dist = 5.0 * cw          # viewer distance; raised parts look slightly bigger

    def height_at(sx, sy):
        uu = sx / cw * 2 - 1
        vv = sy / ch * 2 - 1
        return amp * (a1 * uu * uu + a2 * vv * vv + a3 * uu * vv + c4 * (uu * vv) ** 2)

    # Inverse mapping by fixed-point iteration: output p = c + (s - c) * D / (D - z(s)).
    sx = ox - pad
    sy = oy - pad
    for _ in range(3):
        z = height_at(sx, sy)
        k = (dist - z) / dist
        sx = (ox - ccx) * k + cw / 2.0
        sy = (oy - ccy) * k + ch / 2.0
    radius = cw * style.corner_radius
    alpha = rounded_rect_coverage(sx, sy, 0, 0, cw, ch, radius)
    rgb = bilinear(lit, sx - 0.5, sy - 0.5)

    # ---- shadow -------------------------------------------------------------
    if style.shadow > 0:
        base_h = cw * 0.02
        z = height_at(sx, sy)
        lift = 1.0 + np.maximum(z, 0) / base_h
        offx = style.shadow_offset[0] * cw * lift
        offy = style.shadow_offset[1] * cw * lift
        shx, shy = sx - offx, sy - offy
        smask = rounded_rect_coverage(shx, shy, 0, 0, cw, ch, radius)
        smask = blur_float(smask, cw * style.shadow_blur)
        sa = smask * style.shadow
        out_a = alpha + sa * (1.0 - alpha)
        safe = np.maximum(out_a, 1e-6)[..., None]
        rgb = (rgb * alpha[..., None] + np.array([0.08, 0.06, 0.05], np.float32) * (sa * (1.0 - alpha))[..., None]) / safe
        alpha = out_a

    rgba = np.dstack([np.clip(rgb, 0, 1), np.clip(alpha, 0, 1)])
    img = Image.fromarray((rgba * 255.0 + 0.5).astype(np.uint8), "RGBA")
    return CardImage(image=img, center=(ow / 2.0, oh / 2.0), card_size=(cw, ch),
                     meta={"pad": pad})


def render_card(style_name, photo, card_w, style_params, seed, focus=(0.5, 0.5)):
    if style_name != "instant":
        raise ValueError("unknown style %r (available: %s)" % (style_name, ", ".join(sorted(STYLES))))
    style = InstantStyle.from_dict(style_params)
    return render_instant(photo, card_w, style, seed, focus)
