import json
import os
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from helpers import small_photos, copy_photos
from photodrift import cards, strip, title


class StripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pd-strip-")
        photo = cards.load_photo(os.path.join(small_photos(), "IMG_0001.jpg"))
        card = cards.render_card("instant", photo, 200, {}, 5)
        cls.card_path = os.path.join(cls.tmp, "card.png")
        card.image.save(cls.card_path)
        cls.card_size = card.image.size

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def placement(self, center, rotation=0.0, zoom=100.0, z=1):
        return title.CardPlacement(self.card_path, self.card_size, center, zoom, rotation, z)

    def test_render_matches_placements(self):
        ps = [self.placement((300, 1300)), self.placement((900, 1800), rotation=20, z=2)]
        path = os.path.join(self.tmp, "strip.png")
        top, height = strip.render_strip(ps, 1280, path)
        img = Image.open(path)
        self.assertEqual(img.size, (1280, height))
        self.assertEqual(img.mode, "RGBA")
        b0 = strip.card_bounds(ps[0])
        b1 = strip.card_bounds(ps[1])
        self.assertEqual(top, int(np.floor(b0[1])))
        self.assertEqual(top + height, int(np.ceil(b1[3])))
        a = np.asarray(img)[..., 3]
        # Opaque at both card centres, transparent between the cards on the right of card 1.
        self.assertEqual(a[1300 - top, 300], 255)
        self.assertEqual(a[1800 - top, 900], 255)
        self.assertEqual(a[1300 - top, 1250], 0)
        # The same card unrotated is identical to the card image (no resampling blur).
        card = np.asarray(Image.open(self.card_path))
        x0 = int(300 - self.card_size[0] / 2)
        y0 = int(1300 - self.card_size[1] / 2) - top
        patch = np.asarray(img)[y0:y0 + self.card_size[1], x0:x0 + self.card_size[0]]
        diff = np.abs(patch[..., 3].astype(int) - card[..., 3].astype(int))
        self.assertLessEqual(diff.max(), 2)

    def test_cards_outside_frame_are_clipped(self):
        ps = [self.placement((-50, 1300)), self.placement((1300, 1600))]
        path = os.path.join(self.tmp, "strip2.png")
        top, height = strip.render_strip(ps, 1280, path)
        self.assertEqual(Image.open(path).size[0], 1280)

    def test_transform_rect(self):
        rect = strip.transform_rect(1920, 1080, 1080, 5400, 7000)
        self.assertEqual(rect, "0=0% 100% 100% 500% 1;-1=0% -548.148148% 100% 500% 1")

    def test_preset_file_merge(self):
        kd = os.path.join(self.tmp, "kd")
        pdir = os.path.join(kd, "effects", "presets")
        os.makedirs(pdir)
        path = os.path.join(pdir, "qtblend.json")
        mine = [{"My zoom": [{"name": "rect", "value": "0 0 100 100 1"}]}]
        with open(path, "w") as f:
            json.dump(mine, f)
        strip.write_kdenlive_preset(kd, "PhotoDrift a", strip.preset_params("R1"))
        strip.write_kdenlive_preset(kd, "PhotoDrift b", strip.preset_params("R2"))
        strip.write_kdenlive_preset(kd, "PhotoDrift a", strip.preset_params("R3"))
        with open(path) as f:
            data = json.load(f)
        names = [k for e in data for k in e]
        self.assertEqual(names, ["My zoom", "PhotoDrift b", "PhotoDrift a"])
        a = [e["PhotoDrift a"] for e in data if "PhotoDrift a" in e][0]
        self.assertEqual(a[0], {"name": "rect", "value": "R3"})
        self.assertTrue(os.path.exists(path + ".bak"))

    def test_preset_file_object_form_and_new_file(self):
        kd = os.path.join(self.tmp, "kd2")
        path = strip.write_kdenlive_preset(kd, "PhotoDrift x", strip.preset_params("R"))
        with open(path) as f:
            self.assertEqual(list(json.load(f)[0]), ["PhotoDrift x"])
        with open(path, "w") as f:
            json.dump({"Old": [{"name": "rect", "value": "1"}]}, f)
        strip.write_kdenlive_preset(kd, "PhotoDrift x", strip.preset_params("R"))
        with open(path) as f:
            self.assertEqual([k for e in json.load(f) for k in e], ["Old", "PhotoDrift x"])


class StripProjectTests(unittest.TestCase):
    def test_run_writes_strip_and_preset(self):
        import io
        from contextlib import redirect_stdout
        from photodrift import cli
        photos = copy_photos(small_photos(), names={"IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg"})
        out = tempfile.mkdtemp(prefix="pd-out-")
        kd = tempfile.mkdtemp(prefix="pd-kd-")
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["--photos", photos, "--out", out, "--kdenlive-dir", kd])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
            self.assertIn('Transform preset "PhotoDrift %s"' % os.path.basename(out), text)
            self.assertNotIn("choose the preset again", text)
            self.assertTrue(os.path.exists(os.path.join(out, strip.STRIP_NAME)))
            self.assertTrue(os.path.exists(os.path.join(kd, "effects", "presets", "qtblend.json")))
            # Second run with a change in spacing: the rect changes, the user is told.
            buf = io.StringIO()
            with redirect_stdout(buf):
                cli.main(["--out", out, "--spacing", "0.7"])
            self.assertIn("choose the preset again", buf.getvalue())
            # --no-strip
            os.remove(os.path.join(out, strip.STRIP_NAME))
            with redirect_stdout(io.StringIO()):
                cli.main(["--out", out, "--no-strip"])
            self.assertFalse(os.path.exists(os.path.join(out, strip.STRIP_NAME)))
        finally:
            for d in (photos, out, kd):
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
