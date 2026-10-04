"""Command line interface for PhotoDrift."""

import argparse
import os
import sys

from . import project
from .cards import InstantStyle, parse_aspect
from .layout import LAYOUTS

DESCRIPTION = """\
PhotoDrift: photos drift up over a video in Kdenlive.

Turns each photo into an instant-print style card (PNG with transparency)
and writes a Kdenlive title clip (photodrift.kdenlivetitle) in which the
cards scroll from the bottom of the frame to the top.

Settings are remembered in <out>/photodrift.json: when you run again, only
give the options you want to change.
"""

EPILOG = """\
examples:
  photodrift.py --photos ~/Pictures/summer --out ~/Videos/project/photodrift
  photodrift.py --out ~/Videos/project/photodrift --start 1:10 --end 2:05
  photodrift.py --out ~/Videos/project/photodrift --layout center --tilt 3

card order: edit <out>/order.txt and run again.
"""

STYLE_OPTIONS = [
    # (option, field, type, help)
    ("--aperture", "aperture", str, "photo opening shape: 4:5 (default), 1:1, any W:H, or native"),
    ("--film", "film", float, "faded warm film look, 0..1 (default 0.6)"),
    ("--vignette", "vignette", float, "dark photo corners, 0..1 (default 0.35)"),
    ("--curl", "curl", float, "card curl, 0..1 (default 0.5)"),
    ("--gloss", "gloss", float, "gloss reflection, 0..1 (default 0.5)"),
    ("--gloss-angle", "gloss_angle", float, "gloss angle in degrees (default 30)"),
    ("--bump", "bump", float, "uneven surface, 0..1 (default 0.5)"),
    ("--shadow", "shadow", float, "drop shadow opacity, 0..1 (default 0.45)"),
]


def build_parser():
    p = argparse.ArgumentParser(prog="photodrift.py", description=DESCRIPTION, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="output folder (created if missing)")
    p.add_argument("--photos", help="folder with the photos (remembered)")
    p.add_argument("--recursive", action="store_true", default=None, help="also use photos in subfolders")
    p.add_argument("--no-recursive", dest="recursive", action="store_false", help="only the photo folder itself")
    p.add_argument("--sort", choices=["name", "date", "mtime"],
                   help="order of new photos: name (default), date (EXIF), mtime (file time)")
    p.add_argument("--reset-order", action="store_true", help="forget order.txt and sort all photos again")

    g = p.add_argument_group("video")
    g.add_argument("--size", help="project frame size, e.g. 1920x1080 (default) or 1080x1920")
    g.add_argument("--fps", type=float, help="project frame rate (default 25)")
    g.add_argument("--start", help="where the clip starts in your video, e.g. 1:10 or 00:01:10:05")
    g.add_argument("--end", help="where the clip ends in your video; with --start sets the duration")
    g.add_argument("--duration", help="clip duration (seconds or M:SS); the scroll speed follows from it")
    g.add_argument("--auto-duration", action="store_true",
                   help="forget a set duration; compute it from --card-time")
    g.add_argument("--card-time", type=float,
                   help="automatic duration: seconds each card is visible (default 8)")

    g = p.add_argument_group("strip (speed follows the clip length in Kdenlive)")
    g.add_argument("--strip", dest="strip", action="store_true", default=None,
                   help="write photodrift-strip.png and the Transform preset (default)")
    g.add_argument("--no-strip", dest="strip", action="store_false", help="only write the title clip")
    g.add_argument("--kdenlive-preset", dest="kdenlive_preset", action="store_true", default=None,
                   help="add the preset to Kdenlive's Transform presets (default)")
    g.add_argument("--no-kdenlive-preset", dest="kdenlive_preset", action="store_false",
                   help="do not touch Kdenlive's preset file")
    g.add_argument("--kdenlive-dir", help="Kdenlive data folder (default ~/.local/share/kdenlive)")

    g = p.add_argument_group("layout")
    g.add_argument("--card-width", type=float, help="card width as a fraction of frame width (default 0.30)")
    g.add_argument("--layout", choices=LAYOUTS, help="alternate (default), center or random")
    g.add_argument("--spacing", type=float,
                   help="vertical distance between cards as a fraction of frame height (default 0.5)")
    g.add_argument("--side-offset", type=float,
                   help="alternate layout: distance from centre as a fraction of width (default 0.2)")
    g.add_argument("--jitter-x", type=float, help="random sideways shift, fraction of width (default 0.03)")
    g.add_argument("--jitter-y", type=float, help="random vertical shift, fraction of spacing (default 0.08)")
    g.add_argument("--tilt", type=float, help="maximum random tilt in degrees (default 5)")
    g.add_argument("--seed", type=int, help="random seed: same seed, same cards and layout (default 1)")
    g.add_argument("--reset-positions", action="store_true",
                   help="forget card moves made in Kdenlive and use the automatic layout")

    g = p.add_argument_group("card style")
    g.add_argument("--style", choices=["instant"], help="card style (default instant)")
    g.add_argument("--supersample", type=int, choices=[1, 2],
                   help="card image resolution: 1 = exact size (default), 2 = double, scaled 50%% in the title")
    for opt, _, typ, hlp in STYLE_OPTIONS:
        g.add_argument(opt, type=typ, help=hlp)
    return p


