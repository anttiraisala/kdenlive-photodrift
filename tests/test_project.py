import io
import json
import math
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout

from helpers import small_photos, copy_photos
from photodrift import cli, project, title


def run_cli(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(list(args))
    return rc, buf.getvalue()


def load_state(out_dir):
    with open(os.path.join(out_dir, project.STATE_NAME), encoding="utf-8") as f:
        return json.load(f)


def card_centers(out_dir):
    """{card file basename: (center, rotation, zoom)} as stored in the title."""
    state = load_state(out_dir)
    sizes = {os.path.basename(e["file"]): e["png_size"] for e in state["cards"].values()}
    doc = title.read_title(os.path.join(out_dir, project.TITLE_NAME))
    result = {}
    for item in doc.pixmaps:
        z, r = title.matrix_zoom_rotation(item.matrix)
        result[item.basename] = (title.pos_to_center(item.pos, sizes[item.basename], item.matrix), r, z)
    return result


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def kdenlive_edit(path, edits, duration=None, add_text=False):
    """Change a title file the way Kdenlive's title editor would save it.

    edits: {basename: {"move": (dx, dy)} or {"rotate": degrees}}
    Rotation in Kdenlive's editor is around the item's top-left corner (no
    position change), like QGraphicsItem::setTransform().
    """
    tree = ET.parse(path)
    root = tree.getroot()
    for item in root.findall("item"):
        url = item.find("content").get("url")
        e = edits.get(os.path.basename(url))
        if not e:
            continue
        pos = item.find("position")
        if "move" in e:
            pos.set("x", str(float(pos.get("x")) + e["move"][0]))
            pos.set("y", str(float(pos.get("y")) + e["move"][1]))
        if "rotate" in e:
            tr = pos.find("transform")
            m = title.transform_matrix(100, e["rotate"])
            tr.text = "%f,%f,0,%f,%f,0,0,0,1" % m
            tr.set("rotation", "0,0,%g" % e["rotate"])
    if duration:
        root.set("duration", str(duration))
        root.set("out", str(duration))
    if add_text:
        ET.SubElement(root, "item", {"type": "QGraphicsTextItem", "z-index": "99"}).text = "Hello"
    tree.write(path)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.photos = copy_photos(small_photos(), names={"IMG_%04d.jpg" % i for i in range(1, 6)})
        self.out = tempfile.mkdtemp(prefix="pd-out-")

    def tearDown(self):
        shutil.rmtree(self.photos, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_first_run(self):
        rc, text = run_cli("--photos", self.photos, "--out", self.out, "--card-width", "0.2")
        self.assertEqual(rc, 0, text)
        doc = title.read_title(os.path.join(self.out, project.TITLE_NAME))
        self.assertEqual(len(doc.pixmaps), 5)
        self.assertEqual(doc.start_viewport, (0, 0, 1920, 1080))
        state = load_state(self.out)
        centers = card_centers(self.out)
        ordered = [os.path.basename(state["cards"]["IMG_%04d.jpg" % i]["file"]) for i in range(1, 6)]
        ys = [centers[n][0][1] for n in ordered]
        # Cards are below the frame, in order, and the last one ends before the end viewport.
        self.assertGreater(min(ys), 1080)
        self.assertEqual(ys, sorted(ys))
        self.assertGreater(doc.end_viewport[1], ys[-1])
        # Alternating sides.
        xs = [centers[n][0][0] for n in ordered]
        self.assertLess(xs[0], 960)
        self.assertGreater(xs[1], 960)
        for name in ordered:
            self.assertTrue(os.path.exists(os.path.join(self.out, "cards", name)))
        self.assertTrue(os.path.exists(os.path.join(self.out, "order.txt")))

    def test_rerun_without_changes_is_stable(self):
        run_cli("--photos", self.photos, "--out", self.out)
        path = os.path.join(self.out, project.TITLE_NAME)
        before = read(path)
        rc, text = run_cli("--out", self.out)
        self.assertEqual(rc, 0, text)
        self.assertIn("0 rendered now", text)
        self.assertEqual(read(path), before)
        self.assertFalse(os.path.exists(os.path.join(self.out, "backups")))

    def test_manual_changes_survive_rerun(self):
        run_cli("--photos", self.photos, "--out", self.out, "--duration", "20")
        state = load_state(self.out)
        name = {i: os.path.basename(state["cards"]["IMG_%04d.jpg" % i]["file"]) for i in range(1, 6)}
        path = os.path.join(self.out, project.TITLE_NAME)
        kdenlive_edit(path, {name[2]: {"move": (120, -40)}, name[3]: {"rotate": 12}},
                      duration=777, add_text=True)
        edited = card_centers(self.out)
        written3 = state["cards"]["IMG_0003.jpg"]["written"]["center"]

        # Reorder (swap 1 and 4), add a photo, change spacing.
        shutil.copy2(os.path.join(small_photos(), "IMG_0006.jpg"), self.photos)
        with open(os.path.join(self.out, "order.txt"), "w") as f:
            f.write("IMG_0004.jpg\nIMG_0002.jpg\nIMG_0003.jpg\nIMG_0001.jpg\nIMG_0005.jpg\n")
        rc, text = run_cli("--out", self.out, "--spacing", "0.6", "--auto-duration")
        self.assertEqual(rc, 0, text)
        self.assertIn("Kept changes made in Kdenlive for 2 card(s)", text)
        self.assertIn("New photos: IMG_0006.jpg", text)

        state = load_state(self.out)
        after = card_centers(self.out)
        self.assertEqual(len(after), 6)
        # Card 2: new automatic position + the manual move.
        auto2 = state["cards"]["IMG_0002.jpg"]["auto"]["center"]
        self.assertAlmostEqual(after[name[2]][0][0], auto2[0] + 120, places=2)
        self.assertAlmostEqual(after[name[2]][0][1], auto2[1] - 40, places=2)
        # Card 3: rotation kept. Rotating around the corner also moved its centre; that move is kept.
        self.assertAlmostEqual(after[name[3]][1], 12, places=3)
        auto3 = state["cards"]["IMG_0003.jpg"]["auto"]["center"]
        shift3 = (edited[name[3]][0][0] - written3[0], edited[name[3]][0][1] - written3[1])
        self.assertGreater(abs(shift3[0]) + abs(shift3[1]), 1.0)
        self.assertAlmostEqual(after[name[3]][0][0], auto3[0] + shift3[0], places=2)
        self.assertAlmostEqual(after[name[3]][0][1], auto3[1] + shift3[1], places=2)
        # Card 1 untouched: exactly at its new automatic position, with its automatic tilt.
        auto1 = state["cards"]["IMG_0001.jpg"]["auto"]
        self.assertAlmostEqual(after[name[1]][0][1], auto1["center"][1], places=2)
        self.assertAlmostEqual(after[name[1]][1], auto1["rotation"], places=3)
        # Order: card 4 is now first (topmost), card 1 fourth.
        self.assertLess(after[name[4]][0][1], after[name[1]][0][1])
        # --auto-duration was given; an explicit choice on the command line wins over Kdenlive.
        doc = title.read_title(path)
        self.assertNotEqual(doc.duration, 777)
        # The text item added in Kdenlive is still there.
        self.assertIn("Hello", read(path))
        # A backup of the previous title exists.
        self.assertEqual(len(os.listdir(os.path.join(self.out, "backups"))), 1)

    def test_duration_changed_in_kdenlive_is_kept(self):
        run_cli("--photos", self.photos, "--out", self.out)
        path = os.path.join(self.out, project.TITLE_NAME)
        kdenlive_edit(path, {}, duration=777)
        rc, text = run_cli("--out", self.out)
        self.assertEqual(rc, 0, text)
        self.assertIn("kept from Kdenlive", text)
        self.assertEqual(title.read_title(path).duration, 777)
        # An explicit duration overrides it.
        rc, text = run_cli("--out", self.out, "--start", "1:00", "--end", "1:30")
        self.assertEqual(title.read_title(path).duration, 750)

    def test_removed_photo_is_removed(self):
        run_cli("--photos", self.photos, "--out", self.out)
        state = load_state(self.out)
        gone = os.path.basename(state["cards"]["IMG_0003.jpg"]["file"])
        os.remove(os.path.join(self.photos, "IMG_0003.jpg"))
        rc, text = run_cli("--out", self.out)
        self.assertIn("Photos no longer found: IMG_0003.jpg", text)
        self.assertNotIn(gone, card_centers(self.out))
        self.assertFalse(os.path.exists(os.path.join(self.out, "cards", gone)))

    def test_reset_positions(self):
        run_cli("--photos", self.photos, "--out", self.out)
        state = load_state(self.out)
        n2 = os.path.basename(state["cards"]["IMG_0002.jpg"]["file"])
        kdenlive_edit(os.path.join(self.out, project.TITLE_NAME), {n2: {"move": (300, 0)}})
        run_cli("--out", self.out, "--reset-positions")
        state = load_state(self.out)
        auto = state["cards"]["IMG_0002.jpg"]["auto"]["center"]
        self.assertAlmostEqual(card_centers(self.out)[n2][0][0], auto[0], places=2)

    def test_style_change_rerenders_and_keeps_moves(self):
        run_cli("--photos", self.photos, "--out", self.out)
        state = load_state(self.out)
        n2 = os.path.basename(state["cards"]["IMG_0002.jpg"]["file"])
        kdenlive_edit(os.path.join(self.out, project.TITLE_NAME), {n2: {"move": (50, 70)}})
        rc, text = run_cli("--out", self.out, "--aperture", "1:1", "--card-width", "0.25")
        self.assertIn("5 rendered now", text)
        state = load_state(self.out)
        auto = state["cards"]["IMG_0002.jpg"]["auto"]["center"]
        c = card_centers(self.out)[n2][0]
        self.assertAlmostEqual(c[0], auto[0] + 50, places=2)
        self.assertAlmostEqual(c[1], auto[1] + 70, places=2)

    def test_parse_time(self):
        self.assertEqual(project.parse_time("90", 25), 90)
        self.assertEqual(project.parse_time("1:30", 25), 90)
        self.assertEqual(project.parse_time("0:01:30.5", 25), 90.5)
        self.assertEqual(project.parse_time("00:01:30:05", 25), 90.2)
        with self.assertRaises(project.PhotoDriftError):
            project.parse_time("soon", 25)

    def test_errors(self):
        rc = cli.main(["--out", self.out])
        self.assertEqual(rc, 1)
        rc = cli.main(["--out", self.out, "--photos", "/nonexistent"])
        self.assertEqual(rc, 1)
        rc = cli.main(["--out", self.out, "--photos", self.photos, "--start", "10"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
