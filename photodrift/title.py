"""Reading and writing Kdenlive title clips (.kdenlivetitle).

The format, as written by Kdenlive (src/titler/titledocument.cpp) and read
by MLT's kdenlivetitle producer (src/modules/qt/kdenlivetitle_wrapper.cpp):

    <kdenlivetitle width="1920" height="1080" LC_NUMERIC="C" duration="250" out="250">
     <item type="QGraphicsPixmapItem" z-index="1">
      <position x="100" y="200">
       <transform zoom="100" rotation="0,0,5">m11,m12,m13,m21,m22,m23,m31,m32,m33</transform>
      </position>
      <content url="cards/a.png"/>
     </item>
     <startviewport rect="0,0,1920,1080"/>
     <endviewport rect="0,5000,1920,1080"/>
     <background color="0,0,0,0"/>
    </kdenlivetitle>

Facts this module relies on:
- The item is drawn at ``position`` with the QTransform applied around the
  item's own top-left corner (Kdenlive's editor builds it as
  scale(zoom) then rotate(z) with no translation).
- QTransform maps a point (x, y) to (x*m11 + y*m21 + m31, x*m12 + y*m22 + m32).
- A relative ``url`` is resolved against the folder of the title file.
  When Kdenlive saves the title, the url becomes absolute.
- The viewport moves linearly from start to end over ``out`` frames.
  After that the end viewport is shown.
"""

import copy
import math
import os
import xml.etree.ElementTree as ET


def fmt(v):
    """Short, locale-independent number for the XML."""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = "%.6f" % v
    return s.rstrip("0").rstrip(".")


def transform_matrix(zoom_percent, rotation_deg):
    """(m11, m12, m21, m22) for Kdenlive's scale-then-rotate transform."""
    s = zoom_percent / 100.0
    a = math.radians(rotation_deg)
    c, n = math.cos(a), math.sin(a)
    return (s * c, s * n, -s * n, s * c)


def map_point(m, x, y):
    m11, m12, m21, m22 = m
    return (x * m11 + y * m21, x * m12 + y * m22)


def center_to_pos(center, image_size, zoom_percent, rotation_deg):
    """Item position that puts the centre of an image of ``image_size`` at ``center``."""
    m = transform_matrix(zoom_percent, rotation_deg)
    dx, dy = map_point(m, image_size[0] / 2.0, image_size[1] / 2.0)
    return (center[0] - dx, center[1] - dy)


def pos_to_center(pos, image_size, matrix):
    dx, dy = map_point(matrix, image_size[0] / 2.0, image_size[1] / 2.0)
    return (pos[0] + dx, pos[1] + dy)


def matrix_zoom_rotation(matrix):
    """Decompose (m11, m12, m21, m22) into (zoom percent, rotation degrees)."""
    m11, m12, _, _ = matrix
    return (math.hypot(m11, m12) * 100.0, math.degrees(math.atan2(m12, m11)))


def parse_rect(s):
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bad rect %r" % s)
    return tuple(parts)


class TitleItem:
    """A pixmap item read from a title file."""

    def __init__(self, url, pos, matrix, z):
        self.url = url
        self.pos = pos
        self.matrix = matrix
        self.z = z

    @property
    def basename(self):
        return os.path.basename(self.url.replace("\\", "/"))


class TitleDocument:
    """The parts of a title file PhotoDrift cares about.

    ``pixmaps`` are the image items; ``other_items`` are every other item
    (text, rectangles...) kept as XML elements so that a rewrite does not
    lose things the user added in Kdenlive's title editor.
    """

    def __init__(self):
        self.width = 1920
        self.height = 1080
        self.duration = None
        self.pixmaps = []
        self.other_items = []
        self.start_viewport = None
        self.end_viewport = None
        self.background = "0,0,0,0"


def read_title(path):
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "kdenlivetitle":
        raise ValueError("%s is not a Kdenlive title file" % path)
    doc = TitleDocument()
    doc.width = int(float(root.get("width", "1920")))
    doc.height = int(float(root.get("height", "1080")))
    dur = root.get("duration") or root.get("out")
    doc.duration = int(float(dur)) if dur else None
    for el in root:
        if el.tag == "item":
            if el.get("type") == "QGraphicsPixmapItem":
                pos_el = el.find("position")
                tr_el = pos_el.find("transform") if pos_el is not None else None
                content = el.find("content")
                url = content.get("url", "") if content is not None else ""
                pos = (float(pos_el.get("x", "0")), float(pos_el.get("y", "0"))) if pos_el is not None else (0.0, 0.0)
                matrix = (1.0, 0.0, 0.0, 1.0)
                if tr_el is not None and tr_el.text:
                    vals = [float(v) for v in tr_el.text.split(",")]
                    if len(vals) >= 9:
                        matrix = (vals[0], vals[1], vals[3], vals[4])
                        if abs(vals[6]) > 1e-9 or abs(vals[7]) > 1e-9:
                            # A translation part: fold it into the position.
                            pos = (pos[0] + vals[6], pos[1] + vals[7])
                z = int(float(el.get("z-index", "0")))
                doc.pixmaps.append(TitleItem(url, pos, matrix, z))
            else:
                doc.other_items.append(copy.deepcopy(el))
        elif el.tag == "startviewport" and el.get("rect"):
            doc.start_viewport = parse_rect(el.get("rect"))
        elif el.tag == "endviewport" and el.get("rect"):
            doc.end_viewport = parse_rect(el.get("rect"))
        elif el.tag == "background":
            doc.background = el.get("color", doc.background)
    return doc


class CardPlacement:
    """One card as it is written to the title."""

    def __init__(self, url, image_size, center, zoom, rotation, z):
        self.url = url
        self.image_size = image_size
        self.center = center
        self.zoom = zoom
        self.rotation = rotation
        self.z = z


def build_title_xml(width, height, duration, placements, start_viewport, end_viewport,
                    other_items=(), background="0,0,0,0"):
    root = ET.Element("kdenlivetitle", {
        "width": str(int(width)),
        "height": str(int(height)),
        "LC_NUMERIC": "C",
        "duration": str(int(duration)),
        "out": str(int(duration)),
    })
    for p in placements:
        item = ET.SubElement(root, "item", {"type": "QGraphicsPixmapItem", "z-index": str(int(p.z))})
        x, y = center_to_pos(p.center, p.image_size, p.zoom, p.rotation)
        pos = ET.SubElement(item, "position", {"x": fmt(x), "y": fmt(y)})
        m11, m12, m21, m22 = transform_matrix(p.zoom, p.rotation)
        tr = ET.SubElement(pos, "transform", {
            "zoom": str(int(round(p.zoom))),
            "rotation": "0,0,%s" % fmt(p.rotation),
        })
        tr.text = ",".join(fmt(v) for v in (m11, m12, 0, m21, m22, 0, 0, 0, 1))
        ET.SubElement(item, "content", {"url": p.url})
    for el in other_items:
        root.append(copy.deepcopy(el))
    ET.SubElement(root, "startviewport", {"rect": ",".join(fmt(v) for v in start_viewport)})
    ET.SubElement(root, "endviewport", {"rect": ",".join(fmt(v) for v in end_viewport)})
    ET.SubElement(root, "background", {"color": background})
    ET.indent(root, space=" ")
    return ET.tostring(root, encoding="unicode") + "\n"


def write_title(path, *args, **kwargs):
    text = build_title_xml(*args, **kwargs)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return text
