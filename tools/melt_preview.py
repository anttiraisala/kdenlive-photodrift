#!/usr/bin/env python3
"""Render a preview video of a PhotoDrift title with MLT's melt, without Kdenlive.

The title is composited over a solid colour or over a video file, the same
way Kdenlive does it, using MLT's own kdenlivetitle producer. Useful for
checking the cards and the scrolling quickly, and for automated tests.

Needs melt (sudo apt install melt) and an X11 display: MLT's Qt module
refuses to start without one. On a desktop this is already the case; on a
server use xvfb-run.

Usage:
    python3 tools/melt_preview.py photodrift/photodrift.kdenlivetitle preview.mp4
    python3 tools/melt_preview.py title.kdenlivetitle preview.mp4 --scale 0.5 --background clip.mp4
"""

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction


def build_mlt(title_path, frames, width, height, fps, background):
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
    producer("title", "kdenlivetitle", os.path.abspath(title_path))
    for i, pid in enumerate(("bg", "title")):
        pl = ET.SubElement(root, "playlist", {"id": "pl%d" % i})
        ET.SubElement(pl, "entry", {"producer": pid, "in": "0", "out": last})
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
    p.add_argument("title", help=".kdenlivetitle file")
    p.add_argument("output", help="output video, e.g. preview.mp4")
    p.add_argument("--fps", type=float, default=25.0, help="frame rate (default 25)")
    p.add_argument("--scale", type=float, default=0.5, help="output size relative to the title (default 0.5)")
    p.add_argument("--background", default="#2a5a7a", help="colour (#rrggbb) or a video file")
    p.add_argument("--frames", type=int, help="number of frames (default: the title duration)")
    args = p.parse_args(argv)

    root = ET.parse(args.title).getroot()
    tw, th = int(root.get("width", "1920")), int(root.get("height", "1080"))
    frames = args.frames or int(float(root.get("duration") or root.get("out") or 250))
    w = max(2, int(round(tw * args.scale / 2)) * 2)
    h = max(2, int(round(th * args.scale / 2)) * 2)

    with tempfile.NamedTemporaryFile("w", suffix=".mlt", delete=False) as f:
        f.write(build_mlt(args.title, frames, w, h, args.fps, args.background))
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
