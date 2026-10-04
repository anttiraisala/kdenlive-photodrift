import math
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

import helpers  # noqa: F401  (sets sys.path)
from photodrift import title


class TitleTests(unittest.TestCase):
    def test_center_roundtrip(self):
        for zoom in (100, 50, 73):
            for rot in (0, 4.5, -7, 90):
                pos = title.center_to_pos((500, 2000), (300, 400), zoom, rot)
                m = title.transform_matrix(zoom, rot)
                c = title.pos_to_center(pos, (300, 400), m)
                self.assertAlmostEqual(c[0], 500, places=6)
                self.assertAlmostEqual(c[1], 2000, places=6)
                z, r = title.matrix_zoom_rotation(m)
                self.assertAlmostEqual(z, zoom, places=6)
                self.assertAlmostEqual(r, rot, places=6)

    def test_matrix_matches_qt_rotation(self):
        # QTransform::rotate(a) gives m11=cos, m12=sin, m21=-sin, m22=cos.
        m = title.transform_matrix(100, 30)
        self.assertAlmostEqual(m[0], math.cos(math.radians(30)))
        self.assertAlmostEqual(m[1], math.sin(math.radians(30)))
        self.assertAlmostEqual(m[2], -math.sin(math.radians(30)))

    def test_write_and_read(self):
        placements = [
            title.CardPlacement("/x/cards/a-00000001.png", (300, 400), (480, 1300), 100, 3.5, 1),
            title.CardPlacement("/x/cards/b-00000002.png", (300, 400), (1440, 1840), 50, -2, 2),
        ]
        text = title.build_title_xml(1920, 1080, 500, placements, (0, 0, 1920, 1080), (0, 3000, 1920, 1080))
        root = ET.fromstring(text)
        self.assertEqual(root.tag, "kdenlivetitle")
        self.assertEqual(root.get("LC_NUMERIC"), "C")
        self.assertEqual(root.get("duration"), "500")
        self.assertEqual(root.get("out"), "500")
        items = root.findall("item")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].get("type"), "QGraphicsPixmapItem")
        tr = items[0].find("position/transform")
        self.assertEqual(len(tr.text.split(",")), 9)
        self.assertEqual(tr.get("rotation"), "0,0,3.5")
        self.assertEqual(items[1].find("position/transform").get("zoom"), "50")
        self.assertEqual(root.find("startviewport").get("rect"), "0,0,1920,1080")
        self.assertEqual(root.find("endviewport").get("rect"), "0,3000,1920,1080")
        self.assertEqual(root.find("background").get("color"), "0,0,0,0")

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.kdenlivetitle")
            with open(path, "w") as f:
                f.write(text)
            doc = title.read_title(path)
        self.assertEqual((doc.width, doc.height, doc.duration), (1920, 1080, 500))
        self.assertEqual(len(doc.pixmaps), 2)
        c = title.pos_to_center(doc.pixmaps[1].pos, (300, 400), doc.pixmaps[1].matrix)
        self.assertAlmostEqual(c[0], 1440, places=3)
        self.assertAlmostEqual(c[1], 1840, places=3)
        self.assertEqual(doc.end_viewport, (0, 3000, 1920, 1080))

    def test_other_items_kept(self):
        text = """<kdenlivetitle width="1920" height="1080" duration="100">
 <item type="QGraphicsTextItem" z-index="5"><position x="1" y="2"><transform>1,0,0,0,1,0,0,0,1</transform></position>
 <content font="Sans">Hello</content></item>
 <startviewport rect="0,0,1920,1080"/><endviewport rect="0,10,1920,1080"/>
</kdenlivetitle>"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.kdenlivetitle")
            with open(path, "w") as f:
                f.write(text)
            doc = title.read_title(path)
        self.assertEqual(len(doc.other_items), 1)
        out = title.build_title_xml(1920, 1080, 100, [], (0, 0, 1920, 1080), (0, 10, 1920, 1080), doc.other_items)
        self.assertIn("Hello", out)

    def test_fmt(self):
        self.assertEqual(title.fmt(3.0), "3")
        self.assertEqual(title.fmt(0.1234567), "0.123457")
        self.assertEqual(title.fmt(-2.5), "-2.5")


if __name__ == "__main__":
    unittest.main()
