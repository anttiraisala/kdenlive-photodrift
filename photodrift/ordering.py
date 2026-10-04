"""Finding photos and deciding their order.

The order is kept in a plain text file (``order.txt`` in the output folder),
one photo per line, relative to the photo folder. The user can edit it:

- move lines to change the order,
- put ``#`` in front of a line to leave that photo out.

New photos (not yet in the file) are added at the end, sorted by the sort
key. Photos that no longer exist are dropped from the file.
"""

import datetime
import os
import re

from PIL import Image

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}

ORDER_HEADER = """\
# PhotoDrift card order. One photo per line, top line = first card.
# - Move lines to change the order.
# - Put '#' in front of a photo to leave it out.
# New photos are added to the end when photodrift.py is run again.
"""

EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132


def natural_key(s):
    """Sort key that orders 'IMG_2' before 'IMG_10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def find_photos(folder, recursive=False):
    """Relative paths (with '/' separators) of photos in ``folder``."""
    found = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in filenames:
                if os.path.splitext(name)[1].lower() in PHOTO_EXTENSIONS and not name.startswith("."):
                    rel = os.path.relpath(os.path.join(dirpath, name), folder)
                    found.append(rel.replace(os.sep, "/"))
    else:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and os.path.splitext(name)[1].lower() in PHOTO_EXTENSIONS \
                    and not name.startswith("."):
                found.append(name)
    return found


def photo_date(path):
    """EXIF DateTimeOriginal, else EXIF DateTime, else file modification time."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            value = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(EXIF_DATETIME)
            if value:
                return datetime.datetime.strptime(str(value).strip(), "%Y:%m:%d %H:%M:%S")
    except (OSError, ValueError):
        pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def sort_photos(rel_paths, folder, sort):
    if sort == "name":
        return sorted(rel_paths, key=natural_key)
    if sort == "date":
        return sorted(rel_paths, key=lambda p: (photo_date(os.path.join(folder, p)), natural_key(p)))
    if sort == "mtime":
        return sorted(rel_paths, key=lambda p: (os.path.getmtime(os.path.join(folder, p)), natural_key(p)))
    raise ValueError("unknown sort %r (use name, date or mtime)" % sort)


def read_order_file(path):
    """Return (ordered list, excluded set) from an order file."""
    order, excluded = [], set()
    if not os.path.exists(path):
        return order, excluded
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                # A commented photo name means "leave it out"; other comments are ignored.
                name = line.lstrip("#").strip()
                if name and os.path.splitext(name)[1].lower() in PHOTO_EXTENSIONS:
                    excluded.add(name)
                continue
            if line not in order:
                order.append(line)
    return order, excluded


def write_order_file(path, order, excluded):
    with open(path, "w", encoding="utf-8") as f:
        f.write(ORDER_HEADER)
        for name in order:
            f.write(name + "\n")
        for name in sorted(excluded, key=natural_key):
            f.write("# " + name + "\n")


def resolve_order(folder, order_path, sort="name", recursive=False, reset=False):
    """Decide the card order and update the order file.

    Returns (ordered photos, excluded photos, added, dropped).
    """
    photos = find_photos(folder, recursive)
    available = set(photos)
    old_order, old_excluded = ([], set()) if reset else read_order_file(order_path)
    order = [p for p in old_order if p in available and p not in old_excluded]
    excluded = {p for p in old_excluded if p in available}
    known = set(order) | excluded
    added = sort_photos([p for p in photos if p not in known], folder, sort)
    order.extend(added)
    dropped = [p for p in old_order + sorted(old_excluded) if p not in available]
    write_order_file(order_path, order, excluded)
    return order, sorted(excluded, key=natural_key), added, dropped
