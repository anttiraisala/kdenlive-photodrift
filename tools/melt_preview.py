#!/usr/bin/env python3
"""Render a preview video of PhotoDrift output with MLT's melt, without Kdenlive.

The source is either the title clip (photodrift.kdenlivetitle, rendered with
MLT's own kdenlivetitle producer) or the strip (photodrift-strip.png, moved
with the Transform effect (qtblend) using the rect from
photodrift-transform-preset.json, as Kdenlive does). It is composited over a
solid colour or over a video file. With the strip, --frames sets the clip
length, and the scroll speed follows it.

Needs melt (sudo apt install melt) and an X11 display: MLT's Qt module
refuses to start without one. On a desktop this is already the case; on a
server use xvfb-run.

Usage:
    python3 tools/melt_preview.py photodrift/photodrift.kdenlivetitle preview.mp4
    python3 tools/melt_preview.py title.kdenlivetitle preview.mp4 --scale 0.5 --background clip.mp4
    python3 tools/melt_preview.py photodrift/photodrift-strip.png preview.mp4 --frames 1500
"""

import json

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction


def build_mlt(title_path, frames, width, height, fps, background, strip_rect=None):
    """MLT XML: background track + the title (or, with strip_rect, the strip PNG moved by qtblend)."""
    fr = Fraction(fps).limit_denominator(1001)
    root = ET.Element("mlt", {"LC_NUMERIC": "C"})
    ET.SubElement(root, "profile", {
        "width": str(width), "height": str(height),
        "frame_rate_num": str(fr.numerator), "frame_rate_den": str(fr.denominator),
        "progressive": "1", "sample_aspect_num": "1", "sample_aspect_den": "1",
        "display_aspect_num": str(width), "display_aspect_den": str(height), "colorspace": "709",
    })
    last = str(frames - 1)

    def producer(pid, service, resource, extra=None):
        p = ET.SubElement(root, "producer", {"id": pid, "in": "0", "out": last})
        props = {"mlt_service": service, "resource": resource}
        props.update(extra or {})
        for k, v in props.items():
            ET.SubElement(p, "property", {"name": k}).text = v

    if background and os.path.exists(background):
        producer("bg", "avformat", os.path.abspath(background))
    else:
        producer("bg", "color", background or "#2a5a7a")
    if strip_rect:
        producer("title", "qimage", os.path.abspath(title_path), {"length": str(frames)})
    else:
        producer("title", "kdenlivetitle", os.path.abspath(title_path))
    for i, pid in enumerate(("bg", "title")):
        pl = ET.SubElement(root, "playlist", {"id": "pl%d" % i})
        entry = ET.SubElement(pl, "entry", {"producer": pid, "in": "0", "out": last})
        if pid == "title" and strip_rect:
            flt = ET.SubElement(entry, "filter")
            for k, v in (("mlt_service", "qtblend"), ("rect", strip_rect), ("distort", "1")):
                ET.SubElement(flt, "property", {"name": k}).text = v
    tr = ET.SubElement(root, "tractor", {"id": "main", "in": "0", "out": last})
    mt = ET.SubElement(tr, "multitrack")
    ET.SubElement(mt, "track", {"producer": "pl0"})
    ET.SubElement(mt, "track", {"producer": "pl1"})
    t = ET.SubElement(tr, "transition", {"in": "0", "out": last})
    for k, v in (("mlt_service", "qtblend"), ("a_track", "0"), ("b_track", "1")):
        ET.SubElement(t, "property", {"name": k}).text = v
    return ET.tostring(root, encoding="unicode")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("title", help="photodrift.kdenlivetitle or photodrift-strip.png")
    p.add_argument("output", help="output video, e.g. preview.mp4")
    p.add_argument("--fps", type=float, default=25.0, help="frame rate (default 25)")
    p.add_argument("--scale", type=float, default=0.5, help="output size relative to the title (default 0.5)")
    p.add_argument("--background", default="#2a5a7a", help="colour (#rrggbb) or a video file")
    p.add_argument("--frames", type=int, help="number of frames (default: the title duration)")
    args = p.parse_args(argv)

    folder = os.path.dirname(os.path.abspath(args.title))
    strip_rect = None
    title_path = args.title
    if args.title.lower().endswith(".png"):
        with open(os.path.join(folder, "photodrift-transform-preset.json"), encoding="utf-8") as f:
            preset = json.load(f)[0]
        params = next(iter(preset.values()))
        strip_rect = next(p_["value"] for p_ in params if p_["name"] == "rect")
        title_path = os.path.join(folder, "photodrift.kdenlivetitle")
    root = ET.parse(title_path).getroot()
    tw, th = int(root.get("width", "1920")), int(root.get("height", "1080"))
    frames = args.frames or int(float(root.get("duration") or root.get("out") or 250))
    w = max(2, int(round(tw * args.scale / 2)) * 2)
    h = max(2, int(round(th * args.scale / 2)) * 2)

    with tempfile.NamedTemporaryFile("w", suffix=".mlt", delete=False) as f:
        f.write(build_mlt(args.title, frames, w, h, args.fps, args.background, strip_rect))
        mlt_path = f.name
    cmd = ["melt", "-silent", mlt_path, "-consumer", "avformat:" + args.output,
           "vcodec=libx264", "crf=18", "preset=veryfast", "pix_fmt=yuv420p", "an=1"]
    print("Rendering %d frames at %dx%d ..." % (frames, w, h))
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(mlt_path)
    errors = [ln for ln in (res.stdout + res.stderr).splitlines()
              if "X11" in ln or "rror" in ln]
    if res.returncode != 0 or not os.path.exists(args.output) or errors:
        sys.stderr.write("melt failed (exit %d)\n%s\n" % (res.returncode, "\n".join(errors) or res.stderr[-2000:]))
        return 1
    print("Wrote %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
