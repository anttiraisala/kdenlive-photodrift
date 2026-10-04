import os
import unittest

import numpy as np
from PIL import Image

from helpers import small_photos  # noqa: F401  (sets sys.path)
from photodrift import cards


class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = small_photos()
        cls.photo = cards.load_photo(os.path.join(folder, "IMG_0001.jpg"))

    def render(self, seed=7, **params):
        return cards.render_card("instant", self.photo, 300, params, seed)

    def test_size_and_alpha(self):
        c = self.render()
        img = c.image
        self.assertEqual(img.mode, "RGBA")
        cw, ch = c.card_size
        self.assertEqual(cw, 300)
        # 4:5 aperture: aperture width 300 - 2*18 = 264, height 330; borders 18 + 66.
        self.assertEqual(ch, 18 + 330 + 66)
        self.assertEqual(c.center, (img.size[0] / 2.0, img.size[1] / 2.0))
        a = np.asarray(img)[..., 3]
        # Transparent corners (padding), opaque middle.
        self.assertEqual(a[0, 0], 0)
        self.assertEqual(a[-1, -1], 0)
        self.assertEqual(a[a.shape[0] // 2, a.shape[1] // 2], 255)
        # Shadow: semi-transparent pixels exist below the card.
        cy_bottom = int(c.center[1] + ch / 2 + 3)
        self.assertTrue(0 < a[cy_bottom, a.shape[1] // 2] < 255)

    def test_reproducible(self):
        a = np.asarray(self.render(seed=11).image)
        b = np.asarray(self.render(seed=11).image)
        c = np.asarray(self.render(seed=12).image)
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(np.array_equal(a, c))

    def test_aperture_options(self):
        sq = self.render(aperture="1:1")
        self.assertEqual(sq.card_size[1], 18 + 264 + 66)
        native = self.render(aperture="native")
        w, h = self.photo.size
        expected = 18 + round(264 / max(0.5, min(2.0, w / h))) + 66
        self.assertEqual(native.card_size[1], expected)
        with self.assertRaises(ValueError):
            self.render(aperture="wide")

    def test_effects_off_gives_flat_card(self):
        c = self.render(curl=0, gloss=0, bump=0, shadow=0, film=0, vignette=0)
        a = np.asarray(c.image)
        pad = (a.shape[1] - 300) // 2
        # Without shadow everything outside the card is fully transparent.
        self.assertEqual(a[:pad - 1, :, 3].max(), 0)
        # Without curl the card is an axis-aligned rectangle of exactly card_size.
        rows = np.where(a[..., 3].max(axis=1) > 128)[0]
        self.assertEqual(rows[-1] - rows[0] + 1, c.card_size[1])

    def test_exif_orientation(self):
        folder = small_photos()
        # IMG_0004 is stored sideways with orientation 6; loading must make it upright (portrait or landscape
        # as painted). make_test_photos paints the label "UP WxH" with the upright size.
        raw = Image.open(os.path.join(folder, "IMG_0004.jpg"))
        upright = cards.load_photo(os.path.join(folder, "IMG_0004.jpg"))
        self.assertEqual(raw.size, (upright.size[1], upright.size[0]))

    def test_card_seed_stable(self):
        self.assertEqual(cards.card_seed(1, "a.jpg"), cards.card_seed(1, "a.jpg"))
        self.assertNotEqual(cards.card_seed(1, "a.jpg"), cards.card_seed(1, "b.jpg"))
        self.assertNotEqual(cards.card_seed(1, "a.jpg"), cards.card_seed(2, "a.jpg"))


if __name__ == "__main__":
    unittest.main()
