"""One PhotoDrift run: photos -> card PNGs -> Kdenlive title clip.

Output folder layout:

    <out>/cards/<name>-<hash>.png   card images
    <out>/photodrift.kdenlivetitle  the title clip (cards + scrolling)
    <out>/photodrift.json           settings and per-card state
    <out>/order.txt                 card order, editable
    <out>/backups/                  earlier versions of the title clip

Running again keeps what the user changed by hand in Kdenlive's title
editor (and saved to the title file): card moves, rotation, zoom and the
clip duration. Moves are kept as offsets from the automatic position, so
they survive changes in order, spacing and card size.
"""

import datetime
import hashlib
import json
import math
import os
import re
import shutil
import zlib
from dataclasses import dataclass, field, asdict, fields

from . import cards as cardmod
from . import layout as layoutmod
from . import ordering
from . import strip as stripmod
from . import title as titlemod

STATE_VERSION = 1
CARD_RENDER_VERSION = 1  # bump when the card look changes, to force re-rendering
TITLE_NAME = "photodrift.kdenlivetitle"
STATE_NAME = "photodrift.json"
ORDER_NAME = "order.txt"


@dataclass
class Settings:
    photos: str = ""
    frame_w: int = 1920
    frame_h: int = 1080
    fps: float = 25.0
    style: str = "instant"
    style_params: dict = field(default_factory=dict)
    card_width: float = 0.30      # fraction of frame width
    supersample: int = 1          # card PNG resolution multiplier (zoom 100/supersample in the title)
    layout: str = "alternate"
    spacing: float = 0.5          # fraction of frame height between card centres
    side_offset: float = 0.2
    jitter_x: float = 0.03
    jitter_y: float = 0.08
    tilt: float = 5.0
    seed: int = 1
    sort: str = "name"
    recursive: bool = False
    duration: float = None        # seconds; None = automatic from card_time
    card_time: float = 8.0        # automatic duration: seconds each card is visible
    strip: bool = True            # also write photodrift-strip.png (speed follows clip length)
    kdenlive_preset: bool = True  # write the Transform preset into Kdenlive's preset file
    kdenlive_dir: str = ""        # Kdenlive data folder; "" = ~/.local/share/kdenlive

    @classmethod
    def from_dict(cls, data):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})

    def to_dict(self):
        return asdict(self)


class PhotoDriftError(Exception):
    pass


def parse_time(text, fps):
    """Seconds from '90', '1:30', '0:01:30.5' or 'HH:MM:SS:FF' (frames)."""
    text = str(text).strip()
    parts = text.split(":")
    try:
        if len(parts) == 4:
            h, m, s, f = (float(p) for p in parts)
            return h * 3600 + m * 60 + s + f / fps
        total = 0.0
        for p in parts:
            total = total * 60 + float(p)
        return total
    except ValueError:
        raise PhotoDriftError("cannot read time %r (use e.g. 75, 1:15, 0:01:15.5 or 00:01:15:12)" % text)


def slug(name):
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return s[:40] or "photo"


def card_filename(rel_path):
    stem = os.path.splitext(os.path.basename(rel_path))[0]
    return "%s-%08x.png" % (slug(stem), zlib.crc32(rel_path.encode("utf-8")) & 0xFFFFFFFF)


