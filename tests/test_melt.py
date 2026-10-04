"""Render a generated title with MLT's own kdenlivetitle producer (the one Kdenlive uses).

Skipped when melt is not installed or there is no X11 display (MLT's Qt
module needs one; use xvfb-run on a server).
"""

import io
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np
from PIL import Image

from helpers import small_photos, copy_photos
from photodrift import cli, project
import melt_preview

HAVE_MELT = shutil.which("melt") is not None and bool(os.environ.get("DISPLAY"))


@unittest.skipUnless(HAVE_MELT, "melt or DISPLAY not available")
class MeltRenderTests(unittest.TestCase):
    def test_cards_rise(self):
        photos = copy_photos(small_photos(), names={"IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg"})
        out = tempfile.mkdtemp(prefix="pd-melt-")
        try:
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["--photos", photos, "--out", out, "--size", "640x360", "--duration", "4"])
            self.assertEqual(rc, 0)
            title_path = os.path.join(out, project.TITLE_NAME)
            frames = 100
            mlt = os.path.join(out, "test.mlt")
            with open(mlt, "w") as f:
                f.write(melt_preview.build_mlt(title_path, frames, 320, 180, 25, "#000000"))
            pattern = os.path.join(out, "f-%03d.png")
            res = subprocess.run(["melt", "-silent", mlt, "-consumer", "avformat:" + pattern, "vcodec=png"],
                                 capture_output=True, text=True, timeout=300)
            self.assertNotIn("X11", res.stdout + res.stderr)

            def frame(n):  # melt numbers image files from 1
                return np.asarray(Image.open(pattern % (n + 1)).convert("L"), np.float32)

            # First frame: nothing yet (cards start below the frame). Last frame: everything gone.
            self.assertLess(frame(0).max(), 10)
            self.assertLess(frame(frames - 1).max(), 10)
            # Middle: cards visible, and they move up between two frames.
            a, b = frame(40), frame(44)
            self.assertGreater(a.max(), 150)
            # Find the vertical shift that best maps frame a onto frame b: b(y) == a(y + shift).
            errors = {}
            for shift in range(-20, 21):
                if shift >= 0:
                    d = b[:b.shape[0] - shift] - a[shift:]
                else:
                    d = b[-shift:] - a[:a.shape[0] + shift]
                errors[shift] = float(np.abs(d).mean())
            best = min(errors, key=errors.get)
            self.assertGreater(best, 0, "cards should move up")
        finally:
            shutil.rmtree(out, ignore_errors=True)
            shutil.rmtree(photos, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