def merge_settings(args, stored):
    s = project.Settings.from_dict(stored or {})
    if args.photos:
        s.photos = os.path.abspath(os.path.expanduser(args.photos))
    if args.recursive is not None:
        s.recursive = args.recursive
    if args.sort:
        s.sort = args.sort
    if args.size:
        try:
            w, h = args.size.lower().split("x")
            s.frame_w, s.frame_h = int(w), int(h)
        except ValueError:
            raise project.PhotoDriftError("bad --size %r (use e.g. 1920x1080)" % args.size)
    if args.fps:
        s.fps = args.fps
    if args.strip is not None:
        s.strip = args.strip
    if args.kdenlive_preset is not None:
        s.kdenlive_preset = args.kdenlive_preset
    if args.kdenlive_dir:
        s.kdenlive_dir = os.path.abspath(os.path.expanduser(args.kdenlive_dir))
    for name in ("card_width", "layout", "spacing", "side_offset", "jitter_x", "jitter_y", "tilt",
                 "seed", "style", "supersample", "card_time"):
        v = getattr(args, name)
        if v is not None:
            setattr(s, name, v)
    params = dict(s.style_params)
    for _, fieldname, _, _ in STYLE_OPTIONS:
        v = getattr(args, fieldname)
        if v is not None:
            params[fieldname] = v
    if "aperture" in params:
        parse_aspect(params["aperture"], (1, 1))  # validate early
    s.style_params = params
    InstantStyle.from_dict(params)

    if args.auto_duration:
        s.duration = None
    if args.duration:
        s.duration = project.parse_time(args.duration, s.fps)
    if args.start or args.end:
        if not (args.start and args.end):
            raise project.PhotoDriftError("give both --start and --end")
        start = project.parse_time(args.start, s.fps)
        end = project.parse_time(args.end, s.fps)
        if end <= start:
            raise project.PhotoDriftError("--end must be after --start")
        s.duration = end - start
    return s


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    try:
        stored = (project.load_state(out_dir) or {}).get("settings")
        settings = merge_settings(args, stored)
        if not settings.photos:
            raise project.PhotoDriftError("--photos is needed on the first run")
        duration_given = bool(args.duration or args.start or args.end or args.auto_duration)
        s = project.run(settings, out_dir, reset_order=args.reset_order,
                        reset_positions=args.reset_positions, duration_given=duration_given)
    except (project.PhotoDriftError, ValueError, OSError) as e:
        print("photodrift: error: %s" % e, file=sys.stderr)
        return 1

    print("Title clip: %s" % s["title"])
    print("Cards: %d (%d rendered now)%s" % (
        s["cards"], s["rendered"], ", %d left out in order.txt" % len(s["excluded"]) if s["excluded"] else ""))
    if s["added"]:
        print("New photos: %s" % ", ".join(s["added"]))
    if s["dropped"]:
        print("Photos no longer found: %s" % ", ".join(s["dropped"]))
    if s["kept_manual"]:
        print("Kept changes made in Kdenlive for %d card(s)" % s["kept_manual"])
    print("Duration: %d frames = %.2f s at %g fps (%s)" % (
        s["frames"], s["seconds"], settings.fps, s["duration_source"]))
    print("Scroll speed: %.2f px/frame; each card is visible about %.1f s" % (
        s["px_per_frame"], s["card_visible_s"]))
    if s["card_visible_s"] < 3.0:
        print("Note: cards move fast. Use a longer duration (--start/--end or --duration) "
              "or fewer photos.")
    if s["backup"]:
        print("Previous title saved as %s" % s["backup"])
    st = s["strip"]
    if st:
        print("")
        print("Strip: %s (%dx%d)" % (st["path"], st["size"][0], st["size"][1]))
        if st["preset_file"]:
            print("Transform preset \"%s\" written to %s" % (st["preset_name"], st["preset_file"]))
        print("Transform rect: %s" % st["rect"])
        if st["rect_changed"]:
            print("The strip changed size or travel: choose the preset again on the strip clip in Kdenlive.")
        if st["too_big"]:
            print("WARNING: the strip is too tall for Qt to load (over 256 MB as an image). "
                  "Use fewer photos, a smaller --card-width or --spacing.")
        if st["other_items"]:
            print("Note: %d item(s) added in the title editor (text etc.) are only in the title clip, "
                  "not in the strip." % st["other_items"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