def load_state(out_dir):
    path = os.path.join(out_dir, STATE_NAME)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def render_key(settings, rel_path, photo_path, card_px, seed, focus):
    st = os.stat(photo_path)
    payload = {
        "v": CARD_RENDER_VERSION, "photo": rel_path, "size": st.st_size, "mtime": st.st_mtime_ns,
        "style": settings.style, "params": settings.style_params, "px": card_px,
        "seed": seed, "focus": list(focus),
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def run(settings, out_dir, reset_order=False, reset_positions=False, duration_given=False, log=print):
    """Do one run. Returns a summary dict.

    duration_given -- the duration (or --auto-duration) was given on the command line this time;
                      it then wins over a duration changed in Kdenlive's title editor.
    """
    if not settings.photos or not os.path.isdir(settings.photos):
        raise PhotoDriftError("photo folder not found: %r" % settings.photos)
    out_dir = os.path.abspath(out_dir)
    cards_dir = os.path.join(out_dir, "cards")
    os.makedirs(cards_dir, exist_ok=True)
    title_path = os.path.join(out_dir, TITLE_NAME)

    old_state = load_state(out_dir) or {}
    old_cards = old_state.get("cards", {})

    # ---- order ------------------------------------------------------------
    order, excluded, added, dropped = ordering.resolve_order(
        settings.photos, os.path.join(out_dir, ORDER_NAME), settings.sort, settings.recursive, reset_order)
    if not order:
        raise PhotoDriftError("no photos to use in %s (check order.txt)" % settings.photos)

    # ---- cards ------------------------------------------------------------
    W, H = settings.frame_w, settings.frame_h
    ss = max(1, int(settings.supersample))
    zoom = 100.0 / ss
    card_px = int(round(settings.card_width * W * ss))
    new_cards = {}
    infos = []
    rendered = 0
    for rel in order:
        photo_path = os.path.join(settings.photos, rel)
        prev = old_cards.get(rel, {})
        seed = cardmod.card_seed(settings.seed, rel)
        focus = tuple(prev.get("focus", (0.5, 0.5)))
        fname = card_filename(rel)
        png_path = os.path.join(cards_dir, fname)
        key = render_key(settings, rel, photo_path, card_px, seed, focus)
        if prev.get("render_key") == key and os.path.exists(png_path) and prev.get("png_size"):
            png_size = tuple(prev["png_size"])
            card_size = tuple(prev["card_size"])
        else:
            photo = cardmod.load_photo(photo_path)
            card = cardmod.render_card(settings.style, photo, card_px, settings.style_params, seed, focus)
            card.image.save(png_path, optimize=False)
            png_size, card_size = card.image.size, card.card_size
            rendered += 1
        entry = {
            "file": "cards/" + fname,
            "seed": seed,
            "focus": list(focus),
            "render_key": key,
            "png_size": list(png_size),
            "card_size": list(card_size),
        }
        new_cards[rel] = entry
        infos.append({
            "rel": rel, "seed": seed, "png_path": png_path,
            "png_w": png_size[0] / ss, "png_h": png_size[1] / ss,
            "card_w": card_size[0] / ss, "card_h": card_size[1] / ss,
        })

    # ---- automatic layout -------------------------------------------------
    auto = layoutmod.auto_layout(
        infos, W, H, settings.layout, settings.spacing, settings.side_offset,
        settings.jitter_x, settings.jitter_y, settings.tilt)

    # ---- manual changes from the existing title ----------------------------
    old_title = None
    if os.path.exists(title_path):
        try:
            old_title = titlemod.read_title(title_path)
        except Exception as e:  # noqa: BLE001 - report and carry on with a fresh layout
            log("warning: could not read the existing title (%s); using a fresh layout" % e)
    by_basename = {}
    if old_title and not reset_positions:
        for item in old_title.pixmaps:
            by_basename[item.basename] = item

    placements = []
    kept_manual = 0
    other_items = []
    for z, (info, a) in enumerate(zip(infos, auto), start=1):
        rel = info["rel"]
        entry = new_cards[rel]
        prev = old_cards.get(rel, {})
        cx, cy, rot, zm = a["cx"], a["cy"], a["rotation"], zoom
        item = by_basename.get(os.path.basename(entry["file"]))
        if item is not None:
            # Old PNG size: the item position refers to the image that was in the title then.
            old_png = prev.get("written", {}).get("png_size") or entry["png_size"]
            actual_center = titlemod.pos_to_center(item.pos, old_png, item.matrix)
            actual_zoom, actual_rot = titlemod.matrix_zoom_rotation(item.matrix)
            written = prev.get("written")
            changed = False
            if written:
                dx = actual_center[0] - written["center"][0]
                dy = actual_center[1] - written["center"][1]
                if abs(dx) > 0.5 or abs(dy) > 0.5:
                    cx, cy = cx + dx, cy + dy
                    changed = True
                if abs(actual_rot - written["rotation"]) > 0.05:
                    rot = actual_rot
                    changed = True
                zoom_ratio = actual_zoom / written["zoom"] if written["zoom"] else 1.0
                if abs(zoom_ratio - 1.0) > 0.005:
                    zm = zoom * zoom_ratio
                    changed = True
            else:
                # No record of what we wrote: keep the card exactly as it is.
                cx, cy = actual_center
                rot, zm = actual_rot, actual_zoom
                changed = True
            if changed:
                kept_manual += 1
        placements.append(titlemod.CardPlacement(
            url=info["png_path"], image_size=tuple(entry["png_size"]), center=(cx, cy),
            zoom=zm, rotation=rot, z=z))
        entry["auto"] = {"center": [a["cx"], a["cy"]], "rotation": a["rotation"]}
        entry["written"] = {"center": [cx, cy], "rotation": rot, "zoom": zm,
                            "png_size": entry["png_size"]}
    if old_title:
        other_items = old_title.other_items
        # Image items that are not PhotoDrift cards (added by the user) are kept too.
        for item in old_title.pixmaps:
            item_dir = os.path.dirname(os.path.abspath(os.path.join(out_dir, item.url)))
            if item_dir != cards_dir:
                other_items.append(_pixmap_element(item))

    # ---- viewport and duration --------------------------------------------
    bottom = 0.0
    for p in placements:
        bottom = max(bottom, p.center[1] + layoutmod.rotated_half_height(p.image_size, p.zoom, p.rotation))
    travel = max(1.0, bottom)
    start_vp = (0, 0, W, H)
    end_vp = (0, math.ceil(travel), W, H)

    fps = float(settings.fps)
    written_frames = old_state.get("written_duration")
    kdenlive_changed = (old_title is not None and old_title.duration and written_frames
                        and old_title.duration != written_frames)
    if kdenlive_changed and not duration_given:
        frames = old_title.duration
        settings.duration = frames / fps   # from now on this is the chosen duration
        duration_source = "kept from Kdenlive"
    elif settings.duration:
        frames = int(round(settings.duration * fps))
        duration_source = "set"
    else:
        # Speed such that a card of average height crosses the frame in card_time seconds.
        avg_png_h = sum(i["png_h"] for i in infos) / len(infos)
        speed = (H + avg_png_h) / (settings.card_time * fps)
        frames = int(round(travel / speed))
        duration_source = "automatic, --card-time %g" % settings.card_time
    frames = max(1, frames)

    # ---- write ------------------------------------------------------------
    text = titlemod.build_title_xml(W, H, frames, placements, start_vp, end_vp, other_items)
    backup = None
    if os.path.exists(title_path):
        with open(title_path, encoding="utf-8") as f:
            old_text = f.read()
        if old_text != text:
            bdir = os.path.join(out_dir, "backups")
            os.makedirs(bdir, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = os.path.join(bdir, "photodrift-%s.kdenlivetitle" % stamp)
            n = 1
            while os.path.exists(backup):
                n += 1
                backup = os.path.join(bdir, "photodrift-%s-%d.kdenlivetitle" % (stamp, n))
            shutil.copy2(title_path, backup)
    tmp = title_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, title_path)

    # ---- strip and Transform preset ---------------------------------------
    strip_info = None
    if settings.strip:
        strip_path = os.path.join(out_dir, stripmod.STRIP_NAME)
        strip_top, strip_h = stripmod.render_strip(placements, W, strip_path)
        rect = stripmod.transform_rect(W, H, strip_top, strip_h, math.ceil(travel))
        params = stripmod.preset_params(rect)
        preset_name = "PhotoDrift " + os.path.basename(out_dir)
        save_json(os.path.join(out_dir, stripmod.PRESET_COPY_NAME), [{preset_name: params}])
        preset_file = None
        if settings.kdenlive_preset:
            preset_file = stripmod.write_kdenlive_preset(
                settings.kdenlive_dir or stripmod.default_kdenlive_dir(), preset_name, params)
        strip_info = {
            "path": strip_path, "size": (W, strip_h), "rect": rect, "preset_name": preset_name,
            "preset_file": preset_file,
            "rect_changed": bool(old_state.get("strip_rect")) and rect != old_state.get("strip_rect"),
            "too_big": W * strip_h * 4 > stripmod.QT_IMAGE_LIMIT_BYTES,
            "other_items": len(other_items),
        }

    # Remove card images of photos that are no longer used.
    removed = 0
    keep = {e["file"] for e in new_cards.values()}
    for rel, e in old_cards.items():
        f = e.get("file")
        if f and f not in keep:
            path = os.path.join(out_dir, f)
            if os.path.exists(path):
                os.remove(path)
                removed += 1

    state = {
        "version": STATE_VERSION,
        "settings": settings.to_dict(),
        "written_duration": frames,
        "strip_rect": strip_info["rect"] if strip_info else None,
        "cards": new_cards,
    }
    save_json(os.path.join(out_dir, STATE_NAME), state)

    seconds = frames / fps
    speed = travel / frames
    visible = (H + sum(i["png_h"] for i in infos) / len(infos)) / speed / fps
    summary = {
        "title": title_path, "cards": len(order), "excluded": excluded, "added": added,
        "dropped": dropped, "rendered": rendered, "removed": removed, "kept_manual": kept_manual,
        "frames": frames, "seconds": seconds, "duration_source": duration_source,
        "travel_px": travel, "px_per_frame": speed, "card_visible_s": visible, "backup": backup,
        "strip": strip_info,
    }
    return summary


def _pixmap_element(item):
    import xml.etree.ElementTree as ET
    el = ET.Element("item", {"type": "QGraphicsPixmapItem", "z-index": str(item.z)})
    pos = ET.SubElement(el, "position", {"x": titlemod.fmt(item.pos[0]), "y": titlemod.fmt(item.pos[1])})
    m11, m12, m21, m22 = item.matrix
    tr = ET.SubElement(pos, "transform")
    tr.text = ",".join(titlemod.fmt(v) for v in (m11, m12, 0, m21, m22, 0, 0, 0, 1))
    ET.SubElement(el, "content", {"url": item.url})
    return el
